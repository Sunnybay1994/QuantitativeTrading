"""Fixed monthly residual-momentum definitions; no data access or portfolio decisions.

Blitz, Huij and Martens (2011), section 3 and section 5.1:
https://repub.eur.nl/pub/22252/ResidualMomentum-2011.pdf

At completed signal month m, fit 36 months m-35..m with an intercept. Rank
arithmetic residual sums divided by their sample standard deviation, excluding
the estimated intercept from the score. The main 12-1 formation is m-11..m-1
(11 observations); the alternative six-month formation plus a skip month is
m-6..m-1 (six observations), NOT a five-observation "6-1" definition.

The supplied monthly returns determine dividend/price treatment. A zero supplied
risk-free rate and locally constructed factors are explicit local adaptations,
not a claim of historical risk-free observations or literal FF replication.
"""

import datetime as dt
import math

import numpy as np
import polars as pl

REGRESSION_MONTHS = 36
MINIMUM_STANDARD_DEVIATION = 1e-12
FORMATIONS = {"12_1": 11, "6_skip1": 6}
FACTOR_COLUMNS = ("market_return", "smb_return", "hml_return")
SIGNAL_COLUMNS = (
    "residual_momentum_12_1_ff3_36", "residual_momentum_6_skip1_ff3_36",
    "raw_momentum_12_1", "raw_momentum_6_skip1",
    "vol_scaled_momentum_12_1", "vol_scaled_momentum_6_skip1",
)
OUTPUT_SCHEMA = {
    "symbol": pl.String, "trade_date": pl.Date,
    **dict.fromkeys(SIGNAL_COLUMNS, pl.Float64),
    "history_months": pl.Int64, "regression_status": pl.String,
    "residual_std_12_1": pl.Float64, "residual_std_6_skip1": pl.Float64,
}


def _validate_inputs(
    stocks: pl.DataFrame, factors: pl.DataFrame, month_ends: tuple[dt.date, ...],
    risk_free_monthly: float,
) -> None:
    if not month_ends or any(type(day) is not dt.date for day in month_ends):
        raise ValueError("month_ends must contain nonempty date values")
    month_numbers = [day.year * 12 + day.month for day in month_ends]
    if any(b - a != 1 for a, b in zip(month_numbers, month_numbers[1:])):
        raise ValueError("month_ends must be unique, increasing and calendar-month contiguous")
    if not math.isfinite(risk_free_monthly) or risk_free_monthly <= -1:
        raise ValueError("risk_free_monthly must be finite and greater than -1")
    for frame, keys, values in (
        (stocks, ["symbol", "trade_date"], ["stock_return"]),
        (factors, ["trade_date"], list(FACTOR_COLUMNS)),
    ):
        missing = set(keys + values) - set(frame.columns)
        if missing:
            raise ValueError(f"Missing monthly columns: {sorted(missing)}")
        if frame.schema["trade_date"] != pl.Date:
            raise ValueError("Monthly trade_date columns must have Date dtype")
        if frame.select(pl.any_horizontal(pl.col(k).is_null() for k in keys).any()).item():
            raise ValueError("Missing monthly observation keys")
        if frame.select(keys).is_duplicated().any():
            raise ValueError(f"Duplicate monthly keys: {keys}")
        if not set(frame["trade_date"].to_list()).issubset(month_ends):
            raise ValueError("Monthly observations must match an exact supplied month end")
        if any(not frame.schema[name].is_numeric() for name in values):
            raise ValueError("Monthly returns must have numeric dtypes")
    if stocks.schema["symbol"] != pl.String or stocks.filter(pl.col("symbol") == "").height:
        raise ValueError("Symbols must be nonempty strings")


def compute_residual_momentum(
    monthly_returns: pl.DataFrame,
    monthly_factors: pl.DataFrame,
    *,
    month_ends: tuple[dt.date, ...],
    risk_free_monthly: float = 0.0,
) -> pl.DataFrame:
    """Calculate the fixed two-signal family and four matched return controls.

    ``monthly_returns``: symbol, trade_date, stock_return (monthly simple return).
    ``monthly_factors``: trade_date, market_return, smb_return, hml_return.
    Market and stock returns are gross of the risk-free subtraction; SMB/HML are
    already long-short return spreads. Only the first two have rf subtracted.
    ``month_ends`` is the caller's actual completed exchange-month-end grid.
    Missing months never compress a regression window or receive forward fills.

    Every historically present symbol is retained on the supplied grid, including
    symbols absent at its endpoint. All six signals require the same complete,
    full-rank 36-month regression window. A zero residual variance invalidates its
    residual signal; zero stock-return variance invalidates its scaled control.
    Unscaled controls compound simple returns; residuals are summed, not compounded.
    ``history_months`` counts valid stock returns in the available trailing window.
    ``regression_status=ok`` does not assert that residual variance is nonzero.
    """
    _validate_inputs(monthly_returns, monthly_factors, month_ends, risk_free_monthly)
    if monthly_returns.is_empty():
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    dates = pl.DataFrame({"trade_date": month_ends})
    factors = dates.join(monthly_factors.select("trade_date", *FACTOR_COLUMNS),
                         on="trade_date", how="left", validate="1:1")
    predictors = factors.select(*FACTOR_COLUMNS).to_numpy().astype(float)
    factor_dates = set(monthly_factors["trade_date"])
    factor_present = np.array([day in factor_dates for day in month_ends])
    factor_valid = np.isfinite(predictors).all(axis=1) & (predictors[:, 0] >= -1)
    predictors[:, 0] -= risk_free_monthly
    design = np.column_stack((np.ones(len(month_ends)), predictors))
    output = []
    for (symbol,), group in monthly_returns.group_by("symbol"):
        joined = dates.join(group.select("trade_date", "stock_return"),
                            on="trade_date", how="left", validate="1:1")
        returns = joined["stock_return"].to_numpy().astype(float)
        stock_valid = np.isfinite(returns) & (returns >= -1)
        observed_dates = set(group["trade_date"])
        stock_present = np.array([day in observed_dates for day in month_ends])
        values = {name: np.full(len(month_ends), np.nan) for name in SIGNAL_COLUMNS}
        deviations = {name: np.full(len(month_ends), np.nan) for name in FORMATIONS}
        statuses, histories = [], []
        for end in range(1, len(month_ends) + 1):
            start = max(0, end - REGRESSION_MONTHS)
            histories.append(int(stock_valid[start:end].sum()))
            if end < REGRESSION_MONTHS:
                statuses.append("insufficient_history")
                continue
            if not stock_present[start:end].all():
                statuses.append("missing_stock_month")
                continue
            if not stock_valid[start:end].all():
                statuses.append("invalid_stock_return")
                continue
            if not factor_present[start:end].all():
                statuses.append("missing_factor_month")
                continue
            if not factor_valid[start:end].all():
                statuses.append("invalid_factor_return")
                continue
            x = design[start:end]
            y = returns[start:end] - risk_free_monthly
            coefficients, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
            if rank != 4:
                statuses.append("rank_deficient")
                continue
            residuals = y - x @ coefficients
            statuses.append("ok")
            for label, count in FORMATIONS.items():
                # Last completed month enters beta estimation but is skipped in formation.
                residual_window = residuals[-count - 1:-1]
                stock_window = returns[end - count - 1:end - 1]
                residual_std = float(np.std(residual_window, ddof=1))
                stock_std = float(np.std(stock_window, ddof=1))
                deviations[label][end - 1] = residual_std
                if residual_std > MINIMUM_STANDARD_DEVIATION:
                    values[f"residual_momentum_{label}_ff3_36"][end - 1] = (
                        float(residual_window.sum()) / residual_std)
                raw = float(np.prod(1 + stock_window) - 1)
                values[f"raw_momentum_{label}"][end - 1] = raw
                if stock_std > MINIMUM_STANDARD_DEVIATION:
                    values[f"vol_scaled_momentum_{label}"][end - 1] = raw / stock_std
        chunk = pl.DataFrame({
            "symbol": [symbol] * len(month_ends), "trade_date": month_ends, **values,
            "history_months": histories, "regression_status": statuses,
            **{f"residual_std_{label}": value for label, value in deviations.items()},
        }, schema=OUTPUT_SCHEMA).with_columns(
            *(pl.when(pl.col(name).is_finite()).then(pl.col(name)).otherwise(None)
              for name, dtype in OUTPUT_SCHEMA.items() if dtype == pl.Float64))
        output.append(chunk)
    return pl.concat(output).sort("symbol", "trade_date")
