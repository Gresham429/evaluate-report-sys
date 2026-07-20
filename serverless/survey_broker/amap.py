"""高德地图 REST 客户端（serverless 侧）：逆地理 + 周边 POI，只出事实。

铁律 #7——距离/远近到"好中差"档次的映射是估价师的判断，broker 不做这层
翻译。`prefill_geo` 只把高德返回的事实（地址、公交站名、最近地铁及距离米数、
周边配套名）整理成扁平结构，喂给问卷预填；档次由估价师现场核对时自己定。

`transport` 可注入（同 `NotableClient` 的 Transport 契约思路），签名简化成
`(url) -> (status, text)`——高德是纯 GET+query，不需要 method/headers/body。
单测传假 transport，零网络；真机默认走 urllib。任何失败（网络错误、非 200、
JSON 解析失败、业务 status!="1"）都吞成"空事实"返回，不让一次地图查询失败
拖垮整份问卷预填。
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["AmapClient", "AmapTransport"]

_REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
_AROUND_URL = "https://restapi.amap.com/v3/place/around"

# transport 契约：给定拼好 query 的完整 url → (http_status, response_text)
AmapTransport = Callable[[str], tuple[int, str]]


def _make_urllib_transport(timeout: float) -> AmapTransport:
    """按超时秒数生成真实 transport：只访问固定的高德域名。"""

    def _transport(url: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310  仅高德域名
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            return 0, f"网络错误：{exc}"

    return _transport


def _empty_facts() -> dict[str, Any]:
    return {
        "address": "", "bus_stops": [], "nearest_metro": None, "facilities": [],
        "center": None,    # 最近政府/行政中心 {name, distance_m}——喂 重要场所/离城中心距离
        "highway": None,   # 最近高速口/收费站 {name, distance_m}——喂 离高速口距离
        "parking": None,   # 周边停车场 {count, nearest_m}——喂 附近停车场数量/停车便利度
        "water": None,     # 最近水库/河流/湖泊 {name, distance_m}——喂 离水源地距离（农用）
        "roads": [],       # 就近道路名——喂 道路通达度/临路状况/临街道路等级
    }


class AmapClient:
    """高德 REST 客户端：逆地理 + 周边 POI，喂问卷「地图预填」的地理事实。"""

    def __init__(
        self, key: str, *, transport: AmapTransport | None = None, timeout: float = 10.0
    ) -> None:
        self._key = key
        self._transport = transport or _make_urllib_transport(timeout)

    def _get(self, base_url: str, params: dict[str, str]) -> dict[str, Any] | None:
        """GET 一个高德接口。网络错误/非 200/JSON 坏/业务 status!="1" 都返回 None，不抛异常。"""
        query = dict(params)
        query["key"] = self._key
        url = f"{base_url}?{urllib.parse.urlencode(query)}"
        try:
            status, text = self._transport(url)
        except Exception:  # noqa: BLE001  任何 transport 异常都不该拖垮问卷预填
            logger.warning("高德接口请求异常：%s", base_url, exc_info=True)
            return None
        if status != 200:
            logger.warning("高德接口 HTTP%s：%s", status, base_url)
            return None
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            logger.warning("高德接口响应非 JSON：%s", base_url)
            return None
        if not isinstance(obj, dict) or str(obj.get("status")) != "1":
            logger.warning("高德接口业务失败：%s", base_url)
            return None
        return obj

    def prefill_geo(self, lng: float, lat: float) -> dict[str, Any]:
        """逆地理 + 周边 POI → 事实字典，任何一路失败都给该路的空值，不让预填崩掉。

        Returns:
            `{"address": str, "bus_stops": [名字...],
              "nearest_metro": {"name":..., "distance_m":...} | None,
              "facilities": [名字...]}`——只有事实，无档次判断（铁律 #7）。
        """
        location = f"{lng},{lat}"
        facts = _empty_facts()

        regeo = self._get(_REGEO_URL, {"location": location, "extensions": "all"})
        if regeo is not None:
            # 待真机校准：字段路径按高德逆地理编码文档的常见形状假定——
            #   regeocode.formatted_address / regeocode.roads[].name
            regeocode = regeo.get("regeocode") or {}
            facts["address"] = str(regeocode.get("formatted_address") or "")
            facts["roads"] = self._road_names(regeocode)

        around = self._get(_AROUND_URL, {"location": location, "radius": "1000"})
        if around is not None:
            facts.update(self._poi_facts(around))

        # 定向找最近：政府/行政中心、高速口、停车场、水源（各一次带 keywords 的周边检索）。
        facts["center"] = self._nearest(location, "政府", "5000")
        facts["highway"] = self._nearest(location, "高速", "5000")
        facts["parking"] = self._parking(location, "2000")
        facts["water"] = self._nearest(location, "水库|河流|湖泊", "5000")

        return facts

    def _around_pois(self, location: str, keywords: str, radius: str) -> list[dict[str, Any]]:
        """按关键字周边检索，按距离排序。任何失败回空列表（不拖垮预填）。
        # 待真机校准：keywords 检索 + sortrule=distance；pois[].name/.distance 字段路径。"""
        obj = self._get(
            _AROUND_URL,
            {"location": location, "keywords": keywords, "radius": radius, "sortrule": "distance"},
        )
        pois = (obj.get("pois") or []) if obj else []
        return [p for p in pois if isinstance(p, dict) and p.get("name")]

    def _nearest(self, location: str, keywords: str, radius: str) -> dict[str, Any] | None:
        """最近一条同类 POI → {name, distance_m}；无则 None。"""
        for poi in self._around_pois(location, keywords, radius):
            try:
                return {"name": str(poi.get("name")), "distance_m": float(poi.get("distance") or 0)}
            except (TypeError, ValueError):
                continue
        return None

    def _parking(self, location: str, radius: str) -> dict[str, Any] | None:
        """周边停车场 → {count, nearest_m}；无则 None。"""
        pois = self._around_pois(location, "停车场", radius)
        if not pois:
            return None
        try:
            nearest: float | None = float(pois[0].get("distance") or 0)
        except (TypeError, ValueError):
            nearest = None
        return {"count": len(pois), "nearest_m": nearest}

    @staticmethod
    def _road_names(regeocode: dict[str, Any]) -> list[str]:
        """逆地理 regeocode.roads[].name → 就近几条路名（去重、最多 4 条）。"""
        out: list[str] = []
        for road in regeocode.get("roads") or []:
            if isinstance(road, dict) and road.get("name"):
                name = str(road["name"])
                if name not in out:
                    out.append(name)
        return out[:4]

    @staticmethod
    def _poi_facts(around: dict[str, Any]) -> dict[str, Any]:
        """周边搜索响应 → bus_stops / nearest_metro / facilities（新 dict，不改入参）。

        真机已校准（2026-07-19 打杭州东站）：高德实际的名字/类型是「XX公交车站」
        「地铁E口(1/4号线)」「交通设施服务;地铁站」这类，故关键字放宽到「公交」「地铁」
        才抓得住（卡死成「公交站/地铁站」会把地铁口漏进 facilities）。字段路径
        pois[].name / .type / .distance（米，字符串）实测无误。
        """
        pois = around.get("pois") or []
        bus_stops: list[str] = []
        facilities: list[str] = []
        nearest_metro: dict[str, Any] | None = None
        nearest_distance: float | None = None
        for poi in pois:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or "")
            poi_type = str(poi.get("type") or "")
            if not name:
                continue
            if "公交" in poi_type or "公交" in name:
                bus_stops.append(name)
                continue
            if "地铁" in poi_type or "地铁" in name:
                try:
                    distance = float(poi.get("distance") or 0)
                except (TypeError, ValueError):
                    # 距离解析不出也别把这个地铁站事实丢了——退回 facilities 让估价师看到
                    facilities.append(name)
                    continue
                if nearest_distance is None or distance < nearest_distance:
                    nearest_distance = distance
                    nearest_metro = {"name": name, "distance_m": distance}
                continue
            facilities.append(name)
        return {"bus_stops": bus_stops, "facilities": facilities, "nearest_metro": nearest_metro}
