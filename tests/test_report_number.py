"""报告编号领号：格式正确、递增、缺自动编号字段则报错。假客户端不涉网络。"""

from typing import Any

import pytest

from src.dingtalk.report_number import draw_report_number


class FakeSeqClient:
    """插一行就自增一个"报告序号"，get_record 回读它。"""

    def __init__(self, *, has_seq: bool = True) -> None:
        self._n = 0
        self._last: dict[str, int] = {}
        self._has_seq = has_seq
        self.inserted: list[dict[str, Any]] = []

    def insert_record(self, sheet: str, fields: dict[str, Any]) -> str:
        self._n += 1
        rid = f"r{self._n}"
        self._last[rid] = self._n
        self.inserted.append(fields)
        return rid

    def get_record(self, sheet: str, record_id: str) -> dict[str, Any]:
        fields = {"报告序号": self._last[record_id]} if self._has_seq else {}
        return {"id": record_id, "fields": fields}


def test_draw_formats_with_year_and_autonumber() -> None:
    assert draw_report_number(FakeSeqClient(), "台账", year=2026) == "正恒评报字[2026]第1号"


def test_draw_increments_across_calls() -> None:
    client = FakeSeqClient()
    a = draw_report_number(client, "台账", year=2026)
    b = draw_report_number(client, "台账", year=2026)
    assert a == "正恒评报字[2026]第1号"
    assert b == "正恒评报字[2026]第2号"


def test_draw_passes_metadata_onto_the_row() -> None:
    client = FakeSeqClient()
    draw_report_number(client, "台账", year=2026, metadata={"实勘人": "薛焱"})
    assert client.inserted == [{"实勘人": "薛焱"}]


def test_draw_raises_without_autonumber_field() -> None:
    with pytest.raises(RuntimeError, match="自动编号"):
        draw_report_number(FakeSeqClient(has_seq=False), "台账", year=2026)
