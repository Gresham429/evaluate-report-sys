"""公式声明与策略注册测试。"""

from pathlib import Path

import pytest

from src.engine.methods import get_method
from src.engine.methods.base import ComparisonMethod
from src.engine.spec import load_spec

SPEC_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "比较法-市场比较法-2026版.yaml"


def test_spec_loads() -> None:
    spec = load_spec(SPEC_PATH)
    assert spec.method == "市场比较法"
    assert spec.version == "2026-07"
    assert spec.base_value == 100
    assert set(spec.categories) == {"农用", "办公", "商业"}


def test_spec_declares_all_four_formulas() -> None:
    """公式必须完整声明在 YAML 里，供估价师核对——不得只存在于代码中。"""
    formulas = load_spec(SPEC_PATH).formulas
    assert set(formulas) == {"因素指数", "比准价格", "评估结果", "离散度"}


def test_spec_benchmarks_match_goldens() -> None:
    """YAML 里的对照基准必须与三份金样一致。"""
    benchmarks = load_spec(SPEC_PATH).benchmarks
    assert benchmarks["办公"]["评估结果"] == 2.83
    assert benchmarks["农用"]["评估结果"] == 1399.26
    assert benchmarks["商业"]["评估结果"] == 3.32


def test_method_registry() -> None:
    method = get_method("市场比较法-2026")
    assert isinstance(method, ComparisonMethod)


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="未注册的比较法"):
        get_method("成本法-2030")
