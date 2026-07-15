"""实例模型与日期精度测试。断言值取自三份真实 Excel 的租期原文。

用户选定方案丙：有什么记什么，日期不精确的打标记，不强制补全。
"""

from datetime import date, datetime

import pytest

from src.library.model import DatePrecision, make_id, parse_lease_start
from src.model import Category


@pytest.mark.parametrize(
    ("raw", "expected_date", "expected_precision"),
    [
        # 办公：完整日期区间
        ("2026.1.15-2026.7.14", date(2026, 1, 15), DatePrecision.FULL),
        ("2025.6.1-2026.5.31", date(2025, 6, 1), DatePrecision.FULL),
        ("2025.7.8-2026.7.7", date(2025, 7, 8), DatePrecision.FULL),
        # 商业：datetime 单值，非区间
        (datetime(2025, 10, 28), date(2025, 10, 28), DatePrecision.FULL),
        (datetime(2026, 6, 18), date(2026, 6, 18), DatePrecision.FULL),
        # 农用：仅年月
        ("2025.7-2026.7", date(2025, 7, 1), DatePrecision.YEAR_MONTH),
        # 农用：仅年份 —— 9 条素材中有 2 条如此
        ("2025-2026", date(2025, 1, 1), DatePrecision.YEAR),
        # 无法解析
        ("待定", None, DatePrecision.UNKNOWN),
        (None, None, DatePrecision.UNKNOWN),
    ],
)
def test_parse_lease_start(
    raw: object, expected_date: date | None, expected_precision: DatePrecision
) -> None:
    got_date, got_precision = parse_lease_start(raw)
    assert got_date == expected_date
    assert got_precision == expected_precision


def test_make_id_full_date_uses_year_month() -> None:
    got = make_id(Category.OFFICE, date(2026, 1, 15), DatePrecision.FULL, "兴耀科创城A幢09层")
    assert got == "办公-2026-01-兴耀科创城A幢09层"


def test_make_id_year_only_degrades_to_year() -> None:
    """仅有年份时编号退化到年——月份压不出来就不要假造。"""
    got = make_id(Category.AGRICULTURAL, date(2025, 1, 1), DatePrecision.YEAR, "白浪村围垦五工段")
    assert got == "农用-2025-白浪村围垦五工段"


def test_make_id_unknown_date() -> None:
    got = make_id(Category.COMMERCIAL, None, DatePrecision.UNKNOWN, "某铺")
    assert got == "商业-日期未知-某铺"


def test_make_id_strips_whitespace_in_location() -> None:
    """农用素材的位置含多余空格：'白浪村围垦五工段   203.78亩'。"""
    got = make_id(
        Category.AGRICULTURAL, date(2025, 1, 1), DatePrecision.YEAR, "白浪村围垦五工段   203.78亩"
    )
    assert "   " not in got
