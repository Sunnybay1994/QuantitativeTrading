import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.inspect_qmj_fields import annual_cfoa_input_coverage, inspect_fields


def test_coverage_preserves_missing_fields_and_excludes_unknown_announcements(tmp_path: Path) -> None:
    folder = tmp_path / 'clean/tushare_financials/example'
    folder.mkdir(parents=True)
    raw_path = tmp_path / 'raw.parquet'
    pl.DataFrame({'n_income': [1.0, None]}).write_parquet(raw_path)
    for table, fields in {
        'income': ['n_income'],
        'cashflow': ['depr_fa_coga_dpba', 'c_pay_acq_const_fiolta'],
        'balancesheet': ['total_assets', 'total_cur_assets', 'total_cur_liab', 'money_cap',
                        'st_borr', 'taxes_payable'],
    }.items():
        rows = []
        for symbol in ('000001.SZ', '000002.SZ'):
            for year in (2021, 2022):
                rows.append({'symbol': symbol, 'end_date': dt.date(year, 12, 31),
                             'ann_date': dt.date(year + 1, 3, 1),
                             'f_ann_date': dt.date(year + 1, 3, 1),
                             'available_date': dt.date(year + 1, 3, 1),
                             'report_type': '1', 'comp_type': '1', 'update_flag': '0',
                             'source_file': str(raw_path), **dict.fromkeys(fields, 1.0)})
        if table == 'balancesheet':
            rows[2]['st_borr'] = None
        pl.DataFrame(rows).write_parquet(folder / f'{table}.parquet')
    symbols = ['000001.SZ', '000002.SZ']
    result = inspect_fields(data_root=tmp_path, snapshot='example', symbols=symbols,
                            as_of=dt.date(2023, 3, 1))
    assert result['tables']['income']['rows'] == 2
    absent = next(x for x in result['tables']['income']['fields'] if x['field'] == 'ebitda')
    assert absent['column_present'] is False and absent['finite_rows'] == 0
    coverage = annual_cfoa_input_coverage(data_root=tmp_path, snapshot='example', symbols=symbols,
                                        signals=[dt.date(2023, 3, 1), dt.date(2023, 3, 2)])
    assert coverage[0]['complete_annual_cfoa_symbols'] == 0
    assert coverage[1]['complete_annual_cfoa_symbols'] == 1
