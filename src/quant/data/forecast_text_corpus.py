"""Retain forecast/express text with its own publication date, not first forecast date."""
import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.tushare_bulk import _classify_probe_exception


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


def collect(*, symbols: list[str], start: dt.date, end: dt.date, output: Path,
            data_root: Path, interval: float = 1.3) -> dict:
    if (start > end or not symbols or len(symbols) != len(set(symbols)) or interval < 0
            or any(not re.fullmatch(r'[0-9]{6}\.(SH|SZ)', symbol) for symbol in symbols)):
        raise ValueError('Invalid text corpus scope')
    output.mkdir(parents=True, exist_ok=False)
    raw = data_root/'raw'/'forecast_text_corpus'/output.name
    raw.mkdir(parents=True, exist_ok=False)
    config = {'symbols': symbols, 'start': str(start), 'end': str(end), 'apis': ['forecast', 'express']}
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
    parser.add_argument('--from', dest='start', type=dt.date.fromisoformat)
    parser.add_argument('--to', dest='end', type=dt.date.fromisoformat)
    parser.add_argument('--build-from', nargs='+', type=Path, help='Existing raw forecast files')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    if args.build_from:
        print(json.dumps(build_corpus(args.build_from, args.output)), flush=True)
        return
    if not args.symbols or not args.start or not args.end:
        parser.error('Collection requires --symbols, --from and --to')
    collect(symbols=args.symbols.split(','), start=args.start, end=args.end, output=args.output, data_root=args.data_root)


if __name__ == '__main__':
    main()
