"""往真多维表「实勘问卷」表塞一行假『已提交』问卷，供办公端拉取真机试跑。

一期没有钉钉小程序产出真问卷，本脚本手工造一行，让你在办公端点
「从实勘问卷拉取」看到并预填出表单——用真 NotableClient 打真库，
补上「办公端读真多维表」这最后一环的真机验证。

用法（仓库根 .env 里要有承载层那套凭据）：
    uv run python tools/survey_seed.py            # 建表(若无)+建列+插一行办公样例
    uv run python tools/survey_seed.py 商业       # 指定类别

跑完照它打印的 sheetId 往 .env 加 NOTABLE_SURVEY_SHEET，再起办公端即可试。
清理：这行在多维表里手删即可（本脚本不自动删，避免误删真数据）。
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.dingtalk.notable import NotableClient  # noqa: E402
from src.questionnaire.backend import response_to_fields  # noqa: E402
from src.questionnaire.model import STATUS_SUBMITTED, SurveyResponse  # noqa: E402
from src.questionnaire.provision import ensure_survey_sheet  # noqa: E402

SHEET_NAME = "实勘问卷"


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


def _sample(category: str) -> SurveyResponse:
    """一行办公样例。档次/描述键随手写，真机以基础表因素名为准（这里只求能被拉出来）。"""
    return SurveyResponse(
        问卷ID=f"seed-{category}-001",
        状态=STATUS_SUBMITTED,
        填报人="现场估价师(seed)",
        更新时间="2026-07-19T12:00:00",
        category=category,
        basic={
            "report_no": "",  # 报告编号办公端出报告时统一领，问卷不填
            "project_name": f"{category}类实勘问卷样例",
            "client": "示例委托人",
            "owner": "示例权利人",
            "usage": category,
            "value_date": "2026-04-20",
            "survey_date": "2026-04-20",
            "address": "杭州市示例路 1 号",
            "scale": "房屋建筑面积 100 平方米",
        },
        subjects=(
            {"index": 1, "owner": "示例权利人", "address": "杭州市示例路 1 号",
             "usage": category, "area": 100.0},
        ),
        subject_levels={"临街状况": "优", "楼层": "中"},
        asset_conditions={"临街状况": "临主干道", "楼层": "6/20 层"},
        photos=("https://example/photo-placeholder.jpg",),
        gps={"lat": 30.20, "lng": 120.20},
    )


def main() -> None:
    _load_dotenv()
    client = NotableClient(
        _env("YIDA_APP_KEY"), _env("YIDA_APP_SECRET"),
        base_id=_env("NOTABLE_BASE_ID"), operator_id=_env("NOTABLE_OPERATOR_ID"),
    )
    category = sys.argv[1] if len(sys.argv) > 1 else "办公"

    sheet_id = _find_sheet(client, SHEET_NAME)
    if sheet_id is None:
        print(f"建表『{SHEET_NAME}』…")
        client.create_sheet(SHEET_NAME)
        sheet_id = _find_sheet(client, SHEET_NAME)
    if sheet_id is None:
        sys.exit(f"建表后仍找不到『{SHEET_NAME}』，去多维表网页确认。")
    print(f"『{SHEET_NAME}』sheetId = {sheet_id}")

    created = ensure_survey_sheet(client, sheet_id)
    print(f"建列：{created or '（六列都在）'}")

    response = _sample(category)
    rid = client.insert_record(sheet_id, response_to_fields(response))
    print(f"已插入假『已提交』问卷：问卷ID={response.问卷ID}  行id={rid}")
    print()
    print("下一步：")
    print(f"  1) 往仓库根 .env 加：NOTABLE_SURVEY_SHEET={sheet_id}")
    print("     （并确认 承载后端=多维表 及那套凭据都在 .env）")
    print("  2) 起办公端，出报告页点『从实勘问卷拉取』，应看到这行并能预填出表单。")
    print("  3) 试完在多维表网页手删该行即可。")


if __name__ == "__main__":
    main()
