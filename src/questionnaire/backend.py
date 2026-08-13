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
    STATUS_FINALIZED,
    STATUS_PENDING_REVIEW,
    STATUS_SUBMITTED,
    SurveyInfo,
    SurveyResponse,
)

logger = logging.getLogger(__name__)

__all__ = ["SurveyPullBackend", "response_to_fields"]

_CONTENT = "问卷内容"
_ID, _STATUS, _USER, _MTIME, _CATEGORY = "问卷ID", "状态", "填报人", "更新时间", "类别"


class _Client(Protocol):
    """本后端要的两个能力：读全表 + 改一行。

    改一行**只用来改「实勘问卷」表的状态字段**（发起审核/审核通过）——问卷表是可变表，
    与台账/实例/基础表「只增不改」的铁律不冲突（改的是问卷、不是台账）。
    """

    def list_records(self, sheet: str) -> list[dict[str, Any]]: ...

    def update_record(self, sheet: str, record_id: str, fields: dict[str, Any]) -> None: ...


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
    """「实勘问卷」表 → 办公侧读写。

    读：按状态（已提交 / 待审核）列摘要、按 ID 取一份预填。
    写：只改「状态」字段——发起审核（已提交→待审核）、审核通过（待审核→已定稿）。

    权限「只看自己」：列表/取/改状态都接受 `filler`——非 None 时只认 `填报人==filler` 的行；
    非本人的问卷一律当作「不存在」（不泄露他人问卷是否存在，同 `/api/survey/pull` 的 404 口径）。
    传 None 表示不过滤（旧调用方/工具）。identity 未知时上层传空串 ""——显式 fail-closed，
    什么都看不到、什么都改不了（防未登录/未识别的操作人碰到 `填报人==""` 的问卷）。
    """

    def __init__(self, client: _Client, sheet: str) -> None:
        self._client = client
        self._sheet = sheet

    def _records(self) -> list[dict[str, Any]]:
        """全表原始记录（每条 {id, fields, ...}）。改状态要 record id，故不能只留 fields。"""
        return self._client.list_records(self._sheet)

    def _list_by_status(self, status: str, filler: str | None) -> list[SurveyInfo]:
        if filler == "":  # 空串=识别不出操作人 → fail-closed，什么都不列
            return []
        infos = []
        for rec in self._records():
            fields = rec.get("fields", {})
            if str(fields.get(_STATUS, "")) != status:
                continue
            if filler is not None and str(fields.get(_USER, "")) != filler:
                continue
            infos.append(
                SurveyInfo(
                    问卷ID=str(fields.get(_ID, "")),
                    填报人=str(fields.get(_USER, "")),
                    category=str(fields.get(_CATEGORY, "")),
                    更新时间=str(fields.get(_MTIME, "")),
                )
            )
        return infos

    def list_submitted(self, filler: str | None = None) -> list[SurveyInfo]:
        """列「已提交」问卷摘要（办公端「从实勘问卷拉取」出报告用）。"""
        return self._list_by_status(STATUS_SUBMITTED, filler)

    def list_pending(self, filler: str | None = None) -> list[SurveyInfo]:
        """列「待审核」问卷摘要（办公端审核列表用）。"""
        return self._list_by_status(STATUS_PENDING_REVIEW, filler)

    def load(self, 问卷ID: str, filler: str | None = None) -> SurveyResponse:
        """按 ID 取一份「已提交」问卷（预填出报告）。

        Raises:
            KeyError: 没有该 ID 的已提交问卷，或该问卷非本人（filler 不符），或操作人未识别（filler=""）。
            ValueError: 问卷内容 JSON 坏。
        """
        if filler == "":  # 空串=识别不出操作人 → fail-closed，一律按「不存在」
            raise KeyError(f"未找到已提交问卷：{问卷ID}")
        for rec in self._records():
            fields = rec.get("fields", {})
            if str(fields.get(_STATUS, "")) != STATUS_SUBMITTED:
                continue
            if str(fields.get(_ID, "")) != 问卷ID:
                continue
            if filler is not None and str(fields.get(_USER, "")) != filler:
                continue
            return _fields_to_response(fields)
        raise KeyError(f"未找到已提交问卷：{问卷ID}")

    def _set_status_batch(
        self,
        survey_ids: list[str],
        *,
        expect_status: str,
        new_status: str,
        filler: str | None,
    ) -> dict[str, str]:
        """批量把 `survey_ids` 从 `expect_status` 改到 `new_status`，逐条给结果。

        只读一次全表建索引（批量避免 N 次全表拉取）。**非本人的行不进索引**——故非本人与
        真不存在都统一回「未找到」，不泄露他人问卷是否存在。逐条守卫：不在索引→「未找到」；
        当前状态不是 `expect_status`→「状态非…」（挡住重复处理/越级流转）；通过则
        `update_record` 只写「状态」列，标 "ok"。filler="" 视为识别不出操作人，一律「未找到」。
        """
        if filler == "":  # 空串=识别不出操作人 → fail-closed，一律「未找到」
            return {qid: "未找到" for qid in survey_ids}

        wanted = set(survey_ids)
        index: dict[str, dict[str, Any]] = {}
        for rec in self._records():
            fields = rec.get("fields", {})
            qid = str(fields.get(_ID, ""))
            if qid not in wanted:
                continue
            if filler is not None and str(fields.get(_USER, "")) != filler:
                continue  # 非本人：不进索引 → 下面报「未找到」（不泄露存在性）
            index[qid] = rec

        result: dict[str, str] = {}
        for qid in survey_ids:
            matched = index.get(qid)
            if matched is None:
                result[qid] = "未找到"
                continue
            current = str(matched.get("fields", {}).get(_STATUS, ""))
            if current != expect_status:
                result[qid] = f"状态非{expect_status}（现为{current or '空'}）"
                continue
            self._client.update_record(
                self._sheet, str(matched.get("id", "")), {_STATUS: new_status}
            )
            result[qid] = "ok"
        return result

    def review(self, survey_ids: list[str], filler: str | None = None) -> dict[str, str]:
        """批量发起审核：已提交 → 待审核。返回 {问卷ID: "ok"|原因}。"""
        return self._set_status_batch(
            survey_ids,
            expect_status=STATUS_SUBMITTED,
            new_status=STATUS_PENDING_REVIEW,
            filler=filler,
        )

    def finalize(self, survey_ids: list[str], filler: str | None = None) -> dict[str, str]:
        """批量审核通过：待审核 → 已定稿（终态·锁定）。返回 {问卷ID: "ok"|原因}。"""
        return self._set_status_batch(
            survey_ids,
            expect_status=STATUS_PENDING_REVIEW,
            new_status=STATUS_FINALIZED,
            filler=filler,
        )
