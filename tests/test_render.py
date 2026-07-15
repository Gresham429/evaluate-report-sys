"""渲染器测试。"""

import zipfile
from pathlib import Path

import pytest

from src.attachments.collector import collect
from src.extractor.project import load_project
from src.renderer.render import build_context, render
from tests.conftest import CASES, MATERIALS


def test_context_has_subjects() -> None:
    project = load_project(CASES["办公"])
    context = build_context(project, [])
    assert len(context["subjects"]) == 2
    assert context["report_no"] == "正恒评报字[2026]第F071号"
    assert context["面积单位"] == "㎡"


def test_context_agricultural_units() -> None:
    context = build_context(load_project(CASES["农用"]), [])
    assert context["面积单位"] == "亩"
    assert context["单价单位"] == "元/亩·年"


def test_context_has_attachments_flag() -> None:
    assert build_context(load_project(CASES["办公"]), [])["has_attachments"] is False


@pytest.mark.parametrize("case", ["农用", "办公", "商业"])
def test_render_produces_valid_docx(case: str, tmp_path: Path) -> None:
    project = load_project(CASES[case])
    output = tmp_path / f"{case}.docx"
    render(project, [], output)
    assert output.exists()
    with zipfile.ZipFile(output) as archive:
        assert "word/document.xml" in archive.namelist()


def test_render_is_deterministic(tmp_path: Path) -> None:
    """同一输入渲染两次，正文必须逐字节相同（约束 C2）。"""
    project = load_project(CASES["商业"])
    first, second = tmp_path / "a.docx", tmp_path / "b.docx"
    render(project, [], first)
    render(project, [], second)
    with zipfile.ZipFile(first) as fa, zipfile.ZipFile(second) as fb:
        assert fa.read("word/document.xml") == fb.read("word/document.xml")


def test_render_with_attachments(tmp_path: Path) -> None:
    project = load_project(CASES["办公"])
    pages = collect([MATERIALS / "办公" / "附件" / "海创703.pdf"], tmp_path / "img")
    output = tmp_path / "with.docx"
    render(project, pages, output)
    with zipfile.ZipFile(output) as archive:
        media = [n for n in archive.namelist() if n.startswith("word/media/")]
    assert len(media) >= 7
