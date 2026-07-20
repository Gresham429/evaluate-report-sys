"""照片上传：小程序 base64 → 钉钉存储 → 可下载 URL（broker 用它落 content.photos）。

用户已定「照片存钉钉多维表附件」。落地：photos 现契约是 `content.photos: string[]`
（URL 列表，record.py / backend.py / model.py 三处钉死），故本模块把照片字节上传到
钉钉获得**可下载 URL**，仍以 URL 串写回 content.photos——办公端零改动。

token 复用同一企业内部应用的 accessToken（由 `token_provider` 注入，通常是
`NotableClient.access_token`，同 identity）。transport 可注入，单测零网络。

**⚠ 待真机校准**：钉钉媒体/存储上传接口的**端点、multipart 字段名、响应里取
可下载 URL 的字段路径**全是按文档假定，未打真实钉钉验证。部署后按既有校准法
（同 whoami / prefillGeo）打一次真机核实，改本文件顶部 `_URL` 与 `_parse_url`。
"""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["DingtalkMedia", "MediaTransport"]

# 待真机校准：钉钉媒体上传端点（候选：钉钉存储空间/media 上传；上传得 mediaId 或 downloadUrl）
_URL = "https://oapi.dingtalk.com/media/upload"

# 同 identity 的 Transport：(method, url, headers, body) -> (status, text)
MediaTransport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, str]]

_BOUNDARY = "----zhengheeSurveyPhotoBoundary"


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  仅钉钉域名
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, f"网络错误：{exc}"


def _multipart(name: str, data: bytes, mime: str) -> tuple[bytes, str]:
    """拼一个最简 multipart/form-data 体（待真机校准：字段名/是否要额外表单项）。"""
    b = _BOUNDARY
    head = (
        f"--{b}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="{name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{b}--\r\n".encode()
    return head + data + tail, f"multipart/form-data; boundary={b}"


def _parse_url(obj: dict[str, Any]) -> str:
    """从钉钉响应取可下载 URL（待真机校准：真实字段名可能是 media_id/downloadUrl/...）。"""
    for key in ("downloadUrl", "url", "media_id", "mediaId"):
        val = obj.get(key)
        if val:
            return str(val)
    result = obj.get("result")
    if isinstance(result, dict):
        for key in ("downloadUrl", "url", "fileId"):
            val = result.get(key)
            if val:
                return str(val)
    return ""


class DingtalkMedia:
    """照片字节 → 钉钉存储 → 可下载 URL。"""

    def __init__(
        self, token_provider: Callable[[], str], *, transport: MediaTransport | None = None
    ) -> None:
        self._token = token_provider
        self._transport = transport or _urllib_transport

    def upload(self, name: str, data: bytes, mime: str = "image/jpeg") -> dict[str, str]:
        """上传一张照片，返回 `{"url":..., "name":...}`。失败一律 ValueError（映射 4xx）。"""
        if not data:
            raise ValueError("照片内容为空")
        url = f"{_URL}?access_token={self._token()}&type=image"  # 待真机校准：查询参数
        body, content_type = _multipart(name or "photo.jpg", data, mime)
        status, text = self._transport("POST", url, {"Content-Type": content_type}, body)
        if status != 200:
            raise ValueError(f"媒体上传 HTTP{status}：{text[:120]}")
        try:
            obj: dict[str, Any] = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"媒体上传响应非 JSON：{exc}") from exc
        if obj.get("errcode"):
            raise ValueError(f"媒体上传失败：{obj.get('errmsg') or obj.get('errcode')}")
        got = _parse_url(obj)
        if not got:
            raise ValueError("媒体上传响应缺可下载 URL（接口形状待真机校准）")
        return {"url": got, "name": name}
