"""「实勘问卷」多维表的表结构 + 建列。

平铺六列供列表/筛选，结构化内容进「问卷内容」JSON 列（见 backend.py）。
照片先走 JSON 里的 URL 列表——多维表附件字段支持与否待二期真机验（design §4.1）。
风格同 `tools/notable_provision.py`：`ensure_fields` 幂等建列。
"""

from typing import Protocol

__all__ = ["SURVEY_SHEET_FIELDS", "ensure_survey_sheet"]

SURVEY_SHEET_FIELDS: dict[str, str] = {
    "问卷ID": "text",
    "状态": "text",
    "填报人": "text",
    "更新时间": "text",
    "类别": "text",
    "问卷内容": "text",
}


class _FieldEnsurer(Protocol):
    def ensure_fields(self, sheet: str, specs: dict[str, str]) -> list[str]: ...


def ensure_survey_sheet(client: _FieldEnsurer, sheet: str) -> list[str]:
    """确保「实勘问卷」表六列齐备，返回新建字段名列表。"""
    return client.ensure_fields(sheet, SURVEY_SHEET_FIELDS)
