"""Load published factor terminals on the frozen monthly research universe."""
import datetime as dt
from pathlib import Path

import polars as pl


def read_genetic_panel(*, data_root: Path, statistics: list[Path], factors: list[str],
                       start: dt.date, end: dt.date) -> pl.DataFrame:
    """Require exactly one frozen source per year; preserve missing factor values."""
    frames = []
    keys = ['symbol', 'trade_date']
    for factor in factors:
        if not factor.isidentifier():
            raise ValueError('Invalid factor terminal name')
    for year in range(start.year, end.year + 1):
        folders = [root / f'inputs/{year}' for root in statistics
                   if (root / f'inputs/{year}/monthly_labels.parquet').is_file()]
        if len(folders) != 1:
            raise ValueError(f'Expected one frozen monthly label source for {year}')
        folder = folders[0]
        labels = pl.read_parquet(folder / 'monthly_labels.parquet').filter(
            pl.col('trade_date').is_between(start, end))
        universe = pl.scan_parquet(folder / 'universe.parquet').filter(
            pl.col('eligible')).select(keys).collect()
        frame = labels.join(universe, on=keys, how='inner', validate='1:1')
        for factor in factors:
            path = data_root / 'factors' / factor / f'year={year}/data.parquet'
            scan = pl.scan_parquet(path).rename({'ts_code': 'symbol', 'value': factor})
            values = scan.filter(pl.col('trade_date').is_in(
                frame['trade_date'].unique().implode())).select(*keys, factor).collect()
            frame = frame.join(values, on=keys, how='left', validate='1:1')
        frames.append(frame)
    return pl.concat(frames).rename({'label_rebalance': 'label',
                                    'exit_date_rebalance': 'label_exit_date'}).sort(keys)
