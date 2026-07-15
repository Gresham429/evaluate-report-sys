"""实例库的数据模型与日期解析。

「交易日期」在现有素材中是自由文本，实测四种格式并存：
    '2026.1.15-2026.7.14'      完整日期区间（办公）
    datetime(2025, 10, 28)     真日期类型，单值非区间（商业）
    '2025.7-2026.7'            仅年月（农用）
    '2025-2026'                仅年份（农用，9 条素材中 2 条如此）

用户选定方案丙：有什么记什么，原文保留，日期不精确的打标记，不强制补全。
理由：强制补全会当场卡住（那 2 条的真实租期多半已查不回）；照单全收
则让"日期不可靠"这个事实在库里消失。丙保留事实，把判断交给人。
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["DatePrecision", "StoredInstance", "parse_lease_start", "make_id"]

# 实测：内部日期分隔符只用 '.' 或 '/'（如 '2026.1.15'）；'-' 专用于区间
# 分隔（'2025.7-2026.7'）或裸年份区间（'2025-2026'）。若把 '-' 也纳入内部
# 分隔符类，会跨过区间边界把第二个日期的前几位数字吞成本日期的月/日，
# 例如把 '2025.7-2026.7' 误判成 FULL 并解出 date(2025, 7, 20)，把
# '2025-2026' 误判出月份 20 直接抛 ValueError。故此处刻意不含 '-'。
_FULL_RE = re.compile(r"(\d{4})[./](\d{1,2})[./](\d{1,2})")
_YEAR_MONTH_RE = re.compile(r"(\d{4})[./](\d{1,2})(?![./]\d)")
_YEAR_RE = re.compile(r"(\d{4})")


class DatePrecision(StrEnum):
    """租期起始日的精度。"""

    FULL = "完整"
    YEAR_MONTH = "仅年月"
    YEAR = "仅年"
    UNKNOWN = "无法解析"


@dataclass(frozen=True)
class StoredInstance:
    """实例库中的一条实例。

    市场状况指数**不在此处**——它是「实例 × 本项目价值时点」的配对属性，
    同一实例用于不同时点的项目必须重填，故由估价师每次现填。
    """

    编号: str
    类别: Category
    位置: str
    成交价: float
    面积: float
    出租用途: str
    交易情况: str
    租期原文: str
    起始日: date | None
    日期精度: DatePrecision
    因素档次: dict[str, str] = field(default_factory=dict)
    备注: str = ""


def parse_lease_start(raw: object) -> tuple[date | None, DatePrecision]:
    """解析租期起始日及其精度。

    Args:
        raw: 「交易日期」单元格的原始值。

    Returns:
        (起始日, 精度)。仅年月时日取 1；仅年份时月日取 1/1；无法解析时为 (None, UNKNOWN)。
    """
    if isinstance(raw, datetime):
        return raw.date(), DatePrecision.FULL
    if isinstance(raw, date):
        return raw, DatePrecision.FULL
    if raw is None:
        return None, DatePrecision.UNKNOWN

    text = str(raw).strip()
    if m := _FULL_RE.search(text):
        return date(int(m[1]), int(m[2]), int(m[3])), DatePrecision.FULL
    if m := _YEAR_MONTH_RE.search(text):
        return date(int(m[1]), int(m[2]), 1), DatePrecision.YEAR_MONTH
    if m := _YEAR_RE.search(text):
        return date(int(m[1]), 1, 1), DatePrecision.YEAR
    logger.warning("租期原文 %r 无法解析出起始日", text)
    return None, DatePrecision.UNKNOWN


def make_id(
    category: Category, start: date | None, precision: DatePrecision, location: str
) -> str:
    """生成实例编号：`类别-起始年(月)-位置`。

    仅有年份时退化为 `类别-年-位置` —— 月份压不出来就不假造。

    Args:
        category: 类别。
        start: 起始日。
        precision: 日期精度。
        location: 位置，多余空白会被压缩。

    Returns:
        编号字符串。
    """
    place = re.sub(r"\s+", " ", location).strip()
    if start is None or precision is DatePrecision.UNKNOWN:
        stamp = "日期未知"
    elif precision is DatePrecision.YEAR:
        stamp = f"{start.year}"
    else:
        stamp = f"{start.year}-{start.month:02d}"
    return f"{category.value}-{stamp}-{place}"
