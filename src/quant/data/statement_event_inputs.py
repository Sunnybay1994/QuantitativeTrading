"""Pinned inputs for first-statement reactions, independent of SUE availability."""
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.index_benchmarks import read_index_benchmark
from quant.data.statement_event_dates import validate_statement_dates


def read_statement_market(data_root: Path, config: Path, start: dt.date, end: dt.date) -> pl.DataFrame:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    version = settings.get('statement_event_index_version')
    if not isinstance(version, str) or not version or Path(version).name != version or version in ('.', '..'):
        raise ValueError('Set statement_event_index_version before computing statement reactions')
    summary = json.loads((data_root/'clean/index_benchmarks'/version/'summary.json').read_text(encoding='utf-8'))
    spec = [s for s in summary['series'] if s['index_code'] == 'H00985.CSI']
    if len(spec) != 1 or spec[0]['return_type'] != 'total_return':
        raise ValueError('Statement reactions require H00985.CSI total_return')
    if str(end) > summary['end']:
        raise ValueError('Statement reaction market input exceeds published coverage')
    low = max(start, dt.date.fromisoformat(summary['start']))
    if low > end:
        return pl.DataFrame(schema={'trade_date': pl.Date, 'index_level': pl.Float64})
    return read_index_benchmark(data_root=data_root, version=version, index_code='H00985.CSI',
        start=low, end=end, required_return_type='total_return').select('trade_date', 'index_level')


def read_statement_events(data_root: Path, config: Path, start: dt.date, end: dt.date) -> pl.DataFrame:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    definition = tomllib.loads(Path(settings['statement_event_definition']).read_text(encoding='utf-8'))
    snapshot = settings['financial_snapshot']
    if not snapshot or Path(snapshot).name != snapshot or snapshot in ('.', '..'):
        raise ValueError('Invalid statement financial snapshot')
    # Keep earlier periods for latest-disclosed-period validation, and exclude future announcements.
    history = pl.scan_parquet(data_root/'clean/tushare_financials'/snapshot/'income.parquet').filter(
        pl.col('available_date') <= end).select('symbol', 'ann_date', 'f_ann_date', 'available_date',
        'end_date', 'report_type', 'comp_type', 'n_income', 'n_income_attr_p').collect()
    legacy = pl.read_parquet(definition['legacy_quarantine'], columns=['symbol', 'announcement_date', 'status'])
    return validate_statement_dates(history, legacy).filter(pl.col('announcement_date').is_between(start, end))
