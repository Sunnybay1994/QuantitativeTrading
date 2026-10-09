"""Append-only monthly LLM spend ledger under artifacts/research/llm_ledger/."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_ROOT = Path("artifacts/research/llm_ledger")


def month_path(root: Path = DEFAULT_ROOT, *, now: dt.datetime | None = None) -> Path:
    clock = (now or dt.datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    return root / f"{clock.strftime('%Y-%m')}.jsonl"


def append(row: dict, root: Path = DEFAULT_ROOT, *, now: dt.datetime | None = None) -> Path:
    path = month_path(root, now=now)
    path.parent.mkdir(parents=True, exist_ok=True)
    clock = (now or dt.datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    payload = {"ts": clock.isoformat(), **row}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return path
