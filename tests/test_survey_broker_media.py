"""DingtalkMedia 单测：注入假 transport，零网络。端点/字段仍待真机校准，本测只钉住
解析与失败分支的行为契约（同 identity 的测法）。"""

import json

import pytest

from serverless.survey_broker.media import DingtalkMedia


def _media(status: int, text: str) -> DingtalkMedia:
    calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def transport(method: str, url: str, headers: dict[str, str], body: bytes | None):
        calls.append((method, url, headers, body))
        return status, text

    m = DingtalkMedia(lambda: "tok", transport=transport)
    m._calls = calls  # type: ignore[attr-defined]  测试内省用
    return m


def test_upload_happy_path_returns_url() -> None:
    m = _media(200, json.dumps({"result": {"downloadUrl": "https://dl/x.jpg"}}))
    out = m.upload("x.jpg", b"\xff\xd8\xff", "image/jpeg")
    assert out == {"url": "https://dl/x.jpg", "name": "x.jpg"}
    # 走的是 POST + multipart
    method, url, headers, body = m._calls[0]  # type: ignore[attr-defined]
    assert method == "POST"
    assert "access_token=tok" in url
    assert headers["Content-Type"].startswith("multipart/form-data")
    assert body is not None and b"\xff\xd8\xff" in body


def test_upload_top_level_media_id() -> None:
    m = _media(200, json.dumps({"media_id": "@media123"}))
    assert m.upload("p.jpg", b"data")["url"] == "@media123"


def test_upload_non_200_raises() -> None:
    m = _media(403, "forbidden")
    with pytest.raises(ValueError, match="HTTP403"):
        m.upload("p.jpg", b"data")


def test_upload_errcode_raises() -> None:
    m = _media(200, json.dumps({"errcode": 40001, "errmsg": "invalid token"}))
    with pytest.raises(ValueError, match="媒体上传失败"):
        m.upload("p.jpg", b"data")


def test_upload_missing_url_raises() -> None:
    m = _media(200, json.dumps({"ok": True}))
    with pytest.raises(ValueError, match="待真机校准"):
        m.upload("p.jpg", b"data")


def test_upload_empty_data_raises() -> None:
    m = _media(200, "{}")
    with pytest.raises(ValueError, match="为空"):
        m.upload("p.jpg", b"")


def test_upload_non_json_response_raises() -> None:
    m = _media(200, "<html>not json</html>")
    with pytest.raises(ValueError, match="非 JSON"):
        m.upload("p.jpg", b"data")
