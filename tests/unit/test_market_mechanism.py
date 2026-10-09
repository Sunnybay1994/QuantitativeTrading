import datetime as dt

import polars as pl
import pytest

from quant.research.market_mechanism import DIMENSIONS, aggregate, aligned_states
from quant.research.market_mechanism_mapping import mechanism


def test_state_must_match_exact_signal_and_execution():
    dates = [dt.date(2020, 1, 31), dt.date(2020, 2, 28), dt.date(2020, 3, 31)]
    labels = pl.DataFrame({"trade_date": dates,
        "execution_date_rebalance": [dt.date(2020, 2, 3), dt.date(2020, 3, 2), dt.date(2020, 4, 1)]})
    states = pl.DataFrame({"trade_date": dates[:2],
        "effective_date": [dt.date(2020, 2, 3), dt.date(2020, 3, 3)],
        "timing": ["historical", "historical"], "coverage_ok": [True, True],
        **{c: ["high", "low"] for c in DIMENSIONS}})
    result = aligned_states(labels, states)
    assert result["market_state"].to_list() == ["high", "unknown", "unknown"]
    assert result["alignment_reason"].to_list()[1:] == ["effective_date_mismatch", "state_date_absent"]


def test_ambiguous_state_is_rejected():
    labels = pl.DataFrame({"trade_date": [dt.date(2020, 1, 31)] * 2})
    states = pl.DataFrame({"trade_date": [dt.date(2020, 1, 31)]})
    with pytest.raises(ValueError, match="Ambiguous"):
        aligned_states(labels, states)


def test_sparse_years_not_counted_as_six_month_years():
    data = pl.DataFrame({"family": ["x"] * 8, "year": [2019] * 6 + [2020, 2021],
                         "ic": [0.1] * 6 + [-0.9, None]})
    row = aggregate(data, ["family"], "ic").row(0, named=True)
    assert row["months"] == 7
    assert row["years_observed"] == 2
    assert row["years_at_least_6_months"] == 1
    assert row["positive_qualified_year_fraction"] == 1
    assert row["positive_year_fraction"] == 0.5


def test_financial_mapping_does_not_use_outcomes_or_reverse_direction():
    original = {"id": "pit_asset_growth_yoy", "family": "pit_financial", "direction": -1}
    assert mechanism(original)[0] == "investment_accrual"
    assert mechanism({**original, "mean_ic": -0.2, "statistical_pass": False}) == mechanism(original)
    assert original["direction"] == -1


def test_new_financial_definition_requires_explicit_assignment():
    with pytest.raises(ValueError, match="Unclassified"):
        mechanism({"id": "pit_future_unknown", "family": "pit_financial"})
