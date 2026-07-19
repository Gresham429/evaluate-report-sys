"""PyInstaller 打包脚本。

模板与 copy.yaml **外置**、不打进 exe —— 用户改措辞无需重新编译。

仓库里的布局与交付布局刻意一致（copy.yaml、templates/、data/ 都在根），
运行期靠 `src/paths.py` 统一解析：onefile 冻结后 `Path(__file__)` 指向退出即删的
临时解压目录，凡「用户能看到、能改、要留住」的东西都必须挂在 exe 旁边。

用法：
    uv run python build_exe.py            # 打包 + 产出交付 zip
    uv run python tools/smoke_exe.py dist/appraisal-report-system.exe   # 验它真能用

PyInstaller 不支持交叉编译：在 Windows 上跑才产出 .exe，在 macOS/Linux 上跑产出
对应平台的可执行文件（本地验证冻结行为够用，交付不行）。Windows 产物由
`.github/workflows/build-windows.yml` 出。
"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
# 交付物的名字一律 ASCII：exe、内层目录都用它。**别用中文**——中文名进交付会栽
# 两类跤：① GitHub Release 把资产名里的非 ASCII 字符直接删掉（「估价报告系统.zip」
# 变「.zip」，实测 v1.0.0）；② zip 里的中文条目名被第三方解压软件（WinRAR/360/
# 好压/2345）按 GBK 解成乱码（「估价报告系统.exe」→「浼板€兼姤鍛婄郴缁?.exe」），
# 估价师看到的就是一堆乱码文件名。凡随包发出、要被机器或人按名字认的标识，一律
# ASCII。产品名仍是中文，那是界面/报告里的事，不进文件名。
APP_NAME = "appraisal-report-system"

# 交付 zip 的文件名。同样只能 ASCII（理由见 APP_NAME）。
ARCHIVE_STEM = "appraisal-report-system-windows"

# 交付包里放什么。**刻意不放 data/**：那是估价师的实例库、草稿、基础表，
# 由程序首次运行时自建。塞进交付包的话，下次解压升级会把人家攒的实例库连同
# 草稿一起盖掉——升级不该是数据事故。
_PAYLOAD_DOC = ROOT / "docs" / "使用说明.md"


def _build() -> int:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", APP_NAME,
        "--add-data", f"src/web/static{';' if sys.platform == 'win32' else ':'}src/web/static",
        # 内置 7 张默认基础表（**只读随包**，非 data/）：首次运行本地空时铺进 data/基础表，
        # 离线开箱即用；本地非空则跳过，升级不覆盖。见 __main__.main() 的 seed 调用。
        "--add-data",
        f"resources/默认基础表{';' if sys.platform == 'win32' else ':'}resources/默认基础表",
        # 只在 Windows 上隐藏控制台：交付 exe 双击不该弹出黑终端。隐藏后 stdout/
        # stderr 变 None，日志由 __main__._setup_logging() 接到 exe 旁的日志文件。
        # **仅限 win32**：--noconsole 在 macOS 上会打成 .app 包，本地验证的
        # staging/smoke 都按单个可执行文件走，会撞车；本机只做冻结行为验证，
        # 不发货，留着控制台反而方便调试。
        *(["--noconsole"] if sys.platform == "win32" else []),
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        "src/__main__.py",
    ]
    logger.info("执行：%s", " ".join(command))
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def exe_name() -> str:
    """产物文件名。Windows 带 .exe，其余平台不带。"""
    return f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME


def staging_dir() -> Path:
    """交付包解压后的那个目录。**冒烟测试就对着它跑**——验的是真发出去的形态。

    刻意套在 `_package/` 里而不直接用 `dist/appraisal-report-system/`：非 Windows
    平台 PyInstaller 的产物就叫 `dist/appraisal-report-system`（无后缀），会与同名
    目录撞车。
    Windows 上因为有 `.exe` 后缀撞不上——正因如此，这种错只在本地验证时炸，
    CI 一路绿灯，不如从一开始就别让它有机会。
    """
    return DIST / "_package" / APP_NAME


def _stage() -> Path:
    """把交付内容摆成用户解压后看到的样子。"""
    staging = staging_dir()
    shutil.rmtree(staging.parent, ignore_errors=True)
    staging.mkdir(parents=True)

    shutil.copy2(DIST / exe_name(), staging / exe_name())
    # 忽略 .gitkeep 之类：那是版本管理的事，估价师解开包不该看见它。
    shutil.copytree(
        ROOT / "templates", staging / "templates", ignore=shutil.ignore_patterns(".*")
    )
    shutil.copy2(ROOT / "copy.yaml", staging / "copy.yaml")
    if _PAYLOAD_DOC.exists():
        shutil.copy2(_PAYLOAD_DOC, staging / "使用说明.md")
    return staging


def main() -> int:
    if (code := _build()) != 0:
        logger.error("打包失败")
        return code

    staging = _stage()
    archive = Path(
        shutil.make_archive(str(DIST / ARCHIVE_STEM), "zip", staging.parent, APP_NAME)
    )
    logger.info("已产出交付包 %s（%.1f MB）", archive, archive.stat().st_size / 1024 / 1024)
    logger.info("下一步验它真能用：uv run python tools/smoke_exe.py %s", staging / exe_name())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
