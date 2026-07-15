"""比较法策略的工厂与注册表。"""

import logging

from src.engine.methods.base import ComparisonMethod, Instance, Result
from src.engine.methods.market_2026 import MarketComparison2026

logger = logging.getLogger(__name__)

__all__ = ["ComparisonMethod", "Instance", "Result", "get_method", "register_method"]

_REGISTRY: dict[str, type[ComparisonMethod]] = {}


def register_method(cls: type[ComparisonMethod]) -> type[ComparisonMethod]:
    """注册一个比较法策略。"""
    _REGISTRY[cls.name] = cls
    return cls


def get_method(name: str) -> ComparisonMethod:
    """按名取策略。

    Args:
        name: 策略名，如「市场比较法-2026」。

    Returns:
        策略实例。

    Raises:
        ValueError: 未注册的比较法。
    """
    if name not in _REGISTRY:
        raise ValueError(f"未注册的比较法 {name!r}，已注册：{sorted(_REGISTRY)}")
    return _REGISTRY[name]()


register_method(MarketComparison2026)
