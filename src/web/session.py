"""办公端登录会话：当前操作人 userid。

办公端是单人桌面应用（一个估价师一台机）。登录后把 userid 存进本模块的进程内会话，
之后所有拉取/审核都带上它做权限「只看自己」。

**过渡取值**：钉钉扫码登录 UI 未上前，会话未设时回退到 `.env` 的 `OFFICE_OPERATOR_ID`
（userid，见 `config.office_operator`），让权限链路先跑通；登录 UI 落地后由 `/auth` 回调调
`set_operator` 覆盖，`current_operator` 的取值口不变——登录方式可替换（设计 §4 备选）。
**不用 `NOTABLE_OPERATOR_ID`**：那是多维表 API 的 operatorId（unionId），与问卷「填报人」
（免登 userid）不同源，拿它过滤一条都匹配不上——详见 `config.office_operator` 的说明。

进程内会话状态放模块级容器（非配置常量，是运行期身份），单机单进程足够；不引持久化，
关掉即失效、下次启动重新登录/回退。
"""

import logging

from src.dingtalk import config

logger = logging.getLogger(__name__)

__all__ = [
    "begin_login",
    "clear_operator",
    "consume_login_state",
    "current_operator",
    "is_admin",
    "is_logged_in",
    "operator_name",
    "set_operator",
    "visibility_filter",
]

# 运行期会话：登录后存 {"operator": userid, "operator_name": 名字}；登录中存 {"oauth_state": ...}。
# 用可变容器而非模块级 global 变量，避免 rebind。
_session: dict[str, str] = {}


def set_operator(userid: str, name: str = "") -> None:
    """登录成功后记住当前操作人 userid（+ 显示名）；空 userid 视为登出。"""
    uid = userid.strip()
    if uid:
        _session["operator"] = uid
        _session["operator_name"] = name.strip()
        logger.info("办公端登录：operator=%s（%s）", uid, name.strip() or "无名")
    else:
        _session.pop("operator", None)
        _session.pop("operator_name", None)


def clear_operator() -> None:
    """登出：清掉会话里的操作人（之后 current_operator 回退到 .env 过渡值）。"""
    _session.pop("operator", None)
    _session.pop("operator_name", None)


def operator_name() -> str:
    """当前登录人的显示名（未真登录时为空）。"""
    return _session.get("operator_name", "")


def begin_login(state: str) -> None:
    """开始扫码登录：记下一次性 state，回调时对拍防 CSRF。"""
    _session["oauth_state"] = state


def consume_login_state(state: str) -> bool:
    """回调时校验并**消费** state：与登录时一致才返回 True（用完即弃，防重放）。"""
    expected = _session.pop("oauth_state", None)
    return bool(expected) and expected == state


def is_logged_in() -> bool:
    """当前会话是否已由登录设置过操作人（区分「真登录」与「.env 过渡值」）。"""
    return "operator" in _session


def current_operator() -> str:
    """当前操作人 userid：会话优先，未登录回退 `.env` 的 OFFICE_OPERATOR_ID（过渡）。

    返回空串表示无从识别当前人——上层据此走 fail-closed（权限过滤命中不到任何行）。
    """
    return _session.get("operator") or config.office_operator()


def is_admin() -> bool:
    """当前操作人是否管理员（在 OFFICE_ADMINS 名单里）——管理员办公端可看全部问卷。"""
    op = current_operator()
    return bool(op) and op in config.office_admins()


def visibility_filter() -> str | None:
    """当前操作人能看到的问卷范围，喂给 `SurveyPullBackend` 的 `filler`：

    - `""` 识别不出操作人 → fail-closed（什么都看不到）；
    - `None` 管理员 → 看全部、可审核任何人（不过滤，即「部门领导看下属」简化版）；
    - `userid` 普通估价师 → 只看自己。

    出报告列表、审核列表、拉取、批量审核/定稿全用它，故普通人一律只看自己、管理员一律看全部。
    """
    op = current_operator()
    if not op:
        return ""
    return None if op in config.office_admins() else op
