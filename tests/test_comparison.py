"""比较法与一览表提取测试。断言值均为实测值。"""

import pytest

from src.extractor.comparison import extract_comparison, extract_subjects
from src.extractor.project import load_project
from src.model import Category
from tests.conftest import CASES


@pytest.mark.parametrize(
    ("case", "category", "price", "dispersion"),
    [
        ("农用", Category.AGRICULTURAL, 1399.26, 0.01),
        ("办公", Category.OFFICE, 2.83, 0.05),
        ("商业", Category.COMMERCIAL, 3.32, 0.08),
    ],
)
def test_extract_comparison(case: str, category: Category, price: float, dispersion: float) -> None:
    result = extract_comparison(CASES[case], category)
    assert result["unit_price"] == pytest.approx(price)
    assert result["dispersion"] == pytest.approx(dispersion)


@pytest.mark.parametrize(
    ("case", "category", "count"),
    [("农用", Category.AGRICULTURAL, 1), ("办公", Category.OFFICE, 2), ("商业", Category.COMMERCIAL, 2)],
)
def test_subject_count(case: str, category: Category, count: int) -> None:
    assert len(extract_subjects(CASES[case], category)) == count


def test_office_subjects_exact() -> None:
    subjects = extract_subjects(CASES["办公"], Category.OFFICE)
    assert subjects[0].index == 1
    assert subjects[0].address == "萧山区北干街道萧山科创中心3幢1208室"
    assert subjects[0].area == pytest.approx(356.29)
    assert subjects[0].unit_price == pytest.approx(2.83)
    assert subjects[0].annual_value == 368030
    assert subjects[1].address == "萧山区北干街道萧山科创中心3幢1206室"
    assert subjects[1].annual_value == 379506


def test_agricultural_price_is_read_not_recomputed() -> None:
    """农用一览表 K49=1400 是估价师手工取整值，与比较法 T39=1399.26 不同。

    依约束 C1，提取器必须原样读取 K 列，不得用 T39 覆盖。
    """
    subjects = extract_subjects(CASES["农用"], Category.AGRICULTURAL)
    assert subjects[0].unit_price == pytest.approx(1400.0)
    assert subjects[0].annual_value == 70000
    comparison = extract_comparison(CASES["农用"], Category.AGRICULTURAL)
    assert comparison["unit_price"] == pytest.approx(1399.26)


def test_load_project_office() -> None:
    project = load_project(CASES["办公"])
    assert project.category is Category.OFFICE
    assert project.report_no == "正恒评报字[2026]第F071号"
    assert project.has_certificate is True
    assert project.is_land is False
    assert len(project.subjects) == 2


def test_load_project_agricultural() -> None:
    project = load_project(CASES["农用"])
    assert project.is_land is True
    assert project.has_certificate is False
    assert len(project.subjects) == 1


def test_coercion_excludes_bool() -> None:
    """bool 是 int 子类，但复选框语义的 True 不该被当成数字 1。"""
    from src.extractor.comparison import _as_float, _as_int

    assert _as_int(True) == 0
    assert _as_float(True) == 0.0
    assert _as_int(5) == 5
    assert _as_float(2.83) == 2.83


def test_coercion_non_numeric_falls_back() -> None:
    """非数值退化为默认值——报告里的 0 必须有日志可查。"""
    from datetime import date

    from src.extractor.comparison import _as_float, _as_int, _as_text

    assert _as_int("abc") == 0
    assert _as_float(date(2026, 1, 1)) == 0.0
    assert _as_int(None) == 0
    assert _as_text(None) == ""
    assert _as_text("  甲  ") == "甲"
