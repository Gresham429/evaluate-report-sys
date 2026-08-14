"""org.py：下属集(U) = U 主管部门及所有子孙部门的成员并集。

纯算法 + 缓存 + fail-closed 全在这里钉死；真钉钉端点标「# 待真机校准」，不在单测覆盖。
"""

from typing import Any

import pytest

from src.dingtalk import org


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    org.reset_cache()


class FakeOrgClient:
    """内存假 org 客户端：三张表驱动，计数打接口次数（验缓存）。"""

    def __init__(self, leader: dict[str, list[int]], subs: dict[int, list[int]],
                 members: dict[int, list[str]]) -> None:
        self.leader, self.subs, self.members = leader, subs, members
        self.calls = 0

    def leader_dept_ids(self, userid: str) -> list[int]:
        self.calls += 1
        return list(self.leader.get(userid, []))

    def sub_dept_ids(self, dept_id: int) -> list[int]:
        self.calls += 1
        return list(self.subs.get(dept_id, []))

    def dept_member_ids(self, dept_id: int) -> list[str]:
        self.calls += 1
        return list(self.members.get(dept_id, []))


def test_subordinates_union_of_led_dept_and_subtree() -> None:
    c = FakeOrgClient(leader={"U": [100]}, subs={100: [101], 101: [102]},
                      members={100: ["U", "a"], 101: ["b"], 102: ["c"]})
    assert org.subordinates("U", now=0.0, client=c) == frozenset({"a", "b", "c"})


def test_subordinates_excludes_self() -> None:
    c = FakeOrgClient(leader={"U": [100]}, subs={}, members={100: ["U"]})
    assert org.subordinates("U", now=0.0, client=c) == frozenset()


def test_no_leader_dept_is_empty() -> None:
    c = FakeOrgClient(leader={}, subs={}, members={})
    assert org.subordinates("U", now=0.0, client=c) == frozenset()


def test_empty_userid_is_empty() -> None:
    c = FakeOrgClient(leader={"": [1]}, subs={}, members={1: ["x"]})
    assert org.subordinates("", now=0.0, client=c) == frozenset()


def test_cycle_in_dept_tree_guarded() -> None:
    c = FakeOrgClient(leader={"U": [100]}, subs={100: [101], 101: [100]},  # 环
                      members={100: ["a"], 101: ["b"]})
    assert org.subordinates("U", now=0.0, client=c) == frozenset({"a", "b"})


def test_cache_hit_within_ttl_skips_calls() -> None:
    c = FakeOrgClient(leader={"U": [100]}, subs={}, members={100: ["a"]})
    org.subordinates("U", now=0.0, client=c)
    n = c.calls
    got = org.subordinates("U", now=1.0, client=c)   # TTL 内
    assert got == frozenset({"a"})
    assert c.calls == n, "缓存命中不应再打钉钉接口"


def test_cache_expiry_refetches() -> None:
    c = FakeOrgClient(leader={"U": [100]}, subs={}, members={100: ["a"]})
    org.subordinates("U", now=0.0, client=c)
    n = c.calls
    org.subordinates("U", now=org._TTL + 1.0, client=c)   # 过期
    assert c.calls > n


def test_fail_closed_on_error() -> None:
    class Boom:
        def leader_dept_ids(self, u: str) -> list[int]:
            raise RuntimeError("net down")

        def sub_dept_ids(self, d: int) -> list[int]:
            return []

        def dept_member_ids(self, d: int) -> list[str]:
            return []

    assert org.subordinates("U", now=0.0, client=Boom()) == frozenset()


def test_unconfigured_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(org, "_build_org_client", lambda: None)
    assert org.subordinates("U", now=0.0) == frozenset()


def test_orgclient_parses_dingtalk_shapes() -> None:
    def transport(path: str, params: dict[str, Any]) -> dict[str, Any]:
        if "user/get" in path:
            return {"result": {"leader_in_dept": [
                {"dept_id": 100, "leader": True}, {"dept_id": 5, "leader": False}]}}
        if "department/listsub" in path:
            return {"result": [{"dept_id": 101}, {"dept_id": 102}]}
        if "user/listid" in path:
            return {"result": {"userid_list": ["a", "b"]}}
        return {}

    c = org.OrgClient(transport)
    assert c.leader_dept_ids("U") == [100]   # 只取 leader=True 的部门
    assert c.sub_dept_ids(100) == [101, 102]
    assert c.dept_member_ids(100) == ["a", "b"]
