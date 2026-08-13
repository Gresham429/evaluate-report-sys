"""问卷读取后端跑假客户端：序列化往返、只列已提交、按 ID 取。"""

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
        """测试探针：按问卷ID读当前状态（校验批量改状态真落了库）。"""
        for r in self.rows.get(sheet, []):
            if r["fields"].get("问卷ID") == qid:  # type: ignore[union-attr]
                return str(r["fields"].get("状态", ""))  # type: ignore[union-attr]
        raise KeyError(qid)


def _resp(qid: str, 状态: str, filler: str = "u1") -> SurveyResponse:
    return SurveyResponse(
        问卷ID=qid,
        状态=状态,
        填报人=filler,
        更新时间="2026-07-19T10:00:00",
        category="办公",
        basic={"report_no": f"R-{qid}", "client": "甲"},
        subjects=({"index": 1, "owner": "乙", "address": "A", "usage": "办公",
                   "area": 100.0},),
        subject_levels={"楼层": "中"},
        asset_conditions={"楼层": "6/20"},
        photos=("p1.jpg",),
        gps={"lat": 30.0, "lng": 120.0},
    )


SHEET = "实勘问卷"


def _seed(client: FakeNotableClient, response: SurveyResponse) -> None:
    client.insert_records(SHEET, [response_to_fields(response)])


def test_response_to_fields_shape() -> None:
    fields = response_to_fields(_resp("1", STATUS_SUBMITTED))
    assert fields["问卷ID"] == "1"
    assert fields["状态"] == STATUS_SUBMITTED
    assert fields["类别"] == "办公"
    content = json.loads(fields["问卷内容"])
    assert content["basic"] == {"report_no": "R-1", "client": "甲"}
    assert content["subject_levels"] == {"楼层": "中"}
    assert content["photos"] == ["p1.jpg"]
    assert content["gps"] == {"lat": 30.0, "lng": 120.0}


def test_list_submitted_filters_drafts() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED))
    _seed(client, _resp("2", STATUS_DRAFT))
    _seed(client, _resp("3", STATUS_SUBMITTED))
    infos = SurveyPullBackend(client, SHEET).list_submitted()
    assert {i.问卷ID for i in infos} == {"1", "3"}
    assert all(i.category == "办公" for i in infos)


def test_load_roundtrip() -> None:
    client = FakeNotableClient()
    original = _resp("42", STATUS_SUBMITTED)
    _seed(client, original)
    loaded = SurveyPullBackend(client, SHEET).load("42")
    assert loaded == original


def test_load_missing_raises_keyerror() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED))
    with pytest.raises(KeyError):
        SurveyPullBackend(client, SHEET).load("nope")


def test_load_draft_not_visible() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_DRAFT))
    with pytest.raises(KeyError):
        SurveyPullBackend(client, SHEET).load("1")


def test_load_bad_json_raises_valueerror() -> None:
    client = FakeNotableClient()
    client.insert_records(SHEET, [{
        "问卷ID": "1", "状态": STATUS_SUBMITTED, "填报人": "u",
        "更新时间": "t", "类别": "办公", "问卷内容": "{坏 json",
    }])
    with pytest.raises(ValueError):
        SurveyPullBackend(client, SHEET).load("1")


# ---------------------------------------------------------------- 权限「只看自己」


def test_list_submitted_filters_by_filler() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u2"))
    infos = SurveyPullBackend(client, SHEET).list_submitted("u1")
    assert {i.问卷ID for i in infos} == {"1"}


def test_list_submitted_none_filler_lists_all() -> None:
    """filler=None 不过滤——保留旧调用方（无登录上下文的测试/工具）行为。"""
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u2"))
    infos = SurveyPullBackend(client, SHEET).list_submitted()
    assert {i.问卷ID for i in infos} == {"1", "2"}


def test_list_pending_scoped_to_filler() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_PENDING_REVIEW, "u1"))
    _seed(client, _resp("2", STATUS_PENDING_REVIEW, "u2"))
    _seed(client, _resp("3", STATUS_SUBMITTED, "u1"))  # 未发起审核，不进待审核列表
    infos = SurveyPullBackend(client, SHEET).list_pending("u1")
    assert {i.问卷ID for i in infos} == {"1"}


def test_load_rejects_other_filler() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    backend = SurveyPullBackend(client, SHEET)
    assert backend.load("1", "u1").问卷ID == "1"
    with pytest.raises(KeyError):
        backend.load("1", "u2")


# ---------------------------------------------------------------- 审核 / 定稿 批量


def test_review_moves_submitted_to_pending() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u1"))
    backend = SurveyPullBackend(client, SHEET)
    result = backend.review(["1", "2"], "u1")
    assert result == {"1": "ok", "2": "ok"}
    assert client.status_of(SHEET, "1") == STATUS_PENDING_REVIEW
    assert client.status_of(SHEET, "2") == STATUS_PENDING_REVIEW
    assert {i.问卷ID for i in backend.list_pending("u1")} == {"1", "2"}
    assert backend.list_submitted("u1") == []


def test_review_skips_wrong_status_other_filler_and_unknown() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, "u1"))
    _seed(client, _resp("2", STATUS_PENDING_REVIEW, "u1"))  # 已在审核中
    _seed(client, _resp("3", STATUS_SUBMITTED, "u2"))  # 别人的
    backend = SurveyPullBackend(client, SHEET)
    result = backend.review(["1", "2", "3", "nope"], "u1")
    assert result["1"] == "ok"
    assert result["2"] != "ok"  # 非「已提交」，跳过
    assert result["3"] == "未找到"  # 非本人 → 当作不存在（不泄露他人问卷存在性）
    assert result["nope"] == "未找到"
    # 只有 1 变了；2/3 状态不动
    assert client.status_of(SHEET, "1") == STATUS_PENDING_REVIEW
    assert client.status_of(SHEET, "2") == STATUS_PENDING_REVIEW
    assert client.status_of(SHEET, "3") == STATUS_SUBMITTED


def test_empty_filler_is_fail_closed() -> None:
    """操作人识别不出（filler=""）→ 什么都看不到、什么都改不了。"""
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_SUBMITTED, ""))  # 连填报人也空（未登录手机提交的）
    _seed(client, _resp("2", STATUS_PENDING_REVIEW, "u1"))
    backend = SurveyPullBackend(client, SHEET)
    assert backend.list_submitted("") == []
    assert backend.list_pending("") == []
    with pytest.raises(KeyError):
        backend.load("1", "")
    result = backend.review(["1"], "")
    assert result == {"1": "未找到"}
    assert client.status_of(SHEET, "1") == STATUS_SUBMITTED  # 没被动


def test_finalize_moves_pending_to_finalized() -> None:
    client = FakeNotableClient()
    _seed(client, _resp("1", STATUS_PENDING_REVIEW, "u1"))
    _seed(client, _resp("2", STATUS_SUBMITTED, "u1"))  # 还没发起审核，不能直接定稿
    backend = SurveyPullBackend(client, SHEET)
    result = backend.finalize(["1", "2"], "u1")
    assert result["1"] == "ok"
    assert result["2"] != "ok"  # 非「待审核」，跳过
    assert client.status_of(SHEET, "1") == STATUS_FINALIZED
    assert client.status_of(SHEET, "2") == STATUS_SUBMITTED
    assert backend.list_pending("u1") == []
