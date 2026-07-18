"""建表 + 全后端真机验证：把承载层剩下的两张表和自动编号字段自己建出来、逐个后端跑通。

分步、每步 try/except、原始响应都打印，一次跑完告诉我哪步通哪步要校准/要权限：
  ① 列现有数据表（学响应形状、拿台账 sheetId）
  ② 建『实例库』『基础表』两张表（已存在则跳过）
  ③ 各表 ensure_fields 建齐列
  ④ 台账建『报告序号』自动编号字段（type 字符串可能要校准）
  ⑤ 三个后端 round-trip：实例 save→load、基础表 write→read、领号

配置从仓库根 .env 读。会往你的『房产评估』base 里建表/列——都可在多维表里删。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.dingtalk.notable import NotableClient  # noqa: E402
from src.knowledge_base.notable_backend import NotableBaseTableBackend  # noqa: E402
from src.library.notable_backend import NotableInstanceBackend  # noqa: E402
from src.dingtalk.report_number import draw_report_number  # noqa: E402


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


def _sheet_id(sheet: dict[str, Any]) -> str | None:
    for key in ("id", "sheetId", "sheetIdOrName", "uuid"):
        if sheet.get(key):
            return str(sheet[key])
    return None


def _find_sheet(client: NotableClient, name: str) -> str | None:
    for sheet in client.list_sheets():
        if sheet.get("name") == name:
            return _sheet_id(sheet)
    return None


def _ensure_sheet(client: NotableClient, name: str) -> str | None:
    existing = _find_sheet(client, name)
    if existing:
        print(f"  『{name}』已存在：{existing}")
        return existing
    print(f"  建表『{name}』…", end=" ")
    try:
        resp = client.create_sheet(name)
        print("响应:", json.dumps(resp, ensure_ascii=False)[:160])
    except RuntimeError as exc:
        print("失败:", str(exc)[:160])
        return None
    return _find_sheet(client, name)  # 回列一次拿 sheetId，避开响应形状不确定


def main() -> None:
    _load_dotenv()
    client = NotableClient(
        _env("YIDA_APP_KEY"), _env("YIDA_APP_SECRET"),
        base_id=_env("NOTABLE_BASE_ID"), operator_id=_env("NOTABLE_OPERATOR_ID"),
    )
    ledger_sheet = _env("NOTABLE_SHEET")

    print("=== ① 列现有数据表 ===")
    try:
        sheets = client.list_sheets()
        for s in sheets:
            print(f"  - name={s.get('name')!r}  id={_sheet_id(s)}")
    except RuntimeError as exc:
        print("  list_sheets 失败（端点/权限要校准）：", str(exc)[:160])
        sheets = []

    print("\n=== ② 建『实例库』『基础表』===")
    inst_sheet = _ensure_sheet(client, "实例库")
    base_sheet = _ensure_sheet(client, "基础表")

    print("\n=== ③ 各表 ensure_fields ===")
    if inst_sheet:
        print("  实例库:", client.ensure_fields(inst_sheet, {"编号": "text", "实例": "text"}) or "（都在）")
    if base_sheet:
        print("  基础表:", client.ensure_fields(
            base_sheet, {"种类": "text", "键": "text", "类别": "text", "指纹": "text", "内容": "text"}) or "（都在）")

    print("\n=== ④ 台账建『报告序号』自动编号字段 ===")
    for field_type in ("autoNumber", "auto_number", "serial"):
        try:
            client.create_field(ledger_sheet, "报告序号", field_type)
            print(f"  用 type={field_type} 建成 ✅")
            break
        except RuntimeError as exc:
            print(f"  type={field_type} 不行：{str(exc)[:120]}")

    print("\n=== ⑤ 三个后端 round-trip ===")
    if inst_sheet:
        try:
            ib = NotableInstanceBackend(client, inst_sheet)
            mk = f"inst-{datetime.now():%H%M%S}"
            ib.save([{"编号": mk, "位置": "A"}])
            ok = any(r.get("编号") == mk for r in ib.load())
            print(f"  实例 save→load：{'✅' if ok else '❌'}")
        except RuntimeError as exc:
            print("  实例后端未通：", str(exc)[:160])
    if base_sheet:
        try:
            bb = NotableBaseTableBackend(client, base_sheet)
            fp = f"fp-{datetime.now():%H%M%S}"
            bb.write_version("办公", fp, {"分值标尺": [2, 1, 0, -1, -2], "因素": []})
            ok = bb.version_exists("办公", fp) and bb.read_version("办公", fp) is not None
            print(f"  基础表 write→read：{'✅' if ok else '❌'}")
        except RuntimeError as exc:
            print("  基础表后端未通：", str(exc)[:160])
    try:
        number = draw_report_number(client, ledger_sheet, year=2026, metadata={"记录号": "领号占位"})
        print("  领号：", number, "✅")
    except RuntimeError as exc:
        print("  领号未通：", str(exc)[:160])


if __name__ == "__main__":
    main()
