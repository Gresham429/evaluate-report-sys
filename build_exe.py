"""PyInstaller 打包脚本。

模板与 copy.yaml **外置**、不打进 exe —— 用户改措辞无需重新编译。

仓库里的布局与交付布局刻意一致（copy.yaml、templates/、data/ 都在根），
运行期靠 `src/paths.py` 统一解析：onefile 冻结后 `Path(__file__)` 指向退出即删的
临时解压目录，凡「用户能看到、能改、要留住」的东西都必须挂在 exe 旁边。

用法（在 Windows 上）：
    uv run python build_exe.py
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


def main() -> int:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "估价报告系统",
        "--add-data", f"src/web/static{';' if sys.platform == 'win32' else ':'}src/web/static",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        "src/__main__.py",
    ]
    logger.info("执行：%s", " ".join(command))
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        logger.error("打包失败")
        return result.returncode

    # 模板与文案库外置，供用户直接编辑
    shutil.copytree(ROOT / "templates", DIST / "templates", dirs_exist_ok=True)
    shutil.copy2(ROOT / "copy.yaml", DIST / "copy.yaml")
    logger.info("已产出 %s", DIST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
