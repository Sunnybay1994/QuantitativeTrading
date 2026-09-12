"""Dated market-brief facts from the same saved total-return benchmarks."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.factor_panels import available_sessions

ANCHOR = dt.date(2015, 1, 1)


def series_facts(frame: pl.DataFrame, *, as_of: dt.date, name: str, source: str) -> dict:
    known = frame.filter(pl.col('date') <= as_of)
    if (known.is_empty() or known['date'][-1] != as_of or not known['date'].is_sorted()
            or known['date'].n_unique() != known.height or known['unit_nav'].null_count()
            or not known['unit_nav'].is_finite().all() or (known['unit_nav'] <= 0).any()):
        raise ValueError('Require complete dated positive benchmark observations')
    levels = known['unit_nav']
    returns = levels.tail(61).pct_change().drop_nulls()
    return {'id': name, 'as_of': str(as_of), 'level': levels[-1],
        'return_20': levels[-1]/levels[-21]-1 if len(levels) >= 21 else None,
        'return_60': levels[-1]/levels[-61]-1 if len(levels) >= 61 else None,
        'annualized_volatility_60': returns.std(ddof=1) * 252 ** .5 if len(returns) == 60 else None,
        'source': source, 'return_type': 'total_return'}


def source_id(name: str, settings: dict) -> str:
    version = settings['etf_total_return_snapshot' if name == '510300' else 'equal_weight_snapshot']
    return f'{name}:{version}:anchor={ANCHOR}'


def prepare(*, config: Path, as_of: dt.date, target_date: dt.date,
            output: Path, data_root: Path = Path('data')) -> dict:
    sessions = available_sessions(data_root, target_date)
    if as_of not in sessions or target_date not in sessions or not as_of < target_date:
        raise ValueError('Require actual signal and target exchange sessions')
    first = next(day for day in sessions if day > as_of)
    settings = tomllib.loads(config.read_text(encoding='utf-8'))['benchmarks']
    histories = load_return_benchmarks(config=config, data_root=data_root, start=ANCHOR, end=as_of)
    facts = {'as_of': str(as_of), 'target_date': str(target_date), 'first_forecast_session': str(first),
        'series': [series_facts(frame, as_of=as_of, name=name, source=source_id(name, settings))
                   for name, frame in histories.items()]}
    output.mkdir(parents=True, exist_ok=False)
    (output/'benchmarks.toml').write_bytes(config.read_bytes())
    (output/'facts.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
    return facts


def realized(*, inputs: Path, output: Path, known_through: dt.date,
             data_root: Path = Path('data'), config: Path | None = None) -> dict:
    facts = json.loads((inputs/'facts.json').read_text(encoding='utf-8'))
    target = dt.date.fromisoformat(facts['target_date'])
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    if (target > known_through or known_through > now.date()
            or (known_through == now.date() and now.hour < 15)):
        raise ValueError('Target close is not observable yet')
    origin_config = inputs/'benchmarks.toml'
    settings = tomllib.loads(origin_config.read_text(encoding='utf-8'))['benchmarks']
    target_config = config or origin_config
    histories = load_return_benchmarks(config=target_config, data_root=data_root, start=ANCHOR, end=target)
    rows = []
    for original in facts['series']:
        name = original['id']
        frame = histories[name]
        old = frame.filter(pl.col('date') == dt.date.fromisoformat(facts['as_of']))
        if old.height != 1 or old['unit_nav'][0] != original['level'] or source_id(name, settings) != original['source']:
            raise ValueError('Origin level or benchmark source changed')
        rows.append({'id': name, 'reference_level': original['level'],
                     'total_return': frame['unit_nav'][-1]/original['level']-1,
                     'source': original['source'], 'return_type': 'total_return'})
    result = {'as_of': facts['as_of'], 'target_date': str(target), 'series': rows}
    output.mkdir(parents=True, exist_ok=False)
    (output/'origin_benchmarks.toml').write_bytes(origin_config.read_bytes())
    (output/'realized_benchmarks.toml').write_bytes(target_config.read_bytes())
    (output/'realized.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--as-of', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--target-date', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args()))))
