"""开发期工具：把资产状况三张表（区位/实物/权益状况）的因素行改写为行循环。

贴 `tools/table_loop.py` 的既有 `{%tr %}` 行循环范式（复用其
`_TR_RE`/`_TC_RE`/`_cell_set_text`/`_marker_row`），但多了一层
`table_loop.py` 不需要处理的复杂度：组标签列是纵向合并（vMerge：一个
restart 单元格 + 若干 continue 单元格），且合并的行数随项目实际因素个数
变化——不能像估价对象表那样简单复制一条数据行了事，因为"这一行是不是
merge 起点"这件事本身要随渲染时的循环位置（`loop.first`）变化。

三张表按行识别（而非按表识别）：首列文字以 `GROUP_PREFIXES`
（区位状况/实物状况/权益状况）开头的那一行，是该组纵向合并的 restart
行，标记着该组因素行区间的起点；区间终点是下一个组起点行或表尾。农用类
「基本情况」与「权益状况」共享一张物理表（无「权证登记情况」表，二者
相邻），「基本情况」不属于 GROUP_PREFIXES，其行区间原样保留，只把
「权益状况」的行区间改写成循环——按行而非按表识别正是为了处理这种
混合表。

vMerge 处理（不用 docxtpl 内置的 `{% vm %}` 简写）：
docxtpl 的 `{% vm %}` 会在 patch_xml() 里对整个单元格做一次"从
`</w:tcPr>` 到含 `{% vm %}` 的 `<w:t>` 为止"的正则匹配。金样「区位状况」
「权益状况」组标签格上恰好各挂着一对 Word 自动生成的 TOC 书签
（`<w:bookmarkStart w:name="_Toc...">`，因该单元格文字复用了标题样式），
若同一单元格里再插入本文件另需要的"仅循环首次保留书签"包装（见下），
会与 `{% vm %}` 的正则产生难以预判的交叉匹配。改为手写等价的 Jinja
表达式（`<w:vMerge w:val="{% if loop.first %}restart{% else %}continue
{% endif %}"/>`），语义与 `{% vm %}` 生成的完全一致，但完全在自己控制之
下、不与 docxtpl 的单元格级正则交互。

书签处理：书签起止标记不在"可见文本"之列，重复 N 次不影响金样文本比对，
但会在模板文件本身留下 N 份同名 `w:bookmarkStart`（不合法，且
`test_templates.py`/人工用 Word 打开模板文件都可能触发"发现无法读取的
内容"）。参照 `<w:t>` 里 `{{ }}` 的既有写法，把书签起止标记整体包进
`{% if loop.first %}...{% endif %}`（各自单独一对 `<w:r><w:t>` 承载）：
渲染后无论列表多长，书签都恰好出现一次，与金样的语义（书签本就只框住
一处）一致。

"建筑规模"/"面积大小" 行的描述格已被 `substitute_document_paragraphs`
（tools/build_templates.py）写成 `{{ subjects_narrative }}` 之类的占位符
——那是从 Subject 列表算出来的叙述句，不是实勘表的手写描述，不能被本
模块通用的 `{{ f.description }}` 覆盖掉。按行扫描：凡描述格已含 `{{` 的
行，记下其因素名与原始（已占位符化的）描述文本，在生成的循环数据行里
按 `f.name` 分支：命中该因素名则原样复现那句已占位符化的文本（其中的
`{{ subjects_narrative }}`/`{{ total_area }}` 等会在整份文档渲染时一并
求值），否则退回通用的 `{{ f.description }}`。全程按"扫描到什么就保留
什么"实现，不硬编码"建筑规模"这个具体因素名——农用类叫"面积大小"、
描述句式也不同（前后还夹着字面文字"出租面积为…亩。"），同一套逻辑
照样处理。
"""

import re
from xml.sax.saxutils import unescape

from src.extractor.condition import GROUP_PREFIXES
from tools.table_loop import _TBL_RE, _TC_RE, _TR_RE, _cell_set_text, _marker_row

__all__ = ["parameterize_condition_tables"]

_TAG_RE = re.compile(r"<[^>]+>")
_VMERGE_RE = re.compile(r"<w:vMerge\b[^>]*/>")
_BOOKMARK_RE = re.compile(r"<w:bookmark(?:Start|End)\b[^>]*/>")
_RUN_RE = re.compile(r"<w:r\b[^>]*>")

_GROUP_VARS: dict[str, str] = {
    "区位状况": "区位因素",
    "实物状况": "实物因素",
    "权益状况": "权益因素",
}


def _cell_text(tc_xml: str) -> str:
    """单元格可见文本（去标签、反转义、去首尾空白）。"""
    return unescape(_TAG_RE.sub("", tc_xml)).strip()


def _row_cell_texts(row_xml: str) -> list[str] | None:
    """行内三个单元格的可见文本；非 3 列返回 None（不是资产状况行）。"""
    cells = list(_TC_RE.finditer(row_xml))
    if len(cells) != 3:
        return None
    return [_cell_text(c.group(0)) for c in cells]


def _row_cells3(row_xml: str) -> list[re.Match[str]]:
    cells = list(_TC_RE.finditer(row_xml))
    if len(cells) != 3:
        raise ValueError(f"资产状况行期望 3 列，实得 {len(cells)}：{row_xml[:80]}")
    return cells


def _group_ranges(rows: list[str]) -> list[tuple[str, int, int]]:
    """按首列文字识别表格里的资产状况组行区间：[(组名, start, end), ...]。

    区间终点是下一个组起点行，或表尾——覆盖农用类"基本情况+权益状况"共享
    一张物理表、区间不从第 0 行开始的情形。
    """
    starts: list[tuple[str, int]] = []
    for i, row in enumerate(rows):
        texts = _row_cell_texts(row)
        if texts is None:
            continue
        label = texts[0]
        for prefix in GROUP_PREFIXES:
            if label.startswith(prefix):
                starts.append((prefix, i))
                break
    return [
        (prefix, start, starts[i + 1][1] if i + 1 < len(starts) else len(rows))
        for i, (prefix, start) in enumerate(starts)
    ]


def _vm_label_cell(tc_xml: str, label: str, bookmarks: str) -> str:
    """组标签列 → 手写 vMerge 循环合并：仅 `loop.first` 时 restart+显示组名+书签。

    Args:
        tc_xml: 组标签单元格原始 XML（已去除书签，见调用方）。
        label: 组名字面量（如「区位状况」）。
        bookmarks: 该单元格原有的书签起止标记（可能为空串）。
    """
    tc_xml = _VMERGE_RE.sub("", tc_xml, count=1)
    tc_xml = tc_xml.replace(
        "</w:tcPr>",
        '<w:vMerge w:val="{% if loop.first %}restart{% else %}continue{% endif %}"/></w:tcPr>',
        1,
    )
    tc_xml = _cell_set_text(tc_xml, "{% if loop.first %}" + label + "{% endif %}")
    if bookmarks:
        wrapped = "<w:r><w:t>{% if loop.first %}</w:t></w:r>" + bookmarks + "<w:r><w:t>{% endif %}</w:t></w:r>"
        run_match = _RUN_RE.search(tc_xml)
        if run_match is None:
            raise ValueError("组标签格缺少 <w:r>，无法插回书签")
        tc_xml = tc_xml[: run_match.start()] + wrapped + tc_xml[run_match.start() :]
    return tc_xml


def _description_expr(rows: list[str]) -> str:
    """描述格的渲染表达式：默认 `{{ f.description }}`，已占位符化的行按因素名原样保留。"""
    overrides: list[tuple[str, str]] = []
    for row in rows:
        texts = _row_cell_texts(row)
        if texts is None:
            continue
        _, factor_name, desc = texts
        if "{{" in desc:
            overrides.append((factor_name, desc))

    expr = "{{ f.description }}"
    for factor_name, desc_text in reversed(overrides):
        safe_name = factor_name.replace('"', '\\"')
        expr = f'{{% if f.name == "{safe_name}" %}}' + desc_text + "{% else %}" + expr + "{% endif %}"
    return expr


def _build_condition_loop_rows(rows: list[str], group_label: str, loop_var: str) -> str:
    """把一组因素行（[restart 行, continue 行...]）折叠成单条模板数据行的行循环。"""
    base = rows[0]
    cells = _row_cells3(base)

    bookmarks = "".join(_BOOKMARK_RE.findall(cells[0].group(0)))
    label_cell_no_bookmarks = _BOOKMARK_RE.sub("", cells[0].group(0))
    # marker 行会克隆 base_clean 两份（for/endfor）——即便整行内容在渲染时被
    # docxtpl 丢弃，也不该在模板文件本身留下多份重复书签，故先行去除。
    base_clean = base[: cells[0].start()] + label_cell_no_bookmarks + base[cells[0].end() :]
    cells_clean = _row_cells3(base_clean)

    desc_expr = _description_expr(rows)

    label_cell = _vm_label_cell(cells_clean[0].group(0), group_label, bookmarks)
    name_cell = _cell_set_text(cells_clean[1].group(0), "{{ f.name }}")
    desc_cell = _cell_set_text(cells_clean[2].group(0), desc_expr)

    data_row = (
        base_clean[: cells_clean[0].start()]
        + label_cell
        + base_clean[cells_clean[0].end() : cells_clean[1].start()]
        + name_cell
        + base_clean[cells_clean[1].end() : cells_clean[2].start()]
        + desc_cell
        + base_clean[cells_clean[2].end() :]
    )

    marker_for = _marker_row(base_clean, "{%tr for f in " + loop_var + " %}")
    marker_endfor = _marker_row(base_clean, "{%tr endfor %}")
    return marker_for + data_row + marker_endfor


def _parameterize_condition_table(block: str) -> str:
    """把一张（或半张，农用类"基本情况+权益状况"合表时）资产状况表改写为行循环。"""
    matches = list(_TR_RE.finditer(block))
    if not matches:
        return block
    rows = [m.group(0) for m in matches]
    ranges = _group_ranges(rows)
    if not ranges:
        return block

    out_rows: list[str] = []
    cursor = 0
    for prefix, start, end in ranges:
        out_rows.extend(rows[cursor:start])
        out_rows.append(_build_condition_loop_rows(rows[start:end], prefix, _GROUP_VARS[prefix]))
        cursor = end
    out_rows.extend(rows[cursor:])

    new_rows_xml = "".join(out_rows)
    return block[: matches[0].start()] + new_rows_xml + block[matches[-1].end() :]


def parameterize_condition_tables(xml: str) -> str:
    """把资产状况三张表（区位/实物/权益状况）的因素行改写为 docxtpl 行循环。

    按行首列文字识别（含某个 GROUP_PREFIXES 前缀），不依赖表在文档中的
    序号或整张表的表头——农用类"权益状况"与"基本情况"共享一张物理表。
    文档里其余表格（估价结果一览表、基本情况、权证登记情况等）原样保留。

    Raises:
        ValueError: 文档存在嵌套表格，或某个资产状况组的行结构与预期不符
            （列数异常等）。
    """
    if xml.count("<w:tbl>") != len(_TBL_RE.findall(xml)):
        raise ValueError("word/document.xml 存在嵌套表格，参数化逻辑未处理该情形")

    def _replace(m: re.Match[str]) -> str:
        return _parameterize_condition_table(m.group(0))

    return _TBL_RE.sub(_replace, xml)
