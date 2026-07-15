"""附件收集与 PDF 转图。

附件是用户输入，手动选择、手动排序，可以一个都不选。
用 PyMuPDF 而非 pdf2image：后者依赖 poppler 外部程序，违反跨平台约束 C7。
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

__all__ = ["AttachmentPage", "collect", "IMAGE_SUFFIXES"]

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff"})


@dataclass(frozen=True)
class AttachmentPage:
    """附件展开后的单页图片。"""

    source: Path
    page_index: int
    image_path: Path


def _pdf_to_images(pdf: Path, workdir: Path, dpi: int) -> list[AttachmentPage]:
    pages: list[AttachmentPage] = []
    with fitz.open(pdf) as document:
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(dpi=dpi)
            target = workdir / f"{pdf.stem}_{index:03d}.png"
            pixmap.save(target)
            pages.append(AttachmentPage(source=pdf, page_index=index, image_path=target))
    logger.debug("PDF %s → %d 页图片", pdf.name, len(pages))
    return pages


def collect(
    files: Sequence[Path], workdir: Path, dpi: int = 150
) -> tuple[AttachmentPage, ...]:
    """把用户选的附件展开成有序的图片页。

    Args:
        files: 用户手动选择并排序的文件。顺序即报告中的顺序。
        workdir: 临时图片输出目录。
        dpi: PDF 渲染精度。

    Returns:
        按输入顺序展开的图片页元组。空输入返回空元组
        （报告的「附 件」章节将被省略）。

    Raises:
        ValueError: 文件类型既非 PDF 也非支持的图片格式。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    pages: list[AttachmentPage] = []
    for path in files:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pages.extend(_pdf_to_images(path, workdir, dpi))
        elif suffix in IMAGE_SUFFIXES:
            pages.append(AttachmentPage(source=path, page_index=0, image_path=path))
        else:
            raise ValueError(f"不支持的附件类型 {suffix!r}：{path}")
    logger.info("附件展开：%d 个文件 → %d 页", len(files), len(pages))
    return tuple(pages)
