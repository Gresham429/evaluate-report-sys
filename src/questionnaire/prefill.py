"""问卷 → 办公端出报告表单预填 payload。

与 `src/web/app.py` `/api/extract` 同形状，好让办公表单一视同仁地消费。
**只搬字段、不算数。** 比较法的输出（单价/离散度/一览表价格列）是估价师办公端
选实例后才有的东西，问卷阶段没有，一律留空/0——铁律 #7，系统不替他算、不替他选。
"""

from src.extractor.field_map import SURVEY_FIELDS
from src.questionnaire.model import SurveyResponse
from src.questionnaire.validation import validate_survey

__all__ = ["survey_to_prefill"]


def _subject_row(raw: dict[str, object]) -> dict[str, object]:
    """一行估价对象：采集期已知列原样带出，价格列留 0 待估价师补。"""
    index_raw = raw.get("index", 0)
    area_raw = raw.get("area", 0.0)
    return {
        "index": int(index_raw) if isinstance(index_raw, (int, float, str)) else 0,
        "owner": str(raw.get("owner", "") or ""),
        "address": str(raw.get("address", "") or ""),
        "usage": str(raw.get("usage", "") or ""),
        "area": float(area_raw) if isinstance(area_raw, (int, float, str)) else 0.0,
        "unit_price": 0.0,
        "annual_value": 0,
    }


def survey_to_prefill(response: SurveyResponse) -> dict[str, object]:
    """把一份问卷映射成办公预填 payload。

    Args:
        response: 一份（通常「已提交」的）问卷。

    Returns:
        与 /api/extract 同形状的字典。比较法输出留空，`warnings` 由校验层回填
        （Task 3 接入前恒为空列表）。
    """
    project: dict[str, object] = {"category": response.category}
    for key in SURVEY_FIELDS:
        project[key] = response.basic.get(key, "")
    project["unit_price"] = 0.0
    project["dispersion"] = 0.0
    project["subjects"] = [_subject_row(s) for s in response.subjects]
    project["asset_condition_groups"] = []

    return {
        "project": project,
        "subject_levels": dict(response.subject_levels),
        "asset_conditions": dict(response.asset_conditions),
        "photos": list(response.photos),
        "warnings": [{"code": w.code, "message": w.message} for w in validate_survey(response)],
        "source": "questionnaire",
        "questionnaire_id": response.问卷ID,
    }
