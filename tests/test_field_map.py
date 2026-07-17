"""实勘表 A1 标题 → 类别识别。"""

import pytest

from src.extractor.field_map import detect_category
from src.model import Category


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("住宅房地产实地查勘记录表", Category.RESIDENTIAL),
        ("工业房地产实地查勘记录表", Category.INDUSTRIAL),
        ("停车场房地产实地查勘记录表", Category.PARKING_LAND),
        ("建设用地房地产实地查勘记录表", Category.CONSTRUCTION_LAND),
        ("农用地房地产实地查勘记录表", Category.AGRICULTURAL),
        ("办公房地产实地查勘记录表", Category.OFFICE),
        ("商业房地产实地查勘记录表", Category.COMMERCIAL),
    ],
)
def test_detect_categories(title: str, expected: Category) -> None:
    assert detect_category(title) == expected


def test_detect_unknown_raises() -> None:
    with pytest.raises(ValueError, match="无法识别类别"):
        detect_category("某未知类别实地查勘记录表")
