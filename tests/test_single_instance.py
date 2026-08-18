"""单实例守卫：双击 exe 不再撞端口。

病根（真机日志）：程序是无窗口后台服务，客户「关网页」不等于关程序，旧实例一直占着
8765；下次双击起第二个 → `[Errno 10048] 端口只允许使用一次` → 静默崩，客户只看到旧的坏页面。
守卫：启动时先探 8765 上是不是**本程序**在跑（认 `/api/ping` 标识）——是就直接打开浏览器复用、
不再启第二个；被别的东西占则给清楚提示而非崩。零新依赖、纯标准库。
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from fastapi.testclient import TestClient

from src.__main__ import _our_app_running, _port_free
from src.version import __version__
from src.web.app import create_app


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _serve(body: bytes, path_ok: str = "/api/ping") -> tuple[HTTPServer, int]:
    """起个只在 path_ok 回 200+body、其余 404 的假服务，返回 (server, port)。"""
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == path_ok:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args: Any) -> None:  # 静音
            pass

    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, int(srv.server_address[1])


def test_port_free_true_when_nothing_listening() -> None:
    assert _port_free("127.0.0.1", _free_port()) is True


def test_port_free_false_when_taken() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = int(sock.getsockname()[1])
    try:
        assert _port_free("127.0.0.1", port) is False
    finally:
        sock.close()


def test_our_app_running_false_when_nothing_there() -> None:
    assert _our_app_running("127.0.0.1", _free_port(), timeout=0.5) is False


def test_our_app_running_true_against_our_ping() -> None:
    srv, port = _serve(b'{"app":"appraisal-report-system"}')
    try:
        assert _our_app_running("127.0.0.1", port) is True
    finally:
        srv.shutdown()


def test_our_app_running_false_against_foreign_server() -> None:
    # 端口被占，但不是本程序（/api/ping 不回我们的标识）
    srv, port = _serve(b"not us")
    try:
        assert _our_app_running("127.0.0.1", port) is False
    finally:
        srv.shutdown()


def test_ping_endpoint_reports_identity_and_version() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app"] == "appraisal-report-system"
    assert body["version"] == __version__


def test_ping_is_reachable_even_when_gate_on(monkeypatch: Any) -> None:
    # 钉钉模式下门禁开着，但 /api/ping 必须免登可达（守卫要能探到 gated 实例）
    monkeypatch.setenv("承载后端", "多维表")
    client = TestClient(create_app())
    assert client.get("/api/ping").status_code == 200          # 豁免
    assert client.get("/api/instances").status_code == 403     # 未登录被挡


def test_ping_json_shape_matches_probe_expectation() -> None:
    # 守卫认的就是 {"app": "..."}；用真端点的输出喂探测判定，两边对齐
    client = TestClient(create_app())
    body = client.get("/api/ping").content
    parsed = json.loads(body)
    assert parsed.get("app") == "appraisal-report-system"
