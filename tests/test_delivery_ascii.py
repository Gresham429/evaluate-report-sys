"""交付物的名字一律 ASCII——守住已经栽过的那类跤。

中文名进交付会两头挨打：GitHub Release 把资产名里的非 ASCII 删空；第三方解压
软件（WinRAR/360/好压/2345）把 zip 里的中文条目名按 GBK 解成乱码。后者曾让
`农用.docx` 变 `鍐滅敤.docx`、render() 一份报告也出不来（v1.0.1 实测）。

盯的是「机器要按名字找、或双击要认」的名字：exe、内层目录、三份模板。
docs/使用说明.md 有意保留中文（给人读的文档，名乱了也打得开），不在此约束内。
"""

from pathlib import Path

import build_exe
from src.renderer.render import TEMPLATE_FILENAMES

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def test_app_and_archive_names_are_ascii() -> None:
    assert build_exe.APP_NAME.isascii(), build_exe.APP_NAME
    assert build_exe.ARCHIVE_STEM.isascii(), build_exe.ARCHIVE_STEM


def test_exe_name_is_ascii() -> None:
    assert build_exe.exe_name().isascii(), build_exe.exe_name()


def test_render_template_map_is_ascii_only() -> None:
    for name in TEMPLATE_FILENAMES.values():
        assert name.isascii(), name


def test_delivered_template_files_are_ascii() -> None:
    """真正躺在 templates/ 里、会被打进交付包的文件名，逐个 ASCII。"""
    delivered = [p.name for p in TEMPLATES.glob("*.docx")]
    assert delivered, "templates/ 里没有 .docx，先跑 tools/build_templates.py"
    for name in delivered:
        assert name.isascii(), f"交付模板名含非 ASCII：{name}"
