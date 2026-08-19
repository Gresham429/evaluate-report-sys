"""登录会话持久化：登录后写盘，重启/重开仍保持登录（免每次重扫码）。

真机根因：无窗口服务 + 关网页自停 → 服务频繁自停重启；而登录会话只在内存里，一重启就丢，
用户再打开是空会话 → 又卡「请先登录」（日志证明 OAuth 全程成功、operator 已记入，纯粹是没留住）。
持久化：登录后把 operator 写盘，启动时恢复，登出时清除。授权仍按白名单实时判（安全不变）。
"""

from typing import Any

import pytest

from src.web import session


@pytest.fixture(autouse=True)
def _tmp_session_file(tmp_path: Any, monkeypatch: Any) -> Any:
    # 会话文件重定向到 tmp，隔离、不污染仓库；每个用例干净起步。
    monkeypatch.setattr(session, "app_dir", lambda: tmp_path)
    session.clear_operator()
    yield
    session.clear_operator()


def test_persist_then_restore_survives_restart(tmp_path: Any) -> None:
    session.set_operator("10025", "徐建杭")
    session.persist_login()
    assert (tmp_path / "登录会话.json").exists()

    session._session.clear()          # 模拟服务重启：内存会话没了
    assert session.is_logged_in() is False

    session.restore_login()           # 启动时恢复
    assert session.is_logged_in() is True
    assert session.current_operator() == "10025"
    assert session.operator_name() == "徐建杭"


def test_logout_clears_persisted_file(tmp_path: Any) -> None:
    session.set_operator("10025", "徐建杭")
    session.persist_login()
    f = tmp_path / "登录会话.json"
    assert f.exists()

    session.clear_operator()
    session.persist_login()           # 无 operator → 删文件
    assert not f.exists()
    session.restore_login()           # 恢复也恢复不出登录
    assert session.is_logged_in() is False


def test_restore_without_file_is_noop(tmp_path: Any) -> None:
    session.restore_login()           # 没有文件不报错、不登录
    assert session.is_logged_in() is False


def test_restore_tolerates_corrupt_file(tmp_path: Any) -> None:
    (tmp_path / "登录会话.json").write_text("{ not json", encoding="utf-8")
    session.restore_login()           # 坏文件不崩、当作未登录
    assert session.is_logged_in() is False
