"""启动本地服务并打开浏览器。

用法：
    python -m src
"""

import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import TextIO

import uvicorn

from src.paths import app_dir
from src.web.app import create_app

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765
# 运行期由 Python 写到 exe 旁边——中文名无妨（同 data/草稿/，UTF-16 写 NTFS 名字总对）；
# 会被第三方解压软件搞乱码的只有随 zip 发出去的文件，这个不是。
LOG_FILENAME = "运行日志.log"


def _resolve_log_stream(app_directory: Path, current_stdout: object) -> TextIO | None:
    """冻结且无控制台时，日志该往哪写。

    交付 exe 用 `--noconsole` 打包（否则双击弹出黑终端），PyInstaller 便把
    `sys.stdout` / `sys.stderr` 置为 None。此时任何 print / logging / uvicorn 的
    StreamHandler 都会炸在 None 上——程序默默起不来，而用户连报错都看不到。

    故 stdout 为 None 时，返回一个接到 exe 旁 `运行日志.log` 的 UTF-8 流：既不炸，
    又把「隐藏终端后崩了什么都看不见」变成一份可回看的现场。stdout 正常（开发
    环境）时返回 None，表示沿用现有 stdout，不改动。

    Args:
        app_directory: 日志落地目录（exe 旁边）。
        current_stdout: 传入 `sys.stdout`，抽成参数便于测试。

    Returns:
        要改用的日志流；stdout 正常时返回 None。
    """
    if current_stdout is not None:
        return None
    try:
        return open(app_directory / LOG_FILENAME, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        # 目录不可写（如装进 Program Files 又没权限）也不能让程序起不来。
        return open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _setup_logging() -> None:
    """配置日志。冻结无控制台时先把标准流接到文件，再 basicConfig。

    顺序要紧：uvicorn 的日志把 handler 绑到「配置那一刻的」`sys.stdout`/`stderr`，
    故重定向必须在 `uvicorn.run` 之前完成，否则它照样绑到 None 上。
    """
    stream = _resolve_log_stream(app_dir(), sys.stdout)
    if stream is not None:
        sys.stdout = stream
        sys.stderr = stream
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    _setup_logging()
    url = f"http://{HOST}:{PORT}/"
    logger.info("启动 %s", url)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
