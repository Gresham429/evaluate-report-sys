"""项目数据模型。

所有数值均来自 Excel 的计算缓存值，系统不重算（约束 C1）。
"""

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["Category", "Subject", "Project"]


class Category(StrEnum):
    """估价对象类别。"""

    AGRICULTURAL = "农用"
    OFFICE = "办公"
    COMMERCIAL = "商业"


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

    @property
    def is_land(self) -> bool:
        """农用地类别。影响单位（亩/㎡）与估价范围措辞。"""
        return self.category is Category.AGRICULTURAL

    @property
    def has_certificate(self) -> bool:
        """是否已取得《不动产权证》。驱动正文与附件清单两处条件文本。"""
        return "已取得" in self.certificate_status
