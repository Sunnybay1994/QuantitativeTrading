"""Publish completed-session market context with a verifiable daily receipt."""
import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.data.realtime_store import atomic_json
from quant.execution.manual_session_service import instance_lock
from quant.research.market_indicators_run import history


def completed_observation(date, now, root, record=None):
    """Bind an exact evening receipt, or find a completed prior-session receipt."""
    paths = [Path(record)] if record is not None else sorted(root.glob(f'{date}_*/summary.json'), reverse=True)
    for path in paths:
        if path.stat().st_mtime > now.timestamp():
            continue
        payload = path.read_bytes()
        saved = json.loads(payload)
        execution = path.parent/'scheduler.json'
        if execution.exists():
            status = json.loads(execution.read_text(encoding='utf-8'))
            if not isinstance(status, dict) or status.get('exit_code') != 0:
                continue
        if (isinstance(saved, dict) and saved.get('as_of') == str(date) and saved.get('status') == 'complete'
                and saved.get('rehearsal') is False and saved.get('saved_data') is False):
            return dict(path=str(path), sha256=hashlib.sha256(payload).hexdigest(),
                        available_at=dt.datetime.fromtimestamp(path.stat().st_mtime, now.tzinfo).isoformat())
    raise ValueError(f'No completed live-data daily observation for {date}')


def run(*, data_root=Path('data'), root=Path('artifacts/daily/market_context'), now=None,
        require_daily_receipt=False, daily_root=Path('artifacts/daily/sue_v2'),
        completed_session=None, daily_record=None):
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    if now.tzinfo is None:
        raise ValueError('Require timezone-aware observation clock')
    local = now.astimezone(dt.timezone(dt.timedelta(hours=8)))
    today = local.date()
    cal = pl.read_parquet(data_root/'clean/trade_calendar/market=SH/data.parquet')
    preceding = cal.filter(pl.col('is_open') & (pl.col('date')<today))['date'].max()
    date = completed_session if completed_session is not None else preceding
    effective = None
    try:
        if date is None:
            raise ValueError('No preceding exchange session')
        if completed_session is not None:
            closed = (pl.col('date') <= today) if local.time() >= dt.time(15) else (pl.col('date') < today)
            latest_closed = cal.filter(pl.col('is_open') & closed)['date'].max()
            if date != latest_closed:
                raise ValueError('Completed session is not the latest closed exchange session')
        if daily_record is not None and completed_session is None:
            raise ValueError('An exact daily receipt requires its completed session')
        effective = cal.filter(pl.col('is_open') & (pl.col('date') > date))['date'].min()
        receipt = completed_observation(date, now, daily_root, daily_record) if (
            require_daily_receipt or completed_session is not None) else None
        if effective is None:
            raise ValueError(f'No next exchange session after {date}')
    except (OSError, ValueError) as exc:
        # Keep the immutable historical reports, but never show an old successful
        # session as the current pre-open context when its receipt is absent.
        atomic_json(root/'latest.json', dict(status='incomplete', observed_at=now.isoformat(),
            date=str(date) if date else None, effective_date=str(effective) if effective else None, daily_completion=None,
            market_state='unknown', reason=str(exc), auto_trade=False, changes_positions=False))
        raise
    config = Path('configs/research/market_indicators_v1.toml')
    version = hashlib.sha256(config.read_bytes()+Path(__file__).read_bytes()
        +Path('src/quant/research/market_indicators.py').read_bytes()
        +Path('src/quant/research/market_indicators_run.py').read_bytes()).hexdigest()[:16]
    root.mkdir(parents=True,exist_ok=True)
    with instance_lock(root/'daily.lock'):
        parent = root/str(date)/version
        parent.mkdir(parents=True,exist_ok=True)
        completed = parent/'completed.json'
        if completed.exists():
            saved = json.loads(completed.read_text())
            output = Path(saved['output'])
            if any(not (output/name).exists() or hashlib.sha256((output/name).read_bytes()).hexdigest()!=digest
                   for name,digest in saved['hashes'].items()):
                raise ValueError('Completed market-context evidence changed')
            reused = True
        else:
            count = 1
            while (parent/f'attempt_{count:03d}').exists():
                count += 1
            output = parent/f'attempt_{count:03d}'
            history(config,output,start=date,end=date,data_root=data_root)
            names = ('summary.json','report.md','market_states.parquet','source_manifest.json')
            atomic_json(completed,dict(output=str(output),hashes={name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in names}))
            reused = False
        rows=pl.read_parquet(output/'market_states.parquet').filter(pl.col('trade_date')==date)
        if rows.height!=1:
            raise ValueError('Expected exactly one prior-session state')
        row=rows.row(0,named=True)
        if row['effective_date'] != effective:
            reason = 'Market state effective date differs from the next exchange session'
            atomic_json(root/'latest.json', dict(status='incomplete', observed_at=now.isoformat(),
                date=str(date), effective_date=str(effective), daily_completion=None,
                market_state='unknown', reason=reason, auto_trade=False, changes_positions=False))
            raise ValueError(reason)
        result=dict(status='complete',observed_at=now.isoformat(),date=str(date),
                    effective_date=str(row['effective_date']),
                    available_at=dt.datetime.now(now.tzinfo).isoformat(),
                    daily_completion=receipt,
                    timing='computed_from_completed_session; effective next exchange session; available_at is actual publication time',
                    market_state=row['market_state'],coverage=row['coverage'],
                    reference_stocks=row['reference_stocks'],report=str(output/'report.md'),
                    reused=reused,auto_trade=False,changes_positions=False)
        atomic_json(root/'latest.json',result)
        return result


if __name__ == '__main__':
    print(json.dumps(run(require_daily_receipt=True), ensure_ascii=False))
