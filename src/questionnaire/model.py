"""问卷数据模型。

`SurveyResponse` 是一份实勘问卷的权威快照：估价师现场（或跨设备续填）录入的
基本信息、逐因素档次、资产状况描述、照片与 GPS。办公侧只读它，不改。

基本字段键刻意复用 `SURVEY_FIELDS`（实勘表那 19 项）——问卷采的就是实勘表，
两处用同一套键名，映射到办公 payload 时零翻译、日后加字段只改一处。
"""

from dataclasses import dataclass

from src.extractor.field_map import SURVEY_FIELDS

__all__ = [
    "STATUS_DRAFT",
    "STATUS_FINALIZED",
    "STATUS_PENDING_REVIEW",
    "STATUS_SUBMITTED",
    "SurveyInfo",
    "SurveyResponse",
    "known_basic_keys",
]

STATUS_DRAFT = "草稿"
STATUS_SUBMITTED = "已提交"
STATUS_PENDING_REVIEW = "待审核"  # 办公端「发起审核」后：已提交 → 待审核
STATUS_FINALIZED = "已定稿"  # 办公端「审核通过」后：待审核 → 已定稿（终态·锁定）


def known_basic_keys() -> frozenset[str]:
    """问卷基本字段的合法键集合，等同实勘表 19 项。"""
    return frozenset(SURVEY_FIELDS)


@dataclass(frozen=True)
class SurveyInfo:
    """问卷摘要，供办公端「已提交」列表展示。不含大字段。"""

    问卷ID: str
    填报人: str
    category: str
    更新时间: str


@dataclass(frozen=True)
class SurveyResponse:
    """一份实勘问卷的完整数据。办公侧只读。"""

    问卷ID: str
    状态: str
    填报人: str
    更新时间: str
    category: str
    basic: dict[str, str]
    subjects: tuple[dict[str, object], ...]
    subject_levels: dict[str, str]
    asset_conditions: dict[str, str]
    photos: tuple[str, ...]
    gps: dict[str, float] | None = None
    共有人: tuple[str, ...] = ()  # 全体持有者 userid（含填报人）；空=旧数据，读取时兜底 [填报人]

    def info(self) -> SurveyInfo:
        """取摘要（丢掉 basic/subjects/照片等大字段）。"""
        return SurveyInfo(
            问卷ID=self.问卷ID,
            填报人=self.填报人,
            category=self.category,
            更新时间=self.更新时间,
        )
