"""Three fixed liquidity co-movement proxies, not calibrated LCAPM betas.

Only contemporaneous monthly observations enter trailing exposures. Predictive
labels, transaction costs and admission do not belong in this signal kernel.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl

SIGNALS = ("liquidity_commonality_60m", "return_market_illiquidity_60m",
           "illiquidity_market_return_60m")
CONTROLS = ("liquidity_log_level_60m", "liquidity_logchange_vol_60m",
            "liquidity_return_vol_60m", "liquidity_market_beta_60m")
WINDOW = 60
MIN_MONTHS = 48
MIN_MEMBERS = 100
MIN_COVERAGE = 0.90
KEYS = ["symbol", "trade_date"]
SCHEMA = {"symbol": pl.String, "trade_date": pl.Date, "effective_date": pl.Date,
          "window_start": pl.Date, "window_end": pl.Date,
          **dict.fromkeys((*SIGNALS, *CONTROLS), pl.Float64),
          "joint_months": pl.Int64, "current_reference_members_ex_self": pl.Int64,
          "current_valid_members_ex_self": pl.Int64,
          "current_coverage_ex_self": pl.Float64, "status": pl.String}
MARKET_SCHEMA = {"trade_date": pl.Date, "reference_members": pl.Int64,
                 "valid_members": pl.Int64, "coverage": pl.Float64,
                 "mean_log_illiquidity_change": pl.Float64,
                 "mean_return": pl.Float64, "status": pl.String}


def _month(day: dt.date) -> int:
    return day.year * 12 + day.month - 1


def _calendar(sessions: tuple[dt.date, ...]) -> tuple[dt.date, ...]:
    if not sessions or any(type(d) is not dt.date for d in sessions):
        raise ValueError("sessions must contain dates")
    if sessions != tuple(sorted(set(sessions))):
        raise ValueError("sessions must be unique and increasing")
    ends = tuple(a for a, b in zip(sessions, sessions[1:]) if _month(a) != _month(b))
    if not ends or any(_month(b) - _month(a) != 1 for a, b in zip(ends, ends[1:])):
        raise ValueError("calendar must prove completed consecutive months")
    return ends


def _validate(monthly: pl.DataFrame, ends: tuple[dt.date, ...]) -> None:
    required = [*KEYS, "illiquidity", "monthly_return"]
    if not set(required) <= set(monthly.columns):
        raise ValueError("missing monthly input columns")
    if monthly.schema["symbol"] != pl.String or monthly.schema["trade_date"] != pl.Date:
        raise ValueError("expected String and Date input keys")
    if any(not monthly.schema[c].is_numeric() for c in required[2:]):
        raise ValueError("monthly observations must be numeric")
    if monthly.select(pl.any_horizontal(pl.col(c).is_null() for c in KEYS).any()).item():
        raise ValueError("null input keys")
    if monthly.select(KEYS).is_duplicated().any() or monthly.filter(pl.col("symbol") == "").height:
        raise ValueError("duplicate or empty input keys")
    if not set(monthly["trade_date"].to_list()) <= set(ends):
        raise ValueError("inputs must use completed exchange month ends")
    if monthly.filter(~pl.col("symbol").str.ends_with(".SH") &
                      ~pl.col("symbol").str.ends_with(".SZ")).height:
        raise ValueError("market cohort requires Shanghai/Shenzhen stock symbols")


def _matrix(monthly: pl.DataFrame, ends: tuple[dt.date, ...], name: str,
            symbols: list[str]) -> np.ndarray:
    wide = monthly.pivot(on="trade_date", index="symbol", values=name).sort("symbol")
    empty = np.full(len(symbols), np.nan)
    return np.column_stack([wide[str(d)].to_numpy().astype(float) if str(d) in wide.columns
                            else empty for d in ends])


def _centered(values: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    count = mask.sum(axis=1)
    mean = np.where(mask, values, 0).sum(axis=1) / np.maximum(count, 1)
    centered = np.where(mask, values - mean[:, None], 0)
    return mean, centered


def compute_liquidity_comovement(monthly: pl.DataFrame, *,
                                sessions: tuple[dt.date, ...],
                                signal_dates: tuple[dt.date, ...]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return fixed-family signals/controls and actual market coverage diagnostics.

    Market formation uses prior-month positive finite Amihud observations. Each
    month's equal-weight proxy requires a joint observed cohort. Missing members
    remain in the reference denominator. The target is excluded separately at
    every historical month; its absence is never interpreted as a zero return.
    """
    ends = _calendar(sessions)
    _validate(monthly, ends)
    if not signal_dates or signal_dates != tuple(sorted(set(signal_dates))) or not set(signal_dates) <= set(ends):
        raise ValueError("signals must be increasing completed month ends")
    if monthly.is_empty():
        return pl.DataFrame(schema=SCHEMA), pl.DataFrame(schema=MARKET_SCHEMA)
    symbols = monthly["symbol"].unique().sort().to_list()
    # Retain every calendar month, including months absent from the input table.
    ends = tuple(d for d in ends if min(monthly["trade_date"].min(), signal_dates[0]) <= d <= signal_dates[-1])
    illiq = _matrix(monthly, ends, "illiquidity", symbols)
    returns = _matrix(monthly, ends, "monthly_return", symbols)
    valid_level = np.isfinite(illiq) & (illiq > 0)
    level = np.log(np.where(valid_level, illiq, np.nan))
    previous = np.column_stack([np.full(len(symbols), np.nan), level[:, :-1]])
    change = level - previous
    formation = np.isfinite(previous)
    valid_return = np.isfinite(returns) & (returns >= -1)
    joint = formation & np.isfinite(change) & valid_return
    counts = joint.sum(axis=0)
    reference = formation.sum(axis=0)
    sum_change = np.where(joint, change, 0).sum(axis=0)
    sum_return = np.where(joint, returns, 0).sum(axis=0)
    coverage = counts / np.maximum(reference, 1)
    market_ok = (counts >= MIN_MEMBERS) & (coverage >= MIN_COVERAGE)
    market = pl.DataFrame({"trade_date": ends, "reference_members": reference,
        "valid_members": counts, "coverage": np.where(reference > 0, coverage, np.nan),
        "mean_log_illiquidity_change": np.where(market_ok, sum_change / np.maximum(counts, 1), np.nan),
        "mean_return": np.where(market_ok, sum_return / np.maximum(counts, 1), np.nan),
        "status": np.where(market_ok, "ok", "insufficient_market_coverage")}, schema=MARKET_SCHEMA).fill_nan(None)
    # Leave one out before coverage checks and before trailing estimation.
    ref_ex = reference - formation.astype(int)
    n_ex = counts - joint.astype(int)
    coverage_ex = n_ex / np.maximum(ref_ex, 1)
    market_ex_ok = (n_ex >= MIN_MEMBERS) & (coverage_ex >= MIN_COVERAGE)
    change_ex = (sum_change - np.where(joint, change, 0)) / np.maximum(n_ex, 1)
    return_ex = (sum_return - np.where(joint, returns, 0)) / np.maximum(n_ex, 1)
    usable = joint & market_ex_ok & np.isfinite(change_ex) & np.isfinite(return_ex)
    results = []
    for signal in signal_dates:
        end = ends.index(signal)
        start = max(0, end - WINDOW + 1)
        sl = slice(start, end + 1)
        mask = usable[:, sl]
        n = mask.sum(axis=1)
        full_span = end >= WINDOW - 1
        _, own_dl = _centered(change[:, sl], mask)
        _, market_dl = _centered(change_ex[:, sl], mask)
        _, own_r = _centered(returns[:, sl], mask)
        _, market_r = _centered(return_ex[:, sl], mask)
        mean_level, _ = _centered(level[:, sl], mask)
        with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
            var_dl = (market_dl * market_dl).sum(axis=1)
            var_r = (market_r * market_r).sum(axis=1)
            beta_ll = (own_dl * market_dl).sum(axis=1) / var_dl
            beta_rl = (own_r * market_dl).sum(axis=1) / var_dl
            beta_lr = (own_dl * market_r).sum(axis=1) / var_r
            beta_rr = (own_r * market_r).sum(axis=1) / var_r
            own_dl_vol = np.sqrt((own_dl * own_dl).sum(axis=1) / np.maximum(n - 1, 1))
            own_r_vol = np.sqrt((own_r * own_r).sum(axis=1) / np.maximum(n - 1, 1))
        values = np.column_stack([beta_ll, beta_rl, beta_lr, mean_level, own_dl_vol, own_r_vol, beta_rr])
        # Numerically constant predictors must stay undefined, not become huge slopes.
        tol = 64 * np.finfo(float).eps
        scale_dl = np.where(mask, np.abs(change_ex[:, sl]), 0).max(axis=1)
        scale_r = np.where(mask, np.abs(return_ex[:, sl]), 0).max(axis=1)
        varies = (var_dl > n * (tol * scale_dl) ** 2) & (var_r > n * (tol * scale_r) ** 2)
        numeric = varies & np.isfinite(values).all(axis=1)
        ok = full_span & (n >= MIN_MONTHS) & usable[:, end] & numeric
        status = np.where(~np.full(len(symbols), full_span), "insufficient_history",
                 np.where(~usable[:, end], "current_observation_unavailable",
                 np.where(n < MIN_MONTHS, "insufficient_joint_months",
                 np.where(~numeric, "degenerate_or_nonfinite_window", "ok"))))
        data = {"symbol": symbols, "trade_date": [signal] * len(symbols),
                "effective_date": [sessions[sessions.index(signal) + 1]] * len(symbols),
                "window_start": [ends[start]] * len(symbols), "window_end": [signal] * len(symbols),
                **{name: np.where(ok, values[:, i], np.nan) for i, name in enumerate((*SIGNALS, *CONTROLS))},
                "joint_months": n, "current_reference_members_ex_self": ref_ex[:, end],
                "current_valid_members_ex_self": n_ex[:, end],
                "current_coverage_ex_self": np.where(ref_ex[:, end] > 0, coverage_ex[:, end], np.nan),
                "status": status}
        results.append(pl.DataFrame(data, schema=SCHEMA).fill_nan(None))
    return pl.concat(results).sort("trade_date", "symbol"), market
