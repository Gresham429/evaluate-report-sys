"""把本地 `data/基础表` 各类别各版本推送进多维表，作为共享基线（spec §6「现在」）。

多维表是基础表版本的共享真源；本脚本把本机已有的版本推上去，供别的机器「从钉钉拉取」。
幂等：多维表已有的版本（按指纹）跳过。

用法（先在 .env 配好凭据；本脚本会自动 load 仓库根 .env）：
    uv run python tools/base_table_provision.py
需要 env：YIDA_APP_KEY / YIDA_APP_SECRET / NOTABLE_BASE_ID / NOTABLE_OPERATOR_ID
         / NOTABLE_BASETABLE_SHEET（基础表表 sheetId）。与 `承载后端` 开关无关。
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    _load_env(REPO / ".env")
    sys.path.insert(0, str(REPO))

    from src.dingtalk.factory import notable_base_table_backend
    from src.knowledge_base.backend import LocalFileBaseTableBackend
    from src.knowledge_base.store import DEFAULT_STORE_DIR
    from src.knowledge_base.sync import pull

    remote = notable_base_table_backend()
    if remote is None:
        raise SystemExit(
            "多维表未配。需 .env: YIDA_APP_KEY/YIDA_APP_SECRET/NOTABLE_BASE_ID/"
            "NOTABLE_OPERATOR_ID/NOTABLE_BASETABLE_SHEET"
        )

    local_dir = Path(os.environ.get("基础表目录", str(DEFAULT_STORE_DIR)))
    local = LocalFileBaseTableBackend(local_dir)
    print(f"本地基础表目录：{local_dir}")

    # pull(dest, src)=把 src 里 dest 缺的版本拷进 dest。此处 dest=多维表、src=本地 →
    # 即把本地所有版本推上多维表（幂等，已有跳过）。
    result = pull(remote, local)
    total_new = 0
    for cat, counts in sorted(result.items()):
        total_new += counts["新增"]
        print(f"  {cat}: 推送 {counts['新增']} 版 / 本地共 {counts['合计']} 版")
    print(f"完成：新推 {total_new} 版进多维表。基础表页「从钉钉拉取」可验证。")


if __name__ == "__main__":
    main()
