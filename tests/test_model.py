"""数据模型测试。"""

import pytest

from src.model import Category, Project, Subject


def _project(**overrides: object) -> Project:
    base: dict[str, object] = {
        "category": Category.OFFICE,
        "report_no": "正恒评报字[2026]第F071号",
        "project_name": "测试项目",
        "client": "杭州市萧山区机关事务服务中心",
        "client_address": "地址",
        "legal_rep": "张三",
        "purpose": "评估房地产租赁价值",
        "survey_date": "2026-03-26",
        "value_date": "2026-03-26",
        "materials": "《不动产权证》",
        "certificate_status": "估价对象已取得《不动产权证》",
        "owner": "杭州萧山国有资产投资有限公司",
        "address": "萧山区北干街道萧山科创中心",
        "usage": "办公",
        "scale": "房屋建筑面积723.69平方米",
        "scope": "包含房屋及其分摊建设用地使用权",
        "current_status": "至价值时点，估价对象处于空置状态。",
        "work_period": "2026年1月14日至2026年1月20日",
        "issue_date": "2026-06-05",
        "surveyor": "郑伟娜",
        "unit_price": 2.83,
        "dispersion": 0.05,
        "subjects": (),
    }
    base.update(overrides)
    return Project(**base)  # type: ignore[arg-type]


def test_subject_is_frozen() -> None:
    s = Subject(
        index=1, owner="甲", address="乙", usage="办公",
        area=356.29, unit_price=2.83, annual_value=368030,
    )
    with pytest.raises(AttributeError):
        s.area = 1.0  # type: ignore[misc]


def test_office_is_not_land() -> None:
    assert _project().is_land is False


def test_agricultural_is_land() -> None:
    assert _project(category=Category.AGRICULTURAL).is_land is True


def test_has_certificate_true() -> None:
    assert _project().has_certificate is True


def test_has_certificate_false() -> None:
    p = _project(certificate_status="估价对象未取得《不动产权证》")
    assert p.has_certificate is False


def test_category_values() -> None:
    assert Category.AGRICULTURAL == "农用"
    assert Category.OFFICE == "办公"
    assert Category.COMMERCIAL == "商业"
