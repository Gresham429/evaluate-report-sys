"""闭环测试：/api/import、/api/library、/api/compute。

第一等测试是 test_swapping_selection_changes_result——不是复现 2.83，而是
换一条选中的实例后结果必须跟着变。上一轮的教训：拿金样自己的数据算，
当然能复现；验不出"界面选了实例，但压根没接进引擎"这种半成品。
"""

import os
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from src.engine.inputs import from_excel
from src.knowledge_base.store import BaseTableStore
from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.web.app import create_app
from tests.conftest import CASES

# 办公三条种子实例（E/F/G 列顺序）与 Excel 里原始填写的市场状况指数。
OFFICE_ORDER = ["兴耀科创城A幢09层", "蓝天国际大厦1幢808", "蓝天国际大厦1幢703"]
OFFICE_MARKET_INDEX = {
    "兴耀科创城A幢09层": 98,
    "蓝天国际大厦1幢808": 95,
    "蓝天国际大厦1幢703": 95,
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """已种好三类共 9 条种子实例的库，与三类基础表。"""
    store_path = tmp_path / "库.json"
    store = InstanceStore(store_path)
    for case in ("农用", "办公", "商业"):
        for inst in import_from_excel(CASES[case]):
            store.add(inst)
    store.save()
    monkeypatch.setenv("实例库路径", str(store_path))
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "基础表"))
    # 基础表得先进库，/api/compute 才有知识可用——正是估价师首次使用时要做的事。
    base = BaseTableStore(tmp_path / "基础表")
    for case in ("农用", "办公", "商业"):
        base.import_from_excel(CASES[case])
    return TestClient(create_app())


def _office_levels() -> dict[str, str]:
    """办公估价对象的 28 个因素档次。

    表单路径由估价师逐个下拉框选出来；此处从金样 Excel 读，好让断言仍能对住
    Excel 的 2.83——测的是引擎与接口，不是估价师的手速。
    """
    return from_excel(CASES["办公"]).subject_levels


@pytest.fixture()
def empty_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """空库，供 /api/import、/api/library 的基本入库测试用。"""
    monkeypatch.setenv("实例库路径", str(tmp_path / "空库.json"))
    return TestClient(create_app())


def _office_ids(client: TestClient) -> dict[str, str]:
    """从库里查到办公三条实例各自的真实编号——不硬编码猜测字符串。"""
    items = client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    return {i["位置"]: i["编号"] for i in items}


def _post_compute(client: TestClient, ids_by_location: dict[str, str]) -> Response:
    """重算。**不传文件**——引擎要的三样来自请求、基础表库、表单的档次。"""
    selected = [
        {"编号": ids_by_location[loc], "市场状况指数": OFFICE_MARKET_INDEX[loc], "备注": ""}
        for loc in OFFICE_ORDER
    ]
    return client.post(
        "/api/compute",
        json={"category": "办公", "subject_levels": _office_levels(), "selected": selected},
    )


def test_compute_with_library_instances_reproduces_golden(client: TestClient) -> None:
    """从库里选出办公那三条原始实例 + 原始市场状况指数(98/95/95)，须精确复现 Excel 的 2.83。"""
    response = _post_compute(client, _office_ids(client))
    assert response.status_code == 200
    body = response.json()
    assert body["比准价格"] == pytest.approx([2.92, 2.77, 2.80], abs=0.011)
    assert body["评估结果"] == pytest.approx(2.83, abs=0.011)
    assert body["离散度"] == pytest.approx(0.05, abs=0.011)


def test_swapping_selection_changes_result(client: TestClient) -> None:
    """换一条选中的实例，评估结果必须跟着变。

    这是整个第二轮的目的。若不变，说明界面选了实例但没接进引擎。
    """
    ids = _office_ids(client)
    before = _post_compute(client, ids)
    assert before.status_code == 200
    before_result = before.json()["评估结果"]
    assert before_result == pytest.approx(2.83, abs=0.011)

    # 把实例A换成一条成交价翻倍的替身：同一因素档次（保证合法），
    # 只动成交价，入库为一条全新编号，再用它替换掉原来的实例A重新选。
    original_a = import_from_excel(CASES["办公"])[0]
    assert original_a.位置 == "兴耀科创城A幢09层"
    stand_in = replace(
        original_a,
        编号="办公-测试替身-兴耀科创城A幢09层",
        成交价=original_a.成交价 * 2,
    )
    store = InstanceStore(Path(os.environ["实例库路径"]))
    store.load()
    assert store.add(stand_in) is True
    store.save()

    swapped_ids = dict(ids)
    swapped_ids["兴耀科创城A幢09层"] = stand_in.编号
    after = _post_compute(client, swapped_ids)
    assert after.status_code == 200
    after_result = after.json()["评估结果"]

    assert after_result != before_result, "换了实例结果却没变——界面选了实例但没接进引擎"


def test_missing_market_index_rejected(client: TestClient) -> None:
    """市场状况指数未填必须 400——系统不推算、不给默认值。"""
    ids = _office_ids(client)
    selected = [
        {"编号": ids[loc], "市场状况指数": "" if loc == OFFICE_ORDER[0] else OFFICE_MARKET_INDEX[loc], "备注": ""}
        for loc in OFFICE_ORDER
    ]
    response = client.post(
        "/api/compute",
        json={"category": "办公", "subject_levels": _office_levels(), "selected": selected},
    )
    assert response.status_code == 400


def test_wrong_selection_count_rejected(client: TestClient) -> None:
    """必须选满 3 条。"""
    ids = _office_ids(client)
    selected = [
        {"编号": ids[OFFICE_ORDER[0]], "市场状况指数": OFFICE_MARKET_INDEX[OFFICE_ORDER[0]], "备注": ""},
        {"编号": ids[OFFICE_ORDER[1]], "市场状况指数": OFFICE_MARKET_INDEX[OFFICE_ORDER[1]], "备注": ""},
    ]
    response = client.post(
        "/api/compute",
        json={"category": "办公", "subject_levels": _office_levels(), "selected": selected},
    )
    assert response.status_code == 400


def test_unknown_id_rejected(client: TestClient) -> None:
    """编号不在库里必须 400，不得静默跳过。"""
    ids = _office_ids(client)
    selected = [
        {"编号": ids[OFFICE_ORDER[0]], "市场状况指数": OFFICE_MARKET_INDEX[OFFICE_ORDER[0]], "备注": ""},
        {"编号": ids[OFFICE_ORDER[1]], "市场状况指数": OFFICE_MARKET_INDEX[OFFICE_ORDER[1]], "备注": ""},
        {"编号": "这个编号不存在于库中", "市场状况指数": 95, "备注": ""},
    ]
    response = client.post(
        "/api/compute",
        json={"category": "办公", "subject_levels": _office_levels(), "selected": selected},
    )
    assert response.status_code == 400


def test_import_extracts_without_persisting(empty_client: TestClient) -> None:
    """导入 3 条，且不落库——库仍是空的。"""
    with CASES["办公"].open("rb") as handle:
        response = empty_client.post(
            "/api/import",
            files={"file": ("办公实勘表、比较法.xlsx", handle, "application/vnd.ms-excel")},
        )
    assert response.status_code == 200
    imported = response.json()["imported"]
    assert len(imported) == 3
    assert all(item["日期精度"] for item in imported)

    listed = empty_client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    assert listed == []


def test_import_rejects_non_xlsx(empty_client: TestClient) -> None:
    response = empty_client.post(
        "/api/import", files={"file": ("a.txt", b"not excel", "text/plain")}
    )
    assert response.status_code == 400


def test_library_adds_confirmed_instances(empty_client: TestClient) -> None:
    """把 /api/import 的返回原样喂给 /api/library，须全部入库。"""
    with CASES["办公"].open("rb") as handle:
        imported = empty_client.post(
            "/api/import",
            files={"file": ("办公实勘表、比较法.xlsx", handle, "application/vnd.ms-excel")},
        ).json()["imported"]

    response = empty_client.post("/api/library", json={"instances": imported})
    assert response.status_code == 200
    body = response.json()
    assert body["added"] == 3
    assert body["skipped"] == []

    listed = empty_client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    assert len(listed) == 3


def test_library_rejects_duplicate_without_overwrite(empty_client: TestClient) -> None:
    """重复编号 skipped，不静默覆盖。"""
    with CASES["办公"].open("rb") as handle:
        imported = empty_client.post(
            "/api/import",
            files={"file": ("办公实勘表、比较法.xlsx", handle, "application/vnd.ms-excel")},
        ).json()["imported"]

    first = empty_client.post("/api/library", json={"instances": imported}).json()
    assert first["added"] == 3

    second = empty_client.post("/api/library", json={"instances": imported}).json()
    assert second["added"] == 0
    assert set(second["skipped"]) == {i["编号"] for i in imported}

    # 未被覆盖：库中仍是 3 条，不是 3 条“重复计入”后的怪状态
    listed = empty_client.get("/api/instances", params={"category": "办公"}).json()["instances"]
    assert len(listed) == 3
