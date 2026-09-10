import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.publish_share_changes import (
    normalize_share_changes, publish_share_changes, read_share_change_coverage, read_share_change_history,
)


def sample() -> pl.DataFrame:
    return pl.DataFrame({'SECCODE': ['000021'], 'DECLAREDATE': ['2024-04-03'],
        'VARYDATE': ['2024-03-31'], 'F001V': ['015004,015025'], 'F002V': ['issuance,incentive']})


def test_dates_and_combined_reason_preserved():
    events = normalize_share_changes(sample(), symbol='000021.SZ', source_file='raw.parquet')
    assert events['ann_date'].item() == dt.date(2024, 4, 3)
    assert events['event_date'].item() == dt.date(2024, 3, 31)
    assert events['change_type_codes'].item() == '015004,015025'
    with pytest.raises(ValueError, match='another symbol'):
        normalize_share_changes(sample(), symbol='000022.SZ', source_file='raw.parquet')
    with pytest.raises(ValueError, match='missing'):
        normalize_share_changes(sample().with_columns(pl.lit(None).alias('DECLAREDATE')),
            symbol='000021.SZ', source_file='raw.parquet')


def test_empty_request_is_retained_without_creating_no_issuance_signal(tmp_path: Path):
    requests = []
    for symbol, raw in [('000021.SZ', sample()), ('000022.SZ', sample().head(0))]:
        path = tmp_path / f'{symbol}.parquet'
        raw.write_parquet(path)
        requests.append(dict(symbol=symbol, rows=raw.height, total=raw.height, raw=str(path)))
    summary = tmp_path / 'requests.json'
    summary.write_text(json.dumps(dict(start='2024-01-01', end='2024-12-31',
        pool_size=2, results=requests, missing=[])), encoding='utf-8')
    output = tmp_path / 'clean'
    result = publish_share_changes(request_summary=summary, output=output)
    assert result['rows'] == result['empty_symbols'] == result['announcement_after_event'] == 1
    coverage = read_share_change_coverage(snapshot=output).sort('symbol')
    assert coverage['empty_response'].to_list() == [False, True]
    assert 'no_issuance' not in coverage.columns
    assert read_share_change_history(snapshot=output, symbols=('000022.SZ',)).is_empty()
    with pytest.raises(FileExistsError):
        publish_share_changes(request_summary=summary, output=output)
