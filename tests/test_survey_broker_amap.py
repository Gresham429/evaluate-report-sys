"""AmapClient 单测：假 transport 灌 canned 高德 JSON，零网络。

canned 响应里的字段路径与 `amap.py` 里 `# 待真机校准` 的假设一一对应——
真机校准后若字段路径变了，这份 canned 数据和 amap.py 的解析要一起改。
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


def _regeo_response(address: str, roads: list[str] | None = None) -> str:
    regeocode: dict[str, Any] = {"formatted_address": address}
    if roads is not None:
        regeocode["roads"] = [{"name": r} for r in roads]
    return json.dumps({"status": "1", "regeocode": regeocode})


def _around_response(pois: list[dict[str, Any]]) -> str:
    return json.dumps({"status": "1", "pois": pois})


def test_prefill_geo_parses_facts_from_canned_response() -> None:
    calls: list[str] = []

    def transport(url: str) -> tuple[int, str]:
        calls.append(url)
        dec = urllib.parse.unquote(url)   # keywords 里的中文是百分号编码，解开再判
        if "regeo" in url:
            return 200, _regeo_response("浙江省杭州市西湖区示范路1号", roads=["示范路", "金城路"])
        if "政府" in dec:
            return 200, _around_response([{"name": "西湖区政府", "type": "政府机构", "distance": "3500"}])
        if "高速" in dec:
            return 200, _around_response([{"name": "留下收费站", "type": "交通设施", "distance": "2100"}])
        if "停车场" in dec:
            return 200, _around_response([
                {"name": "P1停车场", "type": "停车场", "distance": "120"},
                {"name": "P2停车场", "type": "停车场", "distance": "300"},
            ])
        if "水库" in dec:
            return 200, _around_response([{"name": "西溪湿地", "type": "风景名胜", "distance": "800"}])
        return 200, _around_response(
            [
                {"name": "示范路公交站", "type": "公交车站", "distance": "80"},
                {"name": "示范路地铁站", "type": "地铁站", "distance": "350"},
                {"name": "另一地铁站", "type": "地铁站", "distance": "900"},
                {"name": "示范超市", "type": "购物服务;超市", "distance": "120"},
            ]
        )

    client = AmapClient("test-key", transport=transport)
    facts = client.prefill_geo(120.15, 30.28)

    assert facts["address"] == "浙江省杭州市西湖区示范路1号"
    assert facts["bus_stops"] == ["示范路公交站"]
    assert facts["nearest_metro"] == {"name": "示范路地铁站", "distance_m": 350.0}
    assert facts["facilities"] == ["示范超市"]
    assert facts["roads"] == ["示范路", "金城路"]
    assert facts["center"] == {"name": "西湖区政府", "distance_m": 3500.0}
    assert facts["highway"] == {"name": "留下收费站", "distance_m": 2100.0}
    assert facts["parking"] == {"count": 2, "nearest_m": 120.0}
    assert facts["water"] == {"name": "西溪湿地", "distance_m": 800.0}
    assert len(calls) == 6  # 逆地理 + 通用周边 + 政府 + 高速 + 停车场 + 水源
    assert all("key=test-key" in u for u in calls)


def test_prefill_geo_returns_empty_facts_on_non_success_status() -> None:
    def transport(url: str) -> tuple[int, str]:
        return 200, json.dumps({"status": "0", "info": "INVALID_USER_KEY"})

    client = AmapClient("bad-key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == _EMPTY


def test_prefill_geo_returns_empty_facts_on_http_error() -> None:
    def transport(url: str) -> tuple[int, str]:
        return 403, "Forbidden"

    client = AmapClient("bad-key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == _EMPTY


def test_prefill_geo_returns_empty_facts_on_transport_exception() -> None:
    def transport(url: str) -> tuple[int, str]:
        raise ConnectionError("boom")

    client = AmapClient("key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == _EMPTY


def test_prefill_geo_returns_empty_facts_on_malformed_json() -> None:
    def transport(url: str) -> tuple[int, str]:
        return 200, "not json"

    client = AmapClient("key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == _EMPTY


def test_metro_with_unparsable_distance_kept_as_facility() -> None:
    # 地铁站距离解析不出：不进 nearest_metro，但事实不丢——退回 facilities
    def transport(url: str) -> tuple[int, str]:
        if "regeo" in url:
            return 200, json.dumps({"status": "1", "regeocode": {"formatted_address": "某地"}})
        return 200, _around_response(
            [{"name": "坏距离地铁站", "type": "地铁站", "distance": "N/A"}]
        )

    client = AmapClient("key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)
    assert facts["nearest_metro"] is None
    assert "坏距离地铁站" in facts["facilities"]


def test_transit_matched_by_broad_keywords() -> None:
    # 真机校准(杭州东站)：高德用「公交车站」「地铁E口」，关键词放宽到「公交」「地铁」才抓得住
    def transport(url: str) -> tuple[int, str]:
        if "regeo" in url:
            return 200, json.dumps({"status": "1", "regeocode": {"formatted_address": "某地"}})
        return 200, _around_response([
            {"name": "东站公交车站", "type": "交通设施服务;公交车站", "distance": "60"},
            {"name": "地铁E口(1/4号线)", "type": "交通设施服务;地铁站", "distance": "120"},
            {"name": "星巴克", "type": "餐饮服务;咖啡厅", "distance": "40"},
        ])

    client = AmapClient("k", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)
    assert facts["bus_stops"] == ["东站公交车站"]
    assert facts["nearest_metro"] == {"name": "地铁E口(1/4号线)", "distance_m": 120.0}
    assert facts["facilities"] == ["星巴克"]
