"""Fractional monthly equal-weight total-return indexes on frozen battery universes."""

import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.factor_benchmarks import read_csi800_members, read_etf_total_return
from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data


def monthly_selections(universe: pl.DataFrame, members: pl.DataFrame | None,
                       sessions: tuple[dt.date, ...], end: dt.date) -> pl.DataFrame:
    """Same signal-close eligible intersection as the original battery benchmark."""
    next_day = dict(zip(sessions, sessions[1:]))
    month_ends = {a for a, b in zip(sessions, sessions[1:]) if (a.year, a.month) != (b.year, b.month)}
    selected = universe.filter(pl.col('eligible') & pl.col('trade_date').is_in(month_ends))
    if universe.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate universe keys')
    rows: list[dict[str, Any]] = []
    for signal in sorted(set(universe['trade_date']) & month_ends):
        effective = next_day[signal]
        if effective > end:
            continue
        frame = selected.filter(pl.col('trade_date') == signal)
        snapshot = None
        if members is not None:
            snapshot = members.filter(pl.col('snapshot_date') <= signal)['snapshot_date'].max()
            if not isinstance(snapshot, dt.date):
                raise ValueError(f'Missing PIT members on {signal}')
            # Do not carry a missing monthly membership file indefinitely.
            if (signal - snapshot).days > 40:
                raise ValueError(f'Stale PIT members on {signal}: {snapshot}')
            names = members.filter(pl.col('snapshot_date') == snapshot)['symbol']
            frame = frame.filter(pl.col('symbol').is_in(names.implode()))
        if frame.is_empty():
            raise ValueError(f'Empty eligible benchmark on {signal}')
        rows.extend({'as_of': signal, 'effective_date': effective, 'symbol': r['symbol'],
                     'weight': 1 / frame.height, 'signal_close': r['close'],
                     'membership_date': snapshot} for r in frame.iter_rows(named=True))
    return pl.DataFrame(rows, schema_overrides={'as_of': pl.Date, 'effective_date': pl.Date,
                                               'membership_date': pl.Date}).sort('effective_date', 'symbol')


def index_day(*, date: dt.date, state: dict, quotes: dict, actions: dict,
              delisted: dict, stopped: set, targets: dict | None) -> tuple[dict, dict, list[dict]]:
    """Old weights earn overnight; a scheduled open resets weights before intraday return.

    On ordinary days ex-date gross cash is reinvested in its own security at close.
    On rebalance days it is included in the capital reweighted at the open.
    """
    weights, last = state.get('weights', {}), state.get('last', {})
    nav = state.get('level', 1000.0)
    symbols = set(weights) | set(targets or {})
    values, prices, events = {}, {}, []
    for symbol in sorted(symbols):
        prior = last.get(symbol, (targets or {}).get(symbol, {}).get('signal_close'))
        if prior is None or not math.isfinite(prior) or prior <= 0:
            raise ValueError(f'Missing prior valuation: {symbol} {date}')
        weight = weights.get(symbol, 0.0)
        terminal = delisted.get(symbol)
        if terminal is not None and date >= terminal:
            if targets and symbol in targets:
                raise ValueError(f'Target delisted by effective date: {symbol} {date}')
            values[symbol] = (0.0, 0.0)
            events.append({'date': date, 'symbol': symbol, 'kind': 'delist_zero_recovery', 'prior_weight': weight})
            continue
        action = actions.get(symbol, {})
        cash, ratio = action.get('div_cash', 0.0), action.get('share_ratio', 0.0)
        if not math.isfinite(cash) or cash < 0 or not math.isfinite(ratio) or ratio <= -1:
            raise ValueError('Invalid corporate action')
        if action and action['ann_date'] > date:
            raise ValueError('Corporate action is not yet known')
        scale = 1 + ratio
        quote = quotes.get(symbol)
        if quote is None or quote['volume'] <= 0:
            # An index mark, not a claim that an absent quote proves suspension.
            mark = (prior - cash) / scale if action.get('adjust_share_price', True) else prior
            op = close = mark
            events.append({'date': date, 'symbol': symbol,
                           'kind': 'suspended_last_mark' if symbol in stopped else 'missing_quote_last_mark',
                           'prior_weight': weight})
        else:
            op, close = quote['open'], quote['close']
        if not all(math.isfinite(p) and p > 0 for p in (op, close)):
            raise ValueError(f'Invalid index quote: {symbol} {date}')
        prices[symbol] = (op, close)
        values[symbol] = (weight * (op * scale + cash) / prior,
                          weight * (close * scale + cash) / prior)
        if action and weight:
            events.append({'date': date, 'symbol': symbol, 'kind': 'gross_ex_date_distribution',
                           'prior_weight': weight, 'cash_per_share': cash, 'share_ratio': ratio})
    opening = sum(v[0] for v in values.values()) if weights else 1.0
    if targets is not None:
        if not targets or abs(sum(r['weight'] for r in targets.values()) - 1) > 1e-10:
            raise ValueError('Index target weights must sum to one')
        ending = {s: opening * r['weight'] * prices[s][1] / prices[s][0] for s, r in targets.items()}
    else:
        ending = {s: value[1] for s, value in values.items() if value[1] > 0}
    gross = sum(ending.values())
    if not math.isfinite(gross) or gross <= 0:
        raise ValueError('Nonpositive index value')
    new = {'weights': {s: v / gross for s, v in ending.items() if v > 0},
           'last': {s: prices[s][1] for s, v in ending.items() if v > 0}, 'level': nav * gross}
    row = {'trade_date': date, 'index_level': new['level'], 'daily_return': gross - 1,
           'opening_index_level': nav * opening, 'rebalance': targets is not None,
           'constituents': len(new['weights']), 'weight_sum': sum(new['weights'].values()),
           'missing_quote_weight': sum(e['prior_weight'] for e in events if e['kind'] == 'missing_quote_last_mark')}
    return new, row, events


def publish(*, config: Path, data_root: Path) -> dict[str, Any]:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    version = settings['version']
    if Path(version).name != version or version in ('', '.', '..'):
        raise ValueError('Invalid version')
    output = data_root / 'clean/equal_weight_indexes' / version
    if output.exists():
        raise FileExistsError('Choose a new index version')
    statistics = Path(settings['statistics'])
    battery = tomllib.loads((statistics / 'battery.toml').read_text(encoding='utf-8'))
    start, end = battery['start'], battery['run']['as_of']
    sessions = available_sessions(data_root, end + dt.timedelta(days=40))
    month_ends = {a for a, b in zip(sessions, sessions[1:]) if (a.year, a.month) != (b.year, b.month)}
    universes = [pl.scan_parquet(statistics / f'inputs/{year}/universe.parquet')
                 .filter(pl.col('trade_date').is_in(month_ends))
                 .select('trade_date', 'symbol', 'eligible', 'close').collect()
                 for year in range(start.year, end.year + 1)]
    universe = pl.concat(universes)
    members = read_csi800_members(data_root=data_root, snapshot=battery['data']['csi800_snapshot'])
    plans = {name: monthly_selections(universe, membership, sessions, end)
             for name, membership in [('all_market_equal_weight', None), ('csi800_equal_weight', members)]}
    folder = data_root / 'clean/stock_execution' / settings['execution_snapshot']
    instruments = pl.read_parquet(folder / 'instruments.parquet')
    dividends = pl.read_parquet(folder / 'dividends.parquet')
    suspensions = pl.read_parquet(folder / 'suspensions.parquet')
    if dividends.select('symbol', 'ex_date').is_duplicated().any():
        raise ValueError('Ambiguous corporate actions')
    delisted = dict(instruments.select('symbol', 'delist_date').iter_rows())
    states: dict[str, dict[str, Any]] = {name: {} for name in plans}
    all_rows: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    output.mkdir(parents=True)
    for name, plan in plans.items():
        plan.write_parquet(output / f'{name}_selections.parquet')
    for year in range(start.year, end.year + 1):
        low, high = max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        needed = set().union(*(set(p.filter(pl.col('effective_date').is_between(low, high))['symbol'])
                              | set(states[name].get('weights', {})) for name, p in plans.items()))
        bars = read_stock_data(data_root=data_root, config=config, table='bar_1d', start=low, end=high,
                               symbols=sorted(needed)).select('trade_date', 'symbol', 'open', 'close', 'volume')
        quotes = {key[0]: {r['symbol']: r for r in f.iter_rows(named=True)}
                  for key, f in bars.partition_by('trade_date', as_dict=True).items()}
        actions = {key[0]: {r['symbol']: r for r in f.iter_rows(named=True)} for key, f in
                   dividends.filter(pl.col('ex_date').is_between(low, high)).partition_by('ex_date', as_dict=True).items()}
        stopped = {key[0]: set(f['symbol']) for key, f in suspensions.filter(pl.col('trade_date').is_between(low, high))
                   .partition_by('trade_date', as_dict=True).items()}
        for name, plan in plans.items():
            scheduled = {key[0]: {r['symbol']: r for r in f.iter_rows(named=True)} for key, f in
                         plan.filter(pl.col('effective_date').is_between(low, high)).partition_by('effective_date', as_dict=True).items()}
            first = plan['effective_date'].min()
            for date in (d for d in sessions if max(low, first) <= d <= high):
                states[name], row, events = index_day(date=date, state=states[name], quotes=quotes.get(date, {}),
                    actions=actions.get(date, {}), delisted=delisted, stopped=stopped.get(date, set()), targets=scheduled.get(date))
                all_rows.append({'index_name': name, **row})
                all_events.extend({'index_name': name, **e} for e in events)
        print(f'Completed {year}: {len(all_rows)} index days', flush=True)
    frame = pl.DataFrame(all_rows)
    frame.write_parquet(output / 'data.parquet')
    events_frame = pl.DataFrame(all_events, infer_schema_length=None)
    events_frame.write_parquet(output / 'events.parquet')
    summary = {'version': version, 'start': str(frame['trade_date'].min()), 'end': str(end),
               'anchor_level': 1000.0, 'rows': frame.height, 'statistics': str(statistics),
               'execution_snapshot': settings['execution_snapshot'], 'csi800_snapshot': battery['data']['csi800_snapshot'],
               'rules': settings['rules'], 'series': frame.group_by('index_name').agg(pl.len().alias('rows'),
                   pl.col('constituents').min().alias('minimum_constituents'), pl.col('constituents').max().alias('maximum_constituents')).to_dicts(),
               'events': events_frame.group_by('index_name', 'kind').len().to_dicts()}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def read_equal_weight_index(*, data_root: Path, version: str, index_name: str,
                            start: dt.date, end: dt.date) -> pl.DataFrame:
    """Read complete close-to-close daily index returns, retaining the first-day open anchor."""
    if Path(version).name != version or version in ('', '.', '..') or start > end:
        raise ValueError('Invalid index query')
    folder = data_root / 'clean/equal_weight_indexes' / version
    summary = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
    if (index_name not in {r['index_name'] for r in summary['series']}
            or str(start) < summary['start'] or str(end) > summary['end']):
        raise ValueError('Index or requested coverage unavailable')
    return pl.scan_parquet(folder / 'data.parquet').filter(
        (pl.col('index_name') == index_name) & pl.col('trade_date').is_between(start, end)
    ).sort('trade_date').with_columns(pl.col('trade_date').alias('date'),
                                     (pl.col('index_level') / 1000).alias('unit_nav')).collect()


def load_return_benchmarks(*, config: Path, data_root: Path, start: dt.date,
                           end: dt.date, names: list[str] | None = None) -> dict[str, pl.DataFrame]:
    """Load selected references with complete coverage; default to all three."""
    settings = tomllib.loads(config.read_text(encoding='utf-8'))['benchmarks']
    supported = ('510300', 'csi800_equal_weight', 'all_market_equal_weight')
    requested = list(supported) if names is None else names
    if not requested or len(set(requested)) != len(requested) or any(n not in supported for n in requested):
        raise ValueError('Invalid return benchmark names')
    if start > end:
        raise ValueError('Invalid return benchmark dates')
    dates = [d for d in available_sessions(data_root, end) if start <= d <= end]
    if not dates:
        raise ValueError('No benchmark sessions')
    result: dict[str, pl.DataFrame] = {}
    for name in requested:
        if name == '510300':
            etf = read_etf_total_return(data_root=data_root, snapshot=settings['etf_total_return_snapshot'], end=end)
            result[name] = etf.with_columns((pl.col('unit_nav') / pl.col('unit_nav').shift(1).fill_null(1.0))
                .alias('gross')).filter(pl.col('date') >= start).select('date', pl.col('gross').cum_prod().alias('unit_nav'))
        else:
            result[name] = read_equal_weight_index(data_root=data_root,
                version=settings['equal_weight_snapshot'], index_name=name, start=start, end=end).select(
                    'date', (1 + pl.col('daily_return')).cum_prod().alias('unit_nav'))
    for name, frame in result.items():
        if frame['date'].to_list() != dates:
            raise ValueError(f'Missing or duplicate benchmark sessions: {name}')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(publish(config=args.config, data_root=args.data_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
