import polars as pl
import pytest

from quant.research.net_payout_feasibility import dividend_inventory


def test_dividend_inventory_keeps_receipt_duplicates_and_does_not_claim_pit(tmp_path):
    for name in ('receipt1', 'receipt2'):
        path = tmp_path/name
        path.mkdir()
        pl.DataFrame({'ts_code': ['a', 'a', 'b', 'c'], 'div_proc': ['实施', '实施', '预案', '实施'],
            'base_share': [100., 100., 100., 0.], 'cash_div_tax': [.5, .5, .5, .5],
            'imp_ann_date': ['20200101', None, '20200101', '20200101'],
            'pay_date': ['20200120'] * 4}).write_parquet(path/'data.parquet')
    result, paths = dividend_inventory(tmp_path)
    assert len(paths) == result['receipt_count'] == 2
    assert result['rows'] == 8
    assert result['cash_implemented_rows'] == 6
    assert result['positive_base_share_rows'] == 4
    assert result['base_and_dates_present_rows'] == 2
    assert 'not unique events' in result['qualification']
    assert 'unverified' in result['qualification']


def test_dividend_inventory_fails_on_missing_declared_directory(tmp_path):
    with pytest.raises(ValueError, match='No dividend receipts'):
        dividend_inventory(tmp_path/'missing')
