"""dispatch() 路由单测：假 store/amap，零网络、不碰真正的 SurveyBrokerStore/AmapClient/FC 入口。"""

from typing import Any

from serverless.survey_broker.handler import dispatch


class FakeStore:
    """内存假 store：够 dispatch 用的 save_draft/load/submit 三个方法。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def save_draft(
        self,
        *,
        survey_id: str | None,
        filler: str,
        category: str,
        updated_at: str,
        content: dict[str, Any],
    ) -> str:
        sid = survey_id or "generated-id"
        self.rows[sid] = {
            "survey_id": sid,
            "status": "草稿",
            "filler": filler,
            "category": category,
            "updated_at": updated_at,
            "content": content,
        }
        return sid

    def load(self, survey_id: str) -> dict[str, Any]:
        if survey_id not in self.rows:
            raise KeyError(f"未找到问卷：{survey_id}")
        return self.rows[survey_id]

    def submit(self, survey_id: str) -> None:
        if survey_id not in self.rows:
            raise KeyError(f"未找到问卷：{survey_id}")
        self.rows[survey_id]["status"] = "已提交"


class FakeAmap:
    """内存假 amap：够 dispatch 用的 prefill_geo 一个方法。"""

    def prefill_geo(self, lng: float, lat: float) -> dict[str, Any]:
        return {"address": f"{lng},{lat}", "bus_stops": [], "nearest_metro": None, "facilities": []}


def test_dispatch_save_draft_happy_path() -> None:
    store = FakeStore()
    status, body = dispatch(
        "saveDraft",
        {"filler": "张三", "category": "住宅", "updated_at": "t1", "content": {}},
        store=store,
        amap=FakeAmap(),
    )
    assert status == 200
    assert body["survey_id"] in store.rows


def test_dispatch_save_draft_with_given_survey_id() -> None:
    store = FakeStore()
    status, body = dispatch(
        "saveDraft",
        {
            "survey_id": "q-fixed",
            "filler": "张三",
            "category": "住宅",
            "updated_at": "t1",
            "content": {},
        },
        store=store,
        amap=FakeAmap(),
    )
    assert status == 200
    assert body == {"survey_id": "q-fixed"}


def test_dispatch_load_draft_happy_path() -> None:
    store = FakeStore()
    store.rows["q1"] = {"survey_id": "q1", "status": "草稿", "filler": "张三"}
    status, body = dispatch("loadDraft", {"survey_id": "q1"}, store=store, amap=FakeAmap())
    assert status == 200
    assert body["survey_id"] == "q1"


def test_dispatch_submit_happy_path() -> None:
    store = FakeStore()
    store.rows["q1"] = {"survey_id": "q1", "status": "草稿"}
    status, body = dispatch("submit", {"survey_id": "q1"}, store=store, amap=FakeAmap())
    assert status == 200
    assert body == {"survey_id": "q1"}
    assert store.rows["q1"]["status"] == "已提交"


def test_dispatch_prefill_geo_happy_path() -> None:
    status, body = dispatch(
        "prefillGeo", {"lng": 120.1, "lat": 30.2}, store=FakeStore(), amap=FakeAmap()
    )
    assert status == 200
    assert body["address"] == "120.1,30.2"


def test_dispatch_unknown_action_returns_400() -> None:
    status, body = dispatch("doSomethingElse", {}, store=FakeStore(), amap=FakeAmap())
    assert status == 400
    assert "error" in body


def test_dispatch_missing_draft_returns_404() -> None:
    status, body = dispatch("loadDraft", {"survey_id": "ghost"}, store=FakeStore(), amap=FakeAmap())
    assert status == 404
    assert "error" in body


def test_dispatch_submit_missing_draft_returns_404() -> None:
    status, body = dispatch("submit", {"survey_id": "ghost"}, store=FakeStore(), amap=FakeAmap())
    assert status == 404
    assert "error" in body


def test_dispatch_save_draft_missing_required_field_returns_400() -> None:
    status, body = dispatch("saveDraft", {"filler": "张三"}, store=FakeStore(), amap=FakeAmap())
    assert status == 400
    assert "error" in body


def test_dispatch_save_draft_non_object_content_returns_400() -> None:
    status, body = dispatch(
        "saveDraft",
        {"filler": "张三", "category": "住宅", "updated_at": "t1", "content": "not-a-dict"},
        store=FakeStore(),
        amap=FakeAmap(),
    )
    assert status == 400
    assert "error" in body


def test_dispatch_load_draft_missing_survey_id_returns_400() -> None:
    status, body = dispatch("loadDraft", {}, store=FakeStore(), amap=FakeAmap())
    assert status == 400
    assert "error" in body


def test_dispatch_non_dict_payload_returns_400() -> None:
    # payload 不是对象（如误传数组）→ 400 而非未捕获 500
    status, body = dispatch("saveDraft", [1, 2], store=FakeStore(), amap=FakeAmap())  # type: ignore[arg-type]
    assert status == 400
    assert "error" in body
