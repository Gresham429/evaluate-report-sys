"""问卷读取后端跑假客户端：序列化往返、只列已提交、按 ID 取。"""

import json

import pytest

from src.questionnaire.backend import SurveyPullBackend, response_to_fields
from src.questionnaire.model import (
    STATUS_DRAFT,
    STATUS_SUBMITTED,
    SurveyResponse,
)


class FakeNotableClient:
    """内存版：list/insert 与真客户端同签名。"""

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


def _resp(qid: str, 状态: str) -> SurveyResponse:
    return SurveyResponse(
        问卷ID=qid,
        状态=状态,
        填报人="u1",
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
