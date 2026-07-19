"""Notable 客户端单元契约：token 缓存/过期重取、分页读、写、容量软告警。

全程假 transport（预置响应），零网络、确定性。真实端点形状在
`tools/notable_backend_smoke.py` 打真库校准，不在此测。
"""

import json
from typing import Any

import pytest

from src.dingtalk.notable import NotableClient

TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"


class FakeTransport:
    """记录每次请求、按脚本回响应。transport 签名 = (method, url, headers, body) -> (status, text)。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._token_calls = 0

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        parsed = json.loads(body) if body else None
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": parsed})
        path = url.split("?", 1)[0]
        if path == TOKEN_URL:
            self._token_calls += 1
            # 每次取 token 给不同值，好断言"缓存命中时没重取"
            return 200, json.dumps({"accessToken": f"tok-{self._token_calls}", "expireIn": 7200})
        if path.endswith("/records/list"):
            return 200, self._list_response(parsed or {})
        if path.endswith("/records"):
            return 200, json.dumps({"value": [{"id": "rec-new"}]})
        return 404, json.dumps({"code": "NotFound"})

    def _list_response(self, body: dict[str, Any]) -> str:
        # 两页：第一页给 nextToken，第二页收尾。按请求里的 nextToken 决定给哪页。
        if not body.get("nextToken"):
            return json.dumps(
                {"records": [{"id": "a", "fields": {"快照": "{\"n\": 1}"}}], "nextToken": "P2"}
            )
        return json.dumps({"records": [{"id": "b", "fields": {"快照": "{\"n\": 2}"}}]})


def _client(transport: FakeTransport) -> NotableClient:
    clock = _FakeClock()
    return NotableClient(
        "ak", "as", base_id="base1", operator_id="op1", transport=transport, clock=clock
    )


class _FakeClock:
    """可推进的时钟，测 token 过期。"""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_token_fetched_once_then_cached() -> None:
    fake = FakeTransport()
    client = _client(fake)
    client.list_records("sheetA")
    client.list_records("sheetA")
    token_calls = [c for c in fake.calls if c["url"] == TOKEN_URL]
    assert len(token_calls) == 1  # 第二次读复用缓存的 token


def test_token_refetched_after_expiry() -> None:
    fake = FakeTransport()
    clock = _FakeClock()
    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=fake, clock=clock)
    client.list_records("s")
    clock.t += 7200  # 过了有效期
    client.list_records("s")
    token_calls = [c for c in fake.calls if c["url"] == TOKEN_URL]
    assert len(token_calls) == 2


def test_list_records_paginates_to_end() -> None:
    fake = FakeTransport()
    records = _client(fake).list_records("sheetA")
    assert [r["id"] for r in records] == ["a", "b"]  # 两页都取到


def test_list_carries_operator_and_token_header() -> None:
    fake = FakeTransport()
    _client(fake).list_records("sheetA")
    list_call = next(c for c in fake.calls if "/records/list" in c["url"])
    assert "op1" in list_call["url"]  # operatorId 进查询串
    assert list_call["headers"]["x-acs-dingtalk-access-token"] == "tok-1"


def test_insert_record_returns_new_id() -> None:
    fake = FakeTransport()
    rid = _client(fake).insert_record("sheetA", {"快照": "{}"})
    assert rid == "rec-new"
    insert_call = next(c for c in fake.calls if c["body"] and "records" in c["body"])
    assert insert_call["body"]["records"][0]["fields"] == {"快照": "{}"}


def test_error_response_raises() -> None:
    def boom(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, str]:
        if url == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        return 403, json.dumps({"code": "Forbidden.AccessDenied", "message": "no perm"})

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=boom)
    with pytest.raises(RuntimeError, match="no perm|Forbidden"):
        client.list_records("s")


def test_get_record_reads_by_id() -> None:
    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        if url.split("?", 1)[0] == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        if method == "GET" and "/records/rec9" in url:
            return 200, json.dumps({"id": "rec9", "fields": {"报告序号": 42}})
        return 404, "{}"

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=transport)
    rec = client.get_record("台账", "rec9")
    assert rec["fields"]["报告序号"] == 42


def test_update_record_issues_put_with_records_body() -> None:
    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        if url.split("?", 1)[0] == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        if method == "PUT" and "/records" in url:
            return 200, json.dumps({"value": [{"id": "rec1"}]})
        return 404, "{}"

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=transport)
    client.update_record("实勘问卷", "rec1", {"状态": "已提交"})


def test_update_record_put_body_carries_id_and_fields() -> None:
    seen: list[dict[str, Any]] = []

    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        if url.split("?", 1)[0] == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        if method == "PUT":
            seen.append({"url": url, "body": json.loads(body) if body else None})
            return 200, "{}"
        return 404, "{}"

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=transport)
    client.update_record("实勘问卷", "rec1", {"状态": "已提交"})
    assert len(seen) == 1
    assert seen[0]["url"].split("?", 1)[0].endswith("/sheets/实勘问卷/records")
    assert seen[0]["body"] == {"records": [{"id": "rec1", "fields": {"状态": "已提交"}}]}


def test_capacity_warning_near_free_limit(caplog: pytest.LogCaptureFixture) -> None:
    def big(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, str]:
        if url == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        page = [{"id": str(i), "fields": {}} for i in range(18000)]
        return 200, json.dumps({"records": page})

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=big)
    with caplog.at_level("WARNING"):
        client.list_records("s")
    assert any("2 万" in r.message or "18000" in r.message or "免费" in r.message for r in caplog.records)


def _token_or(handler: Any) -> Any:
    """包一层：token 请求统一放行，其余交给 handler。"""

    def transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, str]:
        if url.split("?", 1)[0] == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        return handler(method, url.split("?", 1)[0], json.loads(body) if body else None)

    return transport


def test_list_sheets_reads_sheets_array() -> None:
    def handler(method: str, path: str, body: Any) -> tuple[int, str]:
        if method == "GET" and path.endswith("/sheets"):
            return 200, json.dumps({"sheets": [{"name": "台账", "id": "S1"}]})
        return 404, "{}"

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=_token_or(handler))
    assert client.list_sheets() == [{"name": "台账", "id": "S1"}]


def test_create_sheet_returns_response() -> None:
    def handler(method: str, path: str, body: Any) -> tuple[int, str]:
        if method == "POST" and path.endswith("/sheets"):
            return 200, json.dumps({"name": body["name"], "id": "S2"})
        return 404, "{}"

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=_token_or(handler))
    assert client.create_sheet("实例库")["id"] == "S2"


def test_delete_field_issues_delete() -> None:
    deleted: list[str] = []

    def handler(method: str, path: str, body: Any) -> tuple[int, str]:
        if method == "DELETE" and path.endswith("/fields/f1"):
            deleted.append("f1")
            return 200, "{}"
        return 404, "{}"

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=_token_or(handler))
    client.delete_field("s", "f1")
    assert deleted == ["f1"]


def test_ensure_fields_creates_only_missing() -> None:
    created: list[str] = []

    def handler(method: str, path: str, body: Any) -> tuple[int, str]:
        if method == "GET" and path.endswith("/fields"):
            return 200, json.dumps({"fields": [{"name": "标题"}]})
        if method == "POST" and path.endswith("/fields"):
            created.append(body["name"])
            return 200, "{}"
        return 404, "{}"

    client = NotableClient("ak", "as", base_id="b", operator_id="o", transport=_token_or(handler))
    new = client.ensure_fields("s", {"标题": "text", "快照": "text"})
    assert new == ["快照"]
    assert created == ["快照"]


def test_online_true_when_list_sheets_succeeds() -> None:
    def ok_transport(method: str, url: str, headers: dict[str, str], body: bytes | None):
        if url.split("?", 1)[0] == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        return 200, json.dumps({"value": [{"id": "s1", "name": "台账"}]})
    c = NotableClient("ak", "as", base_id="b", operator_id="o", transport=ok_transport)
    assert c.online() is True


def test_online_false_when_transport_errors() -> None:
    def down_transport(method: str, url: str, headers: dict[str, str], body: bytes | None):
        if url.split("?", 1)[0] == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        return 0, "网络错误：timed out"  # 非 200 → _authed 抛 RuntimeError
    c = NotableClient("ak", "as", base_id="b", operator_id="o", transport=down_transport)
    assert c.online() is False


def test_online_false_on_malformed_200_response() -> None:
    """回归测试：HTTP 200 但响应体畸形（JSON 数组而非对象）不应崩溃 online()。"""
    def weird_transport(method: str, url: str, headers: dict[str, str], body: bytes | None):
        if url.split("?", 1)[0] == TOKEN_URL:
            return 200, json.dumps({"accessToken": "t", "expireIn": 7200})
        # 返回 HTTP 200 但体是 JSON 数组，不是对象 → list_sheets 会在其上 .get() → AttributeError
        return 200, "[]"
    c = NotableClient("ak", "as", base_id="b", operator_id="o", transport=weird_transport)
    assert c.online() is False  # 必须返回 False，不能抛异常


def test_client_accepts_timeout_param() -> None:
    c = NotableClient("ak", "as", base_id="b", operator_id="o", timeout=5.0)
    assert c._timeout == 5.0
