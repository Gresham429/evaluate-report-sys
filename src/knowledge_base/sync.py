"""基础表在本地与多维表之间的同步：拉取（多维表→本地并集）、推送（本地一版→多维表）。

D1/D3：基础表存储恒本地；多维表是显式同步目标。版本不可变、按指纹去重，故同步就是
「缺则补」的并集——天然幂等，重复跑不会重写版本、不会重记台账。纯 backend↔backend
拷贝，不碰 store 业务态（指纹校验仍在 store.load 那关把门）。
"""

import logging

from src.knowledge_base.backend import BaseTableBackend
from src.model import Category

logger = logging.getLogger(__name__)

__all__ = ["pull", "push_version", "SyncResult"]

# 每类别：本次新增了几版、库里共几版
SyncResult = dict[str, dict[str, int]]


def _copy_version(dest: BaseTableBackend, src: BaseTableBackend, entry: dict[str, object]) -> bool:
    """把 src 里 entry 指向的那一版拷到 dest；dest 已有则不动。返回是否真拷了。"""
    category = str(entry.get("类别", ""))
    fingerprint = str(entry.get("指纹", ""))
    if not category or not fingerprint or dest.version_exists(category, fingerprint):
        return False
    payload = src.read_version(category, fingerprint)
    if payload is None:
        logger.warning("台账有 %s/%s 但取不到版本内容，跳过", category, fingerprint)
        return False
    dest.write_version(category, fingerprint, payload)
    dest.append_index(dict(entry))
    return True


def pull(dest: BaseTableBackend, src: BaseTableBackend) -> SyncResult:
    """把 src（多维表）所有版本同步进 dest（本地）：本地缺的指纹才写（并集）。

    dest/src 为任一 `BaseTableBackend`。返回 `{类别: {新增, 合计}}`。
    """
    result: SyncResult = {}
    for entry in src.read_index():
        category = str(entry.get("类别", ""))
        if not category:
            continue
        bucket = result.setdefault(category, {"新增": 0, "合计": 0})
        bucket["合计"] += 1
        if _copy_version(dest, src, entry):
            bucket["新增"] += 1
    return result


def push_version(
    dest: BaseTableBackend, src: BaseTableBackend, category: Category, fingerprint: str
) -> bool:
    """把 src（本地）某一版推到 dest（多维表）；dest 已有则不动。返回是否新推。"""
    entry = next(
        (
            e
            for e in src.read_index()
            if str(e.get("类别")) == category.value and str(e.get("指纹")) == fingerprint
        ),
        None,
    )
    return _copy_version(dest, src, entry) if entry is not None else False
