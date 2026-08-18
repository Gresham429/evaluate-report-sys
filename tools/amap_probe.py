"""高德接口校准探针：用真 `AMAP_KEY` 打真实点，dump 原始响应，定位「公交线路号在哪个字段」。

`serverless/survey_broker/amap.py` 的公交线路抽取按「POI 名里正则抽『N路』」实现，但高德是否
在公交站 POI 名/字段里带线路号须真机校准。本探针把 200m 公交站 POI 的**完整字段**打出来，
好据实调 amap._bus_facts 的抽取路径；同时打逆地理 roads（四至用 direction）与四类配套名。

**安全**：key 从环境变量 `AMAP_KEY` 或 `--key` 读，**不硬编码、不打印 key**（URL 里 key 脱敏）。
本脚本只作校准诊断，不进 broker / exe。

用法：
    AMAP_KEY=你的key uv run python tools/amap_probe.py
    AMAP_KEY=你的key uv run python tools/amap_probe.py --location 120.26,30.18
    AMAP_KEY=你的key uv run python tools/amap_probe.py --address "杭州市萧山区柳桥街"
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_GEOCODE = "https://restapi.amap.com/v3/geocode/geo"
_REGEO = "https://restapi.amap.com/v3/geocode/regeo"
_AROUND = "https://restapi.amap.com/v3/place/around"


def _get(url: str, params: dict[str, str], key: str) -> dict[str, Any]:
    """打一个高德接口，回解析后的 dict；网络/解析失败抛异常由 main 兜。"""
    query = dict(params)
    query["key"] = key
    full = f"{url}?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(full, timeout=10) as resp:  # noqa: S310  仅高德固定域名
        return json.loads(resp.read().decode("utf-8"))  # type: ignore[no-any-return]


def _resolve_location(key: str, address: str, city: str, location: str) -> str:
    """有 --location 直接用；否则地理编码 address → 坐标。失败回空串。"""
    if location:
        return location
    geo = _get(_GEOCODE, {"address": address, "city": city}, key)
    geocodes = geo.get("geocodes") or []
    if not geocodes:
        print(f"✗ 地理编码无结果（status={geo.get('status')} info={geo.get('info')}）；"
              f"请换 --address 或直接给 --location lng,lat")
        return ""
    loc = str(geocodes[0].get("location") or "")
    print(f"● 地址「{address}」→ 坐标 {loc}（{geocodes[0].get('formatted_address')}）")
    return loc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="高德接口校准探针（不打印 key）")
    parser.add_argument("--key", default=os.environ.get("AMAP_KEY", ""), help="高德 key（默认取环境变量 AMAP_KEY）")
    parser.add_argument("--address", default="杭州市萧山区商城北路", help="要校准的地址（无 --location 时用它地理编码）")
    parser.add_argument("--location", default="", help="lng,lat（给了就跳过地理编码）")
    parser.add_argument("--city", default="杭州", help="地理编码限定城市")
    args = parser.parse_args(argv)

    if not args.key:
        print("✗ 没有 key：设环境变量 AMAP_KEY 或传 --key（本脚本不会打印 key）")
        return 2

    try:
        loc = _resolve_location(args.key, args.address, args.city, args.location)
        if not loc:
            return 1

        print("\n=== 1) 逆地理 roads（四至用 direction）===")
        regeo = _get(_REGEO, {"location": loc, "extensions": "all"}, args.key)
        roads = (regeo.get("regeocode") or {}).get("roads") or []
        if not roads:
            print("  （无 roads——四至将为空，估价师现场按宗地图补）")
        for road in roads[:8]:
            print(f"  {road.get('name')}  方向={road.get('direction')}  距离={road.get('distance')}m")

        print("\n=== 2) 200m 公交站 完整 POI（★关键：看线路号在哪个字段★）===")
        bus = _get(_AROUND, {"location": loc, "keywords": "公交车站", "radius": "200",
                             "extensions": "all", "sortrule": "distance"}, args.key)
        pois = bus.get("pois") or []
        print(f"  共 {len(pois)} 条公交站 POI；前 3 条完整字段：")
        for poi in pois[:3]:
            print(json.dumps(poi, ensure_ascii=False, indent=2))

        print("\n=== 3) 公共服务四类（1km 内就近名）===")
        for keyword in ["学校", "医院", "银行", "商场|购物中心"]:
            data = _get(_AROUND, {"location": loc, "keywords": keyword, "radius": "1000",
                                 "extensions": "base", "sortrule": "distance"}, args.key)
            names = [p.get("name") for p in (data.get("pois") or [])[:4]]
            print(f"  {keyword}: {names}")
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"✗ 探测失败：{type(exc).__name__}: {exc}")
        return 1

    print("\n把「第 2) 段的公交 POI 完整字段」贴给我——我据线路号实际所在字段调 amap._bus_facts 的抽取。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
