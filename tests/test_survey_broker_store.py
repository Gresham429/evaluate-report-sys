"""SurveyBrokerStore 单测：内存假 client（list_records/insert_record/update_record），零网络。"""

from typing import Any

import pytest

import json

from serverless.survey_broker.record import (
    COL_ID,
    COL_OWNERS,
    COL_STATUS,
    STATUS_DRAFT,
    STATUS_FINALIZED,
    STATUS_PENDING_REVIEW,
    STATUS_SUBMITTED,
)
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

    def delete_record(self, sheet: str, record_id: str) -> None:
        self._rows.pop(record_id, None)


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


def test_delete_draft_removes_row() -> None:
    store = SurveyBrokerStore(FakeClient(), _SHEET)
    sid = store.save_draft(
        survey_id=None, filler="张三", category="住宅",
        updated_at="t", content=_content(),
    )
    store.delete(sid)
    with pytest.raises(KeyError):
        store.load(sid)


def test_delete_submitted_refused() -> None:
    store = SurveyBrokerStore(FakeClient(), _SHEET)
    sid = store.save_draft(
        survey_id=None, filler="张三", category="住宅",
        updated_at="t", content=_content(),
    )
    store.submit(sid)
    with pytest.raises(ValueError, match="已提交"):
        store.delete(sid)
    # 拒删后行还在
    assert store.load(sid)["status"] == STATUS_SUBMITTED


def test_delete_missing_raises_keyerror() -> None:
    store = SurveyBrokerStore(FakeClient(), _SHEET)
    with pytest.raises(KeyError):
        store.delete("ghost")


def _set_status(client: FakeClient, survey_id: str, status: str) -> None:
    """模拟办公端把某问卷改到某状态（直接改底层行）。"""
    for rec in client.list_records(_SHEET):
        if rec["fields"][COL_ID] == survey_id:
            client.update_record(_SHEET, rec["id"], {COL_STATUS: status})
            return
    raise AssertionError(f"no such survey {survey_id}")


@pytest.mark.parametrize("locked", [STATUS_PENDING_REVIEW, STATUS_FINALIZED])
def test_save_draft_refused_when_locked(locked: str) -> None:
    """已进入审核流程（待审核/已定稿）的问卷，服务端拒绝再写——护住终态锁定。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    sid = store.save_draft(
        survey_id=None, filler="张三", category="住宅", updated_at="t1", content=_content()
    )
    _set_status(client, sid, locked)
    with pytest.raises(ValueError, match=locked):
        store.save_draft(
            survey_id=sid, filler="张三", category="住宅", updated_at="t2", content=_content()
        )
    # 拒写后状态与更新时间都不动（离线补传不会把已定稿退回草稿）
    loaded = store.load(sid)
    assert loaded["status"] == locked
    assert loaded["updated_at"] == "t1"


def test_save_draft_writes_owners() -> None:
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    store.save_draft(
        survey_id=None, filler="u1", category="住宅", updated_at="t",
        content=_content(), owners=["u1", "u2"],
    )
    row = client.list_records(_SHEET)[0]
    assert json.loads(row["fields"][COL_OWNERS]) == ["u1", "u2"]


def test_save_draft_owners_default_to_filler() -> None:
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    store.save_draft(
        survey_id=None, filler="u1", category="住宅", updated_at="t", content=_content(),
    )
    row = client.list_records(_SHEET)[0]
    assert json.loads(row["fields"][COL_OWNERS]) == ["u1"]


@pytest.mark.parametrize("locked", [STATUS_PENDING_REVIEW, STATUS_FINALIZED])
def test_submit_refused_when_locked(locked: str) -> None:
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    sid = store.save_draft(
        survey_id=None, filler="李四", category="工业", updated_at="t1", content=_content()
    )
    _set_status(client, sid, locked)
    with pytest.raises(ValueError, match=locked):
        store.submit(sid)
    assert store.load(sid)["status"] == locked


# ─────────────────────────────────── 双向同步 Phase 2：手机端 save_draft 走合并

def _set_content(client: FakeClient, sid: str, content: dict[str, Any], mtime: str) -> None:
    """模拟另一设备/办公端改了线上内容 + 更新时间（直接改底层行）。"""
    from serverless.survey_broker.record import COL_CONTENT, COL_MTIME
    for rec in client.list_records(_SHEET):
        if rec["fields"][COL_ID] == sid:
            client.update_record(
                _SHEET, rec["id"],
                {COL_CONTENT: json.dumps(content, ensure_ascii=False), COL_MTIME: mtime},
            )
            return
    raise AssertionError(f"no such survey {sid}")


def _c(basic: dict[str, str]) -> dict[str, Any]:
    return {"basic": dict(basic), "subjects": [], "subject_levels": {},
            "asset_conditions": {}, "photos": [], "gps": None}


def test_save_draft_merges_different_fields_no_conflict() -> None:
    """带 base 且记录已存在：手机改 a、线上改 b → 自动合并、两处都保住。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    base = _c({"a": "1", "b": "1"})
    sid = store.save_draft(survey_id="q1", filler="u1", category="住宅",
                           updated_at="t1", content=base)
    _set_content(client, sid, _c({"a": "1", "b": "server"}), "t2")  # 线上改 b

    result = store.save_draft(survey_id="q1", filler="u1", category="住宅",
                              updated_at="t3", content=_c({"a": "phone", "b": "1"}), base=base)
    assert result == sid
    loaded = store.load(sid)
    assert loaded["content"]["basic"]["a"] == "phone"   # 手机改的保住
    assert loaded["content"]["basic"]["b"] == "server"  # 线上改的保住


def test_save_draft_conflict_raises_and_not_written() -> None:
    """同字段双改 → 抛 SurveyConflict、不写库。"""
    from serverless.survey_broker.store import SurveyConflict

    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    base = _c({"a": "1"})
    sid = store.save_draft(survey_id="q1", filler="u1", category="住宅",
                           updated_at="t1", content=base)
    _set_content(client, sid, _c({"a": "server"}), "t2")

    with pytest.raises(SurveyConflict) as ei:
        store.save_draft(survey_id="q1", filler="u1", category="住宅",
                         updated_at="t3", content=_c({"a": "phone"}), base=base)
    assert ei.value.conflicts[0]["field"] == "basic.a"
    assert store.load(sid)["content"]["basic"]["a"] == "server"  # 未写


def test_save_draft_resolutions_resolve_and_write() -> None:
    from serverless.survey_broker.store import SurveyConflict  # noqa: F401

    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    base = _c({"a": "1"})
    sid = store.save_draft(survey_id="q1", filler="u1", category="住宅",
                           updated_at="t1", content=base)
    _set_content(client, sid, _c({"a": "server"}), "t2")

    result = store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t3",
                              content=_c({"a": "phone"}), base=base,
                              resolutions={"basic.a": "final"})
    assert result == sid
    assert store.load(sid)["content"]["basic"]["a"] == "final"


def test_save_draft_base_none_is_plain_overwrite() -> None:
    """base=None（旧客户端/新草稿）→ 不合并、整份覆盖（向后兼容）。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    sid = store.save_draft(survey_id="q1", filler="u1", category="住宅",
                           updated_at="t1", content=_c({"a": "1", "b": "1"}))
    _set_content(client, sid, _c({"a": "1", "b": "server"}), "t2")
    store.save_draft(survey_id="q1", filler="u1", category="住宅",
                     updated_at="t3", content=_c({"a": "phone", "b": "1"}))  # 无 base
    loaded = store.load(sid)
    assert loaded["content"]["basic"] == {"a": "phone", "b": "1"}  # 整份覆盖，线上 b 被盖


def test_save_draft_new_record_with_base_inserts_as_is() -> None:
    """给了 base 但记录还不存在（首个草稿）→ 照旧 insert，不合并。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    result = store.save_draft(survey_id="newid", filler="u1", category="住宅",
                              updated_at="t1", content=_c({"a": "phone"}), base=_c({"a": "1"}))
    assert result == "newid"
    assert store.load("newid")["content"]["basic"] == {"a": "phone"}


# ─────────────────────────────────── 选共有人（待办#2）：owners 并集

def test_save_draft_unions_owners() -> None:
    """任何共有人都能再加：再存的 owners 与线上并集，谁都不会被挤掉。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t1",
                     content=_content(), owners=["u1", "a"])
    store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t2",
                     content=_content(), owners=["u1", "b"])
    row = client.list_records(_SHEET)[0]
    assert json.loads(row["fields"][COL_OWNERS]) == ["u1", "a", "b"]


def test_save_draft_owners_none_preserves_existing() -> None:
    """旧客户端 saveDraft 不带 owners → 保留线上现状（不被 [filler] 覆盖、不丢共有人）。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t1",
                     content=_content(), owners=["u1", "a", "b"])
    store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t2",
                     content=_content())  # owners=None
    row = client.list_records(_SHEET)[0]
    assert json.loads(row["fields"][COL_OWNERS]) == ["u1", "a", "b"]


def test_save_draft_filler_always_in_owners() -> None:
    """填报人恒在共有人内——即便传入 owners 漏了 filler。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t1",
                     content=_content(), owners=["a"])   # 漏了 filler
    owners = json.loads(client.list_records(_SHEET)[0]["fields"][COL_OWNERS])
    assert "u1" in owners and "a" in owners


def test_load_returns_owners() -> None:
    """load 回传 owners，供小程序显示已有共有人并在下次并集带上。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t1",
                     content=_content(), owners=["u1", "a"])
    assert store.load("q1")["owners"] == ["u1", "a"]


def test_list_for_user_includes_owned_not_just_created() -> None:
    """手机端「我的问卷」按共有人过滤：自己建的 + 被别人加为共有人的都在；无关的不含。"""
    client = FakeClient()
    store = SurveyBrokerStore(client, _SHEET)
    store.save_draft(survey_id="q1", filler="u1", category="住宅", updated_at="t",
                     content=_content(), owners=["u1"])
    store.save_draft(survey_id="q2", filler="u2", category="住宅", updated_at="t",
                     content=_content(), owners=["u2", "u1"])   # u2 建、把 u1 加为共有人
    store.save_draft(survey_id="q3", filler="u3", category="住宅", updated_at="t",
                     content=_content(), owners=["u3"])
    assert {r["survey_id"] for r in store.list_for_user("u1")} == {"q1", "q2"}
    assert {r["survey_id"] for r in store.list_for_user("u3")} == {"q3"}


def test_list_for_user_empty_userid_is_empty() -> None:
    store = SurveyBrokerStore(FakeClient(), _SHEET)
    assert store.list_for_user("") == []
