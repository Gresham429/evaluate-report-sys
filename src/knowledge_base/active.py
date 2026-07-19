"""每类别「当前生效版本」的本地选择（D2）。

多维表是版本真源；本地拉取缓存后，每台机器各自选一个生效版本（全局默认），
新报告用它。存 `data/基础表/生效版本.json` = `{类别: 指纹}`。缺该文件、缺某类、
或指向已不在库的指纹 → 回落该类别最新导入版（`store.current`）。生效选择是本地
偏好：不同步、不进指纹、坏了可重建。
"""

import json
import logging
from pathlib import Path

from src.knowledge_base.store import BaseTableStore
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["ActiveVersions", "active_fingerprint", "ACTIVE_NAME"]

ACTIVE_NAME = "生效版本.json"


class ActiveVersions:
    """读写「类别 → 生效指纹」的本地配置。"""

    def __init__(self, dir_path: Path) -> None:
        self._path = dir_path / ACTIVE_NAME

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # 损坏不致命：生效选择是可重建偏好，坏了当没选、回落最新，记一条 warning。
            logger.warning("生效版本配置损坏，忽略并回落最新：%s（%s）", self._path, exc)
            return {}
        return {str(k): str(v) for k, v in dict(raw).items()}

    def get(self, category: Category) -> str | None:
        return self._read().get(category.value)

    def set(self, category: Category, fingerprint: str) -> None:
        data = self._read()
        data[category.value] = fingerprint
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def active_fingerprint(
    store: BaseTableStore, active: ActiveVersions, category: Category
) -> str | None:
    """该类别当前应使用的版本指纹。

    配了生效版且该版本仍在库 → 用它；否则回落最新导入版。该类别尚无任何版本时 None。
    """
    chosen = active.get(category)
    if chosen is not None:
        if any(v.指纹 == chosen for v in store.list_versions(category)):
            return chosen
        logger.warning("%s 类生效版本 %s 已不在库，回落最新", category.value, chosen)
    latest = store.current(category)
    return latest.指纹 if latest is not None else None
