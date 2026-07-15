"""草稿接口测试。

草稿的语义是**覆盖**（与实例库的「不覆盖」正相反），且 `数据` 不透明——
后端不理解表单形状。这两条是本文件盯的重点。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    return TestClient(create_app())


def _form_data(报告编号: str = "正恒评报字[2026]第F071号") -> dict[str, object]:
    """一份填了一半的表单，形状随便——后端不该关心。"""
    return {
        "报告编号": 报告编号,
        "类别": "办公",
        "project": {"report_no": 报告编号, "client": "杭州市萧山区机关事务服务中心"},
        "subject_levels": {"临街状况": "四面临街", "楼层": "中低层（7-12）"},
        "subjects": [{"index": 1, "area": 356.29}],
    }


def test_save_then_get_round_trips(client: TestClient) -> None:
    draft_id = client.post("/api/drafts", json={"数据": _form_data()}).json()["id"]
    body = client.get(f"/api/drafts/{draft_id}").json()
    assert body["数据"] == _form_data()
    assert body["报告编号"] == "正恒评报字[2026]第F071号"
    assert body["类别"] == "办公"


def test_saving_same_id_overwrites(client: TestClient) -> None:
    """草稿的核心语义：续存即覆盖，不堆出第二份。"""
    draft_id = client.post("/api/drafts", json={"数据": _form_data()}).json()["id"]
    updated = _form_data()
    updated["project"] = {"report_no": "改过了"}
    again = client.post("/api/drafts", json={"数据": updated, "id": draft_id}).json()["id"]
    assert again == draft_id
    assert len(client.get("/api/drafts").json()["drafts"]) == 1
    assert client.get(f"/api/drafts/{draft_id}").json()["数据"]["project"] == {"report_no": "改过了"}


def test_list_omits_the_form_data(client: TestClient) -> None:
    """列表只给摘要——52 项的表单数据没必要跟着列表走。"""
    client.post("/api/drafts", json={"数据": _form_data()})
    row = client.get("/api/drafts").json()["drafts"][0]
    assert "数据" not in row
    assert set(row) == {"id", "报告编号", "类别", "更新时间"}


def test_half_filled_draft_without_report_no(client: TestClient) -> None:
    """填一半时报告编号还没填——这是常态，不是错误。"""
    draft_id = client.post("/api/drafts", json={"数据": {"随便": "什么"}}).json()["id"]
    row = client.get("/api/drafts").json()["drafts"][0]
    assert row["id"] == draft_id
    assert row["报告编号"] == ""


def test_delete(client: TestClient) -> None:
    draft_id = client.post("/api/drafts", json={"数据": _form_data()}).json()["id"]
    assert client.delete(f"/api/drafts/{draft_id}").status_code == 200
    assert client.get("/api/drafts").json()["drafts"] == []
    assert client.delete(f"/api/drafts/{draft_id}").status_code == 404


def test_get_missing_draft_is_404(client: TestClient) -> None:
    assert client.get("/api/drafts/nosuchid").status_code == 404


def test_empty_when_nothing_saved(client: TestClient) -> None:
    """首次运行草稿目录还不存在，不该炸。"""
    assert client.get("/api/drafts").json()["drafts"] == []


def test_bad_payload_is_400(client: TestClient) -> None:
    assert client.post("/api/drafts", json={}).status_code == 400
    assert client.post("/api/drafts", json={"数据": "不是字典"}).status_code == 400


def test_path_traversal_id_rejected(client: TestClient) -> None:
    """id 从请求里原样进来，不许被拿去读写草稿目录之外的文件。"""
    assert client.get("/api/drafts/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
