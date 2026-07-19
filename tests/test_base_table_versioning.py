"""基础表版本管理：生效版本(active) / 同步(sync) / 首次播种(seed)。

全用内存后端与临时目录，零网络、零 Excel。
"""

from pathlib import Path

from src.knowledge_base.active import ACTIVE_NAME, ActiveVersions, active_fingerprint
from src.knowledge_base.backend import InMemoryBaseTableBackend
from src.knowledge_base.seed import seed_default_base_tables_if_empty
from src.knowledge_base.store import BaseTableStore
from src.knowledge_base.sync import pull, push_version
from src.model import Category

_CAT = Category("办公")


def _payload(mark: str) -> dict[str, object]:
    return {"分值标尺": [2, 1, 0, -1, -2], "因素": [{"名称": mark}]}


def _backend_with_versions(*versions: tuple[str, str]) -> InMemoryBaseTableBackend:
    """造一个装了若干版本的内存后端。versions = [(指纹, 导入时间ISO), ...]。"""
    b = InMemoryBaseTableBackend()
    for fp, when in versions:
        b.write_version(_CAT.value, fp, _payload(fp))
        b.append_index(
            {"类别": _CAT.value, "指纹": fp, "导入时间": when, "来源文件名": f"{fp}.xlsx"}
        )
    return b


# ---------------------------------------------------------------- 生效版本


def test_active_roundtrip_and_missing(tmp_path: Path) -> None:
    av = ActiveVersions(tmp_path)
    assert av.get(_CAT) is None
    av.set(_CAT, "fp-a")
    assert av.get(_CAT) == "fp-a"
    assert (tmp_path / ACTIVE_NAME).exists()


def test_active_corrupt_falls_back_to_empty(tmp_path: Path) -> None:
    (tmp_path / ACTIVE_NAME).write_text("{ not json", encoding="utf-8")
    assert ActiveVersions(tmp_path).get(_CAT) is None  # 不崩，当没选


def test_active_fingerprint_uses_selection_when_present(tmp_path: Path) -> None:
    store = BaseTableStore(
        tmp_path, backend=_backend_with_versions(("old", "2026-07-18T09:00:00"),
                                                 ("new", "2026-07-20T09:00:00"))
    )
    av = ActiveVersions(tmp_path)
    av.set(_CAT, "old")  # 显式选旧版
    assert active_fingerprint(store, av, _CAT) == "old"


def test_active_fingerprint_falls_back_to_latest_when_unset(tmp_path: Path) -> None:
    store = BaseTableStore(
        tmp_path, backend=_backend_with_versions(("old", "2026-07-18T09:00:00"),
                                                 ("new", "2026-07-20T09:00:00"))
    )
    assert active_fingerprint(store, ActiveVersions(tmp_path), _CAT) == "new"


def test_active_fingerprint_falls_back_when_selection_gone(tmp_path: Path) -> None:
    store = BaseTableStore(tmp_path, backend=_backend_with_versions(("new", "2026-07-20T09:00:00")))
    av = ActiveVersions(tmp_path)
    av.set(_CAT, "ghost")  # 指向不存在的指纹
    assert active_fingerprint(store, av, _CAT) == "new"  # 回落最新


def test_active_fingerprint_none_when_no_versions(tmp_path: Path) -> None:
    store = BaseTableStore(tmp_path, backend=InMemoryBaseTableBackend())
    assert active_fingerprint(store, ActiveVersions(tmp_path), _CAT) is None


# ---------------------------------------------------------------- 同步


def test_pull_union_and_idempotent() -> None:
    remote = _backend_with_versions(("a", "2026-07-18T09:00:00"), ("b", "2026-07-20T09:00:00"))
    local = InMemoryBaseTableBackend()
    res = pull(local, remote)
    assert res[_CAT.value] == {"新增": 2, "合计": 2}
    assert local.version_exists(_CAT.value, "a") and local.version_exists(_CAT.value, "b")
    # 再拉一次：全在库，新增 0（幂等）
    assert pull(local, remote)[_CAT.value] == {"新增": 0, "合计": 2}


def test_pull_keeps_existing_local() -> None:
    remote = _backend_with_versions(("a", "2026-07-18T09:00:00"), ("b", "2026-07-20T09:00:00"))
    local = _backend_with_versions(("a", "2026-07-18T09:00:00"))  # 本地已有 a
    res = pull(local, remote)
    assert res[_CAT.value] == {"新增": 1, "合计": 2}  # 只补 b
    assert len(local.read_index()) == 2  # a 不重记


def test_push_version() -> None:
    local = _backend_with_versions(("a", "2026-07-20T09:00:00"))
    remote = InMemoryBaseTableBackend()
    assert push_version(remote, local, _CAT, "a") is True
    assert remote.version_exists(_CAT.value, "a")
    assert push_version(remote, local, _CAT, "a") is False  # 已在，不重推
    assert push_version(remote, local, _CAT, "missing") is False  # 本地无此版


# ---------------------------------------------------------------- 首次播种


def test_seed_into_empty(tmp_path: Path) -> None:
    resources = tmp_path / "res"
    resources.mkdir()
    (resources / "台账.json").write_text("[]", encoding="utf-8")
    (resources / "办公-abc.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "data" / "基础表"
    assert seed_default_base_tables_if_empty(dest, resources) == 2
    assert (dest / "台账.json").exists() and (dest / "办公-abc.json").exists()


def test_seed_skips_when_dest_has_ledger(tmp_path: Path) -> None:
    resources = tmp_path / "res"
    resources.mkdir()
    (resources / "台账.json").write_text("[]", encoding="utf-8")
    dest = tmp_path / "data" / "基础表"
    dest.mkdir(parents=True)
    (dest / "台账.json").write_text('[{"existing": true}]', encoding="utf-8")
    assert seed_default_base_tables_if_empty(dest, resources) == 0  # 不覆盖
    assert "existing" in (dest / "台账.json").read_text(encoding="utf-8")


def test_seed_no_resources(tmp_path: Path) -> None:
    assert seed_default_base_tables_if_empty(tmp_path / "data", tmp_path / "nope") == 0


def test_bundled_defaults_seed_and_load_all_seven(tmp_path: Path) -> None:
    """守护打包内置的 7 张默认基础表：能播种、且每类都能载入（指纹自校验通过）。"""
    from src.paths import bundled_dir

    resources = bundled_dir("resources", "默认基础表")
    assert resources.exists(), "resources/默认基础表 缺失——打包播种源没了"
    dest = tmp_path / "基础表"
    assert seed_default_base_tables_if_empty(dest, resources) >= 8  # 7 版 + 台账
    store = BaseTableStore(dest)
    for cat in Category:
        assert store.current(cat) is not None, f"{cat.value} 缺默认基础表"
        store.load(cat)  # 触发指纹自校验，坏了会 ValueError
