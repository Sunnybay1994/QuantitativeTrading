"""Read only published D1/D2 native event versions and frozen monthly battery inputs."""
import datetime as dt
import json
from pathlib import Path

import polars as pl

TABLES = ('repurchase', 'stk_holdertrade', 'share_float', 'stk_holdernumber', 'report_rc')


def read_sources(data_root: Path, observed_at: dt.datetime):
    if observed_at.tzinfo is None:
        raise ValueError('Require actual zoned observation cutoff')
    result, paths, facts = {}, [], {}
    required = {'ts_code', 'source_row_id', 'source_raw_path', 'source_announcement_date',
                'available_at', 'observed_at'}
    for table in TABLES:
        sections, summaries = [], []
        for summary in sorted((data_root/'clean'/table).glob('snapshot=*/summary.json')):
            files = sorted(summary.parent.glob('year=*/data.parquet'))
            if (summary.parent/'data.parquet').is_file():
                files.append(summary.parent/'data.parquet')
            for path in files:
                frame = pl.read_parquet(path)
                if not required <= set(frame.columns):
                    raise ValueError(f'Published {table} lacks native observation provenance')
                for key in ('available_at', 'observed_at'):
                    if frame.schema[key].time_zone is None:
                        raise ValueError(f'{table} observation timestamps require timezone')
                if frame.select(pl.any_horizontal(pl.col(*required).is_null()).any()).item():
                    raise ValueError(f'{table} has missing observation provenance')
                sections.append(frame.filter((pl.col('available_at') <= observed_at)
                                              & (pl.col('observed_at') <= observed_at)))
                paths.append(path)
            if files:
                paths.append(summary)
                summaries.append(json.loads(summary.read_text(encoding='utf-8')))
        frame = pl.concat(sections, how='diagonal_relaxed') if sections else pl.DataFrame()
        if frame.width:
            frame = frame.with_columns(pl.max_horizontal('available_at', 'observed_at').alias('known_at'))
            frame = frame.sort('known_at').unique('source_row_id', keep='first', maintain_order=True)
        result[table] = frame
        facts[table] = {'rows': frame.height, 'published_snapshots': len(summaries),
            'first_known_at': frame['known_at'].min().isoformat() if frame.height else None,
            'first_announcement': str(frame['source_announcement_date'].min()) if frame.height else None,
            'last_announcement': str(frame['source_announcement_date'].max()) if frame.height else None,
            'historical_vintage_verified': False,
            'permissions': sorted({str(s.get('permission') or s.get('status') or 'history_capture') for s in summaries})}
    return result, sorted(set(paths)), facts


def read_monthly(inputs: Path, start: dt.date, end: dt.date):
    frames, paths = [], []
    for year in range(start.year, end.year+1):
        folder = inputs/str(year)
        labels_path, universe_path = folder/'monthly_labels.parquet', folder/'universe.parquet'
        labels = pl.read_parquet(labels_path).filter(pl.col('trade_date').is_between(start, end))
        # Future or immature labels are not used even if a later cached file contains them.
        labels = labels.with_columns(pl.when(pl.col('exit_date_rebalance') <= end)
                                    .then(pl.col('label_rebalance')).otherwise(None).alias('label_rebalance'))
        dates = labels['trade_date'].unique()
        universe = pl.scan_parquet(universe_path).filter(
            pl.col('eligible') & pl.col('trade_date').is_in(dates.implode())).select(
                'symbol', 'trade_date', 'total_market_value', 'industry_l1').collect()
        frames.append(universe.join(labels.select('symbol', 'trade_date', 'label_rebalance'),
                                    on=['symbol', 'trade_date'], how='left', validate='1:1'))
        paths.extend([labels_path, universe_path])
    return pl.concat(frames), paths
