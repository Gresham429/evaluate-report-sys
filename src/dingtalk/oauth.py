"""办公端钉钉扫码登录（OAuth2 授权码流）客户端。

流程：`build_auth_url` 跳钉钉扫码 → `exchange` 拿 userAccessToken → `me` 取 unionId →
`userid_by_union` 换成 **userid**。最后一步必不可少：网页登录得到的是 unionId，而问卷
「填报人」是免登 userid，二者不同源，不换就匹配不到问卷（见
`docs/superpowers/specs/2026-08-13-办公端钉钉扫码登录-design.md` §1）。

HTTP 可注入（同 `NotableClient.Transport` 契约），单测零网络。端点 2026-08-13 按钉钉现行
文档写，**待真机扫一次校准**（同当年免登 `getuserinfo`）——若某处形状不符，只改本文件常量/解析。
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.dingtalk.notable import Transport

__all__ = ["DingtalkOAuth"]

_AUTH_URL = "https://login.dingtalk.com/oauth2/auth"
_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"  # 待真机校准
_ME_URL = "https://api.dingtalk.com/v1.0/contact/users/me"  # 待真机校准
_UNION_URL = "https://oapi.dingtalk.com/topapi/user/getbyunionid"  # 待真机校准


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method)
    for key, val in headers.items():
        req.add_header(key, val)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310  仅钉钉域名
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, f"网络错误：{exc}"


def _json(text: str, what: str) -> dict[str, Any]:
    try:
        obj = json.loads(text) if text else {}
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"{what}非 JSON：{exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"{what}不是对象")
    return obj


class DingtalkOAuth:
    """钉钉网页扫码登录：换 token → 取 unionId → 换 userid。client_id/secret = 应用 AppKey/AppSecret。"""

    def __init__(
        self, client_id: str, client_secret: str, *, transport: Transport | None = None
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport: Transport = transport or _urllib_transport

    def build_auth_url(self, redirect_uri: str, state: str, *, scope: str = "openid") -> str:
        """扫码登录授权页 URL。state 由调用方生成并存会话，回调时对拍防 CSRF。"""
        query = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scope,
                "prompt": "consent",
                "state": state,
            }
        )
        return f"{_AUTH_URL}?{query}"

    def exchange(self, code: str) -> str:
        """authCode → userAccessToken。失败一律 ValueError（上层映射成 4xx/提示）。"""
        body = json.dumps(
            {
                "clientId": self._client_id,
                "clientSecret": self._client_secret,
                "code": code,
                "grantType": "authorization_code",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        status, text = self._transport(
            "POST", _TOKEN_URL, {"Content-Type": "application/json"}, body
        )
        obj = _json(text, "换 token 响应")
        if status != 200:
            raise ValueError(f"换 token HTTP{status}：{obj.get('message') or text[:120]}")
        token = str(obj.get("accessToken") or "")
        if not token:
            raise ValueError("换 token 响应缺 accessToken（接口形状待校准）")
        return token

    def me(self, user_access_token: str) -> dict[str, str]:
        """userAccessToken → {"unionid":..., "name":...}。缺 unionId 抛 ValueError。"""
        status, text = self._transport(
            "GET", _ME_URL, {"x-acs-dingtalk-access-token": user_access_token}, None
        )
        obj = _json(text, "用户信息响应")
        if status != 200:
            raise ValueError(f"取用户信息 HTTP{status}：{obj.get('message') or text[:120]}")
        unionid = str(obj.get("unionId") or "")
        if not unionid:
            raise ValueError("用户信息缺 unionId（接口形状待校准）")
        return {"unionid": unionid, "name": str(obj.get("nick") or "")}

    def userid_by_union(self, app_token: str, unionid: str) -> str:
        """unionId → userid（用应用 accessToken 调通讯录）。与问卷「填报人」同源的关键一步。"""
        url = f"{_UNION_URL}?access_token={urllib.parse.quote(app_token)}"
        body = json.dumps({"unionid": unionid}, ensure_ascii=False).encode("utf-8")
        status, text = self._transport("POST", url, {"Content-Type": "application/json"}, body)
        obj = _json(text, "getbyunionid 响应")
        if status != 200:
            raise ValueError(f"getbyunionid HTTP{status}：{text[:120]}")
        if obj.get("errcode"):
            raise ValueError(f"unionId 换 userid 失败：{obj.get('errmsg') or obj.get('errcode')}")
        userid = str((obj.get("result") or {}).get("userid") or "")
        if not userid:
            raise ValueError("getbyunionid 缺 userid（接口形状待校准）")
        return userid
