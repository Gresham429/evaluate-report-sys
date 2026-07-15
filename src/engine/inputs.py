"""比较法引擎的输入契约。

**引擎不认识 Excel。** 它真正需要的只有三样：

    category        类别
    knowledge       基础表知识
    subject_levels  估价对象的因素档次

这三样从哪来，引擎不该关心：

    Excel 路径   from_excel(xlsx)                  —— 传一份实勘表，全从里面读
    表单路径     ComparisonInput(类别, 知识, 档次)  —— 档次来自 28 个下拉框，
                                                     知识来自本机存的基础表副本

这正是《比较法引擎与实例库设计》§5 提出、当时因无第二实现而按 YAGNI 缓做的
抽象层。表单落地后有了第二个实现，它才该立起来——早立是空转，晚立是两条
路径各写一遍算法。
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from src.engine.adapter import read_subject_levels
from src.engine.knowledge import Knowledge, extract_knowledge
from src.extractor.survey import extract_survey
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["ComparisonInput", "from_excel"]


@dataclass(frozen=True)
class ComparisonInput:
    """喂给比较法引擎的一份输入。

    Attributes:
        category: 估价对象类别。决定单位与可选实例的范围，故须随输入一起走。
        knowledge: 基础表知识（28 个因素、各档次描述与分值、修正系数）。
        subject_levels: 估价对象的因素档次，因素名 → 档次描述。
    """

    category: Category
    knowledge: Knowledge
    subject_levels: dict[str, str]


def from_excel(path: Path) -> ComparisonInput:
    """从一份实勘表 Excel 凑齐引擎需要的三样。

    这是 Excel 路径的适配器，**也是 Excel 在引擎侧仅存的入口**。表单路径不经过
    这里，直接构造 `ComparisonInput`。

    Args:
        path: 实勘表 Excel 路径（内含实勘表、比较法表、基础表三个工作表）。

    Returns:
        ComparisonInput。

    Raises:
        ValueError: 类别识别不出，或基础表/比较法表缺失。
    """
    survey = extract_survey(path)
    category = survey["category"]
    if not isinstance(category, Category):
        raise ValueError(f"无法识别估价对象类别：{path}")
    source = ComparisonInput(
        category=category,
        knowledge=extract_knowledge(path),
        subject_levels=read_subject_levels(path, category),
    )
    logger.debug(
        "读取比较法输入 %s：类别=%s，%d 个因素",
        path.name, category.value, len(source.knowledge.factors),
    )
    return source
