"""照台账重算。

**把「可复现」从承诺变成当场可验证的事实。**

全程不碰实例库、不碰基础表库——台账快照里什么都有。能这么干，是因为
`src/engine/inputs.py` 已把引擎与 Excel、与存储解耦：重放只是拿快照重新构造一次
`ComparisonInput`，喂给同一个引擎。
"""

import logging

from src.engine.compute import compute
from src.engine.inputs import ComparisonInput
from src.engine.methods.base import Result
from src.ledger.model import LedgerEntry

logger = logging.getLogger(__name__)

__all__ = ["replay"]


def replay(entry: LedgerEntry) -> Result:
    """拿台账快照重算。

    Args:
        entry: 台账记录。

    Returns:
        重算结果。与 `entry.结果` 一致即证明这条记录可复现。

    Raises:
        ValueError: 这份报告未经系统重算（数值取自 Excel），没有可重放的东西。
    """
    if entry.基础表 is None or entry.估价对象档次 is None or entry.实例 is None:
        raise ValueError(
            f"报告「{entry.报告编号}」未经系统重算，数值取自 Excel，无可重放的计算过程"
        )
    if entry.权重 is None:
        raise ValueError(f"台账记录 {entry.记录号} 未记权重，无法重放")

    source = ComparisonInput(
        category=entry.类别,
        knowledge=entry.基础表.实际知识,
        subject_levels=dict(entry.估价对象档次),
    )
    result = compute(source, [use.实例 for use in entry.实例], entry.权重)
    logger.info(
        "重放 %s：台账记 %s，重算得 %s",
        entry.记录号,
        entry.结果.评估结果 if entry.结果 else "无",
        result.评估结果,
    )
    return result
