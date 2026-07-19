"""问卷级校验：从 `src/validator/checks.py` 抽出「只看问卷字段、不碰比较法/Excel」
的那几条，做成纯函数。

**只提示不阻断、永不抛异常**——是否为问题、改不改，估价师定（同 validator 的契约）。
这一层刻意不依赖 `Project`/引擎/openpyxl，好让二期钉钉小程序原样移植成 JS。
"""

from src.questionnaire.model import SurveyResponse
from src.validator.checks import Warning

__all__ = ["validate_survey", "REQUIRED_BASIC_FIELDS"]

# 对齐 validator._REQUIRED_FIELDS 中不依赖比较法的那几项。
REQUIRED_BASIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("report_no", "报告编号"),
    ("client", "委托人"),
    ("owner", "权利人"),
    ("usage", "设定出租用途"),
    ("value_date", "价值时点"),
)


def _check_required(response: SurveyResponse) -> list[Warning]:
    out: list[Warning] = []
    for key, label in REQUIRED_BASIC_FIELDS:
        if not str(response.basic.get(key, "") or "").strip():
            out.append(Warning(code="MISSING_FIELD", message=f"{label}为空。"))
    return out


def _check_asset_descriptions(response: SurveyResponse) -> list[Warning]:
    out: list[Warning] = []
    for factor, desc in response.asset_conditions.items():
        if not str(desc or "").strip():
            out.append(
                Warning(
                    code="ASSET_CONDITION_INCOMPLETE",
                    message=f"{factor} 未填写描述",
                )
            )
    return out


def _check_levels(response: SurveyResponse) -> list[Warning]:
    """有描述的因素却没定档次——档次是办公端比较法的输入，缺了没法重算。"""
    out: list[Warning] = []
    for factor in response.asset_conditions:
        level = response.subject_levels.get(factor)
        if not str(level or "").strip():
            out.append(
                Warning(
                    code="LEVEL_MISSING",
                    message=f"{factor} 有描述但未定档次，办公端比较法将缺此项输入。",
                )
            )
    return out


def validate_survey(response: SurveyResponse) -> tuple[Warning, ...]:
    """校验一份问卷，返回提示元组。**永不抛、永不阻断。**"""
    warnings: list[Warning] = []
    warnings += _check_required(response)
    warnings += _check_asset_descriptions(response)
    warnings += _check_levels(response)
    return tuple(warnings)
