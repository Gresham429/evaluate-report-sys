"""实勘问卷行契约（serverless 侧，vendored 副本）。

serverless broker 不能 `import src.questionnaire`——那个包经
`src.questionnaire.model` → `src.extractor.field_map` → `src.model` 这条链，
最终会拉到 PyYAML（`pyproject.toml` 依赖），与本包"部署到阿里云函数计算、
仅用标准库"的约束冲突。本文件是同一份行契约的独立副本：列名、
「问卷内容」JSON 的六个键，逐一照抄 `src.questionnaire.backend`
（`response_to_fields` / `_fields_to_response`）。

**改动纪律**：这两侧任何一侧改了行契约，另一侧必须同步改，否则办公端读出来的
数据就会跟 serverless 写进去的对不上。`tests/test_survey_broker_record.py`
把两侧对拍成契约测试，防止悄悄漂移。
"""

import json
from typing import Any
from uuid import uuid4

__all__ = [
    "COL_CATEGORY",
    "COL_CONTENT",
    "COL_ID",
    "COL_MTIME",
    "COL_OWNERS",
    "COL_STATUS",
    "COL_USER",
    "CONTENT_KEYS",
    "STATUS_DRAFT",
    "STATUS_FINALIZED",
    "STATUS_PENDING_REVIEW",
    "STATUS_SUBMITTED",
    "content_to_fields",
    "fields_to_content",
    "new_survey_id",
    "owners_from_fields",
]

COL_ID = "问卷ID"
COL_STATUS = "状态"
COL_USER = "填报人"  # 创建人/主填报（单个）
COL_OWNERS = "共有人"  # userid 列表(JSON)：全体持有者，含填报人。可见性/权限以它为准
COL_MTIME = "更新时间"
COL_CATEGORY = "类别"
COL_CONTENT = "问卷内容"

STATUS_DRAFT = "草稿"
STATUS_SUBMITTED = "已提交"
STATUS_PENDING_REVIEW = "待审核"  # 办公端「发起审核」后：已提交 → 待审核
STATUS_FINALIZED = "已定稿"  # 办公端「审核通过」后：待审核 → 已定稿（终态·锁定）

# 「问卷内容」JSON 的六个顶层键，顺序与 response_to_fields 里的 content 字面量一致
# （json.dumps 按插入顺序写键，两侧顺序不一致会导致契约测试的字符串比较误报）。
CONTENT_KEYS = ("basic", "subjects", "subject_levels", "asset_conditions", "photos", "gps")


def content_to_fields(
    *,
    survey_id: str,
    status: str,
    filler: str,
    category: str,
    updated_at: str,
    content: dict[str, Any],
    owners: list[str] | None = None,
) -> dict[str, object]:
    """问卷字段 → 多维表一行 fields。须与 `response_to_fields` 字节级一致。

    owners 未给时兜底 [filler]（填报人恒为持有者）；给了就照写（须已含 filler）。
    """
    body = {k: content.get(k) for k in CONTENT_KEYS}
    owner_list = list(owners) if owners else [filler]
    return {
        COL_ID: survey_id,
        COL_STATUS: status,
        COL_USER: filler,
        COL_OWNERS: json.dumps(owner_list, ensure_ascii=False),
        COL_MTIME: updated_at,
        COL_CATEGORY: category,
        COL_CONTENT: json.dumps(body, ensure_ascii=False),
    }


def owners_from_fields(fields: dict[str, Any]) -> list[str]:
    """一行 fields → 共有人列表；缺/坏/空 → 兜底 [填报人]（旧行无此列时迁移友好）。"""
    raw = fields.get(COL_OWNERS)
    owners: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            owners = [str(x) for x in parsed if str(x)]
    if not owners:
        filler = str(fields.get(COL_USER, ""))
        owners = [filler] if filler else []
    return owners


def fields_to_content(fields: dict[str, Any]) -> dict[str, Any]:
    """多维表一行 fields → 「问卷内容」dict。JSON 坏或不是对象都抛 ValueError。"""
    raw = fields.get(COL_CONTENT) or "{}"
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"问卷内容 JSON 解析失败：{exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("问卷内容不是对象")
    return parsed


def new_survey_id() -> str:
    """新问卷 ID：uuid4 前 12 位十六进制。"""
    return uuid4().hex[:12]
