"""草稿的数据模型与 id 生成。

草稿是**表单状态的续填缓冲，不是权威数据**。故 `数据` 按不透明 JSON 存，后端
不理解也不校验其内部形状——表单字段日后必然增删，后端跟着改一次就是一次多余的
耦合。只有 `报告编号` 与 `类别` 被抽出来平铺，且仅为列表展示。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger(__name__)

__all__ = ["Draft", "DraftInfo", "new_id"]


def new_id() -> str:
    """生成草稿 id。

    用随机数而非时间戳：估价师可能同一秒连存两份（表单边填边存），时钟精度
    防不住相撞。取 uuid4 十六进制前 12 位——只含 0-9a-f，落成文件名天然安全，
    不必像 `_safe_filename` 那样清洗；也不含 `[]` 这类 glob 元字符，
    `Path.glob` 拿它拼模式不会被吞。

    id 刻意**不由报告编号派生**：报告编号在草稿里是会变的（填一半时甚至为空），
    派生就意味着改个编号会换掉 id，覆盖语义随之失效。

    Returns:
        12 位十六进制字符串。
    """
    return uuid4().hex[:12]


def _抽平铺字段(数据: dict[str, object], 键: str) -> str:
    """从表单数据里抽一个平铺字段，抽不到就留空。

    一律不抛：草稿本就可能填一半，此时报告编号还没填，这是常态而非错误。
    非字符串值（形状变了、或表单塞了别的类型）同样退化为空——平铺字段只供
    列表展示，展示只认字符串，猜不出来就别猜。
    """
    值 = 数据.get(键)
    return 值.strip() if isinstance(值, str) else ""


@dataclass(frozen=True)
class DraftInfo:
    """草稿摘要，供列表展示。

    **不含 `数据`**：列表页不需要，而单个估价对象最少 52 项，`数据` 可能很大。
    """

    id: str
    报告编号: str
    类别: str
    更新时间: datetime


@dataclass(frozen=True)
class Draft:
    """一份完整草稿。

    `数据` 是表单原样塞进来的内容，后端不看其内部。
    """

    id: str
    报告编号: str
    类别: str
    更新时间: datetime
    数据: dict[str, object]

    @staticmethod
    def new(
        数据: dict[str, object],
        draft_id: str | None = None,
        now: datetime | None = None,
    ) -> "Draft":
        """由表单数据造一份草稿记录。

        Args:
            数据: 表单原样内容，不校验形状。
            draft_id: 续存已有草稿时传入其 id；缺省则新生成一个（即新建一份）。
            now: 更新时间；缺省取当前时刻。显式开这个口子是为了让测试固定时间，
                模块内不直接调 `datetime.now()`。

        Returns:
            草稿记录。`报告编号`/`类别` 已从 `数据` 抽出平铺，抽不到则为空串。
        """
        return Draft(
            id=draft_id or new_id(),
            报告编号=_抽平铺字段(数据, "报告编号"),
            类别=_抽平铺字段(数据, "类别"),
            更新时间=now or datetime.now(),
            数据=数据,
        )

    def info(self) -> DraftInfo:
        """取摘要（丢掉 `数据`）。"""
        return DraftInfo(
            id=self.id, 报告编号=self.报告编号, 类别=self.类别, 更新时间=self.更新时间
        )
