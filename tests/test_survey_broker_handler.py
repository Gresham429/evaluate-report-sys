"""dispatch() 路由单测：假 store/amap/identity，零网络、不碰真正的客户端/FC 入口。"""

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
        owners: list[str] | None = None,
        base: dict[str, Any] | None = None,
        resolutions: dict[str, Any] | None = None,
    ) -> str:
        sid = survey_id or "generated-id"
        self.last_base = base            # 供测试断言 handler 确实透传了 base
        self.last_resolutions = resolutions
        self.rows[sid] = {
            "survey_id": sid,
            "status": "草稿",
            "filler": filler,
            "category": category,
            "updated_at": updated_at,
            "content": content,
            "owners": owners,
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

    def delete(self, survey_id: str) -> None:
        if survey_id not in self.rows:
            raise KeyError(f"未找到问卷：{survey_id}")
        if self.rows[survey_id].get("status") == "已提交":
            raise ValueError("已提交问卷不可删除")
        del self.rows[survey_id]

    def list_for_user(self, userid: str) -> list[dict[str, Any]]:
        return [
            {"survey_id": sid, "status": r.get("status", ""),
             "category": r.get("category", ""), "updated_at": r.get("updated_at", "")}
            for sid, r in self.rows.items() if userid in (r.get("owners") or [r.get("filler")])
        ]


class FakeAmap:
    """内存假 amap：够 dispatch 用的 prefill_geo 一个方法。"""

    def prefill_geo(self, lng: float, lat: float) -> dict[str, Any]:
        return {"address": f"{lng},{lat}", "bus_stops": [], "nearest_metro": None, "facilities": []}


class FakeIdentity:
    """内存假 identity：够 dispatch 用的 whoami 一个方法。'good' 通过，其余 ValueError。"""

    def whoami(self, auth_code: str) -> dict[str, object]:
        if auth_code == "good":
            return {"userid": "u1", "name": "张三"}
        raise ValueError("bad code")


class FakeMedia:
    """内存假 media：回显收到的字节长度，够 dispatch 用的 upload 一个方法。"""

    def __init__(self) -> None:
        self.last: bytes | None = None

    def upload(self, name: str, data: bytes, mime: str = "image/jpeg") -> dict[str, str]:
        self.last = data
        return {"url": f"https://dl/{name}?len={len(data)}", "name": name}


def test_dispatch_save_draft_happy_path() -> None:
    store = FakeStore()
    status, body = dispatch(
        "saveDraft",
        {"filler": "张三", "category": "住宅", "updated_at": "t1", "content": {}},
        store=store,
        amap=FakeAmap(),
        identity=FakeIdentity(),
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
        identity=FakeIdentity(),
    )
    assert status == 200
    assert body == {"survey_id": "q-fixed"}


def test_dispatch_save_draft_forwards_base_and_resolutions() -> None:
    """双向同步：handler 把 base + resolutions 透传给 store。"""
    store = FakeStore()
    dispatch(
        "saveDraft",
        {"filler": "张三", "category": "住宅", "updated_at": "t1", "content": {},
         "base": {"basic": {"a": "1"}}, "resolutions": {"basic.a": "x"}},
        store=store, amap=FakeAmap(), identity=FakeIdentity(),
    )
    assert store.last_base == {"basic": {"a": "1"}}
    assert store.last_resolutions == {"basic.a": "x"}


def test_dispatch_unexpected_error_maps_to_500() -> None:
    """未预期异常（如 NotableClient 的 RuntimeError）→ 干净 500 + 消息，而非不透明崩溃。"""
    class BoomStore(FakeStore):
        def load(self, survey_id: str) -> dict[str, Any]:
            raise RuntimeError("多维表挂了")

    status, body = dispatch(
        "loadDraft", {"survey_id": "x"},
        store=BoomStore(), amap=FakeAmap(), identity=FakeIdentity(),
    )
    assert status == 500
    assert "多维表挂了" in body["error"]


def test_dispatch_save_draft_conflict_maps_to_conflict_body() -> None:
    """store 抛 SurveyConflict → handler 回 200 + status=conflict + conflicts。"""
    from serverless.survey_broker.store import SurveyConflict

    class ConflictStore(FakeStore):
        def save_draft(self, **kw: Any) -> str:
            raise SurveyConflict([{"field": "basic.a", "base": "0", "mine": "1", "theirs": "2"}], "t2")

    status, body = dispatch(
        "saveDraft",
        {"filler": "张三", "category": "住宅", "updated_at": "t1", "content": {},
         "base": {"basic": {"a": "1"}}},
        store=ConflictStore(), amap=FakeAmap(), identity=FakeIdentity(),
    )
    assert status == 200
    assert body["status"] == "conflict"
    assert body["conflicts"][0]["field"] == "basic.a"
    assert body["theirs_mtime"] == "t2"


def test_dispatch_load_draft_happy_path() -> None:
    store = FakeStore()
    store.rows["q1"] = {"survey_id": "q1", "status": "草稿", "filler": "张三"}
    status, body = dispatch(
        "loadDraft", {"survey_id": "q1"}, store=store, amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 200
    assert body["survey_id"] == "q1"


def test_dispatch_submit_happy_path() -> None:
    store = FakeStore()
    store.rows["q1"] = {"survey_id": "q1", "status": "草稿"}
    status, body = dispatch(
        "submit", {"survey_id": "q1"}, store=store, amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 200
    assert body == {"survey_id": "q1"}
    assert store.rows["q1"]["status"] == "已提交"


def test_dispatch_prefill_geo_happy_path() -> None:
    status, body = dispatch(
        "prefillGeo",
        {"lng": 120.1, "lat": 30.2},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
    )
    assert status == 200
    assert body["address"] == "120.1,30.2"


def test_dispatch_whoami_ok() -> None:
    status, body = dispatch(
        "whoami", {"authCode": "good"}, store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 200
    assert body["userid"] == "u1"


def test_dispatch_whoami_bad_code_400() -> None:
    status, body = dispatch(
        "whoami", {"authCode": "nope"}, store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 400
    assert "error" in body


def test_dispatch_whoami_missing_auth_code_400() -> None:
    status, body = dispatch(
        "whoami", {}, store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 400
    assert "error" in body


def test_dispatch_upload_photo_happy_path() -> None:
    import base64

    media = FakeMedia()
    raw = b"\xff\xd8\xffhello-jpeg"
    status, body = dispatch(
        "uploadPhoto",
        {"name": "a.jpg", "dataBase64": base64.b64encode(raw).decode(), "mime": "image/jpeg"},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
        media=media,
    )
    assert status == 200
    assert body["url"].startswith("https://dl/a.jpg")
    assert media.last == raw  # base64 被正确解码成原字节


def test_dispatch_upload_photo_without_media_returns_500() -> None:
    import base64

    status, body = dispatch(
        "uploadPhoto",
        {"name": "a.jpg", "dataBase64": base64.b64encode(b"x").decode()},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
    )
    assert status == 500
    assert "error" in body


def test_dispatch_upload_photo_bad_base64_returns_400() -> None:
    status, body = dispatch(
        "uploadPhoto",
        {"name": "a.jpg", "dataBase64": "!!!not-base64!!!"},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
        media=FakeMedia(),
    )
    assert status == 400
    assert "error" in body


def test_dispatch_upload_photo_missing_data_returns_400() -> None:
    status, body = dispatch(
        "uploadPhoto",
        {"name": "a.jpg"},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
        media=FakeMedia(),
    )
    assert status == 400
    assert "error" in body


def test_dispatch_list_surveys_filters_by_filler() -> None:
    store = FakeStore()
    store.rows["q1"] = {"survey_id": "q1", "status": "已提交", "filler": "u1", "category": "住宅"}
    store.rows["q2"] = {"survey_id": "q2", "status": "草稿", "filler": "u2", "category": "商业"}
    store.rows["q3"] = {"survey_id": "q3", "status": "已提交", "filler": "u1", "category": "农用"}
    status, body = dispatch(
        "listSurveys", {"filler": "u1"}, store=store, amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 200
    ids = {s["survey_id"] for s in body["surveys"]}
    assert ids == {"q1", "q3"}   # 只回 u1 的，不含 u2


def test_dispatch_list_surveys_missing_filler_400() -> None:
    status, body = dispatch(
        "listSurveys", {}, store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 400
    assert "error" in body


def test_dispatch_delete_draft_happy_path() -> None:
    store = FakeStore()
    store.rows["q1"] = {"survey_id": "q1", "status": "草稿"}
    status, body = dispatch(
        "deleteDraft", {"survey_id": "q1"}, store=store, amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 200
    assert body == {"ok": True}
    assert "q1" not in store.rows


def test_dispatch_delete_submitted_returns_400() -> None:
    store = FakeStore()
    store.rows["q1"] = {"survey_id": "q1", "status": "已提交"}
    status, body = dispatch(
        "deleteDraft", {"survey_id": "q1"}, store=store, amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 400
    assert "error" in body
    assert "q1" in store.rows   # 拒删后还在


def test_dispatch_delete_missing_returns_404() -> None:
    status, body = dispatch(
        "deleteDraft", {"survey_id": "ghost"},
        store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity(),
    )
    assert status == 404
    assert "error" in body


def test_dispatch_unknown_action_returns_400() -> None:
    status, body = dispatch(
        "doSomethingElse", {}, store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 400
    assert "error" in body


def test_dispatch_missing_draft_returns_404() -> None:
    status, body = dispatch(
        "loadDraft",
        {"survey_id": "ghost"},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
    )
    assert status == 404
    assert "error" in body


def test_dispatch_submit_missing_draft_returns_404() -> None:
    status, body = dispatch(
        "submit",
        {"survey_id": "ghost"},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
    )
    assert status == 404
    assert "error" in body


def test_dispatch_save_draft_missing_required_field_returns_400() -> None:
    status, body = dispatch(
        "saveDraft", {"filler": "张三"}, store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 400
    assert "error" in body


def test_dispatch_save_draft_non_object_content_returns_400() -> None:
    status, body = dispatch(
        "saveDraft",
        {"filler": "张三", "category": "住宅", "updated_at": "t1", "content": "not-a-dict"},
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
    )
    assert status == 400
    assert "error" in body


def test_dispatch_load_draft_missing_survey_id_returns_400() -> None:
    status, body = dispatch(
        "loadDraft", {}, store=FakeStore(), amap=FakeAmap(), identity=FakeIdentity()
    )
    assert status == 400
    assert "error" in body


def test_dispatch_non_dict_payload_returns_400() -> None:
    # payload 不是对象（如误传数组）→ 400 而非未捕获 500
    status, body = dispatch(
        "saveDraft",
        [1, 2],  # type: ignore[arg-type]
        store=FakeStore(),
        amap=FakeAmap(),
        identity=FakeIdentity(),
    )
    assert status == 400
    assert "error" in body
