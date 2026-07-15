"""闭环测试：重算出的评估结果必须真的印进报告。

第一等测试是 test_recomputed_result_reaches_the_report——它验的不是「能算」
（那是 test_web_compute 的事），而是**算完的数字有没有走到 docx 里**。
第二轮的教训：引擎会算、界面会显示，但 /api/compute 与 /api/render 之间
没有任何代码相连，生成的报告用的仍是 Excel 里的原单价。这个测试就是拿来
盯住那道缝的：报告里必须出现重算值，且不得残留 Excel 原值 2.83。
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.engine.inputs import from_excel
from src.knowledge_base.store import BaseTableStore
from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.web.app import create_app
from tests.conftest import CASES
from tests.test_render import extract_paragraphs_for_test

OFFICE_ORDER = ["兴耀科创城A幢09层", "蓝天国际大厦1幢808", "蓝天国际大厦1幢703"]
# Excel 里原填的市场状况指数是 98/95/95，算出评估结果 2.83。
# 把第一条改成 120，评估结果必然不同——测试据此分辨「真重算」与「照抄 Excel」。
CHANGED_MARKET_INDEX = {"兴耀科创城A幢09层": 120, "蓝天国际大厦1幢808": 95, "蓝天国际大厦1幢703": 95}
EXCEL_ORIGINAL_PRICE = "2.83"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store_path = tmp_path / "库.json"
    store = InstanceStore(store_path)
    for case in ("农用", "办公", "商业"):
        for inst in import_from_excel(CASES[case]):
            store.add(inst)
    store.save()
    monkeypatch.setenv("实例库路径", str(store_path))
    monkeypatch.setenv("草稿目录", str(tmp_path / "草稿"))
    monkeypatch.setenv("基础表目录", str(tmp_path / "基础表"))
    base = BaseTableStore(tmp_path / "基础表")
    for case in ("农用", "办公", "商业"):
        base.import_from_excel(CASES[case])
    return TestClient(create_app())


def _extract(client: TestClient, case: str) -> dict:
    with CASES[case].open("rb") as handle:
        response = client.post("/api/extract", files={"file": (CASES[case].name, handle)})
    assert response.status_code == 200, response.text
    return response.json()["project"]


def _compute(client: TestClient, case: str, market_index: dict[str, float]) -> dict:
    """重算。**不传文件**——档次从金样读出来当作「表单里填好的那份」。"""
    category = {"办公": "办公", "农用": "农用", "商业": "商业"}[case]
    items = client.get("/api/instances", params={"category": category}).json()["instances"]
    selected = [
        {"编号": i["编号"], "市场状况指数": market_index[i["位置"]], "备注": ""}
        for i in items
    ]
    response = client.post(
        "/api/compute",
        json={
            "category": category,
            "subject_levels": from_excel(CASES[case]).subject_levels,
            "selected": selected,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _compute_office(client: TestClient) -> dict:
    return _compute(client, "办公", CHANGED_MARKET_INDEX)


def test_compute_reports_the_price_unit(client: TestClient) -> None:
    """缺口①：光给 2.83 不给单位是误导——农用 1399.26 与办公 2.83 差 500 倍。"""
    assert _compute_office(client)["单价单位"] == "元/㎡·天"


def test_compute_reports_agricultural_unit(client: TestClient) -> None:
    items = client.get("/api/instances", params={"category": "农用"}).json()["instances"]
    body = _compute(client, "农用", dict.fromkeys((i["位置"] for i in items), 100))
    assert body["单价单位"] == "元/亩·年"


def test_compute_flags_high_dispersion(client: TestClient) -> None:
    """重算出的离散度也要过校验。

    它会跟着结果进报告，而 /api/extract 那次校验查的是 Excel 里的旧值。
    把第一条实例的市场状况指数抬到 120，离散度升到 29%（>20% 阈值），
    此时正在选实例——正是该看见这条提示的时刻。
    """
    body = _compute_office(client)
    assert body["离散度"] > 0.20, "前提：这组指数应算出偏高的离散度"
    codes = [w["code"] for w in body["提示"]]
    assert "DISPERSION_HIGH" in codes


def test_compute_stays_quiet_when_dispersion_is_normal(client: TestClient) -> None:
    """实测办公原本的 98/95/95 离散度 5%，属正常——不该无端提示。"""
    body = _compute(client, "办公", dict(zip(OFFICE_ORDER, [98, 95, 95], strict=True)))
    assert body["评估结果"] == 2.83, "前提：这是金样那组指数"
    assert body["提示"] == []


def test_annual_values_follow_the_price(client: TestClient) -> None:
    """改单价 → 年租赁价值跟着变。公式只有 Python 一份实现，界面来问它。"""
    response = client.post(
        "/api/annual-values",
        json={"category": "办公", "subjects": [{"area": 356.29, "unit_price": 2.83}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["annual_values"] == [368030]


def test_annual_values_reject_unknown_category(client: TestClient) -> None:
    response = client.post(
        "/api/annual-values",
        json={"category": "写字楼", "subjects": [{"area": 1.0, "unit_price": 1.0}]},
    )
    assert response.status_code == 400


def test_recomputed_result_reaches_the_report(client: TestClient, tmp_path: Path) -> None:
    """选实例 → 重算 → 出报告：报告里印的必须是重算值，不是 Excel 原值。"""
    project = _extract(client, "办公")
    assert project["unit_price"] == 2.83, "前提：Excel 原值是 2.83"

    result = _compute_office(client)
    new_price = result["评估结果"]
    assert new_price != 2.83, "换了市场状况指数，评估结果必须跟着变，否则重算没生效"

    # 以下三步即界面「用重算结果更新一览表」按钮所做的事。
    annual = client.post(
        "/api/annual-values",
        json={
            "category": project["category"],
            "subjects": [{"area": s["area"], "unit_price": new_price} for s in project["subjects"]],
        },
    ).json()["annual_values"]
    project["unit_price"] = new_price
    project["dispersion"] = result["离散度"]
    for subject, value in zip(project["subjects"], annual, strict=True):
        subject["unit_price"] = new_price
        subject["annual_value"] = value

    response = client.post(
        "/api/render", data={"project": json.dumps(project, ensure_ascii=False)}
    )
    assert response.status_code == 200, response.text
    output = tmp_path / "报告.docx"
    output.write_bytes(response.content)
    text = "\n".join(extract_paragraphs_for_test(output))

    assert str(new_price) in text, f"报告里没有重算值 {new_price}"
    assert EXCEL_ORIGINAL_PRICE not in text, "报告里还残留着 Excel 原单价 2.83——重算没进报告"
    assert f"{annual[0]:,}" in text, "年租赁价值没跟着单价重算"
