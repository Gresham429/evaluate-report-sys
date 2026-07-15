"""金样文字漂移的归一化规则。

三份金样因人工复制粘贴累积了 25 处措辞不一致（详见设计文档第 8 节）。
本模块是这些规则的**单一事实源**，有双重身份：
  1. 构建模板时统一样板文字；
  2. 金样回归测试的归一化器（把金样也过一遍再比对）。

计数口径为「漂移点」而非「段落」—— 一个段落可能同时含漂移、
项目数据与类别差异。weight 字段记录该规则覆盖的漂移点数。
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["DriftRule", "DRIFT_RULES", "normalise"]


@dataclass(frozen=True)
class DriftRule:
    """一条漂移归一化规则。"""

    name: str
    pattern: str
    replacement: str
    reason: str
    weight: int = 1


# 汉字数字，其序号仍用顿号，不得被阿拉伯数字规则误伤
_CJK_NUMERALS = "一二三四五六七八九十"

DRIFT_RULES: tuple[DriftRule, ...] = (
    DriftRule(
        name="序号点号",
        # 行首阿拉伯数字 + 顿号 → 点号。汉字数字序号不受影响。
        pattern=r"(?m)^(\d+)、",
        replacement=r"\1.",
        reason="GB/T 15834-2011 §4.5.3.5：阿拉伯数字序号后用点号；顿号仅用于汉字数字序号",
        weight=15,
    ),
    DriftRule(
        name="冒号全角",
        pattern=r"注册号:",
        replacement="注册号：",
        reason="GB/T 15834-2011：中文文本用全角冒号",
        weight=2,
    ),
    DriftRule(
        name="方法别名-价值折算法",
        pattern=r"收益法（价值折算法）",
        replacement="价值折算法",
        reason="三份共有段落已定名「比较法、成本法、价值折算法、剩余法四种」，后文应同名",
        weight=1,
    ),
    DriftRule(
        name="方法别名-剩余法",
        pattern=r"假设开发法（剩余法）",
        replacement="剩余法",
        reason="同上",
        weight=1,
    ),
    DriftRule(
        name="见诸于",
        pattern=r"见诸于",
        replacement="见诸",
        reason="语法错误：「诸」是「之于」的合音，「见诸于」为冗余",
        weight=1,
    ),
    DriftRule(
        name="房屋安全",
        pattern=r"已对安全、环境污染",
        replacement="已对房屋安全、环境污染",
        reason="办公与商业同为房屋类，写法应一致（农用地无房屋，本无此项，不受影响）",
        weight=1,
    ),
    DriftRule(
        name="缺复印件",
        pattern=r"《委托评估协议书》；",
        replacement="《委托评估协议书》复印件；",
        reason="估价依据清单列的是复印件；商业金样此处漏写。仅匹配分号结尾，避免误伤正文的「按《委托评估协议书》为准」",
        weight=1,
    ),
    DriftRule(
        name="缺书名号",
        pattern=r"(?<!《)委托评估协议书(?!》)",
        replacement="《委托评估协议书》",
        reason="与另两类一致",
        weight=1,
    ),
    DriftRule(
        name="句末标点",
        pattern=r"(特许经营权等其他权利)；",
        replacement=r"\1。",
        reason="完整句收尾",
        weight=1,
    ),
    DriftRule(
        name="括号全角",
        pattern=r"\((\d+)\)",
        replacement=r"（\1）",
        reason="中文文本用全角括号",
        weight=1,
    ),
)


def normalise(text: str) -> str:
    """对文本应用全部漂移规则。

    幂等：对已归一化的文本再次调用不产生变化。

    Args:
        text: 原始文本。

    Returns:
        归一化后的文本。
    """
    result = text
    for rule in DRIFT_RULES:
        result = re.sub(rule.pattern, rule.replacement, result)
    return result
