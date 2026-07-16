"""冻结路径。

**这是本文件存在的全部理由**：PyInstaller 以 onefile 打包，运行时把代码解压到
临时目录、退出时删掉。凡挂在 `Path(__file__)` 上的用户数据，冻结后都活不过一次
关闭——而开发环境（`python -m src`）一切正常，测试也全绿，**没有任何东西会告诉
你这件事**。这类 bug 只能靠「假装自己被冻结了」来盯。

真实后果（2026-07-16 合并前发现，当时四处全中）：

    data/实例库.json   估价师录的每条实例，关掉程序就没
    data/草稿/         「填一半别丢」的东西，关掉就丢光
    data/基础表/       「旧版本永不覆盖」的承诺，关掉全没了
    copy.yaml          压根不在包里 → 生成报告直接 FileNotFoundError，一份也出不来
"""

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from src import paths

# 存放各存储默认路径的模块。它们的默认路径是**模块级常量，导入时即算定**，
# 故假装冻结之后必须重新导入，否则量到的还是导入那一刻（未冻结）的值。
# 真实 exe 里不需要这一步：PyInstaller 在导入我们的代码之前就设好了 sys.frozen。
_STORE_MODULES = (
    "src.library.store",
    "src.drafts.store",
    "src.knowledge_base.store",
    "src.renderer.render",
)


@pytest.fixture()
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """假装跑在 exe 里：exe 在 tmp_path/app/，代码解压在 tmp_path/_MEI999/。

    连同各存储模块一起重新导入，让它们的默认路径按「冻结」重算一遍；退出时
    再按未冻结重算回来，不留给后面的测试一堆指向 tmp_path 的常量。
    """
    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "估价报告系统.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI999"), raising=False)
    _reload_all()
    yield exe_dir
    monkeypatch.undo()
    _reload_all()


def _reload_all() -> None:
    importlib.reload(paths)
    for name in _STORE_MODULES:
        importlib.reload(importlib.import_module(name))


def test_frozen_data_lives_next_to_the_exe(frozen: Path) -> None:
    """用户数据必须活过进程退出——这是四个存储的共同底线。"""
    assert paths.data_dir() == frozen / "data"


def test_frozen_copy_yaml_lives_next_to_the_exe(frozen: Path) -> None:
    """「改 copy.yaml 不用重新编译」这个承诺，只有放在包外才成立。"""
    assert paths.copy_path() == frozen / "copy.yaml"


def test_frozen_templates_live_next_to_the_exe(frozen: Path) -> None:
    """模板要能在 Word 里直接改。"""
    assert paths.templates_dir() == frozen / "templates"


def test_nothing_resolves_into_the_temp_extract_dir(frozen: Path) -> None:
    """总闸：任何用户可见路径都不许落在退出即删的解压目录里。

    逐个断言容易漏掉下一个新增的存储，故这里按「一个都不许」来判。
    """
    meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    for name, resolved in [
        ("data_dir", paths.data_dir()),
        ("copy_path", paths.copy_path()),
        ("templates_dir", paths.templates_dir()),
        ("app_dir", paths.app_dir()),
    ]:
        assert not resolved.is_relative_to(meipass), f"{name} 落在临时解压目录里：{resolved}"


def test_dev_layout_mirrors_delivery_layout() -> None:
    """开发布局与交付布局须一致——不一致正是这类 bug 的温床。

    仓库根与 exe 旁边摆的是同一套东西：copy.yaml、templates/、data/。
    copy.yaml 曾放在 src/prose/ 而交付时在 exe 旁边，两处不一致，
    于是「包里根本没有它」这件事在开发环境里永远暴露不出来。
    """
    root = Path(__file__).resolve().parents[1]
    assert paths.app_dir() == root
    assert paths.copy_path() == root / "copy.yaml"
    assert paths.copy_path().exists(), "copy.yaml 不在仓库根——布局又漂了"
    assert paths.templates_dir() == root / "templates"
    assert paths.data_dir() == root / "data"


def test_every_store_lands_next_to_the_exe_when_frozen(frozen: Path) -> None:
    """**本文件最要紧的一条。**

    四个存储在冻结后都必须落在 exe 旁边。只比对「等于 paths.data_dir()」是抓不住
    回归的：未冻结时旧写法 `Path(__file__).parents[2]/"data"` 与新写法算出来的
    恰好相同，怎么改都是绿的——那样的测试是假的。故此处按**绝对路径**判，
    且必须在假装冻结之后重新导入过。
    """
    from src.drafts.store import DEFAULT_DRAFT_DIR
    from src.knowledge_base.store import DEFAULT_STORE_DIR
    from src.library.store import DEFAULT_STORE_PATH
    from src.renderer.render import DEFAULT_TEMPLATES_DIR

    assert DEFAULT_STORE_PATH == frozen / "data" / "实例库.json"
    assert DEFAULT_DRAFT_DIR == frozen / "data" / "草稿"
    assert DEFAULT_STORE_DIR == frozen / "data" / "基础表"
    assert DEFAULT_TEMPLATES_DIR == frozen / "templates"


def test_stores_use_the_resolved_paths() -> None:
    """开发环境下四个存储的默认路径也得走 paths，不许自己再拼一份。"""
    from src.drafts.store import DEFAULT_DRAFT_DIR
    from src.knowledge_base.store import DEFAULT_STORE_DIR
    from src.library.store import DEFAULT_STORE_PATH
    from src.renderer.render import DEFAULT_TEMPLATES_DIR

    assert DEFAULT_STORE_PATH == paths.data_dir() / "实例库.json"
    assert DEFAULT_DRAFT_DIR == paths.data_dir() / "草稿"
    assert DEFAULT_STORE_DIR == paths.data_dir() / "基础表"
    assert DEFAULT_TEMPLATES_DIR == paths.templates_dir()
