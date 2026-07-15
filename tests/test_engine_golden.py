"""比较法引擎验收。

上一轮的教训：拿金样自己的数据算，当然能复现——那验不出"换了输入还算不算得对"。
故本文件的第一等测试是 test_swapping_instance_changes_result，而非 12 个数字。
"""

from dataclasses import replace

import pytest

from src.engine.adapter import read_instances, read_subject_levels
from src.engine.knowledge import extract_knowledge
from src.engine.methods import get_method
from src.model import Category
from tests.conftest import CASES

CATEGORIES = {"农用": Category.AGRICULTURAL, "办公": Category.OFFICE, "商业": Category.COMMERCIAL}
EQUAL_WEIGHTS = (0.333333333333333, 0.333333333333333, 0.333333333333333)

BENCHMARKS = {
    "农用": ((1410.0, 1393.89, 1393.89), 1399.26, 0.01),
    "办公": ((2.92, 2.77, 2.80), 2.83, 0.05),
    "商业": ((3.15, 3.40, 3.40), 3.32, 0.08),
}


def _compute(case: str):
    path = CASES[case]
    category = CATEGORIES[case]
    return get_method("市场比较法-2026").compute(
        read_subject_levels(path, category),
        read_instances(path, category),
        extract_knowledge(path),
        EQUAL_WEIGHTS,
    )


def test_swapping_instance_changes_result() -> None:
    """第一等测试：换掉一条实例，评估结果必须跟着变。

    这是本轮的核心能力，也是"拿金样自己的数据算"验不出的东西。
    """
    path, category = CASES["办公"], Category.OFFICE
    knowledge = extract_knowledge(path)
    subject = read_subject_levels(path, category)
    original = read_instances(path, category)
    method = get_method("市场比较法-2026")

    before = method.compute(subject, original, knowledge, EQUAL_WEIGHTS)
    assert before.评估结果 == pytest.approx(2.83)

    # 把实例A的成交价翻倍，其余不动
    swapped = (replace(original[0], 成交价=original[0].成交价 * 2), *original[1:])
    after = method.compute(subject, swapped, knowledge, EQUAL_WEIGHTS)

    assert after.评估结果 != before.评估结果, "换了实例结果却没变——引擎没在算"
    # 实例A比准价翻倍，另两条不变 → 评估结果增加 A 的比准价 × 1/3
    expected = round(before.评估结果 + before.比准价格[0] / 3, 2)
    assert after.评估结果 == pytest.approx(expected, abs=0.02)


def test_swapping_market_index_changes_result() -> None:
    """市场状况指数是人工填的——改它，结果必须跟着变。"""
    path, category = CASES["办公"], Category.OFFICE
    knowledge = extract_knowledge(path)
    subject = read_subject_levels(path, category)
    original = read_instances(path, category)
    method = get_method("市场比较法-2026")

    before = method.compute(subject, original, knowledge, EQUAL_WEIGHTS)
    bumped = (replace(original[0], 市场状况指数=110.0), *original[1:])
    after = method.compute(subject, bumped, knowledge, EQUAL_WEIGHTS)
    assert after.评估结果 > before.评估结果


@pytest.mark.parametrize("case", ["农用", "办公", "商业"])
def test_reproduces_golden_prices(case: str) -> None:
    """比准价格必须精确复现 Excel。"""
    expected, _, _ = BENCHMARKS[case]
    result = _compute(case)
    assert result.比准价格 == pytest.approx(expected, abs=0.011)


@pytest.mark.parametrize("case", ["农用", "办公", "商业"])
def test_reproduces_golden_final(case: str) -> None:
    """评估结果必须精确复现 Excel——这是报告里那个数。"""
    _, expected, _ = BENCHMARKS[case]
    assert _compute(case).评估结果 == pytest.approx(expected, abs=0.011)


@pytest.mark.parametrize("case", ["农用", "办公", "商业"])
def test_reproduces_golden_dispersion(case: str) -> None:
    _, _, expected = BENCHMARKS[case]
    assert _compute(case).离散度 == pytest.approx(expected, abs=0.011)


def test_unknown_level_raises() -> None:
    """档次不在基础表里必须报错，不得静默取默认值。

    静默归零在估价报告里是"看起来合理的假值"，比报错危险得多。
    """
    path, category = CASES["办公"], Category.OFFICE
    knowledge = extract_knowledge(path)
    subject = read_subject_levels(path, category)
    original = read_instances(path, category)
    first_factor = knowledge.factors[0].name
    broken = replace(
        original[0], 因素档次={**original[0].因素档次, first_factor: "这个档次不存在"}
    )
    with pytest.raises(ValueError, match="不在因素"):
        get_method("市场比较法-2026").compute(
            subject, (broken, *original[1:]), knowledge, EQUAL_WEIGHTS
        )


def test_weight_count_mismatch_raises() -> None:
    path, category = CASES["办公"], Category.OFFICE
    with pytest.raises(ValueError, match="权重数量"):
        get_method("市场比较法-2026").compute(
            read_subject_levels(path, category),
            read_instances(path, category),
            extract_knowledge(path),
            (0.5, 0.5),
        )
