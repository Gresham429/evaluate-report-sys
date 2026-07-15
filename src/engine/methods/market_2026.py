"""市场比较法 2026-07 版。

公式的权威声明见 knowledge/比较法-市场比较法-2026版.yaml，本实现须与之逐条对应：

    因素指数 = (实例档次分 − 估价对象档次分) × 每差1档系数 + 基准值
    比准价格 = 成交价 × (基准值/交易情况指数) × (市场状况指数/基准值)
                     × ∏(基准值/因素指数)
    评估结果 = Σ(比准价格 × 权重)
    离散度   = MAX(比准价格) / MIN(比准价格) − 1
"""

import logging
from collections.abc import Sequence

from src.engine.knowledge import Knowledge
from src.engine.methods.base import ComparisonMethod, Instance, Result

logger = logging.getLogger(__name__)

__all__ = ["MarketComparison2026", "BASE_VALUE", "PRICE_DECIMALS"]

BASE_VALUE = 100.0
PRICE_DECIMALS = 2


class MarketComparison2026(ComparisonMethod):
    """市场比较法 2026-07 版。"""

    name = "市场比较法-2026"
    version = "2026-07"

    def compute(
        self,
        subject_levels: dict[str, str],
        instances: Sequence[Instance],
        knowledge: Knowledge,
        weights: Sequence[float],
    ) -> Result:
        if len(weights) != len(instances):
            raise ValueError(
                f"权重数量 {len(weights)} 与实例数量 {len(instances)} 不匹配"
            )
        prices: list[float] = []
        for inst in instances:
            value = inst.成交价 * (BASE_VALUE / inst.交易情况指数)
            value *= inst.市场状况指数 / BASE_VALUE
            for factor in knowledge.factors:
                subj = subject_levels.get(factor.name, "")
                comp = inst.因素档次.get(factor.name, "")
                if not subj and not comp:
                    continue
                if subj not in factor.levels:
                    raise ValueError(
                        f"估价对象档次 {subj!r} 不在因素「{factor.name}」的基础表档次中"
                    )
                if comp not in factor.levels:
                    raise ValueError(
                        f"实例「{inst.位置}」档次 {comp!r} 不在因素「{factor.name}」的基础表档次中"
                    )
                index = (
                    factor.levels[comp] - factor.levels[subj]
                ) * factor.coefficient + BASE_VALUE
                value *= BASE_VALUE / index
            prices.append(round(value, PRICE_DECIMALS))

        final = round(sum(p * w for p, w in zip(prices, weights, strict=True)), PRICE_DECIMALS)
        dispersion = round(max(prices) / min(prices) - 1, PRICE_DECIMALS) if prices else 0.0
        logger.debug("比准价格=%s 评估结果=%s 离散度=%s", prices, final, dispersion)
        return Result(比准价格=tuple(prices), 评估结果=final, 离散度=dispersion)
