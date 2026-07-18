"""后端工厂：按 env 选"多维表"或"本地"后端。三个 Store 的默认后端走这里。

选择而已、不做 I/O（NotableClient 的 token 是首次调用才取）。开关关、配置缺、
或该 Store 没配 sheet → 一律回本地后端（今天的行为一字不变）。断网时的"本地缓存
兜底"是另一个特性（须配 per-user 缓存），本层不做：多维表模式即联网模式，
与「出正式报告需联网」一致。
"""

from pathlib import Path

from src.dingtalk import config
from src.knowledge_base.backend import BaseTableBackend, LocalFileBaseTableBackend
from src.knowledge_base.notable_backend import NotableBaseTableBackend
from src.ledger.backend import LedgerBackend, LocalFileLedgerBackend
from src.ledger.notable_backend import NotableLedgerBackend
from src.library.backend import InstanceBackend, LocalFileInstanceBackend
from src.library.notable_backend import NotableInstanceBackend

__all__ = ["ledger_backend_for", "instance_backend_for", "base_table_backend_for"]


def ledger_backend_for(path: Path) -> LedgerBackend:
    if config.use_notable() and config.ledger_sheet():
        client = config.build_client()
        if client is not None:
            return NotableLedgerBackend(client, config.ledger_sheet())
    return LocalFileLedgerBackend(path)


def instance_backend_for(path: Path) -> InstanceBackend:
    if config.use_notable() and config.instance_sheet():
        client = config.build_client()
        if client is not None:
            return NotableInstanceBackend(client, config.instance_sheet())
    return LocalFileInstanceBackend(path)


def base_table_backend_for(path: Path) -> BaseTableBackend:
    if config.use_notable() and config.base_table_sheet():
        client = config.build_client()
        if client is not None:
            return NotableBaseTableBackend(client, config.base_table_sheet())
    return LocalFileBaseTableBackend(path)
