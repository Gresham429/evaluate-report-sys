"""运行期路径解析——**冻结与否，只在这里判断一次**。

PyInstaller 以 `--onefile` 打包，运行时把代码解压到临时目录（`sys._MEIPASS`），
**退出时删掉**。故冻结后 `Path(__file__)` 指向的是一个即将蒸发的目录：

    非冻结（uv run python -m src）   __file__ → 仓库里的 src/，其父即项目根
    冻结（估价报告系统.exe）         __file__ → /tmp/_MEIxxxx/src/，退出即删

把用户数据或外置文件挂在 `Path(__file__)` 上，冻结后就是：

    data/实例库.json   估价师录的每条实例，关掉程序就没
    data/草稿/         「填一半别丢」的东西，关掉就丢光
    data/基础表/       「旧版本永不覆盖」的承诺，关掉全没了
    copy.yaml          压根不在包里 → 生成报告直接 FileNotFoundError，一份也出不来

**凡是「用户能看到、能改、要留住」的东西，一律挂在 exe 旁边**，即本模块的
`app_dir()`。凡是「随代码走、不该被改」的（模板引擎、Python 包本身）才留在包内。

`templates/` 早已按这个道理处理（`render.py::_templates_dir`），本模块把同一个
判断收成一处，免得下一个新增的存储又各写一遍、又漏一个。
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["app_dir", "data_dir", "templates_dir", "copy_path", "is_frozen"]

# 仓库根：src/paths.py → src/ → 项目根
_REPO_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """是否运行在 PyInstaller 冻结包里。"""
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """用户数据与外置文件的根目录。

    Returns:
        冻结时为 exe 所在目录（数据须活过进程退出）；否则为仓库根。
    """
    return Path(sys.executable).parent if is_frozen() else _REPO_ROOT


def data_dir() -> Path:
    """`data/`：实例库、草稿、基础表各版本。

    **不在这里 mkdir**：各存储自己在写入时建目录，读取时目录不存在即视为空库
    （首次运行本就如此）。此处只管算出路径。
    """
    return app_dir() / "data"


def templates_dir() -> Path:
    """`templates/`：三份 docx 模板，用户可在 Word 里直接改。"""
    return app_dir() / "templates"


def copy_path() -> Path:
    """`copy.yaml`：法定套话，用户可直接改，改一处三类同步。

    冻结后它在 exe 旁边而非包内——「改 copy.yaml 不用重新编译」这个承诺，
    只有放在包外才成立。
    """
    return app_dir() / "copy.yaml"
