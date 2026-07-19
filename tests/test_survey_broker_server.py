"""server.handle：请求体 → dispatch → JSON 字节。纯函数，不碰 socket/网络。"""

import json
from typing import Any

from serverless.survey_broker.server import handle


class FakeStore:
    def __init__(self) -> None:
        self.saved: dict[str, Any] = {}

    def save_draft(
        self, *, survey_id: str | None, filler: str, category: str,
        updated_at: str, content: dict[str, Any],
    ) -> str:
        sid = survey_id or "new-id"
        self.saved[sid] = content
        return sid

    def load(self, survey_id: str) -> dict[str, Any]:
        if survey_id not in self.saved:
            raise KeyError(survey_id)
        return {"survey_id": survey_id, "content": self.saved[survey_id]}

    def submit(self, survey_id: str) -> None:
        if survey_id not in self.saved:
            raise KeyError(survey_id)


class FakeAmap:
    def prefill_geo(self, lng: float, lat: float) -> dict[str, Any]:
        return {"address": "示例地址", "bus_stops": [], "nearest_metro": None, "facilities": []}


def test_handle_save_draft_ok() -> None:
    body = json.dumps(
        {"action": "saveDraft",
         "payload": {"filler": "张三", "category": "住宅", "updated_at": "t", "content": {}}}
    ).encode("utf-8")
    status, out = handle(body, store=FakeStore(), amap=FakeAmap())
    assert status == 200
    assert json.loads(out)["survey_id"]


def test_handle_prefill_geo_ok() -> None:
    body = json.dumps({"action": "prefillGeo", "payload": {"lng": 120.0, "lat": 30.0}}).encode("utf-8")
    status, out = handle(body, store=FakeStore(), amap=FakeAmap())
    assert status == 200
    assert json.loads(out)["address"] == "示例地址"


def test_handle_bad_json_returns_400() -> None:
    status, out = handle(b"{ not json", store=FakeStore(), amap=FakeAmap())
    assert status == 400
    assert "error" in json.loads(out)


def test_handle_non_object_body_returns_400() -> None:
    status, out = handle(b"[1, 2]", store=FakeStore(), amap=FakeAmap())
    assert status == 400
    assert "error" in json.loads(out)


def test_handle_unknown_action_returns_400() -> None:
    body = json.dumps({"action": "nope", "payload": {}}).encode("utf-8")
    status, out = handle(body, store=FakeStore(), amap=FakeAmap())
    assert status == 400


def test_handle_submit_missing_returns_404() -> None:
    body = json.dumps({"action": "submit", "payload": {"survey_id": "ghost"}}).encode("utf-8")
    status, out = handle(body, store=FakeStore(), amap=FakeAmap())
    assert status == 404


def test_handle_downstream_exception_returns_500() -> None:
    # 下游(钉钉)抛非 KeyError/ValueError 异常时，HTTP 边界兜底回 500 而非让进程崩
    class BoomStore:
        def save_draft(self, **kwargs: Any) -> str:
            raise RuntimeError("钉钉炸了")

        def load(self, survey_id: str) -> dict[str, Any]:
            raise RuntimeError("钉钉炸了")

        def submit(self, survey_id: str) -> None:
            raise RuntimeError("钉钉炸了")

    body = json.dumps({"action": "loadDraft", "payload": {"survey_id": "x"}}).encode("utf-8")
    status, out = handle(body, store=BoomStore(), amap=FakeAmap())
    assert status == 500
    assert "error" in json.loads(out)
