"""实例库的多维表后端：整库 load / 按编号 upsert save（**只增不删**）。

实现 `InstanceBackend` 协议。整份实例存「实例」字段(JSON)、编号另存一列作键。
save 只插新编号、不删旧行——共享公司库里本地删除不该删公司数据（铁律 #4 精神 + §3④ 实例只增）。
既有编号的内容修改本版本不回传（实例基本只增，改动罕见；将来加 update 再补）。
"""

import json
import logging

from src.dingtalk.notable import NotableClient

logger = logging.getLogger(__name__)

__all__ = ["NotableInstanceBackend"]

_INSTANCE = "实例"
_KEY = "编号"


class NotableInstanceBackend:
    """实例库 → 钉钉多维表。"""

    def __init__(self, client: NotableClient, sheet: str) -> None:
        self._client = client
        self._sheet = sheet

    def load(self) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for rec in self._client.list_records(self._sheet):
            raw = rec.get("fields", {}).get(_INSTANCE)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("实例库多维表行读不出，已跳过：%s", rec.get("id"), exc_info=True)
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
        return out

    def save(self, records: list[dict[str, object]]) -> None:
        existing = {
            str(rec.get("fields", {}).get(_KEY))
            for rec in self._client.list_records(self._sheet)
            if rec.get("fields", {}).get(_KEY)
        }
        new_rows = [
            {_KEY: str(r[_KEY]), _INSTANCE: json.dumps(r, ensure_ascii=False)}
            for r in records
            if str(r.get(_KEY)) not in existing
        ]
        if new_rows:
            self._client.insert_records(self._sheet, new_rows)
            logger.info("实例库多维表新增 %d 条", len(new_rows))
