"""docx 渲染。

用 docxtpl：模板本身就是 .docx，样式、表格、页面设置原样保留。
运行时不调用 AI（约束 C2）——同一输入永远产出同一输出。
"""

import logging
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from src.attachments.collector import AttachmentPage
from src.model import Category, Project
from src.paths import templates_dir
from src.prose.capital import to_capital
from src.prose.composer import compose

logger = logging.getLogger(__name__)

__all__ = [
    "build_context",
    "render",
    "DEFAULT_TEMPLATES_DIR",
    "TEMPLATE_FILENAMES",
    "ATTACHMENT_WIDTH_MM",
]

DEFAULT_TEMPLATES_DIR = templates_dir()
ATTACHMENT_WIDTH_MM = 160

# 模板文件名一律 ASCII，且与类别标识**解耦**。
#
# 类别本身（Category 的值：农用/办公/商业）是数据模型身份，遍布 JSON payload、
# 台账快照、基础表键，绝不能动。但若直接拿它当文件名（`农用.docx`），交付 zip
# 一经第三方中文解压软件（WinRAR/360/好压/2345）按 GBK 解码，就变成乱码
# `鍐滅敤.docx`——render() 按原中文名再也找不到，一份报告也出不来。
#
# 这与项目栽过的两跤同类：Release 资产名中文被 GitHub 删空、中文不能做 HTTP 路径
# 参数。凡随包发出、要被机器按名字找的标识，一律 ASCII。故此处把「文件名」从
# 「类别值」独立出来，单独取 ASCII 名。
TEMPLATE_FILENAMES: dict[Category, str] = {
    Category.AGRICULTURAL: "farmland.docx",
    Category.OFFICE: "office.docx",
    Category.COMMERCIAL: "commercial.docx",
}


def _validity_end_cn(issue_date: str) -> str:
    """报告使用有效期的截止日 = 出具日期 + 1 年 - 1 天，中文格式。

    金样原文：「使用有效期限为从本报告出具之日起一年（2026年4月27日至
    2027年4月26日止）」—— 截止日是次年同月同日的前一天，不是同一天。
    该日期 Excel 里没有，须推算。

    Args:
        issue_date: 出具日期，ISO 格式（YYYY-MM-DD）。

    Returns:
        中文格式的截止日，如「2027年4月26日」。出具日期为空或不可解析时返回空串。
    """
    try:
        issued = date.fromisoformat(issue_date)
    except (ValueError, TypeError):
        logger.warning("出具日期 %r 不可解析，无法推算有效期截止日", issue_date)
        return ""
    try:
        anniversary = issued.replace(year=issued.year + 1)
    except ValueError:
        # 2月29日出具：次年无该日，取2月28日
        anniversary = issued.replace(year=issued.year + 1, day=28)
    end = anniversary - timedelta(days=1)
    return f"{end.year}年{end.month}月{end.day}日"


def _fmt(value: float) -> str:
    """数值 → 展示字符串。≥1000 加千分位，小数位原样保留。

    估价报告里的金额与面积须加千分位以防看错位数（如 368030 误读成
    36803 或 3680300）。整数值不补小数位——若与金样的小数写法（如
    50.00）不一致，是已知的、经确认的格式改进，不做特殊处理。

    Args:
        value: 待格式化的数值。

    Returns:
        千分位格式化后的字符串。
    """
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,}"


def _date_cn(iso_date: str) -> str:
    """ISO 日期字符串（YYYY-MM-DD）→ 中文日期，月、日不补零。

    如 "2026-03-26" → "2026年3月26日"，与金样原文的写法一致。

    Args:
        iso_date: `extract_survey()` 归一化后的 ISO 日期字符串。

    Returns:
        中文日期字符串；输入为空时返回空字符串。
    """
    if not iso_date:
        return ""
    year, month, day = iso_date.split("-")
    return f"{int(year)}年{int(month)}月{int(day)}日"


def _subjects_narrative(project: Project) -> str:
    """按估价对象逐一枚举、多对象再追加合计的叙述句。

    结构随对象个数变，不能写死：农用类每个片段用"土地使用权面积…亩"，
    其余类别用"房屋建筑面积…平方米"；对象数 > 1 时末尾追加"共计…"，
    单个对象不加（金样农用卷只有 1 个对象，原文本就没有"共计"半句）。

    Args:
        project: 项目数据。

    Returns:
        叙述句字符串，供 {{ subjects_narrative }} 使用。
    """
    unit = "亩" if project.is_land else "平方米"
    label = "土地使用权面积" if project.is_land else "房屋建筑面积"
    fragments = [f"{s.address}{label}{_fmt(s.area)}{unit}" for s in project.subjects]
    narrative = "，".join(fragments)
    if len(project.subjects) > 1:
        total_area = _fmt(sum(s.area for s in project.subjects))
        narrative += f"，共计{label}{total_area}{unit}"
    return narrative


def build_context(project: Project, pages: Sequence[AttachmentPage]) -> dict[str, object]:
    """组装渲染上下文。

    Args:
        project: 项目数据。
        pages: 附件图片页，空表示无附件。

    Returns:
        供 docxtpl 渲染的上下文字典。
    """
    total_value = sum(s.annual_value for s in project.subjects)
    context: dict[str, object] = {
        "report_no": project.report_no,
        "project_name": project.project_name,
        "client": project.client,
        "client_address": project.client_address,
        "legal_rep": project.legal_rep,
        "purpose": project.purpose,
        "survey_date": project.survey_date,
        "value_date": project.value_date,
        "value_date_cn": _date_cn(project.value_date),
        "materials": project.materials,
        "owner": project.owner,
        "address": project.address,
        "usage": project.usage,
        "scale": project.scale,
        "current_status": project.current_status,
        "work_period": project.work_period,
        "issue_date": project.issue_date,
        "issue_date_cn": _date_cn(project.issue_date),
        "validity_end_cn": _validity_end_cn(project.issue_date),
        "unit_price": project.unit_price,
        "dispersion": project.dispersion,
        "subjects": [
            {
                "index": s.index,
                "owner": s.owner,
                "address": s.address,
                "usage": s.usage,
                "area": _fmt(s.area),
                "unit_price": _fmt(s.unit_price),
                "annual_value": _fmt(s.annual_value),
            }
            for s in project.subjects
        ],
        "total_area": _fmt(sum(s.area for s in project.subjects)),
        "total_value": _fmt(total_value),
        "total_value_capital": to_capital(total_value),
        "subjects_narrative": _subjects_narrative(project),
        "has_attachments": len(pages) > 0,
    }
    context["区位因素"] = []
    context["实物因素"] = []
    context["权益因素"] = []
    group_keys = {"区位状况": "区位因素", "实物状况": "实物因素", "权益状况": "权益因素"}
    for group in project.asset_condition_groups:
        key = group_keys.get(group.name)
        if key is None:
            continue
        context[key] = [{"name": f.name, "description": f.description} for f in group.factors]
    context.update(compose(project))
    return context


def render(
    project: Project,
    pages: Sequence[AttachmentPage],
    output: Path,
    templates_dir: Path | None = None,
) -> Path:
    """渲染报告。

    Args:
        project: 项目数据。
        pages: 附件图片页，按用户排定的顺序。
        output: 输出 docx 路径。
        templates_dir: 模板目录，默认取仓库内 templates/。

    Returns:
        输出路径。

    Raises:
        FileNotFoundError: 模板不存在。
    """
    directory = templates_dir or DEFAULT_TEMPLATES_DIR
    template_path = directory / TEMPLATE_FILENAMES[project.category]
    if not template_path.exists():
        raise FileNotFoundError(f"模板不存在：{template_path}")

    document = DocxTemplate(template_path)
    context = build_context(project, pages)
    context["attachment_images"] = [
        InlineImage(document, str(p.image_path), width=Mm(ATTACHMENT_WIDTH_MM)) for p in pages
    ]
    document.render(context)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    logger.info(
        "已生成报告 %s（%d 个估价对象，%d 页附件）", output.name, len(project.subjects), len(pages)
    )
    return output
