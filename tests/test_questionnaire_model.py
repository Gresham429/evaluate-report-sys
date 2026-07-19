"""问卷数据模型：字段身份、摘要抽取、基本字段键与实勘表对齐。"""

from src.extractor.field_map import SURVEY_FIELDS
from src.questionnaire.model import (
    STATUS_DRAFT,
    STATUS_SUBMITTED,
    SurveyInfo,
    SurveyResponse,
    known_basic_keys,
)


def _sample() -> SurveyResponse:
    return SurveyResponse(
        问卷ID="q-001",
        状态=STATUS_SUBMITTED,
        填报人="user-42",
        更新时间="2026-07-19T10:00:00",
        category="办公",
        basic={"report_no": "浙杭xx", "client": "某公司"},
        subjects=({"index": 1, "owner": "张三", "address": "A 路 1 号",
                   "usage": "办公", "area": 100.0},),
        subject_levels={"临街状况": "优", "楼层": "中"},
        asset_conditions={"临街状况": "临主干道", "楼层": "6/20"},
        photos=("https://drive/p1.jpg",),
        gps={"lat": 30.1, "lng": 120.2},
    )


def test_status_constants() -> None:
    assert STATUS_DRAFT == "草稿"
    assert STATUS_SUBMITTED == "已提交"


def test_known_basic_keys_match_survey_fields() -> None:
    assert known_basic_keys() == frozenset(SURVEY_FIELDS)


def test_info_drops_heavy_fields() -> None:
    info = _sample().info()
    assert info == SurveyInfo(
        问卷ID="q-001", 填报人="user-42", category="办公",
        更新时间="2026-07-19T10:00:00",
    )


def test_response_is_frozen() -> None:
    import dataclasses

    resp = _sample()
    try:
        resp.状态 = STATUS_DRAFT  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("SurveyResponse 应为 frozen")
