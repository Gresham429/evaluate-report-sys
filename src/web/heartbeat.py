"""浏览器心跳：页面开着就 beat，关掉标签页 beat 停 → 看门狗宽限后停服。

用途：本程序是无窗口本地服务，客户「关网页」不等于关程序、会永远挂在后台占端口。
让前端页面每几秒 `GET /api/heartbeat` 一次，`__main__` 的看门狗据此判断「还有没有人在看」，
没人看了就优雅停服（进程退出）。这样「关网页 = 关程序」，不留后台、也不会积累实例。

**只在收到第一次心跳后才「武装」**：页面加载需要时间（老机器更慢），武装前看门狗绝不动手，
避免页面还没打开就把自己关了。`clock` 可注入，单测用假时钟不依赖真实时间。
"""

import threading
import time
from collections.abc import Callable

__all__ = ["Heartbeat"]


class Heartbeat:
    """进程内心跳状态：线程安全（端点在请求线程写、看门狗在后台线程读）。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last = 0.0
        self._armed = False
        self._login_deadline = 0.0

    def beat(self) -> None:
        """收到一次心跳：记时间戳，并武装（首拍后看门狗才开始盯）。"""
        with self._lock:
            self._last = self._clock()
            self._armed = True

    def mark_login(self, grace_seconds: float) -> None:
        """点了钉钉登录：此后 grace_seconds 内绝不停服。

        登录时浏览器会跳到钉钉扫码页（别的域名），我们的页面收不到心跳；若这期间停服，
        回调会打到已死的服务、登录进不去。故给足扫码窗口，窗口内看门狗不动手。
        """
        with self._lock:
            self._login_deadline = self._clock() + grace_seconds

    def in_login_grace(self) -> bool:
        """是否仍在「登录扫码宽限」内（此间不许停服）。"""
        with self._lock:
            return self._clock() < self._login_deadline

    @property
    def armed(self) -> bool:
        """是否已收到过至少一次心跳（页面已加载过）。"""
        with self._lock:
            return self._armed

    def idle_seconds(self) -> float:
        """距上次心跳多少秒；未武装恒回 0（看门狗据此不动手）。"""
        with self._lock:
            return self._clock() - self._last if self._armed else 0.0
