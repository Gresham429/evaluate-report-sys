"""在线检测端点：本地模式恒 false/local；多维表模式按 client.online() 定。

不触网——用 monkeypatch 把 config 的三个开关/构造替换成假件。
"""

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_local_mode_reports_offline_local(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # 承载后端未设 → use_notable() False（conftest 不设该 env，默认即本地）
    body = client.get("/api/online").json()
    assert body == {"online": False, "mode": "local"}


def test_notable_up_reports_online(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.dingtalk import config

    class _UpClient:
        def online(self) -> bool:
            return True

    monkeypatch.setattr(config, "use_notable", lambda: True)
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: _UpClient())
    body = client.get("/api/online").json()
    assert body == {"online": True, "mode": "notable"}


def test_notable_but_no_credentials_reports_offline_notable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.dingtalk import config

    monkeypatch.setattr(config, "use_notable", lambda: True)
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: None)
    body = client.get("/api/online").json()
    assert body == {"online": False, "mode": "notable"}


def test_notable_probe_failure_reports_offline_notable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.dingtalk import config

    class _DownClient:
        def online(self) -> bool:
            return False

    monkeypatch.setattr(config, "use_notable", lambda: True)
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: _DownClient())
    body = client.get("/api/online").json()
    assert body == {"online": False, "mode": "notable"}
