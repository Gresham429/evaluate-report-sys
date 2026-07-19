"""基础表接口与表单预填测试。

盯两件事：

1. **表单路径拿得到 28 个下拉框的选项**——选项全部来自基础表，系统不编造档次
2. **Excel 导入一次性预填表单**（19 字段 + 一览表 + 28 档次）+ 基础表入库，
   之后重算与出报告都不再需要那个文件
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from tests.conftest import CASES


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """空的基础表库——首次使用时估价师面对的正是这个状态。"""
    monkeypatch.setenv("实例库路径", str(tmp_path / "库.json"))
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "基础表"))
    return TestClient(create_app())


def _import(client: TestClient, case: str, endpoint: str = "/api/base-tables") -> dict:
    with CASES[case].open("rb") as handle:
        response = client.post(endpoint, files={"file": (CASES[case].name, handle)})
    assert response.status_code == 200, response.text
    return response.json()


def test_factors_before_any_import_is_404(client: TestClient) -> None:
    """一版基础表都没导过时，表单没有下拉框可给——须说清楚，不能给个空表。"""
    response = client.get("/api/factors", params={"category": "办公"})
    assert response.status_code == 404
    assert "办公" in response.json()["detail"]


def test_factors_give_the_dropdown_options(client: TestClient) -> None:
    """28 个因素，各带档次选项。选项来自基础表，不是系统编的。"""
    _import(client, "办公")
    body = client.get("/api/factors", params={"category": "办公"}).json()
    assert len(body["factors"]) == 28

    first = body["factors"][0]
    assert first["名称"] == "重要场所距离"
    assert [lv["描述"] for lv in first["档次"]] == [
        "距区域中心距离＜1KM",
        "距区域中心距离1-1.5KM",
        "距区域中心距离1.5-2KM",
        "距区域中心距离2-2.5KM",
        "距区域中心距离＞2.5KM",
    ]
    # 档次按分值高→低给，与基础表 D..H 的排法一致——估价师看到的次序跟 Excel 一样。
    assert [lv["分值"] for lv in first["档次"]] == [2, 1, 0, -1, -2]


def test_factors_report_which_version(client: TestClient) -> None:
    """界面要能明示当前用的是哪一版（决策记录 §3.4）。"""
    imported = _import(client, "办公")
    body = client.get("/api/factors", params={"category": "办公"}).json()
    assert body["base_table"]["指纹"] == imported["base_table"]["指纹"]
    assert body["base_table"]["来源文件名"] == CASES["办公"].name


def test_reimporting_same_content_is_not_a_new_version(client: TestClient) -> None:
    """估价师没改基础表就又导了一次——这是常态，不是错误，不该堆出第二版。"""
    first = _import(client, "办公")
    assert first["是否新版"] is True
    second = _import(client, "办公")
    assert second["是否新版"] is False
    assert second["base_table"]["指纹"] == first["base_table"]["指纹"]
    assert len(client.get("/api/base-tables", params={"category": "办公"}).json()["versions"]) == 1


def test_three_categories_have_distinct_fingerprints(client: TestClient) -> None:
    """三类的修正系数完全不同，指纹必须两两不同，不能混成一版。"""
    prints = {case: _import(client, case)["base_table"]["指纹"] for case in ("农用", "办公", "商业")}
    assert len(set(prints.values())) == 3


def test_extract_prefills_the_whole_form(client: TestClient) -> None:
    """Excel 导入 = 一次性预填表单：19 字段 + 一览表 + 28 档次，一次交齐。"""
    with CASES["办公"].open("rb") as handle:
        body = client.post("/api/extract", files={"file": (CASES["办公"].name, handle)}).json()

    assert body["project"]["report_no"] == "正恒评报字[2026]第F071号"
    assert len(body["project"]["subjects"]) == 2
    assert len(body["subject_levels"]) == 28
    assert body["subject_levels"]["临街状况"] == "四面临街"
    assert body["单价单位"] == "元/㎡·天"


def test_extract_seeds_the_base_table(client: TestClient) -> None:
    """导入实勘表顺带把基础表收进库——进了库表单才有下拉框可选。"""
    assert client.get("/api/factors", params={"category": "办公"}).status_code == 404
    _import(client, "办公", endpoint="/api/extract")
    assert client.get("/api/factors", params={"category": "办公"}).status_code == 200


def test_extract_records_the_uploaded_filename(client: TestClient) -> None:
    """台账要记「这版是从哪个文件导进来的」，记一串 tmpXXXX 等于没记。"""
    body = _import(client, "办公", endpoint="/api/extract")
    assert body["base_table"]["来源文件名"] == CASES["办公"].name


def test_compute_without_base_table_is_400(client: TestClient) -> None:
    """基础表没进库就重算——须说清楚缺什么，不得静默算出个数来。"""
    response = client.post(
        "/api/compute",
        json={"category": "办公", "subject_levels": {}, "selected": []},
    )
    assert response.status_code == 400


def test_base_tables_list_empty_for_untouched_category(client: TestClient) -> None:
    body = client.get("/api/base-tables", params={"category": "商业"}).json()
    assert body["versions"] == []
    assert body["生效指纹"] is None


def test_unknown_category_is_400(client: TestClient) -> None:
    assert client.get("/api/factors", params={"category": "写字楼"}).status_code == 400
    assert client.get("/api/base-tables", params={"category": "写字楼"}).status_code == 400


# ---------------------------------------------------------------- 版本管理


def test_all_lists_seven_categories_with_flags(client: TestClient) -> None:
    """基础表页手风琴的数据源：7 类别；导入的那类有 1 版且标 latest+active。"""
    imported = _import(client, "办公")
    body = client.get("/api/base-tables/all").json()
    assert len(body["categories"]) == 7
    office = next(c for c in body["categories"] if c["类别"] == "办公")
    assert office["生效指纹"] == imported["base_table"]["指纹"]
    assert len(office["versions"]) == 1
    v = office["versions"][0]
    assert v["latest"] is True and v["active"] is True
    # 没导过的类别为空
    empty = next(c for c in body["categories"] if c["类别"] == "工业")
    assert empty["versions"] == [] and empty["生效指纹"] is None


def test_set_active_requires_existing_fingerprint(client: TestClient) -> None:
    imported = _import(client, "办公")
    fp = imported["base_table"]["指纹"]
    # 不存在的指纹 → 400
    bad = client.post("/api/base-tables/active", json={"category": "办公", "fingerprint": "nope"})
    assert bad.status_code == 400
    # 存在的指纹 → 200，且写进生效版本
    ok = client.post("/api/base-tables/active", json={"category": "办公", "fingerprint": fp})
    assert ok.status_code == 200
    assert ok.json()["生效指纹"] == fp
    assert client.get("/api/base-tables", params={"category": "办公"}).json()["生效指纹"] == fp


def test_set_active_unknown_category_400(client: TestClient) -> None:
    resp = client.post("/api/base-tables/active", json={"category": "写字楼", "fingerprint": "x"})
    assert resp.status_code == 400


def test_pull_without_notable_configured_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本地模式（没配多维表）拉取 → 409 明确提示，不崩。"""
    for key in ("NOTABLE_BASETABLE_SHEET", "YIDA_APP_KEY", "YIDA_APP_SECRET",
                "NOTABLE_BASE_ID", "NOTABLE_OPERATOR_ID"):
        monkeypatch.delenv(key, raising=False)
    resp = client.post("/api/base-tables/pull")
    assert resp.status_code == 409
    assert "多维表" in resp.json()["detail"]
