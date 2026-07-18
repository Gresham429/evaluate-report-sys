"""清掉三张多维表里的多余列（建表时留下的默认列，非后端 schema 需要的）。

默认**只列出、不删**（dry-run）；加 `--delete` 才真删。删前把每张表的字段全打出来、
逐个标 KEEP/删，好核对。主键/首列多半删不掉，删失败会打印出来、不阻塞其余。
"""

import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.dingtalk.notable import NotableClient  # noqa: E402

# 每张表该保留的列（= 对应后端真正用到的字段）
KEEP: dict[str, set[str]] = {
    "NOTABLE_LEDGER_SHEET": {"记录号", "报告编号", "类别", "生成时间", "经手人", "快照", "报告序号"},
    "NOTABLE_INSTANCE_SHEET": {"编号", "实例"},
    "NOTABLE_BASETABLE_SHEET": {"种类", "键", "类别", "指纹", "内容"},
}


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


def _field_id(field: dict[str, Any]) -> str | None:
    for key in ("id", "fieldId", "uuid"):
        if field.get(key):
            return str(field[key])
    return None


def main() -> None:
    do_delete = "--delete" in sys.argv
    _load_dotenv()
    client = NotableClient(
        _env("YIDA_APP_KEY"), _env("YIDA_APP_SECRET"),
        base_id=_env("NOTABLE_BASE_ID"), operator_id=_env("NOTABLE_OPERATOR_ID"),
    )
    print("模式：", "真删 --delete" if do_delete else "dry-run（只列，不删）")

    for env_key, keep in KEEP.items():
        sheet = _env(env_key)
        print(f"\n=== {env_key} = {sheet} ===")
        fields = client.list_fields(sheet)
        for f in fields:
            name = str(f.get("name"))
            fid = _field_id(f)
            ftype = f.get("type", "?")
            mark = "KEEP" if name in keep else "删"
            print(f"  [{mark}] name={name!r}  type={ftype}  id={fid}")
        extras = [f for f in fields if str(f.get("name")) not in keep]
        if not extras:
            print("  （无多余列）")
            continue
        if not do_delete:
            print("  → 将删：", [str(f.get("name")) for f in extras], "（加 --delete 执行）")
            continue
        for f in extras:
            name, fid = str(f.get("name")), _field_id(f)
            if fid is None:
                print(f"  ✗ {name}：拿不到字段 id，跳过")
                continue
            try:
                client.delete_field(sheet, fid)
                print(f"  ✓ 已删 {name}")
            except RuntimeError as exc:
                print(f"  ✗ {name} 删不掉（多半是主键/首列）：{str(exc)[:120]}")


if __name__ == "__main__":
    main()
