"""浏览器心跳 → 关网页自动停服。

无窗口后台服务「关网页≠关程序」会永远挂着；改成：页面开着每几秒 beat 一次，标签页
一关 beat 停，看门狗宽限后优雅停服（进程退出）。「关网页 = 关程序」，不留后台。
看门狗**只在收到过第一次心跳后才武装**——避免页面还没加载就把自己关了（老机器慢）。
"""

from typing import Any

from fastapi.testclient import TestClient

from src.__main__ import _should_shutdown
from src.web.app import create_app
from src.web.heartbeat import Heartbeat


class FakeClock:
    """可推进的假时钟，测心跳空闲判定不依赖真实时间。"""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_heartbeat_not_armed_until_first_beat() -> None:
    hb = Heartbeat(clock=FakeClock())
    assert hb.armed is False
    assert hb.idle_seconds() == 0.0   # 未武装时不报空闲，看门狗据此不动


def test_heartbeat_arms_and_tracks_idle() -> None:
    clk = FakeClock()
    hb = Heartbeat(clock=clk)
    hb.beat()
    assert hb.armed is True
    clk.advance(7.0)
    assert hb.idle_seconds() == 7.0


def test_should_shutdown_only_when_armed_and_idle_over_grace() -> None:
    clk = FakeClock()
    hb = Heartbeat(clock=clk)
    assert _should_shutdown(hb, grace=15.0) is False   # 未武装：绝不关（页面可能还没开）
    hb.beat()
    clk.advance(10.0)
    assert _should_shutdown(hb, grace=15.0) is False   # 武装了，但还在宽限内（刷新页面不误杀）
    clk.advance(10.0)                                   # 累计 20s > 15s
    assert _should_shutdown(hb, grace=15.0) is True     # 关了网页、超宽限 → 停服


def test_login_grace_suppresses_shutdown_while_scanning() -> None:
    # 登录时浏览器跳到钉钉扫码页，我们的页面收不到心跳；登录宽限内绝不停服，
    # 否则回调打到已死的服务、登录进不去（真机暴露的 bug）。
    clk = FakeClock()
    hb = Heartbeat(clock=clk)
    hb.beat()                       # 页面加载过、已武装
    hb.mark_login(300.0)            # 点了登录，给 5 分钟扫码窗口
    clk.advance(120.0)              # 扫码 2 分钟，早超基础宽限 30s
    assert hb.in_login_grace() is True
    assert _should_shutdown(hb, grace=30.0) is False   # 登录中不停服
    clk.advance(200.0)             # 累计 320s > 300s 登录宽限，且仍无心跳
    assert hb.in_login_grace() is False
    assert _should_shutdown(hb, grace=30.0) is True     # 登录窗口过了、还没回来 → 才停


def test_auth_login_marks_login_grace(monkeypatch: Any) -> None:
    # 点 /auth/login 应打「登录中」标记（用假 YIDA 凭据，build_auth_url 纯字符串构造、无网）
    monkeypatch.setenv("承载后端", "多维表")
    monkeypatch.setenv("YIDA_APP_KEY", "dummy_key")
    monkeypatch.setenv("YIDA_APP_SECRET", "dummy_secret")
    app = create_app()
    client = TestClient(app)
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)                 # 跳钉钉授权页
    assert app.state.heartbeat.in_login_grace() is True   # 已进入登录宽限


def test_heartbeat_endpoint_arms_and_is_gate_exempt(monkeypatch: Any) -> None:
    monkeypatch.setenv("承载后端", "多维表")   # 钉钉模式门禁开：登录中也要能续命
    app = create_app()
    client = TestClient(app)
    assert client.get("/api/heartbeat").status_code == 200   # 豁免、免登可达
    assert app.state.heartbeat.armed is True                  # 端点确实喂了心跳
