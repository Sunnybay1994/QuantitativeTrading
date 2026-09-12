import polars as pl
import pytest

from quant.data.neutralization_inputs import neutralization_control_status


def test_control_status_distinguishes_exposure_holes_without_dropping_rows():
    frame = pl.DataFrame({'symbol': list('abcdefg'),
        'total_market_value': [1., None, 0., -1., float('nan'), float('inf'), 10.],
        'industry_l1': ['bank', 'bank', 'bank', 'bank', 'bank', 'bank', '']})
    result = neutralization_control_status(frame)
    assert result['controls_valid'].to_list() == [True, False, False, False, False, False, False]
    assert result['size_missing'].sum() == 5
    assert result['industry_missing'].sum() == 1
    assert result['symbol'].to_list() == list('abcdefg')
    assert 'controls_valid' not in frame.columns


def test_missing_industry_and_required_columns():
    result = neutralization_control_status(pl.DataFrame({
        'total_market_value': [2.], 'industry_l1': [None]}))
    assert result['industry_missing'].item()
    assert not result['controls_valid'].item()
    with pytest.raises(ValueError, match='needs'):
        neutralization_control_status(pl.DataFrame({'total_market_value': [2.]}))
