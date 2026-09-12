"""Pure descriptive health statistics on raw factor values and past-only references."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime as dt
import math
from typing import Any

import numpy as np
import polars as pl


@dataclass(frozen=True)
class HealthParameters:
    minimum_symbols: int = 100
    minimum_reference_months: int = 12
    reference_bins: int = 10
    mad_multiplier: float = 3.0
    mad_normal_scale: float = 1.4826
    psi_smoothing: float = 0.5

    def __post_init__(self) -> None:
        for name in ("minimum_symbols", "minimum_reference_months", "reference_bins"):
            value = getattr(self, name)
            if type(value) is not int or value < (2 if name != "minimum_reference_months" else 1):
                raise ValueError(f"Invalid health parameter: {name}")
        for name in ("mad_multiplier", "mad_normal_scale", "psi_smoothing"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid health parameter: {name}")


def _validate_frame(frame: pl.DataFrame, *, as_of: dt.date, reference: bool) -> None:
    required = {"symbol", "trade_date", "value"}
    if not reference:
        required |= {"industry_l1", "total_market_value"}
    if not required <= set(frame.columns):
        raise ValueError("Factor health input is missing required columns")
    if (frame.schema["symbol"] != pl.String or frame.schema["trade_date"] != pl.Date
            or frame.select(pl.any_horizontal(pl.col("symbol", "trade_date").is_null()).any()).item()
            or frame.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item()):
        raise ValueError("Factor health input requires unique non-null symbol/date keys")
    dtype = frame.schema["value"]
    if dtype != pl.Null and not dtype.is_numeric():
        raise ValueError("Factor health value must be numeric")
    invalid_date = pl.col("trade_date") >= as_of if reference else pl.col("trade_date") != as_of
    if frame.filter(invalid_date).height:
        raise ValueError("Reference dates must be strictly past; current dates must equal as_of")
    if not reference:
        size_type = frame.schema["total_market_value"]
        if size_type != pl.Null and not size_type.is_numeric():
            raise ValueError("Factor health market value must be numeric")
        if frame.schema["industry_l1"] not in (pl.String, pl.Null):
            raise ValueError("Factor health industry must be a string or null")


def _counts(frame: pl.DataFrame) -> tuple[dict[str, Any], np.ndarray]:
    series = frame["value"].cast(pl.Float64)
    array = series.to_numpy()
    null = series.null_count()
    nan = int(np.isnan(array).sum()) - null
    positive_inf, negative_inf = int(np.isposinf(array).sum()), int(np.isneginf(array).sum())
    finite = array[np.isfinite(array)]
    total = len(array)
    nonfinite = nan + positive_inf + negative_inf
    counts: dict[str, Any] = {"total": total, "finite": len(finite), "null": null, "nan": nan,
        "positive_inf": positive_inf, "negative_inf": negative_inf,
        "nonfinite": nonfinite, "missing_or_nonfinite": null + nonfinite}
    for name in ("null", "nan", "nonfinite", "missing_or_nonfinite"):
        counts[f"{name}_rate"] = counts[name] / total if total else None
    return counts, finite


def _distribution(values: np.ndarray, parameters: HealthParameters) -> dict[str, Any]:
    result: dict[str, Any] = {name: None for name in (
        "mean", "std", "p01", "p25", "median", "p75", "p99", "skewness", "excess_kurtosis")}
    n = len(values)
    result.update(n=n, reason=None, skewness_reason=None, excess_kurtosis_reason=None)
    if not n:
        result.update(reason="no_finite_values", skewness_reason="no_finite_values",
                      excess_kurtosis_reason="no_finite_values")
        return result
    quantiles = np.quantile(values, [.01, .25, .5, .75, .99])
    result.update(zip(("p01", "p25", "median", "p75", "p99"), quantiles.tolist(), strict=True))
    mean, std = float(np.mean(values)), float(np.std(values, ddof=0))
    result.update(mean=mean, std=std)
    reason = ("numeric_overflow" if not math.isfinite(mean) or not math.isfinite(std)
              or not np.isfinite(quantiles).all() else
              "insufficient_finite_samples" if n < parameters.minimum_symbols else
              "zero_variance" if std == 0 else None)
    result["reason"] = reason
    result["skewness_reason"] = reason or ("insufficient_finite_samples" if n < 3 else None)
    result["excess_kurtosis_reason"] = reason or ("insufficient_finite_samples" if n < 4 else None)
    if not result["skewness_reason"]:
        result["skewness"] = float(np.mean(((values - mean) / std) ** 3))
    if not result["excess_kurtosis_reason"]:
        result["excess_kurtosis"] = float(np.mean(((values - mean) / std) ** 4) - 3)
    return result


def _mad(values: np.ndarray, parameters: HealthParameters) -> dict[str, Any]:
    result: dict[str, Any] = {"n": len(values), "median": None, "mad": None,
        "lower": None, "upper": None, "clipped_n": None, "clipped_fraction": None, "reason": None}
    if len(values) < parameters.minimum_symbols:
        result["reason"] = "insufficient_finite_samples"
        return result
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    result.update(median=median, mad=mad)
    if mad == 0:
        result["reason"] = "zero_mad_skip"
        return result
    radius = parameters.mad_multiplier * parameters.mad_normal_scale * mad
    lower, upper = median - radius, median + radius
    if not math.isfinite(lower) or not math.isfinite(upper):
        result["reason"] = "numeric_overflow"
        return result
    clipped = int(((values < lower) | (values > upper)).sum())
    result.update(lower=lower, upper=upper, clipped_n=clipped, clipped_fraction=clipped / len(values))
    return result


def _controls(current: pl.DataFrame, parameters: HealthParameters) -> dict[str, Any]:
    raw = current["value"].cast(pl.Float64).to_numpy()
    finite = np.isfinite(raw)
    size = current["total_market_value"].cast(pl.Float64).to_numpy()
    valid_size = np.isfinite(size) & (size > 0)
    pair = finite & valid_size
    size_result: dict[str, Any] = {"paired_n": int(pair.sum()),
        "missing_control_n": int((finite & ~valid_size).sum()), "spearman": None, "reason": None}
    if pair.sum() < parameters.minimum_symbols:
        size_result["reason"] = "insufficient_paired_samples"
    elif np.ptp(raw[pair]) == 0:
        size_result["reason"] = "value_zero_variance"
    elif np.ptp(size[pair]) == 0:
        size_result["reason"] = "size_zero_variance"
    else:
        value_rank = pl.Series(raw[pair]).rank(method="average").to_numpy()
        size_rank = pl.Series(np.log(size[pair])).rank(method="average").to_numpy()
        if np.ptp(size_rank) == 0:
            size_result["reason"] = "size_zero_variance"
        else:
            correlation = float(np.corrcoef(value_rank, size_rank)[0, 1])
            if math.isfinite(correlation):
                size_result["spearman"] = correlation
            else:
                size_result["reason"] = "numeric_overflow"
    industry = current["industry_l1"].to_list()
    valid_industry = np.array([isinstance(x, str) and bool(x) for x in industry], dtype=bool)
    pair = finite & valid_industry
    industries = np.array(industry, dtype=object)[pair]
    y = raw[pair]
    levels = sorted(set(industries))
    industry_result: dict[str, Any] = {"paired_n": int(pair.sum()),
        "missing_control_n": int((finite & ~valid_industry).sum()), "industry_count": len(levels),
        "eta_squared": None, "max_absolute_dummy_pearson": None,
        "max_dummy_industry": None, "max_dummy_signed_pearson": None, "reason": None}
    if len(y) < parameters.minimum_symbols:
        industry_result["reason"] = "insufficient_paired_samples"
    elif np.ptp(y) == 0:
        industry_result["reason"] = "value_zero_variance"
    elif len(levels) < 2:
        industry_result["reason"] = "only_one_industry"
    else:
        mean, std = float(np.mean(y)), float(np.std(y, ddof=0))
        total_ss = float(np.sum((y - mean) ** 2))
        if not all(math.isfinite(number) for number in (mean, std, total_ss)):
            industry_result["reason"] = "numeric_overflow"
            return {"size": size_result, "industry": industry_result}
        if std == 0 or total_ss == 0:
            industry_result["reason"] = "value_zero_variance"
            return {"size": size_result, "industry": industry_result}
        between_ss, correlations = 0.0, []
        for level in levels:
            mask = industries == level
            difference = float(np.mean(y[mask]) - mean)
            if not math.isfinite(difference):
                industry_result["reason"] = "numeric_overflow"
                return {"size": size_result, "industry": industry_result}
            share = float(mask.mean())
            between_ss += int(mask.sum()) * difference ** 2
            correlations.append((level, difference * math.sqrt(share / (1 - share)) / std))
        if not math.isfinite(between_ss) or not all(math.isfinite(item[1]) for item in correlations):
            industry_result["reason"] = "numeric_overflow"
            return {"size": size_result, "industry": industry_result}
        winner = max(correlations, key=lambda item: abs(item[1]))
        industry_result.update(eta_squared=between_ss / total_ss,
            max_absolute_dummy_pearson=abs(winner[1]), max_dummy_industry=winner[0],
            max_dummy_signed_pearson=winner[1])
    return {"size": size_result, "industry": industry_result}


def _drift(current: np.ndarray, reference: np.ndarray, monthly: list[dict[str, Any]],
           parameters: HealthParameters) -> dict[str, Any]:
    total_months = len(monthly)
    finite_months = sum(row["finite_n"] > 0 for row in monthly)
    qualified_months = sum(row["finite_n"] >= parameters.minimum_symbols for row in monthly)
    result: dict[str, Any] = {"current_n": len(current), "reference_n": len(reference),
        "reference_months": qualified_months, "total_reference_months": total_months,
        "finite_reference_months": finite_months, "qualified_reference_months": qualified_months,
        "monthly_reference_counts": monthly,
        "bad_reference_months": [row["month"] for row in monthly
                                 if row["finite_n"] < parameters.minimum_symbols],
        "psi": None, "psi_reason": None,
        "bin_edges": None, "actual_bins": None, "reference_bin_counts": None,
        "current_bin_counts": None, "reference_iqr": None, "median_shift_iqr": None,
        "median_shift_reason": None, "outer_bin_bounds": "negative_and_positive_infinity"}
    reason = ("insufficient_reference_months" if total_months < parameters.minimum_reference_months else
        "insufficient_qualified_reference_months"
        if qualified_months < parameters.minimum_reference_months else
        "insufficient_current_samples" if len(current) < parameters.minimum_symbols else
        "insufficient_reference_samples" if len(reference) < parameters.minimum_symbols else None)
    if reason:
        result.update(psi_reason=reason, median_shift_reason=reason)
        return result
    q25, median, q75 = np.quantile(reference, [.25, .5, .75])
    iqr = float(q75 - q25)
    result["reference_iqr"] = iqr
    if not math.isfinite(iqr) or not math.isfinite(median):
        result["median_shift_reason"] = "numeric_overflow"
    elif iqr == 0:
        result["median_shift_reason"] = "zero_reference_iqr"
    else:
        shift = float((np.median(current) - median) / iqr)
        if math.isfinite(shift):
            result["median_shift_iqr"] = shift
        else:
            result["median_shift_reason"] = "numeric_overflow"
    if np.ptp(reference) == 0:
        result["psi_reason"] = "reference_zero_variance"
        return result
    inner = np.unique(np.quantile(reference, np.arange(1, parameters.reference_bins) / parameters.reference_bins))
    if not np.isfinite(inner).all():
        result["psi_reason"] = "numeric_overflow"
        return result
    edges = np.concatenate(([-np.inf], inner, [np.inf]))
    past_counts, _ = np.histogram(reference, bins=edges)
    current_counts, _ = np.histogram(current, bins=edges)
    smoothing = parameters.psi_smoothing
    p = (past_counts + smoothing) / (len(reference) + smoothing * len(past_counts))
    q = (current_counts + smoothing) / (len(current) + smoothing * len(current_counts))
    result.update(psi=float(np.sum((q - p) * np.log(q / p))),
        bin_edges=[None, *inner.tolist(), None], actual_bins=len(past_counts),
        reference_bin_counts=past_counts.tolist(), current_bin_counts=current_counts.tolist())
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def diagnose_factor_health(
    current: pl.DataFrame, reference: pl.DataFrame, *, as_of: dt.date,
    parameters: HealthParameters = HealthParameters(),
) -> dict[str, Any]:
    """Describe raw values; reference rows must be preselected past months by the caller.

    Rates use all current rows. Population standard deviation and moments use
    finite values. Correlations and MAD use minimum_symbols as their sample floor;
    simple finite-value means/quantiles remain visible for undersized sections.
    PSI requires minimum_reference_months with at least minimum_symbols finite
    observations in each month, pools the supplied past finite observations, uses past-only quantiles,
    and adds psi_smoothing to each histogram count before normalization.
    None endpoints in bin_edges denote negative/positive infinity, respectively.
    """
    if type(as_of) is not dt.date or not isinstance(parameters, HealthParameters):
        raise ValueError("Factor health requires a date and HealthParameters")
    _validate_frame(current, as_of=as_of, reference=False)
    _validate_frame(reference, as_of=as_of, reference=True)
    current_counts, current_values = _counts(current)
    reference_counts, reference_values = _counts(reference)
    monthly = reference.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("month"))
    monthly_counts = monthly.group_by("month").agg(pl.len().alias("total_n"),
        pl.col("value").cast(pl.Float64).is_finite().fill_null(False).sum().alias("finite_n"),
    ).sort("month").to_dicts()
    raw = current["value"].cast(pl.Float64).to_numpy()
    size = current["total_market_value"].cast(pl.Float64).to_numpy()
    valid_industry = np.array([isinstance(x, str) and bool(x)
                              for x in current["industry_l1"].to_list()], dtype=bool)
    valid_controls = np.isfinite(raw) & np.isfinite(size) & (size > 0) & valid_industry
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        result = {"as_of": as_of.isoformat(), "parameters": asdict(parameters),
            "counts": current_counts, "distribution": _distribution(current_values, parameters),
            "mad_clipping": {**_mad(current_values, parameters), "pool": "eligible_finite_raw"},
            "mad_clipping_valid_controls": {**_mad(raw[valid_controls], parameters),
                "pool": "eligible_finite_raw_with_valid_size_and_industry"},
            "controls": _controls(current, parameters),
            "drift": _drift(current_values, reference_values, monthly_counts, parameters),
            "reference_counts": reference_counts}
    return _json_safe(result)
