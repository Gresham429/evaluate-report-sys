"""多维表承载层真机冒烟：证明"我的代码"能把台账写进多维表、再读回来。

与 notable_smoke.py 的区别：那只是裸接口探针；这个走**真正的 NotableClient +
NotableLedgerBackend**，验证的是承载层代码本身。分三段，逐段打印，按真实报错校准：

  ① 客户端 round-trip（存现有『标题』字段的 JSON → get_record → list 读回）——最稳，先证客户端通。
  ② 领号：读一行的自动编号字段（若台账表没建『报告序号』自动编号字段，会明确报出来）。
  ③ 后端 round-trip：best-effort ensure_fields 建齐台账列，跑 NotableLedgerBackend.append→iter。

配置从仓库根 .env 读（NOTABLE_BASE_ID / NOTABLE_SHEET / NOTABLE_OPERATOR_ID + YIDA_APP_KEY/SECRET）。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.dingtalk.notable import NotableClient  # noqa: E402
from src.ledger.notable_backend import NotableLedgerBackend  # noqa: E402


def _load_dotenv() -> None:
    env_file = REPO / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"缺 {name}——填进仓库根 .env。")
    return value


def main() -> None:
    _load_dotenv()
    client = NotableClient(
        _env("YIDA_APP_KEY"),
        _env("YIDA_APP_SECRET"),
        base_id=_env("NOTABLE_BASE_ID"),
        operator_id=_env("NOTABLE_OPERATOR_ID"),
    )
    sheet = _env("NOTABLE_SHEET")

    print("=== ① 客户端 round-trip（存现有『标题』字段）===")
    marker = f"backend-smoke-{datetime.now():%H%M%S}"
    payload = {"记录号": marker, "报告编号": "第TEST号", "类别": "办公"}
    rid = client.insert_record(sheet, {"标题": json.dumps(payload, ensure_ascii=False)})
    print("  写入 id:", rid)
    got = client.get_record(sheet, rid)
    print("  get_record fields:", json.dumps(got.get("fields", {}), ensure_ascii=False)[:200])
    rows = client.list_records(sheet)
    hit = [r for r in rows if r.get("fields", {}).get("标题", "").startswith("{") and marker in r["fields"]["标题"]]
    print(f"  list 共 {len(rows)} 行；找回我们写的行：{'✅' if hit else '❌'}")

    print("\n=== ② 领号（读自动编号字段『报告序号』）===")
    try:
        from src.dingtalk.report_number import draw_report_number

        number = draw_report_number(client, sheet, year=2026)
        print("  领到号：", number, "✅")
    except RuntimeError as exc:
        print("  领号未通（多半是台账表还没建『报告序号』自动编号字段）：", str(exc)[:160])

    print("\n=== ③ 后端 round-trip（best-effort 建列 + NotableLedgerBackend）===")
    try:
        created = client.ensure_fields(
            sheet,
            {"记录号": "text", "报告编号": "text", "类别": "text", "生成时间": "text", "经手人": "text", "快照": "text"},
        )
        print("  ensure_fields 新建列：", created or "（都已存在）")
        backend = NotableLedgerBackend(client, sheet)
        b_marker = f"be-{datetime.now():%H%M%S}"
        backend.append(b_marker, datetime(2026, 7, 18, 12, 0), {"记录号": b_marker, "类别": "办公", "报告编号": "第BE号"})
        found = [p for p in backend.iter_payloads() if p.get("记录号") == b_marker]
        print(f"  后端 append→iter 复现：{'✅' if found else '❌'}", found[:1])
    except RuntimeError as exc:
        print("  后端 round-trip 未通（多半是建字段接口/权限要校准）：", str(exc)[:200])
        print("  → 不阻塞：客户端已证通（①）；建列端点按此报错校准，或请用户手动加这几列。")


if __name__ == "__main__":
    main()
