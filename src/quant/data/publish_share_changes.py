"""Publish captured CNINFO share-change events for annual financial research."""

import argparse
import datetime as dt
import json
from pathlib import Path

import polars as pl


def normalize_share_changes(raw: pl.DataFrame, *, symbol: str, source_file: str) -> pl.DataFrame:
    """Preserve event and announcement dates separately; do not infer issuance."""
    if len(symbol) != 9 or symbol[6:] not in ('.SH', '.SZ') or not symbol[:6].isdigit():
        raise ValueError('Invalid share-change symbol')
    if raw.filter(pl.col('SECCODE').is_null() | (pl.col('SECCODE') != symbol[:6])).height:
        raise ValueError('Share-change response contains another symbol')
    events = raw.select(
        pl.lit(symbol).alias('symbol'),
        pl.col('DECLAREDATE').cast(pl.String).str.to_date('%Y-%m-%d').alias('ann_date'),
        pl.col('VARYDATE').cast(pl.String).str.to_date('%Y-%m-%d').alias('event_date'),
        pl.col('F001V').cast(pl.String).alias('change_type_codes'),
        pl.col('F002V').cast(pl.String).alias('change_type_names'),
        pl.lit(source_file).alias('source_file'),
    )
    if events.select(pl.any_horizontal(pl.all().is_null()).any()).item():
        raise ValueError('Share-change event is missing a required field')
    return events.sort('symbol', 'event_date', 'ann_date', 'change_type_codes')


def publish_share_changes(*, request_summary: Path, output: Path) -> dict:
    """Build a new clean snapshot, retaining explicit successful empty requests."""
    summary = json.loads(request_summary.read_text(encoding='utf-8'))
    requests = summary['results']
    if summary.get('missing') or len(requests) != summary['pool_size']:
        raise ValueError('Share-change requests are incomplete')
    if len({r['symbol'] for r in requests}) != len(requests):
        raise ValueError('Duplicate share-change requests')
    start, end = (dt.date.fromisoformat(summary[k]) for k in ('start', 'end'))
    if start > end:
        raise ValueError('Invalid share-change request range')
    frames, coverage = [], []
    for request in requests:
        raw = pl.read_parquet(request['raw'])
        if raw.height != request['rows'] or raw.height != request['total']:
            raise ValueError('Share-change response count does not match request')
        events = normalize_share_changes(raw, symbol=request['symbol'], source_file=request['raw'])
        if events.filter(~pl.col('event_date').is_between(start, end)).height:
            raise ValueError('Share-change event falls outside requested dates')
        frames.append(events)
        coverage.append(dict(symbol=request['symbol'], start=start, end=end,
            returned_rows=raw.height, empty_response=raw.is_empty(), source_file=request['raw']))
    combined = pl.concat(frames).sort('symbol', 'event_date', 'ann_date', 'change_type_codes')
    output.mkdir(parents=True, exist_ok=False)
    combined.write_parquet(output / 'events.parquet')
    pl.DataFrame(coverage).write_parquet(output / 'request_coverage.parquet')
    return dict(output=str(output), symbols=len(requests), rows=combined.height,
        empty_symbols=sum(r['empty_response'] for r in coverage),
        announcement_after_event=combined.filter(pl.col('ann_date') > pl.col('event_date')).height)


def read_share_change_history(*, snapshot: Path, symbols: tuple[str, ...]) -> pl.DataFrame:
    """Return captured history; the consumer must apply announcement and event cutoffs."""
    return pl.scan_parquet(snapshot / 'events.parquet').filter(pl.col('symbol').is_in(symbols)).collect()


def read_share_change_coverage(*, snapshot: Path) -> pl.DataFrame:
    """Expose request ranges and empty responses without interpreting event absence."""
    return pl.read_parquet(snapshot / 'request_coverage.parquet')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-summary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish_share_changes(request_summary=args.request_summary, output=args.output)))


if __name__ == '__main__':
    main()
