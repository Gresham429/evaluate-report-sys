"""资产状况三张表参数化单测（见 tools/condition_tables.py）。

用「parameterize_subject_tables 已跑过、condition 循环尚未接入」的中间态
document.xml 作为输入，验证 parameterize_condition_tables 正确注入
{%tr for f in <组>因素 %}/{%tr endfor %} 行循环，且不动其余表格。

这份中间态**不能**直接读 templates/*.docx：build_templates.py 的产线现在
把 parameterize_condition_tables 也接进去了（本模块要测的正是这一接入），
成品模板里资产状况表已经是循环后的样子——组标签格的可见文本已变成
"{% if loop.first %}区位状况{% endif %}"，不再以 GROUP_PREFIXES 字面开头，
再跑一遍 parameterize_condition_tables 只会是空操作（_group_ranges 找不到
组起点）。改为直接从金样材料重放 build_templates.py 在这一步之前的预处理
链（归一化 → 项目数据替换为占位符 → 估价对象表行循环），得到一份独立于
templates/ 目录当前状态的、真正待测的输入——见 _pre_condition_xml()。
"""

import zipfile

import pytest

from tools import build_templates
from tools.condition_tables import parameterize_condition_tables

_GOLDEN_TAGS = {"office.docx": "办公", "farmland.docx": "农用"}


def _pre_condition_xml(template_name: str) -> str:
    """复刻 build_templates.build() 里 parameterize_condition_tables 之前的状态。"""
    tag = _GOLDEN_TAGS[template_name]
    golden = build_templates.GOLDENS[tag]
    if not golden.exists():
        pytest.skip(f"案例素材缺失，先准备 {golden}")
    with zipfile.ZipFile(golden) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    xml = build_templates.normalise_document_paragraphs(xml)
    xml = build_templates.substitute_document_paragraphs(xml, build_templates.SUBSTITUTIONS[tag])
    return build_templates.parameterize_subject_tables(xml)


def test_wraps_condition_rows_into_row_loop() -> None:
    xml = _pre_condition_xml("office.docx")
    out = parameterize_condition_tables(xml)
    assert "{%tr for f in 区位因素 %}" in out
    assert "{{ f.description }}" in out and "{{ f.name }}" in out
    assert out.count("{%tr endfor %}") >= 3  # 区位/实物/权益 三张表各一


def test_office_gets_all_three_group_loops() -> None:
    """办公三张资产状况表各自独立（区位/实物/权益不与其他表合并）。

    模板输入已跑过 parameterize_subject_tables（见模块 docstring），自带 3 个
    估价对象表的 `{%tr endfor %}`（"{%tr for s in subjects %}" 那三个）——
    与本函数新增的资产状况 endfor 共用同一个字面量标记（docxtpl 的 `{%tr %}`
    语法本就不区分是哪个 for 的 endfor）。故按"新增了多少个"比较，而非绝对数，
    不依赖也不掩盖 parameterize_subject_tables 那三个是否存在。
    """
    xml = _pre_condition_xml("office.docx")
    baseline = xml.count("{%tr endfor %}")
    out = parameterize_condition_tables(xml)
    assert "{%tr for f in 区位因素 %}" in out
    assert "{%tr for f in 实物因素 %}" in out
    assert "{%tr for f in 权益因素 %}" in out
    assert out.count("{%tr endfor %}") - baseline == 3


def test_office_preserves_subjects_narrative_placeholder() -> None:
    """「建筑规模」行的描述格已是 {{ subjects_narrative }}，不进循环、原样保留。"""
    xml = _pre_condition_xml("office.docx")
    out = parameterize_condition_tables(xml)
    assert "{{ subjects_narrative }}" in out
    assert "建筑规模" in out


def test_office_leaves_non_condition_tables_untouched() -> None:
    """基本情况/权证登记情况/估价结果一览表等不含 GROUP_PREFIXES 首列的表原样不动。"""
    xml = _pre_condition_xml("office.docx")
    out = parameterize_condition_tables(xml)
    for marker in ("基本情况", "权证登记情况", "不动产权证号", "{%tr for s in subjects %}"):
        assert marker in out


def test_farmland_condition_loop_survives_merged_table() -> None:
    """农用「基本情况+权益状况」合在同一张物理表里，权益状况子区间仍须被识别并循环化。

    区位状况/实物状况各自独立成表；权益状况与基本情况共享一张 <w:tbl>
    （因为农用没有「权证登记情况」表，二者物理相邻）。基本情况部分（如
    「是否取得产权证书」）必须原样保留，不得被循环覆盖。

    同 test_office_gets_all_three_group_loops：按新增数量比较 endfor，
    不管 parameterize_subject_tables 预先留下的 3 个估价对象表 endfor。
    """
    xml = _pre_condition_xml("farmland.docx")
    baseline = xml.count("{%tr endfor %}")
    out = parameterize_condition_tables(xml)
    assert "{%tr for f in 区位因素 %}" in out
    assert "{%tr for f in 实物因素 %}" in out
    assert "{%tr for f in 权益因素 %}" in out
    assert out.count("{%tr endfor %}") - baseline == 3
    assert "是否取得产权证书" in out
    assert "{{ total_area }}" in out  # 「面积大小」行已是占位符，不进循环


def test_no_nested_tr_leaks_into_marker_rows() -> None:
    """标记行只应各自独占一行（{%tr %} 的既有约束），不应嵌套出现在数据行内部之外。

    用广义的 "{%tr for"（同时匹配估价对象表的 "for s in subjects" 与资产状况表的
    "for f in <组>因素"）配对 "{%tr endfor %}"——两者理应一一配对，不管 for 的
    循环变量是什么。
    """
    xml = _pre_condition_xml("office.docx")
    out = parameterize_condition_tables(xml)
    # for 与 endfor 应成对出现，且 for 不早于对应的 endfor 之后又出现 for（粗粒度检查数量相等）
    assert out.count("{%tr for") == out.count("{%tr endfor %}")
