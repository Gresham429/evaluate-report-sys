"""新类别算术金样：引擎重算必须复现 Excel 比较法缓存值。

新类别是构造样例，无签发报告可比（Approach A）。故期望值直接读 Excel，
不硬编码——真实案例替换 Excel 后本测试自动重锁。
"""

import openpyxl
import pytest

from src.engine.adapter import read_instances, read_subject_levels
from src.engine.knowledge import extract_knowledge
from src.engine.methods import get_method
from src.extractor.field_map import COMPARISON_FIELDS, comparison_sheet_name
from src.model import Category
from tests.conftest import CASES

NEW = {
    "住宅": Category.RESIDENTIAL,
    "工业": Category.INDUSTRIAL,
    "停车场用地": Category.PARKING_LAND,
    "建设用地": Category.CONSTRUCTION_LAND,
}


def _excel_expected(case: str) -> tuple[float, float]:
    """从 Excel 比较法表读期望值。

    - T39 = 评估结果单价：新模板与旧模板一致，引擎须精确复现（红线）。
    - X37 = 离散度：**新四类模板的 X37 公式是 `MAX/MIN`（少了 -1）**，而方法定义
      与旧三类是 `MAX/MIN-1`。引擎按方法定义算 `MAX/MIN-1` 才对，故这里把新模板的
      X37 减 1 还原为真正的离散度再比。⚠️ 这是新构造样例的模板小瑕疵之一，
      待真实案例复核（另见 adapter._normalize_market 的日期修正方向）。
    """
    sheet = openpyxl.load_workbook(CASES[case], data_only=True)[
        comparison_sheet_name(NEW[case])
    ]
    result = float(sheet[COMPARISON_FIELDS["unit_price"]].value)
    dispersion = round(float(sheet[COMPARISON_FIELDS["dispersion"]].value) - 1, 2)
    return result, dispersion


@pytest.mark.parametrize("case", list(NEW))
def test_new_category_reproduces_excel(case: str) -> None:
    path, category = CASES[case], NEW[case]
    computed = get_method("市场比较法-2026").compute(
        read_subject_levels(path, category),
        read_instances(path, category),
        extract_knowledge(path),
        (1 / 3, 1 / 3, 1 / 3),
    )
    result, dispersion = _excel_expected(case)
    assert computed.评估结果 == pytest.approx(result, abs=0.011)
    assert computed.离散度 == pytest.approx(dispersion, abs=0.011)
