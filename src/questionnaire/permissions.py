"""问卷可见/编辑/定稿 三判定（纯逻辑，无网络/无 web 依赖）。

统一设计 §2 的唯一真相：对登录用户与一份问卷（`owners = 共有人`）——
- **可见(读)**：owner 本人 / owner 的上级 / 管理员。
- **可编辑**（改内容 + 加共有人 + 发起审核）：owner 本人 / 管理员。**上级不能改内容**。
- **可定稿**（待审核→已定稿）：owner 的上级 / 管理员。**部门领导审下属**。

`Viewer` 装当前登录人做判定要的三样：userid、是否管理员、下属集（其主管部门及子孙部门
全体成员 userid；P1 无组织架构时为空）。认不出人（operator=""）且非管理员 → 一律 False
（fail-closed）。判定是纯函数，`org` 模块只负责算 `subordinates`，判定本身不触网。
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

__all__ = ["Viewer", "can_edit", "can_finalize", "can_see"]


@dataclass(frozen=True)
class Viewer:
    """一次请求的判定上下文。subordinates=下属集（P1 空、P2 由 org 填）。"""

    operator: str = ""
    is_admin: bool = False
    subordinates: frozenset[str] = field(default_factory=frozenset)

    def _is_leader_of(self, owners: Iterable[str]) -> bool:
        return bool(set(owners) & self.subordinates)

    def _is_owner(self, owners: Iterable[str]) -> bool:
        return bool(self.operator) and self.operator in set(owners)


def can_see(viewer: Viewer, owners: Iterable[str]) -> bool:
    """可见：owner 本人 / owner 的上级 / 管理员。"""
    return viewer.is_admin or viewer._is_owner(owners) or viewer._is_leader_of(owners)


def can_edit(viewer: Viewer, owners: Iterable[str]) -> bool:
    """可编辑内容/加共有人/发起审核：owner 本人 / 管理员（上级不可）。"""
    return viewer.is_admin or viewer._is_owner(owners)


def can_finalize(viewer: Viewer, owners: Iterable[str]) -> bool:
    """可定稿(待审核→已定稿)：owner 的上级 / 管理员（P1 无上级时只管理员）。"""
    return viewer.is_admin or viewer._is_leader_of(owners)
