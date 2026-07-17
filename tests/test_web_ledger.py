"""台账接口。

盯两件事：
1. **每次生成都落台账**，包括没重算的那种——「这份报告的数字不是引擎算的」恰恰是
   复核最想知道的事
2. **「照此重算」当场能验证复现** —— 可复现不是承诺，是按一下就看得见的事实
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.engine.inputs import from_excel
from src.knowledge_base.store import BaseTableStore
from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.web.app import create_app
from tests.conftest import CASES

OFFICE_MARKET_INDEX = {
    "兴耀科创城A幢09层": 98,
    "蓝天国际大厦1幢808": 95,
    "蓝天国际大厦1幢703": 95,
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_path = tmp_path / "库.json"
    store = InstanceStore(store_path)
    for inst in import_from_excel(CASES["办公"]):
        store.add(inst)
    store.save()
    monkeypatch.setenv("实例库路径", str(store_path))
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "基础表"))
    monkeypatch.setenv("台账目录", str(tmp_path / "台账"))
    BaseTableStore(tmp_path / "基础表").import_from_excel(CASES["办公"])
    return TestClient(create_app())


def _project(client: TestClient) -> dict:
    with CASES["办公"].open("rb") as handle:
        return client.post("/api/extract", files={"file": (CASES["办公"].name, handle)}).json()["project"]


def _ledger_payload(client: TestClient) -> dict:
    items = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    selected = [
        {"编号": i["编号"], "市场状况指数": OFFICE_MARKET_INDEX[i["位置"]], "备注": ""}
        for i in items
    ]
    body = client.post("/api/compute", json={
        "category": "办公",
        "subject_levels": from_excel(CASES["办公"]).subject_levels,
        "selected": selected,
    }).json()
    return {
        "category": "办公",
        "base_table": None,
        "subject_levels": from_excel(CASES["办公"]).subject_levels,
        "selected": selected,
        "result": {
            "比准价格": body["比准价格"],
            "评估结果": body["评估结果"],
            "离散度": body["离散度"],
        },
    }


def _render(client: TestClient, project: dict, ledger: dict | None) -> None:
    data = {"project": json.dumps(project, ensure_ascii=False)}
    if ledger is not None:
        data["ledger"] = json.dumps(ledger, ensure_ascii=False)
    response = client.post("/api/render", data=data)
    assert response.status_code == 200, response.text


def test_generating_a_report_records_a_ledger_entry(client: TestClient) -> None:
    _render(client, _project(client), _ledger_payload(client))
    entries = client.get("/api/ledger").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["报告编号"] == "正恒评报字[2026]第F071号"
    assert entries[0]["经引擎重算"] is True
    assert entries[0]["经手人"]
    assert entries[0]["程序版本"]


def test_report_without_recompute_is_recorded_as_such(client: TestClient) -> None:
    """导入 Excel 直接生成——照记，且如实标明数字不是引擎算的。"""
    _render(client, _project(client), None)
    entries = client.get("/api/ledger").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["经引擎重算"] is False


def test_five_generations_make_five_entries(client: TestClient) -> None:
    """只增不改。中间改过什么全留着。"""
    project = _project(client)
    payload = _ledger_payload(client)
    for _ in range(5):
        _render(client, project, payload)
    assert len(client.get("/api/ledger").json()["entries"]) == 5


def test_list_omits_the_bulky_knowledge(client: TestClient) -> None:
    """列表不必背着 28 个因素的整份知识走。"""
    _render(client, _project(client), _ledger_payload(client))
    row = client.get("/api/ledger").json()["entries"][0]
    assert "实际知识" not in json.dumps(row, ensure_ascii=False)


def test_detail_has_the_whole_snapshot(client: TestClient) -> None:
    _render(client, _project(client), _ledger_payload(client))
    记录号 = client.get("/api/ledger").json()["entries"][0]["记录号"]
    detail = client.get(f"/api/ledger/{记录号}").json()
    assert len(detail["基础表"]["实际知识"]["因素"]) == 28
    assert len(detail["实例"]) == 3
    assert detail["基础表"]["偏离"] == []


def test_replay_endpoint_confirms_reproducibility(client: TestClient) -> None:
    """「照此重算」按下去就该看见「一致」。"""
    _render(client, _project(client), _ledger_payload(client))
    记录号 = client.get("/api/ledger").json()["entries"][0]["记录号"]
    body = client.post(f"/api/ledger/{记录号}/replay").json()
    assert body["一致"] is True
    assert body["重算得的"]["评估结果"] == body["台账记的"]["评估结果"] == 2.83


def test_replay_of_a_non_computed_report_is_400(client: TestClient) -> None:
    _render(client, _project(client), None)
    记录号 = client.get("/api/ledger").json()["entries"][0]["记录号"]
    response = client.post(f"/api/ledger/{记录号}/replay")
    assert response.status_code == 400
    assert "未经系统重算" in response.json()["detail"]


def test_replay_of_unknown_id_is_404(client: TestClient) -> None:
    assert client.post("/api/ledger/没这条/replay").status_code == 404


def test_ledger_failure_does_not_break_report_generation(client: TestClient) -> None:
    """台账记不上不该让报告生成失败。

    报告是估价师要交的东西，台账是我们要留的账。两者冲突时，先保住报告——
    但要在日志里喊出来，不能静默吞掉。
    """
    bad = _ledger_payload(client)
    bad["selected"] = [{"编号": "这个编号不存在于库中", "市场状况指数": 98, "备注": ""}]
    project = _project(client)
    response = client.post("/api/render", data={
        "project": json.dumps(project, ensure_ascii=False),
        "ledger": json.dumps(bad, ensure_ascii=False),
    })
    assert response.status_code == 200, "台账记不上却把报告也搞挂了"


def test_invalid_weights_length_does_not_break_report_generation(client: TestClient) -> None:
    """权重数量不对时，台账记不上但报告照常生成。"""
    bad = _ledger_payload(client)
    bad["weights"] = [0.5, 0.5]  # 只有 2 个，但实例有 3 个
    project = _project(client)
    response = client.post("/api/render", data={
        "project": json.dumps(project, ensure_ascii=False),
        "ledger": json.dumps(bad, ensure_ascii=False),
    })
    assert response.status_code == 200, "权重验证失败不该让报告生成失败"


def test_invalid_weights_sum_does_not_break_report_generation(client: TestClient) -> None:
    """权重和不等于 1 时，台账记不上但报告照常生成。"""
    bad = _ledger_payload(client)
    bad["weights"] = [0.3, 0.3, 0.3]  # 和为 0.9，不等于 1
    project = _project(client)
    response = client.post("/api/render", data={
        "project": json.dumps(project, ensure_ascii=False),
        "ledger": json.dumps(bad, ensure_ascii=False),
    })
    assert response.status_code == 200, "权重验证失败不该让报告生成失败"


def test_unknown_coefficient_override_does_not_break_report_generation(
    client: TestClient,
) -> None:
    """系数覆盖的因素名不存在于基础表——台账记不上，但报告照常生成。

    与权重非法（上两条测试）同一类：写入路径宁可让台账这一条记不上，
    也不能让报告生成失败——报告是估价师要交的东西，台账是我们要留的账，
    冲突时先保住报告。
    """
    bad = _ledger_payload(client)
    bad["coefficient_overrides"] = {"这个因素不存在": 3.0}
    project = _project(client)
    response = client.post("/api/render", data={
        "project": json.dumps(project, ensure_ascii=False),
        "ledger": json.dumps(bad, ensure_ascii=False),
    })
    assert response.status_code == 200, "系数覆盖验证失败不该让报告生成失败"
    # 台账没记上——ValueError 被外层广播 except 捕获、只写日志，不连累报告。
    assert client.get("/api/ledger").json()["entries"] == []


def test_ledger_entry_records_coefficient_deviation(client: TestClient) -> None:
    """带合法系数覆盖生成报告——台账须记下覆盖后的知识与偏离，`结果` 与覆盖后的重算一致。"""
    items = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    selected = [
        {"编号": i["编号"], "市场状况指数": OFFICE_MARKET_INDEX[i["位置"]], "备注": ""}
        for i in items
    ]
    subject_levels = from_excel(CASES["办公"]).subject_levels
    overrides = {"重要场所距离": 3.0}
    computed = client.post("/api/compute", json={
        "category": "办公",
        "subject_levels": subject_levels,
        "selected": selected,
        "coefficient_overrides": overrides,
    }).json()
    assert computed["评估结果"] != pytest.approx(2.83, abs=0.011), "前提：覆盖须改变结果"

    payload = {
        "category": "办公",
        "base_table": None,
        "subject_levels": subject_levels,
        "selected": selected,
        "coefficient_overrides": overrides,
        "偏离理由": "现场勘察结果与基础表默认档次不符",
        "result": {
            "比准价格": computed["比准价格"],
            "评估结果": computed["评估结果"],
            "离散度": computed["离散度"],
        },
    }
    _render(client, _project(client), payload)

    记录号 = client.get("/api/ledger").json()["entries"][0]["记录号"]
    detail = client.get(f"/api/ledger/{记录号}").json()
    偏离 = detail["基础表"]["偏离"]
    assert len(偏离) == 1
    assert 偏离[0]["因素"] == "重要场所距离"
    assert 偏离[0]["现值"] == "3.0"
    assert 偏离[0]["审批单号"] == ""
    assert 偏离[0]["理由"] == "现场勘察结果与基础表默认档次不符"
    factors = {f["名称"]: f["系数"] for f in detail["基础表"]["实际知识"]["因素"]}
    assert factors["重要场所距离"] == 3.0
    assert detail["结果"]["评估结果"] == computed["评估结果"]

    # 照台账重算——须复现覆盖后的结果，而非基础表原系数会算出的 2.83。
    replay_body = client.post(f"/api/ledger/{记录号}/replay").json()
    assert replay_body["一致"] is True
    assert replay_body["重算得的"]["评估结果"] == pytest.approx(computed["评估结果"], abs=0.011)
