"""按数据条件组句。

「文字灵活」的实现方式：灵活来自数据差异，不来自模型随机性。
同一份输入永远产出同一份文字，可复现、可审计（约束 C2）。
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.model import Project

logger = logging.getLogger(__name__)

__all__ = ["load_copy", "compose", "needs_surveyor_credit"]

_DEFAULT_COPY = Path(__file__).with_name("copy.yaml")


def _strip_spaces(name: str) -> str:
    """去掉姓名中的空格。

    报告抬头写作「韩  伟」，实勘表 D46 录作「韩伟」，比对前须统一。
    """
    return name.replace(" ", "").replace("　", "").strip()


def needs_surveyor_credit(surveyor: str, copy: dict[str, Any]) -> bool:
    """现场查勘记录人员是否需要在正文单独署名。

    规则：查勘人若本身就是本报告抬头署名的注册估价师，抬头已署其名，
    正文不再单独提；否则须署名。

    实测：农用/商业 D46=郑伟娜（非注册估价师）→ 署名；
    办公 D46=胡柯（抬头注册估价师之一）→ 不署名。

    Args:
        surveyor: 实勘表 D46 的现场查勘记录人员姓名。
        copy: 文案库，需含 `registered_appraisers`。

    Returns:
        True 表示须署名。
    """
    name = _strip_spaces(surveyor)
    if not name:
        return False
    registered = {_strip_spaces(n) for n in copy.get("registered_appraisers", [])}
    return name not in registered


@lru_cache(maxsize=4)
def _load_cached(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_copy(path: Path | None = None) -> dict[str, Any]:
    """加载文案库。

    Args:
        path: copy.yaml 路径，默认取包内文件。

    Returns:
        含 `boilerplate` 与 `conditional` 的字典。

    Raises:
        FileNotFoundError: 文案库不存在。
    """
    target = path or _DEFAULT_COPY
    if not target.exists():
        raise FileNotFoundError(f"文案库不存在：{target}")
    return _load_cached(target)


def compose(project: Project, copy_path: Path | None = None) -> dict[str, str]:
    """按项目数据选句。

    Args:
        project: 项目数据。
        copy_path: 文案库路径，默认取包内文件。

    Returns:
        条件文本字典，供模板渲染。
    """
    copy = load_copy(copy_path)
    conditional = copy["conditional"]
    cert_key = "已取得" if project.has_certificate else "未取得"
    scope_key = "农用" if project.is_land else "房屋"

    surveyor_key = "有" if needs_surveyor_credit(project.surveyor, copy) else "无"
    surveyor_text = conditional["查勘人署名"][surveyor_key]
    if surveyor_key == "有":
        surveyor_text = surveyor_text.replace("{{ surveyor }}", project.surveyor.strip())

    return {
        "估价范围": conditional["估价范围"][scope_key],
        "权证": conditional["权证"][cert_key],
        "资料清单": conditional["资料清单"][cert_key],
        "附件清单第三项": conditional["附件清单第三项"][cert_key],
        "查勘人署名": surveyor_text,
        "面积单位": "亩" if project.is_land else "㎡",
        "单价单位": "元/亩·年" if project.is_land else "元/㎡·天",
    }
