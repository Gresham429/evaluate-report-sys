"""开发期工具：从三份金样构建三份模板。

模板 = 金样的骨架（样式、表格布局、页面设置）
     + 归一化的样板文字
     - 项目数据（替换为 Jinja 占位符）
     - 嵌入图片（项目数据，运行时注入）

用法：
    uv run python tools/build_templates.py

实现说明（相对 brief 骨架代码的调整，理由见 task-11-report.md）：

1. **图片剥离范围**：只剥离 word/document.xml 引用的图片（区位图/实勘照片/
   权证扫描件，真正的项目数据），保留页眉引用的图片（如司徽 logo）。三份
   金样的司徽字节级相同（md5 一致），是模板骨架的一部分，不是项目数据；
   若一并剥离，会在 word/_rels/header1.xml.rels 里留下悬空引用，Word 打开
   报「文件已损坏」——brief 原脚本未处理这一处。

2. **归一化的应用方式**：brief 原脚本对整份 word/document.xml 原始 XML 字符串
   调用 normalise()。但 document.xml 是单行 XML（无真实换行），drift.py 的
   「序号点号」规则依赖 ^ 锚点匹配"段落起始"，在单行 XML 上只能匹配到文件
   开头（偏移 0），15/25 权重的规则实际从未生效；另有「方法别名」两条规则的
   目标短语在金样里跨 <w:r> 断开（WPS 因格式提示把同一可见短语拆进多个
   run），整串匹配落空。改为按 <w:p> 段落边界拼接可见文本、整体调用
   normalise() 后写回——这与 tools/extract_copy.py（Task 7）抽取样板文字时
   的做法一致，是 normalise() 本来的设计契约（对比 tests/test_drift.py 里
   normalise() 的单测输入都是完整段落字符串，从位置 0 开始）。

3. **定点迭代**：金样商业卷发现"缺书名号"与"缺复印件"两条规则的固定顺序
   单遍扫描不收敛（前者补上《》后，恰好满足后者的匹配条件，但后者已经跑
   过）。normalise() 自身文档承诺幂等，这里在调用方反复调用至收敛，不改
   drift.py 的规则本身。

4. **矢量骨架不动**：document.xml 里有一处纯矢量装饰图形（无 r:embed，
   AlternateContent + wps 形状 + VML 回退），三份金样均有、无实际内嵌图片
   依赖。只清理含 r:embed 的 <w:drawing>/<w:pict>（真正引用图片的），不
   动这处矢量骨架。
"""

import logging
import re
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.sax.saxutils import escape, unescape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.prose.drift import normalise  # noqa: E402
from tools.table_loop import parameterize_subject_tables  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
MATERIALS = ROOT.parent / "案例素材"
TEMPLATES = ROOT / "templates"

GOLDENS = {
    "农用": MATERIALS / "农用" / "正恒评报字[2026]第F093号.docx",
    "办公": MATERIALS / "办公" / "正恒评报字[2026]第F071号.docx",
    "商业": MATERIALS / "商业" / "正恒评报字[2026]第F098号.docx",
}

# 项目数据 → Jinja 占位符。按各金样的实测值替换，均已核对在 document.xml
# 中以连续子串出现（不跨 run 断开）。长串优先，避免短串先匹配导致长串被截断。
#
# 「正文叙述句」补丁（fix2，见 task-12-fix2-report.md）：以下每类新增的条目
# 都只替换与 render.build_context() 已生成占位符完全对应、逐字核对过在该
# 类金样中恰好只出现于目标句子的连续子串——不做任何按类别措辞结构不同、
# 需要新造句式的替换（那类改动仍是已知的、未经确认的范围外缺陷，保留
# 现状，不在本次臆造新条件文案，理由逐条见下）：
#   - 「估价范围」/「依据不足假设」两段共用的 scale 面积描述：农用、办公
#     两类金样该段原文与 Project.scale 逐字相同，可直接替换；商业金样此处
#     措辞是"委托人确认房屋建筑面积为130平方米（其中…）"，与 scale 字段
#     原文不同（scale 字段另有"…及其分摊的土地使用权"结尾），替换会篡改
#     句子结构，故商业类不加这条，维持现状。
#   - 「设定出租用途为{usage}」：农用类的 usage 早已落在原有 "农用地（耕地）"
#     整串替换范围内，无需新增；办公类新增本条；商业类原句是"用途为商业"
#     （无"设定出租"前缀），另立一条精确匹配。
#   - subjects_narrative：只有办公金样的「建筑规模」单元格是"逐对象枚举+
#     共计"这一种句式，农用（"出租面积为50.00亩。"）与商业（"出租面积为
#     130平方米。其中…"）都是另外的句式，需要新造条件文案，不在本次范围。
#   - 年租赁价值金额+大写、价值时点日期：三类金样句式一致，逐类替换。
SUBSTITUTIONS: dict[str, list[tuple[str, str]]] = {
    "农用": [
        ("正恒评报字[2026]第F093号", "{{ report_no }}"),
        ("杭州市钱塘区义蓬街道义蓬村股份经济合作社", "{{ owner }}"),
        ("杭州市钱塘区横一线和钱塘快速路交叉口西南侧", "{{ address }}"),
        ("农用地（耕地）", "{{ usage }}"),
        ("2026年4月27日", "{{ issue_date }}"),
        ("土地使用权面积50.00亩", "{{ scale }}"),
        (
            "年租赁价值为70000元，大写：人民币柒万元整",
            "年租赁价值为{{ total_value }}元，大写：人民币{{ total_value_capital }}",
        ),
        ("2026年4月20日在满足所有估价假设和限制条件下", "{{ value_date_cn }}在满足所有估价假设和限制条件下"),
    ],
    "办公": [
        ("正恒评报字[2026]第F071号", "{{ report_no }}"),
        ("杭州市萧山区机关事务服务中心", "{{ client }}"),
        ("杭州萧山国有资产投资有限公司", "{{ owner }}"),
        ("萧山区北干街道萧山科创中心3幢1206室和3幢1208室", "{{ address }}"),
        ("2026年6月5日", "{{ issue_date }}"),
        ("房屋建筑面积723.69平方米及其分摊的土地使用权", "{{ scale }}"),
        ("设定出租用途为办公", "设定出租用途为{{ usage }}"),
        (
            "萧山区北干街道萧山科创中心3幢1208室房屋建筑面积356.29平方米，"
            "3幢1206室房屋建筑面积367.4平方米，共计房屋建筑面积723.69平方米",
            "{{ subjects_narrative }}",
        ),
        (
            "年租赁价值为747536元，大写：人民币柒拾肆万柒仟伍佰叁拾陆元整",
            "年租赁价值为{{ total_value }}元，大写：人民币{{ total_value_capital }}",
        ),
        ("2026年3月26日在满足所有估价假设和限制条件下", "{{ value_date_cn }}在满足所有估价假设和限制条件下"),
    ],
    "商业": [
        ("正恒评报字[2026]第F098号", "{{ report_no }}"),
        ("杭州市钱塘区义蓬街道义蓬村股份经济合作社", "{{ owner }}"),
        ("钱塘区义蓬街道义蓬中路477号、487号", "{{ address }}"),
        ("2026年4月1日", "{{ issue_date }}"),
        ("用途为商业", "用途为{{ usage }}"),
        (
            "年租赁价值为157534元，大写：人民币壹拾伍万柒仟伍佰叁拾肆元整",
            "年租赁价值为{{ total_value }}元，大写：人民币{{ total_value_capital }}",
        ),
        ("2026年3月25日在满足所有估价假设和限制条件下", "{{ value_date_cn }}在满足所有估价假设和限制条件下"),
    ],
}

# --- 段落边界扫描：正确处理文本框(w:txbxContent)里嵌套的 <w:p> ---
_OPEN_P_RE = re.compile(r"<w:p\b[^>]*(?<!/)>")  # 排除自闭合的空段落 <w:p .../>
_CLOSE_P = "</w:p>"
_TXBX_RE = re.compile(r"<w:txbxContent\b[^>]*>.*?</w:txbxContent>", re.DOTALL)
_WT_RE = re.compile(r"<w:t\b[^>]*>(.*?)</w:t>", re.DOTALL)
_DRAWING_RE = re.compile(r"<w:drawing>.*?</w:drawing>", re.DOTALL)
_PICT_RE = re.compile(r"<w:pict>.*?</w:pict>", re.DOTALL)
_EMBED_RE = re.compile(r'r:embed="[^"]+"')
_MEDIA_REL_RE = re.compile(r"<Relationship[^>]*media/[^>]*/>")
_REL_TARGET_RE = re.compile(r'Target="(media/[^"]+)"')

_MAX_NORMALISE_ROUNDS = 5


def _normalise_fixed_point(text: str) -> str:
    """反复调用 normalise() 至收敛，不改 drift.py 的规则本身。

    normalise() 的文档承诺幂等，但规则按固定顺序单遍扫描——若某规则的输出
    恰好触发排在它前面的另一条规则（如「缺书名号」补上《》后，「缺复印件」
    本该追加"复印件"却已跑过），单遍调用不收敛。金样商业卷实测出现该场景。
    """
    for _ in range(_MAX_NORMALISE_ROUNDS):
        new_text = normalise(text)
        if new_text == text:
            return text
        text = new_text
    logger.warning("normalise 未在 %d 轮内收敛：%.60s...", _MAX_NORMALISE_ROUNDS, text)
    return text


def _iter_paragraph_spans(xml: str) -> Iterator[tuple[int, int]]:
    """深度正确地定位顶层 <w:p>...</w:p>，跳过文本框内嵌套的 <w:p>。

    <w:p> 一般不嵌套，但文本框(<w:txbxContent>)内可以有自己的段落，
    简单的非贪婪正则会在遇到文本框内部的 </w:p> 时提前收尾，截断外层
    段落。这里用开合计数正确处理任意嵌套深度。
    """
    pos = 0
    while True:
        match = _OPEN_P_RE.search(xml, pos)
        if match is None:
            return
        start = match.start()
        depth = 1
        cursor = match.end()
        while depth > 0:
            next_open = _OPEN_P_RE.search(xml, cursor)
            next_close = xml.find(_CLOSE_P, cursor)
            if next_close == -1:
                raise ValueError("word/document.xml 中 <w:p> 标签不闭合")
            if next_open is not None and next_open.start() < next_close:
                depth += 1
                cursor = next_open.end()
            else:
                depth -= 1
                cursor = next_close + len(_CLOSE_P)
        yield start, cursor
        pos = cursor


def _normalise_one_paragraph(para: str) -> str:
    """拼接段落内可见文本、整体归一化，再写回第一个 <w:t>。

    WPS 常因格式提示（字体、语言标记等差异）把同一可见短语拆进多个
    <w:r><w:t>。drift.py 的规则按"段落纯文本"设计，须先按段落拼接文本
    再整体匹配。归一化后的整段文字写回第一个 <w:t>，其余 <w:t> 清空——
    这些漂移点涉及的格式差异仅是次要属性（如 w:lang），不影响可见样式。
    文本框(w:txbxContent)内容视为不属于本段可见文字流，原样保留。
    """
    masked = _TXBX_RE.sub(lambda m: "\x00" * len(m.group(0)), para)
    runs = list(_WT_RE.finditer(masked))
    if not runs:
        return para
    original = "".join(unescape(r.group(1)) for r in runs)
    normalised = _normalise_fixed_point(original)
    if normalised == original:
        return para
    pieces: list[str] = []
    pos = 0
    for i, run in enumerate(runs):
        pieces.append(para[pos : run.start(1)])
        pieces.append(escape(normalised) if i == 0 else "")
        pos = run.end(1)
    pieces.append(para[pos:])
    return "".join(pieces)


def normalise_document_paragraphs(xml: str) -> str:
    """按段落归一化 word/document.xml 的全部样板文字。"""
    out: list[str] = []
    cursor = 0
    for start, end in _iter_paragraph_spans(xml):
        out.append(xml[cursor:start])
        out.append(_normalise_one_paragraph(xml[start:end]))
        cursor = end
    out.append(xml[cursor:])
    return "".join(out)


def _substitute_one_paragraph(para: str, subs: list[tuple[str, str]]) -> str:
    """拼接段落内可见文本、整体做字面替换，再写回第一个 <w:t>。

    SUBSTITUTIONS 原先直接对整份 document.xml 字符串做 str.replace()，
    这对"目标短语在金样里跨 <w:r> 断开"的情形会静默失效——例如封面标题
    的项目地址，WPS 在两个 run 之间插入了一对空的
    <w:bookmarkStart>/<w:bookmarkEnd>（自动生成的 OLE_LINK 书签），
    "萧山区北干街道萧山科创中心3幢1206室和3幢1208室"因此不是连续子串，
    全文件替换找不到它，该处便原样留下金样的项目数据。

    与 normalise_document_paragraphs()/_normalise_one_paragraph() 同一思路：
    按段落拼接可见文本、整体做替换，再写回首个 <w:t>，其余 <w:t> 清空。
    """
    masked = _TXBX_RE.sub(lambda m: "\x00" * len(m.group(0)), para)
    runs = list(_WT_RE.finditer(masked))
    if not runs:
        return para
    original = "".join(unescape(r.group(1)) for r in runs)
    replaced = original
    for raw, placeholder in subs:
        replaced = replaced.replace(raw, placeholder)
    if replaced == original:
        return para
    pieces: list[str] = []
    pos = 0
    for i, run in enumerate(runs):
        pieces.append(para[pos : run.start(1)])
        pieces.append(escape(replaced) if i == 0 else "")
        pos = run.end(1)
    pieces.append(para[pos:])
    return "".join(pieces)


def substitute_document_paragraphs(xml: str, subs: list[tuple[str, str]]) -> str:
    """按段落把 SUBSTITUTIONS 里的项目数据替换为 Jinja 占位符。

    不用整份文件一次性 str.replace()：目标短语若被 WPS 的空标签（书签等）
    跨 run 打断，全文件替换会对那一处静默失效，金样数据就在那处原样
    留下（决定性证据见 tests/test_render.py 的
    test_template_has_no_hardcoded_golden_data）。按段落重建可见文本再
    整体替换可以处理这种情形。
    """
    out: list[str] = []
    cursor = 0
    for start, end in _iter_paragraph_spans(xml):
        out.append(xml[cursor:start])
        out.append(_substitute_one_paragraph(xml[start:end], subs))
        cursor = end
    out.append(xml[cursor:])
    return "".join(out)


def _strip_embedded_pictures(xml: str) -> str:
    """删除引用内嵌图片的 <w:drawing>/<w:pict>，保留不含图片的矢量骨架元素。

    只清理包含 r:embed（即真正引用 word/media/ 图片）的块；文档里还有一处
    纯矢量装饰图形（AlternateContent + wps 形状 + VML 回退，无 r:embed），
    不依赖任何被剥离的图片，属于骨架而非项目数据，不清理。
    """
    xml = _DRAWING_RE.sub(lambda m: "" if _EMBED_RE.search(m.group(0)) else m.group(0), xml)
    xml = _PICT_RE.sub(lambda m: "" if _EMBED_RE.search(m.group(0)) else m.group(0), xml)
    return xml


# 金样里「附 件」章节末尾的扫描件页面（委托协议、权证复印件等）已随
# _strip_embedded_pictures 一并清空为空段落——那些页数是当次案例的具体
# 数量，不是模板该有的骨架。改为在章节末尾追加一段 Jinja 循环，运行时
# 按 render.render() 传入的 attachment_images（Task 12 render.py 组装，
# 来自 collect() 展开的用户附件）逐页插入，页数随输入变化。
# 空 has_attachments 时 {% if %} 整段（含分页符）不产出任何内容，附件
# 一个都不选也能正常出报告（约束见 task-12-brief.md「附件可留空」）。
_ATTACHMENT_LOOP_PARAGRAPH = (
    "<w:p><w:pPr><w:jc w:val=\"center\"/></w:pPr>"
    "<w:r><w:t>{% if has_attachments %}</w:t></w:r>"
    "<w:r><w:br w:type=\"page\"/><w:t>{% for img in attachment_images %}</w:t></w:r>"
    "<w:r><w:t>{{ img }}</w:t></w:r>"
    "<w:r><w:t>{% endfor %}</w:t></w:r>"
    "<w:r><w:t>{% endif %}</w:t></w:r>"
    "</w:p>"
)


def _inject_attachment_loop(xml: str) -> str:
    """在正文最后一个 <w:sectPr>（body 级别的收尾节属性）前插入附件循环段落。

    Raises:
        ValueError: 找不到 body 级别的 <w:sectPr>（document.xml 结构异常）。
    """
    index = xml.rfind("<w:sectPr")
    if index == -1:
        raise ValueError("word/document.xml 缺少 <w:sectPr>，模板结构异常")
    return xml[:index] + _ATTACHMENT_LOOP_PARAGRAPH + xml[index:]


def _media_kept_by_header_footer(source: zipfile.ZipFile, names: list[str]) -> set[str]:
    """word/media 下被 document.xml 以外部件（页眉/页脚等）引用的文件。

    这些是模板骨架的一部分（如三份金样字节级相同的司徽 logo），不是项目
    数据，剥离会在其 .rels 里留下悬空引用导致 Word 报"文件已损坏"。
    """
    keep: set[str] = set()
    for name in names:
        if not name.startswith("word/_rels/") or name == "word/_rels/document.xml.rels":
            continue
        rels_xml = source.read(name).decode("utf-8")
        for target in _REL_TARGET_RE.findall(rels_xml):
            keep.add(f"word/{target}")
    return keep


def _strip_media_names(names: list[str], keep: set[str]) -> list[str]:
    """图片是项目数据，不进模板；骨架部件（页眉等）引用的图片例外保留。"""
    return [n for n in names if not (n.startswith("word/media/") and n not in keep)]


def build(tag: str, golden: Path, target: Path) -> None:
    """由金样构建模板。"""
    with zipfile.ZipFile(golden) as source:
        names = source.namelist()
        keep_media = _media_kept_by_header_footer(source, names)
        keep_names = _strip_media_names(names, keep_media)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            for name in keep_names:
                data = source.read(name)
                if name == "word/document.xml":
                    xml = data.decode("utf-8")
                    xml = normalise_document_paragraphs(xml)
                    xml = substitute_document_paragraphs(xml, SUBSTITUTIONS[tag])
                    xml = parameterize_subject_tables(xml)
                    xml = _strip_embedded_pictures(xml)
                    xml = _inject_attachment_loop(xml)
                    data = xml.encode("utf-8")
                elif name == "word/_rels/document.xml.rels":
                    rels = data.decode("utf-8")
                    rels = _MEDIA_REL_RE.sub("", rels)
                    data = rels.encode("utf-8")
                out.writestr(name, data)
    size_mb = target.stat().st_size / 1e6
    logger.info("%s：%.1fMB → %s (%.2fMB)", golden.name, golden.stat().st_size / 1e6, target.name, size_mb)


def main() -> int:
    missing = [str(p) for p in GOLDENS.values() if not p.exists()]
    if missing:
        logger.error("金样缺失：%s", missing)
        return 1
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    for tag, golden in GOLDENS.items():
        build(tag, golden, TEMPLATES / f"{tag}.docx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
