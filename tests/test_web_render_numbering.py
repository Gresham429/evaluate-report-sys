"""出报告领号：多维表在线时后端领号注入 report_no；本地模式不动；缺凭据 503。

假 client（不触网）：insert_record 自增「报告序号」、get_record 回读、
list_records 回放已插入的行——足够走完 draw + LedgerStore.append + 读回。
"""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


class FakeNotable:
    """一张台账表：插一行自增 seq；带「快照」的行能被 iter 读回。"""

    def __init__(self) -> None:
        self._n = 0
        self.rows: dict[str, dict[str, Any]] = {}

    def insert_record(self, sheet: str, fields: dict[str, Any]) -> str:
        self._n += 1
        rid = f"r{self._n}"
        self.rows[rid] = {"id": rid, "fields": {**fields, "报告序号": self._n}}
        return rid

    def get_record(self, sheet: str, record_id: str) -> dict[str, Any]:
        return self.rows[record_id]

    def list_records(self, sheet: str) -> list[dict[str, Any]]:
        return list(self.rows.values())


def _project_payload(report_no: str = "手填号-勿用") -> str:
    return json.dumps({
        "category": "办公", "report_no": report_no, "project_name": "x", "client": "c",
        "client_address": "", "legal_rep": "", "purpose": "", "survey_date": "",
        "value_date": "", "materials": "", "certificate_status": "", "owner": "",
        "address": "", "usage": "", "scale": "", "scope": "", "current_status": "",
        "work_period": "", "issue_date": "", "surveyor": "", "unit_price": 2.83,
        "dispersion": 0.0, "subjects": [],
    })


@pytest.fixture()
def notable_client() -> FakeNotable:
    return FakeNotable()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, notable_client: FakeNotable) -> TestClient:
    from src.dingtalk import config
    monkeypatch.setattr(config, "use_notable", lambda: True)
    monkeypatch.setattr(config, "ledger_sheet", lambda: "台账表")
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: notable_client)
    # 台账 Store 也要走这个假 client：工厂按同样的 config 选后端
    monkeypatch.setattr(config, "instance_sheet", lambda: "")
    monkeypatch.setattr(config, "base_table_sheet", lambda: "")
    # 钉钉模式有硬门禁：给个授权操作人过门禁，好测领号/渲染本身（非测门禁）。
    monkeypatch.setattr(config, "office_operator", lambda: "tester")
    monkeypatch.setattr(config, "office_allowed_users", lambda: frozenset())
    return TestClient(create_app())


def test_online_render_draws_and_injects_number(
    client: TestClient, notable_client: FakeNotable
) -> None:
    resp = client.post("/api/render", data={"project": _project_payload()})
    assert resp.status_code == 200
    # 领号行 + 正式台账行都落进了假表；正式行的快照带领得的号
    snapshots = [
        json.loads(r["fields"]["快照"])
        for r in notable_client.rows.values()
        if r["fields"].get("快照")
    ]
    assert len(snapshots) == 1
    编号 = snapshots[0]["报告编号"]
    assert 编号.startswith("正恒评报字[") and 编号.endswith("第1号")
    # 下载文件名也用的是领得的号，不是手填的「手填号-勿用」
    assert "手填号" not in resp.headers.get("content-disposition", "")


def test_local_mode_keeps_form_number(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 不 monkeypatch config → 本地模式：report_no 用表单里的手填值
    monkeypatch.setenv("台账目录", str(tmp_path / "台账"))
    local = TestClient(create_app())
    resp = local.post("/api/render", data={"project": _project_payload(report_no="正恒评报字[2026]第F071号")})
    assert resp.status_code == 200
    assert "F071" in resp.headers.get("content-disposition", "")


def test_notable_without_credentials_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.dingtalk import config
    monkeypatch.setattr(config, "use_notable", lambda: True)
    monkeypatch.setattr(config, "ledger_sheet", lambda: "台账表")
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: None)
    monkeypatch.setattr(config, "office_operator", lambda: "tester")  # 过硬门禁
    monkeypatch.setattr(config, "office_allowed_users", lambda: frozenset())
    c = TestClient(create_app())
    resp = c.post("/api/render", data={"project": _project_payload()})
    assert resp.status_code == 503
