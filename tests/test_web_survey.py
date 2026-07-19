"""办公端「从实勘问卷拉取」端点：列已提交 / 拉一份预填 / 未配多维表挡回。

不触网——monkeypatch 把 config 的开关与客户端换成内存假件（同 test_web_online 的测法）。
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.questionnaire.backend import response_to_fields
from src.questionnaire.model import STATUS_DRAFT, STATUS_SUBMITTED, SurveyResponse
from src.web.app import create_app

SHEET = "实勘问卷"


class _FakeClient:
    """内存版 notable 客户端：只实现后端要用的 list_records。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list_records(self, sheet: str) -> list[dict[str, Any]]:
        return [dict(r, fields=dict(r["fields"])) for r in self._rows]


def _resp(qid: str, 状态: str) -> SurveyResponse:
    return SurveyResponse(
        问卷ID=qid,
        状态=状态,
        填报人="user-7",
        更新时间="2026-07-19T10:00:00",
        category="办公",
        basic={"report_no": f"R-{qid}", "client": "甲", "owner": "乙",
               "usage": "办公", "value_date": "2026-04-20"},
        subjects=({"index": 1, "owner": "乙", "address": "A 路 1 号",
                   "usage": "办公", "area": 100.0},),
        subject_levels={"楼层": "中", "临街状况": "优"},
        asset_conditions={"楼层": "6/20", "临街状况": "临主干道"},
        photos=("p1.jpg",),
    )


def _rows(*responses: SurveyResponse) -> list[dict[str, Any]]:
    return [{"id": f"r{i}", "fields": response_to_fields(r)} for i, r in enumerate(responses)]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _wire(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], *, sheet: str = SHEET) -> None:
    from src.dingtalk import config

    monkeypatch.setattr(config, "use_notable", lambda: True)
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: _FakeClient(rows))
    monkeypatch.setattr(config, "survey_sheet", lambda: sheet)


def test_list_returns_submitted_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _rows(_resp("1", STATUS_SUBMITTED), _resp("2", STATUS_DRAFT)))
    surveys = client.get("/api/survey/list").json()["surveys"]
    assert [s["问卷ID"] for s in surveys] == ["1"]
    assert surveys[0]["填报人"] == "user-7"
    assert surveys[0]["category"] == "办公"


def test_pull_returns_prefill_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _rows(_resp("42", STATUS_SUBMITTED)))
    body = client.get("/api/survey/pull", params={"id": "42"}).json()
    assert body["project"]["report_no"] == "R-42"
    assert body["project"]["unit_price"] == 0.0  # 比较法输出留空待估价师补
    assert body["subject_levels"]["楼层"] == "中"
    assert body["asset_conditions"]["临街状况"] == "临主干道"
    assert body["单价单位"] == "元/㎡·天"
    assert body["面积单位"] == "㎡"
    assert body["source"] == "questionnaire"


def test_pull_unknown_id_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _rows(_resp("1", STATUS_SUBMITTED)))
    assert client.get("/api/survey/pull", params={"id": "nope"}).status_code == 404


def test_local_mode_blocks_with_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 默认 use_notable() False（conftest 不设 承载后端）→ 本地模式无问卷源
    assert client.get("/api/survey/list").status_code == 409


def test_notable_without_sheet_blocks_with_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _rows(_resp("1", STATUS_SUBMITTED)), sheet="")
    assert client.get("/api/survey/list").status_code == 409
