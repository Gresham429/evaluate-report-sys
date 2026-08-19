"""启动本地服务并打开浏览器。

用法：
    python -m src
"""

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import TextIO

import uvicorn

from src.knowledge_base.seed import seed_default_base_tables_if_empty
from src.knowledge_base.store import DEFAULT_STORE_DIR
from src.library.seed import seed_default_instances_if_empty
from src.library.store import DEFAULT_STORE_PATH
from src.paths import app_dir, bundled_dir
from src.web.app import create_app
from src.web.heartbeat import Heartbeat
from src.web.session import restore_login

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765
# 本程序的身份标识——`/api/ping` 返回它，单实例守卫据此认「8765 上是不是本程序」。
APP_ID = "appraisal-report-system"
# 关网页自动停服：前端每几秒心跳，超过 GRACE 秒没心跳（关了网页）→ 优雅停服退出。
# GRACE 给足，避免刷新页面/短暂卡顿误杀；只在收到过首拍后才生效（页面没加载不动手）。
# 登录扫码另有更长宽限（`mark_login`，见 app.py），期间绝不停服，否则回调打到死服务、进不去。
_IDLE_GRACE_S = 30.0
_WATCH_INTERVAL_S = 3.0
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


def _load_dotenv() -> None:
    """把 exe/仓库根旁的 .env 灌进环境变量（钉钉凭据、承载后端开关）。

    只在真运行入口调，**不进 create_app()**：测试走 create_app()，一旦在那 load
    就会把真凭据带进单测、去打真钉钉（config.py 的注释也是这个立场）。
    setdefault 语义：命令行/CI 已显式设的变量优先，.env 只补缺。
    """
    env_file = app_dir() / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
    logger.info("已加载 .env：%s", env_file)


def _port_free(host: str, port: int) -> bool:
    """该端口现在能否绑定（没人在听）。仅用于给「被占用」一个清楚提示，不参与实际起服。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _our_app_running(host: str, port: int, *, timeout: float = 1.5) -> bool:
    """该端口上是否已是**本程序**在跑——探 `/api/ping` 认 `APP_ID` 标识。

    探测失败（没人应答/不是本程序/超时/非 JSON）一律视作「没在跑」。
    """
    url = f"http://{host}:{port}/api/ping"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310  仅本机固定地址
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001  探测失败一律当作「没在跑」，绝不因探测异常拖垮启动
        return False
    return isinstance(data, dict) and data.get("app") == APP_ID


def _should_shutdown(heartbeat: Heartbeat, *, grace: float) -> bool:
    """页面已加载过(armed) 且 超过 grace 秒没心跳(关了网页) → 该停服。

    未武装恒 False；**登录扫码宽限内恒 False**（浏览器在钉钉页、收不到心跳，但不能停服）。
    """
    return (
        heartbeat.armed
        and not heartbeat.in_login_grace()
        and heartbeat.idle_seconds() > grace
    )


def _start_shutdown_watchdog(
    server: uvicorn.Server,
    heartbeat: Heartbeat,
    *,
    grace: float = _IDLE_GRACE_S,
    interval: float = _WATCH_INTERVAL_S,
) -> None:
    """后台守护线程：没人看网页了就让 uvicorn 优雅停服（server.should_exit）。"""

    def _watch() -> None:
        while not server.should_exit:
            time.sleep(interval)
            if _should_shutdown(heartbeat, grace=grace):
                logger.info("浏览器已关闭（%.0f 秒无心跳），自动停服退出。", heartbeat.idle_seconds())
                server.should_exit = True
                return

    threading.Thread(target=_watch, daemon=True).start()


def _open_browser(url: str) -> None:
    """打开浏览器看应用。Windows 上**强制用 Edge**（Win10/11 必装、Chromium 内核）。

    本应用用了 fetch/现代 JS，老国产浏览器（IE 内核）会白屏、卡在门禁「请先登录」、
    按钮点不出——用 Edge 从根上规避。Edge 打不开（极少）则回退系统默认浏览器。
    """
    startfile = getattr(os, "startfile", None)
    if sys.platform == "win32" and startfile is not None:
        try:
            startfile(f"microsoft-edge:{url}")   # microsoft-edge: 协议由 Edge 注册，Win10/11 稳定可用
            return
        except OSError:
            logger.warning("用 Edge 打开失败，回退系统默认浏览器", exc_info=True)
    webbrowser.open(url)


def main() -> None:
    _setup_logging()
    _load_dotenv()
    url = f"http://{HOST}:{PORT}/"

    # 单实例守卫：本程序已在跑 → 直接打开浏览器复用，绝不启第二个撞端口（10048）。
    # 客户是无窗口后台服务、「关网页≠关程序」，双击应永远只是「打开网页」。
    if _our_app_running(HOST, PORT):
        logger.info("本程序已在运行，直接打开浏览器：%s", url)
        _open_browser(url)
        return
    # 端口被别的东西占（不是本程序）→ 别硬起 uvicorn 静默崩，给清楚提示并打开浏览器兜底。
    if not _port_free(HOST, PORT):
        logger.error("端口 %s 被占用且不是本程序。请重启电脑后重新打开本程序。", PORT)
        _open_browser(url)
        return

    restore_login()   # 恢复上次登录：服务自停重启/重开后仍保持登录，免每次重扫

    # 首次运行（本地基础表为空）铺内置的 7 张默认基础表，离线开箱即用；本地非空则跳过，
    # 升级不覆盖估价师攒的版本。之后可在基础表页「从钉钉拉取」更新。
    seed_default_base_tables_if_empty(DEFAULT_STORE_DIR, bundled_dir("resources", "默认基础表"))
    # 同理铺内置的默认实例库（12 条起步实例）；本地已有则跳过、升级不覆盖。钉钉模式实例走多维表、
    # 本地这份不参与，播了也无妨。
    seed_default_instances_if_empty(DEFAULT_STORE_PATH, bundled_dir("resources", "默认实例库.json"))
    logger.info("启动 %s", url)
    threading.Timer(1.0, lambda: _open_browser(url)).start()
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))
    _start_shutdown_watchdog(server, app.state.heartbeat)   # 关网页无心跳 → 优雅停服退出
    server.run()


if __name__ == "__main__":
    main()
