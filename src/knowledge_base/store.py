"""基础表存储与版本管理。

方案乙（决策记录 §1）：Excel 是权威，系统存副本，估价师改了基础表就重导一次。
基础表撤不掉——它是估价知识本身（决策记录 §2.5）；但它得从「每份报告传一次
Excel」变成「导入一次、存副本、按版本取用」。

**旧版本永不覆盖**。光记「这份报告用了 v1」不够，得能拿 v1 把当时的结果重算
出来（决策记录 §3.1），故版本文件一旦落盘即不可变。

JSON 而非 SQLite：理由同实例库——单机单用户、数据量小、无并发，且须人类可读
可手改可备份。

与 `InstanceStore` 的一处刻意不同：本类**不设 load/save 的内存态**。实例库有
增删改，需要内存态；基础表只有「导入即落盘」一种写入，读时直接看磁盘最省事，
也不会有内存与磁盘不一致的余地。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.engine.knowledge import Factor, Knowledge, extract_knowledge
from src.extractor.condition import read_survey_conditions
from src.extractor.survey import extract_survey

# 取别名：本模块的 load()/_version_path() 对外的形参就叫 fingerprint（指纹是版本号，
# 这个名字对调用方最自然），裸导入同名函数会在函数体内被形参遮蔽——`fingerprint(k)`
# 会变成 `'str' object is not callable`。
from src.knowledge_base.backend import BaseTableBackend
from src.knowledge_base.fingerprint import fingerprint as compute_fingerprint
from src.paths import data_dir
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["BaseTableStore", "VersionInfo", "ImportResult", "DEFAULT_STORE_DIR", "LEDGER_NAME"]

DEFAULT_STORE_DIR = data_dir() / "基础表"
LEDGER_NAME = "台账.json"


@dataclass(frozen=True)
class VersionInfo:
    """台账里的一条：某类别的某一版基础表是何时、从哪个文件导入的。"""

    类别: Category
    指纹: str
    导入时间: datetime
    来源文件名: str


@dataclass(frozen=True)
class ImportResult:
    """一次导入的结果。

    `是否新版` 为 False 表示这份内容已经在库里了（指纹相同）——不是错误，是
    「估价师没改基础表就又导了一次」的正常情形，此时 `版本` 是**原先那条**，
    导入时间仍是首次导入的时间。
    """

    版本: VersionInfo
    是否新版: bool


class BaseTableStore:
    """基础表版本库。按类别分版，以内容指纹作版本号，旧版永不覆盖。"""

    def __init__(
        self, path: Path = DEFAULT_STORE_DIR, *, backend: BaseTableBackend | None = None
    ) -> None:
        self.path = path  # 保留：既有调用点/测试仍读它
        # 持久化委托给可插拔后端；默认后端由工厂按 env 选（未配置=本地文件，行为一字不变）。
        # 工厂延迟到实例化时导入，避免 store→factory→store 的模块级循环导入。
        if backend is None:
            from src.dingtalk.factory import base_table_backend_for

            backend = base_table_backend_for(path)
        self._backend: BaseTableBackend = backend

    # ------------------------------------------------------------ 对外

    def import_from_excel(self, path: Path, now: datetime | None = None) -> ImportResult:
        """导入一份 Excel 的基础表。

        Args:
            path: 实勘表 Excel 路径（内含基础表工作表）。
            now: 导入时间。默认取当前时间；须可注入，否则测试无从固定时间。
                **须是 naive datetime**（与 `datetime.now()` 一致）：台账按 isoformat
                存盘，混进带时区的值会让此后 `list_versions()` 的排序永久
                `TypeError`（naive 与 aware 不可比），且只能靠手改台账救回。

        Returns:
            ImportResult。指纹已在库中时 `是否新版=False`，且不新增版本、不改写
            首次导入时间；仅当该版本的文件缺失时会按台账把它补回。

        Raises:
            ValueError: 基础表缺失、分值行不合法，或 A1 标题无法识别类别。
        """
        knowledge = extract_knowledge(path)
        group_of = {c.factor: c.group for c in read_survey_conditions(path)}
        knowledge = Knowledge(
            factors=tuple(
                Factor(
                    row=f.row,
                    name=f.name,
                    levels=f.levels,
                    coefficient=f.coefficient,
                    group=group_of.get(f.name, ""),
                    调整范围=f.调整范围,
                )
                for f in knowledge.factors
            ),
            scores=knowledge.scores,
        )
        if any(f.group == "" for f in knowledge.factors):
            logger.warning("基础表 %s 有因素未在实勘表分组里命中，将不分组显示", path.name)
        category = self._detect_category(path)
        digest = compute_fingerprint(knowledge)

        existing = self._find(category, digest)
        if existing is not None:
            # 内容没变就什么都不做：不重写版本（不可变），不重复记台账，也不改写
            # 首次导入时间——那个时间是「这版何时进的库」的事实。
            if not self._backend.version_exists(category.value, digest):
                # 除非版本没了（人工误删、备份不全）。此时必须补回：手里还攥着源头
                # Excel 却救不回旧版本，直接打在「能复现」上，而重导同一份 Excel
                # 正是估价师唯一会想到的自救动作。补版本不补台账——这版何时进的库
                # 是既成事实，不该被一次修复改写成今天。
                self._backend.write_version(category.value, digest, self.to_dict(knowledge))
                logger.warning(
                    "基础表 %s 版本 %s 缺失，已按台账补回", category.value, digest
                )
            logger.info("基础表 %s 指纹 %s 已在库中，未新增版本", category.value, digest)
            return ImportResult(版本=existing, 是否新版=False)

        info = VersionInfo(
            类别=category,
            指纹=digest,
            导入时间=now if now is not None else datetime.now(),
            来源文件名=path.name,
        )
        # 版本已在、台账却无记录（人工拷入等）时只补台账不动版本：落了盘的版本一律
        # 不可变，而同指纹即同内容，重写只会写出一模一样的字节，徒然给「旧版本永不
        # 覆盖」开一道口子。版本是否名副其实交给 load() 校验，不在此处臆断。
        if not self._backend.version_exists(category.value, digest):
            self._backend.write_version(category.value, digest, self.to_dict(knowledge))
        self._append(info)
        logger.info(
            "导入基础表 %s 版本 %s（%d 个因素，来源 %s）",
            category.value,
            digest,
            len(knowledge.factors),
            path.name,
        )
        return ImportResult(版本=info, 是否新版=True)

    def load(self, category: Category, fingerprint: str | None = None) -> Knowledge:
        """取出某一版基础表知识。

        Args:
            category: 类别。
            fingerprint: 版本指纹。不给时取该类别**最新导入**的一版（以台账的
                导入时间为准，不是文件名排序——指纹是哈希，字典序毫无意义）。

        Returns:
            Knowledge。与 `extract_knowledge` 直接读 Excel 所得完全相等，含 row。

        Raises:
            FileNotFoundError: 该类别尚未导入过，或指纹不在库中。
            ValueError: 版本文件的内容与文件名上的指纹对不上（疑遭改动）。
        """
        if fingerprint is None:
            latest = self.current(category)
            if latest is None:
                raise FileNotFoundError(
                    f"尚未导入过 {category.value} 类基础表：{self.path}"
                )
            fingerprint = latest.指纹

        payload = self._backend.read_version(category.value, fingerprint)
        if payload is None:
            raise FileNotFoundError(f"{category.value} 类基础表无版本 {fingerprint}")
        knowledge = self.from_dict(payload)

        # 版本内容是人类可读可手改的 JSON，那手改就迟早会发生。而指纹本就是这份
        # 内容的哈希，验一次即可把版本号从「标签」变成「凭据」：内容与指纹对不上
        # 就说明它已不是当初存进来的那一版。不验的话，「拿 v1 重算 2026-03 那份
        # 报告」会静默算出另一个数——那正是本模块要防的事故，且无声无息。
        # 校验的是**知识**而非字节：改缩进、调键序不算改动，改系数才算。
        actual = compute_fingerprint(knowledge)
        if actual != fingerprint:
            raise ValueError(
                f"基础表版本与指纹不符，疑被改动（{category.value}：版本号 {fingerprint}，"
                f"实际内容为 {actual}）。基础表要改请改 Excel 后重导，重导会落成新版本。"
            )
        return knowledge

    def list_versions(self, category: Category) -> tuple[VersionInfo, ...]:
        """列出某类别的全部版本，按导入时间新→旧。"""
        entries = [(i, v) for i, v in enumerate(self._read_ledger()) if v.类别 is category]
        # 台账序号参与排序：同一时刻导入两版时（测试会固定时间），以后写入台账
        # 者为新。只按时间排会撞上稳定排序，让先入库的反而排前面。
        entries.sort(key=lambda pair: (pair[1].导入时间, pair[0]), reverse=True)
        return tuple(v for _, v in entries)

    def current(self, category: Category) -> VersionInfo | None:
        """该类别最新导入的一版。

        Returns:
            最新版本；该类别尚未导入过时为 None。
        """
        versions = self.list_versions(category)
        return versions[0] if versions else None

    # ------------------------------------------------------------ 序列化

    @staticmethod
    def to_dict(knowledge: Knowledge) -> dict[str, object]:
        """Knowledge → JSON 安全的字典。

        **存 row**：Excel 路径要用它定位比较法表的行（`adapter.py` 的
        `f.row + _FACTOR_OFFSET`），丢了不会报错，只会静默读错行。row 不进
        **指纹**（它不是估价知识）——「存」与「进指纹」是两回事，见
        `fingerprint.py` 的口径说明。
        """
        return {
            "分值标尺": list(knowledge.scores),
            "因素": [
                {
                    "行号": factor.row,
                    "名称": factor.name,
                    "档次": factor.levels,
                    "系数": factor.coefficient,
                    "分组": factor.group,
                    "调整范围": factor.调整范围,
                }
                for factor in knowledge.factors
            ],
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> Knowledge:
        """由 to_dict 的输出还原。往返须无损，含 row。

        `float(f["系数"])` 顺带把手改出来的 `1` 归一成 `1.0`——否则同一份知识会因
        JSON 里的 int/float 写法不同而算出两个指纹。

        Raises:
            KeyError: 必需字段缺失。
            TypeError: 字段结构不合法（如「因素」不是列表）。
            ValueError: 字段值不合法（如行号、系数不是数）。
        """
        factors = data["因素"]
        if not isinstance(factors, list):
            raise TypeError(f"「因素」应为列表，实为 {type(factors).__name__}")
        scores = data["分值标尺"]
        if not isinstance(scores, list):
            raise TypeError(f"「分值标尺」应为列表，实为 {type(scores).__name__}")
        return Knowledge(
            factors=tuple(
                Factor(
                    row=int(f["行号"]),
                    name=str(f["名称"]),
                    levels={str(k): int(v) for k, v in dict(f["档次"]).items()},
                    coefficient=float(f["系数"]),
                    group=str(f.get("分组", "")),
                    调整范围=str(f.get("调整范围", "")),
                )
                for f in factors
            ),
            scores=tuple(int(s) for s in scores),
        )

    # ------------------------------------------------------------ 内部

    def _read_ledger(self) -> tuple[VersionInfo, ...]:
        """从后端读版本台账。

        损坏时如实抛错、不吞（后端 read_index 抛 JSONDecodeError，本处构造
        VersionInfo 时抛 KeyError/ValueError）：台账是「哪版何时从哪来」的唯一记录，
        静默当空库会让下次导入把已有版本重记一遍，等于拿错误数据盖掉事故现场。
        """
        return tuple(
            VersionInfo(
                类别=Category(str(r["类别"])),
                指纹=str(r["指纹"]),
                导入时间=datetime.fromisoformat(str(r["导入时间"])),
                来源文件名=str(r["来源文件名"]),
            )
            for r in self._backend.read_index()
        )

    def _append(self, info: VersionInfo) -> None:
        """追加一条版本台账。"""
        self._backend.append_index(
            {
                "类别": info.类别.value,
                "指纹": info.指纹,
                "导入时间": info.导入时间.isoformat(),
                "来源文件名": info.来源文件名,
            }
        )

    def _find(self, category: Category, fingerprint: str) -> VersionInfo | None:
        return next(
            (v for v in self._read_ledger() if v.类别 is category and v.指纹 == fingerprint),
            None,
        )

    @staticmethod
    def _detect_category(path: Path) -> Category:
        """判类别。

        走 `extract_survey` 而非自己再扫一遍 A1 标题：那段「找实勘表工作表 →
        读 A1 → detect_category」的逻辑已在 `survey.py` 与 `library/importer.py`
        各有一份，不该再添第三份。
        """
        category = extract_survey(path)["category"]
        if not isinstance(category, Category):
            raise ValueError(f"无法识别类别：{path}")
        return category
