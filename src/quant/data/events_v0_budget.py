"""Crash-conservative fee reservations for the one event extraction task."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import threading
import uuid

from quant.data._journal_lock import hold_journal_writer_lock
from quant.llm.ledger import month_path, SHANGHAI

_PAYER_LOCK = threading.Lock()
CALL_RESERVE_USD = .02


def task_budget_usd(now: dt.datetime | None = None) -> float:
    current=(now or dt.datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    return 2. if current.strftime('%Y-%m')=='2026-11' else 5.


class EventBudgetExhausted(RuntimeError):
    pass


def pending(root: Path, now: dt.datetime | None = None) -> dict:
    path = month_path(root/'.event_extract_budget', now=now)
    if not path.exists():
        return dict(requests=0, usd=0.)
    reservations, canceled = {}, set()
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            identity = row['request_id']
            if row['kind'] == 'reserve':
                value = float(row['usd'])
                if not math.isfinite(value) or value <= 0 or identity in reservations:
                    raise ValueError('Invalid event fee reservation')
                reservations[identity] = value
            elif row['kind'] == 'cancel':
                if identity not in reservations:
                    raise ValueError('Unknown event reservation cancellation')
                canceled.add(identity)
            else:
                raise ValueError('Unknown event reservation record')
    charged = set()
    ledger = month_path(root, now=now)
    if ledger.exists():
        for line in ledger.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get('task') == 'event_extract' and row.get('event_request_id'):
                value = row.get('usd')
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise ValueError('Invalid event request charge')
                charged.add(row['event_request_id'])
    remaining = {key: value for key, value in reservations.items() if key not in charged|canceled}
    return dict(requests=len(remaining), usd=math.fsum(remaining.values()))


def _append(path: Path, row: dict) -> None:
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, allow_nan=False)+'\n')
        handle.flush()
        os.fsync(handle.fileno())


def complete_with_budget(complete, messages, settings, *, ledger_root: Path,
                         announcement_id: str, spend, record, limit: float):
    """Hold the existing kernel lock through charging; reserve before the wire."""
    from quant.llm import RequestFailure

    directory = (ledger_root/'.event_extract_budget').resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with _PAYER_LOCK, hold_journal_writer_lock(journal_root=directory):
        started = dt.datetime.now(SHANGHAI)
        limit=min(limit,task_budget_usd(started))
        actual = spend(ledger_root, started)
        unresolved = pending(ledger_root, started)
        if not math.isfinite(actual) or actual < 0:
            raise ValueError('Invalid event extraction spend')
        exposure = Decimal(str(actual))+Decimal(str(unresolved['usd']))
        if exposure+Decimal(str(CALL_RESERVE_USD)) > Decimal(str(limit)):
            raise EventBudgetExhausted('event extraction monthly budget exhausted')
        identity = uuid.uuid4().hex
        path = month_path(directory, now=started)
        _append(path, dict(kind='reserve', request_id=identity, announcement_id=announcement_id,
                           usd=CALL_RESERVE_USD, ts=started.isoformat()))
        try:
            response = complete(messages, {**settings, 'max_usd': CALL_RESERVE_USD,
                                           'reserve_usd': CALL_RESERVE_USD})
        except RequestFailure as exc:
            # Transport explicitly proves these fail before submission.
            if exc.code in ('connect_failed', 'monthly_budget_exhausted'):
                _append(path, dict(kind='cancel', request_id=identity))
            raise
        record(response, identity, started)
        return response
