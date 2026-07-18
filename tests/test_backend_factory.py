"""后端工厂：默认走本地；开关开且配置齐才走多维表；配置缺则回退本地。

env 隔离：每个用例先清掉 `承载后端` 与全部 NOTABLE_/YIDA_ 相关变量，
免得开发机 shell 里残留的值污染判断。
"""

from pathlib import Path

import pytest

from src.dingtalk.factory import (
    base_table_backend_for,
    instance_backend_for,
    ledger_backend_for,
)
from src.knowledge_base.backend import LocalFileBaseTableBackend
from src.knowledge_base.notable_backend import NotableBaseTableBackend
from src.ledger.backend import LocalFileLedgerBackend
from src.ledger.notable_backend import NotableLedgerBackend
from src.library.backend import LocalFileInstanceBackend
from src.library.notable_backend import NotableInstanceBackend

_ENV_KEYS = [
    "承载后端",
    "YIDA_APP_KEY",
    "YIDA_APP_SECRET",
    "NOTABLE_BASE_ID",
    "NOTABLE_OPERATOR_ID",
    "NOTABLE_LEDGER_SHEET",
    "NOTABLE_INSTANCE_SHEET",
    "NOTABLE_BASETABLE_SHEET",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _configure_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("承载后端", "多维表")
    monkeypatch.setenv("YIDA_APP_KEY", "ak")
    monkeypatch.setenv("YIDA_APP_SECRET", "as")
    monkeypatch.setenv("NOTABLE_BASE_ID", "base1")
    monkeypatch.setenv("NOTABLE_OPERATOR_ID", "op1")
    monkeypatch.setenv("NOTABLE_LEDGER_SHEET", "台账")
    monkeypatch.setenv("NOTABLE_INSTANCE_SHEET", "实例库")
    monkeypatch.setenv("NOTABLE_BASETABLE_SHEET", "基础表")


def test_default_is_local() -> None:
    p = Path("/tmp/x")
    assert isinstance(ledger_backend_for(p), LocalFileLedgerBackend)
    assert isinstance(instance_backend_for(p), LocalFileInstanceBackend)
    assert isinstance(base_table_backend_for(p), LocalFileBaseTableBackend)


def test_notable_when_switched_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_full(monkeypatch)
    p = Path("/tmp/x")
    assert isinstance(ledger_backend_for(p), NotableLedgerBackend)
    assert isinstance(instance_backend_for(p), NotableInstanceBackend)
    assert isinstance(base_table_backend_for(p), NotableBaseTableBackend)


def test_switch_off_stays_local(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_full(monkeypatch)
    monkeypatch.delenv("承载后端", raising=False)  # 只关开关，配置仍在
    assert isinstance(ledger_backend_for(Path("/tmp/x")), LocalFileLedgerBackend)


def test_incomplete_config_falls_back_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("承载后端", "多维表")
    monkeypatch.setenv("NOTABLE_LEDGER_SHEET", "台账")  # 有 sheet 但没凭据/baseId
    assert isinstance(ledger_backend_for(Path("/tmp/x")), LocalFileLedgerBackend)


def test_missing_sheet_falls_back_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_full(monkeypatch)
    monkeypatch.delenv("NOTABLE_INSTANCE_SHEET", raising=False)  # 实例没配 sheet
    assert isinstance(instance_backend_for(Path("/tmp/x")), LocalFileInstanceBackend)
    assert isinstance(ledger_backend_for(Path("/tmp/x")), NotableLedgerBackend)  # 台账仍走多维表
