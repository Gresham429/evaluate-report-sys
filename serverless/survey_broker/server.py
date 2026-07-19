"""FC「自定义运行时」入口：把纯 `dispatch` 包成一个极简 HTTP Server。

自定义运行时(Web Server 模式)的约定：进程监听一个端口，函数计算把 HTTP 请求
转发进来。故这里用标准库 `http.server` 起服务，POST body `{action, payload}`
→ `dispatch` → JSON。不引任何第三方框架。

客户端(`NotableClient`/`AmapClient`)在**进程启动时建一次**(`build_context`)，warm
容器复用同一实例——token 缓存随之复用，省掉每请求重换 token。

- 启动命令： `python -m serverless.survey_broker.server`
- 监听端口： 环境变量 `FC_SERVER_PORT`（FC 注入），缺省 9000；与控制台「监听端口」一致。
"""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from serverless.survey_broker.amap import AmapClient
from serverless.survey_broker.handler import _Amap, _Store, dispatch
from serverless.survey_broker.store import SurveyBrokerStore
from src.dingtalk.notable import NotableClient

logger = logging.getLogger(__name__)

__all__ = ["build_context", "handle", "main"]


def build_context() -> tuple[SurveyBrokerStore, AmapClient]:
    """按环境变量建 store + amap（进程启动时调一次）。缺必需变量即 KeyError→进程起不来，属预期。"""
    client = NotableClient(
        os.environ["DINGTALK_APP_KEY"],
        os.environ["DINGTALK_APP_SECRET"],
        base_id=os.environ["NOTABLE_BASE_ID"],
        operator_id=os.environ["NOTABLE_OPERATOR_ID"],
    )
    store = SurveyBrokerStore(client, os.environ["NOTABLE_SURVEY_SHEET"])
    amap = AmapClient(os.environ.get("AMAP_KEY", ""))
    return store, amap


def handle(body_bytes: bytes, *, store: _Store, amap: _Amap) -> tuple[int, bytes]:
    """解析请求体 → `dispatch` → JSON 字节。纯函数，可单测（不碰 socket）。

    请求体约定 `{"action": "...", "payload": {...}}`；体非法 JSON/非对象 → 400。
    """
    try:
        req: Any = json.loads(body_bytes.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return 400, _json({"error": f"请求体非合法 JSON：{exc}"})
    if not isinstance(req, dict):
        return 400, _json({"error": "请求体须为对象"})
    try:
        status, result = dispatch(
            str(req.get("action") or ""), req.get("payload") or {}, store=store, amap=amap
        )
    except Exception as exc:  # noqa: BLE001  HTTP 边界兜底：下游(钉钉/高德)任何异常都回 JSON，绝不让进程崩
        logger.exception("dispatch 未捕获异常")
        return 500, _json({"error": f"内部错误：{type(exc).__name__}: {exc}"})
    return status, _json(result)


def _json(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _make_handler(store: _Store, amap: _Amap) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # 健康检查：FC 探活/浏览器直连都回 200
            self._send(200, b'{"ok":true}')

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length > 0 else b""
                status, out = handle(body, store=store, amap=amap)
            except Exception as exc:  # noqa: BLE001  连读体都可能炸，仍要回响应而非断连
                logger.exception("do_POST 未捕获异常")
                status, out = 500, _json({"error": f"服务器错误：{type(exc).__name__}: {exc}"})
            self._send(status, out)

        def log_message(self, *args: Any) -> None:  # 静音默认 stderr 访问日志
            pass

    return _Handler


def main() -> None:
    port = int(os.environ.get("FC_SERVER_PORT") or os.environ.get("PORT") or "9000")
    store, amap = build_context()
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(store, amap))
    logger.info("survey_broker HTTP server 监听 :%d", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
