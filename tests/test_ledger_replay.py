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
from src.engine.knowledge import Knowledge, apply_coefficient_overrides
from src.engine.methods import get_method
from src.engine.methods.base import ComparisonMethod, Instance, Result
from src.knowledge_base.fingerprint import fingerprint
from src.knowledge_base.store import BaseTableStore
from src.ledger.model import BaseTableUse, InstanceUse, LedgerEntry, MethodUse
from src.ledger.model import from_dict as ledger_from_dict
from src.ledger.model import to_dict as ledger_to_dict
from src.ledger.replay import replay
from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.model import Category, Project
from src.web.app import _build_ledger_entry
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


def _minimal_project(report_no: str, category: Category) -> Project:
    """搭一个满足 `Project` 全部必填字段的最小项目。

    本测试只关心 `_build_ledger_entry` 怎么处理权重，其余字段内容不影响权重
    逻辑，占位即可——但 `Project` 是 frozen dataclass、字段全部必填，仍须凑齐。
    """
    return Project(
        category=category,
        report_no=report_no,
        project_name="测试项目",
        client="测试委托方",
        client_address="测试地址",
        legal_rep="张三",
        purpose="评估房地产租赁价值",
        survey_date="2026-03-26",
        value_date="2026-03-26",
        materials="《不动产权证》",
        certificate_status="估价对象已取得《不动产权证》",
        owner="测试权利人",
        address="测试坐落",
        usage="办公",
        scale="占位",
        scope="占位",
        current_status="占位",
        work_period="占位",
        issue_date="2026-06-05",
        surveyor="测试人员",
        unit_price=0.0,
        dispersion=0.0,
        subjects=(),
    )


def test_ledger_entry_stores_the_weights_actually_used_not_todays_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**台账记录侧的坑**：`_build_ledger_entry` 必须记「当时实际用的那组权重」，
    不是它自己调 `default_weights()` 拿到的今天默认 ⅓⅓⅓。

    三步缺一不可：
    1. 前提——(0.5, 0.3, 0.2) 与默认 ⅓⅓⅓ 必须算出不同的评估结果，否则测试测
       不出区别（拿一样的数蒙混过关）。
    2. 修复本身——`_build_ledger_entry(project, raw)` 记进 `entry.权重` 的必须
       是 raw 里的 (0.5, 0.3, 0.2)，不是 `default_weights()`。这条在修复前
       （`_build_ledger_entry` 硬编码 `权重=default_weights()`）必然失败。
    3. 修复闭环——把这条记录落盘往返（`to_dict` → `from_dict`）后 `replay()`，
       重算结果须与非默认权重那次一致：证明 `replay()` 用的是台账里存的权重，
       不是随手拿到的今天默认（`replay.py` 早已正确读取 `entry.权重`，这一步
       验证的是「存对了」，不是「读对了」）。
    """
    store_path = tmp_path / "库.json"
    store = InstanceStore(store_path)
    for inst in import_from_excel(CASES["办公"]):
        store.add(inst)
    store.save()
    monkeypatch.setenv("实例库路径", str(store_path))
    base_dir = tmp_path / "基础表"
    monkeypatch.setenv("基础表目录", str(base_dir))
    BaseTableStore(base_dir).import_from_excel(CASES["办公"])

    source = from_excel(CASES["办公"])
    selected = [
        {"编号": i.编号, "市场状况指数": OFFICE_MARKET_INDEX[i.位置], "备注": ""}
        for i in store.list_by_category(Category.OFFICE)
    ]

    skewed_weights = (0.5, 0.3, 0.2)
    default_result = compute_from_selection(source, selected, store)
    skewed_result = compute_from_selection(source, selected, store, weights=skewed_weights)
    assert skewed_result.评估结果 != default_result.评估结果, (
        "前提不成立：(0.5,0.3,0.2) 与默认 ⅓⅓⅓ 须算出不同的评估结果，否则测试测不出区别"
    )

    project = _minimal_project("正恒评报字[2026]第F071号", Category.OFFICE)
    raw: dict[str, object] = {
        "category": "办公",
        "base_table": None,
        "subject_levels": source.subject_levels,
        "selected": selected,
        "weights": list(skewed_weights),
        "result": {
            "比准价格": list(skewed_result.比准价格),
            "评估结果": skewed_result.评估结果,
            "离散度": skewed_result.离散度,
        },
    }

    entry = _build_ledger_entry(project, raw)
    assert entry.权重 == skewed_weights, "台账记的不是实际用的权重，而是今天的默认——坑没堵上"
    assert entry.权重 != default_weights()

    round_tripped = ledger_from_dict(ledger_to_dict(entry))
    assert round_tripped.权重 == skewed_weights

    replayed = replay(round_tripped)
    assert replayed.评估结果 == skewed_result.评估结果
    assert replayed.评估结果 != default_result.评估结果


# 办公基础表里「重要场所距离」原系数 1.0、调整范围 2-4。改到 3.0（范围内）足以
# 让评估结果与基础表原值算出的结果不同——是本模块坑测试与软提示测试的公共前提。
OFFICE_OVERRIDE_FACTOR = "重要场所距离"
OFFICE_OVERRIDE_COEFF = 3.0


def test_ledger_entry_stores_the_overridden_coefficient_not_the_base_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**台账记录侧的坑（单份偏离版）**：`_build_ledger_entry` 必须把估价师逐份调过的
    系数存进 `实际知识`，不是基础表原始系数——否则 `replay()` 会悄悄用回基础表
    系数，算出另一个数，且看不出错在哪（与可调权重的坑同一类，见 223d4ac）。

    四步缺一不可：
    1. 前提——覆盖后的系数须与基础表原系数算出不同的评估结果，否则测试测不出
       区别（拿一样的数蒙混过关）。
    2. 修复本身——`entry.基础表.实际知识` 里 `重要场所距离` 的系数必须是覆盖后
       的 3.0，不是基础表原始的 1.0。
    3. `偏离` 必须记下这处差异（因素/字段/原值/现值），且 `审批单号` 为空——
       自由覆盖模式不设审批门槛。
    4. 修复闭环——落盘往返（`to_dict`→`from_dict`）后 `replay()`，重算结果须
       与覆盖后那次一致：证明 `replay()` 用的是台账里存的覆盖后知识，不是
       基础表库里的原始版本（`replay.py` 早已正确读取 `entry.基础表.实际知识`，
       这一步验证的是「存对了」，不是「读对了」）。
    """
    store_path = tmp_path / "库.json"
    store = InstanceStore(store_path)
    for inst in import_from_excel(CASES["办公"]):
        store.add(inst)
    store.save()
    monkeypatch.setenv("实例库路径", str(store_path))
    base_dir = tmp_path / "基础表"
    monkeypatch.setenv("基础表目录", str(base_dir))
    BaseTableStore(base_dir).import_from_excel(CASES["办公"])

    source = from_excel(CASES["办公"])
    selected = [
        {"编号": i.编号, "市场状况指数": OFFICE_MARKET_INDEX[i.位置], "备注": ""}
        for i in store.list_by_category(Category.OFFICE)
    ]

    base_coefficient = next(
        f.coefficient for f in source.knowledge.factors if f.name == OFFICE_OVERRIDE_FACTOR
    )
    assert base_coefficient != OFFICE_OVERRIDE_COEFF, "前提不成立：覆盖值须与基础表原值不同"

    default_result = compute_from_selection(source, selected, store)
    overridden_knowledge = apply_coefficient_overrides(
        source.knowledge, {OFFICE_OVERRIDE_FACTOR: OFFICE_OVERRIDE_COEFF}
    )
    from dataclasses import replace

    overridden_source = replace(source, knowledge=overridden_knowledge)
    overridden_result = compute_from_selection(overridden_source, selected, store)
    assert overridden_result.评估结果 != default_result.评估结果, (
        "前提不成立：覆盖系数须算出与基础表不同的评估结果，否则测试测不出区别"
    )

    project = _minimal_project("正恒评报字[2026]第F071号", Category.OFFICE)
    raw: dict[str, object] = {
        "category": "办公",
        "base_table": None,
        "subject_levels": source.subject_levels,
        "selected": selected,
        "coefficient_overrides": {OFFICE_OVERRIDE_FACTOR: OFFICE_OVERRIDE_COEFF},
        "偏离理由": "实地勘察后估价师判断该项目与基础表默认档次不符",
        "result": {
            "比准价格": list(overridden_result.比准价格),
            "评估结果": overridden_result.评估结果,
            "离散度": overridden_result.离散度,
        },
    }

    entry = _build_ledger_entry(project, raw)
    assert entry.基础表 is not None
    stored_factor = next(
        f for f in entry.基础表.实际知识.factors if f.name == OFFICE_OVERRIDE_FACTOR
    )
    assert stored_factor.coefficient == OFFICE_OVERRIDE_COEFF, (
        "台账记的不是覆盖后的系数，而是基础表原系数——坑没堵上"
    )

    assert len(entry.基础表.偏离) == 1
    deviation = entry.基础表.偏离[0]
    assert deviation.因素 == OFFICE_OVERRIDE_FACTOR
    assert deviation.字段 == "每差1档修正系数"
    assert deviation.原值 == str(base_coefficient)
    assert deviation.现值 == str(OFFICE_OVERRIDE_COEFF)
    assert deviation.审批单号 == "", "自由偏离模式不设审批门槛，审批单号须为空"
    assert deviation.理由 == "实地勘察后估价师判断该项目与基础表默认档次不符"

    # 基线版本/实际指纹不因偏离而变——偏离是「基线版本 + 差异」，不是新版本。
    assert entry.基础表.基线版本 == entry.基础表.实际指纹

    round_tripped = ledger_from_dict(ledger_to_dict(entry))
    assert round_tripped.基础表 is not None
    round_tripped_factor = next(
        f for f in round_tripped.基础表.实际知识.factors if f.name == OFFICE_OVERRIDE_FACTOR
    )
    assert round_tripped_factor.coefficient == OFFICE_OVERRIDE_COEFF

    replayed = replay(round_tripped)
    assert replayed.评估结果 == overridden_result.评估结果
    assert replayed.评估结果 != default_result.评估结果


def test_ledger_entry_without_overrides_keeps_deviation_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没传 coefficient_overrides——`偏离` 须为空、`实际知识` 须是基础表原样。

    向后兼容检查：老 payload（前端还没送 coefficient_overrides 字段）不该被
    本次改动波及。
    """
    entry, _ = _live_entry(tmp_path)
    assert entry.基础表 is not None
    assert entry.基础表.偏离 == ()


def test_ledger_entry_rejects_unknown_coefficient_override_factor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """覆盖里出现基础表没有的因素名——台账不能悄悄把这条记录写下去。

    `apply_coefficient_overrides` 已会为未知因素名报 `ValueError`
    （`src/engine/knowledge.py`），`_build_ledger_entry` 必须原样放行、不吞掉它：
    写入路径宁可炸也不能把一条覆盖了不存在因素的记录写进永久台账。
    `/api/render` 外层有广播 except 兜底（报告照常出、只是台账跳过），
    但这条防线得先在这里立住。
    """
    base_dir = tmp_path / "基础表"
    monkeypatch.setenv("基础表目录", str(base_dir))
    BaseTableStore(base_dir).import_from_excel(CASES["办公"])

    project = _minimal_project("正恒评报字[2026]第F071号", Category.OFFICE)
    raw: dict[str, object] = {
        "category": "办公",
        "base_table": None,
        "coefficient_overrides": {"这个因素不存在": 3.0},
        "result": {"比准价格": [1.0], "评估结果": 1.0, "离散度": 0.0},
    }
    with pytest.raises(ValueError, match="未知因素名"):
        _build_ledger_entry(project, raw)


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
