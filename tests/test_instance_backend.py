"""实例库后端契约：内存后端往返、InstanceStore 跑在任意后端上、空库为空。

内存后端也是将来"宜搭/远端后端"要满足的可执行契约（整库读/写）。
"""

from src.library.backend import InMemoryInstanceBackend
from src.library.importer import import_from_excel
from src.library.store import InstanceStore
from src.model import Category
from tests.conftest import CASES


def test_inmemory_roundtrip() -> None:
    backend = InMemoryInstanceBackend()
    assert backend.load() == []
    backend.save([{"编号": "x1"}, {"编号": "x2"}])
    assert backend.load() == [{"编号": "x1"}, {"编号": "x2"}]


def test_store_over_inmemory_add_save_reload() -> None:
    backend = InMemoryInstanceBackend()
    store = InstanceStore(backend=backend)
    for inst in import_from_excel(CASES["办公"]):
        assert store.add(inst) is True
    store.save()

    # 新起一个 store、共用同一后端 → 应加载到刚存的 3 条
    reloaded = InstanceStore(backend=backend)
    reloaded.load()
    assert len(reloaded.list_by_category(Category.OFFICE)) == 3


def test_store_over_empty_backend_is_empty() -> None:
    store = InstanceStore(backend=InMemoryInstanceBackend())
    store.load()
    assert store.list_by_category(Category.OFFICE) == ()
