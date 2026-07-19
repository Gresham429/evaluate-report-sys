"""问卷级校验：只提示不阻断，覆盖必填缺失/描述空/档次缺。"""

from src.questionnaire.model import STATUS_SUBMITTED, SurveyResponse
from src.questionnaire.prefill import survey_to_prefill
from src.questionnaire.validation import validate_survey


def _resp(**over: object) -> SurveyResponse:
    base = dict(
        问卷ID="q",
        状态=STATUS_SUBMITTED,
        填报人="u",
        更新时间="t",
        category="办公",
        basic={"report_no": "R", "client": "甲", "owner": "乙",
               "usage": "办公", "value_date": "2026-04-20"},
        subjects=(),
        subject_levels={"楼层": "中"},
        asset_conditions={"楼层": "6/20"},
        photos=(),
    )
    base.update(over)
    return SurveyResponse(**base)  # type: ignore[arg-type]


def test_clean_response_no_warnings() -> None:
    assert validate_survey(_resp()) == ()


def test_missing_required_field_warns() -> None:
    codes = {w.code for w in validate_survey(_resp(basic={"client": "甲"}))}
    assert "MISSING_FIELD" in codes


def test_empty_asset_description_warns() -> None:
    ws = validate_survey(_resp(asset_conditions={"楼层": ""}))
    assert any(w.code == "ASSET_CONDITION_INCOMPLETE" for w in ws)


def test_condition_without_level_warns() -> None:
    # 有描述的因素「临街」没有对应档次
    ws = validate_survey(_resp(
        asset_conditions={"楼层": "6/20", "临街": "临主干道"},
        subject_levels={"楼层": "中"},
    ))
    assert any(w.code == "LEVEL_MISSING" for w in ws)


def test_validate_never_raises_on_weird_input() -> None:
    # 空 basic、空一切：不抛，返回若干提示
    ws = validate_survey(_resp(basic={}, asset_conditions={}, subject_levels={}))
    assert isinstance(ws, tuple)


def test_prefill_backfills_warnings() -> None:
    out = survey_to_prefill(_resp(basic={"client": "甲"}))
    warns = out["warnings"]
    assert isinstance(warns, list)
    assert any(w["code"] == "MISSING_FIELD" for w in warns)
