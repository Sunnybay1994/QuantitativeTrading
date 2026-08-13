"""M4-P0 SQLite execution store migrations package."""

from __future__ import annotations

from collections.abc import Callable

import sqlite3

from quant.execution.migrations.v001_initial import upgrade as upgrade_v001
from quant.execution.migrations.v002_outbox_delivery import upgrade as upgrade_v002
from quant.execution.migrations.v003_daily_risk_counters import (
    upgrade as upgrade_v003,
)
from quant.execution.migrations.v004_unified_execution_state import (
    upgrade as upgrade_v004,
)

# Ordered list of (target_version, upgrade_callable).
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, upgrade_v001),
    (2, upgrade_v002),
    (3, upgrade_v003),
    (4, upgrade_v004),
]

__all__ = ["MIGRATIONS"]
