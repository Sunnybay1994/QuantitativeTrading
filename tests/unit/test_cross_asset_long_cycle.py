import datetime as dt
import tomllib
from pathlib import Path

import pandas as pd
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.research.cross_asset_long_cycle import build_targets


def fixture():
    spec = tomllib.loads(Path("configs/research/cross_asset_long_cycle_v1.toml").read_text())
    spec["end"] = dt.date(2014, 9, 1)
    original = tomllib.loads(Path(spec["source_config"]).read_text())
    inverse = tomllib.loads(Path(spec["inverse_volatility_config"]).read_text())
    dates = [t.date() for t in pd.bdate_range("2013-07-01", "2014-10-01")]
    calendar = pl.DataFrame(dict(date=dates, market=["SH"]*len(dates), is_open=[True]*len(dates)))
    prices = pl.DataFrame([dict(trade_date=d, symbol=s, adjusted_close=10*(1+r)**i)
        for i, d in enumerate(dates) for s, r in zip(original["universe"]["symbols"], [.0005, .0001, -.0003])])
    return dict(prices=prices, calendar=calendar), spec, original, inverse


def test_original_rule_and_causal_common_start():
    frames, spec, original, inverse = fixture()
    targets = build_targets(frames, spec, original, inverse)
    first = targets["dual_momentum"].filter(pl.col("execution_date") == spec["start"])
    assert first.filter(pl.col("weight") > 0)["symbol"].to_list() == ["510300.SH"]
    assert first["as_of"].unique().to_list() == [dt.date(2014, 7, 31)]
    assert (first["as_of"] < first["execution_date"]).all()
    changed = dict(frames)
    changed["prices"] = frames["prices"].with_columns(pl.when(pl.col("trade_date") >= dt.date(2014, 8, 1))
        .then(pl.col("adjusted_close") * 2).otherwise(pl.col("adjusted_close")).alias("adjusted_close"))
    other = build_targets(changed, spec, original, inverse)
    for name in targets:
        assert_frame_equal(targets[name].filter(pl.col("execution_date") == spec["start"]),
                           other[name].filter(pl.col("execution_date") == spec["start"]))


def test_no_insufficient_month_history_or_initial_cash_prefix():
    frames, spec, original, inverse = fixture()
    spec["start"] = dt.date(2014, 7, 1)
    with pytest.raises(ValueError, match="13 completed"):
        build_targets(frames, spec, original, inverse)


def test_original_absolute_momentum_filter_keeps_cash_when_all_negative():
    frames, spec, original, inverse = fixture()
    frames["prices"] = frames["prices"].with_columns((1000/pl.col("adjusted_close")).alias("adjusted_close"))
    # Make the originally negative gold series negative as well.
    frames["prices"] = frames["prices"].with_columns(pl.when(pl.col("symbol") == "518880.SH")
        .then(10000/pl.col("adjusted_close")).otherwise(pl.col("adjusted_close")).alias("adjusted_close"))
    targets = build_targets(frames, spec, original, inverse)["dual_momentum"]
    assert targets["weight"].sum() == 0
