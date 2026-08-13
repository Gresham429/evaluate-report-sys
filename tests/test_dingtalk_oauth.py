"""办公端钉钉扫码登录 OAuth2 客户端单测：假 transport，零网络。

真实端点形状（oauth2/userAccessToken、contact/users/me、getbyunionid）待真机校准；
本测试只钉住请求形状与响应解析，不打真钉钉。
"""

import json
import urllib.parse

import pytest

from src.dingtalk.oauth import DingtalkOAuth


class FakeTransport:
    """按顺序吐预置响应，并记录每次调用 (method,url,headers,body)。"""

    def __init__(self, responses: list[tuple[int, str]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        self.calls.append((method, url, headers, body))
        return self._responses.pop(0)


def _oauth(responses: list[tuple[int, str]] | None = None) -> tuple[DingtalkOAuth, FakeTransport]:
    t = FakeTransport(responses or [])
    return DingtalkOAuth("app-key", "app-secret", transport=t), t


def test_build_auth_url_has_required_params() -> None:
    oauth, _ = _oauth()
    url = oauth.build_auth_url("http://127.0.0.1:8765/auth/callback", "st4te")
    assert url.startswith("https://login.dingtalk.com/oauth2/auth?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["client_id"] == ["app-key"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8765/auth/callback"]
    assert q["response_type"] == ["code"]
    assert q["scope"] == ["openid"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["st4te"]


def test_exchange_returns_user_access_token() -> None:
    oauth, t = _oauth([(200, json.dumps({"accessToken": "UAT-1", "expireIn": 7200}))])
    assert oauth.exchange("authcode-1") == "UAT-1"
    method, url, _headers, body = t.calls[0]
    assert method == "POST"
    assert url == "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
    assert json.loads(body) == {
        "clientId": "app-key", "clientSecret": "app-secret",
        "code": "authcode-1", "grantType": "authorization_code",
    }


def test_exchange_non_200_raises() -> None:
    oauth, _ = _oauth([(400, json.dumps({"message": "invalid code"}))])
    with pytest.raises(ValueError, match="换 token"):
        oauth.exchange("bad")


def test_me_returns_unionid_and_name() -> None:
    oauth, t = _oauth([(200, json.dumps({"unionId": "UNI-9", "nick": "张三"}))])
    info = oauth.me("UAT-1")
    assert info == {"unionid": "UNI-9", "name": "张三"}
    method, url, headers, _body = t.calls[0]
    assert method == "GET"
    assert url == "https://api.dingtalk.com/v1.0/contact/users/me"
    assert headers.get("x-acs-dingtalk-access-token") == "UAT-1"


def test_me_missing_unionid_raises() -> None:
    oauth, _ = _oauth([(200, json.dumps({"nick": "无 union"}))])
    with pytest.raises(ValueError, match="unionId"):
        oauth.me("UAT-1")


def test_userid_by_union_returns_userid() -> None:
    oauth, t = _oauth([(200, json.dumps({"errcode": 0, "result": {"userid": "10076"}}))])
    assert oauth.userid_by_union("APP-TOKEN", "UNI-9") == "10076"
    method, url, _headers, body = t.calls[0]
    assert method == "POST"
    assert url.startswith("https://oapi.dingtalk.com/topapi/user/getbyunionid")
    assert "access_token=APP-TOKEN" in url
    assert json.loads(body) == {"unionid": "UNI-9"}


def test_userid_by_union_errcode_raises() -> None:
    oauth, _ = _oauth([(200, json.dumps({"errcode": 60121, "errmsg": "not found"}))])
    with pytest.raises(ValueError, match="userid"):
        oauth.userid_by_union("APP-TOKEN", "UNI-X")
