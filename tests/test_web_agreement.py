"""/api/agreement 端点测试。"""

import json
from urllib.parse import unquote

from fastapi.testclient import TestClient

from src.model import Category
from src.web.app import create_app
from tests.test_render_new_categories import _proj

_XLSX_MEDIA = "application/vnd.openxml"


def _payload(category: Category) -> dict[str, object]:
    p = _proj(category)
    return {
        "category": p.category,
        "report_no": p.report_no,
        "client": p.client,
        "owner": p.owner,
        "address": p.address,
        "subjects": [],
    }


def test_agreement_endpoint_returns_docx() -> None:
    client = TestClient(create_app())
    r = client.post(
        "/api/agreement",
        data={"project": json.dumps(_payload(Category.RESIDENTIAL)), "fee_total": "2616"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(_XLSX_MEDIA)
    assert len(r.content) > 0
    assert "委托评估协议书" in unquote(r.headers.get("content-disposition", ""))


def test_agreement_endpoint_rejects_negative_fee() -> None:
    client = TestClient(create_app())
    r = client.post(
        "/api/agreement",
        data={"project": json.dumps(_payload(Category.INDUSTRIAL)), "fee_total": "-5"},
    )
    assert r.status_code == 400
