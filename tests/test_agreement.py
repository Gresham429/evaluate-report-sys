"""委托评估协议书渲染测试。"""

from pathlib import Path

import docx
import pytest

from src.model import Category
from src.renderer.agreement import build_agreement_context, render_agreement
from tests.test_render_new_categories import _proj


def test_agreement_context_fee_and_capital() -> None:
    ctx = build_agreement_context(_proj(Category.RESIDENTIAL), 2616)
    assert ctx["client"] == "某某委托人"
    assert ctx["fee_total"] == "2,616"
    assert ctx["fee_capital"] == "贰仟陆佰壹拾陆元整"


@pytest.mark.parametrize(
    "category",
    [Category.RESIDENTIAL, Category.PARKING_LAND],
)
def test_agreement_renders(category: Category, tmp_path: Path) -> None:
    out = render_agreement(_proj(category), 2616, tmp_path / "a.docx")
    assert out.exists()
    text = "\n".join(p.text for p in docx.Document(out).paragraphs)
    assert "某某委托人" in text
    assert "贰仟陆佰壹拾陆元整" in text
    assert "{{" not in text and "{%" not in text
    assert "机关事务服务中心" not in text  # 源模板样例值不得泄漏


def test_agreement_rejects_negative_fee(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不能为负"):
        render_agreement(_proj(Category.INDUSTRIAL), -1, tmp_path / "a.docx")
