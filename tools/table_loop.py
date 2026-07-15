"""开发期工具：把「估价结果一览表」及两张摘要表的数据行改写为 docxtpl 行循环。

从 tools/build_templates.py 拆出（Task 12 缺陷修复），保持单文件不超过
400 行。金样里这三张表的数据行是死数据（金样自己的项目数字），从未被
参数化，只有 {{ owner }} 因为恰好落在 SUBSTITUTIONS 的全局字符串替换
范围内才变成占位符。这里改为按行循环：把首行数据行改写成 docxtpl 的
`{%tr for s in subjects %}` / `{%tr endfor %}` 行循环，行数随
render.build_context() 传入的 subjects 实际长度变化。

docxtpl 的 {%tr %} 语法（见 docxtpl/template.py patch_xml()）：只要一行
内出现 {%tr ...%}，patch_xml() 会把该行的 <w:tr>...</w:tr> 整段替换为
裸 Jinja 语句 {% ... %}——同一行内其余单元格内容一并被丢弃。因此
for/endfor 标签必须各自独占一整行（"标记行"），真正重复的数据行放在
两条标记行之间、不含 {%tr %} 标签，保持普通 {{ }} 占位符即可。

三类金样该表在文档里的表序不同，故不按索引取表，按表头内容识别：
含「序号」且含「房屋建筑面积」或「面积（亩）」的表。
"""

import re
from xml.sax.saxutils import escape, unescape

__all__ = ["parameterize_subject_tables"]

_TBL_RE = re.compile(r"<w:tbl>.*?</w:tbl>", re.DOTALL)
_TR_RE = re.compile(r"<w:tr\b[^>]*>.*?</w:tr>", re.DOTALL)
_TC_RE = re.compile(r"<w:tc\b[^>]*>.*?</w:tc>", re.DOTALL)
_WT_RE = re.compile(r"<w:t\b[^>]*>(.*?)</w:t>", re.DOTALL)
_SELF_CLOSING_P_RE = re.compile(r"<w:p\b([^>]*)/>")
_TAG_RE = re.compile(r"<[^>]+>")

_RESULT_TABLE_COLUMNS = 7  # 估价结果一览表：序号/权利人/地址/用途/面积/单价/年租赁价值
_SUMMARY_TABLE_COLUMNS = 5  # 摘要表：序号/权利人/地址/用途/面积
_RESULT_FIELDS = ("index", "owner", "address", "usage", "area", "unit_price", "annual_value")
_SUMMARY_FIELDS = ("index", "owner", "address", "usage", "area")


def _row_text(row_xml: str) -> str:
    """行内可见文本（跨单元格拼接，仅用于表头/合计行识别，不用于写回）。"""
    return unescape(_TAG_RE.sub("", row_xml))


def _is_subject_table(block: str) -> bool:
    """按表头识别：含「序号」且含房屋面积或亩制面积列。"""
    header = _TR_RE.search(block)
    if header is None:
        return False
    text = _row_text(header.group(0))
    return "序号" in text and ("房屋建筑面积" in text or "面积（亩）" in text)


def _cell_set_text(tc_xml: str, text: str) -> str:
    """把单元格可见文本整体替换为 text。

    金样单元格通常只有一个 <w:t>，直接覆盖；若该单元格原本无文字
    （如"合计"行里的空单元格，自闭合 <w:p/> 或有 <w:pPr> 无 <w:r> 的
    <w:p></w:p>），则在其段落内新建一个 run。
    """
    escaped = escape(text)
    runs = list(_WT_RE.finditer(tc_xml))
    if runs:
        pieces: list[str] = []
        pos = 0
        for i, run in enumerate(runs):
            pieces.append(tc_xml[pos : run.start(1)])
            pieces.append(escaped if i == 0 else "")
            pos = run.end(1)
        pieces.append(tc_xml[pos:])
        return "".join(pieces)
    self_closing = _SELF_CLOSING_P_RE.search(tc_xml)
    if self_closing is not None:
        replacement = f"<w:p{self_closing.group(1)}><w:r><w:t>{escaped}</w:t></w:r></w:p>"
        return tc_xml[: self_closing.start()] + replacement + tc_xml[self_closing.end() :]
    close_p = tc_xml.find("</w:p>")
    if close_p == -1:
        raise ValueError(f"单元格缺少 <w:p>，无法写入占位符：{tc_xml[:80]}")
    return tc_xml[:close_p] + f"<w:r><w:t>{escaped}</w:t></w:r>" + tc_xml[close_p:]


def _row_cells(row_xml: str) -> list[re.Match[str]]:
    return list(_TC_RE.finditer(row_xml))


def _set_cell(row_xml: str, index: int, text: str) -> str:
    """把行内第 index 个单元格（0 起）的可见文本整体替换为 text。"""
    cells = _row_cells(row_xml)
    if index >= len(cells):
        raise ValueError(f"行只有 {len(cells)} 个单元格，无法写入第 {index} 个占位符")
    match = cells[index]
    return row_xml[: match.start()] + _cell_set_text(match.group(0), text) + row_xml[match.end() :]


def _marker_row(data_row: str, tag: str) -> str:
    """克隆数据行造一条"标记行"：整行会在渲染时被裸 Jinja 语句取代。

    直接克隆真实数据行而非手写最小 XML，保证标记行本身在模板文件里
    仍是合法的 <w:tr>（tcPr/边框等结构完整）——它的可见内容无关紧要，
    docxtpl patch_xml() 会把整行连同占位符一起替换为 {% ... %}。
    """
    return _set_cell(data_row, 0, tag)


def _build_loop_rows(header: str, data_template: str, total: str | None, columns: int) -> str:
    """拼出参数化后的行序列：表头 + for 标记行 + 数据行 + endfor 标记行 [+ 合计行]。"""
    fields = _RESULT_FIELDS if columns == _RESULT_TABLE_COLUMNS else _SUMMARY_FIELDS
    data_row = data_template
    for i, field in enumerate(fields):
        data_row = _set_cell(data_row, i, "{{ s.%s }}" % field)
    rows = [
        header,
        _marker_row(data_template, "{%tr for s in subjects %}"),
        data_row,
        _marker_row(data_template, "{%tr endfor %}"),
    ]
    if total is not None:
        total_row = _set_cell(total, 4, "{{ total_area }}")
        total_row = _set_cell(total_row, 6, "{{ total_value }}")
        rows.append(total_row)
    return "".join(rows)


def _parameterize_subject_table(block: str) -> str:
    """把一张估价对象表（一览表或摘要表）的数据行改写为 docxtpl 行循环。

    Raises:
        ValueError: 表结构与预期不符（列数异常、缺合计行、无数据行等）。
    """
    matches = list(_TR_RE.finditer(block))
    if not matches:
        raise ValueError("表格内未找到 <w:tr>")
    rows = [m.group(0) for m in matches]
    header = rows[0]
    col_count = len(_row_cells(header))
    total: str | None
    if col_count == _RESULT_TABLE_COLUMNS:
        total = rows[-1]
        if "合计" not in _row_text(total):
            raise ValueError("7 列估价结果一览表末行不是「合计」行，表结构与预期不符")
        data_rows = rows[1:-1]
    elif col_count == _SUMMARY_TABLE_COLUMNS:
        total = None
        data_rows = rows[1:]
    else:
        raise ValueError(f"未预期的估价对象表列数：{col_count}")
    if not data_rows:
        raise ValueError("表格没有可用作循环模板的数据行")
    new_rows_xml = _build_loop_rows(header, data_rows[0], total, col_count)
    return block[: matches[0].start()] + new_rows_xml + block[matches[-1].end() :]


def parameterize_subject_tables(xml: str) -> str:
    """把「估价结果一览表」及两张摘要表的数据行改写为 docxtpl 行循环。

    按表头内容识别（含「序号」且含面积列），不依赖表在文档中的序号——
    三类金样该表的表序并不总是相同。文档里其余表格（签字表、实勘信息
    表等）原样保留。

    Raises:
        ValueError: 文档存在嵌套表格，或某张目标表结构与预期不符。
    """
    if xml.count("<w:tbl>") != len(_TBL_RE.findall(xml)):
        raise ValueError("word/document.xml 存在嵌套表格，参数化逻辑未处理该情形")

    def _replace(m: re.Match[str]) -> str:
        block = m.group(0)
        return _parameterize_subject_table(block) if _is_subject_table(block) else block

    return _TBL_RE.sub(_replace, xml)
