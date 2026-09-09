import datetime as dt

import polars as pl
import pytest

from quant.research.classic_factor_composite import build_monthly_zscore_targets
from quant.research.monthly_cv20_buffer import summarize_cv20_buffer


def test_skipped_month_never_updates_retained_membership() -> None:
    dates = [dt.date(2023, 12, 29), dt.date(2024, 1, 31), dt.date(2024, 2, 29)]
    panel = pl.DataFrame([
        {"trade_date": day, "symbol": symbol, "equal_zscore": value}
        for day, scores in zip(dates, [(3, 2, 1), (1, 3, 2), (2, 3, 1)])
        for symbol, value in zip(("A", "B", "C"), scores)
    ])
    sessions = (dates[0], dt.date(2024, 1, 2), dates[1], dt.date(2024, 2, 1),
                dates[2], dt.date(2024, 3, 1))
    kwargs = dict(sessions=sessions, start=dt.date(2024, 1, 1), end=sessions[-1],
                  top_k=1, retention_rank=2, strategy_name="test")
    monthly = build_monthly_zscore_targets(panel, **kwargs)
    slow = build_monthly_zscore_targets(panel, **kwargs, execution_months=(1, 3, 5, 7, 9, 11))
    assert monthly["symbol"].to_list() == ["A", "B", "B"]
    assert slow["symbol"].to_list() == ["A", "A"]
    assert slow["execution_date"].to_list() == [dt.date(2024, 1, 2), dt.date(2024, 3, 1)]
    # A fold that begins in February still deploys using the prior close.
    kwargs["start"] = dt.date(2024, 2, 1)
    initial = build_monthly_zscore_targets(panel, **kwargs, execution_months=(1, 3, 5, 7, 9, 11))
    assert initial["execution_date"].to_list() == [dt.date(2024, 2, 1), dt.date(2024, 3, 1)]
    assert initial["symbol"].to_list() == ["B", "B"]
    with pytest.raises(ValueError, match="fixed B30"):
        build_monthly_zscore_targets(panel, **kwargs, execution_months=(2, 4, 6, 8, 10, 12))


@pytest.mark.parametrize("turnover,passed", [(6.0, True), (6.01, False)])
def test_bimonthly_requires_every_fold_at_most_six_times(turnover: float, passed: bool) -> None:
    results = [
        dict(fold=fold, comparison=comparison, cost_multiplier=cost,
             total_return=ret, annualized_one_way_turnover=turn)
        for fold in (1, 2, 3)
        for comparison, cost, ret, turn in (
            ("top50", 1, .12, turnover if fold == 3 else 5),
            ("top50", 2, .08, 5),
            ("cv20_monthly_buffered", 1, .10, 10),
        )
    ]
    result = summarize_cv20_buffer(results, comparison="cv20_monthly_buffered", maximum_fold_turnover=6)
    assert result["passed"] is passed
    assert result["within_turnover_limit"] is passed
    assert result["excess_return_1x"] == pytest.approx(1.12**3 - 1.1**3)
