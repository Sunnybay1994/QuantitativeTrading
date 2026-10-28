"""Append-only monthly LLM spend ledger under artifacts/research/llm_ledger/."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
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


def priced_rows(path: Path) -> list[dict]:
    """Logical calls with validated append-only pricing adjustments applied once."""
    originals, adjustments = {}, []
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('kind') == 'pricing_adjustment':
            adjustments.append(row)
        else:
            originals[number] = {**row, '_source_line': number,
                                 '_source_sha256': hashlib.sha256(line).hexdigest()}
    applied = {}
    for row in adjustments:
        source = originals.get(row.get('source_line'))
        if (not source or row.get('source_sha256') != source['_source_sha256']
                or source.get('task') != 'gp_hints' or source.get('usd') not in (None, 0)):
            raise ValueError('Pricing adjustment source does not match an unpriced GP call')
        amount = row.get('usd')
        if type(amount) not in (int, float):
            raise TypeError('Pricing adjustment amount must be numeric')
        if not math.isfinite(amount) or amount <= 0 or row.get('estimated') is not True:
            raise ValueError('Pricing adjustment needs a positive finite estimate')
        usage, tariff = source.get('tokens'), row.get('tariff')
        if not isinstance(usage, dict) or not isinstance(tariff, dict):
            raise TypeError('Pricing adjustment needs original token counts and frozen rates')
        prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
        rates = [tariff.get('input_usd_per_million'), tariff.get('output_usd_per_million')]
        if (type(prompt) is not int or type(completion) is not int or min(prompt, completion) < 0
                or any(type(r) not in (int, float) or not math.isfinite(r) or r <= 0 for r in rates)):
            raise ValueError('Invalid pricing adjustment usage or rate')
        expected = (prompt*rates[0] + completion*rates[1]) / 1_000_000
        if not math.isclose(amount, expected, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError('Pricing adjustment does not match original usage and frozen rates')
        previous = applied.setdefault(row['source_line'], row)
        if previous != row:
            raise ValueError('Conflicting pricing adjustments for one call')
    for number, adjustment in applied.items():
        originals[number].update(usd=adjustment['usd'], estimated=True,
                                 original_usd=originals[number].get('usd'),
                                 pricing_adjustment=adjustment)
    return list(originals.values())
