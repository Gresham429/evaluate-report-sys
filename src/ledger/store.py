"""台账存储。

**只增不改**：没有 `remove()`、没有 `save()`、没有 `update()`——能被改写的记录
不构成依据。同一报告编号生成五次就是五条，各带时间戳；台账会有废条，这是台账该有
的样子，不是缺陷。

**一条一个文件**，理由同 `src/drafts/store.py`：只增不改天然适合，不必读改写整份，
写坏最多折损一条。文件名带时间戳前缀便于人肉浏览，记录号保唯一。

JSON 而非 SQLite：单机、数据量小、无并发，且须人类可读可手改可备份。
"""

import json
import logging
import os
from pathlib import Path

from src.ledger.model import LedgerEntry, from_dict, to_dict
from src.paths import data_dir

logger = logging.getLogger(__name__)

__all__ = ["LedgerStore", "DEFAULT_LEDGER_DIR"]

DEFAULT_LEDGER_DIR = data_dir() / "生成台账"


class LedgerStore:
    """报告生成台账。只增不改。"""

    def __init__(self, path: Path = DEFAULT_LEDGER_DIR) -> None:
        self.path = path

    def append(self, entry: LedgerEntry) -> str:
        """记一条，立即落盘。

        Returns:
            记录号。

        Raises:
            ValueError: 记录号形状不安全（含路径分隔符、空字节，或是 `.`/`..`）。
        """
        self._校验记录号(entry.记录号)
        self.path.mkdir(parents=True, exist_ok=True)
        stamp = entry.生成时间.strftime("%Y%m%d-%H%M%S")
        # 文件名只用时间戳与记录号：报告编号含 [] 等字符，既要清洗又会被 glob
        # 当元字符吞掉。报告编号在文件内容里，够查。
        file = self.path / f"{stamp}-{entry.记录号}.json"
        text = json.dumps(to_dict(entry), ensure_ascii=False, indent=2)

        # 先写临时文件再原子替换：直接写若中途崩掉会留下截断的半份 JSON，
        # 而台账的意义就是「记下来的必须作数」。
        tmp = file.with_suffix(".json.tmp")  # 不叫 *.json，免得被 list_all 扫到
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, file)

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
        """读出目录下的全部记录。坏掉的单份跳过，不连累其余。"""
        if not self.path.exists():
            logger.debug("台账目录不存在，视为空：%s", self.path)
            return []
        entries: list[LedgerEntry] = []
        for file in self.path.glob("*.json"):
            try:
                entries.append(from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                # 台账文件明说可以手改，改坏就得容错：一份坏文件不该让整个台账
                # 打不开，否则其余完好的记录也一起查不了。
                logger.warning("台账文件读不出，已跳过：%s", file, exc_info=True)
        return entries
