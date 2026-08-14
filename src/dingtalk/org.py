"""组织架构：回答「下属集(U)」——U 主管的部门及所有子孙部门的全体成员 userid。

用途（ACL spec §3 / 统一 spec §8）：办公端权限里「owner 的上级可见/可定稿其问卷」，
等价于「从 U 侧往下展开其主管部门的整棵子树、取全体成员」（U 管 D → 看 D 及所有下级部门的人），
故只需从 U 往下算一次，不必对每个 owner 往上回溯。

**fail-closed**：未配置多维表凭据 / 网络失败 / 端点未校准 / 解析异常 → 一律**空集**，
即退回「只有管理员能定稿/看全部」（= P1 行为）。因此本模块可安全上线：真机把三个
topapi 端点校准通之前，「上级」能力自动等于关闭，不会误放权。

钉钉端点/字段路径按现行文档写、标「# 待真机校准」，HTTP 经 `transport` 注入（单测灌假件、
零网络）。token 复用 `NotableClient.access_token()`（同应用免登共用一枚 token）。
"""

import json
import logging
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from src.dingtalk import config

logger = logging.getLogger(__name__)

__all__ = ["OrgClient", "reset_cache", "subordinates"]

# 下属集缓存 TTL：部门树/成员变动不频繁，进程内按 U 缓存 10 分钟，免每次请求打一串接口。
_TTL = 600.0

# transport：(topapi 路径, 参数) → 解析后的 JSON dict。真件用 urllib 打 oapi，假件供单测。
Transport = Callable[[str, dict[str, Any]], dict[str, Any]]

# fail-closed 捕获面：HTTP(OSError/URLError) + API 报错(RuntimeError) + 解析(KeyError/ValueError/
# TypeError，含 json.JSONDecodeError⊂ValueError) + 客户端形状不符(AttributeError)。任一 → 回空集，
# 不让权限判定因组织架构接口抖动/未校准而崩。
_SAFE_ERRORS = (RuntimeError, OSError, KeyError, ValueError, TypeError, AttributeError)

_cache: dict[str, tuple[float, frozenset[str]]] = {}


class OrgClient:
    """三个钉钉组织架构接口的薄封装（端点/字段 # 待真机校准）。HTTP 经 transport 注入。"""

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def leader_dept_ids(self, userid: str) -> list[int]:
        """U 主管的部门 id（leader=True 的）。# 待真机校准：topapi/v2/user/get.leader_in_dept"""
        obj = self._t("topapi/v2/user/get", {"userid": userid})
        result = obj.get("result") or {}
        return [int(x["dept_id"]) for x in result.get("leader_in_dept", []) if x.get("leader")]

    def sub_dept_ids(self, dept_id: int) -> list[int]:
        """某部门的直接子部门 id。# 待真机校准：topapi/v2/department/listsub.result[].dept_id"""
        obj = self._t("topapi/v2/department/listsub", {"dept_id": dept_id})
        return [int(x["dept_id"]) for x in (obj.get("result") or [])]

    def dept_member_ids(self, dept_id: int) -> list[str]:
        """某部门直属成员 userid。# 待真机校准：topapi/user/listid.result.userid_list"""
        obj = self._t("topapi/user/listid", {"dept_id": dept_id})
        return [str(u) for u in ((obj.get("result") or {}).get("userid_list") or [])]


def _subordinates(userid: str, client: OrgClient) -> frozenset[str]:
    """纯计算：U 主管部门 → 展开整棵子树（防环）→ 各部门成员并集，去掉 U 自己。"""
    all_depts: set[int] = set()
    stack = list(client.leader_dept_ids(userid))
    while stack:
        dept = stack.pop()
        if dept in all_depts:
            continue  # 防环：部门树理论上无环，但接口异常也不该死循环
        all_depts.add(dept)
        stack.extend(client.sub_dept_ids(dept))
    members: set[str] = set()
    for dept in all_depts:
        members.update(client.dept_member_ids(dept))
    members.discard(userid)  # 自己不是自己的下属
    return frozenset(members)


def _oapi_transport(token_provider: Callable[[], str]) -> Transport:
    """真件 transport：oapi topapi 用经典 access_token 查询参数 POST JSON。# 待真机校准。"""

    def _t(path: str, params: dict[str, Any]) -> dict[str, Any]:
        token = token_provider()
        url = f"https://oapi.dingtalk.com/{path}?access_token={token}"
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310  仅钉钉域名
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:  # noqa: S310
            obj: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        # topapi 约定 errcode==0 为成功；非 0 抛出（被 subordinates 的 fail-closed 兜住）。
        if obj.get("errcode", 0) != 0:
            raise RuntimeError(f"钉钉 org 接口错误 {obj.get('errcode')}：{obj.get('errmsg')}")
        return obj

    return _t


def _build_org_client() -> OrgClient | None:
    """按配置造真 OrgClient；未配多维表凭据（无 token 来源）→ None（→ 空下属集）。"""
    client = config.build_client()
    if client is None:
        return None
    return OrgClient(_oapi_transport(client.access_token))


def reset_cache() -> None:
    """清空进程内下属集缓存（登出/切换操作人、或测试用）。"""
    _cache.clear()


def subordinates(
    userid: str, *, now: float | None = None, client: OrgClient | None = None
) -> frozenset[str]:
    """U 的下属集 userid（带 TTL 缓存，fail-closed 回空集）。

    Args:
        userid: 当前操作人 userid；空 → 空集。
        now: 单调时钟读数（缓存判定用）；缺省取 `time.monotonic()`。开这个口子供测试固定时间。
        client: 注入 OrgClient（测试用）；缺省按配置构造真件，未配则空集。

    Returns:
        下属 userid 集合；未配置/出错/无上级关系 → 空集。
    """
    if not userid:
        return frozenset()
    t = time.monotonic() if now is None else now
    hit = _cache.get(userid)
    if hit is not None and t < hit[0]:
        return hit[1]
    try:
        cli = client if client is not None else _build_org_client()
        if cli is None:
            return frozenset()  # 未配置组织架构 → 无上级/下属（P1 行为）
        subs = _subordinates(userid, cli)
    except _SAFE_ERRORS:
        logger.exception("下属集查询失败，回退空集（fail-closed）：userid=%s", userid)
        return frozenset()
    _cache[userid] = (t + _TTL, subs)
    return subs
