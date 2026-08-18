"""办公端硬门禁 + 使用授权：config 名单 / session.is_authorized / 中间件 403 / /api/me。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.dingtalk import config
from src.web import session
from src.web.app import create_app


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    session.clear_operator()
    yield
    session.clear_operator()


# ─────────────────────── config.office_allowed_users

def test_allowed_users_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFICE_ALLOWED_USERS", "u1, u2 u3")
    assert config.office_allowed_users() == frozenset({"u1", "u2", "u3"})


def test_allowed_users_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OFFICE_ALLOWED_USERS", raising=False)
    assert config.office_allowed_users() == frozenset()


# ─────────────────────── session.is_authorized

def test_authorized_needs_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "office_operator", lambda: "")  # 无 .env fallback、无登录
    monkeypatch.setattr(config, "office_allowed_users", lambda: frozenset())
    assert session.is_authorized() is False


def test_authorized_empty_allowlist_allows_any_identified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "office_allowed_users", lambda: frozenset())
    monkeypatch.setattr(config, "office_admins", lambda: frozenset())
    session.set_operator("u1")
    assert session.is_authorized() is True


def test_authorized_only_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "office_allowed_users", lambda: frozenset({"u1"}))
    monkeypatch.setattr(config, "office_admins", lambda: frozenset())
    session.set_operator("u2")
    assert session.is_authorized() is False  # 不在名单
    session.set_operator("u1")
    assert session.is_authorized() is True


def test_authorized_admin_always(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "office_allowed_users", lambda: frozenset({"u1"}))
    monkeypatch.setattr(config, "office_admins", lambda: frozenset({"boss"}))
    session.set_operator("boss")
    assert session.is_authorized() is True  # 管理员即便不在允许名单也可用


# ─────────────────────── 中间件

def _wire(monkeypatch: pytest.MonkeyPatch, *, notable: bool = True, operator: str = "",
          allowed: tuple[str, ...] = (), admins: tuple[str, ...] = ()) -> None:
    monkeypatch.setattr(config, "use_notable", lambda: notable)
    monkeypatch.setattr(config, "office_operator", lambda: operator)
    monkeypatch.setattr(config, "office_allowed_users", lambda: frozenset(allowed))
    monkeypatch.setattr(config, "office_admins", lambda: frozenset(admins))


def test_gate_blocks_unauthorized_notable(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, operator="")  # 未登录/无身份
    r = TestClient(create_app()).get("/api/drafts")
    assert r.status_code == 403


def test_gate_exempts_shell_login_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, operator="")
    c = TestClient(create_app())
    assert c.get("/api/me").status_code == 200
    assert c.get("/api/online").status_code == 200
    assert c.get("/").status_code == 200


def test_gate_passes_when_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, operator="u1")  # 有身份 + 空名单 → 授权
    assert TestClient(create_app()).get("/api/drafts").status_code == 200


def test_gate_blocks_identified_but_not_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, operator="u9", allowed=("u1",))  # 登录了但不在白名单
    assert TestClient(create_app()).get("/api/drafts").status_code == 403


def test_local_mode_no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, notable=False, operator="")  # 本地单机模式 → 不门禁
    assert TestClient(create_app()).get("/api/drafts").status_code == 200


def test_me_reports_gated_and_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, operator="u1")
    body = TestClient(create_app()).get("/api/me").json()
    assert body["gated"] is True
    assert body["authorized"] is True
