"""手工录入实例接口测试。

盯的是**服务端派生**：编号、起始日、日期精度都由服务端算，界面不自己算。
`parse_lease_start` 认得出「2025.7-2026.7」是仅年月、「2025-2026」是仅年，
抄一份进 JS 迟早两边解出两个日期。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("实例库路径", str(tmp_path / "库.json"))
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "基础表"))
    return TestClient(create_app())


def _new(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "类别": "办公",
        "位置": "某某大厦1幢101",
        "成交价": 2.5,
        "面积": 100.0,
        "出租用途": "办公",
        "交易情况": "正常",
        "交易情况指数": 100,
        "租期原文": "2026.1.15-2026.7.14",
        "因素档次": {"临街状况": "四面临街"},
        "备注": "",
    }
    payload.update(overrides)
    return payload


def test_manual_entry_lands_in_the_library(client: TestClient) -> None:
    """录完就该能在选实例时看到——否则录了个寂寞。"""
    body = client.post("/api/instances", json=_new()).json()
    assert body["added"] is True
    listed = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    assert len(listed) == 1
    assert listed[0]["位置"] == "某某大厦1幢101"
    # 档次确实存进去了——列表接口不回传它，故回头查 /api/instances 的返回值本身。
    assert body["instance"]["因素档次"] == {"临街状况": "四面临街"}


def test_id_is_derived_not_supplied(client: TestClient) -> None:
    """编号由服务端按「类别-起始年月-位置」派生，不让界面编。"""
    body = client.post("/api/instances", json=_new()).json()
    assert body["instance"]["编号"] == "办公-2026-01-某某大厦1幢101"


def test_date_precision_derived_from_free_text(client: TestClient) -> None:
    """三种真实写法各自的精度，全由服务端解析出来。"""
    cases = {
        "2026.1.15-2026.7.14": ("完整", "2026-01-15"),
        "2025.7-2026.7": ("仅年月", "2025-07-01"),
        "2025-2026": ("仅年", "2025-01-01"),
    }
    for raw, (precision, start) in cases.items():
        body = client.post(
            "/api/instances", json=_new(租期原文=raw, 位置=f"位置{raw}")
        ).json()
        assert body["instance"]["日期精度"] == precision, raw
        assert body["instance"]["起始日"] == start, raw


def test_unparseable_date_is_flagged_not_invented(client: TestClient) -> None:
    """解不出来就照实标记，不假造一个月份糊过去。"""
    body = client.post("/api/instances", json=_new(租期原文="租期面议")).json()
    assert body["instance"]["日期精度"] == "无法解析"
    assert body["instance"]["起始日"] is None
    assert "日期未知" in body["instance"]["编号"]


def test_duplicate_is_reported_not_overwritten(client: TestClient) -> None:
    """同位置同起始月撞编号，多半是重复录入——如实报告，不静默顶掉已有的。"""
    assert client.post("/api/instances", json=_new()).json()["added"] is True
    assert client.post("/api/instances", json=_new(成交价=99)).json()["added"] is False
    listed = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    assert len(listed) == 1
    assert listed[0]["成交价"] == 2.5, "已有的那条被覆盖了"


def test_blank_location_rejected(client: TestClient) -> None:
    """位置是编号的一部分，空着编号就成了「办公-2026-01-」。"""
    assert client.post("/api/instances", json=_new(位置="  ")).status_code == 400


def test_unknown_category_rejected(client: TestClient) -> None:
    assert client.post("/api/instances", json=_new(类别="写字楼")).status_code == 400


def test_manual_instance_is_selectable_for_compute(client: TestClient) -> None:
    """手工录的实例与 Excel 导的一视同仁，都能拿去重算。"""
    client.post("/api/instances", json=_new())
    listed = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    assert listed[0]["编号"]
    # 只验它进得了选择列表；真算得对不对由 test_web_compute 的金样盯着。
    assert listed[0]["类别"] == "办公"
