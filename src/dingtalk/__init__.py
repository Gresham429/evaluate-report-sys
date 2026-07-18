"""钉钉多维表承载层：把知识/台账/实例同步到公司钉钉多维表（免费、零服务器）。

设计见 `docs/superpowers/specs/2026-07-18-多维表承载层-design.md`。
本包只管"打多维表"这层；各 Store 通过既有可插拔后端 Protocol 接进来，engine/渲染/金样不受影响。
"""

from src.dingtalk.notable import NotableClient

__all__ = ["NotableClient"]
