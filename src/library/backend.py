"""实例库存储后端：把"整库存在哪"从 InstanceStore 分出来。

InstanceStore 管业务（内存态、去重、按类别列、按起始日排）；后端只管"把整库
读出来 / 整库写回去"。实例库是低频、基本只增的整档 JSON，故后端按整库 load/save
（与台账/基础表的按条不同——各存储的缝口贴各自的访问模式）。

将来宜搭远端后端实现同一 Protocol：load = 拉全部行、save = 同步行（实例基本只增，
多为新增行）。见 docs 宜搭数据模型 §2 表 C。搬的是不透明 record dict，序列化仍归
InstanceStore。
"""

import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = ["InstanceBackend", "LocalFileInstanceBackend", "InMemoryInstanceBackend"]


@runtime_checkable
class InstanceBackend(Protocol):
    """实例库持久化后端：整库读 / 整库写。"""

    def load(self) -> list[dict[str, object]]:
        """读出全部实例的原始 dict；空库返回 []。"""
        ...

    def save(self, records: list[dict[str, object]]) -> None:
        """整库写回。"""
        ...


class LocalFileInstanceBackend:
    """单个 JSON 数组文件。行为搬自原 InstanceStore，字节级不变（人类可读、缩进）。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[dict[str, object]]:
        if not self.path.exists():
            logger.debug("实例库不存在，视为空库：%s", self.path)
            return []
        return list(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, records: list[dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class InMemoryInstanceBackend:
    """内存实例库后端：供测试与离线。也是"宜搭/远端后端"要满足的可执行契约。"""

    def __init__(self) -> None:
        self._records: list[dict[str, object]] = []

    def load(self) -> list[dict[str, object]]:
        return list(self._records)

    def save(self, records: list[dict[str, object]]) -> None:
        self._records = list(records)
