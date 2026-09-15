import datetime as dt
from decimal import Decimal

import polars as pl

from quant.backtest.daily_simulator import _round_lot
from quant.research.pead_events import build_events, portfolio_weights, replay_events
from tests.unit.test_earnings_surprise import income
from tests.unit.test_daily_simulator import _bar, _calendar, _instruments


def dividends():
    return pl.DataFrame(schema={"symbol": pl.String, "ex_date": pl.Date, "ann_date": pl.Date,
        "record_date": pl.Date, "pay_date": pl.Date, "div_cash": pl.Float64,
        "share_ratio": pl.Float64, "share_list_date": pl.Date})


def test_new_event_does_not_trim_an_existing_round_lot():
    for price in [0.71, 9.89, 31.37, 1873.21]:
        state = {"cash": 812321.13, "receivables": [],
                 "holdings": {"600000.SH": {"quantity": 5700, "mark_price": price}}}
        weights = portfolio_weights(state=state, date=dt.date(2026, 1, 5),
            opens={"600000.SH": price}, dividends=dividends(), expired=set(), entrants=["600001.SH"])
        equity = Decimal(str(state["cash"])) + Decimal(5700) * Decimal(str(price))
        assert _round_lot(weights["600000.SH"], equity, price, 100) == 5700
        assert 0 < weights["600001.SH"] <= .02
        assert sum(weights.values()) <= 1.000000001


def test_event_score_ignores_future_revisions_and_future_quarter_peers():
    history = income([float(i ** 2) for i in range(20)])
    days = tuple(dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(900))
    bars = pl.DataFrame({"symbol": ["000001.SZ"] * len(days), "trade_date": days,
                         "amount": [30_000_000.] * len(days)})
    names = pl.DataFrame({"symbol": ["000001.SZ"], "name": ["ABC"],
        "start_date": [days[0]], "end_date": [None]}, schema_overrides={"end_date": pl.Date})
    kwargs = dict(bars=bars, names=names, sessions=days, start=dt.date(2023, 7, 1),
                  end=dt.date(2025, 1, 31), minimum_threshold_events=1)
    before = build_events(history=history, **kwargs)
    later = history.tail(1).with_columns(pl.lit(dt.date(2025, 3, 1)).alias("available_date"),
        pl.lit(dt.date(2025, 3, 1)).alias("ann_date"), pl.lit(dt.date(2025, 3, 1)).alias("f_ann_date"),
        pl.lit("1").alias("update_flag"), pl.lit(999999.).alias("n_income_attr_p"))
    after = build_events(history=pl.concat([history, later]), **kwargs)
    assert before.equals(after)
    assert before.filter(pl.col("threshold_count") == 0)["threshold"].null_count() > 0
    assert all(e > a for a, e in before.select("announcement_date", "execution_date").iter_rows())
    for row in before.iter_rows(named=True):
        assert days.index(row["expiry_date"]) - days.index(row["execution_date"]) == 40
    truncated = build_events(history=history.filter(pl.col("end_date") < dt.date(2024, 10, 1)), **kwargs)
    early = before.filter(pl.col("announcement_date") <= dt.date(2024, 10, 20))
    assert early.equals(truncated)


def test_overlap_does_not_extend_and_blocked_exit_retries():
    import tomllib
    from pathlib import Path
    from quant.backtest.rules import DailyMarketState

    config = tomllib.loads(Path("configs/research/b31_pead40_20260909.toml").read_text(encoding="utf-8-sig"))
    days = [dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(5)]
    bars = pl.concat([_bar(d) for d in days])
    events = pl.DataFrame({"symbol": ["600000.SH"] * 2,
        "announcement_date": [days[0] - dt.timedelta(days=1), days[0]],
        "execution_date": [days[0], days[1]], "expiry_date": [days[2], days[4]]})
    states = {(d, "600000.SH"): DailyMarketState(at_lower_limit=d == days[2]) for d in days}
    nav, trades, rejects, decisions = replay_events(events=events, bars=bars, calendar=_calendar(*days),
        instruments=_instruments(), dividends=dividends(), market_states=states,
        sessions=days, config=config, name="pead40")
    assert decisions["decision"].to_list() == ["ENTRY_ATTEMPT", "OVERLAP_SKIP"]
    assert trades["side"].to_list() == ["BUY", "SELL"]
    assert trades["date"].to_list() == [days[0], days[3]]
    assert rejects.height == 1
    assert nav["position_count"].to_list() == [1, 1, 1, 0, 0]



def test_new_symbol_event_preserves_old_position_and_failed_entry_is_not_chased():
    import tomllib
    from pathlib import Path
    from quant.backtest.rules import DailyMarketState

    config = tomllib.loads(Path("configs/research/b31_pead40_20260909.toml").read_text(encoding="utf-8-sig"))
    days = [dt.date(2026, 1, 5) + dt.timedelta(days=i) for i in range(4)]
    first = pl.concat([_bar(d, open_price=31.37, close_price=31.37) for d in days])
    second = first.with_columns(pl.lit("600001.SH").alias("symbol"))
    instruments = pl.concat([_instruments(), _instruments().with_columns(pl.lit("600001.SH").alias("symbol"))])
    events = pl.DataFrame({"symbol": ["600000.SH", "600001.SH"],
        "announcement_date": [days[0] - dt.timedelta(days=1), days[0]],
        "execution_date": [days[0], days[1]], "expiry_date": [days[3], days[3]]})
    states = {(d, s): DailyMarketState(at_upper_limit=s == "600001.SH" and d == days[1])
              for d in days for s in ["600000.SH", "600001.SH"]}
    _, trades, rejects, _ = replay_events(events=events, bars=pl.concat([first, second]),
        calendar=_calendar(*days), instruments=instruments, dividends=dividends(),
        market_states=states, sessions=days, config=config, name="pead40")
    assert trades["symbol"].to_list() == ["600000.SH", "600000.SH"]
    assert trades["date"].to_list() == [days[0], days[3]]
    assert trades["quantity"].n_unique() == 1
    assert rejects["symbol"].to_list() == ["600001.SH"]
