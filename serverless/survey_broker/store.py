"""实勘问卷草稿/提交的读写编排（serverless 侧）。

**只给「实勘问卷」这张可变表用**——台账/实例/基础表后端一律不调
`update_record`，"只增不改"（铁律 #4）由调用侧不使用来保证，本模块不做
额外拦截。`client` 既可以是真正的 `NotableClient`，也可以是任何实现了
`list_records`/`insert_record`/`update_record` 的对象（单测用内存假实现，
零网络）。
"""

from typing import Any, Protocol

from serverless.survey_broker.merge import merge_content
from serverless.survey_broker.record import (
    COL_CATEGORY,
    COL_ID,
    COL_MTIME,
    COL_STATUS,
    COL_USER,
    STATUS_DRAFT,
    STATUS_FINALIZED,
    STATUS_PENDING_REVIEW,
    STATUS_SUBMITTED,
    content_to_fields,
    fields_to_content,
    new_survey_id,
)

__all__ = ["RecordWriter", "SurveyBrokerStore", "SurveyConflict"]


class SurveyConflict(Exception):
    """save_draft 三方合并遇同字段双改：不写库，把冲突逐字段抛给调用方（handler 映射）。"""

    def __init__(self, conflicts: list[dict[str, Any]], theirs_mtime: str) -> None:
        super().__init__("问卷内容冲突，需逐字段解决")
        self.conflicts = conflicts
        self.theirs_mtime = theirs_mtime


def _resolve(
    merged: dict[str, Any], conflicts: list[dict[str, Any]], resolutions: dict[str, Any]
) -> list[dict[str, Any]]:
    """把 resolutions 选定值覆盖到 merged 对应字段，返回仍未解决的冲突（与办公端同构）。"""
    unresolved: list[dict[str, Any]] = []
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
    return unresolved

# 已进入审核流程、服务端拒绝再写的状态：待审核/已定稿。
# 客户端（小程序）已把这两态置只读，但那只是前端提示——真正的「已定稿=终态·锁定」
# 必须由服务端兜底：否则手机离线时打开一份已定稿问卷、拉取失败没锁上、改完联网补传，
# saveDraft/submit 会把它退回草稿/已提交并覆盖内容。这里在写入口挡死。
_LOCKED_STATUSES = (STATUS_PENDING_REVIEW, STATUS_FINALIZED)


class RecordWriter(Protocol):
    """本 store 需要「实勘问卷」表的读/插/改/删四个能力。"""

    def list_records(self, sheet: str) -> list[dict[str, Any]]: ...

    def insert_record(self, sheet: str, fields: dict[str, Any]) -> str: ...

    def update_record(self, sheet: str, record_id: str, fields: dict[str, Any]) -> None: ...

    def delete_record(self, sheet: str, record_id: str) -> None: ...


class SurveyBrokerStore:
    """「实勘问卷」表读写：草稿续填（同 ID upsert）/ 按 ID 取 / 提交改状态。"""

    def __init__(self, client: RecordWriter, sheet: str) -> None:
        self._client = client
        self._sheet = sheet

    def _find(self, survey_id: str) -> tuple[str, str] | None:
        """按问卷ID找 (行id, 当前状态)（不筛状态——草稿/已提交/待审核/已定稿都命中）。找不到给 None。"""
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if str(fields.get(COL_ID, "")) == survey_id:
                return str(rec.get("id")), str(fields.get(COL_STATUS, ""))
        return None

    def save_draft(
        self,
        *,
        survey_id: str | None,
        filler: str,
        category: str,
        updated_at: str,
        content: dict[str, Any],
        owners: list[str] | None = None,
        base: dict[str, Any] | None = None,
        resolutions: dict[str, Any] | None = None,
    ) -> str:
        """存草稿：给定 ID 且该行存在 → 原行 update；否则新开一行（无 ID 时现生成）。

        已进入审核流程（待审核/已定稿）的问卷拒写，护住「已定稿=终态·锁定」（见 `_LOCKED_STATUSES`）。
        owners=共有人 userid 列表（现场估价师选的），未给兜底 [filler]。

        **双向同步（Phase 2）**：给了 `base`（手机端载入时的底版）且该行已存在时，读线上
        =theirs 走 `merge_content(base, content, theirs)`——手机没改的字段取线上（保住办公端
        刚回写的改动）。同字段双改 → 抛 `SurveyConflict`（不写），小程序逐字段选后带
        `resolutions` 重发。`base=None`（旧客户端/首个草稿）→ 不合并、整份写入（向后兼容）。

        Returns:
            问卷ID（新生成的或沿用传入的）。

        Raises:
            ValueError: 该问卷已待审核/已定稿，不可修改（映射 400）。
            SurveyConflict: 同字段双改、需逐字段解决（映射为冲突响应）。
        """
        sid = survey_id or new_survey_id()
        found = self._find(sid)
        if found is not None and found[1] in _LOCKED_STATUSES:
            raise ValueError(f"问卷已{found[1]}，不可修改")

        to_write = content
        if base is not None and found is not None:
            current = self.load(sid)  # theirs = 线上当前内容
            merged, conflicts = merge_content(base, content, current["content"])
            unresolved = _resolve(merged, conflicts, resolutions or {})
            if unresolved:
                raise SurveyConflict(unresolved, current["updated_at"])
            to_write = merged

        fields = content_to_fields(
            survey_id=sid,
            status=STATUS_DRAFT,
            filler=filler,
            category=category,
            updated_at=updated_at,
            content=to_write,
            owners=owners,
        )
        if found is not None:
            self._client.update_record(self._sheet, found[0], fields)
        else:
            self._client.insert_record(self._sheet, fields)
        return sid

    def load(self, survey_id: str) -> dict[str, Any]:
        """按问卷ID取一行（草稿/已提交都可）。

        Raises:
            KeyError: 没有该 ID 的行。
            ValueError: 问卷内容 JSON 坏。
        """
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if str(fields.get(COL_ID, "")) == survey_id:
                return {
                    "survey_id": str(fields.get(COL_ID, "")),
                    "status": str(fields.get(COL_STATUS, "")),
                    "filler": str(fields.get(COL_USER, "")),
                    "category": str(fields.get(COL_CATEGORY, "")),
                    "updated_at": str(fields.get(COL_MTIME, "")),
                    "content": fields_to_content(fields),
                }
        raise KeyError(f"未找到问卷：{survey_id}")

    def submit(self, survey_id: str) -> None:
        """把某问卷状态改成已提交。已待审核/已定稿的拒绝再提交（终态锁定）。

        Raises:
            KeyError: 没有该 ID 的行。
            ValueError: 该问卷已待审核/已定稿，不可再提交（映射 400）。
        """
        found = self._find(survey_id)
        if found is None:
            raise KeyError(f"未找到问卷：{survey_id}")
        if found[1] in _LOCKED_STATUSES:
            raise ValueError(f"问卷已{found[1]}，不可再提交")
        self._client.update_record(self._sheet, found[0], {COL_STATUS: STATUS_SUBMITTED})

    def list_by_filler(self, filler: str) -> list[dict[str, Any]]:
        """某填报人的全部问卷摘要（不含内容）——供手机端「我的问卷」跨设备查看。"""
        out: list[dict[str, Any]] = []
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if str(fields.get(COL_USER, "")) == filler:
                out.append({
                    "survey_id": str(fields.get(COL_ID, "")),
                    "status": str(fields.get(COL_STATUS, "")),
                    "category": str(fields.get(COL_CATEGORY, "")),
                    "updated_at": str(fields.get(COL_MTIME, "")),
                })
        return out

    def delete(self, survey_id: str) -> None:
        """删一份草稿/暂存件。**已提交的拒删**——只增不改的底账语义靠这层守住。

        Raises:
            KeyError: 没有该 ID 的行（映射 404）。
            ValueError: 该问卷已提交，不可删除（映射 400）。
        """
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if str(fields.get(COL_ID, "")) == survey_id:
                if str(fields.get(COL_STATUS, "")) == STATUS_SUBMITTED:
                    raise ValueError("已提交问卷不可删除")
                self._client.delete_record(self._sheet, str(rec.get("id")))
                return
        raise KeyError(f"未找到问卷：{survey_id}")
