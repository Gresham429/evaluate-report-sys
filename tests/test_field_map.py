"""字段映射与类别识别测试。"""

import pytest

from src.extractor.field_map import (
    RESULT_FIRST_ROW,
    RESULT_HEADER_ROW,
    SURVEY_FIELDS,
    comparison_sheet_name,
    detect_category,
    survey_sheet_name,
)
from src.model import Category


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("农用地房地产实地查勘记录表", Category.AGRICULTURAL),
        ("办公房地产实地查勘记录表", Category.OFFICE),
        ("商业房地产实地查勘记录表", Category.COMMERCIAL),
    ],
)
def test_detect_category(title: str, expected: Category) -> None:
    assert detect_category(title) is expected


def test_detect_category_unknown_raises() -> None:
    with pytest.raises(ValueError, match="无法识别类别"):
        detect_category("工业房地产实地查勘记录表")


def test_survey_sheet_name_office_is_prefixed() -> None:
    assert survey_sheet_name(Category.OFFICE) == "办公房地产实地查勘记录表"


def test_survey_sheet_name_others_unprefixed() -> None:
    assert survey_sheet_name(Category.AGRICULTURAL) == "房地产实地查勘记录表"
    assert survey_sheet_name(Category.COMMERCIAL) == "房地产实地查勘记录表"


def test_comparison_sheet_name() -> None:
    assert comparison_sheet_name(Category.OFFICE) == "办公房地产比较法"
    assert comparison_sheet_name(Category.AGRICULTURAL) == "房地产比较法"
    assert comparison_sheet_name(Category.COMMERCIAL) == "房地产比较法"


def test_survey_fields_cover_spec() -> None:
    assert SURVEY_FIELDS["report_no"] == "H2"
    assert SURVEY_FIELDS["client"] == "C3"
    assert SURVEY_FIELDS["certificate_status"] == "C10"
    assert SURVEY_FIELDS["owner"] == "C11"
    assert SURVEY_FIELDS["usage"] == "C13"
    assert SURVEY_FIELDS["current_status"] == "C16"
    assert SURVEY_FIELDS["surveyor"] == "D46"


def test_result_table_rows() -> None:
    assert RESULT_HEADER_ROW == 48
    assert RESULT_FIRST_ROW == 49
