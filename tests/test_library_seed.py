"""默认实例库首次播种：全新装拷入、有则不覆盖、无资源则跳过。"""

import json
from pathlib import Path

from src.library.seed import seed_default_instances_if_empty


def _resource(tmp: Path, data: list[dict]) -> Path:
    f = tmp / "默认实例库.json"
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return f


def test_seeds_when_local_empty(tmp_path: Path) -> None:
    res = _resource(tmp_path, [{"编号": "农用-a"}, {"编号": "办公-b"}])
    dest = tmp_path / "data" / "实例库.json"
    assert seed_default_instances_if_empty(dest, res) == 1
    assert dest.exists()
    assert [x["编号"] for x in json.loads(dest.read_text(encoding="utf-8"))] == ["农用-a", "办公-b"]


def test_skips_and_never_overwrites_existing(tmp_path: Path) -> None:
    res = _resource(tmp_path, [{"编号": "默认"}])
    dest = tmp_path / "实例库.json"
    dest.write_text('[{"编号":"用户已攒"}]', encoding="utf-8")
    assert seed_default_instances_if_empty(dest, res) == 0
    assert "用户已攒" in dest.read_text(encoding="utf-8")  # 不覆盖


def test_skips_when_no_resource(tmp_path: Path) -> None:
    assert seed_default_instances_if_empty(tmp_path / "实例库.json", tmp_path / "缺.json") == 0
