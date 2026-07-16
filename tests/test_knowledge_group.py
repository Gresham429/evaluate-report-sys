"""因素资产状况分组测试：分组进存储但不进指纹。"""

from pathlib import Path

import pytest

from src.engine.knowledge import Factor, extract_knowledge
from src.knowledge_base.fingerprint import fingerprint
from src.knowledge_base.store import BaseTableStore

MATERIALS = Path(__file__).resolve().parents[1].parent / "案例素材"
OFFICE = MATERIALS / "办公" / "办公实勘表、比较法.xlsx"
pytestmark = pytest.mark.skipif(not OFFICE.exists(), reason="需要 案例素材")


def test_factor_group_defaults_empty() -> None:
    # 仅加字段，默认空——既有直接读知识的调用方不受影响。
    f = Factor(row=3, name="楼层", levels={"高": 2}, coefficient=1.0)
    assert f.group == ""


def test_fingerprint_unchanged_by_grouping() -> None:
    # 分组不进指纹：给因素填了 group 也不改变指纹。
    base = extract_knowledge(OFFICE)
    grouped = base.__class__(
        factors=tuple(
            Factor(row=x.row, name=x.name, levels=x.levels,
                   coefficient=x.coefficient, group="区位状况")
            for x in base.factors
        ),
        scores=base.scores,
    )
    assert fingerprint(grouped) == fingerprint(base)


def test_store_roundtrips_group(tmp_path: Path) -> None:
    from src.engine.knowledge import Knowledge
    k = Knowledge(
        factors=(Factor(row=3, name="楼层", levels={"高": 2}, coefficient=1.0, group="区位状况"),),
        scores=(2, 1, 0, -1, -2),
    )
    assert BaseTableStore.from_dict(BaseTableStore.to_dict(k)).factors[0].group == "区位状况"
