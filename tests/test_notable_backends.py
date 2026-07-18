"""三个 Notable 后端跑假客户端：往返一致、版本不可变、实例只增不删、台账无 mutation API。

假客户端在内存里存行，行为对齐真实 notable 客户端的 list/insert（不涉网络），
故这些测试锁的是"后端怎么把 payload 映射成多维表行、又读回来"这层逻辑。
"""

from datetime import datetime
from typing import Any

from src.knowledge_base.notable_backend import NotableBaseTableBackend
from src.ledger.notable_backend import NotableLedgerBackend
from src.library.notable_backend import NotableInstanceBackend


class FakeNotableClient:
    """内存版 notable 客户端：list/insert 与真客户端同签名，供后端单测。"""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self._n = 0

    def list_records(self, sheet: str) -> list[dict[str, Any]]:
        return [dict(r, fields=dict(r["fields"])) for r in self.rows.get(sheet, [])]

    def insert_records(self, sheet: str, fields_list: list[dict[str, Any]]) -> list[str]:
        ids = []
        for fields in fields_list:
            self._n += 1
            rid = f"r{self._n}"
            self.rows.setdefault(sheet, []).append({"id": rid, "fields": dict(fields)})
            ids.append(rid)
        return ids

    def insert_record(self, sheet: str, fields: dict[str, Any]) -> str:
        return self.insert_records(sheet, [fields])[0]


# ------------------------------------------------------------ 台账

def test_ledger_append_then_iter_roundtrip() -> None:
    client = FakeNotableClient()
    backend = NotableLedgerBackend(client, "台账")  # type: ignore[arg-type]
    p1 = {"记录号": "a1", "报告编号": "第1号", "类别": "办公", "经手人": "薛", "x": 1}
    p2 = {"记录号": "a2", "报告编号": "第2号", "类别": "农用", "经手人": "韩", "y": 2}
    backend.append("a1", datetime(2026, 5, 1, 9, 0), p1)
    backend.append("a2", datetime(2026, 5, 2, 9, 0), p2)
    got = list(backend.iter_payloads())
    assert p1 in got and p2 in got and len(got) == 2


def test_ledger_backend_has_no_mutation_api() -> None:
    """铁律 #4：台账后端不得有 update/delete/remove。"""
    backend = NotableLedgerBackend(FakeNotableClient(), "台账")  # type: ignore[arg-type]
    assert not hasattr(backend, "update")
    assert not hasattr(backend, "remove")
    assert not hasattr(backend, "delete")


def test_ledger_skips_unreadable_snapshot() -> None:
    client = FakeNotableClient()
    backend = NotableLedgerBackend(client, "台账")  # type: ignore[arg-type]
    backend.append("a1", datetime(2026, 5, 1, 9, 0), {"记录号": "a1"})
    client.rows["台账"].append({"id": "bad", "fields": {"快照": "{坏JSON"}})  # 混入坏行
    got = list(backend.iter_payloads())
    assert got == [{"记录号": "a1"}]  # 坏行跳过，不连累其余


# ------------------------------------------------------------ 基础表

def test_base_table_version_immutable_roundtrip() -> None:
    client = FakeNotableClient()
    backend = NotableBaseTableBackend(client, "基础表")  # type: ignore[arg-type]
    assert backend.version_exists("办公", "fp1") is False
    assert backend.read_version("办公", "fp1") is None
    payload = {"分值标尺": [2, 1, 0, -1, -2], "因素": []}
    backend.write_version("办公", "fp1", payload)
    assert backend.version_exists("办公", "fp1") is True
    assert backend.read_version("办公", "fp1") == payload
    # 别的类别/指纹互不串
    assert backend.version_exists("农用", "fp1") is False
    assert backend.read_version("办公", "fp2") is None


def test_base_table_index_append_and_read() -> None:
    client = FakeNotableClient()
    backend = NotableBaseTableBackend(client, "基础表")  # type: ignore[arg-type]
    assert backend.read_index() == []
    backend.append_index({"类别": "办公", "指纹": "fp1", "导入时间": "2026-07-16T10:00:00", "来源文件名": "a.xlsx"})
    backend.append_index({"类别": "农用", "指纹": "fp2", "导入时间": "2026-07-17T11:00:00", "来源文件名": "b.xlsx"})
    idx = backend.read_index()
    assert [e["类别"] for e in idx] == ["办公", "农用"]
    assert idx[0]["指纹"] == "fp1"


def test_base_table_version_and_index_coexist() -> None:
    """版本行与索引行同表共存、互不误读。"""
    client = FakeNotableClient()
    backend = NotableBaseTableBackend(client, "基础表")  # type: ignore[arg-type]
    backend.write_version("办公", "fp1", {"因素": []})
    backend.append_index({"类别": "办公", "指纹": "fp1", "导入时间": "t", "来源文件名": "a"})
    assert len(backend.read_index()) == 1  # 版本行没被当成索引
    assert backend.version_exists("办公", "fp1") is True


# ------------------------------------------------------------ 实例库

def test_instance_save_then_load_roundtrip() -> None:
    client = FakeNotableClient()
    backend = NotableInstanceBackend(client, "实例库")  # type: ignore[arg-type]
    assert backend.load() == []
    backend.save([{"编号": "x1", "位置": "A"}, {"编号": "x2", "位置": "B"}])
    got = backend.load()
    assert {r["编号"] for r in got} == {"x1", "x2"}


def test_instance_save_is_incremental_no_dup_no_delete() -> None:
    """只增不删：再 save 一个超集只插新的；save 一个子集不删旧的（共享库不因本地删除删公司数据）。"""
    client = FakeNotableClient()
    backend = NotableInstanceBackend(client, "实例库")  # type: ignore[arg-type]
    backend.save([{"编号": "x1"}, {"编号": "x2"}])
    backend.save([{"编号": "x1"}, {"编号": "x2"}, {"编号": "x3"}])  # 超集：只该多插 x3
    assert {r["编号"] for r in backend.load()} == {"x1", "x2", "x3"}
    assert len(client.rows["实例库"]) == 3  # 没重复插 x1/x2
    backend.save([{"编号": "x1"}])  # 子集：不删 x2/x3
    assert {r["编号"] for r in backend.load()} == {"x1", "x2", "x3"}
