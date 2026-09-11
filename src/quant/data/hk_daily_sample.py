"""Save a fixed three-security public daily sample for source feasibility only."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quant.data.connectors.yahoo_intraday import fetch_daily_history


def collect(output: Path, data_root: Path) -> dict:
    raw = data_root/'raw'/'hk_daily_sample'/output.name
    raw.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for symbol, provider_symbol in [('00700.HK', '0700.HK'), ('00939.HK', '0939.HK'), ('09988.HK', '9988.HK')]:
        try:
            payload = fetch_daily_history(provider_symbol, start=dt.date(2015, 1, 1), end=dt.date(2026, 9, 10))
            (raw/f'{symbol}.json').write_text(json.dumps(payload), encoding='utf-8')
            result = payload['chart']['result'][0]
            quote = result['indicators']['quote'][0]
            adjusted = result['indicators']['adjclose'][0]['adjclose']
            frame = pl.DataFrame({'symbol': [symbol]*len(result['timestamp']),
                'date': [dt.datetime.fromtimestamp(t, ZoneInfo('Asia/Hong_Kong')).date() for t in result['timestamp']],
                **quote, 'adjusted_close': adjusted})
            frame.write_parquet(output/f'{symbol}.parquet')
            rows.append({'symbol': symbol, 'rows': frame.height, 'first': str(frame['date'].min()),
                'last': str(frame['date'].max()), 'duplicate_dates': frame['date'].is_duplicated().sum(),
                'null_close': frame['close'].null_count(), 'null_adjusted_close': frame['adjusted_close'].null_count(),
                'dividends': len(result.get('events', {}).get('dividends', {})),
                'splits': len(result.get('events', {}).get('splits', {})),
                'currency': result['meta'].get('currency')})
        except Exception as exc:
            rows.append({'symbol': symbol, 'error_type': type(exc).__name__})
    (output/'summary.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    return {'rows': rows}
