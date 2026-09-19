import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

from quant.factors.expressions import evaluate_expressions
from quant.research.pressure_reversal_readiness import expression_key, profile


def _expressions():
    settings = tomllib.loads(Path("configs/research/pressure_reversal_v1.toml").read_text())
    return {x["id"]: x["expr"] for x in settings["candidates"] + settings["controls"]}


def _panel():
    return pl.DataFrame([
        {"symbol": symbol, "trade_date": dt.date(2020, 1, 1) + dt.timedelta(days=i),
         "adj_close": 10.0 + i * (j + 1) / 100,
         "amount": 100.0 + i * (j + 1), "industry_l1": "SW:test"}
        for j, symbol in enumerate(["A", "B", "C"]) for i in range(25)
    ]).sort("symbol", "trade_date")


def test_later_input_changes_do_not_change_earlier_signals():
    panel = _panel()
    cutoff = dt.date(2020, 1, 24)
    changed = panel.with_columns(
        pl.when(pl.col("trade_date") > cutoff).then(1000000).otherwise(pl.col("amount")).alias("amount"),
        pl.when(pl.col("trade_date") > cutoff).then(1).otherwise(pl.col("adj_close")).alias("adj_close"),
    )
    before = evaluate_expressions(panel, _expressions()).filter(pl.col("trade_date") <= cutoff)
    after = evaluate_expressions(changed, _expressions()).filter(pl.col("trade_date") <= cutoff)
    assert_frame_equal(before, after)


def test_unknown_industry_cannot_produce_pressure_candidates():
    panel = _panel().with_columns(pl.lit(None, dtype=pl.String).alias("industry_l1"))
    values = evaluate_expressions(panel, _expressions())
    for name in ["pressure_reversal_high_amount_v1", "pressure_reversal_low_amount_v1"]:
        assert values[name].null_count() == panel.height
    assert values["raw_reversal_5"].is_finite().sum() > 0


def test_missing_exchange_session_is_not_skipped_in_amount_history():
    panel = _panel().with_columns(
        pl.when(pl.col("trade_date") == dt.date(2020, 1, 15))
        .then(None).otherwise(pl.col("amount")).alias("amount")
    )
    values = evaluate_expressions(panel, _expressions()).filter(pl.col("trade_date") == dt.date(2020, 1, 25))
    assert values["abnormal_amount_20"].null_count() == 3


def test_zero_amount_is_unavailable_and_profile_excludes_warmup():
    panel = _panel().with_columns(
        pl.when(pl.col("trade_date") == dt.date(2020, 1, 25))
        .then(0).otherwise(pl.col("amount")).alias("amount")
    )
    day = dt.date(2020, 1, 25)
    result = profile(panel, panel, _expressions(), day, day)
    assert result["observed_stock_days"] == 3
    assert result["nonpositive_amount_rows"] == 3
    assert result["signal_finite_rows"]["pressure_reversal_high_amount_v1"] == 0


def test_ast_duplicate_check_ignores_layout_but_not_direction():
    assert expression_key("rank(amount)") == expression_key("rank( amount )")
    assert expression_key("rank(amount)") != expression_key("-rank(amount)")


def test_high_amount_condition_strengthens_loser_not_winner():
    day = dt.date(2020, 1, 25)
    panel = _panel().with_columns(
        pl.when((pl.col("symbol") == "A") & (pl.col("trade_date") == day))
        .then(10000).otherwise(pl.col("amount")).alias("amount")
    )
    values = evaluate_expressions(panel, _expressions()).filter(pl.col("trade_date") == day)
    loser = values.filter(pl.col("symbol") == "A").row(0, named=True)
    winner = values.filter(pl.col("symbol") == "C").row(0, named=True)
    assert loser["pressure_reversal_high_amount_v1"] == 0.5
    assert loser["pressure_reversal_low_amount_v1"] == 0
    assert winner["pressure_reversal_high_amount_v1"] < 0
