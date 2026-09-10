"""Cross-sectional preprocessing and calendar-aware factor battery statistics."""
import datetime as dt
import math

import numpy as np
import polars as pl

from quant.research.classic_factor_evaluation import newey_west_t_statistic


def preprocess_cross_section(
    values: np.ndarray, log_size: np.ndarray, industry: np.ndarray, *,
    neutralize: bool, mad_multiplier: float = 3.0, mad_normal_scale: float = 1.4826,
) -> np.ndarray:
    """MAD clip, optionally remove size/industry exposures, then standardize."""
    if len(values) != len(log_size) or len(values) != len(industry):
        raise ValueError("Cross-sectional controls must align with factor values")
    result = np.full(len(values), np.nan)
    valid = np.isfinite(values)
    if neutralize:
        valid &= np.isfinite(log_size) & np.array([isinstance(x, str) and bool(x) for x in industry])
    if valid.sum() < 2:
        return result
    y = values[valid].astype(float)
    center = np.median(y)
    scale = np.median(np.abs(y - center)) * mad_normal_scale
    if scale > 0:
        y = np.clip(y, center - mad_multiplier * scale, center + mad_multiplier * scale)
    reference_scale = max(1.0, float(np.std(y)))
    if neutralize:
        industries = industry[valid]
        levels = np.unique(industries)
        size = log_size[valid] - np.mean(log_size[valid])
        design = np.column_stack((np.ones(len(y)), size,
            *[(industries == level).astype(float) for level in levels[1:]]))
        y = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
    standard_deviation = float(np.std(y, ddof=0))
    if standard_deviation <= 1e-12 * reference_scale:
        return result
    result[valid] = (y - np.mean(y)) / standard_deviation
    return result


def rank_ic_by_date(
    frame: pl.DataFrame, *, score: str, label: str, minimum_symbols: int,
    minimum_paired_coverage: float,
) -> pl.DataFrame:
    """Rank only finite pairs, while retaining the original signal cohort size."""
    planned = frame.select("trade_date").unique()
    cohort = frame.filter(pl.col(score).is_not_null() & pl.col(score).is_finite())
    signals = cohort.group_by("trade_date").agg(pl.len().alias("signal_count"))
    pairs = cohort.filter(pl.col(label).is_not_null() & pl.col(label).is_finite()).with_columns(
        pl.col(score).rank("average").over("trade_date").alias("_score_rank"),
        pl.col(label).rank("average").over("trade_date").alias("_label_rank"))
    stats = pairs.group_by("trade_date").agg(pl.len().alias("paired_count"),
        pl.corr("_score_rank", "_label_rank").alias("rank_ic"))
    return (planned.join(signals, on="trade_date", how="left", validate="1:1").join(
        stats, on="trade_date", how="left", validate="1:1").with_columns(
            pl.col("signal_count").fill_null(0), pl.col("paired_count").fill_null(0),
        ).with_columns((pl.col("paired_count")/pl.col("signal_count")).fill_nan(0).alias("paired_coverage"))
        .with_columns(pl.when((pl.col("paired_count") >= minimum_symbols)
            & (pl.col("paired_coverage") >= minimum_paired_coverage) & pl.col("rank_ic").is_finite())
            .then(pl.col("rank_ic")).otherwise(None).alias("rank_ic")).sort("trade_date"))


def monthly_ic_summary(
    dates: list[dt.date], values: list[float | None], *, lag: int = 6,
    minimum_months_per_year: int = 6,
) -> dict:
    """HAC lags count calendar months, including holes in a factor's history."""
    if len(dates) != len(values) or lag < 0:
        raise ValueError("Invalid monthly IC sequence")
    indices = [d.year*12+d.month for d in dates]
    if indices != sorted(set(indices)):
        raise ValueError("Monthly IC requires one increasing observation per calendar month")
    observed = {index: float(value) for index, value in zip(indices, values, strict=True)
                if value is not None and math.isfinite(value)}
    count = len(observed)
    if count == 0:
        return {"months": 0, "mean_ic": None, "icir": None, "newey_west_t": None,
                "p_value": None, "positive_month_fraction": None,
                "yearly_positive_fraction": None, "qualified_years": 0}
    y = np.array(list(observed.values()))
    mean = float(np.mean(y))
    standard_deviation = float(np.std(y, ddof=1)) if count > 1 else 0.0
    statistic = _indexed_hac_t(observed, lag=lag)
    annual: dict[int, list[float]] = {}
    for date, value in zip(dates, values, strict=True):
        if value is not None and math.isfinite(value):
            annual.setdefault(date.year, []).append(value)
    means = [float(np.mean(v)) for v in annual.values() if len(v) >= minimum_months_per_year]
    return {"months": count, "mean_ic": mean,
        "icir": mean/standard_deviation if standard_deviation > 1e-12 else None,
        "newey_west_t": statistic,
        "p_value": math.erfc(abs(statistic)/math.sqrt(2)) if statistic is not None else None,
        "positive_month_fraction": float(np.mean(y > 0)),
        "yearly_positive_fraction": sum(v > 0 for v in means)/len(means) if means else None,
        "qualified_years": len(means)}


def session_ic_summary(dates: list[dt.date], values: list[float | None], *,
                       sessions: tuple[dt.date, ...], lag: int = 20) -> dict:
    """Summarize overlapping daily IC without compressing missing trading days."""
    if (len(dates) != len(values) or lag < 0 or dates != sorted(set(dates))
            or sessions != tuple(sorted(set(sessions))) or not set(dates) <= set(sessions)):
        raise ValueError("Invalid daily IC calendar")
    indices = {date: index for index, date in enumerate(sessions)}
    observed = {indices[date]: float(value) for date, value in zip(dates, values, strict=True)
                if value is not None and math.isfinite(value)}
    y = np.array(list(observed.values()))
    mean = float(np.mean(y)) if len(y) else None
    deviation = float(np.std(y, ddof=1)) if len(y) > 1 else 0.
    return {"sessions": len(y), "mean_ic": mean,
            "icir": mean/deviation if mean is not None and deviation > 1e-12 else None,
            "newey_west_t": _indexed_hac_t(observed, lag=lag)}


def _indexed_hac_t(observed: dict[int, float], *, lag: int) -> float | None:
    count = len(observed)
    y = np.array(list(observed.values()))
    if count < 2 or np.std(y, ddof=1) <= 1e-12:
        return None
    keys = list(observed)
    if keys[-1]-keys[0]+1 == count:
        return newey_west_t_statistic(y.tolist(), lag=min(lag, count-1))
    mean = float(np.mean(y))
    centered = {index: value-mean for index, value in observed.items()}
    long_run = sum(value*value for value in centered.values())/count
    for offset in range(1, lag+1):
        covariance = sum(value*centered.get(index-offset, 0.) for index, value in centered.items())/count
        long_run += 2*(1-offset/(lag+1))*covariance
    error = math.sqrt(max(0., long_run)/count)
    return mean/error if error > 0 else None


def benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    """Keep missing tests in the registered family size, conservatively."""
    observed = []
    for index, value in enumerate(p_values):
        if value is not None:
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Invalid p-value")
            observed.append((value, index))
    observed.sort()
    adjusted: list[float | None] = [None]*len(p_values)
    running = 1.0
    for rank in range(len(observed), 0, -1):
        value, index = observed[rank-1]
        running = min(running, value*len(p_values)/rank)
        adjusted[index] = running
    return adjusted
