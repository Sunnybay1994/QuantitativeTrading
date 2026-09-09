import datetime as dt

import polars as pl

from quant.data import stock_execution_inputs as source


def test_stock_actions_keep_combined_cash_but_exclude_creditor_shares(monkeypatch, tmp_path):
    calls = []

    class Connector:
        def __init__(self, **kwargs):
            pass

        def query_raw(self, api, **params):
            calls.append(api)
            if api == "stk_limit":
                return pl.DataFrame({"ts_code": ["300760.SZ", "000793.SZ"],
                    "trade_date": [params["trade_date"]] * 2, "up_limit": [12.0, 3.0], "down_limit": [8.0, 2.0]})
            if api == "suspend_d":
                return pl.DataFrame()
            if api == "stock_basic":
                schema = {"ts_code": pl.String, "name": pl.String, "list_date": pl.String, "delist_date": pl.String}
                if params["list_status"] != "L":
                    return pl.DataFrame(schema=schema)
                return pl.DataFrame({"ts_code": ["300760.SZ", "000793.SZ"], "name": ["Mindray", "Huawen"],
                    "list_date": ["20180101", "19900101"], "delist_date": [None, None]}, schema=schema)
            if params["ts_code"] == "300760.SZ":
                return pl.DataFrame({"ts_code": ["300760.SZ"] * 2, "div_proc": ["实施"] * 2,
                    "imp_ann_date": ["20260520"] * 2, "record_date": ["20260527"] * 2,
                    "ex_date": ["20260528"] * 2, "pay_date": ["20260528"] * 2,
                    "div_listdate": [None] * 2, "cash_div_tax": [0.31, 1.25], "stk_div": [0.0] * 2})
            return pl.DataFrame({"ts_code": ["000793.SZ"], "div_proc": ["实施"], "imp_ann_date": ["20260612"],
                "record_date": ["20260618"], "ex_date": ["20260622"], "pay_date": [None],
                "div_listdate": ["20260622"], "cash_div_tax": [0.0], "stk_div": [1.2]})

    monkeypatch.setattr(source, "TushareConnector", Connector)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    kwargs = dict(data_root=tmp_path, symbols=["000793.SZ", "300760.SZ"],
        execution_dates=[dt.date(2026, 5, 28)], start=dt.date(2026, 1, 1), end=dt.date(2026, 9, 8),
        output=tmp_path / "clean/execution")
    _, _, dividends, instruments = source.prepare_stock_execution_inputs(**kwargs)
    assert dividends.filter(pl.col("symbol") == "300760.SZ").item(0, "div_cash") == 1.56
    assert dividends.filter(pl.col("symbol") == "000793.SZ").item(0, "share_ratio") == 0.0
    assert instruments.height == 2
    count = len(calls)
    source.prepare_stock_execution_inputs(**kwargs)
    assert len(calls) == count
