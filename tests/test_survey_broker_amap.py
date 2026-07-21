"""AmapClient 单测：假 transport 灌 canned 高德 JSON，零网络；`pace=0` 免节流等待。

关键字/半径/限流重试经真机(钱江新城)校准，见 amap.py 顶部说明。canned 字段路径与
amap.py 的解析一一对应，真机再校准时两边一起改。
"""

import json
import urllib.parse
from typing import Any

from serverless.survey_broker.amap import AmapClient

# prefill_geo 失败/空时的规范返回形状（与 amap._empty_facts 对齐）
_EMPTY = {
    "address": "", "bus_stops": [], "nearest_metro": None, "facilities": [],
    "center": None, "highway": None, "parking": None, "water": None, "roads": [],
}


def _client(transport: Any) -> AmapClient:
    return AmapClient("test-key", transport=transport, pace=0)   # pace=0：测试不 sleep


def _regeo(address: str, roads: list[str] | None = None) -> str:
    regeocode: dict[str, Any] = {"formatted_address": address}
    if roads is not None:
        regeocode["roads"] = [{"name": r} for r in roads]
    return json.dumps({"status": "1", "regeocode": regeocode})


def _around(pois: list[dict[str, Any]]) -> str:
    return json.dumps({"status": "1", "pois": pois})


def _rate_limited() -> str:
    return json.dumps({"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10021"})


def test_prefill_geo_parses_all_facts_from_canned_response() -> None:
    calls: list[str] = []

    def transport(url: str) -> tuple[int, str]:
        calls.append(url)
        dec = urllib.parse.unquote(url)   # keywords 里的中文是百分号编码
        if "regeo" in url:
            return 200, _regeo("浙江省杭州市上城区某路", roads=["钱江路", "新业路"])
        if "公交车站" in dec:
            return 200, _around([{"name": "来福士(公交站)", "distance": "80"},
                                 {"name": "市民中心(公交站)", "distance": "120"}])
        if "地铁站" in dec:
            return 200, _around([{"name": "新业路(地铁站)", "distance": "145"}])
        if "学校" in dec:
            return 200, _around([{"name": "某幼儿园", "distance": "200"},
                                 {"name": "某医院", "distance": "260"}])
        if "市政府" in dec:
            return 200, _around([{"name": "杭州市人民政府", "distance": "382"}])
        if "收费站" in dec:
            return 200, _around([{"name": "杭州收费站(S2杭甬高速)", "distance": "9887"}])
        if "停车场" in dec:
            return 200, _around([{"name": "P1停车场", "distance": "118"},
                                 {"name": "P2停车场", "distance": "200"}])
        if "水库" in dec:
            return 200, _around([{"name": "青山水库", "distance": "800"}])
        return 200, _around([])

    facts = _client(transport).prefill_geo(120.21, 30.25)
    assert facts["address"] == "浙江省杭州市上城区某路"
    assert facts["roads"] == ["钱江路", "新业路"]
    assert facts["bus_stops"] == ["来福士(公交站)", "市民中心(公交站)"]
    assert facts["nearest_metro"] == {"name": "新业路(地铁站)", "distance_m": 145.0}
    assert facts["facilities"] == ["某幼儿园", "某医院"]
    assert facts["center"] == {"name": "杭州市人民政府", "distance_m": 382.0}
    assert facts["highway"] == {"name": "杭州收费站(S2杭甬高速)", "distance_m": 9887.0}
    assert facts["parking"] == {"count": 2, "nearest_m": 118.0}
    assert facts["water"] == {"name": "青山水库", "distance_m": 800.0}
    # 逆地理 + 公交/地铁/配套/中心/高速/停车场/水库 各一次
    assert len(calls) == 8
    assert all("key=test-key" in u for u in calls)


def test_prefill_geo_returns_empty_facts_on_non_success_status() -> None:
    facts = _client(lambda u: (200, json.dumps({"status": "0", "info": "INVALID_USER_KEY"}))).prefill_geo(120.0, 30.0)
    assert facts == _EMPTY


def test_prefill_geo_returns_empty_facts_on_http_error() -> None:
    assert _client(lambda u: (403, "Forbidden")).prefill_geo(120.0, 30.0) == _EMPTY


def test_prefill_geo_returns_empty_facts_on_transport_exception() -> None:
    def boom(url: str) -> tuple[int, str]:
        raise ConnectionError("boom")

    assert _client(boom).prefill_geo(120.0, 30.0) == _EMPTY


def test_prefill_geo_returns_empty_facts_on_malformed_json() -> None:
    assert _client(lambda u: (200, "not json")).prefill_geo(120.0, 30.0) == _EMPTY


def test_rate_limit_retries_once_then_succeeds() -> None:
    # 地铁那一路第一次限流(10021)，退避重试第二次成功；其余路正常。
    hits = {"metro": 0}

    def transport(url: str) -> tuple[int, str]:
        dec = urllib.parse.unquote(url)
        if "regeo" in url:
            return 200, _regeo("某地")
        if "地铁站" in dec:
            hits["metro"] += 1
            return (200, _rate_limited()) if hits["metro"] == 1 else \
                (200, _around([{"name": "新业路(地铁站)", "distance": "100"}]))
        return 200, _around([])

    facts = _client(transport).prefill_geo(120.0, 30.0)
    assert facts["nearest_metro"] == {"name": "新业路(地铁站)", "distance_m": 100.0}
    assert hits["metro"] == 2   # 限流后确实重试了一次


def test_metro_unparsable_distance_gives_none() -> None:
    def transport(url: str) -> tuple[int, str]:
        dec = urllib.parse.unquote(url)
        if "regeo" in url:
            return 200, _regeo("某地")
        if "地铁站" in dec:
            return 200, _around([{"name": "坏距离站", "distance": "N/A"}])
        return 200, _around([])

    facts = _client(transport).prefill_geo(120.0, 30.0)
    assert facts["nearest_metro"] is None
