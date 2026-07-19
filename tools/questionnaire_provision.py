"""建「实勘问卷」多维表并建齐列（二期账号就位后跑）。

配置从仓库根 .env 读。一期不依赖此脚本——表结构与建列逻辑已在
`src/questionnaire/provision.py` 用假客户端测过。
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.dingtalk.notable import NotableClient  # noqa: E402
from src.questionnaire.provision import ensure_survey_sheet  # noqa: E402


def _load_dotenv() -> None:
    env_file = REPO / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"缺 {name}——填进仓库根 .env。")
    return value


def _find_sheet(client: NotableClient, name: str) -> str | None:
    for sheet in client.list_sheets():
        if sheet.get("name") == name:
            for key in ("id", "sheetId", "sheetIdOrName", "uuid"):
                if sheet.get(key):
                    return str(sheet[key])
    return None


def main() -> None:
    _load_dotenv()
    client = NotableClient(
        _env("YIDA_APP_KEY"), _env("YIDA_APP_SECRET"),
        base_id=_env("NOTABLE_BASE_ID"), operator_id=_env("NOTABLE_OPERATOR_ID"),
    )
    name = "实勘问卷"
    sheet_id = _find_sheet(client, name)
    if sheet_id is None:
        print(f"建表『{name}』…")
        client.create_sheet(name)
        sheet_id = _find_sheet(client, name)
    if sheet_id is None:
        sys.exit(f"建表后仍找不到『{name}』，请在多维表里检查。")
    created = ensure_survey_sheet(client, sheet_id)
    print(f"『{name}』建列：{created or '（都在）'}")


if __name__ == "__main__":
    main()
