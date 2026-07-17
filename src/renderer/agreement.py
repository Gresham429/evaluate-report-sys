"""委托评估协议书渲染。四类通用，与估价报告解耦。

模板 `templates/entrustment_agreement.docx` 由公司《委托评估协议书模板.docx》
一次性 jinja 化而来（甲方=委托人、收费合计、大写）。协议书大部分是固定法律
文本，只这几处随项目变。

协议书无估价算术，**不进台账**（快照自洽只管估价，见 docs/README §2 铁律 4/5）。
收费合计由估价师手填（浙价服差额计费属执业收费标准，§8 不编码进系统）；
大写用 prose.capital 生成——法律文书里大写作准，不得算错。
运行时零 AI（约束 C2）。
"""

import logging
from pathlib import Path

from docxtpl import DocxTemplate

from src.model import Project
from src.paths import templates_dir
from src.prose.capital import to_capital

logger = logging.getLogger(__name__)

__all__ = ["build_agreement_context", "render_agreement", "AGREEMENT_TEMPLATE"]

AGREEMENT_TEMPLATE = "entrustment_agreement.docx"


def build_agreement_context(project: Project, fee_total: int) -> dict[str, object]:
    """组装协议书上下文。

    Args:
        project: 项目数据（取委托人）。
        fee_total: 估价师手填的收费合计，整数元。

    Returns:
        供 docxtpl 渲染的上下文。fee_total 加千分位、fee_capital 为中文大写。
    """
    return {
        "client": project.client,
        "fee_total": f"{fee_total:,}",
        "fee_capital": to_capital(fee_total),
    }


def render_agreement(
    project: Project,
    fee_total: int,
    output: Path,
    templates_dir_override: Path | None = None,
) -> Path:
    """渲染委托评估协议书 docx。

    Args:
        project: 项目数据。
        fee_total: 收费合计，整数元。
        output: 输出 docx 路径。
        templates_dir_override: 模板目录，默认取 paths.templates_dir()。

    Returns:
        输出路径。

    Raises:
        FileNotFoundError: 模板不存在。
        ValueError: fee_total 为负（to_capital 会拒绝）。
    """
    directory = templates_dir_override or templates_dir()
    template_path = directory / AGREEMENT_TEMPLATE
    if not template_path.exists():
        raise FileNotFoundError(f"协议书模板不存在：{template_path}")
    document = DocxTemplate(template_path)
    document.render(build_agreement_context(project, fee_total))
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(output)
    logger.info("已生成委托评估协议书 %s（收费 %d 元）", output.name, fee_total)
    return output
