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
from collections.abc import Callable
from typing import Any, Protocol

from src.questionnaire.merge import CONTENT_KEYS, merge_content
from src.questionnaire.model import (
    STATUS_FINALIZED,
    STATUS_PENDING_REVIEW,
    STATUS_SUBMITTED,
    SurveyInfo,
    SurveyResponse,
)
from src.questionnaire.permissions import Viewer, can_edit, can_finalize, can_see

logger = logging.getLogger(__name__)

__all__ = ["SurveyPullBackend", "response_content", "response_to_fields"]

_CONTENT = "问卷内容"
_ID, _STATUS, _USER, _MTIME, _CATEGORY = "问卷ID", "状态", "填报人", "更新时间", "类别"
_OWNERS = "共有人"  # 与 serverless record.COL_OWNERS 同步（契约测试对拍）

# 已进入审核流程、回写拒写的状态：待审核/已定稿（同 broker store._LOCKED_STATUSES）。
_LOCKED = (STATUS_PENDING_REVIEW, STATUS_FINALIZED)
_MERGE_SECTIONS = ("basic", "subject_levels", "asset_conditions")  # 参与字段级合并的三块


def _owners_from_fields(fields: dict[str, Any]) -> list[str]:
    """一行 fields → 共有人列表；缺/坏/空 → 兜底 [填报人]。镜像 record.owners_from_fields。"""
    raw = fields.get(_OWNERS)
    owners: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            owners = [str(x) for x in parsed if str(x)]
    if not owners:
        u = str(fields.get(_USER, ""))
        owners = [u] if u else []
    return owners


class _Client(Protocol):
    """本后端要的两个能力：读全表 + 改一行。

    改一行**只用来改「实勘问卷」表的状态字段**（发起审核/审核通过）——问卷表是可变表，
    与台账/实例/基础表「只增不改」的铁律不冲突（改的是问卷、不是台账）。
    """

    def list_records(self, sheet: str) -> list[dict[str, Any]]: ...

    def update_record(self, sheet: str, record_id: str, fields: dict[str, Any]) -> None: ...


def response_content(response: SurveyResponse) -> dict[str, Any]:
    """`SurveyResponse` → 「问卷内容」六键 dict（回写合并的 base/theirs 用同一形状）。"""
    return {
        "basic": dict(response.basic),
        "subjects": [dict(s) for s in response.subjects],
        "subject_levels": dict(response.subject_levels),
        "asset_conditions": dict(response.asset_conditions),
        "photos": list(response.photos),
        "gps": response.gps,
    }


def _content_from_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """一行 fields → 「问卷内容」dict（回写时取线上 theirs）。JSON 坏抛 ValueError。"""
    raw = fields.get(_CONTENT) or "{}"
    try:
        content = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"问卷内容 JSON 解析失败：{exc}") from exc
    if not isinstance(content, dict):
        raise ValueError("问卷内容不是对象")
    return content


def _count_applied_theirs(
    base: dict[str, Any], mine: dict[str, Any], theirs: dict[str, Any]
) -> int:
    """统计「我没改而线上改了」的叶子数——供前端提示「合并了对方 N 处改动」。"""
    n = 0
    for section in _MERGE_SECTIONS:
        b, m, t = base.get(section) or {}, mine.get(section) or {}, theirs.get(section) or {}
        for key in set(b) | set(m) | set(t):
            if m.get(key) == b.get(key) and t.get(key) != b.get(key):
                n += 1
    return n


def response_to_fields(response: SurveyResponse) -> dict[str, object]:
    """`SurveyResponse` → 多维表一行 fields。二期 serverless 写库的行契约。"""
    content = response_content(response)
    owner_list = list(response.共有人) if response.共有人 else [response.填报人]
    return {
        _ID: response.问卷ID,
        _STATUS: response.状态,
        _USER: response.填报人,
        _OWNERS: json.dumps(owner_list, ensure_ascii=False),
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
        共有人=tuple(_owners_from_fields(fields)),
    )


class SurveyPullBackend:
    """「实勘问卷」表 → 办公侧读写。

    读：按状态（已提交 / 待审核）列摘要、按 ID 取一份预填。
    写：只改「状态」字段——发起审核（已提交→待审核）、审核通过（待审核→已定稿）。

    权限：所有读写都带一个 `Viewer`（当前登录人 + 是否管理员 + 下属集），按问卷「共有人」
    逐份判定（见 `permissions`）——可见=owner/上级/管理员；发起审核须可编辑(owner/管理员)；
    定稿须可定稿(上级/管理员)。判不通的问卷一律当「不存在」（不泄露存在性，同 pull 的 404）。
    """

    def __init__(self, client: _Client, sheet: str) -> None:
        self._client = client
        self._sheet = sheet

    def _records(self) -> list[dict[str, Any]]:
        """全表原始记录（每条 {id, fields, ...}）。改状态要 record id，故不能只留 fields。"""
        return self._client.list_records(self._sheet)

    def _list_by_status(self, status: str, viewer: Viewer) -> list[SurveyInfo]:
        infos = []
        for rec in self._records():
            fields = rec.get("fields", {})
            if str(fields.get(_STATUS, "")) != status:
                continue
            if not can_see(viewer, _owners_from_fields(fields)):
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

    def list_submitted(self, viewer: Viewer) -> list[SurveyInfo]:
        """列当前登录人可见的「已提交」问卷摘要（办公端出报告用）。"""
        return self._list_by_status(STATUS_SUBMITTED, viewer)

    def list_pending(self, viewer: Viewer) -> list[SurveyInfo]:
        """列当前登录人可见的「待审核」问卷摘要（办公端审核列表用）。"""
        return self._list_by_status(STATUS_PENDING_REVIEW, viewer)

    def load(self, 问卷ID: str, viewer: Viewer) -> SurveyResponse:
        """按 ID 取一份「已提交」问卷（预填出报告）；不可见者一律 KeyError（当不存在）。

        Raises:
            KeyError: 没有该 ID 的已提交问卷，或当前登录人不可见。
            ValueError: 问卷内容 JSON 坏。
        """
        for rec in self._records():
            fields = rec.get("fields", {})
            if str(fields.get(_STATUS, "")) != STATUS_SUBMITTED:
                continue
            if str(fields.get(_ID, "")) != 问卷ID:
                continue
            if not can_see(viewer, _owners_from_fields(fields)):
                continue
            return _fields_to_response(fields)
        raise KeyError(f"未找到已提交问卷：{问卷ID}")

    def _set_status_batch(
        self,
        survey_ids: list[str],
        *,
        expect_status: str,
        new_status: str,
        viewer: Viewer,
        permit: Callable[[Viewer, list[str]], bool],
    ) -> dict[str, str]:
        """批量把 `survey_ids` 从 `expect_status` 改到 `new_status`，逐条给结果。

        只读一次全表建索引。`permit`（可编辑/可定稿）判不通的行**不进索引**——故无权与
        真不存在都统一回「未找到」（不泄露存在性）。逐条守卫：不在索引→「未找到」；当前状态
        非 `expect_status`→「状态非…」（挡重复处理/越级）；通过则只写「状态」列，标 "ok"。
        """
        wanted = set(survey_ids)
        index: dict[str, dict[str, Any]] = {}
        for rec in self._records():
            fields = rec.get("fields", {})
            qid = str(fields.get(_ID, ""))
            if qid not in wanted:
                continue
            if not permit(viewer, _owners_from_fields(fields)):
                continue  # 无权：不进索引 → 下面报「未找到」
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

    def review(self, survey_ids: list[str], viewer: Viewer) -> dict[str, str]:
        """批量发起审核：已提交 → 待审核（须可编辑：owner/管理员）。返回 {问卷ID: "ok"|原因}。"""
        return self._set_status_batch(
            survey_ids,
            expect_status=STATUS_SUBMITTED,
            new_status=STATUS_PENDING_REVIEW,
            viewer=viewer,
            permit=can_edit,
        )

    def finalize(self, survey_ids: list[str], viewer: Viewer) -> dict[str, str]:
        """批量审核通过：待审核 → 已定稿（须可定稿：上级/管理员）。返回 {问卷ID: "ok"|原因}。"""
        return self._set_status_batch(
            survey_ids,
            expect_status=STATUS_PENDING_REVIEW,
            new_status=STATUS_FINALIZED,
            viewer=viewer,
            permit=can_finalize,
        )

    def writeback(
        self,
        问卷ID: str,
        *,
        base: dict[str, Any],
        mine: dict[str, Any],
        viewer: Viewer,
        now: str,
        resolutions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """办公端「保存回问卷」：读线上→三方合并→有冲突则不写返回、无冲突写回。

        统一 spec §5：授权 `can_edit`（owner/管理员，上级不能改内容）；`待审核/已定稿`
        锁态拒写；回写只改「问卷内容」+「更新时间」，不动状态/共有人。`resolutions`
        （`{field: 选定值}`）覆盖对应冲突字段后视为已解决。

        Returns:
            `{"status":"saved", merged, merged_mtime, applied_theirs_count}` 或
            `{"status":"conflict", conflicts, theirs_mtime}`。

        Raises:
            KeyError: 无该问卷、或当前登录人无编辑权（映射 404，不泄露存在性）。
            ValueError: 问卷处于锁态（待审核/已定稿）不可回写（映射 400），或问卷内容 JSON 坏。
        """
        resolutions = resolutions or {}
        for rec in self._records():
            fields = rec.get("fields", {})
            if str(fields.get(_ID, "")) != 问卷ID:
                continue
            if not can_edit(viewer, _owners_from_fields(fields)):
                continue  # 无编辑权 → 当不存在
            status = str(fields.get(_STATUS, ""))
            if status in _LOCKED:
                raise ValueError(f"问卷已{status}，不可回写")

            theirs = _content_from_fields(fields)
            theirs_mtime = str(fields.get(_MTIME, ""))
            merged, conflicts = merge_content(base, mine, theirs)

            unresolved = []
            for c in conflicts:
                field = str(c["field"])
                if field in resolutions:
                    section, _, key = field.partition(".")
                    merged.setdefault(section, {})
                    if resolutions[field] is None:
                        merged[section].pop(key, None)
                    else:
                        merged[section][key] = resolutions[field]
                else:
                    unresolved.append(c)
            if unresolved:
                return {"status": "conflict", "conflicts": unresolved, "theirs_mtime": theirs_mtime}

            self._client.update_record(
                self._sheet,
                str(rec.get("id", "")),
                {_CONTENT: json.dumps({k: merged.get(k) for k in CONTENT_KEYS},
                                      ensure_ascii=False), _MTIME: now},
            )
            return {
                "status": "saved",
                "merged": merged,
                "merged_mtime": now,
                "applied_theirs_count": _count_applied_theirs(base, mine, theirs),
            }
        raise KeyError(f"未找到可回写问卷：{问卷ID}")
