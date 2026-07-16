"""台账存储。

**只增不改**是这个模块的全部理由——能被改写的记录不构成依据。故本类刻意没有
remove()、save()、update()，测试也盯着这一点。
"""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from src.engine.inputs import from_excel
from src.engine.methods.base import Instance, Result
from src.knowledge_base.fingerprint import fingerprint
from src.ledger.model import BaseTableUse, InstanceUse, LedgerEntry, MethodUse, to_dict
from src.ledger.store import LedgerStore
from src.model import Category
from tests.conftest import CASES


def _entry(报告编号: str = "正恒评报字[2026]第F071号", when: datetime | None = None) -> LedgerEntry:
    knowledge = from_excel(CASES["办公"]).knowledge
    digest = fingerprint(knowledge)
    return LedgerEntry.new(
        报告编号=报告编号,
        类别=Category.OFFICE,
        基础表=BaseTableUse(基线版本=digest, 偏离=(), 实际知识=knowledge, 实际指纹=digest),
        估价对象档次={"临街状况": "四面临街"},
        实例=(
            InstanceUse(
                实例=Instance(位置="某处", 成交价=2.52, 交易情况指数=100.0,
                             市场状况指数=98.0, 因素档次={"临街状况": "四面临街"}),
                编号="办公-2026-01-某处",
            ),
        ),
        方法=MethodUse(名称="市场比较法-2026", 版本="2026-07"),
        权重=(1 / 3, 1 / 3, 1 / 3),
        结果=Result(比准价格=(2.92, 2.77, 2.80), 评估结果=2.83, 离散度=0.05),
        一览表=({"index": 1, "area": 356.29},),
        now=when or datetime(2026, 7, 16, 11, 30, 0),
        经手人="张三@ZH-PC-03",
    )


def test_append_then_get_round_trips(tmp_path: Path) -> None:
    """存进去取回来必须是同一条——含整份基础表知识。"""
    store = LedgerStore(tmp_path)
    entry = _entry()
    记录号 = store.append(entry)
    got = store.get(记录号)
    assert got == entry, "落盘往返丢了东西"
    assert got is not None
    assert got.基础表 is not None
    assert len(got.基础表.实际知识.factors) == 28


def test_same_report_generated_five_times_keeps_five(tmp_path: Path) -> None:
    """**本文件第一等的测试。**

    同一报告编号生成五次就是五条，一条不少。台账会有废条——这是台账该有的样子，
    不是缺陷。「最后那条」即交出去的那份，但中间改过什么全留着。
    """
    store = LedgerStore(tmp_path)
    for i in range(5):
        store.append(_entry(when=datetime(2026, 7, 16, 11, 30, i)))
    entries = store.list_all()
    assert len(entries) == 5
    assert len({e.记录号 for e in entries}) == 5
    assert all(e.报告编号 == "正恒评报字[2026]第F071号" for e in entries)


def test_store_has_no_way_to_delete_or_edit() -> None:
    """只增不改——不是靠自觉，是根本没有那个方法。"""
    assert not hasattr(LedgerStore, "remove")
    assert not hasattr(LedgerStore, "save")
    assert not hasattr(LedgerStore, "update")


def test_list_is_newest_first(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path)
    store.append(_entry(报告编号="早", when=datetime(2026, 7, 16, 9, 0, 0)))
    store.append(_entry(报告编号="晚", when=datetime(2026, 7, 16, 18, 0, 0)))
    assert [e.报告编号 for e in store.list_all()] == ["晚", "早"]


def test_empty_when_nothing_recorded(tmp_path: Path) -> None:
    """首次运行目录还不存在，不该炸。"""
    assert LedgerStore(tmp_path / "还没有").list_all() == ()


def test_get_unknown_is_none(tmp_path: Path) -> None:
    assert LedgerStore(tmp_path).get("没这条") is None


def test_report_no_with_brackets_is_safe(tmp_path: Path) -> None:
    """报告编号含 []，落文件名时不能炸，也不能被 glob 当成元字符吞掉。"""
    store = LedgerStore(tmp_path)
    记录号 = store.append(_entry(报告编号="正恒评报字[2026]第F071号"))
    assert store.get(记录号) is not None
    assert len(store.list_all()) == 1


def test_one_broken_file_does_not_sink_the_rest(tmp_path: Path) -> None:
    """台账文件明说可以手改，改坏就得容错——一份坏文件不该让整个台账打不开。"""
    store = LedgerStore(tmp_path)
    store.append(_entry())
    (tmp_path / "坏掉的.json").write_text("{ 这不是 json", encoding="utf-8")
    assert len(store.list_all()) == 1


def test_file_is_human_readable(tmp_path: Path) -> None:
    """须人类可读可手改可备份。"""
    store = LedgerStore(tmp_path)
    store.append(_entry())
    text = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "正恒评报字" in text, "中文被转义了"
    assert "\n  " in text, "没有缩进"


def test_append_rejects_unsafe_record_id(tmp_path: Path) -> None:
    """记录号形状不安全就必须拒绝，不能被直接拼进文件名。

    今天 `记录号` 只由 `new_record_id()` 产出，天然安全——但那只是调用约定，
    不是保证：`LedgerEntry` 是普通 frozen dataclass，直接构造就能绕开
    `new()`（`test_ledger_model.py` 里已有这么干的先例）。这里就用同样的
    绕法，造一条记录号不干净的记录，钉死 `append()` 会拒绝它。
    """
    store = LedgerStore(tmp_path)
    for 坏记录号 in ("../evil", "a/b", "a\\b", "..", ".", "", "带\0空字节"):
        坏条目 = replace(_entry(), 记录号=坏记录号)
        with pytest.raises(ValueError):
            store.append(坏条目)
    # 校验必须在落盘动作之前拦住，不能先写了坏文件再报错。
    assert list(tmp_path.glob("*")) == [], "校验没拦住，留下了垃圾文件"


def test_get_rejects_path_traversal_record_id(tmp_path: Path) -> None:
    """`get()` 刻意不拿记录号拼路径；记录号从网页 URL 原样传入，不能被拼成
    穿越到台账目录之外——这条测试钉死这一点，见 `store.get()` docstring。

    台账目录之外放一份内容合法、能被 `from_dict` 解析的「诱饵」文件：如果
    `get()` 哪天被改成直接拼路径读文件，这份诱饵就会被读到、返回给调用方，
    而不是抛异常——那样的话下面 `is None` 的断言才会给出清楚的失败信息，
    而不是被无关的 `FileNotFoundError` 掩盖。
    """
    store_dir = tmp_path / "台账"
    store = LedgerStore(store_dir)
    store.append(_entry())

    诱饵 = json.dumps(to_dict(_entry(报告编号="诱饵")), ensure_ascii=False)
    (tmp_path / "外部诱饵.json").write_text(诱饵, encoding="utf-8")

    assert store.get("../外部诱饵") is None
    assert store.get("../../../../../../etc/passwd") is None
