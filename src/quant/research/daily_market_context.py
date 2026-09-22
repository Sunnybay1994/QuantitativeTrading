"""Attach prior-session market context to existing daily observation, without trading."""
import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.data.realtime_store import atomic_json
from quant.execution.manual_session_service import instance_lock
from quant.research.market_indicators_run import history


def run(*, data_root=Path('data'), root=Path('artifacts/daily/market_context'), now=None):
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    if now.tzinfo is None:
        raise ValueError('Require timezone-aware observation clock')
    today = now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    cal = pl.read_parquet(data_root/'clean/trade_calendar/market=SH/data.parquet')
    date = cal.filter(pl.col('is_open') & (pl.col('date')<today))['date'].max()
    if date is None:
        raise ValueError('No preceding exchange session')
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
        result=dict(status='complete',observed_at=now.isoformat(),date=str(date),
                    market_state=row['market_state'],coverage=row['coverage'],
                    reference_stocks=row['reference_stocks'],report=str(output/'report.md'),
                    reused=reused,auto_trade=False,changes_positions=False)
        atomic_json(root/'latest.json',result)
        return result
