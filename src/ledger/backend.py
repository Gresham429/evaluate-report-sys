"""台账存储后端：把"数据到底落在哪"从 LedgerStore 里分出来。

LedgerStore 管业务（记录号安全、排序、按内容过滤）；后端只管"把一条 payload
存下去、把全部 payload 读出来"。今天只有本地文件后端；将来钉钉/宜搭远端后端
实现同一个 Protocol 即可插进来，LedgerStore 一行不改（见 docs 钉钉同步 design §5/§2b）。

**只增不改**（铁律 #4）：接口没有 update/delete。搬的是不透明 payload dict，
序列化仍归 ledger/model.py（铁律 #5 自洽快照不进后端）。
"""

import json
import logging
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = ["LedgerBackend", "LocalFileLedgerBackend", "InMemoryLedgerBackend"]


@runtime_checkable
class LedgerBackend(Protocol):
    """台账持久化后端。只 append、只读，无 update/delete。"""

    def append(
        self, record_id: str, created_at: datetime, payload: dict[str, object]
    ) -> None:
        """落一条。record_id 已由 LedgerStore 校验过形状安全。"""
        ...

    def iter_payloads(self) -> Iterator[dict[str, object]]:
        """逐条读出全部 payload（顺序不保证；排序归 LedgerStore）。"""
        ...


class LocalFileLedgerBackend:
    """一条一个 JSON 文件，原子写，坏文件跳过。行为搬自原 LedgerStore。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(
        self, record_id: str, created_at: datetime, payload: dict[str, object]
    ) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        stamp = created_at.strftime("%Y%m%d-%H%M%S")
        # 文件名只用时间戳与记录号：报告编号含 [] 等字符，既要清洗又会被 glob
        # 当元字符吞掉。报告编号在文件内容里，够查。
        file = self.path / f"{stamp}-{record_id}.json"
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        # 先写临时文件再原子替换：中途崩掉不留半份 JSON（台账记下的必须作数）。
        tmp = file.with_suffix(".json.tmp")  # 不叫 *.json，免得被 iter_payloads 扫到
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, file)

    def iter_payloads(self) -> Iterator[dict[str, object]]:
        if not self.path.exists():
            logger.debug("台账目录不存在，视为空：%s", self.path)
            return
        for file in self.path.glob("*.json"):
            try:
                yield json.loads(file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                # 台账文件明说可手改，改坏就得容错：一份坏文件不连累其余。
                logger.warning("台账文件读不出，已跳过：%s", file, exc_info=True)


class InMemoryLedgerBackend:
    """内存台账后端：供测试与离线。append-only，不落盘。

    也是"宜搭/远端后端"将来要满足的可执行契约（append=新增、iter=读全部）。
    """

    def __init__(self) -> None:
        self._payloads: list[dict[str, object]] = []

    def append(
        self, record_id: str, created_at: datetime, payload: dict[str, object]
    ) -> None:
        self._payloads.append(payload)

    def iter_payloads(self) -> Iterator[dict[str, object]]:
        return iter(list(self._payloads))
