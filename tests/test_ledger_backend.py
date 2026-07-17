"""台账后端契约：LedgerStore 跑在任意后端上、内存后端往返一致、append-only。

内存后端也是将来"宜搭/远端后端"要满足的可执行契约。
"""

from datetime import datetime

from src.ledger.backend import InMemoryLedgerBackend
from src.ledger.store import LedgerStore
from tests.test_ledger_model import _entry  # 复用既有的合法 LedgerEntry 构造


def test_inmemory_roundtrip() -> None:
    backend = InMemoryLedgerBackend()
    backend.append("abc123", datetime(2026, 5, 1, 9, 0, 0), {"记录号": "abc123", "x": 1})
    assert list(backend.iter_payloads()) == [{"记录号": "abc123", "x": 1}]


def test_store_over_inmemory_append_list_get() -> None:
    store = LedgerStore(backend=InMemoryLedgerBackend())
    entry = _entry()
    rid = entry.记录号
    assert store.append(entry) == rid
    assert [e.记录号 for e in store.list_all()] == [rid]
    assert store.get(rid) is not None
    assert store.get("不存在") is None


def test_backend_has_no_mutation_api() -> None:
    """铁律 #4：后端不得有 update/delete/remove。"""
    backend = InMemoryLedgerBackend()
    assert not hasattr(backend, "update")
    assert not hasattr(backend, "remove")
    assert not hasattr(backend, "delete")
