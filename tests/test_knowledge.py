"""基础表知识提取测试。断言值均为三份真实 Excel 的实测值。

新 C1：基础表的知识（因素/档次/系数/分值）是既定正确的，系统只读不改。
"""

import pytest

from src.engine.knowledge import extract_knowledge
from tests.conftest import CASES


@pytest.mark.parametrize(("case", "count"), [("农用", 27), ("办公", 28), ("商业", 28)])
def test_factor_count(case: str, count: int) -> None:
    """三类的因素数不同——农用 27，办公与商业 28。"""
    assert len(extract_knowledge(CASES[case]).factors) == count


@pytest.mark.parametrize("case", ["农用", "办公", "商业"])
def test_score_scale(case: str) -> None:
    """分值标尺三类一致：好→差 = 2/1/0/-1/-2。"""
    assert extract_knowledge(CASES[case]).scores == (2, 1, 0, -1, -2)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("农用", (2, 1, 2, 1, 2, 0)),
        ("办公", (1, 1, 2, 2, 1, 3)),
        ("商业", (2, 2, 2, 0, 1, 2)),
    ],
)
def test_coefficients_differ_by_category(case: str, expected: tuple[int, ...]) -> None:
    """每类的修正系数完全不同——这正是基础表必须按文件读、
    不能搞一份全公司主表的证据。"""
    factors = extract_knowledge(CASES[case]).factors
    assert tuple(int(f.coefficient) for f in factors[:6]) == expected


def test_levels_map_description_to_score() -> None:
    """档次描述 → 分值。办公第一个因素是「重要场所距离」。"""
    first = extract_knowledge(CASES["办公"]).factors[0]
    assert first.levels["距区域中心距离＜1KM"] == 2
    assert first.levels["距区域中心距离1-1.5KM"] == 1
    assert first.levels["距区域中心距离1.5-2KM"] == 0
    assert first.levels["距区域中心距离2-2.5KM"] == -1
    assert first.levels["距区域中心距离＞2.5KM"] == -2


def test_factor_rows_are_contiguous_from_3() -> None:
    """因素占基础表 3..30 行，比较法 9..36 行与之一一对应（偏移 6）。"""
    factors = extract_knowledge(CASES["办公"]).factors
    assert factors[0].row == 3
    assert factors[-1].row == 30
