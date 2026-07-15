"""docx 渲染。

用 docxtpl：模板本身就是 .docx，样式、表格、页面设置原样保留。
运行时不调用 AI（约束 C2）——同一输入永远产出同一输出。
"""

import logging
from collections.abc import Sequence
from pathlib import Path

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from src.attachments.collector import AttachmentPage
from src.model import Project
from src.prose.composer import compose

logger = logging.getLogger(__name__)

__all__ = ["build_context", "render", "DEFAULT_TEMPLATES_DIR", "ATTACHMENT_WIDTH_MM"]

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
ATTACHMENT_WIDTH_MM = 160


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


def build_context(project: Project, pages: Sequence[AttachmentPage]) -> dict[str, object]:
    """组装渲染上下文。

    Args:
        project: 项目数据。
        pages: 附件图片页，空表示无附件。

    Returns:
        供 docxtpl 渲染的上下文字典。
    """
    context: dict[str, object] = {
        "report_no": project.report_no,
        "project_name": project.project_name,
        "client": project.client,
        "client_address": project.client_address,
        "legal_rep": project.legal_rep,
        "purpose": project.purpose,
        "survey_date": project.survey_date,
        "value_date": project.value_date,
        "materials": project.materials,
        "owner": project.owner,
        "address": project.address,
        "usage": project.usage,
        "scale": project.scale,
        "current_status": project.current_status,
        "work_period": project.work_period,
        "issue_date": project.issue_date,
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
        "total_value": _fmt(sum(s.annual_value for s in project.subjects)),
        "has_attachments": len(pages) > 0,
    }
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
    template_path = directory / f"{project.category.value}.docx"
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
