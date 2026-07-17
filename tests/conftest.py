"""测试夹具：定位案例素材。"""

from pathlib import Path

import pytest

MATERIALS = Path(__file__).resolve().parents[2] / "案例素材"

CASES = {
    "农用": MATERIALS / "农用" / "农用地实勘表、比较法.xlsx",
    "办公": MATERIALS / "办公" / "办公实勘表、比较法.xlsx",
    "商业": MATERIALS / "商业" / "商业实勘表、比较法.xlsx",
    "住宅": MATERIALS / "住宅" / "住宅实勘表、比较法.xlsx",
    "工业": MATERIALS / "工业" / "工业实勘表、比较法.xlsx",
    "停车场用地": MATERIALS / "停车场用地" / "停车场用地实勘表、比较法.xlsx",
    "建设用地": MATERIALS / "建设用地" / "建设用地实勘表、比较法.xlsx",
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


@pytest.fixture(autouse=True)
def _isolate_data_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """任何测试都不许写进真实 `data/`。

    默认就该是安全的，不能靠每个测试自己记得设环境变量：`/api/extract` 加了
    「顺带把基础表收进库」之后，三个没设 `基础表目录` 的 web 测试立刻开始往
    真实 `data/基础表/` 落文件——**而且测试全绿，无人会发现**。靠自觉的防线
    迟早被下一个新测试绕过；在这里兜底，绕不过去。

    测试自己 `setenv` 的会盖掉这里（后设的赢），需要指定路径时照常指定。
    """
    monkeypatch.setenv("实例库路径", str(tmp_path / "_默认实例库.json"))
    monkeypatch.setenv("草稿目录", str(tmp_path / "_默认草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "_默认基础表"))
    monkeypatch.setenv("台账目录", str(tmp_path / "_默认台账"))
