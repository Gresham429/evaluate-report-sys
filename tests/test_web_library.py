"""实例库网页接口测试。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.web.app import create_app
from tests.conftest import CASES


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_path = tmp_path / "库.json"
    store = InstanceStore(store_path)
    for case in ("农用", "办公", "商业"):
        for inst in import_from_excel(CASES[case]):
            store.add(inst)
    store.save()
    monkeypatch.setenv("实例库路径", str(store_path))
    return TestClient(create_app())


def test_list_instances_by_category(client: TestClient) -> None:
    r = client.get("/api/instances", params={"category": "办公"})
    assert r.status_code == 200
    items = r.json()["instances"]
    assert len(items) == 3
    assert all(i["类别"] == "办公" for i in items)


def test_list_sorted_newest_first(client: TestClient) -> None:
    """按起始日从新到旧。不做推荐——列表顺序就是全部的"智能"。"""
    items = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    assert items[0]["位置"] == "兴耀科创城A幢09层"
    starts = [i["起始日"] for i in items]
    assert starts == sorted(starts, reverse=True)


def test_year_only_instance_carries_precision_flag(client: TestClient) -> None:
    """仅有年份的实例必须带精度标记，供界面提示。"""
    items = client.get("/api/instances", params={"category": "农用"}).json()["instances"]
    marked = [i for i in items if i["日期精度"] == "仅年"]
    assert len(marked) == 2


def test_no_recommendation_fields_in_payload(client: TestClient) -> None:
    """接口不得返回任何推荐/评分字段——系统不做可比性判断。"""
    items = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    forbidden = {"推荐", "score", "评分", "rank", "排名", "highlight", "高亮", "相似度"}
    for item in items:
        assert not (forbidden & set(item)), f"接口不得含推荐字段：{set(item) & forbidden}"


def test_unknown_category_returns_400(client: TestClient) -> None:
    # 用真正不在枚举里的类别；「工业」等已是合法类别（第六轮新增）。
    r = client.get("/api/instances", params={"category": "别墅"})
    assert r.status_code == 400
