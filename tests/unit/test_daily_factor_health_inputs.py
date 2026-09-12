import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data import daily_factor_health_inputs as inputs

AS_OF = dt.date(2026, 9, 11)
PREVIOUS = dt.date(2026, 9, 10)


@pytest.fixture
def saved_day(tmp_path, monkeypatch):
    symbols = ["000001.SZ", "000002.SZ", "000003.SZ"]
    rows = [{"symbol": symbol, "trade_date": day, "open": 10.0, "high": 11.0,
             "low": 9.0, "close": 10.0, "volume": 1000.0, "amount": amount,
             "adj_factor": 1.0, "source": "fixture"}
            for day in (PREVIOUS, AS_OF) for symbol, amount in zip(symbols, (1000.0, 2000.0, 50000.0), strict=True)]
    bars = pl.from_dicts(rows)
    basic = pl.DataFrame({"symbol": symbols, "trade_date": [AS_OF] * 3,
                          "total_market_value": [1e9, None, 1e10]})
    tables = {"bar_1d": bars, "daily_basic": basic}
    monkeypatch.setattr(inputs, "available_sessions", lambda root, through: (PREVIOUS, AS_OF))
    monkeypatch.setattr(inputs, "read_stock_data", lambda **kwargs: tables[kwargs["table"]])
    config = tmp_path / "battery.toml"
    config.write_text('minimum_symbols=1\n[data]\nlimits_snapshot="old"\n[universe]\n'
        'minimum_listing_days=120\namount_window_sessions=2\namount_exclude_bottom_fraction=0.2\n', encoding="utf-8")
    reference = tmp_path / f"clean/stock_paper_inputs/date={AS_OF}"
    reference.mkdir(parents=True)
    pl.DataFrame({"symbol": symbols, "list_date": [dt.date(2020, 1, 1)] * 3,
        "delist_date": [None] * 3, "instrument_type": ["STOCK"] * 3},
        schema={"symbol": pl.String, "list_date": pl.Date, "delist_date": pl.Date,
                "instrument_type": pl.String}).write_parquet(reference / "instruments.parquet")
    pl.DataFrame({"symbol": [*symbols, symbols[1]], "name": ["甲", "乙", "ST丙", "ST未来"],
        "start_date": [dt.date(2020, 1, 1)] * 3 + [AS_OF + dt.timedelta(days=1)],
        "ann_date": [dt.date(2020, 1, 1)] * 3 + [AS_OF + dt.timedelta(days=1)]}).write_parquet(reference / "names.parquet")
    limits = pl.DataFrame({"symbol": symbols, "trade_date": [AS_OF] * 3,
                           "up_limit": [11.0] * 3, "down_limit": [9.0] * 3})
    limits.write_parquet(reference / "limits.parquet")
    old = tmp_path / "clean/factor_execution/old/year=2026/limits.parquet"
    old.parent.mkdir(parents=True)
    limits.with_columns(pl.lit(PREVIOUS).alias("trade_date")).write_parquet(old)
    industry = tmp_path / "clean/tushare_industry/current"
    industry.mkdir(parents=True)
    (industry / "summary.json").write_text(json.dumps({"as_of": str(AS_OF), "with_current": True}), encoding="utf-8")
    pl.DataFrame({"symbol": [symbols[0]], "valid_from": [dt.date(2020, 1, 1)],
        "valid_to": [AS_OF + dt.timedelta(days=1)], "industry_l1": ["SW2021:1"],
        "industry_l2": ["SW2021:11"], "industry_l3": ["SW2021:111"]}).write_parquet(industry / "intervals.parquet")
    return {"root": tmp_path, "config": config, "reference": reference, "industry": industry,
            "tables": tables, "limits": limits}


def read(saved):
    return inputs.read_daily_health_universe(data_root=saved["root"], refresh_config=Path("unused.toml"),
                                             battery_config=saved["config"], as_of=AS_OF)


def test_same_battery_rules_preserve_missing_controls_and_ignore_future_name(saved_day):
    result = read(saved_day)
    assert result.height == 3
    assert result["eligible"].to_list() == [False, True, False]
    assert result["liquidity_ok"].to_list()[0] is False
    assert result["not_risk_name"].to_list() == [True, True, False]
    eligible = result.filter(pl.col("eligible"))
    assert eligible["industry_l1"].to_list() == [None]
    assert eligible["total_market_value"].to_list() == [None]
    assert eligible["daily_basic_row_present"].to_list() == [True]
    assert "stock_paper_inputs" in result["limits_source"][0]
    assert result["industry_source_as_of"].to_list() == [AS_OF] * 3


def test_same_day_raw_limits_are_read_only_fallback(saved_day):
    (saved_day["reference"] / "limits.parquet").unlink()
    root = saved_day["root"] / f"raw/tushare/stk_limit/date={AS_OF}"
    root.mkdir(parents=True)
    (root / "saved.json").write_text(json.dumps({"parameters": {"trade_date": AS_OF.strftime("%Y%m%d")}}), encoding="utf-8")
    saved_day["limits"].rename({"symbol": "ts_code"}).with_columns(
        pl.col("trade_date").dt.strftime("%Y%m%d")).write_parquet(root / "saved.parquet")
    result = read(saved_day)
    assert "saved.parquet" in result["limits_source"][0]
    assert result["eligible"].sum() == 1


def test_partial_configured_limits_use_complete_same_day_paper_input(saved_day):
    old = saved_day["root"] / "clean/factor_execution/old/year=2026/limits.parquet"
    saved_day["limits"].head(1).write_parquet(old)
    result = read(saved_day)
    assert result.height == 3 and result["eligible"].sum() == 1
    assert "stock_paper_inputs" in result["limits_source"][0]


@pytest.mark.parametrize("problem", ["limits_absent", "limit_key_gap", "industry_stale", "industry_future", "warmup_gap", "wrong_basic_date"])
def test_missing_inputs_never_fall_back_to_wrong_session(saved_day, problem):
    if problem == "limits_absent":
        (saved_day["reference"] / "limits.parquet").unlink()
    elif problem == "limit_key_gap":
        saved_day["limits"].head(2).write_parquet(saved_day["reference"] / "limits.parquet")
    elif problem in ("industry_stale", "industry_future"):
        date = PREVIOUS if problem == "industry_stale" else AS_OF + dt.timedelta(days=1)
        (saved_day["industry"] / "summary.json").write_text(json.dumps({"as_of": str(date), "with_current": True}), encoding="utf-8")
    elif problem == "warmup_gap":
        saved_day["tables"]["bar_1d"] = saved_day["tables"]["bar_1d"].filter(pl.col("trade_date") == AS_OF)
    else:
        saved_day["tables"]["daily_basic"] = saved_day["tables"]["daily_basic"].with_columns(pl.lit(PREVIOUS).alias("trade_date"))
    with pytest.raises(ValueError):
        read(saved_day)


def test_daily_factor_statuses_and_eligible_left_join(tmp_path):
    symbols = [f"00000{i}.SZ" for i in range(1, 6)]
    universe = pl.DataFrame({"symbol": symbols, "trade_date": [AS_OF] * 5,
        "eligible": [True, True, True, True, False], "industry_l1": [None] * 5,
        "total_market_value": [None] * 5})
    folder = tmp_path / "factors/alpha/year=2026"
    folder.mkdir(parents=True)
    pl.DataFrame({"trade_date": [AS_OF] * 3 + [PREVIOUS], "ts_code": symbols[:4],
                  "value": [0.0, None, float("inf"), 1.0]}).write_parquet(folder / "data.parquet")
    result = inputs.read_daily_health_factor(data_root=tmp_path, factor_id="alpha", universe=universe, as_of=AS_OF)
    assert result.height == 4
    assert result["raw_value_status"].to_list() == ["observed", "null_value", "nonfinite_value", "missing_row"]
    missing = inputs.read_daily_health_factor(data_root=tmp_path, factor_id="absent", universe=universe, as_of=AS_OF)
    assert missing["raw_value_status"].to_list() == ["missing_partition"] * 4
    with pytest.raises(ValueError, match="wrong-date"):
        inputs.read_daily_health_factor(data_root=tmp_path, factor_id="alpha", universe=universe, as_of=PREVIOUS)
    with pytest.raises(ValueError, match="identifier"):
        inputs.read_daily_health_factor(data_root=tmp_path, factor_id="../alpha", universe=universe, as_of=AS_OF)


def test_daily_factor_duplicate_rows_fail(tmp_path):
    universe = pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": [AS_OF], "eligible": [True],
                             "industry_l1": ["SW2021:1"], "total_market_value": [1e9]})
    folder = tmp_path / "factors/alpha/year=2026"
    folder.mkdir(parents=True)
    pl.DataFrame({"trade_date": [AS_OF] * 2, "ts_code": ["000001.SZ"] * 2, "value": [1.0, 2.0]}).write_parquet(folder / "data.parquet")
    with pytest.raises(ValueError, match="Duplicate"):
        inputs.read_daily_health_factor(data_root=tmp_path, factor_id="alpha", universe=universe, as_of=AS_OF)
