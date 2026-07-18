"""基础表的多维表后端：一张表两类行（版本 / 索引），用「种类」字段区分。

实现 `BaseTableBackend` 协议。版本内容不可变（`write_version` 只在 store 判定不存在时被调用）；
版本行带「键」=`{类别}|{指纹}`便于查；索引只追加。整份内容存「内容」字段(JSON)。
"""

import json
import logging

from src.dingtalk.notable import NotableClient

logger = logging.getLogger(__name__)

__all__ = ["NotableBaseTableBackend"]

_KIND = "种类"
_KEY = "键"
_CONTENT = "内容"
_KIND_VERSION = "版本"
_KIND_INDEX = "索引"


class NotableBaseTableBackend:
    """基础表版本库 → 钉钉多维表。版本不可变、索引只追加。"""

    def __init__(self, client: NotableClient, sheet: str) -> None:
        self._client = client
        self._sheet = sheet

    def _version_fields(self, category: str, fingerprint: str) -> dict[str, object] | None:
        key = f"{category}|{fingerprint}"
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if fields.get(_KIND) == _KIND_VERSION and fields.get(_KEY) == key:
                return dict(fields)
        return None

    def write_version(self, category: str, fingerprint: str, payload: dict[str, object]) -> None:
        self._client.insert_record(
            self._sheet,
            {
                _KIND: _KIND_VERSION,
                _KEY: f"{category}|{fingerprint}",
                "类别": category,
                "指纹": fingerprint,
                _CONTENT: json.dumps(payload, ensure_ascii=False),
            },
        )

    def read_version(self, category: str, fingerprint: str) -> dict[str, object] | None:
        fields = self._version_fields(category, fingerprint)
        if fields is None:
            return None
        return dict(json.loads(str(fields[_CONTENT])))

    def version_exists(self, category: str, fingerprint: str) -> bool:
        return self._version_fields(category, fingerprint) is not None

    def read_index(self) -> list[dict[str, object]]:
        # 损坏（非法 JSON）如实抛错、不吞：台账是「哪版何时从哪来」的唯一记录（同本地后端口径）。
        out: list[dict[str, object]] = []
        for rec in self._client.list_records(self._sheet):
            fields = rec.get("fields", {})
            if fields.get(_KIND) == _KIND_INDEX:
                out.append(dict(json.loads(str(fields[_CONTENT]))))
        return out

    def append_index(self, entry: dict[str, object]) -> None:
        self._client.insert_record(
            self._sheet,
            {_KIND: _KIND_INDEX, _CONTENT: json.dumps(entry, ensure_ascii=False)},
        )
