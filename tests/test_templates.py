"""模板构建测试。"""

import zipfile
from pathlib import Path

import pytest

from src.renderer.render import TEMPLATE_FILENAMES

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
# 文件名一律取自 render 的单一映射（见 TEMPLATE_FILENAMES 的说明）：一律 ASCII，
# 交付 zip 里的中文文件名会被第三方解压软件按 GBK 解成乱码，render() 便找不到模板。
NAMES = tuple(TEMPLATE_FILENAMES.values())


def test_template_filenames_are_ascii() -> None:
    """随包发出、要被机器按名字找的模板，文件名必须是 ASCII。

    否则第三方解压软件（WinRAR/360/好压等）会把中文名按 GBK 解成乱码
    （农用.docx → 鍐滅敤.docx），render() 一份报告也出不来。
    """
    for name in NAMES:
        assert name.isascii(), f"模板文件名含非 ASCII：{name}"


@pytest.mark.parametrize("name", NAMES)
def test_template_exists(name: str) -> None:
    assert (TEMPLATES / name).exists(), "先运行 uv run python tools/build_templates.py"


@pytest.mark.parametrize("name", NAMES)
def test_template_is_valid_docx(name: str) -> None:
    with zipfile.ZipFile(TEMPLATES / name) as archive:
        assert "word/document.xml" in archive.namelist()


@pytest.mark.parametrize("name", NAMES)
def test_template_images_stripped(name: str) -> None:
    """图片是项目数据，不该留在模板里。模板应远小于金样。"""
    assert (TEMPLATES / name).stat().st_size < 2_000_000


@pytest.mark.parametrize("name", NAMES)
def test_template_has_placeholders(name: str) -> None:
    with zipfile.ZipFile(TEMPLATES / name) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "{{" in xml or "{%" in xml, "模板应含 Jinja 占位符"


def test_templates_share_styles() -> None:
    """三份模板派生自共用同一样式表的金样，样式应保持一致。"""
    digests = set()
    for name in NAMES:
        with zipfile.ZipFile(TEMPLATES / name) as archive:
            digests.add(hash(archive.read("word/styles.xml")))
    assert len(digests) == 1
