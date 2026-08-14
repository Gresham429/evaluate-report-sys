"""多维表承载层配置：全从环境变量读，缺一即视为未配置（回退本地）。

凭据/ID 放仓库根 `.env`（已 gitignore）。**本模块不自动加载 .env**——测试用
monkeypatch 设 env、冒烟脚本自己 load、真运行时在启动处 load，避免 .env 真值
泄进单测。切换开关默认关（`承载后端` 未设即走本地），故不配置就是今天的行为。
"""

import os

from src.dingtalk.notable import NotableClient
from src.dingtalk.oauth import DingtalkOAuth

__all__ = [
    "use_notable",
    "use_org",
    "build_client",
    "build_oauth",
    "login_redirect_uri",
    "office_operator",
    "office_admins",
    "ledger_sheet",
    "instance_sheet",
    "base_table_sheet",
    "survey_sheet",
]

_SWITCH = "承载后端"
_SWITCH_ON = "多维表"


def use_notable() -> bool:
    """总开关：环境变量 `承载后端=多维表` 才把存储切到多维表。"""
    return os.environ.get(_SWITCH, "").strip() == _SWITCH_ON


def use_org() -> bool:
    """是否启用「组织架构上级」（`org.py` 接钉钉部门树填下属集）。**默认关**。

    三个 topapi 端点须真机校准（见 org.py），校准通前保持 P1——`viewer()` 的下属集恒空、
    只有管理员能定稿/看全部。校准通后设 env `组织架构上级=on` 开启，「owner 的上级可见/可定稿」
    才生效。默认关也让不接组织架构的部署（及全部单测）零受影响。
    """
    return os.environ.get("组织架构上级", "").strip() == "on"


def build_client(*, timeout: float = 30.0) -> NotableClient | None:
    """按 env 里的凭据 + baseId + operatorId 造客户端；缺任一返回 None。

    timeout: 传给 NotableClient 的 HTTP 超时。在线探测用短超时（5s），
    常规读写用默认 30s。
    """
    app_key = os.environ.get("YIDA_APP_KEY", "").strip()
    app_secret = os.environ.get("YIDA_APP_SECRET", "").strip()
    base_id = os.environ.get("NOTABLE_BASE_ID", "").strip()
    operator_id = os.environ.get("NOTABLE_OPERATOR_ID", "").strip()
    if not (app_key and app_secret and base_id and operator_id):
        return None
    return NotableClient(
        app_key, app_secret, base_id=base_id, operator_id=operator_id, timeout=timeout
    )


def build_oauth() -> DingtalkOAuth | None:
    """按 env 里的应用凭据造钉钉扫码登录客户端；缺凭据返回 None。

    OAuth2 的 client_id/secret 就是企业内部应用的 AppKey/AppSecret（同多维表那套，
    `YIDA_APP_KEY/SECRET`）——同一个应用，网页登录和多维表读写共用凭据。
    """
    app_key = os.environ.get("YIDA_APP_KEY", "").strip()
    app_secret = os.environ.get("YIDA_APP_SECRET", "").strip()
    if not (app_key and app_secret):
        return None
    return DingtalkOAuth(app_key, app_secret)


def login_redirect_uri() -> str:
    """扫码登录回调地址，须与钉钉后台「安全设置 → 重定向URL」里登记的一字不差。

    默认本机 `http://127.0.0.1:8765/auth/callback`（2026-08-13 已在钉钉后台存上）；
    换端口/形态时用 env `OFFICE_LOGIN_REDIRECT` 覆盖。
    """
    return os.environ.get(
        "OFFICE_LOGIN_REDIRECT", "http://127.0.0.1:8765/auth/callback"
    ).strip()


def office_operator() -> str:
    """办公端当前操作人 **userid**（OFFICE_OPERATOR_ID）——权限「只看自己」的过渡取值。

    **务必与 `NOTABLE_OPERATOR_ID` 区分**：后者是多维表 API 的 operatorId，取的是 **unionId**
    命名空间（`jYDA…` 那种），只用于 API 鉴权；而问卷「填报人」来自钉钉小程序免登，是
    **userid**（如 `10076`）。两者是同一个人的不同 id，字符串比不相等——若拿 unionId 去过滤
    填报人，一条都匹配不上。故办公端身份单列一个 userid 变量。

    登录 UI（步骤 6 钉钉扫码登录，也返回 userid）落地后由 `/auth` 回调覆盖，取值口不变。
    未设时返回空串 → `current_operator()` 走 fail-closed（认不出人就什么都看不到）。
    """
    return os.environ.get("OFFICE_OPERATOR_ID", "").strip()


def office_admins() -> frozenset[str]:
    """管理员 userid 名单（OFFICE_ADMINS，逗号/空格分隔）——名单内的人办公端可看**全部**问卷。

    「部门领导看下属」的简化占位（设计 §5）：接组织架构/角色前，先用一份显式 userid 名单
    放开可见范围。名单外的人＝普通估价师，只看自己（`填报人==自己`）。名单里的 userid 与问卷
    「填报人」同源（钉钉免登 userid）。
    """
    raw = os.environ.get("OFFICE_ADMINS", "")
    return frozenset(raw.replace(",", " ").split())


def ledger_sheet() -> str:
    """台账表的 sheetId/表名（NOTABLE_LEDGER_SHEET）。"""
    return os.environ.get("NOTABLE_LEDGER_SHEET", "").strip()


def instance_sheet() -> str:
    """实例库表的 sheetId/表名（NOTABLE_INSTANCE_SHEET）。"""
    return os.environ.get("NOTABLE_INSTANCE_SHEET", "").strip()


def base_table_sheet() -> str:
    """基础表版本表的 sheetId/表名（NOTABLE_BASETABLE_SHEET）。"""
    return os.environ.get("NOTABLE_BASETABLE_SHEET", "").strip()


def survey_sheet() -> str:
    """实勘问卷表的 sheetId/表名（NOTABLE_SURVEY_SHEET）。办公端拉取已提交问卷用。"""
    return os.environ.get("NOTABLE_SURVEY_SHEET", "").strip()
