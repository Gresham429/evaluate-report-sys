"""数据校验。

**只提示，不阻断。** 是否为问题、是否修改，由估价师判断——
系统无资格代为决定。所有检查项均源自真实素材中遇到的问题。
"""

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from src.engine.annual import annual_value
from src.model import Project

logger = logging.getLogger(__name__)

__all__ = ["Warning", "validate", "check_dispersion", "DISPERSION_THRESHOLD"]

# 比准价格离散度提示阈值。实测农用 0.01、办公 0.05、商业 0.08 均属正常。
DISPERSION_THRESHOLD = 0.20

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


def validate(project: Project, path: Path) -> tuple[Warning, ...]:
    """校验项目数据。

    Args:
        project: 项目数据。
        path: 源 xlsx 路径，用于检查外部引用。

    Returns:
        警告元组。**永不抛异常，永不阻断。**
    """
    warnings: list[Warning] = []
    warnings += _check_required(project)
    warnings += check_dispersion(project.dispersion)
    warnings += _check_table(project)
    warnings += _check_external_refs(path)
    logger.debug("校验 %s：%d 条提示", path.name, len(warnings))
    return tuple(warnings)
