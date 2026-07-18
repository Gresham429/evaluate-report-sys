"""多维表承载层配置：全从环境变量读，缺一即视为未配置（回退本地）。

凭据/ID 放仓库根 `.env`（已 gitignore）。**本模块不自动加载 .env**——测试用
monkeypatch 设 env、冒烟脚本自己 load、真运行时在启动处 load，避免 .env 真值
泄进单测。切换开关默认关（`承载后端` 未设即走本地），故不配置就是今天的行为。
"""

import os

from src.dingtalk.notable import NotableClient

__all__ = [
    "use_notable",
    "build_client",
    "ledger_sheet",
    "instance_sheet",
    "base_table_sheet",
]

_SWITCH = "承载后端"
_SWITCH_ON = "多维表"


def use_notable() -> bool:
    """总开关：环境变量 `承载后端=多维表` 才把存储切到多维表。"""
    return os.environ.get(_SWITCH, "").strip() == _SWITCH_ON


def build_client() -> NotableClient | None:
    """按 env 里的凭据 + baseId + operatorId 造客户端；缺任一返回 None。"""
    app_key = os.environ.get("YIDA_APP_KEY", "").strip()
    app_secret = os.environ.get("YIDA_APP_SECRET", "").strip()
    base_id = os.environ.get("NOTABLE_BASE_ID", "").strip()
    operator_id = os.environ.get("NOTABLE_OPERATOR_ID", "").strip()
    if not (app_key and app_secret and base_id and operator_id):
        return None
    return NotableClient(app_key, app_secret, base_id=base_id, operator_id=operator_id)


def ledger_sheet() -> str:
    """台账表的 sheetId/表名（NOTABLE_LEDGER_SHEET）。"""
    return os.environ.get("NOTABLE_LEDGER_SHEET", "").strip()


def instance_sheet() -> str:
    """实例库表的 sheetId/表名（NOTABLE_INSTANCE_SHEET）。"""
    return os.environ.get("NOTABLE_INSTANCE_SHEET", "").strip()


def base_table_sheet() -> str:
    """基础表版本表的 sheetId/表名（NOTABLE_BASETABLE_SHEET）。"""
    return os.environ.get("NOTABLE_BASETABLE_SHEET", "").strip()
