"""docx 文本抽取与差异报告，供金样回归测试使用。"""

import html
import logging
import re
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["extract_paragraphs", "diff_report"]

_MAX_DIFF_LINES = 20


def extract_paragraphs(path: Path) -> list[str]:
    """抽取 docx 的段落文本。

    Args:
        path: docx 路径。

    Returns:
        非空段落文本列表，按文档顺序。
    """
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return [line.strip() for line in text.split("\n") if line.strip()]


def diff_report(missing: list[str], actual: list[str]) -> str:
    """生成可读的缺失段落报告。

    Args:
        missing: 金样有、输出没有的段落。
        actual: 输出的全部段落，用于提示最接近的候选。

    Returns:
        多行差异说明。
    """
    lines = [f"渲染结果缺少金样的 {len(missing)} 个段落："]
    for paragraph in missing[:_MAX_DIFF_LINES]:
        lines.append(f"  - {paragraph[:100]}")
    if len(missing) > _MAX_DIFF_LINES:
        lines.append(f"  …另有 {len(missing) - _MAX_DIFF_LINES} 段")
    lines.append(f"（输出共 {len(actual)} 段）")
    return "\n".join(lines)
