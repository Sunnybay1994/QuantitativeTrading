import datetime as dt

import polars as pl
import pytest

from quant.data import stock_execution_inputs as source


def test_restore_old_codes_keeps_original_listing_age_and_existing_rows():
    frame = pl.DataFrame({"symbol": ["001872.SZ", "001914.SZ", "302132.SZ"],
        "name": ["port", "property", "aircraft"],
        "list_date": [dt.date(1993, 5, 5), dt.date(1994, 9, 28), dt.date(2010, 8, 27)],
        "delist_date": [None]*3, "status": ["LISTED"]*3},
        schema_overrides={"delist_date": pl.Date})
    result = source.restore_historical_instruments(frame)
    assert result.height == 6
    old = result.filter(pl.col("symbol") == "000022.SZ").row(0, named=True)
    assert old["list_date"] == dt.date(1993, 5, 5)
    assert old["delist_date"] == dt.date(2018, 12, 26)
    assert source.restore_historical_instruments(result).equals(result)
    assert result.head(3).equals(frame)


@pytest.mark.parametrize("creditor_ann,invalid", [("20260612", False), ("20260623", True)])
def test_stock_actions_keep_combined_cash_but_exclude_creditor_shares(monkeypatch, tmp_path, creditor_ann, invalid):
    calls = []

    class Connector:
        def __init__(self, **kwargs):
            pass

        def query_raw(self, api, **params):
            calls.append(api)
            if api == "stk_limit":
                return pl.DataFrame({"ts_code": ["300760.SZ", "000793.SZ", "003001.SZ"],
                    "trade_date": [params["trade_date"]] * 3, "up_limit": [12.0, 3.0, 50.0], "down_limit": [8.0, 2.0, 30.0]})
            if api == "suspend_d":
                return pl.DataFrame()
            if api == "stock_basic":
                schema = {"ts_code": pl.String, "name": pl.String, "list_date": pl.String, "delist_date": pl.String}
                if params["list_status"] != "L":
                    return pl.DataFrame(schema=schema)
                return pl.DataFrame({"ts_code": ["300760.SZ", "000793.SZ", "003001.SZ"], "name": ["Mindray", "Huawen", "Zhongyan"],
                    "list_date": ["20180101", "19900101", "20200101"], "delist_date": [None, None, None]}, schema=schema)
            if params["ts_code"] == "300760.SZ":
                return pl.DataFrame({"ts_code": ["300760.SZ"] * 2, "div_proc": ["实施"] * 2,
                    "imp_ann_date": ["20260520"] * 2, "record_date": ["20260527"] * 2,
                    "ex_date": ["20260528"] * 2, "pay_date": ["20260528"] * 2,
                    "div_listdate": [None] * 2, "cash_div_tax": [0.31, 1.25], "stk_div": [0.0] * 2})
            if params["ts_code"] == "003001.SZ":
                return pl.DataFrame({"ts_code": ["003001.SZ"] * 2, "div_proc": ["实施"] * 2,
                    "imp_ann_date": ["20250630", "20250705"], "record_date": ["20250704"] * 2,
                    "ex_date": ["20250707"] * 2, "pay_date": ["20250707"] * 2,
                    "div_listdate": ["20250707"] * 2, "cash_div_tax": [.2814904] * 2,
                    "stk_div": [.3992772] * 2})
            return pl.DataFrame({"ts_code": ["000793.SZ"], "div_proc": ["实施"], "imp_ann_date": [creditor_ann],
                "record_date": ["20260618"], "ex_date": ["20260622"], "pay_date": [None],
                "div_listdate": ["20260622"], "cash_div_tax": [0.0], "stk_div": [1.2]})

    monkeypatch.setattr(source, "TushareConnector", Connector)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    kwargs = dict(data_root=tmp_path, symbols=["000793.SZ", "003001.SZ", "300760.SZ"],
        execution_dates=[dt.date(2026, 5, 28)], start=dt.date(2025, 1, 1), end=dt.date(2026, 9, 8),
        output=tmp_path / "clean/execution")
    if invalid:
        with pytest.raises(ValueError, match="Incomplete stock dividend dates"):
            source.prepare_stock_execution_inputs(**kwargs)
        return
    _, _, dividends, instruments = source.prepare_stock_execution_inputs(**kwargs)
    assert dividends.filter(pl.col("symbol") == "300760.SZ").item(0, "div_cash") == 1.56
    assert dividends.filter(pl.col("symbol") == "000793.SZ").item(0, "share_ratio") == 0.0
    assert instruments.height == 3
    revised = dividends.filter(pl.col("symbol") == "003001.SZ")
    assert revised.height == 1
    assert revised.item(0, "ann_date") == dt.date(2025, 7, 5)
    count = len(calls)
    source.prepare_stock_execution_inputs(**kwargs)
    assert len(calls) == count
