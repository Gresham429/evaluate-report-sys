"""问卷内容字段级三方合并（纯函数，无副作用、不触网）。

办公端回写与手机端保存**走同一套**，故本文件与 `serverless/survey_broker/merge.py`
是字节相同的两份副本（serverless 不能 import `src.*`，见 record.py 顶部注释）。
`tests/test_survey_merge.py` 末尾把两侧对同一 (base,mine,theirs) 的输出对拍，防漂移。

叶子空间只含三块可编辑内容：`basic` / `subject_levels` / `asset_conditions`。
`subjects`(报告产物一览表) / `photos` / `gps`(手机采集) 不参与字段级合并，恒取线上——
办公端不回写这三块，故「我没动→取线上」天然保住对方新加的照片、GPS 与线上一览表。
"""

from typing import Any

__all__ = ["CONTENT_KEYS", "merge_content"]

# 「问卷内容」JSON 的六个顶层键，顺序与 record.CONTENT_KEYS 一致（落库 JSON 字节一致）。
CONTENT_KEYS = ("basic", "subjects", "subject_levels", "asset_conditions", "photos", "gps")

_MERGE_SECTIONS = ("basic", "subject_levels", "asset_conditions")  # 参与字段级合并
_TAKE_THEIRS = ("subjects", "photos", "gps")  # 恒取线上


def _ordered_union(*dicts: dict[str, Any]) -> list[str]:
    """三个 dict 的键并集，按 base→mine→theirs 首见序（稳定、可复现，保留原字段序）。"""
    seen: dict[str, None] = {}
    for d in dicts:
        for k in d:
            if k not in seen:
                seen[k] = None
    return list(seen)


def merge_content(
    base: dict[str, Any], mine: dict[str, Any], theirs: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """三方合并问卷内容。返回 (merged, conflicts)。

    base/mine/theirs 均为 {basic, subjects, subject_levels, asset_conditions, photos, gps}。
    - 逐叶子（三块内容 dict 的键并集）：
      - 我没改(mine==base) → 取线上 theirs；
      - 对方没改(theirs==base) → 取我的 mine；
      - 双方改成同值(mine==theirs) → 取该值（非冲突）；
      - 三者互异 → 记冲突，merged 暂占 mine（待上层按 resolutions 覆盖）。
    - subjects/photos/gps：恒取 theirs（保留线上）。

    conflicts 逐条 `{field, base, mine, theirs}`，field 形如 `basic.client`；
    **不含 label**——展示层（办公前端/小程序）按 field 自行映射标签，保证两侧字节一致。
    """
    merged: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []

    for section in _MERGE_SECTIONS:
        b = base.get(section) or {}
        m = mine.get(section) or {}
        t = theirs.get(section) or {}
        out: dict[str, Any] = {}
        for key in _ordered_union(b, m, t):
            bv, mv, tv = b.get(key), m.get(key), t.get(key)
            if mv == bv:
                chosen = tv  # 我没改 → 取线上
            elif tv == bv:
                chosen = mv  # 对方没改 → 取我的
            elif mv == tv:
                chosen = mv  # 双改成一样 → 一致，非冲突
            else:
                conflicts.append(
                    {"field": f"{section}.{key}", "base": bv, "mine": mv, "theirs": tv}
                )
                chosen = mv  # 暂占我的，待 resolutions 覆盖
            if chosen is not None:
                out[key] = chosen
        merged[section] = out

    for section in _TAKE_THEIRS:
        merged[section] = theirs.get(section)

    # 按 CONTENT_KEYS 重排，落库 JSON 键序与 record 契约一致。
    return {k: merged.get(k) for k in CONTENT_KEYS}, conflicts
