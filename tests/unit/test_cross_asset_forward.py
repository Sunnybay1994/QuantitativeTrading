import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.execution.cross_asset_forward import account_config_text, assess_forward, run
from quant.execution.paper_ledger import next_targets

CONFIG = Path("configs/research/b20_three_asset_forward_20260909.toml")
SYMBOLS = ["510300.SH", "511010.SH", "518880.SH"]


def fixture_inputs():
    dates = [dt.date(2026, 6, 1) + dt.timedelta(days=i) for i in range(152)]
    dates = [d for d in dates if d.weekday() < 5]
    cal = pl.DataFrame({"date": dates, "market": ["SH"] * len(dates), "is_open": [True] * len(dates),
                       "is_connect_open": [False] * len(dates), "is_half_day": [False] * len(dates)})
    rows = []
    for index, symbol in enumerate(SYMBOLS):
        price = 10. * (index + 1)
        for n, date in enumerate(dates):
            price *= 1 + (.001 * (index + 1) if n % 2 else -.001 * (index + 1))
            if date <= dt.date(2026, 9, 11):
                rows.append({"symbol": symbol, "trade_date": date, "open": price, "close": price,
                             "high": price + 1, "low": price - 1, "volume": 10000000.,
                             "amount": price * 10000000., "adj_factor": 1., "source": "fixture"})
    bars = pl.DataFrame(rows)
    prices = bars.select("symbol", "trade_date", pl.col("close").alias("adjusted_close"))
    instruments = pl.DataFrame({"symbol": SYMBOLS, "market": ["SH"] * 3, "name": SYMBOLS,
        "instrument_type": ["ETF"] * 3, "currency": ["CNY"] * 3, "list_date": [dt.date(2010, 1, 1)] * 3,
        "delist_date": [None] * 3, "board_lot": [100] * 3, "status": ["LISTED"] * 3}).with_columns(
            pl.col("delist_date").cast(pl.Date))
    dividends = pl.DataFrame(schema={"symbol": pl.String, "ann_date": pl.Date, "record_date": pl.Date,
                                    "ex_date": pl.Date, "pay_date": pl.Date, "div_cash": pl.Float64})
    return bars, prices, cal, instruments, dividends


def test_initial_signal_uses_completed_month_and_costs_are_scaled():
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    account = tomllib.loads(account_config_text(cfg, "strategy", 2.))
    assert account["costs"]["etf"]["slippage_per_share"] == .002
    _, prices, cal, _, _ = fixture_inputs()
    date, following = dt.date(2026, 9, 9), dt.date(2026, 9, 10)
    before = next_targets(date, following, following, SYMBOLS, account, prices, cal)
    shocked = prices.with_columns(pl.when(pl.col("trade_date") > dt.date(2026, 8, 31))
        .then(pl.col("adjusted_close") * 100).otherwise(pl.col("adjusted_close")).alias("adjusted_close"))
    assert before == next_targets(date, following, following, SYMBOLS, account, shocked, cal)
    assert sum(r["weight"] for r in before) == pytest.approx(1)
    assert before[0]["weight"] > before[1]["weight"] > before[2]["weight"]


def test_forward_accounts_resume_like_contiguous_run(monkeypatch, tmp_path):
    from quant.execution import paper_ledger
    from quant.research import monthly_etf

    inputs = fixture_inputs()
    monkeypatch.setattr(monthly_etf, "read_inputs", lambda *a, **k: inputs)
    bars = inputs[0]
    limits = bars.select("symbol", "trade_date", (pl.col("close") + 2).alias("up_limit"),
                        (pl.col("close") - 2).alias("down_limit"))
    monkeypatch.setattr(paper_ledger, "read_limits", lambda root: limits)
    first = run(config_path=CONFIG, data_root=tmp_path, output=tmp_path / "split", end=dt.date(2026, 9, 9), refresh_data=False)
    assert first["conclusion"] is None
    assert len(first["accounts"]) == 6
    assert all(a["sessions"] == 0 for a in first["accounts"])
    orders = pl.read_csv(tmp_path / "split/cost_1/strategy/2026-09-09/orders.csv")
    assert orders.height == 3 and set(orders["execution_date"]) == {"2026-09-10"}
    run(config_path=CONFIG, data_root=tmp_path, output=tmp_path / "split", end=dt.date(2026, 9, 10), refresh_data=False)
    split = run(config_path=CONFIG, data_root=tmp_path, output=tmp_path / "split", end=dt.date(2026, 9, 11), refresh_data=False)
    whole = run(config_path=CONFIG, data_root=tmp_path, output=tmp_path / "whole", end=dt.date(2026, 9, 11), refresh_data=False)
    assert split["results"] == whole["results"]
    assert all(r["sessions"] == 2 for r in split["results"])
    for cost in (.5, 1., 2.):
        for kind in ("strategy", "s0"):
            rel = f"cost_{cost:g}/{kind}/2026-09-11/state.json"
            assert json.loads((tmp_path / "split" / rel).read_text()) == json.loads((tmp_path / "whole" / rel).read_text())


def test_no_admission_before_endpoint_or_with_insufficient_data():
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    rows = [{"fold": 1, "comparison": kind, "cost_multiplier": cost, "sessions": 50,
             "test_start": "2026-09-10", "total_return": .04, "cagr": .1,
             "max_drawdown": -.01 if kind == "strategy" else -.05,
             "annualized_one_way_turnover": 2.5} for cost in (.5, 1., 2.) for kind in ("strategy", "s0")]
    assert assess_forward(rows, cfg, dt.date(2026, 11, 27))["conclusion"] is None
    assert assess_forward(rows, cfg, dt.date(2026, 11, 30))["conclusion"] == "PAPER_CANDIDATE"
    assert assess_forward(rows, cfg, dt.date(2026, 11, 30), True)["conclusion"] == "REJECTED"
    rows[0]["sessions"] = 2
    assert assess_forward(rows, cfg, dt.date(2026, 11, 30))["conclusion"] == "REJECTED"
