"""数据校验。

**只提示，不阻断。** 是否为问题、是否修改，由估价师判断——
系统无资格代为决定。所有检查项均源自真实素材中遇到的问题。
"""

import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from src.engine.annual import annual_value
from src.model import Project
from src.prose.composer import area_unit

logger = logging.getLogger(__name__)

__all__ = ["Warning", "validate", "check_dispersion", "DISPERSION_THRESHOLD"]

# 比准价格离散度提示阈值。实测农用 0.01、办公 0.05、商业 0.08 均属正常。
DISPERSION_THRESHOLD = 0.20

# 面积比对容差。一览表面积实测两位小数，0.01 足够吸收浮点误差而不放过真错。
_AREA_TOLERANCE = 0.01

# 规模字段里「数字 + 单位」的写法。实测三份金样：
#   农用「土地使用权面积50.00亩」
#   办公「房屋建筑面积723.69平方米及其分摊的土地使用权」
#   商业「义蓬中路477号房屋建筑面积60平方米、487号房屋建筑面积70平方米及其分摊的土地使用权」
# 房屋类兼收「平方米」与「㎡」两种写法：报告里印「㎡」，而估价师在规模字段
# 里手写的是「平方米」，两种都得认，否则换个写法就静默失效。
_AREA_UNIT_PATTERN = {"亩": r"亩", "㎡": r"(?:平方米|㎡)"}
_AREA_IN_TEXT = r"(\d+(?:\.\d+)?)\s*{unit}"

_REQUIRED_FIELDS = (
    ("report_no", "报告编号"),
    ("client", "委托人"),
    ("owner", "权利人"),
    ("usage", "设定出租用途"),
    ("value_date", "价值时点"),
)


@dataclass(frozen=True)
class Warning:
    """一条校验提示。"""

    code: str
    message: str


def check_dispersion(dispersion: float) -> tuple[Warning, ...]:
    """离散度是否偏高。

    取值可能来自 Excel（读进来时校验），也可能来自换实例后的重算——重算出的
    离散度同样要过这一关，否则「选了三条不可比的实例」这件事在最该被看见的
    时刻（选实例时）反而没人提。故本函数按数值收参，不绑 Project。

    Args:
        dispersion: 比准价格离散度。

    Returns:
        提示元组，正常时为空。
    """
    if dispersion > DISPERSION_THRESHOLD:
        return (
            Warning(
                code="DISPERSION_HIGH",
                message=(
                    f"比准价格离散度 {dispersion:.0%} 超过 "
                    f"{DISPERSION_THRESHOLD:.0%}，建议复核可比实例的选取。"
                ),
            ),
        )
    return ()


def _check_required(project: Project) -> list[Warning]:
    warnings: list[Warning] = []
    for field, label in _REQUIRED_FIELDS:
        if not str(getattr(project, field) or "").strip():
            warnings.append(Warning(code="MISSING_FIELD", message=f"{label}为空。"))
    return warnings


def _check_table(project: Project) -> list[Warning]:
    """一览表自洽性：年租赁价值须与单价×面积对得上。

    公式取自 `src.engine.annual`——与界面改单价后的重算共用同一份实现，
    免得校验器与重算各算各的。此处仅比对，不修正：是否为问题、怎么改，
    由估价师判断。
    """
    warnings: list[Warning] = []
    for subject in project.subjects:
        expected = annual_value(project.category, subject.area, subject.unit_price)
        if abs(expected - subject.annual_value) > 1:
            warnings.append(
                Warning(
                    code="TABLE_INCONSISTENT",
                    message=(
                        f"第 {subject.index} 项「{subject.address}」年租赁价值 "
                        f"{subject.annual_value:,} 与按单价×面积算得的 {expected:,.0f} 不符，"
                        f"请复核是否改了单价未重算。"
                    ),
                )
            )
    return warnings


def _check_scale(project: Project) -> list[Warning]:
    """规模字段写的面积，与一览表面积合计是否对得上。

    **不替他填，但替他核。** 19 项基本字段全部人工填、系统不拼凑（用户明确
    要求：「不拼凑 实地勘察去填写」——拼凑出的文字进了报告是要签字的，责任
    不清）。但手填就会手滑，把 723.69 打成 732.69，报告里就有两个互相打架的
    数。系统无权替他改，可以替他看一眼。

    比对口径要能容下三份金样的三种写法：

        农用  「土地使用权面积50.00亩」                    → [50]    单个数即合计
        办公  「房屋建筑面积723.69平方米及其分摊…」         → [723.69] 单个数即合计
        商业  「…477号房屋建筑面积60平方米、487号…70平方米」 → [60,70]  逐对象列，合计从没写出来

    故「任一个数等于合计」或「诸数之和等于合计」都算对得上。只认前者会把
    商业那种写法一律误报——一个总在喊狼来了的提示，比没有提示更糟。

    找不到任何按该类别单位计的数时**不提示**：可能是没填，也可能是换了种
    写法，系统没有把握就不吭声。
    """
    unit = area_unit(project.category)
    pattern = _AREA_IN_TEXT.format(unit=_AREA_UNIT_PATTERN[unit])
    found = [float(m) for m in re.findall(pattern, project.scale or "")]
    if not found:
        return []

    total = sum(s.area for s in project.subjects)
    if any(abs(n - total) < _AREA_TOLERANCE for n in found):
        return []
    if abs(sum(found) - total) < _AREA_TOLERANCE:
        return []
    return [
        Warning(
            code="SCALE_MISMATCH",
            message=(
                f"规模字段写的 {'、'.join(f'{n:g}' for n in found)} "
                f"{'平方米' if unit == '㎡' else unit}，"
                f"与一览表面积合计 {total:g} 不符，请复核。"
            ),
        )
    ]


def _check_external_refs(path: Path) -> list[Warning]:
    """检测工作簿是否引用外部文件。

    办公表 I33 引用 /Users/admin/Desktop/... 是他人机器的绝对路径。
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            rels = [n for n in names if "externalLink" in n and n.endswith(".rels")]
            targets: list[str] = []
            for rel in rels:
                content = archive.read(rel).decode("utf-8", errors="replace")
                targets += [
                    part.split('"')[0]
                    for part in content.split('Target="')[1:]
                ]
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        logger.warning("无法检查外部引用 %s：%s", path, exc)
        return []
    if targets:
        return [
            Warning(
                code="EXTERNAL_REF",
                message=(
                    f"工作簿引用了外部文件：{'、'.join(targets)}。"
                    f"若该文件不存在，相关单元格读到的是历史缓存值。"
                ),
            )
        ]
    return []


def validate(project: Project, path: Path | None = None) -> tuple[Warning, ...]:
    """校验项目数据。

    Args:
        project: 项目数据。
        path: 源 xlsx 路径，用于检查外部引用。**表单路径没有源文件，传 None
            即跳过这一项**——其余各项与数据从哪来无关，一律照查。

    Returns:
        警告元组。**永不抛异常，永不阻断。**
    """
    warnings: list[Warning] = []
    warnings += _check_required(project)
    warnings += check_dispersion(project.dispersion)
    warnings += _check_table(project)
    warnings += _check_scale(project)
    if path is not None:
        warnings += _check_external_refs(path)
    logger.debug("校验 %s：%d 条提示", path.name if path else "表单", len(warnings))
    return tuple(warnings)
