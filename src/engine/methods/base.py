"""比较法策略的抽象基类。

新增比较法 = 新增一个策略实现 + 对应 YAML 声明，注册即可用，老策略不动。

诚实的边界：形态不同的方法（成本法、收益法）须写代码——不同的算法就是
不同的算法，无法参数化。但它被隔离成命名、带版本、可独立测试的单元。
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from src.engine.knowledge import Knowledge

logger = logging.getLogger(__name__)

__all__ = ["Instance", "Result", "ComparisonMethod"]


@dataclass(frozen=True)
class Instance:
    """一条比较实例，已配好本项目所需的市场状况指数。

    市场状况指数不属于实例固有属性——它是「实例 × 本项目价值时点」的配对
    属性，由估价师每次现填。故它在此处而非实例库中。
    """

    位置: str
    成交价: float
    交易情况指数: float
    市场状况指数: float
    因素档次: dict[str, str]


@dataclass(frozen=True)
class Result:
    """比较法的计算结果。"""

    比准价格: tuple[float, ...]
    评估结果: float
    离散度: float


class ComparisonMethod(ABC):
    """比较法策略。"""

    name: str
    version: str

    @abstractmethod
    def compute(
        self,
        subject_levels: dict[str, str],
        instances: Sequence[Instance],
        knowledge: Knowledge,
        weights: Sequence[float],
    ) -> Result:
        """计算比准价格与评估结果。

        Args:
            subject_levels: 估价对象的因素档次，因素名 → 档次描述。
            instances: 比较实例，通常 3 条。
            knowledge: 从 Excel 基础表提取的知识。
            weights: 各实例权重，长度须与 instances 一致。

        Returns:
            Result。

        Raises:
            ValueError: 档次不在基础表中，或权重数量不匹配。
        """
