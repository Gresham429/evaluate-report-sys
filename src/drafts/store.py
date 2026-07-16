"""草稿存储。

**一份草稿一个文件**，而非全塞一个 JSON——与实例库（`src/library/store.py`
用单文件）刻意相反，理由是两者的写入形态不同：

- 写得频繁：表单边填边存，单文件意味着每存一份就要把所有草稿重写一遍，
  白写 O(n)；一份一文件只重写自己那份。
- 爆炸半径：草稿功能的唯一目的就是「填一半别丢」。单文件写到一半崩掉会
  连坐全部草稿，把「一次写坏、全部丢光」引进来与这个目的自相矛盾；
  一份一文件最多折损一份。
- 删除即 unlink，不必惊动别人。

实例库反过来用单文件是对的：它低频写入、条目要整体载入并按类别一起看。
草稿高频写入、彼此独立、只按 id 单取，没有整体载入的需要。

代价是 `list_all()` 要读 N 个文件。草稿数量预计几十份，可忽略。
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from src.drafts.model import Draft, DraftInfo
from src.paths import data_dir

logger = logging.getLogger(__name__)

__all__ = ["DraftStore", "DEFAULT_DRAFT_DIR"]

DEFAULT_DRAFT_DIR = data_dir() / "草稿"


class DraftStore:
    """本机草稿。存、列、取、删，不校验 `数据` 的形状。

    与 `InstanceStore` 不同，本类不做内存缓存、无 `load()`/`save()` 两段式：
    每次 `save()` 立即落盘。边填边存要的就是「存了就不会丢」，攒在内存里
    等一次总写恰好是这功能要防的事。
    """

    def __init__(self, path: Path = DEFAULT_DRAFT_DIR) -> None:
        self.path = path

    def save(self, draft: Draft) -> str:
        """存一份草稿，立即落盘。

        id 已存在则**覆盖**——草稿的语义就是覆盖，与实例库的「不覆盖」正相反：
        实例是既成事实的记录，重复编号多半是误操作，故 `InstanceStore.add()`
        拒绝；草稿是正在改的东西，后一次保存本就该顶掉前一次。

        Args:
            draft: 草稿记录，通常由 `Draft.new()` 造出。

        Returns:
            草稿 id（即 `draft.id`），供前端续存时回传。

        Raises:
            ValueError: id 形状不安全（含路径分隔符等）。
        """
        file = self._文件(draft.id)
        file.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self.to_dict(draft), ensure_ascii=False, indent=2)

        # 先写临时文件再原子替换：直接就地重写时若中途崩掉，会留下截断的半份
        # JSON，等于把这份草稿弄丢——而防丢正是本模块存在的理由。
        tmp = file.with_suffix(".json.tmp")  # 不叫 *.json，免得被 list_all 扫到
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, file)

        logger.info("存草稿 %s（报告编号 %r）", draft.id, draft.报告编号)
        return draft.id

    def list_all(self) -> tuple[DraftInfo, ...]:
        """列出全部草稿摘要，按更新时间新→旧。

        只给摘要，不含 `数据`——列表页不需要，且单个估价对象最少 52 项，可能很大。
        目录不存在时视为无草稿（首次运行必然如此）。

        更新时间相同时以 id 兜底排序，保证次序稳定可复现。
        """
        if not self.path.exists():
            logger.debug("草稿目录不存在，视为无草稿：%s", self.path)
            return ()

        infos = [d.info() for d in self._读全部()]
        infos.sort(key=lambda i: (i.更新时间, i.id), reverse=True)
        return tuple(infos)

    def get(self, draft_id: str) -> Draft | None:
        """按 id 取一份完整草稿。

        Returns:
            对应草稿；id 不存在时为 None。

        Raises:
            ValueError: id 形状不安全（含路径分隔符等）。
        """
        file = self._文件(draft_id)
        if not file.exists():
            return None
        return self.from_dict(json.loads(file.read_text(encoding="utf-8")))

    def remove(self, draft_id: str) -> bool:
        """删一份草稿。

        Returns:
            True 表示已删除；False 表示不存在。

        Raises:
            ValueError: id 形状不安全（含路径分隔符等）。
        """
        file = self._文件(draft_id)
        try:
            file.unlink()
        except FileNotFoundError:
            return False
        logger.info("删草稿 %s", draft_id)
        return True

    def _文件(self, draft_id: str) -> Path:
        """草稿 id 对应的文件路径。

        id 会从网页请求原样传进来，故必须挡住 `../` 这类路径穿越：草稿目录
        之外的文件不该被本模块读到或删掉。

        Raises:
            ValueError: id 为空，或含路径分隔符、空字节，或是 `.`/`..`。
        """
        if (
            not draft_id
            or "/" in draft_id
            or "\\" in draft_id
            or "\0" in draft_id
            or draft_id in (".", "..")
        ):
            logger.warning("草稿 id 形状不安全，拒绝：%r", draft_id)
            raise ValueError(f"草稿 id 不合法：{draft_id!r}")
        return self.path / f"{draft_id}.json"

    def _读全部(self) -> list[Draft]:
        """读出目录下的全部草稿。坏掉的单份跳过，不连累其余。"""
        drafts = []
        for file in self.path.glob("*.json"):
            try:
                drafts.append(self.from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, KeyError, ValueError):
                # 草稿文件是明说可以手改的，改坏就得容错：一份坏文件不该让
                # 整个草稿列表打不开，否则其余完好的草稿也一起没法续填了。
                logger.warning("草稿文件读不出，已跳过：%s", file, exc_info=True)
        return drafts

    @staticmethod
    def to_dict(draft: Draft) -> dict[str, object]:
        """序列化为 JSON 安全的字典。供磁盘持久化，也供网页接口复用，
        保证接口与草稿文件的形状始终一致。"""
        return {
            "id": draft.id,
            "报告编号": draft.报告编号,
            "类别": draft.类别,
            "更新时间": draft.更新时间.isoformat(),
            "数据": draft.数据,
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> Draft:
        """由 to_dict 的输出还原。

        `数据` 原样取回，不校验内部形状。

        Raises:
            KeyError: 必需字段缺失。
            ValueError: 更新时间不是合法 ISO 时刻。
        """
        return Draft(
            id=str(data["id"]),
            报告编号=str(data.get("报告编号", "")),
            类别=str(data.get("类别", "")),
            更新时间=datetime.fromisoformat(str(data["更新时间"])),
            数据=dict(data.get("数据", {})),  # type: ignore[call-overload]
        )
