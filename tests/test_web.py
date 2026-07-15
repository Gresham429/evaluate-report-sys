"""网页接口测试。"""

from fastapi.testclient import TestClient

from src.web.app import create_app
from tests.conftest import CASES


def _client() -> TestClient:
    return TestClient(create_app())


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
