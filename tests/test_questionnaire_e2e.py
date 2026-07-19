"""端到端：一行假『已提交』记录 → 拉取 → 映射 → payload 可被办公端还原。

不触真库、不落盘。锁的是五个组件串起来对得上办公 /api/extract 契约。
"""

from src.model import Category
from src.questionnaire.backend import SurveyPullBackend, response_to_fields
from src.questionnaire.model import STATUS_SUBMITTED, SurveyResponse
from src.questionnaire.prefill import survey_to_prefill


class FakeNotableClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {}

    def list_records(self, sheet: str) -> list[dict[str, object]]:
        return [dict(r, fields=dict(r["fields"])) for r in self.rows.get(sheet, [])]

    def insert_records(self, sheet: str, fields_list: list[dict[str, object]]) -> list[str]:
        for i, fields in enumerate(fields_list):
            self.rows.setdefault(sheet, []).append({"id": f"r{i}", "fields": dict(fields)})
        return [f"r{i}" for i in range(len(fields_list))]


SHEET = "实勘问卷"


def _submitted() -> SurveyResponse:
    return SurveyResponse(
        问卷ID="q-end",
        状态=STATUS_SUBMITTED,
        填报人="u1",
        更新时间="2026-07-19T10:00:00",
        category="办公",
        basic={"report_no": "R-1", "client": "甲", "owner": "乙",
               "usage": "办公", "value_date": "2026-04-20"},
        subjects=({"index": 1, "owner": "乙", "address": "A 路 1 号",
                   "usage": "办公", "area": 100.0},),
        subject_levels={"楼层": "中", "临街状况": "优"},
        asset_conditions={"楼层": "6/20", "临街状况": "临主干道"},
        photos=("p1.jpg",),
    )


def test_end_to_end_submitted_to_prefill() -> None:
    client = FakeNotableClient()
    client.insert_records(SHEET, [response_to_fields(_submitted())])

    backend = SurveyPullBackend(client, SHEET)
    infos = backend.list_submitted()
    assert [i.问卷ID for i in infos] == ["q-end"]

    response = backend.load("q-end")
    out = survey_to_prefill(response)
    project = out["project"]

    # payload 满足办公端 _project_from_payload 的硬前置
    assert isinstance(project["subjects"], list)
    Category(project["category"])  # 合法枚举值，否则抛
    assert project["report_no"] == "R-1"
    assert out["subject_levels"]["楼层"] == "中"
    assert out["asset_conditions"]["临街状况"] == "临主干道"
    assert out["photos"] == ["p1.jpg"]
    # 五项必填齐全 → 无 MISSING_FIELD
    assert all(w["code"] != "MISSING_FIELD" for w in out["warnings"])
