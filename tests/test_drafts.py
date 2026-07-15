"""草稿存储测试。

草稿的唯一目的是「填一半别丢」，故测试重点在覆盖语义、往返无损与列表可用性，
而**不在**校验 `数据` 的形状——后端本就不理解它。
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.drafts import Draft, DraftStore

_基准时刻 = datetime(2026, 7, 16, 3, 12, 0)


def _表单数据(报告编号: str = "浙嘉源估字[2026]第001号") -> dict[str, object]:
    """造一份带嵌套、中文与浮点数的表单数据。"""
    return {
        "报告编号": 报告编号,
        "类别": "办公",
        "估价对象": {
            "坐落": "嘉兴市南湖区兴耀科创城A幢09层",
            "一览表": [
                {"分户": "A-901", "面积": 356.29},
                {"分户": "A-902", "面积": 367.4},
            ],
        },
        "因素档次": {"临街状况": "较好", "楼层": "中"},
    }


def test_roundtrip_preserves_nested_and_chinese(tmp_path: Path) -> None:
    """存→取往返无损，含嵌套 dict/list、中文键值与浮点数。"""
    store = DraftStore(tmp_path)
    数据 = _表单数据()
    draft_id = store.save(Draft.new(数据, now=_基准时刻))

    got = store.get(draft_id)
    assert got is not None
    assert got.数据 == 数据
    assert got.id == draft_id
    assert got.更新时间 == _基准时刻


def test_same_id_overwrites_not_appends(tmp_path: Path) -> None:
    """同 id 再存即覆盖，不新增——草稿的核心语义，与实例库的「不覆盖」相反。"""
    store = DraftStore(tmp_path)
    first = Draft.new(_表单数据(), now=_基准时刻)
    draft_id = store.save(first)

    改后 = _表单数据()
    改后["估价对象"] = {"坐落": "改过了"}
    再存 = store.save(Draft.new(改后, draft_id=draft_id, now=datetime(2026, 7, 16, 4, 0)))

    assert 再存 == draft_id, "覆盖不得换 id"
    assert len(store.list_all()) == 1, "覆盖不得新增一份"
    got = store.get(draft_id)
    assert got is not None
    assert got.数据["估价对象"] == {"坐落": "改过了"}, "覆盖后须是新内容"


def test_list_all_newest_first(tmp_path: Path) -> None:
    """列表按更新时间新→旧。"""
    store = DraftStore(tmp_path)
    store.save(Draft.new(_表单数据("旧"), now=datetime(2026, 7, 16, 1, 0)))
    store.save(Draft.new(_表单数据("新"), now=datetime(2026, 7, 16, 9, 0)))
    store.save(Draft.new(_表单数据("中"), now=datetime(2026, 7, 16, 5, 0)))

    assert [d.报告编号 for d in store.list_all()] == ["新", "中", "旧"]


def test_list_all_omits_数据(tmp_path: Path) -> None:
    """列表只给摘要，不带 `数据`——列表页不需要，且可能很大。"""
    store = DraftStore(tmp_path)
    store.save(Draft.new(_表单数据(), now=_基准时刻))

    info = store.list_all()[0]
    assert not hasattr(info, "数据")


def test_flat_fields_extracted(tmp_path: Path) -> None:
    """报告编号/类别 抽出来平铺，供列表展示——估价师要认得出哪份是哪份。"""
    store = DraftStore(tmp_path)
    store.save(Draft.new(_表单数据(), now=_基准时刻))

    info = store.list_all()[0]
    assert info.报告编号 == "浙嘉源估字[2026]第001号"
    assert info.类别 == "办公"
    assert info.更新时间 == _基准时刻


def test_flat_fields_blank_when_absent(tmp_path: Path) -> None:
    """`数据` 里压根没这两个键时留空且不报错——草稿本就可能填一半。"""
    store = DraftStore(tmp_path)
    draft_id = store.save(Draft.new({"随便填了点": "还没填编号"}, now=_基准时刻))

    info = store.list_all()[0]
    assert info.报告编号 == ""
    assert info.类别 == ""

    got = store.get(draft_id)
    assert got is not None
    assert got.数据 == {"随便填了点": "还没填编号"}, "抽不到平铺字段不得影响 数据 本身"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    assert DraftStore(tmp_path).get("根本不存在") is None


def test_remove(tmp_path: Path) -> None:
    """删得掉；删不存在的返回 False。"""
    store = DraftStore(tmp_path)
    draft_id = store.save(Draft.new(_表单数据(), now=_基准时刻))

    assert store.remove(draft_id) is True
    assert store.get(draft_id) is None
    assert store.remove(draft_id) is False, "删不存在的不得报错"


def test_list_all_on_missing_dir_is_empty(tmp_path: Path) -> None:
    """目录不存在时视为无草稿，不炸——首次运行必然如此。"""
    store = DraftStore(tmp_path / "还没建过")
    assert store.list_all() == ()


def test_two_saves_same_instant_get_distinct_ids(tmp_path: Path) -> None:
    """同一时刻连存两份，id 不得相撞——故 id 不依赖时钟精度。"""
    store = DraftStore(tmp_path)
    a = store.save(Draft.new(_表单数据("甲"), now=_基准时刻))
    b = store.save(Draft.new(_表单数据("乙"), now=_基准时刻))

    assert a != b
    assert len(store.list_all()) == 2


def test_report_no_with_unsafe_chars_roundtrips(tmp_path: Path) -> None:
    """报告编号含 `[]`、`/` 等字符仍能存取——id 与报告编号无关，故不受其影响。"""
    store = DraftStore(tmp_path)
    编号 = '浙嘉源估字[2026]第9号/附件*A?"<>|'
    draft_id = store.save(Draft.new(_表单数据(编号), now=_基准时刻))

    got = store.get(draft_id)
    assert got is not None
    assert got.数据["报告编号"] == 编号
    assert store.list_all()[0].报告编号 == 编号


def test_traversal_id_rejected(tmp_path: Path) -> None:
    """id 会从网页请求原样传进来，`../` 这类穿越必须挡住。"""
    store = DraftStore(tmp_path)
    外部文件 = tmp_path.parent / "外部.json"
    外部文件.write_text("{}", encoding="utf-8")

    for 坏 in ("../外部", "a/b", "..", ""):
        with pytest.raises(ValueError):
            store.get(坏)
        with pytest.raises(ValueError):
            store.remove(坏)

    assert 外部文件.exists(), "草稿目录之外的文件不得被删掉"


def test_json_is_human_readable(tmp_path: Path) -> None:
    """草稿文件须人类可读可手改。"""
    store = DraftStore(tmp_path)
    store.save(Draft.new(_表单数据(), now=_基准时刻))

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "兴耀科创城A幢09层" in text, "中文不得被转义成 \\uXXXX"
    assert "\n  " in text, "须缩进换行，不得压成一行"
    assert json.loads(text)["更新时间"] == _基准时刻.isoformat()
