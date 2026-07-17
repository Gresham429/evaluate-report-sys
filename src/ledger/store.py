"""台账存储。

**只增不改**：没有 `remove()`、没有 `save()`、没有 `update()`——能被改写的记录
不构成依据。同一报告编号生成五次就是五条，各带时间戳；台账会有废条，这是台账该有
的样子，不是缺陷。

**一条一个文件**，理由同 `src/drafts/store.py`：只增不改天然适合，不必读改写整份，
写坏最多折损一条。文件名带时间戳前缀便于人肉浏览，记录号保唯一。

JSON 而非 SQLite：单机、数据量小、无并发，且须人类可读可手改可备份。
"""

import logging
from pathlib import Path

from src.ledger.backend import LedgerBackend, LocalFileLedgerBackend
from src.ledger.model import LedgerEntry, from_dict, to_dict
from src.paths import data_dir

logger = logging.getLogger(__name__)

__all__ = ["LedgerStore", "DEFAULT_LEDGER_DIR"]

DEFAULT_LEDGER_DIR = data_dir() / "生成台账"


class LedgerStore:
    """报告生成台账。只增不改。"""

    def __init__(
        self, path: Path = DEFAULT_LEDGER_DIR, *, backend: LedgerBackend | None = None
    ) -> None:
        self.path = path  # 保留：既有调用点/测试仍读它
        # 持久化委托给可插拔后端；默认本地文件后端 → 既有行为一字不变。
        self._backend: LedgerBackend = backend or LocalFileLedgerBackend(path)

    def append(self, entry: LedgerEntry) -> str:
        """记一条，立即落盘。

        Returns:
            记录号。

        Raises:
            ValueError: 记录号形状不安全（含路径分隔符、空字节，或是 `.`/`..`）。
        """
        self._校验记录号(entry.记录号)
        self._backend.append(entry.记录号, entry.生成时间, to_dict(entry))
        logger.info("记台账 %s（报告 %s，经手人 %s）", entry.记录号, entry.报告编号, entry.经手人)
        return entry.记录号

    def list_all(self) -> tuple[LedgerEntry, ...]:
        """全部记录，生成时间新→旧。

        目录不存在时视为空——首次运行本就如此。
        时间相同时以记录号兜底排序，保证次序稳定可复现。
        """
        entries = self._读全部()
        entries.sort(key=lambda e: (e.生成时间, e.记录号), reverse=True)
        return tuple(entries)

    def get(self, 记录号: str) -> LedgerEntry | None:
        """按记录号取一条。

        **刻意不拿记录号拼路径**：这里是「先读全部、再按内容里的记录号字段过滤」，
        不像 `append()` 拼文件名那样直接把记录号嵌进路径。这不是没顾上性能，
        是安全选择——记录号会从网页 URL 原样传进来，若为了省下这次线性扫描而
        改成拼路径直读，`"../../etc/passwd"` 这类记录号就是路径穿越，会读到
        台账目录之外的文件。条目量对台账这种低频只增数据可忽略，这笔 O(n)
        换来「记录号无论长什么样都出不了这个目录」的保证，划算。
        `tests/test_ledger_store.py::test_get_rejects_path_traversal_record_id`
        钉死了这一点，回归会被它挡住。

        Returns:
            对应记录；记录号不存在（含形状可疑、明显是路径穿越的记录号）时
            均为 None。
        """
        return next((e for e in self._读全部() if e.记录号 == 记录号), None)

    @staticmethod
    def _校验记录号(记录号: str) -> None:
        """记录号落文件名前的形状校验，写法与理由对齐 `drafts/store.py::_文件()`。

        今天 `记录号` 只由 `new_record_id()`（uuid4 十六进制前 12 位）产出，
        只含 `0-9a-f`，天然是安全文件名——但那只是调用约定，不是类型系统能
        保证的事：`LedgerEntry` 是普通 frozen dataclass，`tests/test_ledger_model.py`
        里已有「绕开 `LedgerEntry.new()`、直接构造 `LedgerEntry(...)`」的先例，
        证明这条路走得通。将来若有调用方这么造一条记录号不干净的记录再
        `append()`，若不在这里挡，文件名就会被直接注入。

        Raises:
            ValueError: 记录号为空，或含路径分隔符、空字节，或是 `.`/`..`。
        """
        if (
            not 记录号
            or "/" in 记录号
            or "\\" in 记录号
            or "\0" in 记录号
            or 记录号 in (".", "..")
        ):
            logger.warning("记录号形状不安全，拒绝落台账：%r", 记录号)
            raise ValueError(f"记录号不合法：{记录号!r}")

    def _读全部(self) -> list[LedgerEntry]:
        """从后端读出全部记录。还原失败的单条跳过，不连累其余。

        坏文件的容错（文件明说可手改、改坏一份不该拖垮整份台账）现由本地文件
        后端在 iter_payloads 里兜；这里再兜一层"payload 能读出但字段坏"的还原失败。
        """
        entries: list[LedgerEntry] = []
        for payload in self._backend.iter_payloads():
            try:
                entries.append(from_dict(payload))
            except (KeyError, TypeError, ValueError):
                logger.warning("台账 payload 还原失败，已跳过", exc_info=True)
        return entries
