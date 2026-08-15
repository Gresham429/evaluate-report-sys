"""「实勘问卷」多维表的表结构 + 建列。

平铺七列供列表/筛选/权限，结构化内容进「问卷内容」JSON 列（见 backend.py）。
照片先走 JSON 里的 URL 列表——多维表附件字段支持与否待二期真机验（design §4.1）。
风格同 `tools/notable_provision.py`：`ensure_fields` 幂等建列。

**本清单必须覆盖 `response_to_fields`/`content_to_fields` 实际写入的每一列**，否则真机写入
会 404「fail to find field」——「共有人」列（2026-08-13 加 ACL 时进写入契约却漏了本清单）
就这么栽过（真机 saveDraft 全 500）。`tests/test_questionnaire_provision.py` 加了对拍防漂移。
"""

from typing import Protocol

__all__ = ["SURVEY_SHEET_FIELDS", "ensure_survey_sheet"]

SURVEY_SHEET_FIELDS: dict[str, str] = {
    "问卷ID": "text",
    "状态": "text",
    "填报人": "text",
    "共有人": "text",   # userid 列表(JSON)：可见/编辑权限以它为准（ACL）。漏建即真机写入 404。
    "更新时间": "text",
    "类别": "text",
    "问卷内容": "text",
}


class _FieldEnsurer(Protocol):
    def ensure_fields(self, sheet: str, specs: dict[str, str]) -> list[str]: ...


def ensure_survey_sheet(client: _FieldEnsurer, sheet: str) -> list[str]:
    """确保「实勘问卷」表七列齐备（幂等，只补缺的），返回新建字段名列表。"""
    return client.ensure_fields(sheet, SURVEY_SHEET_FIELDS)
