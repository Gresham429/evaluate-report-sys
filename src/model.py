"""项目数据模型。

所有数值均来自 Excel 的计算缓存值，系统不重算（约束 C1）。
"""

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Category", "Subject", "ConditionFactor", "ConditionGroup", "Project"]


class Category(StrEnum):
    """估价对象类别。值为中文，是数据身份，遍布 JSON/台账，不可改（见 §5 坑 7）。"""

    AGRICULTURAL = "农用"
    OFFICE = "办公"
    COMMERCIAL = "商业"
    RESIDENTIAL = "住宅"
    INDUSTRIAL = "工业"
    PARKING_LAND = "停车场用地"
    CONSTRUCTION_LAND = "建设用地"


# land 口径的唯一来源：土地类按亩/年计租、报告用「土地」措辞。房屋类按㎡/天×365。
# annual_value 与 is_land 都从这里取，杜绝双实现漂移。
_LAND_CATEGORIES = frozenset(
    {Category.AGRICULTURAL, Category.PARKING_LAND, Category.CONSTRUCTION_LAND}
)


@dataclass(frozen=True)
class Subject:
    """估价结果一览表中的单个估价对象。

    数值直接来自 Excel，不重算。
    """

    index: int
    owner: str
    address: str
    usage: str
    area: float
    unit_price: float
    annual_value: int


@dataclass(frozen=True)
class ConditionFactor:
    """资产状况里一个因素的一行：手写描述 + 因素名。

    描述是估价师逐因素手写的依据（实勘表 D 列），进报告、不进算术。
    """

    name: str
    description: str


@dataclass(frozen=True)
class ConditionGroup:
    """资产状况的一组（区位状况 / 实物状况 / 权益状况）及其逐因素行。"""

    name: str
    factors: tuple[ConditionFactor, ...]


@dataclass(frozen=True)
class Project:
    """一个估价项目的全部数据。"""

    category: Category
    report_no: str
    project_name: str
    client: str
    client_address: str
    legal_rep: str
    purpose: str
    survey_date: str
    value_date: str
    materials: str
    certificate_status: str
    owner: str
    address: str
    usage: str
    scale: str
    scope: str
    current_status: str
    work_period: str
    issue_date: str
    surveyor: str
    unit_price: float
    dispersion: float
    subjects: tuple[Subject, ...]
    # 报告（三）估价对象资产状况的三张表数据。默认空 → 既有构造点不受影响；
    # 由 web 层/load_project 用基础表分组组装后填入。描述只进报告、不进算术。
    asset_condition_groups: tuple[ConditionGroup, ...] = ()

    @property
    def is_land(self) -> bool:
        """土地类（农用/停车场用地/建设用地）。影响单位（亩/㎡）与估价范围措辞。"""
        return self.category in _LAND_CATEGORIES

    @property
    def has_certificate(self) -> bool:
        """是否已取得《不动产权证》。驱动正文与附件清单两处条件文本。"""
        return "已取得" in self.certificate_status
