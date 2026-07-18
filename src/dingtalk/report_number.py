"""报告编号领号：向台账多维表要一个全公司唯一递增号（§3①）。

多维表的「自动编号」字段行创建即自增、允许跳号——正合"领了没出报告即跳空"。
领号 = 插一行占位/领号记录（可带实勘/项目元信息）→ 回读该行的自动编号 → 组装成
`正恒评报字[YYYY]第{序号}号`。领号时机在实勘开始，绑定整个项目。

离线（领不到号）由调用方处理：只出草稿、不发正式号（§3①）。本函数只管"联网时领一个号"。
"""

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

__all__ = ["draw_report_number", "SEQ_FIELD"]

SEQ_FIELD = "报告序号"
_PREFIX = "正恒评报字"


class _RecordClient(Protocol):
    """领号只用到客户端的这两件：插一行、按 id 回读。"""

    def insert_record(self, sheet: str, fields: dict[str, Any]) -> str: ...
    def get_record(self, sheet: str, record_id: str) -> dict[str, Any]: ...


def draw_report_number(
    client: _RecordClient,
    sheet: str,
    *,
    year: int,
    seq_field: str = SEQ_FIELD,
    prefix: str = _PREFIX,
    metadata: dict[str, Any] | None = None,
) -> str:
    """领一个报告编号。

    Args:
        client: notable 客户端。
        sheet: 台账表。
        year: 编号里的年份。
        seq_field: 自动编号字段名。
        prefix: 编号前缀。
        metadata: 领号行要带的元信息（如项目/实勘人），可空。

    Returns:
        形如 `正恒评报字[2026]第7号` 的编号。

    Raises:
        RuntimeError: 新行读不到自动编号字段（表未配"自动编号"字段）。
    """
    # 多维表拒绝空 fields 的插入，故领号占位行至少带一个字段（有实勘元信息就带上）。
    record_id = client.insert_record(sheet, metadata or {"记录号": "领号占位"})
    record = client.get_record(sheet, record_id)
    seq = record.get("fields", {}).get(seq_field)
    if seq is None:
        raise RuntimeError(
            f"多维表 {sheet} 领号失败：新行无自动编号字段「{seq_field}」——"
            f"请在台账表加一个『自动编号』类型的字段并命名为 {seq_field}。"
        )
    logger.info("领报告编号：%s[%d]第%s号", prefix, year, seq)
    return f"{prefix}[{year}]第{seq}号"
