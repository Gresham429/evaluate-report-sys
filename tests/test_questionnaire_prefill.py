"""问卷 → 办公预填 payload：形状对齐 /api/extract，比较法输出留空待补。"""

from src.extractor.field_map import SURVEY_FIELDS
from src.questionnaire.model import STATUS_SUBMITTED, SurveyResponse
from src.questionnaire.prefill import survey_to_prefill


def _resp() -> SurveyResponse:
    return SurveyResponse(
        问卷ID="q-9",
        状态=STATUS_SUBMITTED,
        填报人="u1",
        更新时间="2026-07-19T10:00:00",
        category="办公",
        basic={"report_no": "R-1", "client": "甲", "owner": "乙", "usage": "办公",
               "value_date": "2026-04-20"},
        subjects=({"index": 1, "owner": "乙", "address": "A 路 1 号",
                   "usage": "办公", "area": 100.0},),
        subject_levels={"楼层": "中", "临街状况": "优"},
        asset_conditions={"楼层": "6/20", "临街状况": "临主干道"},
        photos=("p1.jpg", "p2.jpg"),
    )


def test_project_has_all_19_basic_keys_and_category() -> None:
    out = survey_to_prefill(_resp())
    project = out["project"]
    assert isinstance(project, dict)
    assert project["category"] == "办公"
    for key in SURVEY_FIELDS:
        assert key in project, f"缺基本字段 {key}"
    assert project["client"] == "甲"
    assert project["report_no"] == "R-1"
    # 未填的基本字段给空串，不丢键
    assert project["legal_rep"] == ""


def test_comparison_outputs_are_empty_for_appraiser() -> None:
    out = survey_to_prefill(_resp())
    project = out["project"]
    assert project["unit_price"] == 0.0
    assert project["dispersion"] == 0.0
    assert project["asset_condition_groups"] == []
    subj = project["subjects"][0]
    assert subj["unit_price"] == 0.0
    assert subj["annual_value"] == 0
    # 采集期已知列原样带出
    assert subj["owner"] == "乙"
    assert subj["area"] == 100.0
    assert subj["index"] == 1


def test_levels_conditions_photos_passthrough() -> None:
    out = survey_to_prefill(_resp())
    assert out["subject_levels"] == {"楼层": "中", "临街状况": "优"}
    assert out["asset_conditions"] == {"楼层": "6/20", "临街状况": "临主干道"}
    assert out["photos"] == ["p1.jpg", "p2.jpg"]
    assert out["source"] == "questionnaire"
    assert out["questionnaire_id"] == "q-9"
    assert out["warnings"] == []


def test_unit_labels_match_extract_contract() -> None:
    # 与 /api/extract 同形状：界面据 单价单位/面积单位 标一览表表头。办公=房屋类。
    out = survey_to_prefill(_resp())
    assert out["单价单位"] == "元/㎡·天"
    assert out["面积单位"] == "㎡"


def test_unit_labels_empty_on_bad_category() -> None:
    # 类别非法（草稿未填全）时退化空串，不炸预填。
    import dataclasses

    out = survey_to_prefill(dataclasses.replace(_resp(), category="不存在的类别"))
    assert out["单价单位"] == ""
    assert out["面积单位"] == ""
