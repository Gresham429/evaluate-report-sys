"""从 Excel 基础表提取比较法知识。

新 C1：基础表的知识（因素、档次、系数、分值）是既定正确的，系统只读不改。
用户改系数/档次/因素 → 改 Excel 基础表即生效，本模块不需改动。

实测：三类的修正系数完全不同（农用 [2,1,2,1,2,0]、办公 [1,1,2,2,1,3]、
商业 [2,2,2,0,1,2]），故必须按上传的 Excel 逐份读取，不存在全公司主表。
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import openpyxl

logger = logging.getLogger(__name__)

__all__ = ["Factor", "Knowledge", "extract_knowledge", "BASE_SHEET"]

BASE_SHEET = "比较因素条件说明表（基础表）"

_FIRST_FACTOR_ROW = 3
_LAST_FACTOR_ROW = 30
_SCORE_ROW = 31          # 分值标尺行：D..H = 2/1/0/-1/-2
_LEVEL_COLS = range(4, 9)  # D..H
_COEFF_COL = 9           # I 列：每差 1 档修正系数
_NAME_COLS = (3, 2)      # C 列优先（因素名），退到 B 列（分组名）


@dataclass(frozen=True)
class Factor:
    """一个比较因素。"""

    row: int
    name: str
    levels: dict[str, int]
    coefficient: float


@dataclass(frozen=True)
class Knowledge:
    """一份基础表承载的全部比较法知识。"""

    factors: tuple[Factor, ...]
    scores: tuple[int, ...]


def _cell_text(sheet: object, row: int, col: int) -> str:
    value = sheet.cell(row, col).value  # type: ignore[attr-defined]
    return str(value).strip() if value is not None else ""


def extract_knowledge(path: Path) -> Knowledge:
    """读 Excel 基础表 → 比较法知识。

    Args:
        path: 实勘表 Excel 路径（内含基础表工作表）。

    Returns:
        Knowledge。因素按基础表行序排列，空行跳过。

    Raises:
        ValueError: 基础表缺失，或分值行不是 5 个整数。
    """
    workbook = openpyxl.load_workbook(path, data_only=True)
    if BASE_SHEET not in workbook.sheetnames:
        raise ValueError(f"工作簿缺少基础表 {BASE_SHEET!r}：{path}")
    sheet = workbook[BASE_SHEET]

    raw_scores = [sheet.cell(_SCORE_ROW, col).value for col in _LEVEL_COLS]
    if not all(isinstance(s, int) for s in raw_scores) or len(raw_scores) != 5:
        raise ValueError(
            f"基础表第 {_SCORE_ROW} 行应为 5 个整数分值，实为 {raw_scores!r}：{path}"
        )
    scores = tuple(int(s) for s in raw_scores)  # type: ignore[arg-type]

    factors: list[Factor] = []
    for row in range(_FIRST_FACTOR_ROW, _LAST_FACTOR_ROW + 1):
        name = next((t for c in _NAME_COLS if (t := _cell_text(sheet, row, c))), "")
        levels = {
            text: scores[i]
            for i, col in enumerate(_LEVEL_COLS)
            if (text := _cell_text(sheet, row, col))
        }
        if not name:
            # 无因素名的行不是真实因素——实测农用基础表第 23 行即为例证：
            # B/C 列均为空，但 D..H 遗留了与表头行（第 2 行）相同的通用占位文本
            # "好/较好/一般/较差/差"，系数为 0，属模板残留而非真实评估因素。
            continue
        coeff = sheet.cell(row, _COEFF_COL).value
        factors.append(
            Factor(
                row=row,
                name=name,
                levels=levels,
                coefficient=float(coeff) if isinstance(coeff, (int, float)) else 0.0,
            )
        )
    logger.debug("提取基础表 %s：%d 个因素", path.name, len(factors))
    return Knowledge(factors=tuple(factors), scores=scores)
