"""台账的多维表后端：一行一条，整份 payload 存「快照」字段(JSON)；只增不改。

实现 `LedgerBackend` 协议（append + iter_payloads）。**没有 update/delete**——
台账只增不改（铁律 #4）由此天然满足。索引列（记录号/报告编号/类别/生成时间/经手人）
只为人肉浏览，权威内容在「快照」里（铁律 #5 自洽快照）。
"""

import json
import logging
from collections.abc import Iterator
from datetime import datetime

from src.dingtalk.notable import NotableClient

logger = logging.getLogger(__name__)

__all__ = ["NotableLedgerBackend", "SNAPSHOT_FIELD"]

SNAPSHOT_FIELD = "快照"


class NotableLedgerBackend:
    """台账 → 钉钉多维表。append=插一行，iter=读全表反序列化。"""

    def __init__(self, client: NotableClient, sheet: str, *, snapshot_field: str = SNAPSHOT_FIELD) -> None:
        self._client = client
        self._sheet = sheet
        self._field = snapshot_field

    def append(self, record_id: str, created_at: datetime, payload: dict[str, object]) -> None:
        fields: dict[str, object] = {
            "记录号": record_id,
            "报告编号": str(payload.get("报告编号", "")),
            "类别": str(payload.get("类别", "")),
            "生成时间": created_at.isoformat(),
            "经手人": str(payload.get("经手人", "")),
            self._field: json.dumps(payload, ensure_ascii=False),
        }
        self._client.insert_record(self._sheet, fields)

    def iter_payloads(self) -> Iterator[dict[str, object]]:
        for rec in self._client.list_records(self._sheet):
            raw = rec.get("fields", {}).get(self._field)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError, TypeError):
                # 单元格可被人在多维表里手改，改坏一行不该拖垮整份台账（同本地后端的容错口径）。
                logger.warning("台账多维表行快照读不出，已跳过：%s", rec.get("id"), exc_info=True)
                continue
            if isinstance(parsed, dict):
                yield parsed
