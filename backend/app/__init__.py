"""Cairn 后端应用包。

版本号的真源在 `app/version.py`（T8.6），这里只做转发：别处仍然可以 `app.__version__`。
"""
from app.version import VERSION as __version__

__all__ = ["__version__"]
