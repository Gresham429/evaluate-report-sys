"""实勘问卷草稿/提交的读写编排（serverless 侧）。

**只给「实勘问卷」这张可变表用**——台账/实例/基础表后端一律不调
`update_record`，"只增不改"（铁律 #4）由调用侧不使用来保证，本模块不做
额外拦截。`client` 既可以是真正的 `NotableClient`，也可以是任何实现了
`list_records`/`insert_record`/`update_record` 的对象（单测用内存假实现，
零网络）。
"""

from typing import Any, Protocol

from serverless.survey_broker.record import (
    COL_CATEGORY,
    COL_ID,
    COL_MTIME,
    COL_STATUS,
    COL_USER,
    STATUS_DRAFT,
    STATUS_SUBMITTED,
    content_to_fields,
    fields_to_content,
    new_survey_id,
)

__all__ = ["RecordWriter", "SurveyBrokerStore"]


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

    def _record_id(self, survey_id: str) -> str | None:
        """按问卷ID找行 id（不筛状态——草稿/已提交都能命中）。找不到给 None。"""
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if str(fields.get(COL_ID, "")) == survey_id:
                return str(rec.get("id"))
        return None

    def save_draft(
        self,
        *,
        survey_id: str | None,
        filler: str,
        category: str,
        updated_at: str,
        content: dict[str, Any],
    ) -> str:
        """存草稿：给定 ID 且该行存在 → 原行 update；否则新开一行（无 ID 时现生成）。

        Returns:
            问卷ID（新生成的或沿用传入的）。
        """
        sid = survey_id or new_survey_id()
        record_id = self._record_id(sid)
        fields = content_to_fields(
            survey_id=sid,
            status=STATUS_DRAFT,
            filler=filler,
            category=category,
            updated_at=updated_at,
            content=content,
        )
        if record_id is not None:
            self._client.update_record(self._sheet, record_id, fields)
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
        """把某问卷状态改成已提交。

        Raises:
            KeyError: 没有该 ID 的行。
        """
        record_id = self._record_id(survey_id)
        if record_id is None:
            raise KeyError(f"未找到问卷：{survey_id}")
        self._client.update_record(self._sheet, record_id, {COL_STATUS: STATUS_SUBMITTED})

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
