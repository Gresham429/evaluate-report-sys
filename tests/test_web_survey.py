"""办公端「从实勘问卷拉取」端点：列已提交 / 拉一份预填 / 未配多维表挡回。

不触网——monkeypatch 把 config 的开关与客户端换成内存假件（同 test_web_online 的测法）。
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.questionnaire.backend import response_to_fields
from src.questionnaire.model import (
    STATUS_DRAFT,
    STATUS_FINALIZED,
    STATUS_PENDING_REVIEW,
    STATUS_SUBMITTED,
    SurveyResponse,
)
from src.web.app import create_app

SHEET = "实勘问卷"


class _FakeClient:
    """内存版 notable 客户端：list_records + update_record（改状态用）。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list_records(self, sheet: str) -> list[dict[str, Any]]:
        return [dict(r, fields=dict(r["fields"])) for r in self._rows]

    def update_record(self, sheet: str, record_id: str, fields: dict[str, Any]) -> None:
        for r in self._rows:
            if r["id"] == record_id:
                r["fields"].update(fields)
                return
        raise KeyError(record_id)

    def status_of(self, qid: str) -> str:
        for r in self._rows:
            if r["fields"].get("问卷ID") == qid:
                return str(r["fields"].get("状态", ""))
        raise KeyError(qid)


def _resp(qid: str, 状态: str, filler: str = "user-7") -> SurveyResponse:
    return SurveyResponse(
        问卷ID=qid,
        状态=状态,
        填报人=filler,
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


@pytest.fixture(autouse=True)
def _clear_session() -> Iterator[None]:
    """会话是进程内模块状态，跨测试会串——每例前后清掉。"""
    from src.web import session

    session.clear_operator()
    yield
    session.clear_operator()


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    *,
    sheet: str = SHEET,
    operator: str = "user-7",
    admins: tuple[str, ...] = (),
) -> _FakeClient:
    from src.dingtalk import config

    fake = _FakeClient(rows)
    monkeypatch.setattr(config, "use_notable", lambda: True)
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: fake)
    monkeypatch.setattr(config, "survey_sheet", lambda: sheet)
    monkeypatch.setattr(config, "office_operator", lambda: operator)
    monkeypatch.setattr(config, "office_admins", lambda: frozenset(admins))
    return fake


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


# ------------------------------------------------------------ 权限「只看自己」


def test_list_shows_only_own_submitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(
        monkeypatch,
        _rows(_resp("1", STATUS_SUBMITTED, "user-7"), _resp("2", STATUS_SUBMITTED, "user-9")),
        operator="user-7",
    )
    surveys = client.get("/api/survey/list").json()["surveys"]
    assert [s["问卷ID"] for s in surveys] == ["1"]


def test_pull_rejects_other_owner_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _rows(_resp("1", STATUS_SUBMITTED, "user-9")), operator="user-7")
    assert client.get("/api/survey/pull", params={"id": "1"}).status_code == 404


# ------------------------------------------------------------ 审核列表 + 批量流转


def test_review_list_returns_own_pending(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(
        monkeypatch,
        _rows(
            _resp("1", STATUS_PENDING_REVIEW, "user-7"),
            _resp("2", STATUS_PENDING_REVIEW, "user-9"),
            _resp("3", STATUS_SUBMITTED, "user-7"),
        ),
        operator="user-7",
    )
    surveys = client.get("/api/survey/review/list").json()["surveys"]
    assert [s["问卷ID"] for s in surveys] == ["1"]


def test_review_endpoint_moves_submitted_to_pending(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _wire(
        monkeypatch,
        _rows(_resp("1", STATUS_SUBMITTED, "user-7"), _resp("2", STATUS_SUBMITTED, "user-7")),
        operator="user-7",
    )
    body = client.post("/api/survey/review", json={"survey_ids": ["1", "2"]}).json()
    assert body["ok"] == ["1", "2"]
    assert fake.status_of("1") == STATUS_PENDING_REVIEW
    assert fake.status_of("2") == STATUS_PENDING_REVIEW
    # 出报告列表（已提交）现在空了，都进了审核列表
    assert client.get("/api/survey/list").json()["surveys"] == []
    assert [s["问卷ID"] for s in client.get("/api/survey/review/list").json()["surveys"]] == ["1", "2"]


def test_finalize_endpoint_locks_pending(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 定稿须上级/管理员——用管理员 boss（P1 无组织架构、无上级，故用 admin）
    fake = _wire(
        monkeypatch, _rows(_resp("1", STATUS_PENDING_REVIEW, "user-7")),
        operator="boss", admins=("boss",),
    )
    body = client.post("/api/survey/finalize", json={"survey_ids": ["1"]}).json()
    assert body["ok"] == ["1"]
    assert fake.status_of("1") == STATUS_FINALIZED


def test_owner_cannot_finalize_via_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """owner 从端点定稿自己的 → 无权 → 未 ok、状态不动。"""
    fake = _wire(
        monkeypatch, _rows(_resp("1", STATUS_PENDING_REVIEW, "user-7")), operator="user-7"
    )
    body = client.post("/api/survey/finalize", json={"survey_ids": ["1"]}).json()
    assert body["ok"] == []
    assert fake.status_of("1") == STATUS_PENDING_REVIEW


def test_review_cannot_touch_others_survey(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _wire(
        monkeypatch, _rows(_resp("1", STATUS_SUBMITTED, "user-9")), operator="user-7"
    )
    body = client.post("/api/survey/review", json={"survey_ids": ["1"]}).json()
    assert body["ok"] == []
    assert body["results"]["1"] != "ok"
    assert fake.status_of("1") == STATUS_SUBMITTED  # 别人的问卷状态不动


def test_me_reports_operator_and_login_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _rows(), operator="user-7")
    body = client.get("/api/me").json()
    assert body["operator"] == "user-7"
    assert body["logged_in"] is False  # 过渡取值（.env），非真登录


# ------------------------------------------------------------ 管理员看全部（分角色）


def test_admin_sees_all_submitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """管理员（在 OFFICE_ADMINS 名单）出报告列表能看到所有人的已提交，不止自己的。"""
    _wire(
        monkeypatch,
        _rows(_resp("1", STATUS_SUBMITTED, "user-7"), _resp("2", STATUS_SUBMITTED, "user-9")),
        operator="boss",
        admins=("boss",),
    )
    surveys = client.get("/api/survey/list").json()["surveys"]
    assert {s["问卷ID"] for s in surveys} == {"1", "2"}


def test_admin_can_review_others_survey(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """管理员能对别人的问卷发起审核/审核通过（部门领导审下属的简化版）。"""
    fake = _wire(
        monkeypatch, _rows(_resp("1", STATUS_SUBMITTED, "user-9")), operator="boss", admins=("boss",)
    )
    body = client.post("/api/survey/review", json={"survey_ids": ["1"]}).json()
    assert body["ok"] == ["1"]
    assert fake.status_of("1") == STATUS_PENDING_REVIEW


def test_non_admin_still_scoped_to_self(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """名单外的普通估价师照旧只看自己——admin 名单不影响非管理员。"""
    _wire(
        monkeypatch,
        _rows(_resp("1", STATUS_SUBMITTED, "user-7"), _resp("2", STATUS_SUBMITTED, "user-9")),
        operator="user-7",
        admins=("boss",),
    )
    surveys = client.get("/api/survey/list").json()["surveys"]
    assert [s["问卷ID"] for s in surveys] == ["1"]


def test_me_reports_admin_flag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _rows(), operator="boss", admins=("boss",))
    assert client.get("/api/me").json()["is_admin"] is True
    _wire(monkeypatch, _rows(), operator="user-7", admins=("boss",))
    assert client.get("/api/me").json()["is_admin"] is False


def test_review_ignores_empty_ids(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空串 survey_id 被过滤，不会误命中「问卷ID 为空」的行。"""
    fake = _wire(
        monkeypatch, _rows(_resp("1", STATUS_SUBMITTED, "user-7")), operator="user-7"
    )
    body = client.post("/api/survey/review", json={"survey_ids": ["", "1"]}).json()
    assert body["ok"] == ["1"]
    assert "" not in body["results"]  # 空串被前置过滤，不进结果
    assert fake.status_of("1") == STATUS_PENDING_REVIEW
