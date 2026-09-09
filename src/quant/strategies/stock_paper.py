"""Fixed B32 stock factors and buffered selections; caller supplies dated inputs."""

import datetime as dt
from typing import Any

import polars as pl

from quant.factors import compute_classic_daily_factors
from quant.factors.reversal_volatility import exclude_historical_risk_names
from quant.factors.turnover_variability import compute_turnover_variability
from quant.research.classic_factor_composite import build_equal_weight_zscore_composite


def effective_stock_factors(
    *,
    bars: pl.DataFrame,
    daily_basic: pl.DataFrame,
    names: pl.DataFrame,
    sessions: tuple[dt.date, ...],
    as_of: dt.date,
    config: dict[str, Any],
) -> pl.DataFrame:
    """Keep the B25 complete-case pool; compute only after cutting future rows."""
    bars = bars.filter(pl.col("trade_date") <= as_of)
    daily_basic = daily_basic.filter(pl.col("trade_date") <= as_of)
    past_sessions = tuple(date for date in sessions if date <= as_of)
    if not past_sessions or past_sessions[-1] != as_of:
        raise ValueError("Signal date is not a completed exchange session")
    classic = compute_classic_daily_factors(bars).filter(pl.col("trade_date") == as_of)
    cv20 = compute_turnover_variability(daily_basic, sessions=past_sessions, window=20).filter(
        pl.col("trade_date") == as_of
    )
    panel = classic.join(cv20, on=["symbol", "trade_date"], how="inner", validate="1:1")
    spec = config["universe"]
    panel = panel.filter(
        (pl.col("history_rows") >= spec["minimum_history_rows"])
        & (pl.col("liquidity_20") >= spec["minimum_average_amount"])
        & pl.all_horizontal(pl.col(column).is_finite() for column in spec["same_effective_pool"])
    )
    panel = exclude_historical_risk_names(panel, names.filter(pl.col("start_date") <= as_of))
    if panel.height < max(config["signal"]["top_k"], spec["minimum_daily_symbols"]):
        raise ValueError(f"Insufficient complete effective stock pool: {as_of} ({panel.height})")
    return panel.sort("symbol")


def stock_targets(
    panel: pl.DataFrame,
    *,
    previous_targets: list[str],
    as_of: dt.date,
    execution_date: dt.date,
    account: dict[str, Any],
    top_k: int = 50,
) -> tuple[list[dict[str, Any]], pl.DataFrame]:
    if execution_date <= as_of or panel["trade_date"].unique().to_list() != [as_of]:
        raise ValueError("Targets require one past close and a later execution date")
    scored = build_equal_weight_zscore_composite(
        panel, component_directions=tuple(zip(account["components"], account["directions"]))
    )
    ranked = scored.sort("equal_zscore", "symbol", descending=[True, False]).with_row_index(
        "rank", offset=1
    )
    retained = ranked.head(account["retention_rank"]).filter(
        pl.col("symbol").is_in(previous_targets)
    )
    if retained.height > top_k:
        raise ValueError("Previous target membership exceeds the fixed number of slots")
    chosen = pl.concat(
        [
            retained,
            ranked.filter(~pl.col("symbol").is_in(retained["symbol"].implode())).head(
                top_k - retained.height
            ),
        ]
    )
    if chosen.height != top_k:
        raise ValueError("Insufficient stock targets")
    members = chosen["symbol"].to_list()
    ranked = ranked.with_columns(
        pl.col("symbol").is_in(members).alias("selected"),
        pl.col("symbol").is_in(retained["symbol"].implode()).alias("retained"),
    )
    return [
        {
            "as_of": str(as_of),
            "execution_date": str(execution_date),
            "strategy": account["name"],
            "strategy_version": "v1",
            "symbol": symbol,
            "weight": 1 / top_k,
        }
        for symbol in sorted(members)
    ], ranked
