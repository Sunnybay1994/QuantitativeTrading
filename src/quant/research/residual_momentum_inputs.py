"""Read-only month-end inputs for the fixed residual-momentum research family."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.factors.reversal_volatility import size_value_proxy_returns


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def month_end_dates(sessions, start, end):
    dates = pl.DataFrame({'trade_date': [d for d in sessions if start <= d <= end]})
    if dates.is_empty():
        raise ValueError('No exchange sessions in monthly input range')
    return tuple(dates.group_by(pl.col('trade_date').dt.month_start()).agg(
        pl.col('trade_date').max().alias('month_end'))['month_end'].sort().to_list())


def monthly_panel(bars, basic, month_ends):
    """Require the exact calendar close; a missing endpoint never bridges a month."""
    keys = ['symbol', 'trade_date']
    for frame in (bars, basic):
        if frame.select(keys).is_duplicated().any():
            raise ValueError('Duplicate month-end source keys')
    # Filter only security type, not current listing/eligibility or future survival.
    bars = bars.filter(pl.col('symbol').str.contains(r'^(60|68|00|30)[0-9]{4}\.(SH|SZ)$'))
    grid = bars.select('symbol').unique().join(
        pl.DataFrame({'trade_date': month_ends}, schema={'trade_date': pl.Date}), how='cross')
    grid = grid.join(bars.select(*keys, 'close', 'adj_factor'), on=keys, how='left', validate='1:1')
    grid = grid.join(basic.select(*keys, 'total_market_value', 'pb'), on=keys, how='left', validate='1:1')
    grid = grid.sort(keys).with_columns(
        pl.when(pl.all_horizontal(pl.col(c).is_finite() & (pl.col(c) > 0)
                                  for c in ('close', 'adj_factor')))
        .then(pl.col('close') * pl.col('adj_factor')).otherwise(None).alias('_price'))
    grid = grid.with_columns(
        (pl.col('_price') / pl.col('_price').shift(1).over('symbol') - 1).alias('_return'),
        pl.col('total_market_value').shift(1).over('symbol').alias('_lag_mv'),
        pl.col('trade_date').dt.month_start().alias('_month'))
    return grid.with_columns(pl.when(pl.col('_return').is_finite()).then(pl.col('_return'))
                             .otherwise(None).alias('_return'))


def freeze_inputs(*, config: Path, output: Path, data_root: Path) -> dict:
    """Freeze projected data and all exact source hashes before looking at labels."""
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    data = spec['data']
    refresh = Path(data['refresh_config'])
    settings = tomllib.loads(refresh.read_text(encoding='utf-8'))
    calendar = available_sessions(data_root, data['as_of'] + dt.timedelta(days=40))
    position = calendar.index(data['as_of'])
    if position + 1 == len(calendar) or calendar[position + 1].month == data['as_of'].month:
        raise ValueError('Research cutoff must be a completed exchange month end')
    months = month_end_dates(calendar, data['warmup_start'], data['as_of'])
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    (output/'refresh.toml').write_bytes(refresh.read_bytes())
    (output/'battery.toml').write_bytes(Path(data['battery_config']).read_bytes())
    write_json(output/'started.json', {'started_at': dt.datetime.now(dt.timezone.utc),
        'config_sha256': digest(config), 'stage': 'freezing_label_free_inputs'})
    source_paths = [refresh, Path(data['battery_config']),
                    data_root/'clean/trade_calendar/market=SH/data.parquet',
                    data_root/'clean/trade_calendar/market=SZ/data.parquet']
    source_hashes = {str(p): digest(p) for p in source_paths}
    frames = {'bar_1d': [], 'daily_basic': []}
    for year in sorted({d.year for d in months}):
        dates = [d for d in months if d.year == year]
        base = {'bar_1d': data_root/'clean/tushare_bulk/snapshots'/settings['stock_snapshot']
                    /f'bar_1d/asset=stock/year={year}',
                'daily_basic': data_root/'clean/tushare_daily_basic/snapshots'/settings['daily_basic_snapshot']
                    /f'year={year}'}
        for table, columns in {'bar_1d': ['symbol', 'trade_date', 'close', 'adj_factor'],
                              'daily_basic': ['symbol', 'trade_date', 'total_market_value', 'pb']}.items():
            paths = sorted(base[table].glob('*.parquet'))
            for day in dates:
                folder = data_root/f'clean/tushare_incremental/date={day}'
                if all((folder/f'{t}.parquet').is_file() for t in ('bar_1d', 'daily_basic', 'adjust_factor')):
                    paths.append(folder/f'{table}.parquet')
            if not paths:
                raise ValueError(f'Missing {table} history in {year}')
            hashes = {str(path): digest(path) for path in paths}
            frame = pl.concat([pl.scan_parquet(p).filter(pl.col('trade_date').is_in(dates))
                               .select(columns) for p in paths], how='vertical_relaxed').collect()
            # Match the existing frozen-history + completed-increment precedence.
            frame = frame.unique(['symbol', 'trade_date'], keep='last', maintain_order=True)
            if any(digest(path) != hashes[str(path)] for path in paths):
                raise ValueError('Monthly source changed while read')
            source_hashes.update(hashes)
            frames[table].append(frame)
        print(json.dumps({'input_year': year, 'month_ends': len(dates)}), flush=True)
    bars, basic = (pl.concat(frames[t], how='vertical_relaxed') for t in ('bar_1d', 'daily_basic'))
    missing = set(months) - set(bars['trade_date'])
    if missing:
        raise ValueError(f'Entire month-end prices missing: {sorted(missing)}')
    grid = monthly_panel(bars, basic, months)
    proxies = size_value_proxy_returns(grid, minimum_bucket_symbols=10)
    returns = grid.select('symbol', 'trade_date', pl.col('_return').alias('stock_return'))
    for name, frame in {'monthly_returns': returns, 'monthly_factors': proxies,
                        'monthly_inputs': grid}.items():
        frame.write_parquet(output/f'{name}.parquet')
    if any(digest(Path(p)) != sha for p, sha in source_hashes.items()):
        raise ValueError('Monthly source changed before input publication')
    manifest = {'config_sha256': digest(config), 'source_files': source_hashes,
        'projected_files': {p.name: digest(p) for p in output.glob('*.parquet')},
        'month_ends': months, 'rows': grid.height, 'historical_symbols': grid['symbol'].n_unique(),
        'proxy_rows': proxies.height, 'proxy_complete_rows': proxies.drop_nulls().height,
        'finished_at': dt.datetime.now(dt.timezone.utc), 'label_free': True}
    write_json(output/'input_manifest.json', manifest)
    return manifest
