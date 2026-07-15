"""字段映射与类别识别测试。"""

import pytest

from src.extractor.field_map import (
    COMPARISON_FIELDS,
    RESULT_COLUMNS,
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


def test_survey_fields_complete() -> None:
    """全部 19 个实勘表坐标。写错一个，提取出的报告数据就是错的。"""
    assert SURVEY_FIELDS == {
        "project_name": "C2",
        "client": "C3",
        "client_address": "C4",
        "legal_rep": "C5",
        "purpose": "C6",
        "survey_date": "C7",
        "value_date": "C8",
        "materials": "C9",
        "certificate_status": "C10",
        "owner": "C11",
        "address": "C12",
        "usage": "C13",
        "scale": "C14",
        "scope": "C15",
        "current_status": "C16",
        "surveyor": "D46",
        "report_no": "H2",
        "work_period": "H3",
        "issue_date": "H4",
    }


def test_comparison_fields_complete() -> None:
    """比较法坐标。T39 是评估结果单价，X37 是比准价格离散度。"""
    assert COMPARISON_FIELDS == {"unit_price": "T39", "dispersion": "X37"}


def test_result_columns() -> None:
    """一览表列序：序号, 权利人, 地址, 用途, 面积, 单价, 年租赁价值。"""
    assert RESULT_COLUMNS == (6, 7, 8, 9, 10, 11, 12)


def test_result_table_rows() -> None:
    assert RESULT_HEADER_ROW == 48
    assert RESULT_FIRST_ROW == 49
