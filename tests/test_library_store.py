"""实例库存储与批量导入测试。"""

from pathlib import Path

import pytest

from src.library.importer import import_from_excel
from src.library.model import DatePrecision
from src.library.store import InstanceStore
from src.model import Category
from tests.conftest import CASES


def test_import_three_instances_per_file() -> None:
    """每份 Excel 含 3 条实例。"""
    for case in ("农用", "办公", "商业"):
        assert len(import_from_excel(CASES[case])) == 3


def test_import_all_nine() -> None:
    """三份素材共 9 条种子实例。"""
    total = sum(len(import_from_excel(CASES[c])) for c in ("农用", "办公", "商业"))
    assert total == 9


def test_imported_office_instance_fields() -> None:
    """办公实例A 的实测值。"""
    got = {i.位置: i for i in import_from_excel(CASES["办公"])}
    a = got["兴耀科创城A幢09层"]
    assert a.类别 is Category.OFFICE
    assert a.成交价 == pytest.approx(2.52)
    assert a.面积 == pytest.approx(1434.37)
    assert a.出租用途 == "办公"
    assert a.交易情况 == "正常"
    assert a.日期精度 is DatePrecision.FULL
    assert a.编号 == "办公-2026-01-兴耀科创城A幢09层"
    assert len(a.因素档次) == 28


def test_imported_agricultural_year_only_is_marked() -> None:
    """农用的两条仅有年份 '2025-2026'，须被标记为「仅年」。"""
    marked = [i for i in import_from_excel(CASES["农用"]) if i.日期精度 is DatePrecision.YEAR]
    assert len(marked) == 2
    for inst in marked:
        assert inst.租期原文 == "2025-2026"
        assert inst.编号.startswith("农用-2025-")


def test_store_roundtrip(tmp_path: Path) -> None:
    store = InstanceStore(tmp_path / "库.json")
    for case in ("农用", "办公", "商业"):
        for inst in import_from_excel(CASES[case]):
            assert store.add(inst) is True
    store.save()

    reloaded = InstanceStore(tmp_path / "库.json")
    reloaded.load()
    assert len(reloaded.list_by_category(Category.OFFICE)) == 3
    assert len(reloaded.list_by_category(Category.AGRICULTURAL)) == 3


def test_store_rejects_duplicate_id(tmp_path: Path) -> None:
    """重复编号不得静默覆盖。"""
    store = InstanceStore(tmp_path / "库.json")
    first = import_from_excel(CASES["办公"])[0]
    assert store.add(first) is True
    assert store.add(first) is False


def test_list_sorted_newest_first(tmp_path: Path) -> None:
    """按起始日从新到旧——用户明确要求，且不做任何推荐。"""
    store = InstanceStore(tmp_path / "库.json")
    for inst in import_from_excel(CASES["办公"]):
        store.add(inst)
    listed = store.list_by_category(Category.OFFICE)
    starts = [i.起始日 for i in listed]
    assert starts == sorted(starts, reverse=True)
    assert listed[0].位置 == "兴耀科创城A幢09层"  # 2026-01-15，最新


def test_json_is_human_readable(tmp_path: Path) -> None:
    """库文件须人类可读可手改——估价师要能直接查看备份。"""
    path = tmp_path / "库.json"
    store = InstanceStore(path)
    store.add(import_from_excel(CASES["办公"])[0])
    store.save()
    text = path.read_text(encoding="utf-8")
    assert "兴耀科创城A幢09层" in text, "中文不得被转义成 \\uXXXX"
    assert "\n" in text, "须缩进换行，不得压成一行"
