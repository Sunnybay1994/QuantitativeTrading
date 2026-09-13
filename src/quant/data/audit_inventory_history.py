"""Audit existing published inventory history before registering inventory factors."""
import argparse
import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.financial_repository import TushareFinancialHistoryQuery, read_tushare_financial_history


def run(*, data_root: Path, snapshot: str, output: Path) -> dict:
    if Path(snapshot).name != snapshot or snapshot in ('.', '..'):
        raise ValueError('Invalid financial snapshot')
    path = data_root/'clean/tushare_financials'/snapshot/'balancesheet.parquet'
    symbols = pl.scan_parquet(path).select('symbol').unique().collect()['symbol'].to_list()
    frame = read_tushare_financial_history(data_root=data_root,
        query=TushareFinancialHistoryQuery(snapshot, 'balancesheet', dt.date(2010, 1, 1),
            dt.date(2026, 9, 13), tuple(symbols), extra_fields=('inventories',)))
    valid = (pl.col('inventories').is_finite() & (pl.col('inventories') >= 0)
             & pl.col('total_assets').is_finite() & (pl.col('total_assets') > 0)).fill_null(False)
    counts = frame.with_columns(valid.alias('valid'), pl.col('end_date').dt.year().alias('year'))
    annual = counts.group_by('year').agg(pl.len().alias('revision_rows'),
        pl.col('valid').sum().alias('valid_rows'),
        pl.col('symbol').filter(pl.col('valid')).n_unique().alias('valid_symbols')).sort('year')
    result = {'snapshot': snapshot, 'rows': frame.height, 'symbols': frame['symbol'].n_unique(),
        'valid_rows': counts['valid'].sum(), 'source_min_period': str(frame['end_date'].min()),
        'source_max_period': str(frame['end_date'].max()),
        'scope': 'Published revision coverage; not PIT-selected monthly availability or a factor result'}
    output.mkdir(parents=True, exist_ok=False)
    annual.write_csv(output/'annual_coverage.csv')
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(run(**vars(parser.parse_args()))))
