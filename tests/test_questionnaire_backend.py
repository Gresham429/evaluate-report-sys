"""问卷读取后端跑假客户端：序列化往返 + 按「共有人」逐份判可见/可编辑/可定稿。"""

import json

import pytest

from src.questionnaire.backend import SurveyPullBackend, response_to_fields
from src.questionnaire.model import (
    STATUS_DRAFT,
    STATUS_FINALIZED,
    STATUS_PENDING_REVIEW,
    STATUS_SUBMITTED,
    SurveyResponse,
)
from src.questionnaire.permissions import Viewer

# 常用判定上下文
ADMIN = Viewer(operator="root", is_admin=True)


def U(op: str, *subs: str) -> Viewer:
    """普通登录人（可带下属集，模拟部门主管）。"""
    return Viewer(operator=op, subordinates=frozenset(subs))


class FakeNotableClient:
    """内存版：list/insert/update 与真客户端同签名。"""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {}
        self._n = 0

    def list_records(self, sheet: str) -> list[dict[str, object]]:
        return [dict(r, fields=dict(r["fields"])) for r in self.rows.get(sheet, [])]

    def insert_records(self, sheet: str, fields_list: list[dict[str, object]]) -> list[str]:
        ids = []
        for fields in fields_list:
            self._n += 1
            rid = f"r{self._n}"
            self.rows.setdefault(sheet, []).append({"id": rid, "fields": dict(fields)})
            ids.append(rid)
        return ids

    def update_record(self, sheet: str, record_id: str, fields: dict[str, object]) -> None:
        for r in self.rows.get(sheet, []):
            if r["id"] == record_id:
                r["fields"].update(fields)  # type: ignore[union-attr]
                return
        raise KeyError(record_id)

    def status_of(self, sheet: str, qid: str) -> str:
        for r in self.rows.get(sheet, []):
            if r["fields"].get("问卷ID") == qid:  # type: ignore[union-attr]
                return str(r["fields"].get("状态", ""))  # type: ignore[union-attr]
        raise KeyError(qid)


def _resp(qid: str, 状态: str, filler: str = "u1", owners: tuple[str, ...] | None = None) -> SurveyResponse:
    return SurveyResponse(
        问卷ID=qid,
        状态=状态,
        填报人=filler,
        共有人=owners if owners is not None else (filler,),
        更新时间="2026-07-19T10:00:00",
        category="办公",
        basic={"report_no": f"R-{qid}", "client": "甲"},
        subjects=({"index": 1, "owner": "乙", "address": "A", "usage": "办公", "area": 100.0},),
        subject_levels={"楼层": "中"},
        asset_conditions={"楼层": "6/20"},
        photos=("p1.jpg",),
        gps={"lat": 30.0, "lng": 120.0},
    )


SHEET = "实勘问卷"


def _seed(client: FakeNotableClient, response: SurveyResponse) -> None:
    client.insert_records(SHEET, [response_to_fields(response)])


# ---------------------------------------------------------------- 序列化 / 状态过滤


def test_response_to_fields_shape() -> None:
    fields = response_to_fields(_resp("1", STATUS_SUBMITTED))
    assert fields["问卷ID"] == "1"
    assert fields["状态"] == STATUS_SUBMITTED
    assert fields["类别"] == "办公"
    content = json.loads(fields["问卷内容"])
    assert content["basic"] == {"report_no": "R-1", "client": "甲"}
    assert content["subject_levels"] == {"楼层": "中"}
    assert content["gps"] == {"lat": 30.0, "lng": 120.0}


def test_list_submitted_filters_drafts() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED))
    _seed(client, _resp("2", STATUS_DRAFT))
    _seed(client, _resp("3", STATUS_SUBMITTED))
    infos = SurveyPullBackend(client, SHEET).list_submitted(ADMIN)
    assert {i.问卷ID for i in infos} == {"1", "3"}


def test_load_roundtrip() -> None:
    client = FakeNotableClient()
    original = _resp("42", STATUS_SUBMITTED)
    _seed(client, original)
    assert SurveyPullBackend(client, SHEET).load("42", ADMIN) == original


def test_load_missing_raises_keyerror() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED))
    with pytest.raises(KeyError):
        SurveyPullBackend(client, SHEET).load("nope", ADMIN)


def test_load_draft_not_visible() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_DRAFT))
    with pytest.raises(KeyError):
        SurveyPullBackend(client, SHEET).load("1", ADMIN)  # 草稿不出（状态过滤）


def test_load_bad_json_raises_valueerror() -> None:
    client = FakeNotableClient()
    client.insert_records(SHEET, [{
        "问卷ID": "1", "状态": STATUS_SUBMITTED, "填报人": "u", "共有人": '["u"]',
        "更新时间": "t", "类别": "办公", "问卷内容": "{坏 json",
    }])
    with pytest.raises(ValueError):
        SurveyPullBackend(client, SHEET).load("1", ADMIN)


# ---------------------------------------------------------------- 可见（读）：共有人 / 管理员


def test_owner_sees_only_own() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u2"))
    assert {i.问卷ID for i in SurveyPullBackend(client, SHEET).list_submitted(U("u1"))} == {"1"}


def test_admin_lists_all() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u2"))
    assert {i.问卷ID for i in SurveyPullBackend(client, SHEET).list_submitted(ADMIN)} == {"1", "2"}


def test_coowner_and_leader_can_see() -> None:
    client = FakeNotableClient()
    # 问卷 1 的共有人是 u1、u2（跨部门共有）
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1", owners=("u1", "u2")))
    b = SurveyPullBackend(client, SHEET)
    assert {i.问卷ID for i in b.list_submitted(U("u2"))} == {"1"}          # 共有人之一
    assert {i.问卷ID for i in b.list_submitted(U("boss", "u2"))} == {"1"}  # u2 的上级
    assert b.list_submitted(U("stranger")) == []                          # 无关的人看不到


def test_list_pending_scoped() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_PENDING_REVIEW, "u1"))
    _seed(client, _resp("2", STATUS_PENDING_REVIEW, "u2"))
    _seed(client, _resp("3", STATUS_SUBMITTED, "u1"))
    assert {i.问卷ID for i in SurveyPullBackend(client, SHEET).list_pending(U("u1"))} == {"1"}


def test_load_rejects_non_visible() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    b = SurveyPullBackend(client, SHEET)
    assert b.load("1", U("u1")).问卷ID == "1"
    with pytest.raises(KeyError):
        b.load("1", U("u2"))


def test_unidentified_fail_closed() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, ""))  # 填报人也空
    b = SurveyPullBackend(client, SHEET)
    assert b.list_submitted(U("")) == []
    with pytest.raises(KeyError):
        b.load("1", U(""))
    assert b.review(["1"], U("")) == {"1": "未找到"}


# ---------------------------------------------------------------- 发起审核（owner）/ 定稿（上级/管理员）


def test_owner_reviews_own_submitted() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u1"))
    b = SurveyPullBackend(client, SHEET)
    assert b.review(["1", "2"], U("u1")) == {"1": "ok", "2": "ok"}
    assert client.status_of(SHEET, "1") == STATUS_PENDING_REVIEW
    assert {i.问卷ID for i in b.list_pending(U("u1"))} == {"1", "2"}


def test_review_skips_wrong_status_others_and_unknown() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_PENDING_REVIEW, "u1"))  # 已在审核中
    _seed(client, _resp("3", STATUS_SUBMITTED, "u2"))  # 别人的
    result = SurveyPullBackend(client, SHEET).review(["1", "2", "3", "nope"], U("u1"))
    assert result["1"] == "ok"
    assert result["2"] != "ok"  # 非「已提交」
    assert result["3"] == "未找到"  # 非共有人 → 当不存在
    assert result["nope"] == "未找到"
    assert client.status_of(SHEET, "3") == STATUS_SUBMITTED


def test_owner_cannot_finalize_own() -> None:
    """定稿要上级/管理员——owner 定不了自己的（发起与批准分离）。"""
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_PENDING_REVIEW, "u1"))
    result = SurveyPullBackend(client, SHEET).finalize(["1"], U("u1"))
    assert result["1"] == "未找到"  # owner 无定稿权 → 当不存在
    assert client.status_of(SHEET, "1") == STATUS_PENDING_REVIEW  # 没被动


def test_leader_finalizes_but_cannot_review() -> None:
    """上级能定稿、但不能发起审核（不改内容）。"""
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_PENDING_REVIEW, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u1"))
    boss = U("boss", "u1")  # boss 是 u1 的上级
    assert SurveyPullBackend(client, SHEET).finalize(["1"], boss) == {"1": "ok"}
    assert client.status_of(SHEET, "1") == STATUS_FINALIZED
    # 上级去发起审核(已提交→待审核)→ 无编辑权 → 未找到
    assert SurveyPullBackend(client, SHEET).review(["2"], boss) == {"2": "未找到"}
    assert client.status_of(SHEET, "2") == STATUS_SUBMITTED


def test_admin_finalizes() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_PENDING_REVIEW, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u1"))  # 非待审核
    result = SurveyPullBackend(client, SHEET).finalize(["1", "2"], ADMIN)
    assert result["1"] == "ok"
    assert result["2"] != "ok"  # 非「待审核」
    assert client.status_of(SHEET, "1") == STATUS_FINALIZED
