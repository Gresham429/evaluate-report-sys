"""SurveyBrokerStore 单测：内存假 client（list_records/insert_record/update_record），零网络。"""

from typing import Any

import pytest

from serverless.survey_broker.record import COL_ID, STATUS_DRAFT, STATUS_SUBMITTED
from serverless.survey_broker.store import SurveyBrokerStore

_SHEET = "实勘问卷"


class FakeClient:
    """内存版多维表：够 SurveyBrokerStore 用的 list/insert/update 三个方法。"""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def list_records(self, sheet: str) -> list[dict[str, Any]]:
        return [{"id": rid, "fields": dict(fields)} for rid, fields in self._rows.items()]

    def insert_record(self, sheet: str, fields: dict[str, Any]) -> str:
        self._seq += 1
        rid = f"rec-{self._seq}"
        self._rows[rid] = dict(fields)
        return rid

    def update_record(self, sheet: str, record_id: str, fields: dict[str, Any]) -> None:
        self._rows[record_id].update(fields)


def _content() -> dict[str, Any]:
    return {
        "basic": {"project_name": "示范项目"},
        "subjects": [],
        "subject_levels": {},
        "asset_conditions": {},
        "photos": [],
        "gps": None,
    }


def test_save_draft_new_then_load() -> None:
    store = SurveyBrokerStore(FakeClient(), _SHEET)
    survey_id = store.save_draft(
        survey_id=None,
        filler="张三",
        category="住宅",
        updated_at="2026-07-19T10:00:00",
        content=_content(),
    )
    assert survey_id  # 现生成了一个非空 ID

    loaded = store.load(survey_id)
    assert loaded["survey_id"] == survey_id
    assert loaded["status"] == STATUS_DRAFT
    assert loaded["filler"] == "张三"
    assert loaded["category"] == "住宅"
    assert loaded["content"]["basic"] == {"project_name": "示范项目"}


def test_save_draft_existing_id_updates_same_row_no_duplicate() -> None:
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)

    sid = store.save_draft(
        survey_id="q-fixed", filler="张三", category="住宅", updated_at="t1", content=_content()
    )
    again = store.save_draft(
        survey_id=sid, filler="张三", category="住宅", updated_at="t2", content=_content()
    )

    assert again == sid
    rows = client.list_records(_SHEET)
    assert len(rows) == 1  # 没有新增行——同 ID 是原地更新
    assert rows[0]["fields"][COL_ID] == sid

    loaded = store.load(sid)
    assert loaded["updated_at"] == "t2"


def test_save_draft_given_id_not_found_inserts_with_that_id() -> None:
    """给了 survey_id 但表里还没有这一行（如小程序端已经生成好 ID）→ 新插一行，沿用该 ID。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)

    sid = store.save_draft(
        survey_id="client-generated-id",
        filler="赵六",
        category="工业",
        updated_at="t1",
        content=_content(),
    )

    assert sid == "client-generated-id"
    rows = client.list_records(_SHEET)
    assert len(rows) == 1
    assert rows[0]["fields"][COL_ID] == "client-generated-id"


def test_submit_changes_status() -> None:
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    sid = store.save_draft(
        survey_id=None, filler="李四", category="工业", updated_at="t1", content=_content()
    )

    store.submit(sid)

    loaded = store.load(sid)
    assert loaded["status"] == STATUS_SUBMITTED


def test_load_unknown_raises_key_error() -> None:
    store = SurveyBrokerStore(FakeClient(), _SHEET)
    with pytest.raises(KeyError):
        store.load("no-such-id")


def test_submit_unknown_raises_key_error() -> None:
    store = SurveyBrokerStore(FakeClient(), _SHEET)
    with pytest.raises(KeyError):
        store.submit("no-such-id")
