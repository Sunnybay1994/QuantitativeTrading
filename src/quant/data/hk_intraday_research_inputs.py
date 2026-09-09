"""Existing HK minute observations and chart corporate actions for design research."""

import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.intraday_bars import TZ
from quant.data.intraday_research_inputs import read_etf_minutes


def read_hk_design_inputs(data_root: Path, pool_config: Path) -> tuple[pl.DataFrame, tuple[dt.date, ...], dict[str, list[dict[str, Any]]]]:
    members = tomllib.loads(pool_config.read_text(encoding="utf-8"))["members"]
    frames, actions = [], {}
    for member in members:
        symbol = member["symbol"]
        frames.append(read_etf_minutes(data_root, symbol, "60m", "yahoo"))
        coverage = data_root / "clean/bar_intraday/freq=60m/source=yahoo" / f"symbol={symbol}" / "coverage.json"
        raw_path = Path(json.loads(coverage.read_text(encoding="utf-8"))["raw"])
        chart = json.loads(raw_path.read_text(encoding="utf-8"))["chart"]["result"][0]
        if chart["meta"]["symbol"] != member["yahoo_symbol"]:
            raise ValueError("Unexpected corporate-action source symbol")
        events = chart.get("events", {})
        if events.get("splits"):
            raise ValueError(f"Split-adjusted intraday dividend units require verification: {symbol}")
        values = []
        for event in events.get("dividends", {}).values():
            values.append({"date": dt.datetime.fromtimestamp(event["date"], TZ).date(),
                           "cash": float(event["amount"]), "split": 1.})
        for event in events.get("splits", {}).values():
            values.append({"date": dt.datetime.fromtimestamp(event["date"], TZ).date(),
                           "cash": 0., "split": float(event["numerator"]) / float(event["denominator"])})
        actions[symbol] = sorted(values, key=lambda r: (r["date"], r["cash"] == 0))
    calendar = pl.read_parquet(data_root / "clean/trade_calendar/market=HK/data.parquet")
    half_days = tomllib.loads(Path("configs/calendars/hk_intraday_half_days.toml").read_text())["dates"]
    sessions = tuple(calendar.filter(pl.col("is_open") & ~pl.col("is_half_day")
        & ~pl.col("date").is_in(half_days))["date"].unique().sort().to_list())
    return pl.concat(frames, how="diagonal_relaxed"), sessions, actions
