"""条件组句测试。灵活性来自数据差异，非模型随机性。"""

from src.extractor.project import load_project
from src.prose.composer import compose
from tests.conftest import CASES


def test_agricultural_scope_is_land() -> None:
    result = compose(load_project(CASES["农用"]))
    assert "包含土地使用权" in result["估价范围"]
    assert "房屋" not in result["估价范围"]


def test_office_scope_is_building() -> None:
    result = compose(load_project(CASES["办公"]))
    assert "包含房屋及其分摊建设用地使用权" in result["估价范围"]
    assert "网费、物业费" in result["估价范围"]


def test_certificate_conditional() -> None:
    assert compose(load_project(CASES["办公"]))["权证"] == "估价对象已取得《不动产权证》"
    assert compose(load_project(CASES["农用"]))["权证"] == "估价对象未取得《不动产权证》"


def test_materials_list_follows_certificate() -> None:
    """资料清单与权证由同一条件驱动，必须联动。"""
    office = compose(load_project(CASES["办公"]))
    assert "《不动产权证》" in office["资料清单"]
    agri = compose(load_project(CASES["农用"]))
    assert "《不动产权证》" not in agri["资料清单"]


def test_attachment_item_three_follows_certificate() -> None:
    """附件清单第三项与正文资料清单由同一条件驱动。"""
    office = compose(load_project(CASES["办公"]))
    assert office["附件清单第三项"] == "三、《委托评估协议书》、《不动产权证》复印件"
    agri = compose(load_project(CASES["农用"]))
    assert agri["附件清单第三项"] == "三、《委托评估协议书》复印件"


def test_units_by_category() -> None:
    agri = compose(load_project(CASES["农用"]))
    assert agri["面积单位"] == "亩"
    assert agri["单价单位"] == "元/亩·年"
    office = compose(load_project(CASES["办公"]))
    assert office["面积单位"] == "㎡"
    assert office["单价单位"] == "元/㎡·天"


def test_surveyor_credited_when_not_registered_appraiser() -> None:
    """农用/商业 D46=郑伟娜，非抬头注册估价师 → 须署名。"""
    for case in ("农用", "商业"):
        result = compose(load_project(CASES[case]))
        assert "及现场查勘记录人员郑伟娜" in result["查勘人署名"]


def test_surveyor_omitted_when_is_registered_appraiser() -> None:
    """办公 D46=胡柯，本身就是抬头的注册估价师 → 抬头已署名，正文不再提。"""
    result = compose(load_project(CASES["办公"]))
    assert "现场查勘记录人员" not in result["查勘人署名"]
    assert "胡柯" not in result["查勘人署名"]


def test_needs_surveyor_credit_ignores_name_spacing() -> None:
    """报告抬头写「韩  伟」，实勘表录「韩伟」，比对须去空格。"""
    from src.prose.composer import needs_surveyor_credit

    copy = {"registered_appraisers": ["韩伟", "胡柯"]}
    assert needs_surveyor_credit("韩  伟", copy) is False
    assert needs_surveyor_credit("胡柯", copy) is False
    assert needs_surveyor_credit("郑伟娜", copy) is True
    assert needs_surveyor_credit("", copy) is False


def test_compose_is_deterministic() -> None:
    """同一输入必须永远产出同一输出（约束 C2）。"""
    project = load_project(CASES["商业"])
    assert compose(project) == compose(project)
