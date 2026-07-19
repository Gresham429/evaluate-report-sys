"""实勘问卷的多维表读取后端（办公侧，一期）。

**只读。** 办公端照旧用本地 `NotableClient` 直读「实勘问卷」表里「已提交」的记录
（同承载层那套凭据），拉一份 → 解成 `SurveyResponse`。写库（草稿/提交）是二期
serverless 的活，本后端不写。

一行的形状：问卷ID/状态/填报人/更新时间/类别 平铺（供列表与筛选），其余结构化内容
（basic/subjects/subject_levels/asset_conditions/photos/gps）塞进「问卷内容」JSON 列
——同 `NotableInstanceBackend` 拿单列存 JSON 的做法，多维表列类型有限，结构化数据
一律走 JSON。`response_to_fields` 是这套编码的唯一实现，**二期 serverless 写库须照它**。
"""

import json
import logging
from typing import Any, Protocol

from src.questionnaire.model import (
    STATUS_SUBMITTED,
    SurveyInfo,
    SurveyResponse,
)

logger = logging.getLogger(__name__)

__all__ = ["SurveyPullBackend", "response_to_fields"]

_CONTENT = "问卷内容"
_ID, _STATUS, _USER, _MTIME, _CATEGORY = "问卷ID", "状态", "填报人", "更新时间", "类别"


class _Reader(Protocol):
    """本后端只需要「读全表」这一个能力。"""

    def list_records(self, sheet: str) -> list[dict[str, Any]]: ...


def response_to_fields(response: SurveyResponse) -> dict[str, object]:
    """`SurveyResponse` → 多维表一行 fields。二期 serverless 写库的行契约。"""
    content = {
        "basic": response.basic,
        "subjects": [dict(s) for s in response.subjects],
        "subject_levels": response.subject_levels,
        "asset_conditions": response.asset_conditions,
        "photos": list(response.photos),
        "gps": response.gps,
    }
    return {
        _ID: response.问卷ID,
        _STATUS: response.状态,
        _USER: response.填报人,
        _MTIME: response.更新时间,
        _CATEGORY: response.category,
        _CONTENT: json.dumps(content, ensure_ascii=False),
    }


def _fields_to_response(fields: dict[str, Any]) -> SurveyResponse:
    """多维表一行 fields → `SurveyResponse`。JSON 坏抛 ValueError。"""
    raw = fields.get(_CONTENT) or "{}"
    try:
        content = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("问卷内容 JSON 解析失败（问卷ID=%s）：%s", fields.get(_ID), exc)
        raise ValueError(f"问卷内容 JSON 解析失败：{exc}") from exc
    if not isinstance(content, dict):
        raise ValueError("问卷内容不是对象")
    return SurveyResponse(
        问卷ID=str(fields.get(_ID, "")),
        状态=str(fields.get(_STATUS, "")),
        填报人=str(fields.get(_USER, "")),
        更新时间=str(fields.get(_MTIME, "")),
        category=str(fields.get(_CATEGORY, "")),
        basic={str(k): str(v) for k, v in (content.get("basic") or {}).items()},
        subjects=tuple(dict(s) for s in (content.get("subjects") or [])),
        subject_levels={str(k): str(v) for k, v in (content.get("subject_levels") or {}).items()},
        asset_conditions={str(k): str(v) for k, v in (content.get("asset_conditions") or {}).items()},
        photos=tuple(str(p) for p in (content.get("photos") or [])),
        gps=content.get("gps") if isinstance(content.get("gps"), dict) else None,
    )


class SurveyPullBackend:
    """「实勘问卷」表 → 办公侧读取。只列/取「已提交」。"""

    def __init__(self, client: _Reader, sheet: str) -> None:
        self._client = client
        self._sheet = sheet

    def _submitted_records(self) -> list[dict[str, Any]]:
        out = []
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if str(fields.get(_STATUS, "")) == STATUS_SUBMITTED:
                out.append(fields)
        return out

    def list_submitted(self) -> list[SurveyInfo]:
        """列出所有「已提交」问卷的摘要。"""
        infos = []
        for fields in self._submitted_records():
            infos.append(
                SurveyInfo(
                    问卷ID=str(fields.get(_ID, "")),
                    填报人=str(fields.get(_USER, "")),
                    category=str(fields.get(_CATEGORY, "")),
                    更新时间=str(fields.get(_MTIME, "")),
                )
            )
        return infos

    def load(self, 问卷ID: str) -> SurveyResponse:
        """按 ID 取一份「已提交」问卷。

        Raises:
            KeyError: 没有该 ID 的已提交问卷。
            ValueError: 问卷内容 JSON 坏。
        """
        for fields in self._submitted_records():
            if str(fields.get(_ID, "")) == 问卷ID:
                return _fields_to_response(fields)
        raise KeyError(f"未找到已提交问卷：{问卷ID}")
