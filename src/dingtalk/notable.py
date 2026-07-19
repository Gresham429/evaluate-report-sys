"""钉钉多维表（notable）客户端：token 缓存 + 读/写记录。

**HTTP 可注入**：`transport` 把"发一个请求"收成一个可替换的可调用对象，
签名 `(method, url, headers, body) -> (status, text)`。单测传假 transport（预置响应），
零网络、确定性；真机传默认的 urllib transport。真实端点形状以
`tools/notable_backend_smoke.py` 打真库校准为准。

记录读写含 `update_record`——**只给可变的「实勘问卷」表用**（草稿续填/提交改状态）；
台账只增不改（铁律 #4）、基础表旧版不覆盖、实例只增不删，都由上层后端"不调 update"
天然满足，客户端本身不做按表种类的强制拦截，靠调用侧约束。
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["NotableClient", "Transport"]

_BASE = "https://api.dingtalk.com"
_TOKEN_URL = f"{_BASE}/v1.0/oauth2/accessToken"
_PAGE_SIZE = 100
_TOKEN_EARLY_REFRESH = 60  # 提前 60s 重取，避开边界
_CAPACITY_WARN = 18000  # 免费额度约 2 万行，到 90% 就告警

# transport 契约：给定 (method, url, headers, body_bytes) → (http_status, response_text)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, str]]


def _make_urllib_transport(timeout: float) -> Transport:
    """按超时秒数生成真实 transport：只访问固定的钉钉域名。"""
    def _transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        req = urllib.request.Request(url, data=body, method=method)
        for key, val in headers.items():
            req.add_header(key, val)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  仅钉钉域名
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            return 0, f"网络错误：{exc}"
    return _transport


class NotableClient:
    """一个多维表（base）上的读写客户端。token 自缓存，按操作人 operatorId 调用。"""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        *,
        base_id: str,
        operator_id: str,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 30.0,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._base_id = base_id
        self._operator_id = operator_id
        self._timeout = timeout
        self._transport: Transport = transport or _make_urllib_transport(timeout)
        self._clock = clock
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------ 鉴权

    def _access_token(self) -> str:
        """企业内部应用 accessToken，带缓存；过期（含提前量）才重取。"""
        if self._token is not None and self._clock() < self._token_expiry:
            return self._token
        status, text = self._raw(
            "POST", _TOKEN_URL, {"Content-Type": "application/json"},
            {"appKey": self._app_key, "appSecret": self._app_secret},
        )
        if status != 200:
            raise RuntimeError(f"取钉钉 accessToken 失败 HTTP{status}: {text[:200]}")
        obj = json.loads(text)
        self._token = str(obj["accessToken"])
        self._token_expiry = self._clock() + float(obj["expireIn"]) - _TOKEN_EARLY_REFRESH
        return self._token

    # ------------------------------------------------------------ 底层请求

    def _raw(
        self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> tuple[int, str]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        return self._transport(method, url, headers, data)

    def _authed(self, method: str, url: str, body: dict[str, Any] | None) -> dict[str, Any]:
        """带 token 调一个多维表接口；非 200 抛 RuntimeError（把钉钉的 message 透出来）。"""
        headers = {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": self._access_token(),
        }
        status, text = self._raw(method, url, headers, body)
        obj: dict[str, Any] = json.loads(text) if text else {}
        if status != 200:
            msg = obj.get("message") or obj.get("code") or text[:200]
            raise RuntimeError(f"多维表接口失败 HTTP{status}: {msg}")
        return obj

    def _records_url(self, sheet: str, suffix: str = "") -> str:
        base = f"{_BASE}/v1.0/notable/bases/{self._base_id}/sheets/{sheet}/records{suffix}"
        return f"{base}?operatorId={urllib.parse.quote(self._operator_id)}"

    # ------------------------------------------------------------ 记录读写

    def list_records(self, sheet: str) -> list[dict[str, Any]]:
        """读全表记录（分页兜到底）。每条形如 {id, fields, createdBy, createdTime, ...}。"""
        url = self._records_url(sheet, "/list")
        out: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            body: dict[str, Any] = {"maxResults": _PAGE_SIZE}
            if next_token:
                body["nextToken"] = next_token
            obj = self._authed("POST", url, body)
            out.extend(obj.get("records", []))
            next_token = obj.get("nextToken")
            if not next_token:
                break
        if len(out) >= _CAPACITY_WARN:
            logger.warning(
                "多维表 %s 已 %d 行，接近免费额度 2 万行——须扩容（钉钉文档企业版）或归档", sheet, len(out)
            )
        return out

    def insert_records(self, sheet: str, fields_list: list[dict[str, Any]]) -> list[str]:
        """批量写记录，返回新行 id 列表。fields 的 key 是多维表字段名。"""
        url = self._records_url(sheet)
        obj = self._authed("POST", url, {"records": [{"fields": f} for f in fields_list]})
        return [str(v["id"]) for v in obj.get("value", [])]

    def insert_record(self, sheet: str, fields: dict[str, Any]) -> str:
        """写一条，返回新行 id。"""
        ids = self.insert_records(sheet, [fields])
        if not ids:
            raise RuntimeError(f"多维表 {sheet} 写入未返回记录 id")
        return ids[0]

    def update_record(self, sheet: str, record_id: str, fields: dict[str, Any]) -> None:
        """更新一行字段（问卷草稿续填/提交改状态用）。**只给可变的实勘问卷表用**——
        台账/实例/基础表后端一律不调它，「只增不改」由调用侧不使用来保证。
        端点形状待真机校准（同 tools/notable_backend_smoke.py 打真库校准）。"""
        url = self._records_url(sheet)  # PUT .../records，body {records:[{id, fields}]}
        self._authed("PUT", url, {"records": [{"id": record_id, "fields": fields}]})

    def get_record(self, sheet: str, record_id: str) -> dict[str, Any]:
        """按记录 id 取一行（领号后回读自动编号用）。返回形如 {id, fields, ...}。"""
        url = self._records_url(sheet, f"/{urllib.parse.quote(record_id)}")
        return self._authed("GET", url, None)

    # ------------------------------------------------------------ 数据表（建表用）

    def _sheets_url(self, suffix: str = "") -> str:
        base = f"{_BASE}/v1.0/notable/bases/{self._base_id}/sheets{suffix}"
        return f"{base}?operatorId={urllib.parse.quote(self._operator_id)}"

    def list_sheets(self) -> list[dict[str, Any]]:
        """列出 base 下的数据表。响应形状兜一下（sheets / value）。"""
        obj = self._authed("GET", self._sheets_url(), None)
        sheets = obj.get("sheets", obj.get("value", []))
        return list(sheets) if isinstance(sheets, list) else []

    def create_sheet(self, name: str) -> dict[str, Any]:
        """建一张数据表，返回原始响应（含新表 id/sheetId，形状待校准）。"""
        return self._authed("POST", self._sheets_url(), {"name": name})

    def online(self) -> bool:
        """轻量在线探测：能列出数据表即在线。抛错/超时视为离线。

        用于 /api/online：不改变任何数据，只探连通性。凡异常一律吞成 False——
        离线的表现就是"探不通"，调用方不需要知道具体炸在哪。
        """
        try:
            self.list_sheets()
            return True
        except Exception:  # noqa: BLE001  探测的契约就是「任何失败都算离线」——含畸形但 200 的响应(list 体/缺字段)引发的 AttributeError/KeyError/TypeError
            return False

    # ------------------------------------------------------------ 字段（建表用）

    def _fields_url(self, sheet: str) -> str:
        base = f"{_BASE}/v1.0/notable/bases/{self._base_id}/sheets/{sheet}/fields"
        return f"{base}?operatorId={urllib.parse.quote(self._operator_id)}"

    def list_fields(self, sheet: str) -> list[dict[str, Any]]:
        """列出某表的字段定义。响应形状按真实接口校准（fields / value 兜一下）。"""
        obj = self._authed("GET", self._fields_url(sheet), None)
        fields = obj.get("fields", obj.get("value", []))
        return list(fields) if isinstance(fields, list) else []

    def create_field(self, sheet: str, name: str, field_type: str = "text") -> None:
        """建一个字段。"""
        self._authed("POST", self._fields_url(sheet), {"name": name, "type": field_type})

    def ensure_fields(self, sheet: str, specs: dict[str, str]) -> list[str]:
        """确保这些字段存在，缺的建掉，返回新建的字段名列表。"""
        existing = {str(f.get("name")) for f in self.list_fields(sheet)}
        created = []
        for name, field_type in specs.items():
            if name not in existing:
                self.create_field(sheet, name, field_type)
                created.append(name)
        return created

    def delete_field(self, sheet: str, field_id: str) -> None:
        """删一个字段（按字段 id）。主键/首列可能删不掉，调用方自行容错。"""
        url = f"{_BASE}/v1.0/notable/bases/{self._base_id}/sheets/{sheet}/fields/{urllib.parse.quote(field_id)}"
        self._authed("DELETE", f"{url}?operatorId={urllib.parse.quote(self._operator_id)}", None)
