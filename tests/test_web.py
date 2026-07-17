"""网页接口测试。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.knowledge_base.store import BaseTableStore
from src.web.app import create_app
from tests.conftest import CASES
from tests.test_render import extract_paragraphs_for_test


def _client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """已导入办公基础表的夹具——分组/资产状况描述都要能按基础表因素序对上。"""
    monkeypatch.setenv("实例库路径", str(tmp_path / "库.json"))
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "基础表"))
    BaseTableStore(tmp_path / "基础表").import_from_excel(CASES["办公"])
    return TestClient(create_app())


def _minimal_office_payload(client: TestClient) -> dict:
    """一份完整、可渲染的办公项目 payload——直接从真实实勘表提取，不手拼半成品字段。"""
    with CASES["办公"].open("rb") as handle:
        response = client.post(
            "/api/extract",
            files={"file": (CASES["办公"].name, handle)},
        )
    assert response.status_code == 200, response.text
    return response.json()["project"]


def _bare_office_payload() -> dict:
    """不依赖任何已导入基础表的最小办公 payload，专测「缺基础表」这条错误路径。"""
    return {
        "category": "办公", "report_no": "测试编号", "project_name": "", "client": "",
        "client_address": "", "legal_rep": "", "purpose": "", "survey_date": "",
        "value_date": "", "materials": "", "certificate_status": "", "owner": "",
        "address": "", "usage": "", "scale": "", "scope": "", "current_status": "",
        "work_period": "", "issue_date": "", "surveyor": "", "unit_price": 1.0,
        "dispersion": 0.0, "subjects": [],
    }


def test_index_served() -> None:
    response = _client().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_extract_returns_project_and_warnings() -> None:
    with CASES["办公"].open("rb") as handle:
        response = _client().post(
            "/api/extract",
            files={"file": ("办公实勘表、比较法.xlsx", handle, "application/vnd.ms-excel")},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["report_no"] == "正恒评报字[2026]第F071号"
    assert body["project"]["category"] == "办公"
    assert len(body["project"]["subjects"]) == 2
    assert isinstance(body["warnings"], list)


def test_extract_rejects_non_xlsx() -> None:
    response = _client().post(
        "/api/extract", files={"file": ("a.txt", b"not excel", "text/plain")}
    )
    assert response.status_code == 400


def test_extract_agricultural_category() -> None:
    with CASES["农用"].open("rb") as handle:
        response = _client().post(
            "/api/extract",
            files={"file": ("农用地实勘表、比较法.xlsx", handle, "application/vnd.ms-excel")},
        )
    assert response.json()["project"]["category"] == "农用"


def test_extract_prefills_asset_conditions() -> None:
    """实勘表导入要把逐因素手写描述一并交给前端预填——不逼估价师重打一遍字。"""
    with CASES["办公"].open("rb") as handle:
        response = _client().post(
            "/api/extract",
            files={"file": ("办公实勘表、比较法.xlsx", handle, "application/vnd.ms-excel")},
        )
    body = response.json()
    assert "第十二层" in body["asset_conditions"]["楼层"]


def test_factors_endpoint_includes_group(client: TestClient) -> None:
    """表单要按分组分节铺开 28 个因素，分组只能来自基础表，不能在 JS 里另编一份。"""
    data = client.get("/api/factors", params={"category": "办公"}).json()
    assert all("分组" in f for f in data["factors"])
    assert {"区位状况", "实物状况", "权益状况"} <= {f["分组"] for f in data["factors"]}


def test_render_payload_carries_descriptions_into_report(
    client: TestClient, tmp_path: Path
) -> None:
    """表单提交的逐因素描述要真的印进报告，不是收了就扔。"""
    payload = _minimal_office_payload(client)
    payload["asset_conditions"] = {"楼层": "所在层数为第十二层，测试专用描述。"}
    r = client.post("/api/render", data={"project": json.dumps(payload, ensure_ascii=False)})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
    output = tmp_path / "报告.docx"
    output.write_bytes(r.content)
    text = "\n".join(extract_paragraphs_for_test(output))
    assert "所在层数为第十二层，测试专用描述。" in text


def test_render_payload_without_asset_conditions_still_renders(client: TestClient) -> None:
    """没带 asset_conditions 的既有调用方（Task 6 之前的行为）不能被这次改动拖累。"""
    payload = _minimal_office_payload(client)
    assert "asset_conditions" not in payload
    r = client.post("/api/render", data={"project": json.dumps(payload, ensure_ascii=False)})
    assert r.status_code == 200
    assert r.content[:2] == b"PK"


def test_render_rejects_asset_conditions_without_base_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """带描述却没导过基础表：因素分组/序无从谈起，须报 400，不能悄悄丢描述。"""
    monkeypatch.setenv("实例库路径", str(tmp_path / "库.json"))
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "基础表"))
    bare_client = TestClient(create_app())
    payload = _bare_office_payload()
    payload["asset_conditions"] = {"楼层": "所在层数为第十二层。"}
    r = bare_client.post(
        "/api/render", data={"project": json.dumps(payload, ensure_ascii=False)}
    )
    assert r.status_code == 400
