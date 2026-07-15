"""基础表版本库。

Excel 基础表是估价知识的权威（ADR-001）；本包负责把它导入一次、存副本、按版本
取用，且**旧版本永不覆盖**——「能复现」是可复查的前提。
"""

from src.knowledge_base.fingerprint import canonical_form, fingerprint
from src.knowledge_base.store import (
    DEFAULT_STORE_DIR,
    LEDGER_NAME,
    BaseTableStore,
    ImportResult,
    VersionInfo,
)

__all__ = [
    "fingerprint",
    "canonical_form",
    "BaseTableStore",
    "VersionInfo",
    "ImportResult",
    "DEFAULT_STORE_DIR",
    "LEDGER_NAME",
]
