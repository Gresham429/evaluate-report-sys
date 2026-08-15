"""首次运行播种默认实例库：`data/实例库.json` 不存在时，把打包内置的默认实例拷进去。

与 `knowledge_base/seed.py` 同思路：只在全新安装（本地无实例库）时执行，绝不覆盖用户
已攒的实例（遵守 build_exe「升级不覆盖用户数据」的承诺）。默认实例随 exe 打包在
`resources/默认实例库.json`，由程序在本机解出/拷入——文件名不经用户的解压软件，故绝无
中文名乱码（§坑7：中文文件名进 zip 被第三方解压软件按 GBK 解成乱码、程序按名找不到）。
纯文件拷贝，首次启动开销可忽略。
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["seed_default_instances_if_empty"]


def seed_default_instances_if_empty(dest_path: Path, resource_file: Path) -> int:
    """dest_path（实例库.json）不存在时，把 resource_file 拷成它。

    Returns:
        1 = 已播种；0 = 本地已有实例库（跳过，不覆盖）或无资源可拷。
    """
    if dest_path.exists():
        return 0  # 已有实例库（老用户 / 已播种）→ 绝不覆盖
    if not resource_file.exists():
        logger.warning("默认实例库资源不存在，跳过播种：%s", resource_file)
        return 0
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resource_file, dest_path)
    logger.info("首次运行：已播种默认实例库到 %s", dest_path)
    return 1
