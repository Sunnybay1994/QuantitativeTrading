import datetime as dt
import json

import polars as pl
import pytest

from quant.data.factor_control_receipts import pending_control_start, write_control_receipt


COLUMNS = ('mean', 'compounded')


def frame(day, value):
    return pl.DataFrame({'symbol': ['A'], 'trade_date': [day],
        'mean': [value], 'compounded': [value]}, schema_overrides={'mean': pl.Float64, 'compounded': pl.Float64})


def test_empty_partial_month_is_complete_but_later_month_end_still_computes(tmp_path):
    path = tmp_path/'year=2021.parquet'
    start, mid, end = dt.date(2021,1,1), dt.date(2021,1,15), dt.date(2021,1,29)
    write_control_receipt(path, frame(end, 1.).head(0), start=start, end=mid, columns=COLUMNS)
    assert pending_control_start(path, start=start, end=mid, columns=COLUMNS) is None
    assert pending_control_start(path, start=start, end=end, columns=COLUMNS) == dt.date(2021,1,16)
    write_control_receipt(path, frame(end, None), start=dt.date(2021,1,16), end=end, columns=COLUMNS)
    assert pending_control_start(path, start=start, end=end, columns=COLUMNS) is None
    assert pl.read_parquet(path)['mean'].null_count() == 1


def test_disjoint_ranges_never_claim_the_gap_was_computed(tmp_path):
    path = tmp_path/'year=2021.parquet'
    jan, mar = dt.date(2021,1,29), dt.date(2021,3,31)
    write_control_receipt(path, frame(jan, 1.), start=dt.date(2021,1,1), end=jan, columns=COLUMNS)
    assert pending_control_start(path, start=dt.date(2021,3,1), end=mar, columns=COLUMNS) == dt.date(2021,3,1)
    write_control_receipt(path, frame(mar, 2.), start=dt.date(2021,3,1), end=mar, columns=COLUMNS)
    assert pending_control_start(path, start=dt.date(2021,1,1), end=mar, columns=COLUMNS) == dt.date(2021,1,1)
    assert pl.read_parquet(path).height == 2


@pytest.mark.parametrize('damage', ['missing', 'unparseable', 'different_schema', 'different_content'])
def test_incomplete_or_changed_control_receipt_rebuilds_requested_interval(tmp_path, damage):
    path = tmp_path/'year=2021.parquet'
    start, end = dt.date(2021,1,1), dt.date(2021,1,29)
    write_control_receipt(path, frame(end, 1.), start=start, end=end, columns=COLUMNS)
    record = path.with_suffix('.coverage.json')
    if damage == 'missing':
        record.unlink()
    elif damage == 'unparseable':
        record.write_text('{')
    elif damage == 'different_schema':
        saved = json.loads(record.read_text()); saved['columns'] = ['other']
        record.write_text(json.dumps(saved))
    else:
        frame(end, 99.).write_parquet(path)
    assert pending_control_start(path, start=start, end=end, columns=COLUMNS) == start
    write_control_receipt(path, frame(end, 1.), start=start, end=end, columns=COLUMNS)
    assert pending_control_start(path, start=start, end=end, columns=COLUMNS) is None
    assert pl.read_parquet(path)['mean'].item() == 1.


def test_invalid_output_does_not_replace_completed_controls(tmp_path):
    path = tmp_path/'year=2021.parquet'
    start, end = dt.date(2021,1,1), dt.date(2021,1,29)
    write_control_receipt(path, frame(end, 1.), start=start, end=end, columns=COLUMNS)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Duplicate'):
        write_control_receipt(path, pl.concat([frame(end, 2.)]*2), start=start, end=end, columns=COLUMNS)
    with pytest.raises(ValueError, match='outside'):
        write_control_receipt(path, frame(dt.date(2021,2,1), 2.), start=start, end=end, columns=COLUMNS)
    assert path.read_bytes() == before
