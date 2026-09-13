import datetime as dt

import polars as pl

from quant.data.financial_repository import TushareFinancialHistoryQuery, read_tushare_financial_history


def test_inventory_read_preserves_revisions_and_missing_values(tmp_path):
    folder = tmp_path/'clean/tushare_financials/sample'
    folder.mkdir(parents=True)
    first, revised = dt.date(2020, 4, 1), dt.date(2020, 8, 1)
    frame = pl.DataFrame({'symbol': ['000001.SZ']*2, 'end_date': [dt.date(2019, 12, 31)]*2,
        'ann_date': [first, revised], 'f_ann_date': [first, revised],
        'available_date': [first, revised], 'report_type': ['1']*2, 'comp_type': ['1']*2,
        'update_flag': ['0', '1'], 'total_assets': [100., 110.],
        'total_hldr_eqy_exc_min_int': [50., 55.], 'inventories': [None, 20.], 'source': ['tushare']*2})
    frame.write_parquet(folder/'balancesheet.parquet')
    actual = read_tushare_financial_history(data_root=tmp_path,
        query=TushareFinancialHistoryQuery('sample', 'balancesheet', dt.date(2019, 1, 1),
            dt.date(2020, 1, 1), ('000001.SZ',), extra_fields=('inventories',)))
    assert actual['inventories'].to_list() == [None, 20.]
    assert actual['available_date'].to_list() == [first, revised]
