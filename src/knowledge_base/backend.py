"""基础表存储后端：把"版本文件 + 版本台账落在哪"从 BaseTableStore 分出来。

BaseTableStore 管业务（指纹计算/校验、类别识别、旧版永不覆盖、文件缺失补回、去重）；
后端只管两件持久化：①按 (类别,指纹) 存/读一份**不可变**版本内容；②读/追加**版本台账索引**。
今天只有本地文件后端；将来钉钉/宜搭远端后端实现同一 Protocol 即可插进来
（宜搭里：一版一行、台账即查表本身；见 docs 宜搭数据模型 §2 表 D）。

搬的是不透明 payload dict（版本内容 = to_dict(Knowledge)；索引条目 = VersionInfo 的
dict），序列化仍归 BaseTableStore（铁律 #5/#8 的口径不进后端）。
"""

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = ["BaseTableBackend", "LocalFileBaseTableBackend", "InMemoryBaseTableBackend"]

_LEDGER_NAME = "台账.json"


@runtime_checkable
class BaseTableBackend(Protocol):
    """基础表持久化后端。版本内容不可变（只在不存在时写）；台账只追加。"""

    def write_version(self, category: str, fingerprint: str, payload: dict[str, object]) -> None:
        """存一份版本内容。**只在该版本不存在时被调用**（不可变，铁律 #8）。"""
        ...

    def read_version(self, category: str, fingerprint: str) -> dict[str, object] | None:
        """读一份版本内容；不存在返回 None。"""
        ...

    def version_exists(self, category: str, fingerprint: str) -> bool:
        """该 (类别,指纹) 版本是否已落库。"""
        ...

    def read_index(self) -> list[dict[str, object]]:
        """读版本台账（全部条目的原始 dict）。空库返回 []；损坏须抛错，不吞。"""
        ...

    def append_index(self, entry: dict[str, object]) -> None:
        """追加一条版本台账。"""
        ...


class LocalFileBaseTableBackend:
    """一版一个 JSON 文件（`{类别}-{指纹}.json`）+ 一份 `台账.json` 索引。

    行为搬自原 BaseTableStore，字节级不变：版本文件人类可读、不加原子写（不可变，
    靠"只在不存在时写"保证）；台账整档读改写。
    """

    def __init__(self, path: Path, ledger_name: str = _LEDGER_NAME) -> None:
        self.path = path
        self._ledger_name = ledger_name

    def _version_path(self, category: str, fingerprint: str) -> Path:
        return self.path / f"{category}-{fingerprint}.json"

    def write_version(self, category: str, fingerprint: str, payload: dict[str, object]) -> None:
        target = self._version_path(category, fingerprint)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_version(self, category: str, fingerprint: str) -> dict[str, object] | None:
        target = self._version_path(category, fingerprint)
        if not target.exists():
            return None
        return dict(json.loads(target.read_text(encoding="utf-8")))

    def version_exists(self, category: str, fingerprint: str) -> bool:
        return self._version_path(category, fingerprint).exists()

    def _ledger_path(self) -> Path:
        return self.path / self._ledger_name

    def read_index(self) -> list[dict[str, object]]:
        path = self._ledger_path()
        if not path.exists():
            logger.debug("基础表台账不存在，视为空库：%s", path)
            return []
        # 损坏（非法 JSON）如实抛错，不吞：台账是「哪版何时从哪来」的唯一记录，
        # 静默当空库会让下次导入把已有版本重记一遍。
        raw = json.loads(path.read_text(encoding="utf-8"))
        return list(raw)

    def append_index(self, entry: dict[str, object]) -> None:
        entries = [*self.read_index(), entry]
        self._ledger_path().parent.mkdir(parents=True, exist_ok=True)
        self._ledger_path().write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class InMemoryBaseTableBackend:
    """内存基础表后端：供测试与离线。也是"宜搭/远端后端"要满足的可执行契约。"""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], dict[str, object]] = {}
        self._index: list[dict[str, object]] = []

    def write_version(self, category: str, fingerprint: str, payload: dict[str, object]) -> None:
        self._versions[(category, fingerprint)] = payload

    def read_version(self, category: str, fingerprint: str) -> dict[str, object] | None:
        return self._versions.get((category, fingerprint))

    def version_exists(self, category: str, fingerprint: str) -> bool:
        return (category, fingerprint) in self._versions

    def read_index(self) -> list[dict[str, object]]:
        return list(self._index)

    def append_index(self, entry: dict[str, object]) -> None:
        self._index.append(entry)
