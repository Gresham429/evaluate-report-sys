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
    for col in ("问卷ID", "状态", "填报人", "更新时间", "类别", "问卷内容"):
        assert col in SURVEY_SHEET_FIELDS
    assert SURVEY_SHEET_FIELDS["问卷内容"] == "text"


def test_ensure_creates_all_on_empty() -> None:
    client = FakeProvisionClient()
    created = ensure_survey_sheet(client, "实勘问卷")
    assert set(created) == set(SURVEY_SHEET_FIELDS)


def test_ensure_is_idempotent() -> None:
    client = FakeProvisionClient(existing=set(SURVEY_SHEET_FIELDS))
    assert ensure_survey_sheet(client, "实勘问卷") == []
