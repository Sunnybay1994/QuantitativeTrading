"""共享 DeepSeek 费用账本只读查询。写入仍由各调用方的 ScoreCache 完成。"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from quant.core.paths import project_paths

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_CACHE = Path("research/p7_deepseek_cache.sqlite")


def cache_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    return project_paths().artifacts / DEFAULT_CACHE


def month_spend_usd(path: Path | None = None, *, now: dt.datetime | None = None) -> float:
    target = cache_path(path)
    if not target.exists():
        return 0.0
    clock = now or dt.datetime.now(SHANGHAI)
    local = clock.astimezone(SHANGHAI)
    month = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    connection = sqlite3.connect(target)
    try:
        rows = connection.execute(
            "SELECT created_at,state,reserved_usd,charged_usd FROM attempts"
        ).fetchall()
    except sqlite3.Error:
        return 0.0
    finally:
        connection.close()
    total = 0.0
    for created_at, state, reserved, charged in rows:
        created = dt.datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=SHANGHAI)
        if created.astimezone(SHANGHAI) < month:
            continue
        total += max(charged, reserved) if state == "unknown" else float(charged or 0)
    return total


def remaining_budget_usd(limit: float, path: Path | None = None) -> float:
    return max(0.0, float(limit) - month_spend_usd(path))
