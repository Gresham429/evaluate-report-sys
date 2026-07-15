"""读取比较法的公式声明（YAML）。

YAML 是权威表述与文档，供估价师阅读核对；策略实现须与之逐条对应。
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

__all__ = ["MethodSpec", "load_spec", "DEFAULT_SPEC_DIR"]

DEFAULT_SPEC_DIR = Path(__file__).resolve().parents[2] / "knowledge"


@dataclass(frozen=True)
class MethodSpec:
    """一份比较法的公式声明。"""

    method: str
    version: str
    categories: tuple[str, ...]
    base_value: float
    formulas: dict[str, str]
    weights: tuple[float, ...]
    benchmarks: dict[str, dict[str, Any]]


def load_spec(path: Path) -> MethodSpec:
    """加载公式声明。

    Args:
        path: YAML 路径。

    Returns:
        MethodSpec。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 必需字段缺失。
    """
    if not path.exists():
        raise FileNotFoundError(f"公式声明不存在：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("方法", "版本", "适用类别", "基准值", "公式", "权重", "对照基准"):
        if key not in data:
            raise ValueError(f"公式声明缺少字段 {key!r}：{path}")
    return MethodSpec(
        method=str(data["方法"]),
        version=str(data["版本"]),
        categories=tuple(data["适用类别"]),
        base_value=float(data["基准值"]),
        formulas=dict(data["公式"]),
        weights=tuple(float(w) for w in data["权重"]["默认"]),
        benchmarks=dict(data["对照基准"]),
    )
