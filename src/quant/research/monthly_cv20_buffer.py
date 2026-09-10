"""Admission rules for the paired retention-buffer experiments."""

import math
from typing import Any


def summarize_cv20_buffer(
    results: list[dict[str, Any]], *, comparison: str = "cv20_unbuffered",
    maximum_fold_turnover: float | None = None,
) -> dict[str, Any]:
    """Use actual paired replays; lower turnover is required in every fold."""
    primary = {r["fold"]: r for r in results if r["comparison"] == "top50" and r["cost_multiplier"] == 1}
    baseline = {r["fold"]: r for r in results if r["comparison"] == comparison and r["cost_multiplier"] == 1}
    stress = {r["fold"]: r for r in results if r["comparison"] == "top50" and r["cost_multiplier"] == 2}
    if not primary or primary.keys() != baseline.keys() or primary.keys() != stress.keys():
        raise ValueError("Buffer experiments require complete paired and stress replays")
    one = math.prod(1 + r["total_return"] for r in primary.values()) - 1
    base = math.prod(1 + r["total_return"] for r in baseline.values()) - 1
    two = math.prod(1 + r["total_return"] for r in stress.values()) - 1
    lower = all(primary[f]["annualized_one_way_turnover"] < baseline[f]["annualized_one_way_turnover"] for f in primary)
    within_limit = maximum_fold_turnover is None or all(
        r["annualized_one_way_turnover"] <= maximum_fold_turnover for r in primary.values())
    return {"comparison": comparison, "excess_return_1x": one - base,
            "net_return_1x": one, "baseline_return_1x": base, "net_return_2x": two,
            "lower_turnover_every_fold": lower, "within_turnover_limit": within_limit,
            "passed": one > 0 and one > base and two > 0 and lower and within_limit}
