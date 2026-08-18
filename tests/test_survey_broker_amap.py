"""AmapClient 单测：假 transport 灌 canned 高德 JSON，零网络；`pace=0` 免节流等待。

关键字/半径/限流重试经真机(钱江新城)校准，见 amap.py 顶部说明。canned 字段路径与
amap.py 的解析一一对应，真机再校准时两边一起改。

2026-08-18 按估价师反馈扩了三项（见 amap.py `prefill_geo` 文档）：
- 临街状况：regeo roads 的 `direction` → 四至 `bordering{东南西北}`（就近道路草稿，请核对）；
- 200 米内公交：`bus_lines` 线路号 + `bus_stop_count`（半径 200，线路从 POI 名抽取）；
- 公共服务设施：拆 `facilities{schools,hospitals,banks,malls}` 四类，各自就近取名。
"""

import json
import urllib.parse
from typing import Any

from serverless.survey_broker.amap import AmapClient

# prefill_geo 失败/空时的规范返回形状（与 amap._empty_facts 对齐）
_EMPTY = {
    "address": "",
    "roads": [],
    "bordering": {"东": "", "南": "", "西": "", "北": ""},
    "bus_stops": [],
    "bus_stop_count": 0,
    "bus_lines": [],
    "nearest_metro": None,
    "facilities": {"schools": [], "hospitals": [], "banks": [], "malls": []},
    "center": None,
    "highway": None,
    "parking": None,
    "water": None,
}


def _client(transport: Any) -> AmapClient:
    return AmapClient("test-key", transport=transport, pace=0)   # pace=0：测试不 sleep


def _regeo(address: str, roads: list[dict[str, Any]] | None = None) -> str:
    """roads 传高德原样的 [{name,direction,distance}, ...]（direction 供四至）。"""
    regeocode: dict[str, Any] = {"formatted_address": address}
    if roads is not None:
        regeocode["roads"] = roads
    return json.dumps({"status": "1", "regeocode": regeocode})


def _around(pois: list[dict[str, Any]]) -> str:
    return json.dumps({"status": "1", "pois": pois})


def _rate_limited() -> str:
    return json.dumps({"status": "0", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT", "infocode": "10021"})


# ---- 一份贯穿全字段的 canned 响应，供综合用例与部分专项用例复用 ----
_ROADS = [
    {"name": "市心路", "direction": "东", "distance": "30"},
    {"name": "金城路", "direction": "南", "distance": "45"},
    {"name": "金惠路", "direction": "西", "distance": "60"},
    {"name": "北塘路", "direction": "北", "distance": "80"},
]


def _full_transport(url: str) -> tuple[int, str]:
    dec = urllib.parse.unquote(url)   # keywords 里的中文是百分号编码
    if "regeo" in url:
        return 200, _regeo("浙江省杭州市萧山区某路", roads=_ROADS)
    if "公交" in dec:   # 200 米内公交站，名字带线路号
        return 200, _around([{"name": "商城北路口(712路;723路)", "distance": "80"},
                             {"name": "柳桥街站(733路)", "distance": "150"}])
    if "地铁站" in dec:
        return 200, _around([{"name": "新业路(地铁站)", "distance": "145"}])
    if "学校" in dec:
        return 200, _around([{"name": "回澜初中", "distance": "200"},
                             {"name": "育才小学", "distance": "260"}])
    if "医院" in dec:
        return 200, _around([{"name": "社区卫生院", "distance": "300"},
                             {"name": "萧山医院", "distance": "500"}])
    if "银行" in dec:
        return 200, _around([{"name": "中国工商银行", "distance": "180"},
                             {"name": "萧山农商银行", "distance": "220"}])
    if "商场" in dec or "购物" in dec:
        return 200, _around([{"name": "杭州胤隆汇休闲主题酒店", "distance": "400"},
                             {"name": "杭州金马饭店", "distance": "450"}])
    if "市政府" in dec:
        return 200, _around([{"name": "萧山区人民政府", "distance": "382"}])
    if "收费站" in dec:
        return 200, _around([{"name": "萧山收费站(S2)", "distance": "9887"}])
    if "停车场" in dec:
        return 200, _around([{"name": "P1停车场", "distance": "118"}])
    if "水库" in dec:
        return 200, _around([{"name": "青山水库", "distance": "800"}])
    return 200, _around([])


def test_prefill_geo_parses_all_facts_from_canned_response() -> None:
    facts = _client(_full_transport).prefill_geo(120.21, 30.25)
    assert facts["address"] == "浙江省杭州市萧山区某路"
    assert facts["roads"] == ["市心路", "金城路", "金惠路", "北塘路"]
    assert facts["bordering"] == {"东": "市心路", "南": "金城路", "西": "金惠路", "北": "北塘路"}
    assert facts["bus_lines"] == ["712路", "723路", "733路"]
    assert facts["bus_stop_count"] == 2
    assert facts["nearest_metro"] == {"name": "新业路(地铁站)", "distance_m": 145.0}
    assert facts["facilities"] == {
        "schools": ["回澜初中", "育才小学"],
        "hospitals": ["社区卫生院", "萧山医院"],
        "banks": ["中国工商银行", "萧山农商银行"],
        "malls": ["杭州胤隆汇休闲主题酒店", "杭州金马饭店"],
    }
    assert facts["center"] == {"name": "萧山区人民政府", "distance_m": 382.0}
    assert facts["highway"] == {"name": "萧山收费站(S2)", "distance_m": 9887.0}
    assert facts["parking"] == {"count": 1, "nearest_m": 118.0}
    assert facts["water"] == {"name": "青山水库", "distance_m": 800.0}


def test_bordering_picks_nearest_road_per_direction() -> None:
    # 同一方向多条路取最近；"东南"复合方向同时进东和南候选。
    roads = [
        {"name": "远东路", "direction": "东", "distance": "300"},
        {"name": "近东路", "direction": "东", "distance": "40"},
        {"name": "东南斜街", "direction": "东南", "distance": "50"},
    ]

    def transport(url: str) -> tuple[int, str]:
        if "regeo" in url:
            return 200, _regeo("某地", roads=roads)
        return 200, _around([])

    facts = _client(transport).prefill_geo(120.0, 30.0)
    assert facts["bordering"]["东"] == "近东路"        # 40 < 50 < 300
    assert facts["bordering"]["南"] == "东南斜街"       # 南向唯一候选
    assert facts["bordering"]["西"] == ""              # 无西向路
    assert facts["bordering"]["北"] == ""


def test_bus_lines_extracted_and_deduped_from_poi_names() -> None:
    def transport(url: str) -> tuple[int, str]:
        dec = urllib.parse.unquote(url)
        if "regeo" in url:
            return 200, _regeo("某地")
        if "公交" in dec:
            return 200, _around([
                {"name": "某站(712路;723路)", "distance": "60"},
                {"name": "另一站(712路;K5路)", "distance": "120"},   # 712 去重
            ])
        return 200, _around([])

    facts = _client(transport).prefill_geo(120.0, 30.0)
    assert facts["bus_lines"] == ["712路", "723路", "K5路"]
    assert facts["bus_stop_count"] == 2


def test_bus_lines_from_address_field_skip_discontinued() -> None:
    # 真机校准：线路号在 address、分号分隔；停运线整段带「(停运)」前缀，须整段跳过。
    def transport(url: str) -> tuple[int, str]:
        dec = urllib.parse.unquote(url)
        if "regeo" in url:
            return 200, _regeo("某地")
        if "公交" in dec:
            return 200, _around([
                {"name": "火车南站西广场(公交站)", "distance": "150",
                 "address": "(停运)8701路(通宵线);700路;707路;733路"},
                {"name": "火车南站东(公交站)", "distance": "180",
                 "address": "123路;736路(北线);736路B"},
            ])
        return 200, _around([])

    facts = _client(transport).prefill_geo(120.0, 30.0)
    assert facts["bus_lines"] == ["700路", "707路", "733路", "123路", "736路"]  # 8701路(停运)被跳
    assert facts["bus_stop_count"] == 2


def test_facilities_four_categories_are_independent() -> None:
    # 估价师反馈的根因：混搜时最近几条全是学校 → 只出学校。分类独立搜后各有其项。
    def transport(url: str) -> tuple[int, str]:
        dec = urllib.parse.unquote(url)
        if "regeo" in url:
            return 200, _regeo("某地")
        if "学校" in dec:
            return 200, _around([{"name": "A小学"}, {"name": "B中学"}])
        if "医院" in dec:
            return 200, _around([{"name": "C医院"}])
        if "银行" in dec:
            return 200, _around([{"name": "D银行"}])
        if "商场" in dec or "购物" in dec:
            return 200, _around([{"name": "E广场"}])
        return 200, _around([])

    facts = _client(transport).prefill_geo(120.0, 30.0)
    assert facts["facilities"]["schools"] == ["A小学", "B中学"]
    assert facts["facilities"]["hospitals"] == ["C医院"]
    assert facts["facilities"]["banks"] == ["D银行"]
    assert facts["facilities"]["malls"] == ["E广场"]


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
