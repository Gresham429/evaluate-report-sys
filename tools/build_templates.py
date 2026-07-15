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
SUBSTITUTIONS: dict[str, list[tuple[str, str]]] = {
    "农用": [
        ("正恒评报字[2026]第F093号", "{{ report_no }}"),
        ("杭州市钱塘区义蓬街道义蓬村股份经济合作社", "{{ owner }}"),
        ("杭州市钱塘区横一线和钱塘快速路交叉口西南侧", "{{ address }}"),
        ("农用地（耕地）", "{{ usage }}"),
        ("2026年4月27日", "{{ issue_date }}"),
    ],
    "办公": [
        ("正恒评报字[2026]第F071号", "{{ report_no }}"),
        ("杭州市萧山区机关事务服务中心", "{{ client }}"),
        ("杭州萧山国有资产投资有限公司", "{{ owner }}"),
        ("萧山区北干街道萧山科创中心3幢1206室和3幢1208室", "{{ address }}"),
        ("2026年6月5日", "{{ issue_date }}"),
    ],
    "商业": [
        ("正恒评报字[2026]第F098号", "{{ report_no }}"),
        ("杭州市钱塘区义蓬街道义蓬村股份经济合作社", "{{ owner }}"),
        ("钱塘区义蓬街道义蓬中路477号、487号", "{{ address }}"),
        ("2026年4月1日", "{{ issue_date }}"),
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


def _strip_embedded_pictures(xml: str) -> str:
    """删除引用内嵌图片的 <w:drawing>/<w:pict>，保留不含图片的矢量骨架元素。

    只清理包含 r:embed（即真正引用 word/media/ 图片）的块；文档里还有一处
    纯矢量装饰图形（AlternateContent + wps 形状 + VML 回退，无 r:embed），
    不依赖任何被剥离的图片，属于骨架而非项目数据，不清理。
    """
    xml = _DRAWING_RE.sub(lambda m: "" if _EMBED_RE.search(m.group(0)) else m.group(0), xml)
    xml = _PICT_RE.sub(lambda m: "" if _EMBED_RE.search(m.group(0)) else m.group(0), xml)
    return xml


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
                    for raw, placeholder in SUBSTITUTIONS[tag]:
                        xml = xml.replace(raw, placeholder)
                    xml = _strip_embedded_pictures(xml)
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
