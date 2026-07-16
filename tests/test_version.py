"""版本号单一来源。

台账要记「这份报告是哪个版本生成的」，用途是**发现算法 bug 时查出哪些报告受影响**。
这要求版本号准确且唯一——含糊的版本号比没有更坏。

历史教训：pyproject.toml 曾写 0.1.0，而 git tag 已经打到 v1.0.1，两者各说各话，
且代码里根本没有版本号可读。
"""

import ast
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

    用 AST 解析而不是文本扫描：文本扫描分不清「代码真的 import 了它」和
    「docstring 在解释为什么不该 import 它」，会逼着文档把这个名字藏起来，
    反而惩罚了写得清楚的注释。`import importlib.metadata` 和
    `from importlib import metadata` 是两种等价写法，只堵一种等于没堵。
    """
    source = (_ROOT / "src" / "version.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="src/version.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = {alias.name for alias in node.names}
            assert "importlib.metadata" not in imported, (
                "禁止 `import importlib.metadata`：冻结的 exe 读不到包元信息"
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module == "importlib":
                imported = {alias.name for alias in node.names}
                assert "metadata" not in imported, (
                    "禁止 `from importlib import metadata`：冻结的 exe 读不到包元信息"
                )
