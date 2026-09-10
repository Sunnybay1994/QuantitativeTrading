import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data import factor_battery_inputs as inputs
from tests.unit.test_factor_expressions import sample_bars


def test_monthly_labels_cross_year_boundaries_without_future_universe_changes(tmp_path, monkeypatch):
    # Shift the existing bar fixture so December's return ends at February open.
    bars = sample_bars().with_columns((pl.col("trade_date")-pl.duration(days=31)).alias("trade_date"))
    sessions = tuple(bars["trade_date"].unique().sort().to_list())
    symbols = bars["symbol"].unique().sort().to_list()
    instruments = pl.DataFrame({"symbol": symbols, "list_date": [dt.date(2010,1,1)]*4,
        "delist_date": [None]*4, "instrument_type": ["STOCK"]*4}, schema_overrides={"delist_date":pl.Date})
    for market, frame in (("SH", instruments), ("SZ", instruments.clear())):
        path = tmp_path / f"clean/instrument/market={market}"
        path.mkdir(parents=True)
        frame.write_parquet(path/"data.parquet")
    names = pl.DataFrame({"symbol": symbols, "name": ["normal"]*4,
        "start_date": [dt.date(2010,1,1)]*4, "ann_date": [dt.date(2010,1,1)]*4})
    path = tmp_path/"clean/stock_name_history"
    path.mkdir(parents=True)
    names.write_parquet(path/"data.parquet")
    path = tmp_path/"clean/factor_execution/fixture/year=2019"
    path.mkdir(parents=True)
    bars.filter(pl.col("trade_date").dt.year()==2019).select("symbol","trade_date").with_columns(
        (pl.col("symbol").str.slice(0,1).cast(pl.Float64)*100).alias("up_limit"),
        pl.lit(1.).alias("down_limit")).write_parquet(path/"limits.parquet")
    monkeypatch.setattr(inputs, "available_sessions", lambda root, through: tuple(d for d in sessions if d<=through))

    def read(root, config, start, end, calendar):
        selected = bars.filter(pl.col("trade_date").is_between(start,end))
        return selected.with_columns(pl.lit(1e9).alias("total_market_value")), selected

    monkeypatch.setattr(inputs, "read_factor_inputs", read)
    monkeypatch.setattr(inputs, "read_factor_industry", lambda root, panel: panel.with_columns(
        pl.lit("fixture").alias("industry_l1")))
    kwargs = dict(data_root=tmp_path, refresh_config=tmp_path/"unused", limits_snapshot="fixture",
        start=dt.date(2019,12,1), end=dt.date(2019,12,31), known_through=sessions[-1])
    universe, labels = inputs.read_battery_year(**kwargs)
    assert labels["execution_date_rebalance"].unique().to_list() == [dt.date(2020,1,1)]
    assert labels["exit_date_rebalance"].unique().to_list() == [dt.date(2020,2,1)]
    assert labels["trade_date"].unique().to_list() == [dt.date(2019,12,31)]
    for row in labels.iter_rows(named=True):
        stock = bars.filter(pl.col("symbol")==row["symbol"])
        opens = {r["trade_date"]:r["open"]*r["adj_factor"] for r in stock.iter_rows(named=True)}
        assert row["label_rebalance"] == pytest.approx(opens[dt.date(2020,2,1)]/opens[dt.date(2020,1,1)]-1)
    # A future name change cannot affect signal-time eligibility or controls.
    change = names.head(1).with_columns(pl.lit("*ST later").alias("name"),
        pl.lit(dt.date(2020,1,5)).alias("start_date"),pl.lit(dt.date(2020,1,5)).alias("ann_date"))
    pl.concat([names, change]).write_parquet(tmp_path/"clean/stock_name_history/data.parquet")
    after, _ = inputs.read_battery_year(**kwargs)
    assert_frame_equal(universe, after)
    # Incomplete next-month prices leave the December outcome unavailable.
    _, truncated = inputs.read_battery_year(**{**kwargs, "known_through":dt.date(2020,1,15)})
    assert truncated["label_rebalance"].null_count() == 4
