"""台账记录的数据模型。

**存快照，不存引用**——一条记录自己就能重算，不依赖任何别的东西还在不在。

理由：实例库是可变的（`InstanceStore.remove()` 存在，只是接口层没暴露，那是巧合
不是保证）。存引用的话，有人事后动了实例库，台账就悬空，「能复现」退化成「希望
没人改过」。代价是每条约 10 KB，几百份报告几 MB，可忽略。

基础表的知识也整份存，不只存指纹：把一条台账单独发给别人复核，他手上没有那个
版本文件也要能重算。
"""

import getpass
import logging
import platform
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from src.engine.knowledge import Knowledge
from src.engine.methods.base import Instance, Result
from src.knowledge_base.store import BaseTableStore
from src.model import Category
from src.version import __version__

logger = logging.getLogger(__name__)

__all__ = [
    "BaseTableUse",
    "Deviation",
    "InstanceUse",
    "LedgerEntry",
    "MethodUse",
    "current_operator",
    "from_dict",
    "new_record_id",
    "to_dict",
]


def new_record_id() -> str:
    """台账记录号。

    用随机而非时间戳：同一秒连生成两份报告，时钟精度防不住相撞。取 uuid4 十六进制
    前 12 位——只含 0-9a-f，落成文件名天然安全。
    """
    return uuid4().hex[:12]


def current_operator() -> str:
    """经手人：`登录名@机器名`，自动取，不让人填。

    **不是身份认证**——登录名改得掉。但复查范围是内部复核（决策记录 §1：「这个是
    我们自己人来看的」），够用；且不用估价师记得填，填了会忘、会乱填。接钉钉后
    换成真实工号。

    取不到时退化为空串而非抛错：台账记不全好过报告生成失败。
    """
    try:
        user = getpass.getuser()
    except OSError:  # 无 home、无 LOGNAME 的环境
        logger.warning("取不到登录名，经手人将只记机器名")
        user = ""
    return f"{user}@{platform.node()}"


@dataclass(frozen=True)
class Deviation:
    """单份报告对基础表的一处偏离。

    **今天恒空**——偏离功能未上线（用户决定：只留口子）。形状先定下来，将来加时
    老记录的空数组语义天然正确，不必重写历史台账。

    偏离必须存成「基线版本 + 差异」，不能存成「另一个版本」：否则一年下来库里躺着
    两百个指纹，分不出哪些是公司知识演进、哪些是某个项目破了个例。
    """

    因素: str
    字段: str
    原值: str
    现值: str
    审批单号: str = ""
    理由: str = ""


@dataclass(frozen=True)
class BaseTableUse:
    """这份报告用的基础表。"""

    基线版本: str
    偏离: tuple[Deviation, ...]
    实际知识: Knowledge
    实际指纹: str


@dataclass(frozen=True)
class MethodUse:
    """这份报告用的比较法。

    **存名称与版本，重放时按名字取方法，不取今天的默认。** 理由同权重：今天只有
    「市场比较法-2026」一种，但将来有人加了 2027 版并改掉默认，重放旧台账会拿新算法
    去算旧数据，**静默算出另一个数**——而台账正是为了防这个而存在。
    """

    名称: str
    版本: str


@dataclass(frozen=True)
class InstanceUse:
    """这份报告用的一条实例。

    `实例` 已含市场状况指数（它是「实例 × 本项目价值时点」的配对属性，非实例固有）。
    `编号` 单独留着只为可读——**重放不靠它去库里查**，靠的是 `实例` 本身。
    """

    实例: Instance
    编号: str
    判断依据: str = ""


@dataclass(frozen=True)
class LedgerEntry:
    """一次生成的完整快照。"""

    记录号: str
    报告编号: str
    生成时间: datetime
    经手人: str
    程序版本: str
    类别: Category
    基础表: BaseTableUse | None
    估价对象档次: dict[str, str] | None
    实例: tuple[InstanceUse, ...] | None
    方法: MethodUse | None
    权重: tuple[float, ...] | None
    结果: Result | None
    一览表: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def 经引擎重算(self) -> bool:
        """这份报告的数字是不是引擎算的。

        导入 Excel 直接生成时为 False——**这不是缺失，恰恰是复核最想知道的事**。
        """
        return self.结果 is not None

    @staticmethod
    def new(
        报告编号: str,
        类别: Category,
        基础表: BaseTableUse | None,
        估价对象档次: dict[str, str] | None,
        实例: tuple[InstanceUse, ...] | None,
        方法: MethodUse | None,
        权重: tuple[float, ...] | None,
        结果: Result | None,
        一览表: tuple[dict[str, object], ...],
        now: datetime | None = None,
        经手人: str | None = None,
    ) -> "LedgerEntry":
        """造一条记录。

        Args:
            now: 生成时间；缺省取当前时刻。显式开口子是为了让测试固定时间。
            经手人: 缺省自动取 `登录名@机器名`。

        Raises:
            ValueError: `基础表`、`估价对象档次`、`实例`、`方法`、`权重`、`结果`
                六者没有同生共灭。这六个字段只因「经引擎重算」这一件事同时
                出现——出现就必须一起出现，不出现就必须一起不出现，否则会
                造出「有结果却没有基础表」这种记录：`经引擎重算` 单靠
                `结果 is not None` 判断，那样的记录会自称「经引擎重算」，
                却缺着重算所需的东西，它在说谎。这条校验只在写入路径
                （本方法）上把关；`from_dict()` 读取台账文件时刻意不查，
                理由见该函数 docstring。
        """
        字段 = {
            "基础表": 基础表,
            "估价对象档次": 估价对象档次,
            "实例": 实例,
            "方法": 方法,
            "权重": 权重,
            "结果": 结果,
        }
        已给 = {名 for 名, 值 in 字段.items() if 值 is not None}
        if 已给 and 已给 != set(字段):
            缺失 = sorted(set(字段) - 已给)
            raise ValueError(
                "基础表/估价对象档次/实例/方法/权重/结果六者必须同生同灭"
                f"（要么全有、要么全无）：已给 {sorted(已给)}，缺 {缺失}"
            )
        return LedgerEntry(
            记录号=new_record_id(),
            报告编号=报告编号,
            生成时间=now or datetime.now(),
            经手人=经手人 or current_operator(),
            程序版本=__version__,
            类别=类别,
            基础表=基础表,
            估价对象档次=估价对象档次,
            实例=实例,
            方法=方法,
            权重=权重,
            结果=结果,
            一览表=一览表,
        )


def _instance_to_dict(use: InstanceUse) -> dict[str, object]:
    return {
        "编号": use.编号,
        "位置": use.实例.位置,
        "成交价": use.实例.成交价,
        "交易情况指数": use.实例.交易情况指数,
        "市场状况指数": use.实例.市场状况指数,
        "因素档次": dict(use.实例.因素档次),
        "判断依据": use.判断依据,
    }


def _instance_from_dict(data: dict[str, object]) -> InstanceUse:
    return InstanceUse(
        实例=Instance(
            位置=str(data["位置"]),
            成交价=float(data["成交价"]),  # type: ignore[arg-type]
            交易情况指数=float(data["交易情况指数"]),  # type: ignore[arg-type]
            市场状况指数=float(data["市场状况指数"]),  # type: ignore[arg-type]
            因素档次={str(k): str(v) for k, v in dict(data["因素档次"]).items()},  # type: ignore[call-overload]
        ),
        编号=str(data["编号"]),
        判断依据=str(data.get("判断依据", "")),
    )


def _base_table_to_dict(use: BaseTableUse) -> dict[str, object]:
    return {
        "基线版本": use.基线版本,
        "偏离": [
            {
                "因素": d.因素, "字段": d.字段, "原值": d.原值,
                "现值": d.现值, "审批单号": d.审批单号, "理由": d.理由,
            }
            for d in use.偏离
        ],
        # 知识的序列化复用基础表库那份，保证台账与版本文件的形状始终一致。
        "实际知识": BaseTableStore.to_dict(use.实际知识),
        "实际指纹": use.实际指纹,
    }


def _base_table_from_dict(data: dict[str, object]) -> BaseTableUse:
    raw = data.get("偏离")
    return BaseTableUse(
        基线版本=str(data["基线版本"]),
        偏离=tuple(
            Deviation(
                因素=str(d["因素"]), 字段=str(d["字段"]), 原值=str(d["原值"]),
                现值=str(d["现值"]), 审批单号=str(d.get("审批单号", "")),
                理由=str(d.get("理由", "")),
            )
            for d in (raw if isinstance(raw, list) else [])
        ),
        实际知识=BaseTableStore.from_dict(dict(data["实际知识"])),  # type: ignore[call-overload]
        实际指纹=str(data["实际指纹"]),
    )


def to_dict(entry: LedgerEntry) -> dict[str, object]:
    """序列化为 JSON 安全的字典。供磁盘持久化，也供网页接口复用，
    保证接口与台账文件的形状始终一致。"""
    return {
        "记录号": entry.记录号,
        "报告编号": entry.报告编号,
        "生成时间": entry.生成时间.isoformat(),
        "经手人": entry.经手人,
        "程序版本": entry.程序版本,
        "类别": entry.类别.value,
        "经引擎重算": entry.经引擎重算,
        # 一律用 is not None，不用真值判断：空 {} / 空 () 是「知道且为空」，
        # None 是「压根没有」，两者语义不同。真值判断会把空容器也存成 None，
        # 「空」与「没有」混成一个东西，台账就说不清历史上到底有没有这个字段。
        "基础表": _base_table_to_dict(entry.基础表) if entry.基础表 is not None else None,
        "估价对象档次": dict(entry.估价对象档次) if entry.估价对象档次 is not None else None,
        "实例": [_instance_to_dict(i) for i in entry.实例] if entry.实例 is not None else None,
        "方法": {"名称": entry.方法.名称, "版本": entry.方法.版本} if entry.方法 is not None else None,
        "权重": list(entry.权重) if entry.权重 is not None else None,
        "结果": {
            "比准价格": list(entry.结果.比准价格),
            "评估结果": entry.结果.评估结果,
            "离散度": entry.结果.离散度,
        } if entry.结果 is not None else None,
        "一览表": [dict(s) for s in entry.一览表],
    }


def from_dict(data: dict[str, object]) -> LedgerEntry:
    """由 to_dict 的输出还原。

    刻意不校验「基础表/估价对象档次/实例/方法/权重/结果」六者同生同灭
    （那条校验在 `LedgerEntry.new()` 里，见其 docstring）。原因：台账文件
    明说可以人类手改（`src/ledger/store.py` 的 `_读全部` 就是「坏文件跳过、
    不连累其余」的容错立场）。读取端若加严格的跨字段校验，等于哪天有人
    手改坏一条记录的某一个字段，整条记录直接读不出来、连内容都看不见，
    反而不如原样读回来，让人自己看出它坏在哪。`new()` 是写入路径，绝不能
    写出一条自相矛盾的记录；`from_dict()` 是读取路径，宁可读出一条「有点
    可疑」的记录，也不要让人连读都读不到。

    Raises:
        KeyError: 必需字段缺失。
        ValueError: 类别或时间不合法。
    """
    结果 = data.get("结果")
    实例 = data.get("实例")
    方法 = data.get("方法")
    档次 = data.get("估价对象档次")
    权重 = data.get("权重")
    基础表 = data.get("基础表")
    # 判断一律用 is not None，与 to_dict 对称：空 {} / 空 [] 也是「存在但为空」，
    # 不是「没有这个字段」。一边认空一边不认，存与读就不是一回事，往返即废。
    return LedgerEntry(
        记录号=str(data["记录号"]),
        报告编号=str(data["报告编号"]),
        生成时间=datetime.fromisoformat(str(data["生成时间"])),
        经手人=str(data["经手人"]),
        程序版本=str(data["程序版本"]),
        类别=Category(str(data["类别"])),
        基础表=_base_table_from_dict(dict(基础表)) if 基础表 is not None else None,  # type: ignore[call-overload]
        估价对象档次={str(k): str(v) for k, v in dict(档次).items()} if 档次 is not None else None,  # type: ignore[call-overload]
        实例=tuple(_instance_from_dict(i) for i in 实例) if 实例 is not None else None,  # type: ignore[attr-defined]
        方法=MethodUse(
            名称=str(dict(方法)["名称"]), 版本=str(dict(方法)["版本"])  # type: ignore[call-overload]
        ) if 方法 is not None else None,
        权重=tuple(float(w) for w in 权重) if 权重 is not None else None,  # type: ignore[attr-defined]
        结果=Result(
            比准价格=tuple(float(p) for p in dict(结果)["比准价格"]),  # type: ignore[call-overload]
            评估结果=float(dict(结果)["评估结果"]),  # type: ignore[arg-type,call-overload]
            离散度=float(dict(结果)["离散度"]),  # type: ignore[arg-type,call-overload]
        ) if 结果 is not None else None,
        一览表=tuple(dict(s) for s in data.get("一览表", [])),  # type: ignore[attr-defined]
    )
