"""钉钉免登：authCode → userid（+ 姓名）。broker 用它取"填报人"身份。

token 复用同一企业内部应用的 accessToken（由 `token_provider` 注入，通常是
`NotableClient.access_token`）——免登和多维表读写是同一个应用，token 通用。
transport 可注入（同 NotableClient 的 Transport 契约），单测零网络。

免登接口 = `topapi/v2/user/getuserinfo`（access_token 调、body 带 code）——
**2026-07-19 真机验通**：小程序 `dd.getAuthCode` → broker whoami → 换回真名，
入口页「填报人」正确显示；假 code 回「不存在的临时授权码」。端点/解析无需再改。
"""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["DingtalkIdentity", "IdentityTransport"]

# 免登换 userid 的端点（2026-07-19 真机验通，勿改）
_URL = "https://oapi.dingtalk.com/topapi/v2/user/getuserinfo"

# 同 NotableClient.Transport：(method, url, headers, body) -> (status, text)
IdentityTransport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, str]]


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310  仅钉钉域名
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, f"网络错误：{exc}"


class DingtalkIdentity:
    """钉钉免登换身份。"""

    def __init__(
        self, token_provider: Callable[[], str], *, transport: IdentityTransport | None = None
    ) -> None:
        self._token = token_provider
        self._transport = transport or _urllib_transport

    def whoami(self, auth_code: str) -> dict[str, str]:
        """authCode → {"userid":..., "name":...}。无效/失败一律 ValueError（映射成 4xx）。"""
        url = f"{_URL}?access_token={self._token()}"
        body = json.dumps({"code": auth_code}, ensure_ascii=False).encode("utf-8")
        status, text = self._transport("POST", url, {"Content-Type": "application/json"}, body)
        if status != 200:
            raise ValueError(f"免登接口 HTTP{status}：{text[:120]}")
        try:
            obj: dict[str, Any] = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"免登响应非 JSON：{exc}") from exc
        if obj.get("errcode"):
            raise ValueError(f"免登失败：{obj.get('errmsg') or obj.get('errcode')}")
        result = obj.get("result") or {}
        userid = str(result.get("userid") or "")
        if not userid:
            raise ValueError("免登响应缺 userid（接口形状待校准）")
        return {"userid": userid, "name": str(result.get("name") or "")}
