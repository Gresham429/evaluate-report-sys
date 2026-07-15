"""测试夹具：定位案例素材。"""

from pathlib import Path

import pytest

MATERIALS = Path(__file__).resolve().parents[2] / "案例素材"

CASES = {
    "农用": MATERIALS / "农用" / "农用地实勘表、比较法.xlsx",
    "办公": MATERIALS / "办公" / "办公实勘表、比较法.xlsx",
    "商业": MATERIALS / "商业" / "商业实勘表、比较法.xlsx",
}

GOLDENS = {
    "农用": MATERIALS / "农用" / "正恒评报字[2026]第F093号.docx",
    "办公": MATERIALS / "办公" / "正恒评报字[2026]第F071号.docx",
    "商业": MATERIALS / "商业" / "正恒评报字[2026]第F098号.docx",
}


@pytest.fixture(scope="session", autouse=True)
def _require_materials() -> None:
    missing = [str(p) for p in (*CASES.values(), *GOLDENS.values()) if not p.exists()]
    if missing:
        pytest.skip(f"案例素材缺失：{missing}")
