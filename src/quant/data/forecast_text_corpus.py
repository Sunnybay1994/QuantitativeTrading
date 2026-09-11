"""Retain forecast/express text with its own publication date, not first forecast date."""
import argparse
import datetime as dt
import json
import re
import random
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.tushare_bulk import _classify_probe_exception


def select_historical_scope(inputs: list[Path], output: Path, *, count: int = 512,
                            seed: int = 20260912) -> dict:
    """Freeze a reproducible sample before querying its forecast text."""
    frame = pl.concat([pl.read_parquet(path) for path in inputs], how='diagonal_relaxed')
    eligible = frame.filter(
        pl.col('ts_code').str.contains(r'^[036][0-9]{5}\.(SH|SZ)$')
        & (pl.col('list_date') <= '20170101')
        & (pl.col('delist_date').is_null() | (pl.col('delist_date') == '')
           | (pl.col('delist_date') >= '20100101'))
    )['ts_code'].unique().sort().to_list()
    symbols = sorted(random.Random(seed).sample(eligible, count))
    result = {'symbols': symbols, 'seed': seed, 'eligible': len(eligible),
              'source_files': [str(path) for path in inputs],
              'selection': 'SH/SZ A shares listed by 2017-01-01 and not delisted before '
                           '2010-01-01; includes subsequently delisted stocks; random sample.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    return result


def normalize_forecasts(frame: pl.DataFrame) -> pl.DataFrame:
    """Keep each publication, including revisions; empty reasons remain missing."""
    required = {'ts_code', 'ann_date', 'end_date', 'change_reason'}
    if not required.issubset(frame.columns):
        raise ValueError('Missing forecast columns')
    result = frame.with_columns(
        pl.col('ann_date').str.to_date('%Y%m%d').alias('publication_date'),
        pl.col('end_date').str.to_date('%Y%m%d').alias('report_period'),
        pl.col('change_reason').str.strip_chars().replace('', None).alias('reason_text'),
    )
    if result.filter(
        pl.col('publication_date').is_null() | pl.col('report_period').is_null()
        | pl.col('ts_code').is_null()
        | ~pl.col('ts_code').str.contains(r'^[0-9]{6}\.(SH|SZ)$')
    ).height:
        raise ValueError('Invalid forecast identity or dates')
    # Same-day conflicting releases cannot be ordered without a timestamp.
    result = result.unique(maintain_order=True)
    keys = ['ts_code', 'publication_date', 'report_period']
    result = result.with_columns(
        (pl.len().over(keys) > 1).alias('same_day_conflict'),
        pl.lit('after_close').alias('availability'),
    )
    return result.sort(keys)


def build_corpus(inputs: list[Path], output: Path) -> dict:
    """Publish inspectable clean text and coverage from retained raw forecasts."""
    frames = [pl.read_parquet(path) for path in inputs]
    if not frames:
        raise ValueError('No forecast inputs')
    frame = normalize_forecasts(pl.concat(frames, how='diagonal_relaxed'))
    output.mkdir(parents=True, exist_ok=False)
    frame.write_parquet(output/'forecasts.parquet')
    yearly = frame.group_by(pl.col('publication_date').dt.year().alias('year')).agg(
        pl.len().alias('forecasts'), pl.col('reason_text').count().alias('with_reason'),
        pl.col('ts_code').n_unique().alias('symbols'),
    ).sort('year')
    yearly.write_csv(output/'coverage.csv')
    summary = {'rows': frame.height, 'symbols': frame['ts_code'].n_unique(),
               'with_reason': frame['reason_text'].count(),
               'same_day_conflicts': frame['same_day_conflict'].sum(),
               'first': str(frame['publication_date'].min()),
               'last': str(frame['publication_date'].max()),
               'inputs': [str(path) for path in inputs],
               'availability': 'Own announcement date after close; never first_ann_date. '
                               'Vendor history is not an archived original-text verification.'}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def monthly_coverage(frame: pl.DataFrame, *, start: dt.date, end: dt.date) -> pl.DataFrame:
    """Describe month-end availability, not trading signals or return performance."""
    if start > end:
        raise ValueError('Reversed coverage dates')
    rows = []
    month = start.replace(day=1)
    while month <= end:
        following = (month.replace(year=month.year + 1, month=1) if month.month == 12
                     else month.replace(month=month.month + 1))
        cutoff = min(following - dt.timedelta(days=1), end)
        known = frame.filter(pl.col('publication_date') <= cutoff)
        # A newer textless publication invalidates older text for this coverage estimate.
        latest = known.sort('ts_code', 'publication_date', 'report_period').unique(
            subset=['ts_code'], keep='last', maintain_order=True,
        )
        for days in (30, 90, 120):
            recent = latest.filter(pl.col('publication_date') > cutoff - dt.timedelta(days=days))
            usable = recent.filter(pl.col('reason_text').is_not_null()
                                   & ~pl.col('same_day_conflict'))
            rows.append({'as_of': cutoff, 'max_age_days': days,
                         'recent_forecast_symbols': recent.height,
                         'reason_symbols': usable.height})
        month = following
    return pl.DataFrame(rows)


def collect(*, symbols: list[str], start: dt.date, end: dt.date, output: Path,
            data_root: Path, interval: float = 1.3,
            apis: tuple[str, ...] = ('forecast', 'express')) -> dict:
    if (start > end or not symbols or len(symbols) != len(set(symbols)) or interval < 0
            or any(not re.fullmatch(r'[0-9]{6}\.(SH|SZ)', symbol) for symbol in symbols)):
        raise ValueError('Invalid text corpus scope')
    if not apis or len(set(apis)) != len(apis) or set(apis) - {'forecast', 'express'}:
        raise ValueError('Invalid text corpus APIs')
    output.mkdir(parents=True, exist_ok=False)
    raw = data_root/'raw'/'forecast_text_corpus'/output.name
    raw.mkdir(parents=True, exist_ok=False)
    config = {'symbols': symbols, 'start': str(start), 'end': str(end), 'apis': list(apis)}
    (output/'scope.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    client = TushareConnector()
    rows = []
    for symbol in symbols:
        for api in config['apis']:
            params = {'ts_code': symbol, 'start_date': start.strftime('%Y%m%d'), 'end_date': end.strftime('%Y%m%d')}
            captured = dt.datetime.now(dt.timezone.utc).isoformat()
            try:
                frame = client.query_raw(api, **params)
                frame.write_parquet(raw/f'{api}_{symbol}.parquet')
                if frame.height and (set(frame['ts_code']) != {symbol} or
                    frame.filter(pl.col('ann_date').is_null() |
                        ~pl.col('ann_date').str.to_date('%Y%m%d').is_between(start, end)).height):
                    raise ValueError('Provider returned records outside requested scope')
                text_fields = [key for key in ('summary', 'change_reason', 'perf_summary') if key in frame.columns]
                row = {'api': api, 'symbol': symbol, 'rows': frame.height, 'captured_at': captured,
                    'result': 'returned', 'columns': frame.columns,
                    'first': frame['ann_date'].min() if frame.height else None,
                    'last': frame['ann_date'].max() if frame.height else None,
                    'text_fields': {key: frame.filter(pl.col(key).is_not_null() &
                        (pl.col(key).str.strip_chars() != '')).height for key in text_fields},
                    'potentially_truncated': frame.height >= (3500 if api == 'forecast' else 1000)}
            except Exception as exc:
                row = {'api': api, 'symbol': symbol, 'captured_at': captured,
                       'result': _classify_probe_exception(exc).lower()}
            rows.append(row)
            (output/'summary.json').write_text(json.dumps({'scope': config, 'requests': rows}, indent=2), encoding='utf-8')
            print(json.dumps(row, ensure_ascii=True), flush=True)
            time.sleep(interval)
    return {'scope': config, 'requests': rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols')
    parser.add_argument('--symbols-file', type=Path, help='JSON file containing a symbols list')
    parser.add_argument('--apis', nargs='+', choices=['forecast', 'express'],
                        default=['forecast', 'express'])
    parser.add_argument('--from', dest='start', type=dt.date.fromisoformat)
    parser.add_argument('--to', dest='end', type=dt.date.fromisoformat)
    parser.add_argument('--build-from', nargs='+', type=Path, help='Existing raw forecast files')
    parser.add_argument('--coverage-from', type=Path, help='Normalized forecast parquet')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    if args.coverage_from:
        if not args.start or not args.end or args.build_from:
            parser.error('Coverage requires --from and --to, without --build-from')
        result = monthly_coverage(pl.read_parquet(args.coverage_from),
                                  start=args.start, end=args.end)
        args.output.mkdir(parents=True, exist_ok=False)
        result.write_csv(args.output/'monthly_coverage.csv')
        print(result.group_by('max_age_days').agg(
            (pl.col('reason_symbols') >= 100).sum().alias('months_at_least_100'),
            pl.col('reason_symbols').min().alias('minimum_symbols'),
        ).sort('max_age_days'))
        return
    if args.build_from:
        print(json.dumps(build_corpus(args.build_from, args.output)), flush=True)
        return
    if args.symbols and args.symbols_file:
        parser.error('Use one symbol source')
    if not (args.symbols or args.symbols_file) or not args.start or not args.end:
        parser.error('Collection requires --symbols, --from and --to')
    symbols = (json.loads(args.symbols_file.read_text(encoding='utf-8'))['symbols']
               if args.symbols_file else args.symbols.split(','))
    collect(symbols=symbols, start=args.start, end=args.end, output=args.output,
            data_root=args.data_root, apis=tuple(args.apis))


if __name__ == '__main__':
    main()
