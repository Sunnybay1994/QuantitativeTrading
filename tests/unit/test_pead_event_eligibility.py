import datetime as dt

import polars as pl
import pytest

from quant.research.pead_event_eligibility import ELIGIBILITY_SCHEMA, enrich_event_eligibility

START = dt.date(2019, 1, 1)
SESSIONS = tuple(START + dt.timedelta(days=i) for i in range(1100)
                 if (START + dt.timedelta(days=i)).weekday() < 5)
DATE = dt.date(2020, 4, 1)
SYMBOL = "000001.SZ"


def event_rows(records=None):
    records = records or [(SYMBOL, DATE, 10., "VALID")]
    return pl.DataFrame([{"symbol": symbol, "announcement_date": date,
                         "end_date": dt.date(date.year - 1, 12, 31),
                         "sue": sue, "status": status, "reason": "original diagnostic"}
                        for symbol, date, sue, status in records], schema={
        "symbol": pl.String, "announcement_date": pl.Date, "end_date": pl.Date,
        "sue": pl.Float64, "status": pl.String, "reason": pl.String})


def market(symbols=(SYMBOL,)):
    bars = pl.DataFrame({"symbol": [symbol for symbol in symbols for _ in SESSIONS],
                         "trade_date": list(SESSIONS) * len(symbols),
                         "close": [10.] * len(SESSIONS) * len(symbols),
                         "amount": [25_000_000.] * len(SESSIONS) * len(symbols)})
    names = pl.DataFrame({"symbol": list(symbols), "name": ["历史正常公司"] * len(symbols),
                         "start_date": [START] * len(symbols), "end_date": [None] * len(symbols),
                         "ann_date": [START] * len(symbols)}, schema={
        "symbol": pl.String, "name": pl.String, "start_date": pl.Date,
        "end_date": pl.Date, "ann_date": pl.Date})
    return bars, names


def evaluate(events=None, bars=None, names=None, sessions=SESSIONS):
    default_bars, default_names = market()
    return enrich_event_eligibility(events=event_rows() if events is None else events,
        bars=default_bars if bars is None else bars, names=default_names if names is None else names,
        sessions=sessions)


def test_preserves_all_event_columns_and_complete_known_history_is_market_eligible():
    original = event_rows()
    result = evaluate(original)
    assert result.select(original.columns).equals(original)
    assert {key: result.schema[key] for key in ELIGIBILITY_SCHEMA} == ELIGIBILITY_SCHEMA
    row = result.row(0, named=True)
    assert row["eligible"] and row["market_eligible"] and row["financial_eligible"]
    assert row["expected_price_date"] == row["price_date"] == DATE
    assert row["liquidity_session_count"] == 20 and row["liquidity20"] == 25_000_000.
    assert row["valid_price_history"] == len([day for day in SESSIONS if day <= DATE])
    assert row["name_status"] == "NORMAL" and row["name_ann_date"] == START
    assert not row["selected"] and row["selection_reason"] == "PRIOR_QUARTER_BELOW_100"


def test_missing_recent_session_is_not_backfilled_by_older_twentieth_bar():
    bars, _ = market()
    bars = bars.filter(pl.col("trade_date") != dt.date(2020, 3, 27))
    row = evaluate(bars=bars).row(0, named=True)
    assert row["price_date"] == DATE and row["valid_price_history"] > 120
    assert row["liquidity_session_count"] == 19 and row["liquidity20"] is None
    assert not row["market_eligible"]
    assert "INCOMPLETE_20_SESSION_AMOUNT" in row["eligibility_reason"]


def test_amount_average_matches_independent_exact_exchange_window():
    bars, _ = market()
    known = [day for day in SESSIONS if day <= DATE]
    amounts = {day: float(20_000_000 + i * 10000) for i, day in enumerate(known)}
    varying = pl.DataFrame({"symbol": [SYMBOL] * len(known), "trade_date": known,
                           "close": [10.] * len(known), "amount": list(amounts.values())})
    # An absent observation just outside the 20-session interval is irrelevant.
    varying = varying.filter(pl.col("trade_date") != known[-21])
    row = evaluate(bars=varying).row(0, named=True)
    assert row["liquidity_window_start"] == known[-20]
    assert row["liquidity_session_count"] == 20
    assert row["liquidity20"] == pytest.approx(sum(amounts[day] for day in known[-20:]) / 20)
    assert row["eligible"]


def test_stale_close_cannot_use_old_price_or_old_liquidity_window():
    bars, _ = market()
    bars = bars.filter(pl.col("trade_date") < dt.date(2020, 3, 30))
    row = evaluate(bars=bars).row(0, named=True)
    assert row["price_date"] == dt.date(2020, 3, 27)
    assert row["liquidity_session_count"] == 17 and row["liquidity20"] is None
    assert "STALE_CLOSE" in row["eligibility_reason"] and not row["eligible"]


@pytest.mark.parametrize("bad", [None, float("nan"), -1.])
def test_invalid_amount_is_missing_not_zero_or_an_older_observation(bad):
    bars, _ = market()
    bars = bars.with_columns(pl.when(pl.col("trade_date") == DATE).then(pl.lit(bad, dtype=pl.Float64))
                            .otherwise(pl.col("amount")).alias("amount"))
    row = evaluate(bars=bars).row(0, named=True)
    assert row["liquidity_session_count"] == 19 and row["liquidity20"] is None
    assert not row["eligible"]


def test_zero_amount_counts_as_observed_and_minimum_amount_is_inclusive():
    bars, _ = market()
    bars = bars.with_columns(pl.lit(20_000_000.).alias("amount"))
    assert evaluate(bars=bars)["eligible"][0]
    bars = bars.with_columns(pl.when(pl.col("trade_date") == DATE).then(0.)
                            .otherwise(pl.col("amount")).alias("amount"))
    row = evaluate(bars=bars).row(0, named=True)
    assert row["liquidity_session_count"] == 20 and row["liquidity20"] == 19_000_000.
    assert row["eligibility_reason"] == "MEAN_AMOUNT_BELOW_20M"


def test_valid_close_history_counts_actual_valid_prices_and_exact_120_boundary():
    bars, _ = market()
    dates = [day for day in SESSIONS if day <= DATE][-120:]
    bars = bars.filter(pl.col("trade_date").is_in(dates))
    assert evaluate(bars=bars)["eligible"][0]
    invalid = bars.with_columns(pl.when(pl.col("trade_date") == dates[0]).then(float("nan"))
                               .otherwise(pl.col("close")).alias("close"))
    row = evaluate(bars=invalid).row(0, named=True)
    assert row["valid_price_history"] == 119
    assert row["eligibility_reason"] == "PRICE_HISTORY_BELOW_120"
    invalid = bars.with_columns(pl.when(pl.col("trade_date") == DATE).then(0.)
                               .otherwise(pl.col("close")).alias("close"))
    assert "STALE_CLOSE" in evaluate(bars=invalid)["eligibility_reason"][0]


def test_weekend_announcement_uses_last_exchange_close_but_announcement_day_name():
    bars, names = market()
    weekend = dt.date(2020, 4, 5)
    changed = names.with_columns(pl.lit("*ST公司").alias("name"),
        pl.lit(dt.date(2020, 4, 4)).alias("start_date"), pl.lit(dt.date(2020, 4, 3)).alias("ann_date"))
    row = evaluate(event_rows([(SYMBOL, weekend, 10., "VALID")]), bars,
                   pl.concat([names, changed])).row(0, named=True)
    assert row["expected_price_date"] == row["price_date"] == dt.date(2020, 4, 3)
    assert row["name_status"] == "RISK_NAME" and not row["eligible"]


@pytest.mark.parametrize("change,expected", [
    ({"ann_date": None}, "UNKNOWN_NAME_ANNOUNCEMENT"),
    ({"end_date": dt.date(2020, 3, 31)}, "UNKNOWN_NAME_EXPIRED"),
    ({"name": None}, "UNKNOWN_NAME_VALUE"),
    ({"name": "*ST退市"}, "RISK_NAME"),
])
def test_latest_known_name_is_not_replaced_by_older_normal(change, expected):
    _, names = market()
    latest = names.with_columns(pl.lit(dt.date(2020, 3, 1)).alias("start_date"))
    latest = latest.with_columns([pl.lit(value, dtype=names.schema[key]).alias(key)
                                  for key, value in change.items()])
    row = evaluate(names=pl.concat([names, latest])).row(0, named=True)
    assert row["name_status"] == expected and not row["eligible"]


def test_unknown_and_conflicting_names_do_not_count_as_normal():
    _, names = market()
    assert evaluate(names=names.head(0))["name_status"][0] == "UNKNOWN_NAME_COVERAGE"
    assert evaluate(names=names.drop("ann_date"))["name_status"][0] == "UNKNOWN_NAME_ANNOUNCEMENT"
    conflict = names.with_columns(pl.lit("ST公司").alias("name"))
    assert evaluate(names=pl.concat([names, conflict]))["name_status"][0] == "UNKNOWN_NAME_CONFLICT"
    assert evaluate(names=pl.concat([names, names])).equals(evaluate(names=names))


def quarterly_example():
    symbols = (SYMBOL, "000002.SZ")
    records = [(symbols[i % 2], dt.date(2020, 1, 10) + dt.timedelta(days=i // 2),
                float(i - 50), "VALID") for i in range(100)]
    records += [(SYMBOL, dt.date(2020, 4, 1), 40., "VALID"),
                (SYMBOL, dt.date(2020, 6, 30), 40., "VALID"),
                (SYMBOL, dt.date(2020, 7, 1), 40., "VALID")]
    bars, names = market(symbols)
    return event_rows(records), bars, names


def test_quarter_threshold_uses_all_eligible_sues_linear_quantile_and_fixed_boundaries():
    events, bars, names = quarterly_example()
    actual = evaluate(events, bars, names)
    april = actual.filter(pl.col("announcement_date") == dt.date(2020, 4, 1)).row(0, named=True)
    june = actual.filter(pl.col("announcement_date") == dt.date(2020, 6, 30)).row(0, named=True)
    july = actual.filter(pl.col("announcement_date") == dt.date(2020, 7, 1)).row(0, named=True)
    # The 100-point cohort includes fifty negative scores, not only winners.
    assert april["threshold_count"] == june["threshold_count"] == 100
    assert april["threshold"] == pytest.approx(39.1) and april["selected"]
    assert april["threshold_quarter_start"] == dt.date(2020, 1, 1)
    assert april["threshold_quarter_end"] == dt.date(2020, 3, 31)
    assert july["threshold_count"] == 2 and july["threshold"] is None
    assert not july["selected"]


def test_99_prior_eligible_events_are_insufficient_and_invalid_event_stays_visible():
    events, bars, names = quarterly_example()
    events = events.with_row_index("i").with_columns(pl.when(pl.col("i") == 0)
        .then(pl.lit("MISSING")).otherwise(pl.col("status")).alias("status")).drop("i")
    actual = evaluate(events, bars, names)
    assert actual.height == events.height
    assert not actual["financial_eligible"][0] and actual["market_eligible"][0]
    april = actual.filter(pl.col("announcement_date") == DATE).row(0, named=True)
    assert april["threshold_count"] == 99 and april["threshold"] is None and not april["selected"]


def test_market_ineligible_prior_event_is_excluded_from_the_quarter_cohort():
    events, bars, names = quarterly_example()
    # Only the last prior-quarter event of symbol 2 sees this missing observation.
    bars = bars.filter(~((pl.col("symbol") == "000002.SZ")
                        & (pl.col("trade_date") == dt.date(2020, 2, 28))))
    actual = evaluate(events, bars, names)
    april = actual.filter(pl.col("announcement_date") == DATE).row(0, named=True)
    assert april["threshold_count"] == 99 and april["threshold"] is None
    invalid = actual.filter((pl.col("symbol") == "000002.SZ")
                            & (pl.col("announcement_date") == dt.date(2020, 2, 28)))
    assert invalid["financial_eligible"][0] and not invalid["market_eligible"][0]


def test_sue_must_be_positive_even_if_previous_quarter_threshold_is_negative():
    events, bars, names = quarterly_example()
    events = events.with_columns(pl.lit(-1.).alias("sue"))
    april = evaluate(events, bars, names).filter(pl.col("announcement_date") == DATE).row(0, named=True)
    assert april["threshold"] == -1. and not april["selected"]
    assert april["selection_reason"] == "NONPOSITIVE_SUE"


def test_future_prices_events_and_retroactive_future_announced_name_do_not_change_past():
    events, bars, names = quarterly_example()
    past = events.filter(pl.col("announcement_date") <= DATE)
    old = evaluate(past, bars.filter(pl.col("trade_date") <= DATE), names)
    future_name = names.head(1).with_columns(pl.lit("ST公司").alias("name"),
        pl.lit(dt.date(2020, 2, 1)).alias("start_date"), pl.lit(dt.date(2020, 7, 1)).alias("ann_date"))
    new = evaluate(events, bars, pl.concat([names, future_name])).filter(pl.col("announcement_date") <= DATE)
    assert new.equals(old)


def test_retired_company_keeps_historical_event_without_current_survivor_filter():
    bars, names = market(("000018.SZ",))
    bars = bars.filter(pl.col("trade_date") <= DATE)
    names = names.with_columns(pl.lit(dt.date(2020, 5, 1)).alias("end_date"))
    row = evaluate(event_rows([("000018.SZ", DATE, 3., "VALID")]), bars, names).row(0, named=True)
    assert row["eligible"] and row["symbol"] == "000018.SZ"


def test_empty_result_has_typed_columns_and_duplicate_prices_fail_closed():
    result = evaluate(event_rows().head(0))
    assert result.is_empty()
    assert {key: result.schema[key] for key in ELIGIBILITY_SCHEMA} == ELIGIBILITY_SCHEMA
    bars, _ = market()
    with pytest.raises(ValueError, match="Duplicate symbol/day"):
        evaluate(bars=pl.concat([bars, bars.filter(pl.col("trade_date") == DATE)]))
    with pytest.raises(ValueError, match="Duplicate first-disclosure"):
        evaluate(pl.concat([event_rows(), event_rows()]))


def test_no_prior_price_and_truncated_calendar_are_explicitly_ineligible():
    bars, _ = market()
    no_price = evaluate(bars=bars.head(0)).row(0, named=True)
    assert no_price["valid_price_history"] == 0 and "NO_VALID_CLOSE" in no_price["eligibility_reason"]
    before = event_rows([(SYMBOL, START - dt.timedelta(days=1), 2., "VALID")])
    row = evaluate(before).row(0, named=True)
    assert "NO_PRIOR_EXCHANGE_SESSION" in row["eligibility_reason"]
    truncated = tuple(day for day in SESSIONS if day < DATE)
    row = evaluate(bars=bars.filter(pl.col("trade_date") < DATE), sessions=truncated).row(0, named=True)
    assert "CALENDAR_COVERAGE_UNKNOWN" in row["eligibility_reason"]
