"""年租赁价值算术。

一览表的年租赁价值不是手填的数，是 Excel 里的公式算出来的（实测三份金样）：

    农用      L = K × J                  面积（亩）× 年租赁单价（元/亩·年）
    房屋类    L = ROUND(J × K × 365, 0)  面积（㎡）× 单价（元/㎡·天）× 365 天

本模块是这条公式在系统内的**唯一实现**：校验器（比对 Excel 读来的值）与
界面改单价后的重算共用它，杜绝双实现漂移。

**单价填多少不归本模块管。** 实测农用把评估结果 1399.26 手工取整成 1400 才
写进一览表——取整与否是估价师的判断（ADR-001 划的界：知识与判断归人，
算术归系统）。给什么单价就按什么算。
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from src.model import Category, _LAND_CATEGORIES

logger = logging.getLogger(__name__)

__all__ = ["annual_value", "DAYS_PER_YEAR"]

# 房屋类按日计租，年租赁价值须乘满一年。实测三份金样一律 365，不按闰年调整。
DAYS_PER_YEAR = 365


def _round_half_up(value: float) -> int:
    """逢五进一取整到个位，与 Excel 的 ROUND 一致。

    不能用内置 `round()`：它是银行家舍入（round-half-to-even），182.5 会
    舍成 182，而 Excel 记 183。差一块钱也是对不上账。
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def annual_value(category: Category, area: float, unit_price: float) -> int:
    """按类别算一个估价对象的年租赁价值。

    Args:
        category: 估价对象类别，决定要不要乘 365 天（土地类不乘）。
        area: 面积。土地类为亩，房屋类为㎡。
        unit_price: 单价。土地类为元/亩·年，房屋类为元/㎡·天。

    Returns:
        年租赁价值（元），取整到个位。
    """
    raw = area * unit_price
    if category not in _LAND_CATEGORIES:  # 土地类按年计租，房屋类×365
        raw *= DAYS_PER_YEAR
    return _round_half_up(raw)
