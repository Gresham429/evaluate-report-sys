"""实例库存储。

JSON 而非 SQLite：单机单用户、数据量小（预计数百条）、无并发；
JSON 便于估价师直接查看、手改与备份，无需引入运维负担。
"""

import json
import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path

from src.library.model import DatePrecision, StoredInstance
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["InstanceStore", "DEFAULT_STORE_PATH"]

DEFAULT_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "实例库.json"


class InstanceStore:
    """实例库。按类别分类，按起始日从新到旧列出。**不做任何推荐或筛选。**"""

    def __init__(self, path: Path = DEFAULT_STORE_PATH) -> None:
        self.path = path
        self._items: dict[str, StoredInstance] = {}

    def load(self) -> None:
        """从磁盘加载。文件不存在时视为空库。"""
        if not self.path.exists():
            logger.debug("实例库不存在，视为空库：%s", self.path)
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._items = {r["编号"]: self._from_dict(r) for r in raw}
        logger.info("加载实例库 %s：%d 条", self.path, len(self._items))

    def save(self) -> None:
        """写回磁盘。UTF-8、缩进、不转义中文——须人类可读可手改。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [self._to_dict(i) for i in self._items.values()]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("写入实例库 %s：%d 条", self.path, len(self._items))

    def add(self, instance: StoredInstance) -> bool:
        """入库。

        Returns:
            True 表示已新增；False 表示编号已存在（**不覆盖**）。
        """
        if instance.编号 in self._items:
            logger.warning("实例编号已存在，未覆盖：%s", instance.编号)
            return False
        self._items[instance.编号] = instance
        return True

    def remove(self, 编号: str) -> bool:
        """删除。

        Returns:
            True 表示已删除；False 表示不存在。
        """
        return self._items.pop(编号, None) is not None

    def list_by_category(self, category: Category) -> tuple[StoredInstance, ...]:
        """按类别列出，起始日从新到旧。

        **不做推荐、不高亮、不打分、不筛选**——哪条更可比由估价师判断。
        起始日为空者排在最后。
        """
        items = [i for i in self._items.values() if i.类别 is category]
        items.sort(key=lambda i: i.起始日 or date.min, reverse=True)
        return tuple(items)

    @staticmethod
    def _to_dict(inst: StoredInstance) -> dict[str, object]:
        data = asdict(inst)
        data["类别"] = inst.类别.value
        data["日期精度"] = inst.日期精度.value
        data["起始日"] = inst.起始日.isoformat() if inst.起始日 else None
        return data

    @staticmethod
    def _from_dict(data: dict[str, object]) -> StoredInstance:
        start = data.get("起始日")
        return StoredInstance(
            编号=str(data["编号"]),
            类别=Category(str(data["类别"])),
            位置=str(data["位置"]),
            成交价=float(data["成交价"]),  # type: ignore[arg-type]
            面积=float(data["面积"]),  # type: ignore[arg-type]
            出租用途=str(data["出租用途"]),
            交易情况=str(data["交易情况"]),
            租期原文=str(data["租期原文"]),
            起始日=date.fromisoformat(str(start)) if start else None,
            日期精度=DatePrecision(str(data["日期精度"])),
            因素档次=dict(data.get("因素档次", {})),  # type: ignore[call-overload]
            备注=str(data.get("备注", "")),
        )
