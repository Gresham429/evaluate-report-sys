"""可见/编辑/定稿 三判定单测（纯逻辑）。"""

from src.questionnaire.permissions import Viewer, can_edit, can_finalize, can_see

OWNERS = ["u1", "u2"]  # 一份问卷的共有人


def test_owner_can_see_and_edit_but_not_finalize() -> None:
    v = Viewer(operator="u1", is_admin=False, subordinates=frozenset())
    assert can_see(v, OWNERS)
    assert can_edit(v, OWNERS)
    assert not can_finalize(v, OWNERS)  # owner 不能定稿自己的（要上级/管理员）


def test_leader_can_see_and_finalize_but_not_edit() -> None:
    # U 是 u2 的上级（u2 在其下属集）
    v = Viewer(operator="boss", is_admin=False, subordinates=frozenset({"u2", "u9"}))
    assert can_see(v, OWNERS)       # 上级可见
    assert can_finalize(v, OWNERS)  # 上级可定稿
    assert not can_edit(v, OWNERS)  # 上级不改内容


def test_admin_can_do_everything() -> None:
    v = Viewer(operator="root", is_admin=True, subordinates=frozenset())
    assert can_see(v, OWNERS) and can_edit(v, OWNERS) and can_finalize(v, OWNERS)


def test_outsider_sees_nothing() -> None:
    v = Viewer(operator="stranger", is_admin=False, subordinates=frozenset({"x", "y"}))
    assert not can_see(v, OWNERS)
    assert not can_edit(v, OWNERS)
    assert not can_finalize(v, OWNERS)


def test_unidentified_fail_closed() -> None:
    v = Viewer(operator="", is_admin=False, subordinates=frozenset())
    assert not can_see(v, OWNERS)
    assert not can_edit(v, OWNERS)
    assert not can_finalize(v, OWNERS)


def test_cross_department_coowner_visible_to_each_owner() -> None:
    # 跨部门共有：u1、u2 不同部门；u1 本人能看，u2 的上级也能看
    assert can_see(Viewer(operator="u1"), OWNERS)                       # owner 本人
    assert can_see(Viewer(operator="lead2", subordinates=frozenset({"u2"})), OWNERS)  # u2 上级
