"""Excel 单元格映射。

三份 Excel 的字段位置已实测一致（A2–A18 全部相同），故只需一份映射表。
仅工作表名与 A1 标题因类别而异。
"""

from src.model import Category

__all__ = [
    "SURVEY_FIELDS",
    "COMPARISON_FIELDS",
    "RESULT_HEADER_ROW",
    "RESULT_FIRST_ROW",
    "RESULT_COLUMNS",
    "detect_category",
    "survey_sheet_name",
    "comparison_sheet_name",
]

# 实勘表：字段名 → 单元格。三类通用。
SURVEY_FIELDS: dict[str, str] = {
    "project_name": "C2",
    "client": "C3",
    "client_address": "C4",
    "legal_rep": "C5",
    "purpose": "C6",
    "survey_date": "C7",
    "value_date": "C8",
    "materials": "C9",
    "certificate_status": "C10",
    "owner": "C11",
    "address": "C12",
    "usage": "C13",
    "scale": "C14",
    "scope": "C15",
    "current_status": "C16",
    "surveyor": "D46",  # 现场查勘记录人员，手工录入
    "report_no": "H2",
    "work_period": "H3",
    "issue_date": "H4",
}

# 比较法表：字段名 → 单元格。
COMPARISON_FIELDS: dict[str, str] = {
    "unit_price": "T39",  # 评估结果单价
    "dispersion": "X37",  # 比准价格离散度
}

# 估价结果一览表位置（三类一致，实测）
RESULT_HEADER_ROW = 48
RESULT_FIRST_ROW = 49
# 列序：序号, 权利人, 地址, 用途, 面积, 单价, 年租赁价值
RESULT_COLUMNS: tuple[int, ...] = (6, 7, 8, 9, 10, 11, 12)

_TITLE_PREFIX: dict[str, Category] = {
    "农用地": Category.AGRICULTURAL,
    "办公": Category.OFFICE,
    "商业": Category.COMMERCIAL,
}


def detect_category(title: str) -> Category:
    """由实勘表 A1 标题识别类别。

    比读 C13「设定出租用途」可靠：C13 内容是自由文本（如「农用地（耕地）」），
    而 A1 是固定标题。

    Args:
        title: 实勘表 A1 单元格文本。

    Returns:
        识别出的类别。

    Raises:
        ValueError: 标题不匹配任何已知类别。
    """
    text = (title or "").strip()
    for prefix, category in _TITLE_PREFIX.items():
        if text.startswith(prefix):
            return category
    raise ValueError(f"无法识别类别，实勘表 A1 标题为：{text!r}")


def survey_sheet_name(category: Category) -> str:
    """实勘表工作表名。办公类带前缀，另两类不带。"""
    return "办公房地产实地查勘记录表" if category is Category.OFFICE else "房地产实地查勘记录表"


def comparison_sheet_name(category: Category) -> str:
    """比较法工作表名。办公类带前缀，另两类不带。"""
    return "办公房地产比较法" if category is Category.OFFICE else "房地产比较法"
