"""开发期工具：从三份实勘表 Excel 批量种子导入实例库。

三份素材（农用/办公/商业各一份实勘表、比较法.xlsx）共可抽出 9 条种子实例。
写入 `data/实例库.json`；重复运行不会重复写入——已存在的编号原样跳过
（`InstanceStore.add` 的既有语义，见 src/library/store.py）。

用法：
    uv run python tools/seed_library.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.library.importer import import_from_excel  # noqa: E402
from src.library.store import DEFAULT_STORE_PATH, InstanceStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MATERIALS = Path(__file__).resolve().parents[2] / "案例素材"
SOURCES: dict[str, Path] = {
    "农用": MATERIALS / "农用" / "农用地实勘表、比较法.xlsx",
    "办公": MATERIALS / "办公" / "办公实勘表、比较法.xlsx",
    "商业": MATERIALS / "商业" / "商业实勘表、比较法.xlsx",
}


def main() -> int:
    missing = [str(p) for p in SOURCES.values() if not p.exists()]
    if missing:
        logger.error("素材缺失：%s", missing)
        return 1

    store = InstanceStore(DEFAULT_STORE_PATH)
    store.load()

    added = 0
    skipped: list[str] = []
    for category, path in SOURCES.items():
        instances = import_from_excel(path)
        for inst in instances:
            if store.add(inst):
                added += 1
            else:
                skipped.append(inst.编号)
        logger.info("%s：%s → 抽取 %d 条", category, path.name, len(instances))

    store.save()
    logger.info("已写入 %s：新增 %d 条，跳过 %d 条重复", store.path, added, len(skipped))
    if skipped:
        logger.warning("跳过（编号已存在，未覆盖）：%s", skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
