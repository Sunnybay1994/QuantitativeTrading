"""The fixed B28 paired buffer experiment admission rules."""

import math
from typing import Any


def summarize_cv20_buffer(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Use actual paired replays; lower turnover is required in every fold."""
    primary = {r["fold"]: r for r in results if r["comparison"] == "top50" and r["cost_multiplier"] == 1}
    baseline = {r["fold"]: r for r in results if r["comparison"] == "cv20_unbuffered" and r["cost_multiplier"] == 1}
    stress = {r["fold"]: r for r in results if r["comparison"] == "top50" and r["cost_multiplier"] == 2}
    if not primary or primary.keys() != baseline.keys() or primary.keys() != stress.keys():
        raise ValueError("B28 requires complete paired and stress replays")
    one = math.prod(1 + r["total_return"] for r in primary.values()) - 1
    base = math.prod(1 + r["total_return"] for r in baseline.values()) - 1
    two = math.prod(1 + r["total_return"] for r in stress.values()) - 1
    lower = all(primary[f]["annualized_one_way_turnover"] < baseline[f]["annualized_one_way_turnover"] for f in primary)
    return {"comparison": "cv20_unbuffered", "excess_return_1x": one - base,
            "net_return_1x": one, "baseline_return_1x": base, "net_return_2x": two,
            "lower_turnover_every_fold": lower, "passed": one > base and two > 0 and lower}
