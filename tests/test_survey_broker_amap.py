"""AmapClient 单测：假 transport 灌 canned 高德 JSON，零网络。

canned 响应里的字段路径与 `amap.py` 里 `# 待真机校准` 的假设一一对应——
真机校准后若字段路径变了，这份 canned 数据和 amap.py 的解析要一起改。
"""

import json
from typing import Any

from serverless.survey_broker.amap import AmapClient


def _regeo_response(address: str) -> str:
    return json.dumps({"status": "1", "regeocode": {"formatted_address": address}})


def _around_response(pois: list[dict[str, Any]]) -> str:
    return json.dumps({"status": "1", "pois": pois})


def test_prefill_geo_parses_facts_from_canned_response() -> None:
    calls: list[str] = []

    def transport(url: str) -> tuple[int, str]:
        calls.append(url)
        if "regeo" in url:
            return 200, _regeo_response("浙江省杭州市西湖区示范路1号")
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
    assert len(calls) == 2  # 逆地理 + 周边搜索各打一次
    assert all("key=test-key" in u for u in calls)


def test_prefill_geo_returns_empty_facts_on_non_success_status() -> None:
    def transport(url: str) -> tuple[int, str]:
        return 200, json.dumps({"status": "0", "info": "INVALID_USER_KEY"})

    client = AmapClient("bad-key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == {"address": "", "bus_stops": [], "nearest_metro": None, "facilities": []}


def test_prefill_geo_returns_empty_facts_on_http_error() -> None:
    def transport(url: str) -> tuple[int, str]:
        return 403, "Forbidden"

    client = AmapClient("bad-key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == {"address": "", "bus_stops": [], "nearest_metro": None, "facilities": []}


def test_prefill_geo_returns_empty_facts_on_transport_exception() -> None:
    def transport(url: str) -> tuple[int, str]:
        raise ConnectionError("boom")

    client = AmapClient("key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == {"address": "", "bus_stops": [], "nearest_metro": None, "facilities": []}


def test_prefill_geo_returns_empty_facts_on_malformed_json() -> None:
    def transport(url: str) -> tuple[int, str]:
        return 200, "not json"

    client = AmapClient("key", transport=transport)
    facts = client.prefill_geo(120.0, 30.0)

    assert facts == {"address": "", "bus_stops": [], "nearest_metro": None, "facilities": []}
