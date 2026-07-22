"""M4-P0 SQLite execution store migrations package."""

from __future__ import annotations

from collections.abc import Callable

import sqlite3

from quant.execution.migrations.v001_initial import upgrade as upgrade_v001
from quant.execution.migrations.v002_outbox_delivery import upgrade as upgrade_v002

# Ordered list of (target_version, upgrade_callable).
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, upgrade_v001),
    (2, upgrade_v002),
]

__all__ = ["MIGRATIONS"]
