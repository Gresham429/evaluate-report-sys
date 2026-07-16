"""台账数据模型。

**快照自洽**是这个模型的全部理由：一条记录自己就能重算，不依赖实例库、基础表库
还在不在。故往返无损是第一等的测试——存下去取回来但丢了字段，等于台账在说谎。
"""

from datetime import datetime

from src.engine.inputs import from_excel
from src.engine.knowledge import Knowledge
from src.engine.methods.base import Instance, Result
from src.knowledge_base.fingerprint import fingerprint
from src.ledger.model import (
    BaseTableUse,
    InstanceUse,
    LedgerEntry,
    MethodUse,
    current_operator,
    from_dict,
    new_record_id,
    to_dict,
)
from src.model import Category
from tests.conftest import CASES

WHEN = datetime(2026, 7, 16, 11, 30, 0)


def _knowledge() -> Knowledge:
    return from_excel(CASES["办公"]).knowledge


def _entry() -> LedgerEntry:
    knowledge = _knowledge()
    digest = fingerprint(knowledge)
    return LedgerEntry.new(
        报告编号="正恒评报字[2026]第F071号",
        类别=Category.OFFICE,
        基础表=BaseTableUse(
            基线版本=digest, 偏离=(), 实际知识=knowledge, 实际指纹=digest
        ),
        估价对象档次=dict(from_excel(CASES["办公"]).subject_levels),
        实例=(
            InstanceUse(
                实例=Instance(
                    位置="兴耀科创城A幢09层",
                    成交价=2.52,
                    交易情况指数=100.0,
                    市场状况指数=98.0,
                    因素档次={"临街状况": "四面临街"},
                ),
                编号="办公-2026-01-兴耀科创城A幢09层",
                判断依据="起始日贴近价值时点",
            ),
        ),
        方法=MethodUse(名称="市场比较法-2026", 版本="2026-07"),
        权重=(1 / 3, 1 / 3, 1 / 3),
        结果=Result(比准价格=(2.92, 2.77, 2.80), 评估结果=2.83, 离散度=0.05),
        一览表=({"index": 1, "area": 356.29, "unit_price": 2.83, "annual_value": 368030},),
        now=WHEN,
        经手人="张三@ZH-PC-03",
    )


def test_round_trip_loses_nothing() -> None:
    """存下去取回来必须一模一样——**含整份基础表知识**。

    知识整份存是为了「把一条台账单独发给别人，他手上没有版本文件也能重算」。
    丢了它，快照自洽就是空话。
    """
    entry = _entry()
    assert from_dict(to_dict(entry)) == entry


def test_knowledge_survives_the_round_trip_intact() -> None:
    """28 个因素、档次、系数、标尺，一个都不能少。"""
    entry = _entry()
    back = from_dict(to_dict(entry))
    assert back.基础表 is not None
    assert back.基础表.实际知识 == _knowledge()
    assert len(back.基础表.实际知识.factors) == 28


def test_weights_are_recorded() -> None:
    """权重现在写死各 ⅓，但哪天开放可调，重放必须用当时那组，不能用今天的。"""
    assert from_dict(to_dict(_entry())).权重 == (1 / 3, 1 / 3, 1 / 3)


def test_method_is_recorded() -> None:
    """方法名与版本也得存，理由同权重。

    今天只有「市场比较法-2026」一种，但将来有人加了 2027 版并改掉默认，重放旧台账
    会拿新算法去算旧数据，**静默算出另一个数**——而台账正是为了防这个而存在。
    """
    back = from_dict(to_dict(_entry()))
    assert back.方法 is not None
    assert back.方法.名称 == "市场比较法-2026"
    assert back.方法.版本 == "2026-07"


def test_deviation_is_empty_but_present() -> None:
    """今天没有单份偏离功能，但形状先留着。

    将来加偏离，老记录的空数组语义天然正确——不必重写历史台账。
    """
    data = to_dict(_entry())
    assert data["基础表"]["偏离"] == []
    assert data["基础表"]["实际指纹"] == data["基础表"]["基线版本"]


def test_report_without_recompute() -> None:
    """导入 Excel 直接生成的报告：没有基础表、没有实例、没有结果。

    **这不是缺失，是复核最想知道的事**——这份报告的数字不是引擎算的。
    """
    entry = LedgerEntry.new(
        报告编号="正恒评报字[2026]第F071号",
        类别=Category.OFFICE,
        基础表=None,
        估价对象档次=None,
        实例=None,
        方法=None,
        权重=None,
        结果=None,
        一览表=({"index": 1, "area": 356.29, "unit_price": 2.83, "annual_value": 368030},),
        now=WHEN,
        经手人="张三@ZH-PC-03",
    )
    assert entry.经引擎重算 is False
    assert from_dict(to_dict(entry)) == entry


def test_recomputed_entry_says_so() -> None:
    assert _entry().经引擎重算 is True


def test_record_ids_do_not_collide() -> None:
    """同一秒连生成两份报告不能撞号——时钟精度防不住。"""
    assert len({new_record_id() for _ in range(500)}) == 500


def test_operator_is_login_at_host() -> None:
    """经手人自动取，不让人填——填了会忘、会乱填。

    不是身份认证（改得掉），内部复核够用；接钉钉后换成真实工号。
    """
    operator = current_operator()
    assert "@" in operator
    assert operator.split("@")[0]
    assert operator.split("@")[1]


def test_time_is_injectable() -> None:
    """测试要能固定时间，模块内不许直接调 datetime.now() 而无法注入。"""
    assert _entry().生成时间 == WHEN
