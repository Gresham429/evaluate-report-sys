"""session.viewer() 接线：下属集受 config.use_org() 开关控制。

默认关 → 恒空（P1，只 admin 能定稿/看全部）；开启 → 由 org 填（真机校准后生效）。
"""

from collections.abc import Iterator

import pytest

from src.dingtalk import config, org
from src.web import session


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    session.clear_operator()
    org.reset_cache()
    yield
    session.clear_operator()


def test_viewer_subordinates_empty_when_org_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "office_operator", lambda: "u1")
    monkeypatch.setattr(config, "use_org", lambda: False)
    # 即便 org 会返回下属，开关关时也不该被调用/采纳
    monkeypatch.setattr(org, "subordinates", lambda uid, **k: frozenset({"nope"}))
    assert session.viewer().subordinates == frozenset()


def test_viewer_subordinates_filled_when_org_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "office_operator", lambda: "boss")
    monkeypatch.setattr(config, "use_org", lambda: True)
    monkeypatch.setattr(
        org, "subordinates",
        lambda uid, **k: frozenset({"a", "b"}) if uid == "boss" else frozenset(),
    )
    v = session.viewer()
    assert v.operator == "boss"
    assert v.subordinates == frozenset({"a", "b"})
