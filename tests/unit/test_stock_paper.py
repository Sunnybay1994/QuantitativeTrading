import copy
import datetime as dt
import json
import sys
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.backtest.costs import AShareCostModel
from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA, StockPaperInputs, map_day_dividends
from quant.execution import stock_paper
from quant.strategies.stock_paper import effective_stock_factors, stock_targets

D0, D1, D2 = dt.date(2026, 9, 9), dt.date(2026, 9, 10), dt.date(2026, 9, 11)


def fixture_inputs():
    start, end = dt.date(2026, 1, 1), dt.date(2026, 10, 5)
    sessions = tuple(
        start + dt.timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + dt.timedelta(days=i)).weekday() < 5
    )
    symbols = [f"{600000 + number:06d}.SH" for number in range(60)]
    rows, basic = [], []
    for number, symbol in enumerate(symbols):
        for index, date in enumerate(sessions):
            price = 10 + number * 0.1 + index * 0.001 * (number % 7 + 1)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "open": price,
                    "high": price + 0.1,
                    "low": price - 0.1,
                    "close": price,
                    "volume": 3000000.0,
                    "amount": 30000000.0,
                    "adj_factor": 1.0,
                    "source": "fixture",
                }
            )
            basic.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "turnover_rate": 1.0 + (index % 5) * (number % 11 + 1) * 0.01,
                }
            )
    calendar = pl.DataFrame(
        {
            "market": ["SH"] * len(sessions),
            "date": sessions,
            "is_open": [True] * len(sessions),
            "is_connect_open": [False] * len(sessions),
            "is_half_day": [False] * len(sessions),
        }
    )
    instruments = pl.DataFrame(
        {
            "symbol": symbols,
            "market": ["SH"] * 60,
            "name": ["示例股份"] * 60,
            "instrument_type": ["STOCK"] * 60,
            "currency": ["CNY"] * 60,
            "list_date": [dt.date(2000, 1, 1)] * 60,
            "delist_date": [None] * 60,
            "board_lot": [100] * 60,
            "status": ["LISTED"] * 60,
        }
    )
    names = pl.DataFrame(
        {
            "symbol": symbols,
            "name": ["示例股份"] * 60,
            "start_date": [start] * 60,
            "end_date": [None] * 60,
            "ann_date": [start] * 60,
        }
    )
    limits = pl.DataFrame(
        [
            {"symbol": symbol, "trade_date": date, "up_limit": 100.0, "down_limit": 1.0}
            for symbol in symbols
            for date in sessions
        ]
    )
    inputs = StockPaperInputs(
        pl.DataFrame(rows),
        pl.DataFrame(basic),
        calendar,
        names,
        instruments,
        limits,
        pl.DataFrame(schema={"symbol": pl.String, "trade_date": pl.Date}),
        pl.DataFrame(schema=DIVIDEND_SCHEMA),
    )
    text = Path("configs/paper/b32_stock_observation_20260909.toml").read_text(encoding="utf-8")
    text = text.replace("top_n = 800", "top_n = 60").replace(
        "minimum_daily_symbols = 100", "minimum_daily_symbols = 50"
    )
    config = tomllib.loads(text)
    return inputs, config, text, sessions


def patch_reader(monkeypatch, inputs):
    monkeypatch.setattr(stock_paper, "read_stock_paper_calendar", lambda *_: inputs.calendar)
    monkeypatch.setattr(stock_paper, "read_stock_paper_freeze", lambda *_: inputs.bars)
    monkeypatch.setattr(stock_paper, "read_stock_paper_inputs", lambda *_: inputs)


def initial_state(symbol="600000.SH"):
    return {
        "date": str(D0),
        "cash": 1000000.0,
        "holdings": {},
        "receivables": [],
        "restricted_shares": [],
        "nav": [],
        "previous_targets": [symbol],
        "pending": [
            {
                "as_of": str(D0),
                "execution_date": str(D1),
                "symbol": symbol,
                "strategy": "b32_cv20_buffer75",
                "strategy_version": "v1",
                "weight": 0.02,
            }
        ],
    }


def test_initial_real_sizing_continuation_and_repeat_no_fill(tmp_path, monkeypatch):
    inputs, config, text, _ = fixture_inputs()
    patch_reader(monkeypatch, inputs)
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    output = tmp_path / "observation"
    first = stock_paper.run(config_path=path, data_root=tmp_path, output=output, end=D0)
    assert all(row["sessions"] == 0 and row["targets"] == 50 for row in first["accounts"])
    for account in config["accounts"]:
        folder = output / account["name"] / str(D0)
        assert pl.read_csv(folder / "nav.csv").is_empty()
        assert not (folder / "fills.csv").exists()
        orders = pl.read_csv(folder / "orders.csv")
        assert orders.height == 50
        assert (orders["quantity"] % orders["board_lot"] == 0).all()
        assert orders["cash_after"].min() >= 0
        assert (orders["estimated_notional"] + orders["estimated_fee"]).sum() <= 1000000
    next_day = stock_paper.run(config_path=path, data_root=tmp_path, output=output, end=D1)
    assert all(row["sessions"] == 1 and row["positions"] == 50 for row in next_day["accounts"])
    continued = stock_paper.run(config_path=path, data_root=tmp_path, output=output, end=D2)
    assert all(row["sessions"] == 2 for row in continued["accounts"])
    state_path = output / "b32_cv20_buffer75" / str(D2) / "state.json"
    before = state_path.read_bytes()
    repeated = stock_paper.run(config_path=path, data_root=tmp_path, output=output, end=D2)
    assert all(row["new_sessions"] == 0 for row in repeated["accounts"])
    assert state_path.read_bytes() == before
    assert pl.read_csv(state_path.parent / "fills.csv").is_empty()


def test_missing_current_price_preserves_last_snapshot(tmp_path, monkeypatch):
    inputs, _, text, _ = fixture_inputs()
    patch_reader(monkeypatch, inputs)
    config_path = tmp_path / "config.toml"
    config_path.write_text(text, encoding="utf-8")
    output = tmp_path / "obs"
    stock_paper.run(config_path=config_path, data_root=tmp_path, output=output, end=D0)
    initial_path = output / "b32_cv20_buffer75" / str(D0) / "state.json"
    initial = initial_path.read_bytes()
    chosen = json.loads(initial)["pending"][0]["symbol"]
    inputs.bars = inputs.bars.filter(~((pl.col("symbol") == chosen) & (pl.col("trade_date") == D1)))
    with pytest.raises(ValueError, match="Missing current stock price"):
        stock_paper.run(config_path=config_path, data_root=tmp_path, output=output, end=D1)
    assert initial_path.read_bytes() == initial
    assert not (output / "b32_cv20_buffer75" / str(D1) / "state.json").exists()


def test_future_rows_and_effective_names_cannot_change_today_targets():
    inputs, config, _, sessions = fixture_inputs()
    kwargs = dict(names=inputs.names, sessions=sessions, as_of=D0, config=config)
    baseline = effective_stock_factors(bars=inputs.bars, daily_basic=inputs.daily_basic, **kwargs)
    future_bars = inputs.bars.with_columns(
        pl.when(pl.col("trade_date") > D0)
        .then(pl.col("close") * 100)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    future_basic = inputs.daily_basic.with_columns(
        pl.when(pl.col("trade_date") > D0)
        .then(99999.0)
        .otherwise(pl.col("turnover_rate"))
        .alias("turnover_rate")
    )
    changed = effective_stock_factors(bars=future_bars, daily_basic=future_basic, **kwargs)
    assert changed.equals(baseline)
    future_name = inputs.names.head(1).with_columns(
        pl.lit(D1).alias("start_date"), pl.lit("STfixture").alias("name")
    )
    kwargs["names"] = pl.concat([inputs.names, future_name], how="vertical_relaxed")
    assert effective_stock_factors(
        bars=inputs.bars, daily_basic=inputs.daily_basic, **kwargs
    ).equals(baseline)


def test_buffer_keeps_previous_targets_within_top75_and_same_effective_pool():
    inputs, config, _, sessions = fixture_inputs()
    panel = effective_stock_factors(
        bars=inputs.bars,
        daily_basic=inputs.daily_basic,
        names=inputs.names,
        sessions=sessions,
        as_of=D0,
        config=config,
    )
    account = config["accounts"][0]
    _, ranking = stock_targets(
        panel, previous_targets=[], as_of=D0, execution_date=D1, account=account
    )
    previous = ranking.tail(50)["symbol"].to_list()
    targets, _ = stock_targets(
        panel, previous_targets=previous, as_of=D0, execution_date=D1, account=account
    )
    assert set(row["symbol"] for row in targets) == set(previous)
    missing_symbol = panel["symbol"][0]
    missing_basic = inputs.daily_basic.filter(
        ~((pl.col("symbol") == missing_symbol) & (pl.col("trade_date") == D0))
    )
    reduced = effective_stock_factors(
        bars=inputs.bars,
        daily_basic=missing_basic,
        names=inputs.names,
        sessions=sessions,
        as_of=D0,
        config=config,
    )
    assert missing_symbol not in reduced["symbol"]
    for spec in config["accounts"]:
        _, ranked = stock_targets(
            reduced, previous_targets=[], as_of=D0, execution_date=D1, account=spec
        )
        assert set(ranked["symbol"]) == set(reduced["symbol"])


def test_actual_bands_sell_tax_and_cash_budget():
    inputs, config, _, _ = fixture_inputs()
    local = stock_paper.account_config(
        config, config["accounts"][0], {"halt": False, "sell_only": False}
    )
    state = initial_state()
    _, result = stock_paper.advance_stock_day(date=D1, state=state, inputs=inputs, config=local)
    fill = result.trades.row(0, named=True)
    costs = AShareCostModel(**config["costs"]["a_share"])
    assert fill["fee"] == pytest.approx(costs.fee(fill["notional"], D1, "BUY"))
    state["holdings"] = {"600000.SH": {"quantity": 100, "mark_price": 10.0}}
    state["pending"][0]["weight"] = 0.0
    _, sold = stock_paper.advance_stock_day(date=D1, state=state, inputs=inputs, config=local)
    sale = sold.trades.row(0, named=True)
    assert sale["fee"] == pytest.approx(costs.fee(sale["notional"], D1, "SELL"))
    assert sale["fee"] - costs.fee(sale["notional"], D1, "BUY") == pytest.approx(
        sale["notional"] * 0.0005
    )
    blocked = copy.deepcopy(inputs)
    blocked.limits = inputs.limits.with_columns(pl.lit(1.0).alias("up_limit"))
    _, rejected = stock_paper.advance_stock_day(
        date=D1, state=initial_state(), inputs=blocked, config=local
    )
    assert rejected.trades.is_empty() and not rejected.rejections.is_empty()
    blocked.limits = inputs.limits.clear()
    with pytest.raises(ValueError, match="Missing stock price band"):
        stock_paper.advance_stock_day(date=D1, state=initial_state(), inputs=blocked, config=local)


def test_global_halt_and_sell_only_and_repeat_date():
    inputs, config, _, _ = fixture_inputs()
    state = initial_state()
    halted = stock_paper.account_config(
        config, config["accounts"][0], {"halt": True, "sell_only": False}
    )
    assert stock_paper.reference_orders(state, inputs, halted).is_empty()
    next_state, result = stock_paper.advance_stock_day(
        date=D1, state=state, inputs=inputs, config=halted
    )
    assert result.trades.is_empty() and next_state["cash"] == 1000000
    sell_only = stock_paper.account_config(
        config, config["accounts"][0], {"halt": False, "sell_only": True}
    )
    assert stock_paper.reference_orders(state, inputs, sell_only).is_empty()
    _, result = stock_paper.advance_stock_day(date=D1, state=state, inputs=inputs, config=sell_only)
    assert result.trades.is_empty()
    state["holdings"] = {"600000.SH": {"quantity": 100, "mark_price": 10.0}}
    state["pending"][0]["weight"] = 1.0
    inputs.dividends = pl.DataFrame(
        {
            "symbol": ["600000.SH"],
            "ann_date": [D0],
            "record_date": [D0],
            "ex_date": [D1],
            "pay_date": [D1],
            "div_cash": [1.0],
            "share_ratio": [0.0],
            "share_list_date": [None],
        }
    )
    _, paid_result = stock_paper.advance_stock_day(
        date=D1, state=state, inputs=inputs, config=sell_only
    )
    assert paid_result.trades.filter(pl.col("side") == "BUY").is_empty()
    with pytest.raises(ValueError, match="execute a date twice"):
        stock_paper.advance_stock_day(date=D1, state=next_state, inputs=inputs, config=halted)
    config["paper"]["auto_trade"] = True
    unsafe = stock_paper.account_config(
        config, config["accounts"][0], {"halt": False, "sell_only": False}
    )
    with pytest.raises(ValueError, match="auto_trade"):
        stock_paper.reference_orders(state, inputs, unsafe)


def test_official_suspension_carries_prior_mark_without_filling():
    inputs, config, _, _ = fixture_inputs()
    state = initial_state()
    inputs.bars = inputs.bars.filter(
        ~((pl.col("symbol") == "600000.SH") & (pl.col("trade_date") == D1))
    )
    inputs.suspensions = pl.DataFrame({"symbol": ["600000.SH"], "trade_date": [D1]})
    local = stock_paper.account_config(
        config, config["accounts"][0], {"halt": False, "sell_only": False}
    )
    next_state, result = stock_paper.advance_stock_day(
        date=D1, state=state, inputs=inputs, config=local
    )
    assert result.trades.is_empty() and result.rejections["reason"].to_list() == ["SUSPENDED"]
    assert next_state["cash"] == 1000000


def test_dividend_mapper_excludes_future_and_account_recognizes_cash():
    raw = pl.DataFrame(
        {
            "ts_code": ["600000.SH"],
            "div_proc": ["实施"],
            "imp_ann_date": ["20260909"],
            "record_date": ["20260909"],
            "ex_date": ["20260910"],
            "pay_date": ["20260911"],
            "div_listdate": [None],
            "cash_div_tax": [1.0],
            "stk_div": [0.0],
        }
    )
    assert map_day_dividends(raw, D0).is_empty()
    dividends = map_day_dividends(raw, D1)
    inputs, config, _, _ = fixture_inputs()
    inputs.dividends = dividends.with_columns((pl.col("div_cash") * 0.8).alias("div_cash"))
    state = initial_state()
    state["pending"] = []
    state["holdings"] = {"600000.SH": {"quantity": 100, "mark_price": 10.0}}
    local = stock_paper.account_config(
        config, config["accounts"][0], {"halt": False, "sell_only": False}
    )
    ex, _ = stock_paper.advance_stock_day(date=D1, state=state, inputs=inputs, config=local)
    assert ex["nav"][-1]["receivable"] == 80.0
    paid, _ = stock_paper.advance_stock_day(date=D2, state=ex, inputs=inputs, config=local)
    assert paid["cash"] == state["cash"] + 80.0
    assert not paid["receivables"]


def test_persistent_controls_change_active_orders_without_replaying_snapshot(tmp_path, monkeypatch):
    inputs, _, text, _ = fixture_inputs()
    patch_reader(monkeypatch, inputs)
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    output = tmp_path / "observation"
    kwargs = dict(config_path=path, data_root=tmp_path, output=output, end=D0)
    stock_paper.run(**kwargs)
    snapshot = output / "b32_cv20_buffer75" / str(D0) / "state.json"
    before = snapshot.read_bytes()
    halted = stock_paper.run(**kwargs, halt=True)
    assert all(row["reference_orders"] == 0 for row in halted["accounts"])
    assert json.loads((output / "controls.json").read_text())["halt"]
    only_sells = stock_paper.run(**kwargs, halt=False, sell_only=True)
    assert all(row["reference_orders"] == 0 for row in only_sells["accounts"])
    resumed = stock_paper.run(**kwargs, sell_only=False)
    assert all(row["reference_orders"] == 50 for row in resumed["accounts"])
    assert snapshot.read_bytes() == before


def test_cli_before_input_cutoff_skips_nav_but_applies_manual_halt(tmp_path, monkeypatch, capsys):
    class Early(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 9, 17, 30, tzinfo=tz)

    monkeypatch.setattr(stock_paper.dt, "datetime", Early)
    monkeypatch.setattr(
        sys, "argv", ["stock_paper", "--to", "today", "--output", str(tmp_path), "--halt"]
    )
    stock_paper.main()
    result = json.loads(capsys.readouterr().out)
    assert (
        result["action"] == "skipped_waiting_for_daily_inputs" and result["snapshots_advanced"] == 0
    )
    assert json.loads((tmp_path / "controls.json").read_text())["halt"]
    assert not list(tmp_path.glob("**/state.json"))


def test_monthly_expectations_keep_entry_costs_reset_folds_and_omit_partial_month():
    from quant.reporting.stock_paper_monthly import historical_months

    dates = [dt.date(2024, 1, 2), dt.date(2024, 1, 31), dt.date(2024, 2, 1), dt.date(2025, 1, 31)]
    nav = pl.DataFrame({"date": dates, "fold": [1, 1, 1, 2], "unit_nav": [0.99, 1.1, 1.2, 1.3]})
    calendar = pl.DataFrame({"date": dates + [dt.date(2024, 2, 29)], "is_open": [True] * 5})
    result = historical_months(nav, calendar)
    assert result["month"].to_list() == ["2024-01", "2025-01"]
    assert result["return"].to_list() == pytest.approx([0.1, 0.3])
