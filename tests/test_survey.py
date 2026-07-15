"""实勘表提取器测试。断言值均为三份真实 Excel 的实测值。"""

from datetime import date

import pytest

from src.extractor.survey import excel_serial_to_date, extract_survey
from src.model import Category
from tests.conftest import CASES


def test_excel_serial_to_date() -> None:
    assert excel_serial_to_date(46132) == date(2026, 4, 20)
    assert excel_serial_to_date(46107) == date(2026, 3, 26)
    assert excel_serial_to_date(46106) == date(2026, 3, 25)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("农用", Category.AGRICULTURAL),
        ("办公", Category.OFFICE),
        ("商业", Category.COMMERCIAL),
    ],
)
def test_category_detected(case: str, expected: Category) -> None:
    assert extract_survey(CASES[case])["category"] is expected


@pytest.mark.parametrize(
    ("case", "field", "expected"),
    [
        ("农用", "report_no", "正恒评报字[2026]第F093号"),
        ("办公", "report_no", "正恒评报字[2026]第F071号"),
        ("商业", "report_no", "正恒评报字[2026]第F098号"),
        ("农用", "client", "杭州市钱塘区义蓬街道义蓬村股份经济合作社"),
        ("办公", "client", "杭州市萧山区机关事务服务中心"),
        ("办公", "owner", "杭州萧山国有资产投资有限公司"),
        ("农用", "usage", "农用地（耕地）"),
        ("办公", "usage", "办公"),
        ("商业", "usage", "商业"),
        ("农用", "certificate_status", "估价对象未取得《不动产权证》"),
        ("办公", "certificate_status", "估价对象已取得《不动产权证》"),
        ("商业", "certificate_status", "估价对象未取得《不动产权证》"),
    ],
)
def test_field_values(case: str, field: str, expected: str) -> None:
    assert extract_survey(CASES[case])[field] == expected


@pytest.mark.parametrize(
    ("case", "expected"),
    [("农用", "2026-04-20"), ("办公", "2026-03-26"), ("商业", "2026-03-25")],
)
def test_value_date_converted(case: str, expected: str) -> None:
    assert extract_survey(CASES[case])["value_date"] == expected


@pytest.mark.parametrize(
    ("case", "expected"),
    [("农用", "郑伟娜"), ("办公", "胡柯"), ("商业", "郑伟娜")],
)
def test_surveyor_extracted(case: str, expected: str) -> None:
    """现场查勘记录人员由估价师手工录入 D46。"""
    assert extract_survey(CASES[case])["surveyor"] == expected
