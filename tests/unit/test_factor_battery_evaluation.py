import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data import factor_battery_inputs as inputs
from quant.research.factor_battery_evaluation import evaluate_factor_year, summarize_factor_statistics


def test_evaluation_keeps_direction_empty_dates_and_cross_year_persistence():
    settings = tomllib.loads(Path("configs/factors/battery.toml").read_text())
    settings.update(minimum_symbols=20,groups=2)
    sessions = tuple(dt.date(2020,12,1)+dt.timedelta(days=i) for i in range(62))
    month_ends = (dt.date(2020,12,31),dt.date(2021,1,31))
    universe = pl.DataFrame([{"symbol":f"s{i:02}","trade_date":d,"eligible":d!=sessions[5],
        "total_market_value":1e9,"industry_l1":"one"} for d in sessions for i in range(20)])
    values = universe.select("symbol","trade_date").with_columns(
        pl.col("symbol").str.slice(1).cast(pl.Float64).alias("value"))
    labels = values.select("symbol","trade_date", *[(-pl.col("value")/1000).alias(f"label_{h}")
        for h in settings["decay_sessions"]])
    monthly = labels.filter(pl.col("trade_date").is_in(month_ends)).select("symbol","trade_date",
        pl.col("label_20").alias("label_rebalance"))
    parts = [evaluate_factor_year(universe=universe.filter(pl.col("trade_date").dt.year()==year),
        values=values,daily_labels=labels,monthly_labels=monthly.filter(pl.col("trade_date").dt.year()==year),
        direction=-1,settings=settings) for year in (2020,2021)]
    daily = pl.concat([part.daily_ic for part in parts])
    assert daily.height == len(sessions)*2*5
    assert daily.filter(pl.col("trade_date")==sessions[5])["rank_ic"].null_count() == 10
    assert daily["rank_ic"].drop_nulls().min() == pytest.approx(1)
    summaries, changes = summarize_factor_statistics(parts,sessions=sessions,settings=settings)
    assert [row["months"] for row in summaries] == [2,2]
    assert changes.height == 2 and changes["previous_signal"].unique().to_list() == [month_ends[0]]
    assert changes["rank_autocorrelation"].to_list() == pytest.approx([1,1])
    assert changes["top_target_turnover"].to_list() == pytest.approx([0,0])
    empty = evaluate_factor_year(universe=universe,
        values=values.with_columns(pl.lit(None,dtype=pl.Float64).alias("value")),
        daily_labels=labels,monthly_labels=monthly,direction=1,settings=settings)
    rejected, _ = summarize_factor_statistics([empty],sessions=sessions,settings=settings)
    assert all(row["months"]==0 and row["first_valid_month"] is None for row in rejected)


def test_reader_masks_newer_forward_returns_at_as_of(tmp_path, monkeypatch):
    dates = tuple(dt.date(2020,1,1)+dt.timedelta(days=i) for i in range(80))
    keys = pl.DataFrame({"ts_code":["600000.SH"]*80,"trade_date":dates})
    for name, frame in (("fixture",keys.with_columns(pl.lit(1.).alias("value"))),
                        ("forward_returns",keys.with_columns(*[pl.lit(.1).alias(f"label_{h}") for h in (1,5,10,20,60)]))):
        folder = tmp_path/f"factors/{name}/year=2020"
        folder.mkdir(parents=True)
        frame.write_parquet(folder/"data.parquet")
    monkeypatch.setattr(inputs,"available_sessions",lambda root,through:tuple(d for d in dates if d<=through))
    values, labels = inputs.read_battery_factor_year(tmp_path,factor="fixture",year=2020,known_through=dates[61])
    assert values.height == labels.height == 62
    assert labels["label_60"].count() == 1 and labels["label_20"].count() == 41
    assert labels["label_60"][0] == .1 and labels["label_60"][1] is None
