"""照台账重算。

第一等的测试是 test_replay_survives_a_wrecked_library——**把实例库整个删掉，重放
照样算得出**。这才是「快照自洽」的证明，其余都是陪衬：拿还在库里的数据算得出来，
证明不了台账自洽，只证明库还在。
"""

import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pytest

from src.engine.compute import METHOD_NAME, compute, compute_from_selection, default_weights
from src.engine.inputs import from_excel
from src.engine.knowledge import Knowledge
from src.engine.methods import get_method
from src.engine.methods.base import ComparisonMethod, Instance, Result
from src.knowledge_base.fingerprint import fingerprint
from src.ledger.model import BaseTableUse, InstanceUse, LedgerEntry, MethodUse
from src.ledger.replay import replay
from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.model import Category
from tests.conftest import CASES

OFFICE_MARKET_INDEX = {
    "兴耀科创城A幢09层": 98,
    "蓝天国际大厦1幢808": 95,
    "蓝天国际大厦1幢703": 95,
}
OFFICE_GOLDEN = 2.83


def _live_entry(tmp_path: Path) -> tuple[LedgerEntry, InstanceStore]:
    """走完整链路算一遍，把它记成一条台账。"""
    store = InstanceStore(tmp_path / "库.json")
    for inst in import_from_excel(CASES["办公"]):
        store.add(inst)
    store.save()

    source = from_excel(CASES["办公"])
    selections = [
        {"编号": i.编号, "市场状况指数": OFFICE_MARKET_INDEX[i.位置], "备注": ""}
        for i in store.list_by_category(Category.OFFICE)
    ]
    result = compute_from_selection(source, selections, store)
    assert result.评估结果 == OFFICE_GOLDEN

    digest = fingerprint(source.knowledge)
    entry = LedgerEntry.new(
        报告编号="正恒评报字[2026]第F071号",
        类别=Category.OFFICE,
        基础表=BaseTableUse(
            基线版本=digest, 偏离=(), 实际知识=source.knowledge, 实际指纹=digest
        ),
        估价对象档次=dict(source.subject_levels),
        实例=tuple(
            InstanceUse(
                实例=Instance(
                    位置=i.位置,
                    成交价=i.成交价,
                    交易情况指数=i.交易情况指数,
                    市场状况指数=float(OFFICE_MARKET_INDEX[i.位置]),
                    因素档次=dict(i.因素档次),
                ),
                编号=i.编号,
            )
            for i in store.list_by_category(Category.OFFICE)
        ),
        方法=MethodUse(名称=METHOD_NAME, 版本=get_method(METHOD_NAME).version),
        权重=default_weights(),
        结果=result,
        一览表=(),
        now=datetime(2026, 7, 16, 11, 30, 0),
        经手人="张三@ZH-PC-03",
    )
    return entry, store


def test_replay_reproduces_the_recorded_result(tmp_path: Path) -> None:
    entry, _ = _live_entry(tmp_path)
    assert entry.结果 is not None
    assert replay(entry) == entry.结果


def test_replay_survives_a_wrecked_library(tmp_path: Path) -> None:
    """**第一等的测试**：实例库整个删掉，重放照样算得出同一个数。

    这才是「快照自洽」的证明。拿还在库里的数据算得出来，只证明库还在。
    """
    entry, store = _live_entry(tmp_path)
    store.path.unlink()
    shutil.rmtree(tmp_path / "基础表", ignore_errors=True)
    assert not store.path.exists()

    assert entry.结果 is not None
    assert replay(entry).评估结果 == OFFICE_GOLDEN


def test_replay_uses_the_recorded_weights(tmp_path: Path) -> None:
    """权重取台账里那组，不取今天 spec 里的——否则哪天开放可调，旧报告就重放错了。"""
    from dataclasses import replace

    entry, _ = _live_entry(tmp_path)
    skewed = replace(entry, 权重=(1.0, 0.0, 0.0))
    assert replay(skewed).评估结果 != OFFICE_GOLDEN
    assert replay(skewed).评估结果 == pytest.approx(2.92, abs=0.011), "该等于实例A 的比准价格"


def test_replay_refuses_a_report_that_was_never_computed(tmp_path: Path) -> None:
    """没经引擎算过的报告没什么可重放的——须说清楚，不得算出个数来蒙人。"""
    entry = LedgerEntry.new(
        报告编号="正恒评报字[2026]第F071号",
        类别=Category.OFFICE,
        基础表=None, 估价对象档次=None, 实例=None, 方法=None, 权重=None, 结果=None,
        一览表=(),
        now=datetime(2026, 7, 16, 11, 30, 0),
        经手人="张三@ZH-PC-03",
    )
    with pytest.raises(ValueError, match="未经系统重算"):
        replay(entry)


# 三类金样的市场状况指数与评估结果，取自 ADR-001 的实证表。
GOLDENS = {
    "农用": (Category.AGRICULTURAL, 1399.26),
    "办公": (Category.OFFICE, 2.83),
    "商业": (Category.COMMERCIAL, 3.32),
}


@pytest.mark.parametrize("case", ["农用", "办公", "商业"])
def test_replay_reproduces_every_golden(case: str, tmp_path: Path) -> None:
    """三类金样走完整链路记成台账后，重放仍得同一个数。

    只验办公是不够的：农用与办公的单位差 500 倍、修正系数完全不同（农用
    [2,1,2,1,2,0]、办公 [1,1,2,2,1,3]），且农用基础表只有 27 个因素而非 28。
    一类过了不代表三类都过。
    """
    from src.engine.adapter import read_instances
    from src.engine.methods.base import Instance

    category, expected = GOLDENS[case]
    store = InstanceStore(tmp_path / f"{case}库.json")
    for inst in import_from_excel(CASES[case]):
        store.add(inst)
    store.save()

    source = from_excel(CASES[case])
    # 市场状况指数取 Excel 里原填的那组（比较法表第 8 行 M/N/O），
    # 它是「实例 × 价值时点」的配对属性，不在实例库里。
    excel_instances = read_instances(CASES[case], category)
    market = {i.位置: i.市场状况指数 for i in excel_instances}

    instances = tuple(
        Instance(
            位置=i.位置,
            成交价=i.成交价,
            交易情况指数=i.交易情况指数,
            市场状况指数=market[i.位置],
            因素档次=dict(i.因素档次),
        )
        for i in store.list_by_category(category)
    )
    live = compute(source, instances, default_weights())
    assert live.评估结果 == pytest.approx(expected, abs=0.011), f"{case} 前提：金样应算出 {expected}"

    digest = fingerprint(source.knowledge)
    entry = LedgerEntry.new(
        报告编号=f"{case}金样",
        类别=category,
        基础表=BaseTableUse(基线版本=digest, 偏离=(), 实际知识=source.knowledge, 实际指纹=digest),
        估价对象档次=dict(source.subject_levels),
        实例=tuple(InstanceUse(实例=i, 编号=f"{case}-{n}") for n, i in enumerate(instances)),
        方法=MethodUse(名称=METHOD_NAME, 版本=get_method(METHOD_NAME).version),
        权重=default_weights(),
        结果=live,
        一览表=(),
        now=datetime(2026, 7, 16, 11, 30, 0),
        经手人="张三@ZH-PC-03",
    )
    # 把库整个删掉再重放——快照自洽的证明。
    store.path.unlink()
    assert replay(entry) == live
    assert replay(entry).评估结果 == pytest.approx(expected, abs=0.011)


FAKE_METHOD_NAME = "测试用假方法"


class _FakeMethod(ComparisonMethod):
    """假比较法：不管输入是什么，永远返回同一个可预测的假结果。

    存在的唯一理由：项目里目前只注册了「市场比较法-2026」一种方法，无论
    `replay()` 读不读 `entry.方法`，用真方法重算都得到同一个数——现有测试
    套件分辨不出这两种情形。注册这个假方法、把结果记成假方法名，就能造出
    一种「读了 entry.方法 得假结果、不读则得真结果」的可分辨场景，从而
    证明 `replay()` 确实按台账记的方法名取方法，而非悄悄走 `compute()`
    的默认值。
    """

    name = FAKE_METHOD_NAME
    version = "假-0"

    def compute(
        self,
        subject_levels: dict[str, str],
        instances: Sequence[Instance],
        knowledge: Knowledge,
        weights: Sequence[float],
    ) -> Result:
        return Result(比准价格=(9999.99,) * len(instances), 评估结果=9999.99, 离散度=0.0)


def test_replay_uses_the_recorded_method_not_todays_default(tmp_path: Path) -> None:
    """**这是能拦住「方法字段白存」这类回归的守卫测试。**

    只注册一种真方法时，读不读 `entry.方法` 都算出同一个数，任何测试都分辨
    不出来——这正是评审点出的漏洞。这里临时注册一个假方法，结果与真方法
    判若两数，再把台账的 `方法` 改记成假方法名：`replay()` 若正确读取
    `entry.方法.名称`，就该走假方法、得到 9999.99；若像修复前那样硬编码
    默认方法，就仍会算出办公金样的 2.83。
    """
    from dataclasses import replace

    from src.engine.methods import _REGISTRY, register_method

    entry, _ = _live_entry(tmp_path)
    assert entry.方法 is not None
    assert entry.结果 is not None

    register_method(_FakeMethod)
    try:
        fake_entry = replace(
            entry, 方法=MethodUse(名称=FAKE_METHOD_NAME, 版本=_FakeMethod.version)
        )
        result = replay(fake_entry)
        assert result.评估结果 == 9999.99, "没走假方法，说明 replay 没按 entry.方法 取方法"
        assert result.评估结果 != entry.结果.评估结果
    finally:
        # 用完即删，别把假方法留在注册表里污染其余测试。
        del _REGISTRY[FAKE_METHOD_NAME]
