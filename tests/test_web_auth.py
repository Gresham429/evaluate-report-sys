"""办公端钉钉扫码登录端点：/auth/login、/auth/callback、/auth/logout。

不触网——monkeypatch 掉 config.build_oauth（假 transport）与 build_client（假应用 token）。
"""

import json
import urllib.parse
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.dingtalk.oauth import DingtalkOAuth
from src.web.app import create_app


class _FakeTransport:
    def __init__(self, responses: list[tuple[int, str]]) -> None:
        self._responses = list(responses)

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        return self._responses.pop(0)


class _FakeClient:
    def access_token(self) -> str:
        return "APP-TOK"


# exchange → me → userid_by_union 三步的成功响应
_OK_FLOW = [
    (200, json.dumps({"accessToken": "UAT", "expireIn": 7200})),
    (200, json.dumps({"unionId": "UNI-1", "nick": "张三"})),
    (200, json.dumps({"errcode": 0, "result": {"userid": "10076"}})),
]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _clear_session() -> Iterator[None]:
    from src.web import session

    session.clear_operator()
    session._session.pop("oauth_state", None)
    yield
    session.clear_operator()
    session._session.pop("oauth_state", None)


def _wire(monkeypatch: pytest.MonkeyPatch, responses: list[tuple[int, str]]) -> None:
    from src.dingtalk import config

    oauth = DingtalkOAuth("app-key", "app-secret", transport=_FakeTransport(responses))
    monkeypatch.setattr(config, "build_oauth", lambda: oauth)
    monkeypatch.setattr(config, "build_client", lambda *, timeout=30.0: _FakeClient())


def _login_state(client: TestClient) -> str:
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert loc.startswith("https://login.dingtalk.com/oauth2/auth?")
    return urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)["state"][0]


def test_login_redirects_to_dingtalk_with_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, [])
    state = _login_state(client)
    assert state  # 生成了一次性 state


def test_login_without_credentials_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.dingtalk import config

    monkeypatch.setattr(config, "build_oauth", lambda: None)
    assert client.get("/auth/login", follow_redirects=False).status_code == 409


def test_callback_full_flow_sets_operator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, list(_OK_FLOW))
    state = _login_state(client)
    r = client.get(
        "/auth/callback", params={"authCode": "AC", "state": state}, follow_redirects=False
    )
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/"
    me = client.get("/api/me").json()
    assert me["operator"] == "10076"          # unionId 已换成 userid
    assert me["operator_name"] == "张三"
    assert me["logged_in"] is True


def test_callback_bad_state_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, list(_OK_FLOW))
    _login_state(client)  # 存了一个 state
    r = client.get(
        "/auth/callback", params={"authCode": "AC", "state": "WRONG"}, follow_redirects=False
    )
    assert r.status_code == 400
    assert client.get("/api/me").json()["logged_in"] is False  # 没登进去


def test_callback_dingtalk_failure_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, [(400, json.dumps({"message": "invalid code"}))])  # exchange 就失败
    state = _login_state(client)
    r = client.get(
        "/auth/callback", params={"authCode": "bad", "state": state}, follow_redirects=False
    )
    assert r.status_code == 400
    assert client.get("/api/me").json()["logged_in"] is False


def test_logout_clears_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, list(_OK_FLOW))
    state = _login_state(client)
    client.get("/auth/callback", params={"authCode": "AC", "state": state}, follow_redirects=False)
    assert client.get("/api/me").json()["logged_in"] is True
    r = client.get("/auth/logout", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert client.get("/api/me").json()["logged_in"] is False
