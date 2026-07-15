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

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.engine.knowledge import Factor, Knowledge, extract_knowledge
from src.extractor.survey import extract_survey
from src.knowledge_base.fingerprint import fingerprint
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["BaseTableStore", "VersionInfo", "ImportResult", "DEFAULT_STORE_DIR", "LEDGER_NAME"]

DEFAULT_STORE_DIR = Path(__file__).resolve().parents[2] / "data" / "基础表"
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

    def __init__(self, path: Path = DEFAULT_STORE_DIR) -> None:
        self.path = path

    # ------------------------------------------------------------ 对外

    def import_from_excel(self, path: Path, now: datetime | None = None) -> ImportResult:
        """导入一份 Excel 的基础表。

        Args:
            path: 实勘表 Excel 路径（内含基础表工作表）。
            now: 导入时间。默认取当前时间；须可注入，否则测试无从固定时间。

        Returns:
            ImportResult。指纹已在库中时 `是否新版=False`，且不重写任何文件。

        Raises:
            ValueError: 基础表缺失、分值行不合法，或 A1 标题无法识别类别。
        """
        knowledge = extract_knowledge(path)
        category = self._detect_category(path)
        digest = fingerprint(knowledge)

        existing = self._find(category, digest)
        if existing is not None:
            # 内容没变就什么都不做：不重写文件（不可变），不重复记台账，
            # 也不改写首次导入时间——那个时间是「这版何时进的库」的事实。
            logger.info("基础表 %s 指纹 %s 已在库中，未新增版本", category.value, digest)
            return ImportResult(版本=existing, 是否新版=False)

        info = VersionInfo(
            类别=category,
            指纹=digest,
            导入时间=now if now is not None else datetime.now(),
            来源文件名=path.name,
        )
        target = self._version_path(category, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 文件已在、台账却无记录（人工拷入、或台账损坏重建）时，只补台账不动文件：
        # 落了盘的版本一律不可变。同指纹即同内容，重写它也只会写出一模一样的字节，
        # 徒然给「旧版本永不覆盖」开一道口子。
        if not target.exists():
            target.write_text(
                json.dumps(self.to_dict(knowledge), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        self._append(info)
        logger.info(
            "导入基础表 %s → %s（%d 个因素，来源 %s）",
            category.value,
            target.name,
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
        """
        if fingerprint is None:
            latest = self.current(category)
            if latest is None:
                raise FileNotFoundError(
                    f"尚未导入过 {category.value} 类基础表：{self.path}"
                )
            fingerprint = latest.指纹

        target = self._version_path(category, fingerprint)
        if not target.exists():
            raise FileNotFoundError(
                f"{category.value} 类基础表无版本 {fingerprint}：{target}"
            )
        return self.from_dict(json.loads(target.read_text(encoding="utf-8")))

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
                }
                for factor in knowledge.factors
            ],
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> Knowledge:
        """由 to_dict 的输出还原。往返须无损，含 row。

        Raises:
            KeyError: 必需字段缺失。
            TypeError: 字段结构不合法。
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
                )
                for f in factors
            ),
            scores=tuple(int(s) for s in scores),
        )

    # ------------------------------------------------------------ 内部

    def _version_path(self, category: Category, fingerprint: str) -> Path:
        return self.path / f"{category.value}-{fingerprint}.json"

    def _ledger_path(self) -> Path:
        return self.path / LEDGER_NAME

    def _read_ledger(self) -> tuple[VersionInfo, ...]:
        """读台账。文件不存在时视为空库——首次运行时它本就不存在。"""
        path = self._ledger_path()
        if not path.exists():
            logger.debug("基础表台账不存在，视为空库：%s", path)
            return ()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            VersionInfo(
                类别=Category(str(r["类别"])),
                指纹=str(r["指纹"]),
                导入时间=datetime.fromisoformat(str(r["导入时间"])),
                来源文件名=str(r["来源文件名"]),
            )
            for r in raw
        )

    def _append(self, info: VersionInfo) -> None:
        """追加一条台账。UTF-8、缩进、不转义中文——须人类可读可手改。"""
        entries = [*self._read_ledger(), info]
        payload = [
            {
                "类别": e.类别.value,
                "指纹": e.指纹,
                "导入时间": e.导入时间.isoformat(),
                "来源文件名": e.来源文件名,
            }
            for e in entries
        ]
        self._ledger_path().parent.mkdir(parents=True, exist_ok=True)
        self._ledger_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
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
