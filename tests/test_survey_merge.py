"""字段级三方合并 `merge_content`：分支穷举 + broker/办公两侧对拍。

合并是纯函数、无副作用、不触网——每条分支都能在这里钉死。broker 侧
（`serverless.survey_broker.merge`）是办公侧（`src.questionnaire.merge`）的独立副本，
末尾契约测试对拍两者对同一 (base,mine,theirs) 输出一致，防悄悄漂移。
"""

from typing import Any

from src.questionnaire.merge import CONTENT_KEYS, merge_content


def _content(**over: Any) -> dict[str, Any]:
    base = {"basic": {}, "subjects": [], "subject_levels": {},
            "asset_conditions": {}, "photos": [], "gps": None}
    base.update(over)
    return base


def test_nobody_changed_returns_base_no_conflict() -> None:
    base = _content(basic={"client": "甲"})
    merged, conflicts = merge_content(base, _content(basic={"client": "甲"}),
                                      _content(basic={"client": "甲"}))
    assert conflicts == []
    assert merged["basic"] == {"client": "甲"}
    assert tuple(merged.keys()) == CONTENT_KEYS  # 六键齐全且有序


def test_only_mine_changed_takes_mine() -> None:
    base = _content(basic={"client": "甲"})
    mine = _content(basic={"client": "乙"})   # 我改了
    theirs = _content(basic={"client": "甲"})  # 对方没动
    merged, conflicts = merge_content(base, mine, theirs)
    assert conflicts == []
    assert merged["basic"]["client"] == "乙"


def test_only_theirs_changed_takes_theirs() -> None:
    base = _content(basic={"client": "甲"})
    mine = _content(basic={"client": "甲"})     # 我没动
    theirs = _content(basic={"client": "丙"})    # 对方改了
    merged, conflicts = merge_content(base, mine, theirs)
    assert conflicts == []
    assert merged["basic"]["client"] == "丙"


def test_different_fields_changed_both_preserved() -> None:
    base = _content(basic={"client": "甲"}, subject_levels={"楼层": "中"})
    mine = _content(basic={"client": "乙"}, subject_levels={"楼层": "中"})    # 只改 basic
    theirs = _content(basic={"client": "甲"}, subject_levels={"楼层": "高"})  # 只改 levels
    merged, conflicts = merge_content(base, mine, theirs)
    assert conflicts == []
    assert merged["basic"]["client"] == "乙"       # 我的 basic 保住
    assert merged["subject_levels"]["楼层"] == "高"  # 对方的 levels 保住


def test_same_field_conflict_recorded_and_tentatively_mine() -> None:
    base = _content(basic={"client": "甲"})
    mine = _content(basic={"client": "乙"})
    theirs = _content(basic={"client": "丙"})
    merged, conflicts = merge_content(base, mine, theirs)
    assert conflicts == [{"field": "basic.client", "base": "甲", "mine": "乙", "theirs": "丙"}]
    assert merged["basic"]["client"] == "乙"  # 暂占我的，待 resolutions 覆盖


def test_same_field_both_changed_same_value_no_conflict() -> None:
    base = _content(basic={"client": "甲"})
    merged, conflicts = merge_content(base, _content(basic={"client": "乙"}),
                                      _content(basic={"client": "乙"}))
    assert conflicts == []
    assert merged["basic"]["client"] == "乙"


def test_photos_gps_subjects_always_take_theirs() -> None:
    base = _content(photos=[], gps=None, subjects=[])
    mine = _content(photos=[], gps=None, subjects=[{"index": 1}])  # 办公端本地一览表（不回写）
    theirs = _content(photos=["p1.jpg"], gps={"lat": 30.0, "lng": 120.0}, subjects=[])
    merged, conflicts = merge_content(base, mine, theirs)
    assert conflicts == []
    assert merged["photos"] == ["p1.jpg"]           # 对方新加的照片保留
    assert merged["gps"] == {"lat": 30.0, "lng": 120.0}
    assert merged["subjects"] == []                  # 恒取线上，不回写办公端一览表


def test_added_field_kept() -> None:
    base = _content(basic={"client": "甲"})
    mine = _content(basic={"client": "甲", "phone": "123"})  # 我新增一个字段
    theirs = _content(basic={"client": "甲"})
    merged, conflicts = merge_content(base, mine, theirs)
    assert conflicts == []
    assert merged["basic"]["phone"] == "123"


def test_asset_conditions_branch() -> None:
    base = _content(asset_conditions={"楼层": "6/20"})
    mine = _content(asset_conditions={"楼层": "6/20"})
    theirs = _content(asset_conditions={"楼层": "8/20"})  # 对方改描述
    merged, conflicts = merge_content(base, mine, theirs)
    assert conflicts == []
    assert merged["asset_conditions"]["楼层"] == "8/20"


# ─────────────────────────────────── broker/办公 契约对拍

def test_broker_and_office_merge_agree() -> None:
    from serverless.survey_broker.merge import merge_content as broker_merge

    base = _content(basic={"client": "甲", "owner": "张"},
                    subject_levels={"楼层": "中", "临街状况": "优"},
                    asset_conditions={"楼层": "6/20"})
    mine = _content(basic={"client": "乙", "owner": "张"},
                    subject_levels={"楼层": "中", "临街状况": "良"},
                    asset_conditions={"楼层": "6/20"})
    theirs = _content(basic={"client": "丙", "owner": "张"},
                      subject_levels={"楼层": "高", "临街状况": "优"},
                      asset_conditions={"楼层": "6/20"}, photos=["p.jpg"])

    assert broker_merge(base, mine, theirs) == merge_content(base, mine, theirs)


def test_broker_and_office_conflict_shape_agree() -> None:
    from serverless.survey_broker.merge import merge_content as broker_merge

    base = _content(basic={"k": "0"})
    mine = _content(basic={"k": "1"})
    theirs = _content(basic={"k": "2"})
    o_merged, o_conf = merge_content(base, mine, theirs)
    b_merged, b_conf = broker_merge(base, mine, theirs)
    assert o_conf == b_conf
    assert o_merged == b_merged
