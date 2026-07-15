"""把实例库里选中的实例接入比较法引擎——闭合"选实例 → 重算"的环。

上一轮暴露的计划缺口：引擎会算（Task 3）、实例库能存能列（Task 4/5/6），
但选完实例后没有任何代码把两者接起来。本模块是唯一的接口：给一份实勘表
Excel（估价对象档次与基础表知识的来源）+ 库中选中的实例编号 + 估价师
现填的市场状况指数，算出比准价格与评估结果。

不做推荐：选哪三条、市场状况指数填多少，全部由估价师决定；本模块只管算对。
"""

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from src.engine.adapter import read_subject_levels
from src.engine.knowledge import extract_knowledge
from src.engine.methods import get_method
from src.engine.methods.base import Instance, Result
from src.engine.spec import DEFAULT_SPEC_DIR, load_spec
from src.extractor.survey import extract_survey
from src.library.store import InstanceStore
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["compute_from_selection", "SELECTION_SIZE", "METHOD_NAME"]

METHOD_NAME = "市场比较法-2026"
SPEC_FILENAME = "比较法-市场比较法-2026版.yaml"
SELECTION_SIZE = 3


def _resolve_market_index(raw_id: str, raw_index: object) -> float:
    """把用户提交的市场状况指数原始值转成 float。

    市场状况指数是估价师的专业判断，系统不推算、不给默认值——缺失或空白
    一律报错，不得静默取 0 或取基准值 100。

    Raises:
        ValueError: 未填，或类型/取值不是合法数字。
    """
    if raw_index is None:
        raise ValueError(f"实例「{raw_id}」未填市场状况指数——系统不推算、不给默认值")
    if isinstance(raw_index, str) and not raw_index.strip():
        raise ValueError(f"实例「{raw_id}」未填市场状况指数——系统不推算、不给默认值")
    if isinstance(raw_index, bool) or not isinstance(raw_index, int | float | str):
        raise ValueError(f"实例「{raw_id}」市场状况指数类型不对：{raw_index!r}")
    try:
        return float(raw_index)
    except ValueError as exc:
        raise ValueError(f"实例「{raw_id}」市场状况指数不是有效数字：{raw_index!r}") from exc


def _resolve_instance(
    item: Mapping[str, object], category: Category, store: InstanceStore
) -> Instance:
    """把一条选中项（库编号 + 现填市场状况指数）解析成引擎需要的 Instance。

    Raises:
        ValueError: 编号缺失、不在库中、类别不符，或市场状况指数不合法。
    """
    raw_id = item.get("编号")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ValueError(f"选中项缺少编号：{item!r}")

    stored = store.get(raw_id)
    if stored is None:
        raise ValueError(f"编号不在库中：{raw_id}")
    if stored.类别 is not category:
        raise ValueError(
            f"实例「{raw_id}」类别（{stored.类别.value}）与估价对象类别"
            f"（{category.value}）不一致"
        )

    market_index = _resolve_market_index(raw_id, item.get("市场状况指数"))
    return Instance(
        位置=stored.位置,
        成交价=stored.成交价,
        交易情况指数=stored.交易情况指数,
        市场状况指数=market_index,
        因素档次=dict(stored.因素档次),
    )


def compute_from_selection(
    path: Path,
    selections: Sequence[Mapping[str, object]],
    store: InstanceStore,
) -> tuple[Category, Result]:
    """从库里取出选中的实例，接入市场比较法引擎重算。

    Args:
        path: 估价对象所在的实勘表 Excel（提供估价对象档次与基础表知识）。
        selections: 选中项，形如
            `[{"编号": str, "市场状况指数": number, "备注": str}, ...]`，须恰好 3 条。
        store: 已加载（`load()` 过）的实例库。

    Returns:
        `(类别, Result)`。类别一并返回是因为**数字离了单位就是误导**——
        农用算出 1399.26（元/亩·年）与办公算出 2.83（元/㎡·天）量级差 500 倍，
        谁拿到这些数字谁就得同时拿到判断单位的依据，不能让调用方自己去猜、
        或另读一遍 Excel。

    Raises:
        ValueError: 选中数量不为 3、某项缺编号、编号不在库中、类别不符，
                    或市场状况指数缺失/不合法。
    """
    if len(selections) != SELECTION_SIZE:
        raise ValueError(f"须选满 {SELECTION_SIZE} 条实例，实选 {len(selections)} 条")

    survey = extract_survey(path)
    category = survey["category"]
    if not isinstance(category, Category):
        raise ValueError(f"无法识别估价对象类别：{path}")

    knowledge = extract_knowledge(path)
    subject_levels = read_subject_levels(path, category)
    instances = tuple(_resolve_instance(item, category, store) for item in selections)

    spec = load_spec(DEFAULT_SPEC_DIR / SPEC_FILENAME)
    method = get_method(METHOD_NAME)
    try:
        result = method.compute(subject_levels, instances, knowledge, spec.weights)
    except ZeroDivisionError as exc:
        # 市场状况指数填 0（或使某条比准价格算出 0）会让离散度公式除零——
        # 这不是系统故障，是估价师填了个物理上不成立的指数，同样按 400 报告。
        raise ValueError("市场状况指数或档次取值导致比准价格算出 0，无法计算离散度，请核对填写") from exc
    logger.info(
        "重算完成：类别=%s 比准价格=%s 评估结果=%s 离散度=%s",
        category.value, result.比准价格, result.评估结果, result.离散度,
    )
    return category, result
