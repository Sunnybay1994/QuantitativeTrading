"""Reconcile retained Hong Kong feasibility samples; no network in analysis."""
import json
from pathlib import Path

import polars as pl

from quant.data.connectors.hkex_shareholding import parse_holdings


def holding_pages(probe: Path) -> list[Path]:
    return [probe/'hkex_latest.html', *sorted(probe.glob('hkex_????-??-??.html'))]


def compare_market_flows(probe: Path, raw: Path) -> list[dict]:
    frames = [pl.read_parquet(path) for path in raw.glob('*moneyflow_hsgt.parquet')]
    vendor = pl.concat(frames, how='diagonal_relaxed')
    rows = []
    for path in sorted(probe.glob('hkex_daily_????????.js')):
        text = path.read_text(encoding='utf-8').split('=', 1)[1].strip().rstrip(';')
        markets = json.loads(text)
        south_buy, south_sell, north_total = 0., 0., 0.
        for market in markets:
            table = next(block['table'] for block in market['content']
                         if block.get('table', {}).get('classname') == 'tradingTable')
            values = dict(zip(table['schema'][0], [float(row['td'][0][0].replace(',', '')) for row in table['tr']]))
            if 'Southbound' in market['market']:
                south_buy += values['Buy Turnover']
                south_sell += values['Sell Turnover']
            else:
                north_total += values['Total Turnover']
        date = markets[0]['date']
        row = vendor.filter(pl.col('trade_date') == date.replace('-', '')).row(0, named=True)
        rows.append({'date': date, 'vendor_south_money': float(row['south_money']),
            'official_south_net_hkd_million': south_buy-south_sell,
            'official_south_total_hkd_million': south_buy+south_sell,
            'vendor_north_money': float(row['north_money']),
            'official_north_total_rmb_million': north_total})
    return rows


def read_holdings(raw: Path) -> pl.DataFrame:
    frames = [pl.read_parquet(path) for path in sorted(raw.glob('*hk_hold.parquet'))]
    frames = [frame for frame in frames if frame.height]
    result = pl.concat(frames, how='diagonal_relaxed').select(
        pl.col('ts_code').alias('symbol'), pl.col('trade_date').str.to_date('%Y%m%d').alias('holding_date'),
        pl.col('vol').cast(pl.Int64).alias('shares'), pl.col('ratio').cast(pl.Float64).alias('issued_share_percent'),
        'exchange')
    if result.select('symbol', 'holding_date', 'exchange').is_duplicated().any():
        raise ValueError('Duplicate southbound holdings keys')
    if result.filter((pl.col('shares') < 0) | ~pl.col('issued_share_percent').is_between(0., 100.)).height:
        raise ValueError('Invalid southbound holdings values')
    return result.sort('symbol', 'holding_date')


def analyze(probe: Path, yahoo: Path, data_root: Path) -> dict:
    raw = data_root/'raw'/'hk_low_frequency_probe'/probe.name
    holdings = read_holdings(raw)
    coverage = holdings.group_by('symbol').agg(pl.len().alias('rows'),
        pl.col('holding_date').min().alias('first'), pl.col('holding_date').max().alias('last'),
        (pl.col('holding_date').dt.weekday() > 5).sum().alias('weekend_rows')).sort('symbol')
    comparisons = []
    for path in holding_pages(probe):
        frame = parse_holdings(path.read_text(encoding='utf-8')).rename({'shareholding_date': 'holding_date'})
        joined = holdings.join(frame, on=['symbol', 'holding_date'], suffix='_official')
        comparisons.append({'date': str(frame['holding_date'][0]), 'official_rows': frame.height,
            'missing_official_percent': frame['issued_share_percent'].null_count(), 'sample_matches': joined.height,
            'maximum_share_difference': joined.select((pl.col('shares')-pl.col('shares_official')).abs().max()).item(),
            'maximum_percent_difference': joined.select((pl.col('issued_share_percent')-
                pl.col('issued_share_percent_official')).abs().max()).item()})
    vendor = pl.read_parquet(raw/'01_hk_daily.parquet').with_columns(
        pl.col('trade_date').str.to_date('%Y%m%d').alias('date'))
    daily = pl.read_parquet(yahoo/'00700.HK.parquet')
    joined = vendor.select('date', pl.col('close').alias('vendor_close'), pl.col('vol').alias('vendor_volume')).join(
        daily.select('date', 'close', 'volume'), on='date').sort('date').with_columns(
        (pl.col('close')/pl.col('vendor_close')).alias('price_ratio'))
    breaks = joined.with_columns(pl.col('price_ratio').diff().alias('change')).filter(pl.col('change').abs() > .01)
    extra = daily.join(vendor.select('date'), on='date', how='anti').select('date', 'close', 'volume')
    calendar = pl.read_parquet(data_root/'clean'/'trade_calendar'/'market=HK'/'data.parquet')
    classified = holdings.join(calendar.select(pl.col('date').alias('holding_date'), 'is_open'),
                               on='holding_date', how='left')
    return {'holdings': coverage.to_dicts(), 'official_comparisons': comparisons,
        'market_flow_comparisons': compare_market_flows(probe, raw),
        'calendar': {'first': str(calendar['date'].min()), 'last': str(calendar['date'].max()),
            'outside_calendar': classified['is_open'].null_count(),
            'known_closed_day_rows': classified.filter(~pl.col('is_open')).height},
        'tencent_price_comparison': {'common_dates': joined.height,
            'maximum_close_difference': joined.select((pl.col('close')-pl.col('vendor_close')).abs().max()).item(),
            'median_volume_ratio': joined.select((pl.col('vendor_volume')/pl.col('volume')).median()).item(),
            'first_pair': joined.head(1).to_dicts()[0], 'last_pair': joined.tail(1).to_dicts()[0],
            'large_ratio_breaks': breaks.select('date', 'price_ratio', 'change').to_dicts(),
            'yahoo_extra_dates': extra.to_dicts()},
        'yahoo_coverage': json.loads((yahoo/'summary.json').read_text(encoding='utf-8'))}


def save_samples(probe: Path, data_root: Path, *, version: str) -> dict:
    """Keep source dates and archive time distinct; do not invent publication time."""
    raw = data_root/'raw'/'hkex_southbound_samples'/version
    clean = data_root/'clean'/'hk_southbound_samples'/version
    raw.mkdir(parents=True, exist_ok=False)
    clean.mkdir(parents=True, exist_ok=False)
    for path in holding_pages(probe):
        payload = path.read_bytes()
        (raw/path.name).write_bytes(payload)
        frame = parse_holdings(payload.decode('utf-8'))
        frame.write_parquet(clean/f'hkex_{frame["shareholding_date"][0]}.parquet')
    read_holdings(data_root/'raw'/'hk_low_frequency_probe'/probe.name).write_parquet(clean/'tushare_holdings.parquet')
    source = {'historical_publication_timestamps': 'not_available', 'probe': str(probe),
        'purpose': 'source feasibility sample; not a historical investable universe',
        'holdings_definition': 'aggregate ChinaClear holdings, not official net purchases'}
    (clean/'source.json').write_text(json.dumps(source, indent=2), encoding='utf-8')
    return {'clean': str(clean), 'raw': str(raw)}


def archive_daily_statistics(probe: Path, data_root: Path, *, version: str) -> None:
    folder = data_root/'raw'/'hkex_daily_samples'/version
    folder.mkdir(parents=True, exist_ok=False)
    for path in [probe/'hkex_daily.html', *sorted(probe.glob('hkex_daily_????????.js'))]:
        (folder/path.name).write_bytes(path.read_bytes())
