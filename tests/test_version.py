"""版本号单一来源。

台账要记「这份报告是哪个版本生成的」，用途是**发现算法 bug 时查出哪些报告受影响**。
这要求版本号准确且唯一——含糊的版本号比没有更坏。

历史教训：pyproject.toml 曾写 0.1.0，而 git tag 已经打到 v1.0.1，两者各说各话，
且代码里根本没有版本号可读。
"""

import re
import tomllib
from pathlib import Path

from src.version import __version__

_ROOT = Path(__file__).resolve().parents[1]


def test_version_is_a_plain_semver() -> None:
    """不带 v 前缀——前缀只属于 git tag，混进来早晚拼出 vv1.0.1。"""
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_pyproject_matches() -> None:
    """两处不许各说各话。src/version.py 是唯一来源，pyproject 跟着它。"""
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_frozen_exe_can_read_it() -> None:
    """必须是模块常量，不能靠 importlib.metadata 读 pyproject。

    冻结的 exe 里包没被安装，metadata 读不到——那样台账里的版本号会是空的，
    而它恰恰是出事时最要紧的一列。
    """
    source = (_ROOT / "src" / "version.py").read_text(encoding="utf-8")
    assert "importlib.metadata" not in source
    assert "__version__" in source
