"""启动本地服务并打开浏览器。

用法：
    python -m src
"""

import logging
import threading
import webbrowser

import uvicorn

from src.web.app import create_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765


def main() -> None:
    url = f"http://{HOST}:{PORT}/"
    logger.info("启动 %s", url)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
