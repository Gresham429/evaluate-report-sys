"""实勘问卷表结构：ensure 建齐六列、幂等。"""

from src.questionnaire.provision import SURVEY_SHEET_FIELDS, ensure_survey_sheet


class FakeProvisionClient:
    """记录已存在字段，模拟 ensure_fields 只建缺的。"""

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = set(existing or set())

    def ensure_fields(self, sheet: str, specs: dict[str, str]) -> list[str]:
        created = [name for name in specs if name not in self.existing]
        self.existing.update(created)
        return created


def test_fields_cover_flat_columns_and_json() -> None:
    for col in ("问卷ID", "状态", "填报人", "共有人", "更新时间", "类别", "问卷内容"):
        assert col in SURVEY_SHEET_FIELDS
    assert SURVEY_SHEET_FIELDS["问卷内容"] == "text"


def test_provision_covers_every_written_column() -> None:
    """建表清单必须覆盖 response_to_fields 实际写入的每一列——否则真机写入 404
    「fail to find field」（「共有人」漏建就让 saveDraft 全 500，2026-08-15 真机栽过）。"""
    from src.questionnaire.backend import response_to_fields
    from src.questionnaire.model import SurveyResponse

    r = SurveyResponse(问卷ID="q", 状态="草稿", 填报人="u", 更新时间="t", category="办公",
                       basic={}, subjects=(), subject_levels={}, asset_conditions={}, photos=())
    written = set(response_to_fields(r).keys())
    missing = written - set(SURVEY_SHEET_FIELDS)
    assert not missing, f"建表清单漏了这些写入列：{missing}"


def test_ensure_creates_all_on_empty() -> None:
    client = FakeProvisionClient()
    created = ensure_survey_sheet(client, "实勘问卷")
    assert set(created) == set(SURVEY_SHEET_FIELDS)


def test_ensure_is_idempotent() -> None:
    client = FakeProvisionClient(existing=set(SURVEY_SHEET_FIELDS))
    assert ensure_survey_sheet(client, "实勘问卷") == []
