from pathlib import Path

import pytest

from src.extractor.condition import SurveyCondition, read_survey_conditions

MATERIALS = Path(__file__).resolve().parents[1].parent / "案例素材"
OFFICE = MATERIALS / "办公" / "办公实勘表、比较法.xlsx"
FARMLAND = MATERIALS / "农用" / "农用地实勘表、比较法.xlsx"

pytestmark = pytest.mark.skipif(not OFFICE.exists(), reason="需要 案例素材 真 Excel")


def test_reads_grouped_per_factor_descriptions() -> None:
    conds = read_survey_conditions(OFFICE)
    by_factor = {c.factor: c for c in conds}
    # 区位组的一个因素，描述取自 D 列
    assert by_factor["楼层"].group == "区位状况"
    assert "第十二层" in by_factor["楼层"].description
    # 实物、权益各命中一个，组名按前缀归一（办公 A 列写「权益状况(二)」）
    assert by_factor["建筑结构"].group == "实物状况"
    assert by_factor["使用限制"].group == "权益状况"


def test_every_condition_has_group_and_factor() -> None:
    conds = read_survey_conditions(OFFICE)
    assert conds, "至少应读到若干因素"
    assert all(c.group in ("区位状况", "实物状况", "权益状况") for c in conds)
    assert all(c.factor for c in conds)


def _has_cjk(text: str) -> bool:
    """检测文字中是否含有 CJK 字符。"""
    return any('一' <= ch <= '鿿' for ch in text)


@pytest.mark.skipif(not FARMLAND.exists(), reason="需要 农用 案例素材")
def test_skips_template_junk_rows() -> None:
    """实勘表的模板残留行（因素名无 CJK，如 "0"）应被跳过。"""
    conds = read_survey_conditions(FARMLAND)
    assert conds, "农用地实勘表应读到若干因素"
    # 不应含名为 "0" 的因素（模板残留）
    assert all(c.factor != "0" for c in conds), "应跳过因素名为 '0' 的模板残留行"
    # 所有因素名都应含 CJK 字符（真实因素都是中文）
    assert all(_has_cjk(c.factor) for c in conds), "所有因素名应含 CJK 字符，跳过模板残留的纯数字/符号行"
