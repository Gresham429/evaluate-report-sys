"""Project 装载与资产状况填充测试。"""

from src.extractor.project import load_project
from tests.conftest import CASES


def test_load_project_fills_asset_conditions() -> None:
    p = load_project(CASES["办公"])
    groups = {g.name: g for g in p.asset_condition_groups}
    assert set(groups) == {"区位状况", "实物状况", "权益状况"}
    loc = {f.name: f.description for f in groups["区位状况"].factors}
    assert "第十二层" in loc["楼层"]
