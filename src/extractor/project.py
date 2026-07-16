"""组装完整 Project。"""

import logging
from pathlib import Path

from src.extractor.comparison import extract_comparison, extract_subjects
from src.extractor.condition import GROUP_PREFIXES, read_survey_conditions
from src.extractor.survey import extract_survey
from src.model import Category, ConditionFactor, ConditionGroup, Project

logger = logging.getLogger(__name__)

__all__ = ["load_project"]


def _asset_condition_groups(path: Path) -> tuple[ConditionGroup, ...]:
    """从实勘表读取资产状况并按组聚合。

    按 GROUP_PREFIXES 顺序（区位→实物→权益）分组，
    组内按出现序保持，丢弃空组。

    Args:
        path: xlsx 路径。

    Returns:
        按组聚合的 ConditionGroup 元组。
    """
    conds = read_survey_conditions(path)
    ordered: dict[str, list[ConditionFactor]] = {g: [] for g in GROUP_PREFIXES}
    for c in conds:
        ordered.setdefault(c.group, []).append(ConditionFactor(c.factor, c.description))
    return tuple(
        ConditionGroup(name=g, factors=tuple(fs)) for g, fs in ordered.items() if fs
    )


def load_project(path: Path) -> Project:
    """读 xlsx → Project。

    Args:
        path: xlsx 路径。

    Returns:
        完整的 Project。

    Raises:
        ValueError: 类别无法识别或工作表缺失。
    """
    survey = extract_survey(path)
    category = survey["category"]
    assert isinstance(category, Category)
    comparison = extract_comparison(path, category)
    subjects = extract_subjects(path, category)

    return Project(
        category=category,
        report_no=str(survey["report_no"] or ""),
        project_name=str(survey["project_name"] or ""),
        client=str(survey["client"] or ""),
        client_address=str(survey["client_address"] or ""),
        legal_rep=str(survey["legal_rep"] or ""),
        purpose=str(survey["purpose"] or ""),
        survey_date=str(survey["survey_date"] or ""),
        value_date=str(survey["value_date"] or ""),
        materials=str(survey["materials"] or ""),
        certificate_status=str(survey["certificate_status"] or ""),
        owner=str(survey["owner"] or ""),
        address=str(survey["address"] or ""),
        usage=str(survey["usage"] or ""),
        scale=str(survey["scale"] or ""),
        scope=str(survey["scope"] or ""),
        current_status=str(survey["current_status"] or ""),
        work_period=str(survey["work_period"] or ""),
        issue_date=str(survey["issue_date"] or ""),
        surveyor=str(survey["surveyor"] or ""),
        unit_price=comparison["unit_price"],
        dispersion=comparison["dispersion"],
        subjects=subjects,
        asset_condition_groups=_asset_condition_groups(path),
    )
