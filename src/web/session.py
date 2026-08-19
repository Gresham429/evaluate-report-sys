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

import json
import logging

from src.dingtalk import config, org
from src.paths import app_dir
from src.questionnaire.permissions import Viewer

logger = logging.getLogger(__name__)

# 登录会话落盘文件名（放 exe 旁 / 仓库根）：登录一次，重启/重开仍保持登录。
# 只存 userid + 名字（非密钥）；授权仍按白名单实时判，安全不变。
_SESSION_FILENAME = "登录会话.json"

__all__ = [
    "begin_login",
    "clear_operator",
    "consume_login_state",
    "current_operator",
    "is_admin",
    "is_authorized",
    "is_logged_in",
    "operator_name",
    "persist_login",
    "restore_login",
    "set_operator",
    "viewer",
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


def persist_login() -> None:
    """把当前登录人写盘（无登录人则删文件）。best-effort，失败只告警不影响主流程。

    登录后调它 → 服务重启/重开（关网页自停后再打开）仍保持登录，免每次重扫码。登出后调它删文件。
    """
    path = app_dir() / _SESSION_FILENAME
    try:
        op = _session.get("operator")
        if op:
            path.write_text(
                json.dumps(
                    {"operator": op, "operator_name": _session.get("operator_name", "")},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        else:
            path.unlink(missing_ok=True)
    except OSError:
        logger.warning("登录会话持久化失败：%s", path, exc_info=True)


def restore_login() -> None:
    """启动时从磁盘恢复上次登录（若有）。坏文件/缺文件都不崩，当作未登录。"""
    path = app_dir() / _SESSION_FILENAME
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        uid = str(data.get("operator") or "") if isinstance(data, dict) else ""
    except (OSError, json.JSONDecodeError, ValueError):
        logger.warning("恢复登录会话失败（文件损坏？）：%s", path, exc_info=True)
        return
    if uid:
        _session["operator"] = uid
        _session["operator_name"] = str(data.get("operator_name") or "")
        logger.info("已恢复上次登录：operator=%s", uid)


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


def is_authorized() -> bool:
    """当前用户是否被许可使用办公端（硬门禁用）。

    = 有身份（`current_operator()` 非空——生产配置不设 `OFFICE_OPERATOR_ID`，故等于**必须登录**）
      且（`OFFICE_ALLOWED_USERS` 为空 → 放行任何已识别者；或 operator 在名单内；或是管理员）。
    认不出人（operator=""）一律 False（fail-closed）。仅在钉钉模式下由中间件/前端据此挡人。
    """
    op = current_operator()
    if not op:
        return False
    allowed = config.office_allowed_users()
    return not allowed or op in allowed or is_admin()


def viewer() -> Viewer:
    """当前请求的判定上下文（喂给 `SurveyPullBackend` 逐份判 can_see/can_edit/can_finalize）。

    operator=当前登录人 userid（会话或 .env 过渡，"" 表认不出→fail-closed）；is_admin=在
    OFFICE_ADMINS 名单；subordinates=下属集——`config.use_org()` 开启时由 `org` 按钉钉部门树填
    （fail-closed：未配/未校准/出错→空），默认关时恒空（P1：只有管理员能定稿/看全部）。
    """
    op = current_operator()
    subs = org.subordinates(op) if config.use_org() else frozenset()
    return Viewer(operator=op, is_admin=is_admin(), subordinates=subs)
