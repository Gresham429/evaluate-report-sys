"""模板构建测试。"""

import zipfile
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
NAMES = ("农用", "办公", "商业")


@pytest.mark.parametrize("name", NAMES)
def test_template_exists(name: str) -> None:
    assert (TEMPLATES / f"{name}.docx").exists(), "先运行 uv run python tools/build_templates.py"


@pytest.mark.parametrize("name", NAMES)
def test_template_is_valid_docx(name: str) -> None:
    with zipfile.ZipFile(TEMPLATES / f"{name}.docx") as archive:
        assert "word/document.xml" in archive.namelist()


@pytest.mark.parametrize("name", NAMES)
def test_template_images_stripped(name: str) -> None:
    """图片是项目数据，不该留在模板里。模板应远小于金样。"""
    assert (TEMPLATES / f"{name}.docx").stat().st_size < 2_000_000


@pytest.mark.parametrize("name", NAMES)
def test_template_has_placeholders(name: str) -> None:
    with zipfile.ZipFile(TEMPLATES / f"{name}.docx") as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "{{" in xml or "{%" in xml, "模板应含 Jinja 占位符"


def test_templates_share_styles() -> None:
    """三份模板派生自共用同一样式表的金样，样式应保持一致。"""
    digests = set()
    for name in NAMES:
        with zipfile.ZipFile(TEMPLATES / f"{name}.docx") as archive:
            digests.add(hash(archive.read("word/styles.xml")))
    assert len(digests) == 1
