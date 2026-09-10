"""Inspect duplicate ex-date dividend records already captured for a backtest."""

import argparse
import datetime as dt
import json
from pathlib import Path

import polars as pl


def read_cached_history(data_root: Path, start: dt.date, end: dt.date) -> pl.DataFrame:
    latest: dict[str, Path] = {}
    for path in sorted((data_root / 'raw/tushare/dividend').glob('date=*/*.json')):
        meta = json.loads(path.read_text(encoding='utf-8'))
        symbol = meta.get('parameters', {}).get('ts_code')
        if symbol:
            latest[symbol] = path.with_suffix('.parquet')
    frames = [pl.read_parquet(p) for p in latest.values()]
    return pl.concat(frames, how='diagonal_relaxed').filter(
        (pl.col('div_proc') == '实施') & pl.col('ex_date').is_not_null()
        & pl.col('ex_date').is_between(pl.lit(start.strftime('%Y%m%d')), pl.lit(end.strftime('%Y%m%d'))))


def read_conflicts(data_root: Path, start: dt.date, end: dt.date) -> pl.DataFrame:
    raw = read_cached_history(data_root, start, end)
    keys = raw.group_by('ts_code', 'ex_date').len().filter(pl.col('len') > 1)
    return raw.join(keys.select('ts_code', 'ex_date'), on=['ts_code', 'ex_date']).sort('ts_code', 'ex_date', 'end_date')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--end', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--invalid-dates', action='store_true')
    args = parser.parse_args()
    frame = read_conflicts(Path('data'), args.start, args.end)
    if args.invalid_dates:
        frame = read_cached_history(Path('data'), args.start, args.end).filter(
            pl.col('imp_ann_date').is_null() | pl.col('record_date').is_null()
            | (pl.col('imp_ann_date') > pl.col('ex_date')) | (pl.col('record_date') >= pl.col('ex_date'))
            | ((pl.col('cash_div_tax').cast(pl.Float64).fill_null(0) > 0)
               & (pl.col('pay_date').is_null() | (pl.col('pay_date') < pl.col('ex_date'))))
            | ((pl.col('stk_div').cast(pl.Float64).fill_null(0) > 0)
               & (pl.col('div_listdate').is_null() | (pl.col('div_listdate') < pl.col('ex_date')))))
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(frame.to_dicts(), out, ensure_ascii=False, indent=2)
    print(frame.select('ts_code', 'end_date', 'ann_date', 'imp_ann_date', 'record_date', 'ex_date', 'cash_div_tax', 'stk_div').write_csv())


if __name__ == '__main__':
    main()
