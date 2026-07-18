"""实例库存储。

JSON 而非 SQLite：单机单用户、数据量小（预计数百条）、无并发；
JSON 便于估价师直接查看、手改与备份，无需引入运维负担。
"""

import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path

from src.library.backend import InstanceBackend
from src.library.model import DatePrecision, StoredInstance
from src.paths import data_dir
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["InstanceStore", "DEFAULT_STORE_PATH"]

DEFAULT_STORE_PATH = data_dir() / "实例库.json"


class InstanceStore:
    """实例库。按类别分类，按起始日从新到旧列出。**不做任何推荐或筛选。**"""

    def __init__(
        self, path: Path = DEFAULT_STORE_PATH, *, backend: InstanceBackend | None = None
    ) -> None:
        self.path = path  # 保留：既有调用点/测试仍读它
        # 持久化委托给可插拔后端；默认后端由工厂按 env 选（未配置=本地文件，行为一字不变）。
        # 工厂延迟到实例化时导入，避免 store→factory→store 的模块级循环导入。
        if backend is None:
            from src.dingtalk.factory import instance_backend_for

            backend = instance_backend_for(path)
        self._backend: InstanceBackend = backend
        self._items: dict[str, StoredInstance] = {}

    def load(self) -> None:
        """从后端加载整库。空库时 self._items 为空。"""
        self._items = {
            str(r["编号"]): self.from_dict(r) for r in self._backend.load()
        }
        logger.info("加载实例库：%d 条", len(self._items))

    def save(self) -> None:
        """整库写回后端。序列化须人类可读可手改（本地后端保证）。"""
        self._backend.save([self.to_dict(i) for i in self._items.values()])
        logger.info("写入实例库：%d 条", len(self._items))

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

    def get(self, 编号: str) -> StoredInstance | None:
        """按编号取一条。

        Returns:
            对应实例；编号不在库中时为 None。
        """
        return self._items.get(编号)

    def list_by_category(self, category: Category) -> tuple[StoredInstance, ...]:
        """按类别列出，起始日从新到旧。

        **不做推荐、不高亮、不打分、不筛选**——哪条更可比由估价师判断。
        起始日为空者排在最后。
        """
        items = [i for i in self._items.values() if i.类别 is category]
        items.sort(key=lambda i: i.起始日 or date.min, reverse=True)
        return tuple(items)

    @staticmethod
    def to_dict(inst: StoredInstance) -> dict[str, object]:
        """序列化为 JSON 安全的字典。供磁盘持久化，也供 /api/import、/api/library 复用，
        保证网页接口与库文件的形状始终一致。"""
        data = asdict(inst)
        data["类别"] = inst.类别.value
        data["日期精度"] = inst.日期精度.value
        data["起始日"] = inst.起始日.isoformat() if inst.起始日 else None
        return data

    @staticmethod
    def from_dict(data: dict[str, object]) -> StoredInstance:
        """由 to_dict 的输出还原。

        Raises:
            KeyError: 必需字段缺失。
            ValueError: 字段值不合法（如类别、日期精度不是已知枚举值）。
        """
        start = data.get("起始日")
        return StoredInstance(
            编号=str(data["编号"]),
            类别=Category(str(data["类别"])),
            位置=str(data["位置"]),
            成交价=float(data["成交价"]),  # type: ignore[arg-type]
            面积=float(data["面积"]),  # type: ignore[arg-type]
            出租用途=str(data["出租用途"]),
            交易情况=str(data["交易情况"]),
            交易情况指数=float(data["交易情况指数"]),  # type: ignore[arg-type]
            租期原文=str(data["租期原文"]),
            起始日=date.fromisoformat(str(start)) if start else None,
            日期精度=DatePrecision(str(data["日期精度"])),
            因素档次=dict(data.get("因素档次", {})),  # type: ignore[call-overload]
            备注=str(data.get("备注", "")),
        )
