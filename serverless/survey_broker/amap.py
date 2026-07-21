"""高德地图 REST 客户端（serverless 侧）：逆地理 + 定向周边检索，只出事实。

铁律 #7——距离/远近到"好中差"档次的映射是估价师的判断，broker 不做这层翻译。
`prefill_geo` 把高德返回的事实（地址、就近道路、最近公交/地铁/政府中心/高速口/停车场/
水库、周边配套名）整理成扁平结构喂问卷预填；档次由估价师现场核对时自己定。

**关键字/半径经真机(钱江新城 120.21,30.25)校准**（2026-07-21）：
- 公交/地铁/政府中心/停车场/高速口 走**定向 keywords 检索**（通用周边在密集商圈会把
  公交地铁挤出前 20 条）；水源用「水库」（河/江不是点 POI、按名字模糊匹配会命中饭店）。
- 高德个人 key **并发 QPS 低**：连打多次会 `CUQPS_HAS_EXCEEDED_THE_LIMIT`(10021)，故
  各周边调用间**节流** `pace` 秒，且 `_get` 遇限流**退避重试一次**。

`transport` 可注入（`(url) -> (status, text)`）；单测传假 transport + `pace=0`，零网络零等待。
任何一路失败都给该路空值，不让一次地图查询拖垮整份预填。
"""

import json
import logging
import time
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
        "center": None,    # 最近市/区政府·管委会 {name, distance_m}——喂 重要场所/离城中心距离
        "highway": None,   # 最近高速收费站 {name, distance_m}——喂 离高速口距离
        "parking": None,   # 周边停车场 {count, nearest_m}——喂 附近停车场数量/停车便利度
        "water": None,     # 最近水库 {name, distance_m}——喂 离水源地距离（农用）
        "roads": [],       # 就近道路名——喂 道路通达度/临路状况/临街道路等级
    }


class AmapClient:
    """高德 REST 客户端：逆地理 + 定向周边检索，喂问卷「地图预填」的地理事实。"""

    def __init__(
        self,
        key: str,
        *,
        transport: AmapTransport | None = None,
        timeout: float = 10.0,
        pace: float = 0.4,
    ) -> None:
        self._key = key
        self._transport = transport or _make_urllib_transport(timeout)
        self._pace = pace   # 各周边调用间隔秒，压住高德个人 key 的并发 QPS 限制

    def _get(self, base_url: str, params: dict[str, str]) -> dict[str, Any] | None:
        """GET 一个高德接口；限流(10021/CUQPS)退避重试一次，其余失败一律 None，不抛异常。"""
        query = dict(params)
        query["key"] = self._key
        url = f"{base_url}?{urllib.parse.urlencode(query)}"
        for attempt in range(2):
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
            if not isinstance(obj, dict):
                return None
            if str(obj.get("status")) == "1":
                return obj
            info = str(obj.get("info") or "")
            code = str(obj.get("infocode") or "")
            if attempt == 0 and (code == "10021" or "CUQPS" in info):
                if self._pace:
                    time.sleep(self._pace + 0.3)   # 限流：多退避一点再重试
                continue
            logger.warning("高德接口业务失败：%s info=%s", base_url, info)
            return None
        return None

    def prefill_geo(self, lng: float, lat: float) -> dict[str, Any]:
        """逆地理 + 定向周边 → 事实字典，任何一路失败都给该路空值。只有事实、无档次判断（#7）。

        Returns:
            `{address, bus_stops:[名], nearest_metro:{name,distance_m}|None, facilities:[名],
              center/highway/water:{name,distance_m}|None, parking:{count,nearest_m}|None,
              roads:[路名]}`。
        """
        location = f"{lng},{lat}"
        facts = _empty_facts()

        regeo = self._get(_REGEO_URL, {"location": location, "extensions": "all"})
        if regeo is not None:
            # 待真机校准：regeocode.formatted_address / regeocode.roads[].name（已真机确认可用）
            regeocode = regeo.get("regeocode") or {}
            facts["address"] = str(regeocode.get("formatted_address") or "")
            facts["roads"] = self._road_names(regeocode)

        facts["bus_stops"] = self._around_names(location, "公交车站", "1000", 8)
        facts["nearest_metro"] = self._nearest(location, "地铁站", "2000")
        facts["facilities"] = self._around_names(location, "学校|医院|幼儿园", "1500", 6)
        facts["center"] = self._nearest(location, "市政府|区政府|管委会", "5000")
        facts["highway"] = self._nearest(location, "收费站", "15000")
        facts["parking"] = self._parking(location, "停车场", "2000")
        facts["water"] = self._nearest(location, "水库", "8000")
        return facts

    def _around_pois(self, location: str, keywords: str, radius: str) -> list[dict[str, Any]]:
        """按关键字周边检索（按距离排序）。调用前节流；任何失败回空列表。"""
        if self._pace:
            time.sleep(self._pace)
        obj = self._get(
            _AROUND_URL,
            {"location": location, "keywords": keywords, "radius": radius, "sortrule": "distance"},
        )
        pois = (obj.get("pois") or []) if obj else []
        return [p for p in pois if isinstance(p, dict) and p.get("name")]

    def _around_names(self, location: str, keywords: str, radius: str, limit: int) -> list[str]:
        """就近若干条同类 POI 的名字（去重、最多 limit 条）。"""
        out: list[str] = []
        for poi in self._around_pois(location, keywords, radius):
            name = str(poi.get("name") or "")
            if name and name not in out:
                out.append(name)
            if len(out) >= limit:
                break
        return out

    def _nearest(self, location: str, keywords: str, radius: str) -> dict[str, Any] | None:
        """最近一条同类 POI → {name, distance_m}；无则 None。"""
        for poi in self._around_pois(location, keywords, radius):
            try:
                return {"name": str(poi.get("name")), "distance_m": float(poi.get("distance") or 0)}
            except (TypeError, ValueError):
                continue
        return None

    def _parking(self, location: str, keywords: str, radius: str) -> dict[str, Any] | None:
        """周边停车场 → {count, nearest_m}；无则 None。"""
        pois = self._around_pois(location, keywords, radius)
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
