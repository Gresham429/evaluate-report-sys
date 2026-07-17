"""因素调整范围（Excel J 列）测试：范围进存储、不进指纹；含 parse_range 与
apply_coefficient_overrides——单份报告调系数的知识层基础设施。

延续 test_knowledge_group.py 的测法：group 怎么测，调整范围照样测一遍。
"""

from pathlib import Path

import pytest

from src.engine.knowledge import (
    Factor,
    Knowledge,
    apply_coefficient_overrides,
    extract_knowledge,
    parse_range,
)
from src.knowledge_base.fingerprint import fingerprint
from src.knowledge_base.store import BaseTableStore

MATERIALS = Path(__file__).resolve().parents[1].parent / "案例素材"
OFFICE = MATERIALS / "办公" / "办公实勘表、比较法.xlsx"
pytestmark = pytest.mark.skipif(not OFFICE.exists(), reason="需要 案例素材")

_SCORES = (2, 1, 0, -1, -2)


# ---------------------------------------------------------------- 提取


def test_factor_range_defaults_empty() -> None:
    # 仅加字段，默认空——既有直接构造 Factor 的调用方不受影响。
    f = Factor(row=3, name="楼层", levels={"高": 2}, coefficient=1.0)
    assert f.调整范围 == ""


def test_extract_knowledge_reads_real_ranges() -> None:
    """办公基础表 J 列实测值（决策记录 §7 / followup-2a 任务事实）。"""
    factors = extract_knowledge(OFFICE).factors
    assert factors[0].row == 3 and factors[0].调整范围 == "2-4"  # 重要场所距离
    assert factors[3].row == 6 and factors[3].调整范围 == "2-4"  # 楼层
    assert factors[14].row == 17 and factors[14].调整范围 == "1-2"  # 楼幢位置
    assert factors[17].row == 20 and factors[17].调整范围 == "1-3"  # 建筑结构


# ---------------------------------------------------------------- 指纹口径（不变）


def test_fingerprint_unchanged_by_range() -> None:
    """调整范围不进指纹：给因素填了范围也不改变指纹，三份钉住的基础表指纹不受影响。"""
    base = extract_knowledge(OFFICE)
    ranged = base.__class__(
        factors=tuple(
            Factor(
                row=x.row,
                name=x.name,
                levels=x.levels,
                coefficient=x.coefficient,
                group=x.group,
                调整范围="9-9",
            )
            for x in base.factors
        ),
        scores=base.scores,
    )
    assert fingerprint(ranged) == fingerprint(base)


def test_fingerprint_of_real_office_excel_unchanged() -> None:
    """回归钉子：加字段前 test_knowledge_base.py 钉的办公指纹必须原样成立。"""
    assert fingerprint(extract_knowledge(OFFICE)) == "95d043e06567"


# ---------------------------------------------------------------- 存取往返


def test_store_roundtrips_range(tmp_path: Path) -> None:
    k = Knowledge(
        factors=(
            Factor(row=3, name="楼层", levels={"高": 2}, coefficient=1.0, 调整范围="2-4"),
        ),
        scores=_SCORES,
    )
    assert BaseTableStore.from_dict(BaseTableStore.to_dict(k)).factors[0].调整范围 == "2-4"


def test_store_from_dict_tolerates_missing_range_key() -> None:
    """旧数据（导入本特性之前落盘的版本文件）没有「调整范围」键，须容忍读出空串。"""
    old_data: dict[str, object] = {
        "分值标尺": list(_SCORES),
        "因素": [
            {"行号": 3, "名称": "楼层", "档次": {"高": 2}, "系数": 1.0, "分组": ""},
        ],
    }
    loaded = BaseTableStore.from_dict(old_data)
    assert loaded.factors[0].调整范围 == ""


def test_import_from_excel_preserves_range(tmp_path: Path) -> None:
    """真实导入路径（含实勘表分组转换）不得把调整范围重置回空——曾是一处真实的坑：
    store.py 在填 group 时新建 Factor，若漏传调整范围会被默认值悄悄抹掉。"""
    store = BaseTableStore(tmp_path)
    result = store.import_from_excel(OFFICE, now=None)
    loaded = store.load(result.版本.类别, result.版本.指纹)
    by_row = {f.row: f.调整范围 for f in loaded.factors}
    assert by_row[3] == "2-4"
    assert by_row[6] == "2-4"
    assert by_row[17] == "1-2"
    assert by_row[20] == "1-3"


# ---------------------------------------------------------------- parse_range


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2-4", (2.0, 4.0)),
        ("1-3", (1.0, 3.0)),
        ("1-2", (1.0, 2.0)),
        ("3-10", (3.0, 10.0)),
        (" 2-4 ", (2.0, 4.0)),  # 首尾空白容忍
    ],
)
def test_parse_range_happy(text: str, expected: tuple[float, float]) -> None:
    assert parse_range(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "0",  # 分值标尺/系数行常见的非范围值，如实测 r31 J 列
        "abc",
        "2-4-6",
        "2到4",
    ],
)
def test_parse_range_malformed_returns_none(text: str) -> None:
    assert parse_range(text) is None


# ---------------------------------------------------------------- apply_coefficient_overrides


def _knowledge() -> Knowledge:
    return Knowledge(
        factors=(
            Factor(row=3, name="楼层", levels={"高": 2}, coefficient=1.0,
                   group="区位状况", 调整范围="2-4"),
            Factor(row=4, name="朝向", levels={"南": 2}, coefficient=1.0),
        ),
        scores=_SCORES,
    )


def test_apply_coefficient_overrides_replaces_only_named_factor() -> None:
    base = _knowledge()
    overridden = apply_coefficient_overrides(base, {"楼层": 3.0})

    assert overridden.factors[0].coefficient == 3.0
    # 其余字段原样保留，包括 group/调整范围。
    assert overridden.factors[0].row == base.factors[0].row
    assert overridden.factors[0].group == base.factors[0].group
    assert overridden.factors[0].调整范围 == base.factors[0].调整范围
    # 未命中的因素完全不变（同一个对象也好、值相等也好，等值即可）。
    assert overridden.factors[1] == base.factors[1]
    assert overridden.scores == base.scores


def test_apply_coefficient_overrides_empty_is_identity() -> None:
    base = _knowledge()
    assert apply_coefficient_overrides(base, {}) == base


def test_apply_coefficient_overrides_unknown_name_raises() -> None:
    base = _knowledge()
    with pytest.raises(ValueError, match="未知因素名"):
        apply_coefficient_overrides(base, {"不存在的因素": 1.0})


def test_apply_coefficient_overrides_does_not_mutate_input() -> None:
    base = _knowledge()
    apply_coefficient_overrides(base, {"楼层": 3.0})
    assert base.factors[0].coefficient == 1.0, "输入 knowledge 不得被就地改写"


def test_apply_coefficient_overrides_changes_fingerprint() -> None:
    """指纹本身仍覆盖系数（覆盖前后指纹不同）——这只是常识性 sanity check：
    我们不会给「实际知识」重新算版本指纹，per-report 覆盖走的是另一条记录路径
    （台账 Deviation），而不是新的基础表版本。"""
    base = _knowledge()
    overridden = apply_coefficient_overrides(base, {"楼层": 3.0})
    assert fingerprint(overridden) != fingerprint(base)
