"""Retrospective liquidity stress; scaled fills are not new account replays."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions


def run(config: Path, output: Path, data_root: Path = Path('data')) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False:
        raise ValueError('Diagnostic only')
    source = Path(spec['source'])
    initial = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))['portfolio']['initial_cash']
    frames = []
    for path in sorted((source/'budgeted/cost_1').glob('*/trades.parquet')):
        frame = pl.read_parquet(path)
        if frame.filter(pl.col('date').dt.year() != int(path.parent.name)).height:
            raise ValueError('Overlapping checkpoint years')
        frames.append(frame)
    fills = pl.concat(frames, how='vertical_relaxed').group_by('date', 'symbol').agg(pl.col('notional').sum())
    last = fills['date'].max()
    if not isinstance(last, dt.date):
        raise ValueError('Require nonempty dated fills')
    sessions = available_sessions(data_root, last+dt.timedelta(days=1))
    calendar = pl.DataFrame({'date': sessions[1:], 'as_of': sessions[:-1]})
    fills = fills.join(calendar, on='date', how='left', validate='m:1')
    if fills['as_of'].null_count():
        raise ValueError('Missing previous session')
    frames = []
    for year in sorted(set(fills['as_of'].dt.year())):
        path = Path(spec['statistics'])/f'inputs/{year}/universe.parquet'
        frames.append(pl.scan_parquet(path).select('symbol', pl.col('trade_date').alias('as_of'),
            'amount20').filter(pl.col('as_of').is_in(fills['as_of'].unique().implode())).collect())
    base = fills.join(pl.concat(frames), on=['as_of', 'symbol'], how='left', validate='m:1')
    base = base.with_columns(pl.when(pl.col('amount20').is_finite() & (pl.col('amount20') > 0))
        .then(pl.col('amount20')).otherwise(None).alias('amount20'))
    rows = []
    details = []
    for capital in spec['initial_capitals']:
        detail = base.with_columns(pl.lit(capital).alias('initial_capital'),
            (pl.col('notional')*capital/initial/pl.col('amount20')).alias('participation'))
        details.append(detail)
        valid = detail.filter(pl.col('participation').is_not_null())
        rows.append({'initial_capital': capital, 'symbol_days': detail.height,
            'known_adv': valid.height, 'missing_adv': detail.height-valid.height,
            'p95_participation': valid['participation'].quantile(.95),
            'maximum_participation': valid['participation'].max(),
            'above_5pct': valid.filter(pl.col('participation') > spec['participation_limit']).height})
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    pl.concat(details).write_parquet(output/'participation.parquet')
    pl.DataFrame(rows).write_csv(output/'capacity_diagnostic.csv')
    summary = {'rows': rows, 'capacity_verified': False, 'auto_trade': False,
        'method': spec['method'], 'limitation': 'Linear scaling ignores changed holdings, rounding, fees and market impact; missing ADV remains unknown.'}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    lines = ['# Capacity liquidity diagnostic', '', '|Initial CNY|Known ADV|Missing ADV|P95 participation|Max participation|Above 5%|', '|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append('|'+ '|'.join(str(r[k]) for k in ('initial_capital','known_adv','missing_adv','p95_participation','maximum_participation','above_5pct'))+'|')
    lines += ['', summary['limitation'], 'Capacity is not verified. This is not a replay or a return/cost curve.']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.output)))
