"""serverless/survey_broker/record.py 行契约测试：与办公侧字节级一致。

`serverless.survey_broker.record` 是 `src.questionnaire.backend` 那份行契约的
独立副本（serverless 不能 import `src.questionnaire`，见 record.py 顶部注释）。
本测试跑在仓库测试环境里，两边都能 import——就是要在这唯一的地方把两份
"抄写"对拍，防止悄悄漂移。
"""

import json

import pytest

from serverless.survey_broker.record import (
    COL_CATEGORY,
    COL_CONTENT,
    COL_ID,
    COL_MTIME,
    COL_STATUS,
    COL_USER,
    CONTENT_KEYS,
    content_to_fields,
    fields_to_content,
    new_survey_id,
)
from src.questionnaire.backend import response_to_fields
from src.questionnaire.model import SurveyResponse


def _sample_response() -> SurveyResponse:
    return SurveyResponse(
        问卷ID="q-001",
        状态="草稿",
        填报人="张三",
        更新时间="2026-07-19T10:00:00",
        category="住宅",
        basic={"project_name": "示范项目", "client": "示范委托方"},
        subjects=({"编号": "A1", "面积": 88.5},),
        subject_levels={"区位": "好"},
        asset_conditions={"外观": "完好"},
        photos=("https://x/1.jpg",),
        gps={"lat": 30.1, "lng": 120.2},
    )


def _content_of(response: SurveyResponse) -> dict[str, object]:
    """按 `response_to_fields` 同样的取法组出 content dict，喂给 content_to_fields。"""
    return {
        "basic": dict(response.basic),
        "subjects": [dict(s) for s in response.subjects],
        "subject_levels": dict(response.subject_levels),
        "asset_conditions": dict(response.asset_conditions),
        "photos": list(response.photos),
        "gps": response.gps,
    }


def test_content_to_fields_matches_office_contract_columns_and_json() -> None:
    response = _sample_response()
    office = response_to_fields(response)
    broker = content_to_fields(
        survey_id=response.问卷ID,
        status=response.状态,
        filler=response.填报人,
        category=response.category,
        updated_at=response.更新时间,
        content=_content_of(response),
    )

    expected_columns = {COL_ID, COL_STATUS, COL_USER, COL_MTIME, COL_CATEGORY, COL_CONTENT}
    assert set(office) == expected_columns
    assert set(broker) == expected_columns
    # 列名相同前提下，同一份数据两边编码出来的 fields 应该字节级一致（含「问卷内容」JSON 字符串）。
    assert broker == office

    office_keys = tuple(json.loads(office[COL_CONTENT]).keys())
    broker_keys = tuple(json.loads(broker[COL_CONTENT]).keys())
    assert office_keys == CONTENT_KEYS
    assert broker_keys == CONTENT_KEYS


def test_content_to_fields_with_draft_status_and_no_gps() -> None:
    fields = content_to_fields(
        survey_id="q-002",
        status="草稿",
        filler="李四",
        category="工业",
        updated_at="2026-07-19T11:00:00",
        content={
            "basic": {},
            "subjects": [],
            "subject_levels": {},
            "asset_conditions": {},
            "photos": [],
            "gps": None,
        },
    )
    assert fields[COL_STATUS] == "草稿"
    parsed = json.loads(str(fields[COL_CONTENT]))
    assert parsed["gps"] is None
    assert tuple(parsed.keys()) == CONTENT_KEYS


def test_fields_to_content_round_trips() -> None:
    content = {
        "basic": {"a": "1"},
        "subjects": [{"编号": "A1"}],
        "subject_levels": {"区位": "好"},
        "asset_conditions": {"外观": "完好"},
        "photos": ["https://x/1.jpg"],
        "gps": {"lat": 1.0, "lng": 2.0},
    }
    fields = content_to_fields(
        survey_id="q-003",
        status="已提交",
        filler="王五",
        category="停车场",
        updated_at="2026-07-19T12:00:00",
        content=content,
    )
    assert fields_to_content(fields) == content


def test_fields_to_content_rejects_bad_json() -> None:
    with pytest.raises(ValueError, match="问卷内容"):
        fields_to_content({COL_CONTENT: "{not json"})


def test_fields_to_content_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="不是对象"):
        fields_to_content({COL_CONTENT: "[1, 2, 3]"})


def test_fields_to_content_missing_column_defaults_to_empty_object() -> None:
    assert fields_to_content({}) == {}


def test_new_survey_id_is_12_hex_chars_and_unique() -> None:
    a, b = new_survey_id(), new_survey_id()
    assert a != b
    assert len(a) == 12
    int(a, 16)  # 应是合法十六进制


def test_status_constants_match_across_broker_and_office() -> None:
    """四态生命周期：两侧状态常量逐一对齐。

    办公端与 serverless broker 是同一份状态机的两个抄本，任一侧改了状态值另一侧不跟，
    办公端读出来的状态就会跟 broker 写进去的对不上（审核列表拉空、只读误判）。这里把
    四个状态常量对拍，钉死漂移。
    """
    from serverless.survey_broker import record as broker
    from src.questionnaire import model as office

    assert broker.STATUS_DRAFT == office.STATUS_DRAFT == "草稿"
    assert broker.STATUS_SUBMITTED == office.STATUS_SUBMITTED == "已提交"
    assert broker.STATUS_PENDING_REVIEW == office.STATUS_PENDING_REVIEW == "待审核"
    assert broker.STATUS_FINALIZED == office.STATUS_FINALIZED == "已定稿"
