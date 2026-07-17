"""基础表后端契约：内存后端往返、BaseTableStore 跑在任意后端上、重导不新增版本。

内存后端也是将来"宜搭/远端后端"要满足的可执行契约（一版一条 + 台账即查表）。
"""

from datetime import datetime

from src.knowledge_base import BaseTableStore, fingerprint
from src.knowledge_base.backend import InMemoryBaseTableBackend
from src.model import Category
from tests.conftest import CASES


def test_inmemory_version_roundtrip() -> None:
    backend = InMemoryBaseTableBackend()
    assert backend.read_version("办公", "abc123") is None
    assert backend.version_exists("办公", "abc123") is False
    backend.write_version("办公", "abc123", {"分值标尺": [2, 1, 0, -1, -2], "因素": []})
    assert backend.version_exists("办公", "abc123") is True
    assert backend.read_version("办公", "abc123") == {"分值标尺": [2, 1, 0, -1, -2], "因素": []}


def test_inmemory_index_append() -> None:
    backend = InMemoryBaseTableBackend()
    assert backend.read_index() == []
    backend.append_index({"类别": "办公", "指纹": "abc123"})
    backend.append_index({"类别": "农用", "指纹": "def456"})
    assert backend.read_index() == [
        {"类别": "办公", "指纹": "abc123"},
        {"类别": "农用", "指纹": "def456"},
    ]


def test_store_over_inmemory_import_and_load() -> None:
    store = BaseTableStore(backend=InMemoryBaseTableBackend())
    result = store.import_from_excel(CASES["办公"], now=datetime(2026, 7, 16, 10, 0))
    assert result.是否新版 is True
    loaded = store.load(Category.OFFICE, result.版本.指纹)
    assert fingerprint(loaded) == result.版本.指纹
    assert [v.指纹 for v in store.list_versions(Category.OFFICE)] == [result.版本.指纹]


def test_store_over_inmemory_reimport_not_new_version() -> None:
    store = BaseTableStore(backend=InMemoryBaseTableBackend())
    first = store.import_from_excel(CASES["办公"], now=datetime(2026, 7, 16, 10, 0))
    second = store.import_from_excel(CASES["办公"], now=datetime(2026, 7, 17, 11, 0))
    assert second.是否新版 is False
    assert second.版本.指纹 == first.版本.指纹
    assert second.版本.导入时间 == first.版本.导入时间  # 重导不改写首次导入时间
    assert len(store.list_versions(Category.OFFICE)) == 1
