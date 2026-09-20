"""Discover a charged symbol's earliest available minute without new symbol quota."""
import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.connectors.futu_history import history_page, history_quota
from quant.data.connectors.futu_realtime import FutuRealtime
from quant.data.realtime_store import atomic_json


def main():
    out = Path('artifacts/minute_history') / ('earliest_probe_' + dt.datetime.now().strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True)
    client = FutuRealtime()
    try:
        used, remaining, charged = history_quota(client.context)
        if not charged:
            raise RuntimeError('No already-charged symbol available for probe')
        symbol = sorted(charged)[0]
        frame, key = history_page(client.context, symbol, '1990-01-01', '2022-12-31', None)
        raw = Path('data/raw/futu/earliest_probe') / out.name / 'page_0000.parquet'
        raw.parent.mkdir(parents=True)
        with raw.open('xb') as stream:
            pl.from_pandas(frame).write_parquet(stream)
        result = dict(symbol=symbol, requested_start='1990-01-01', requested_end='2022-12-31',
            rows=len(frame), first=str(frame['time_key'].min()) if len(frame) else None,
            last=str(frame['time_key'].max()) if len(frame) else None, has_more=bool(key),
            quota_before=[used, remaining], quota_after=list(history_quota(client.context)[:2]), raw=str(raw))
        atomic_json(out / 'result.json', result)
        print(json.dumps(result))
    finally:
        client.close()


if __name__ == '__main__':
    main()
