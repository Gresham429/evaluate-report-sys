"""附件收集测试。附件是用户输入，可留空。"""

from pathlib import Path

from src.attachments.collector import collect
from tests.conftest import MATERIALS

OFFICE_PDFS = MATERIALS / "办公" / "附件"


def test_empty_input_returns_empty(tmp_path: Path) -> None:
    """无附件时返回空——报告的「附 件」章节将被省略。"""
    assert collect([], tmp_path) == ()


def test_pdf_expanded_to_pages(tmp_path: Path) -> None:
    """海创703.pdf 实测 7 页。"""
    pdf = OFFICE_PDFS / "海创703.pdf"
    pages = collect([pdf], tmp_path)
    assert len(pages) == 7
    assert all(p.image_path.exists() for p in pages)
    assert [p.page_index for p in pages] == list(range(7))


def test_order_follows_input(tmp_path: Path) -> None:
    """用户手动排的顺序必须被保留。"""
    a = OFFICE_PDFS / "海创808.pdf"
    b = OFFICE_PDFS / "海创703.pdf"
    pages = collect([a, b], tmp_path)
    assert pages[0].source == a
    assert pages[len(pages) - 1].source == b


def test_all_three_office_attachments(tmp_path: Path) -> None:
    files = [
        OFFICE_PDFS / "海创703.pdf",
        OFFICE_PDFS / "海创808.pdf",
        OFFICE_PDFS / "XYKC-ZLF-2024-0033房屋租赁合同——杭州鑫锐祥商贸有限公司.pdf",
    ]
    pages = collect(files, tmp_path)
    assert len(pages) > 14
    assert all(p.image_path.stat().st_size > 0 for p in pages)
