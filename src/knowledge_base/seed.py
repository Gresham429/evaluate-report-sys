"""首次运行播种默认基础表：`data/基础表` 为空时，把打包内置的默认版本拷进去。

只在本地**无台账**（全新安装）时执行，绝不覆盖既有版本——遵守 `build_exe` 那条
「升级不覆盖用户数据」的承诺。默认版本随 exe 打包在 `resources/默认基础表/`。
纯文件拷贝，不引 store/openpyxl，首次启动开销可忽略。
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["seed_default_base_tables_if_empty"]

# 必须与 knowledge_base/backend.py 的台账文件名一致（用它判断"本地是否已有基础表"）。
_LEDGER_NAME = "台账.json"


def seed_default_base_tables_if_empty(dest_dir: Path, resources_dir: Path) -> int:
    """dest_dir 无台账时，把 resources_dir 的默认基础表（版本 JSON + 台账）拷进去。

    Returns:
        拷入的文件数。0 = 本地已有数据（跳过，不覆盖）或无资源可拷。
    """
    if (dest_dir / _LEDGER_NAME).exists():
        return 0  # 已有基础表（老用户 / 已播种）→ 绝不覆盖
    if not resources_dir.exists():
        logger.warning("默认基础表资源目录不存在，跳过播种：%s", resources_dir)
        return 0
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in sorted(resources_dir.glob("*.json")):
        shutil.copy2(f, dest_dir / f.name)
        count += 1
    if count:
        logger.info("首次运行：已播种 %d 个默认基础表文件到 %s", count, dest_dir)
    return count
