"""输入抽象层：引擎不认识 Excel。

第一等测试是 test_engine_computes_from_inputs_never_touched_by_excel——
它证明的不是「Excel 路径还能算」（那是 test_engine_golden 的事），而是
**手工攒出来的输入照样能算出金样**。表单路径就是这么喂它的：档次来自 28 个
下拉框，基础表知识来自本机存的副本，全程没有 xlsx。这条过了，表单才有地基。
"""

import pytest

from src.engine.compute import compute_from_selection
from src.engine.inputs import ComparisonInput, from_excel
from src.engine.knowledge import Factor, Knowledge
from src.engine.methods.base import Instance
from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.model import Category
from tests.conftest import CASES

# 实测：办公 Excel 里原填的市场状况指数，算出评估结果 2.83（见 ADR-001 的表）。
OFFICE_MARKET_INDEX = {
    "兴耀科创城A幢09层": 98,
    "蓝天国际大厦1幢808": 95,
    "蓝天国际大厦1幢703": 95,
}
OFFICE_GOLDEN = 2.83


def _office_store(tmp_path) -> InstanceStore:  # type: ignore[no-untyped-def]
    store = InstanceStore(tmp_path / "库.json")
    for inst in import_from_excel(CASES["办公"]):
        store.add(inst)
    return store


def _office_selections(store: InstanceStore) -> list[dict[str, object]]:
    return [
        {"编号": i.编号, "市场状况指数": OFFICE_MARKET_INDEX[i.位置], "备注": ""}
        for i in store.list_by_category(Category.OFFICE)
    ]


def test_from_excel_reads_all_three_inputs() -> None:
    """Excel 适配器要凑齐引擎需要的三样：类别、基础表知识、估价对象档次。"""
    source = from_excel(CASES["办公"])
    assert source.category is Category.OFFICE
    assert len(source.knowledge.factors) == 28
    assert len(source.subject_levels) == 28


def test_engine_computes_from_inputs_never_touched_by_excel(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """把输入拆成纯 Python 数据再重建，引擎必须算出同一个金样 2.83。

    这里刻意绕开 `from_excel()`：知识与档次先降解成 dict/str/float，再重新
    组装成 `ComparisonInput`——正是表单路径将来要走的形状（档次来自下拉框，
    知识来自本机 JSON 副本）。若引擎还偷偷依赖 xlsx 的任何东西，这条会红。
    """
    excel_source = from_excel(CASES["办公"])

    # 降解为纯数据，模拟「存过一趟 JSON、又从表单收了一遍」。
    plain_factors = [
        {
            "row": f.row,
            "name": f.name,
            "levels": dict(f.levels),
            "coefficient": f.coefficient,
        }
        for f in excel_source.knowledge.factors
    ]
    plain_levels = dict(excel_source.subject_levels)
    plain_scores = list(excel_source.knowledge.scores)

    rebuilt = ComparisonInput(
        category=Category.OFFICE,
        knowledge=Knowledge(
            factors=tuple(
                Factor(
                    row=int(d["row"]),  # type: ignore[arg-type]
                    name=str(d["name"]),
                    levels=dict(d["levels"]),  # type: ignore[arg-type]
                    coefficient=float(d["coefficient"]),  # type: ignore[arg-type]
                )
                for d in plain_factors
            ),
            scores=tuple(plain_scores),
        ),
        subject_levels=plain_levels,
    )

    store = _office_store(tmp_path)
    result = compute_from_selection(rebuilt, _office_selections(store), store)
    assert result.评估结果 == OFFICE_GOLDEN


def test_both_paths_agree(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Excel 路径与手攒路径必须算出完全相同的结果——同一个引擎，同一份输入。"""
    store = _office_store(tmp_path)
    selections = _office_selections(store)
    excel_source = from_excel(CASES["办公"])
    hand_source = ComparisonInput(
        category=excel_source.category,
        knowledge=excel_source.knowledge,
        subject_levels=dict(excel_source.subject_levels),
    )
    assert compute_from_selection(excel_source, selections, store) == compute_from_selection(
        hand_source, selections, store
    )


def test_category_mismatch_still_caught(tmp_path) -> None:
    """跨类别选实例仍须拦住——抽象层不能把这道防护弄丢了。"""
    store = InstanceStore(tmp_path / "库.json")
    for case in ("办公", "农用"):
        for inst in import_from_excel(CASES[case]):
            store.add(inst)
    land = store.list_by_category(Category.AGRICULTURAL)
    selections = [{"编号": i.编号, "市场状况指数": 100, "备注": ""} for i in land]
    with pytest.raises(ValueError, match="类别"):
        compute_from_selection(from_excel(CASES["办公"]), selections, store)


def test_compute_needs_no_store(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """给现成的实例就该能算，不必先塞进一个库再取出来。

    这是重放的地基：台账里的实例是快照，本来就不在库里，也不该为了算它而临时建库。
    """
    from src.engine.compute import compute, default_weights

    store = _office_store(tmp_path)
    source = from_excel(CASES["办公"])
    instances = tuple(
        Instance(
            位置=i.位置,
            成交价=i.成交价,
            交易情况指数=i.交易情况指数,
            市场状况指数=OFFICE_MARKET_INDEX[i.位置],
            因素档次=dict(i.因素档次),
        )
        for i in store.list_by_category(Category.OFFICE)
    )
    result = compute(source, instances, default_weights())
    assert result.评估结果 == OFFICE_GOLDEN


def test_both_entry_points_agree(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """compute_from_selection 只是「取库 + 调 compute」，两者结果必须一致。"""
    from src.engine.compute import compute, default_weights

    store = _office_store(tmp_path)
    source = from_excel(CASES["办公"])
    via_store = compute_from_selection(source, _office_selections(store), store)
    instances = tuple(
        Instance(
            位置=i.位置,
            成交价=i.成交价,
            交易情况指数=i.交易情况指数,
            市场状况指数=OFFICE_MARKET_INDEX[i.位置],
            因素档次=dict(i.因素档次),
        )
        for i in store.list_by_category(Category.OFFICE)
    )
    assert compute(source, instances, default_weights()) == via_store


def test_default_weights_are_thirds() -> None:
    """权重写死各 ⅓（用户决定）。台账要存它——哪天开放可调，重放必须用当时那组。"""
    from src.engine.compute import default_weights

    weights = default_weights()
    assert len(weights) == 3
    assert sum(weights) == pytest.approx(1.0, abs=0.001)
