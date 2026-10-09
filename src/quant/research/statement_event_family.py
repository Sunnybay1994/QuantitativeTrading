"""Compute the fixed statement family and original-universe coverage without return labels."""
import argparse
import bisect
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data
from quant.data.statement_event_inputs import read_statement_events, read_statement_market
from quant.factors.statement_event_reaction import NAMES, attach_statement_reactions, compute_statement_reactions


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def save(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)


def run(*, output: Path, refresh: Path, definition: Path, universe: Path, data_root: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    spec = tomllib.loads(definition.read_text(encoding='utf-8'))
    if tuple(spec['signals']) != NAMES or spec['directions'] != [1, 1]:
        raise ValueError('This intake implements only the registered statement family')
    config = output/'refresh.toml'
    original = refresh.read_text(encoding='utf-8')
    config.write_text('statement_event_index_version = "'+spec['initial_index_version']+'"\n'
        +'statement_event_definition = '+json.dumps(definition.as_posix())+'\n'+original, encoding='utf-8')
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    sources = [refresh, definition, config, Path(spec['legacy_quarantine']), Path(spec['forecast_corpus']),
        data_root/'clean/tushare_financials'/settings['financial_snapshot']/'income.parquet']
    sources += list((data_root/'clean/index_benchmarks'/spec['initial_index_version']).glob('*.*'))
    sources += list((data_root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']/'bar_1d/asset=stock').glob('year=*/*.parquet'))
    sources += list((data_root/'clean/tushare_daily_basic/snapshots'/settings['daily_basic_snapshot']).glob('year=*/*.parquet'))
    sources += list(universe.glob('*/universe.parquet'))
    sources += [data_root/f'clean/trade_calendar/market={market}/data.parquet' for market in ('SH', 'SZ')]
    sources += [p/name for p in (data_root/'clean/tushare_incremental').glob('date=*')
        if '2008-09-01' <= p.name[5:] <= '2026-01-07'
        for name in ('bar_1d.parquet', 'daily_basic.parquet', 'adjust_factor.parquet') if (p/name).exists()]
    sources += [Path(__file__), Path('src/quant/factors/statement_event_reaction.py'),
        Path('src/quant/data/statement_event_inputs.py'), Path('src/quant/data/statement_event_dates.py')]
    manifest = {str(p): digest(p) for p in sorted(set(sources)) if p.is_file()}
    save(output/'source_manifest_before.json', manifest)
    calendar = available_sessions(data_root, dt.date(2026, 2, 1))
    # A full earlier year supplies carried events at the first 2010 month end.
    start, end = dt.date(2009, 1, 1), dt.date(2025, 12, 31)
    events = read_statement_events(data_root, config, start, end)
    events.write_parquet(output/'event_date_quality.parquet')
    reactions = []
    verification = []
    for year in range(2009, 2026):
        subset = events.filter(pl.col('announcement_date').dt.year() == year)
        first = bisect.bisect_left(calendar, dt.date(year, 1, 1))
        last = bisect.bisect_left(calendar, dt.date(year, 12, 31))
        low, high = calendar[max(0, first-65)], calendar[last+2]
        bars = read_stock_data(data_root=data_root, config=config, table='bar_1d', start=low, end=high)
        basic = read_stock_data(data_root=data_root, config=config, table='daily_basic', start=low, end=high)
        observations = bars.select('symbol', 'trade_date', 'close', 'adj_factor', 'volume').join(
            basic.select('symbol', 'trade_date', 'total_shares', 'float_shares'),
            on=['symbol', 'trade_date'], how='left', validate='1:1')
        market = read_statement_market(data_root, config, low, high)
        calculated = compute_statement_reactions(subset, observations, market, sessions=calendar)
        calculated.write_parquet(output/f'events_{year}.parquet')
        reactions.append(calculated)
        # Actual data prefixes must agree at the last close, including cross-month announcements.
        cutoff = max(d for d in calendar if d <= dt.date(year, 4, 30))
        prefix = compute_statement_reactions(subset.filter(pl.col('announcement_date') <= cutoff),
            observations.filter(pl.col('trade_date') <= cutoff), market.filter(pl.col('trade_date') <= cutoff), sessions=calendar)
        columns = ['symbol', 'announcement_date', *NAMES]
        left = prefix.filter(pl.col('reaction_end') <= cutoff).select(columns).sort(columns[:2])
        right = calculated.filter(pl.col('reaction_end') <= cutoff).select(columns).sort(columns[:2])
        if not left.equals(right):
            raise ValueError(f'Prefix changed in {year}')
        date_prefix = read_statement_events(data_root, config, dt.date(year, 1, 1), cutoff)
        if not date_prefix.equals(subset.filter(pl.col('announcement_date') <= cutoff)):
            raise ValueError(f'Date validation depends on future announcement in {year}')
        disturbed = observations.with_columns(*[pl.when(pl.col('trade_date') > cutoff)
            .then(pl.col(c)*7).otherwise(pl.col(c)).alias(c)
            for c in ('close', 'adj_factor', 'volume', 'total_shares', 'float_shares')])
        disturbed_market = market.with_columns(pl.when(pl.col('trade_date') > cutoff)
            .then(pl.col('index_level')*13).otherwise(pl.col('index_level')).alias('index_level'))
        changed = compute_statement_reactions(subset, disturbed, disturbed_market, sessions=calendar)
        changed = changed.filter(pl.col('reaction_end') <= cutoff).select(columns).sort(columns[:2])
        if not changed.equals(right):
            raise ValueError(f'Future input perturbation changed completed event in {year}')
        # Independent scalar formulas, using dates explicitly rather than the vectorized window join.
        valid = calculated.filter(pl.col('price_status') == 'valid').head(8)
        for row in valid.iter_rows(named=True):
            anchor = bisect.bisect_left(calendar, row['announcement_date'])
            stock = observations.filter((pl.col('symbol') == row['symbol']) & pl.col('trade_date').is_in([calendar[anchor-2], calendar[anchor+1]])).sort('trade_date')
            index = market.filter(pl.col('trade_date').is_in([calendar[anchor-2], calendar[anchor+1]])).sort('trade_date')
            px = (stock['close'] * stock['adj_factor']).to_list()
            expected = px[1]/px[0] - index['index_level'][1]/index['index_level'][0]
            if abs(row[NAMES[0]]-expected) > 1e-12:
                raise ValueError('Independent price formula differs')
        valid_volume = calculated.filter(pl.col('volume_status') == 'valid').head(8)
        for row in valid_volume.iter_rows(named=True):
            anchor = bisect.bisect_left(calendar, row['announcement_date'])
            stock = observations.filter(pl.col('symbol') == row['symbol'])
            base = stock.filter(pl.col('trade_date').is_in(calendar[anchor-63:anchor-7]))['volume'].to_list()
            event = stock.filter(pl.col('trade_date').is_in(calendar[anchor-1:anchor+2]))['volume'].to_list()
            expected = (sum(event)/3)/(sum(base)/56)-1
            if len(base) != 56 or len(event) != 3 or abs(row[NAMES[1]]-expected) > 1e-12:
                raise ValueError('Independent volume formula differs')
        verification.append({'year': year, 'prefix_rows': left.height, 'price_scalar_samples': valid.height,
            'volume_scalar_samples': valid_volume.height, 'future_perturbation_passed': True,
            'announcement_prefix_passed': True, 'passed': True})
        print(json.dumps({'year': year, 'events': calculated.height, 'price_valid': calculated[NAMES[0]].count(),
            'volume_valid': calculated[NAMES[1]].count()}), flush=True)
    result = pl.concat(reactions)
    forecasts = pl.read_parquet(spec['forecast_corpus'], columns=['ts_code', 'publication_date', 'report_period']).rename(
        {'ts_code': 'symbol', 'report_period': 'end_date'}).group_by('symbol', 'end_date').agg(
        pl.col('publication_date').min().alias('earliest_known_forecast'))
    result = result.join(forecasts, on=['symbol', 'end_date'], how='left', validate='m:1').with_columns(
        (pl.col('earliest_known_forecast') < pl.col('announcement_date')).fill_null(False).alias('known_earlier_forecast'),
        (pl.col('announcement_date').dt.strftime('%Y-%m') != pl.col('reaction_end').dt.strftime('%Y-%m')).alias('cross_month'))
    result.write_parquet(output/'event_signals.parquet')
    result.with_columns(pl.col('announcement_date').dt.year().alias('year')).group_by(
        'year', 'legacy_sue_status', 'event_date_status', 'price_status', 'volume_status',
        'known_earlier_forecast', 'cross_month').len().sort('year').write_parquet(output/'event_quality_breakdown.parquet')
    monthly = []
    for year in range(2010, 2026):
        keys = pl.read_parquet(universe/str(year)/'universe.parquet', columns=['symbol', 'trade_date', 'eligible'])
        monthends = [max(d for d in calendar if d.year == year and d.month == m) for m in range(1, 13)]
        keys = keys.filter(pl.col('eligible') & pl.col('trade_date').is_in(monthends)).select('symbol', 'trade_date')
        values = attach_statement_reactions(keys, result)
        monthly.append(values.group_by('trade_date').agg(pl.len().alias('eligible_count'),
            *[pl.col(n).count().alias(n+'_count') for n in NAMES]).sort('trade_date'))
    coverage = pl.concat(monthly).with_columns(*[(pl.col(n+'_count')/pl.col('eligible_count')).alias(n+'_coverage') for n in NAMES])
    coverage.write_parquet(output/'monthly_coverage.parquet')
    warmup_events = result.filter(pl.col('announcement_date').dt.year() == 2009).height
    result = result.filter(pl.col('announcement_date') >= dt.date(2010, 1, 1))
    after = {p: digest(Path(p)) for p in manifest}
    save(output/'source_manifest_after.json', after)
    if manifest != after:
        raise ValueError('Input or implementation changed during computation')
    save(output/'verification.json', {'source_hashes_equal': True, 'yearly': verification,
        'label_data_read': False, 'vintage_limitation': 'Publication-date replay; original source-observed vintages not established'})
    summary = {'family': spec['family'], 'events': result.height, 'warmup_2009_events': warmup_events,
        'date_valid': result['event_date_valid'].sum(),
        'cross_month': result['cross_month'].sum(), 'known_earlier_forecast': result['known_earlier_forecast'].sum(),
        'nonvalid_sue_date_passed': result.filter(pl.col('event_date_valid') & (pl.col('legacy_sue_status') != 'VALID')).height,
        'price_status': result.group_by('price_status').len().to_dicts(),
        'volume_status': result.group_by('volume_status').len().to_dicts(),
        'signals': {n: {'valid_events': result[n].count(), 'months_at_least_100': coverage.filter(pl.col(n+'_count') >= 100).height,
            'minimum_monthly_coverage': coverage[n+'_coverage'].min(), 'median_monthly_coverage': coverage[n+'_coverage'].median()} for n in NAMES},
        'interpretation': 'Computability only; original N1/N3/N4 admission and account performance remain untested'}
    save(output/'summary.json', summary)
    (output/'report.md').write_text('# Statement event family input verification\n\n```json\n'+json.dumps(summary, ensure_ascii=False, indent=2)+'\n```\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refresh', type=Path, required=True)
    parser.add_argument('--definition', type=Path, default=Path('configs/research/statement_event_family_v1.toml'))
    parser.add_argument('--universe', type=Path, default=Path('artifacts/factors/battery_statistics_20260831_20260911/inputs'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
