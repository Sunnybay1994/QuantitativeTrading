"""Same-support P7 incremental IC diagnostics; returns never enter the regression."""
from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl

from quant.factors.forecast_text_score import DIMENSIONS
from quant.research.factor_battery_statistics import monthly_ic_summary, session_ic_summary

CONTROLS = ("forecast_p_change_midpoint", "pit_sue8", "total_market_value")


def residualize_text(text: np.ndarray, midpoint: np.ndarray, sue: np.ndarray,
                     market_value: np.ndarray, industry: np.ndarray) -> tuple[np.ndarray, int]:
    """OLS projection using only contemporaneous explanatory inputs; no return argument."""
    if not all(len(x) == len(text) for x in (midpoint, sue, market_value, industry)):
        raise ValueError("Regression inputs must align")
    if (not all(np.isfinite(x).all() for x in (text, midpoint, sue, market_value))
            or not (market_value > 0).all()
            or not all(isinstance(x, str) and bool(x.strip()) for x in industry)):
        raise ValueError("Regression requires complete finite controls")
    columns = [np.ones(len(text))]
    for raw in (midpoint, sue, np.log(market_value)):
        scale = np.std(raw)
        if scale > 1e-12:
            columns.append((raw - np.mean(raw)) / scale)
    levels = np.unique(industry)
    columns.extend((industry == level).astype(float) for level in levels[1:])
    design = np.column_stack(columns)
    coefficients, _, rank, _ = np.linalg.lstsq(design, text, rcond=None)
    residual = text - design @ coefficients
    if len(text) <= rank or np.std(residual) <= 1e-12 * max(1., float(np.std(text))):
        residual = np.full(len(text), np.nan)
    return residual, int(rank)


def _ic(score: np.ndarray, returns: np.ndarray) -> float | None:
    if len(score) < 2 or not np.isfinite(score).all() or not np.isfinite(returns).all():
        return None
    value = pl.DataFrame({"score": score, "returns": returns}).select(
        pl.corr(pl.col("score").rank("average"), pl.col("returns").rank("average"))
    ).item()
    return float(value) if value is not None and np.isfinite(value) else None


def diagnose_sections(panel: pl.DataFrame, *, label: str, frequency: str,
                      settings: dict) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Every comparator uses the identical text/control/return intersection per date."""
    required = {"symbol", "trade_date", "eligible", "industry_l1", label, *CONTROLS,
                *[f"text_{name}" for name in DIMENSIONS]}
    if not required.issubset(panel.columns) or panel.select("symbol", "trade_date").is_duplicated().any():
        raise ValueError("Missing columns or duplicate symbol-date keys")
    rows, support = [], []
    for section in panel.sort("trade_date", "symbol").partition_by("trade_date"):
        date = section["trade_date"][0]
        eligible = section.filter(pl.col("eligible").fill_null(False))
        controls = pl.all_horizontal(*[pl.col(c).is_not_null() & pl.col(c).is_finite() for c in CONTROLS])
        controls &= (pl.col("total_market_value") > 0) & pl.col("industry_l1").is_not_null()
        controls &= pl.col("industry_l1").str.strip_chars() != ""
        controls_count = eligible.filter(controls).height
        for name, direction in zip(DIMENSIONS, (1, -1, -1), strict=True):
            factor = f"text_{name}"
            text_valid = pl.col(factor).is_not_null() & pl.col(factor).is_finite()
            text_count = eligible.filter(text_valid).height
            input_common = eligible.filter(text_valid & controls)
            common = input_common.filter(pl.col(label).is_not_null() & pl.col(label).is_finite())
            count = common.height
            paired_coverage = count / input_common.height if input_common.height else 0.
            sufficient = count >= settings["minimum_symbols"] and (
                paired_coverage >= settings["minimum_paired_coverage"])
            residual = np.full(count, np.nan)
            rank = None
            text = common[factor].to_numpy() * direction
            if sufficient:
                residual, rank = residualize_text(text, common[CONTROLS[0]].to_numpy(),
                    common[CONTROLS[1]].to_numpy(), common[CONTROLS[2]].to_numpy(),
                    common["industry_l1"].to_numpy())
            values = {"text": text, "forecast_midpoint": common[CONTROLS[0]].to_numpy(),
                      "pit_sue8": common[CONTROLS[1]].to_numpy(), "residual_text": residual}
            observed_returns = common[label].to_numpy()
            for comparator, value in values.items():
                rows.append({"factor": factor, "trade_date": date, "frequency": frequency,
                    "comparator": comparator, "universe_count": eligible.height,
                    "text_count": text_count, "controls_count": controls_count,
                    "forecast_count": eligible.filter(pl.col(CONTROLS[0]).is_finite()).height,
                    "sue_count": eligible.filter(pl.col(CONTROLS[1]).is_finite()).height,
                    "input_common_count": input_common.height, "common_count": count,
                    "text_complete_case_fraction": count / text_count if text_count else 0.,
                    "label_paired_coverage": paired_coverage, "regression_rank": rank,
                    "rank_ic": _ic(value, observed_returns) if sufficient else None})
            if count:
                support.append(common.select("symbol", "trade_date", *CONTROLS, "industry_l1",
                    pl.col(label).alias("next_open_label")).with_columns(
                    pl.lit(factor).alias("factor"), pl.lit(frequency).alias("frequency"),
                    pl.Series("directed_text", text), pl.Series("residual_text", residual).fill_nan(None)))
    row_schema = {"factor": pl.String, "trade_date": pl.Date, "frequency": pl.String,
        "comparator": pl.String, "universe_count": pl.Int64, "text_count": pl.Int64,
        "controls_count": pl.Int64, "forecast_count": pl.Int64, "sue_count": pl.Int64,
        "input_common_count": pl.Int64, "common_count": pl.Int64,
        "text_complete_case_fraction": pl.Float64, "label_paired_coverage": pl.Float64,
        "regression_rank": pl.Int64, "rank_ic": pl.Float64}
    support_schema = {"symbol": pl.String, "trade_date": pl.Date,
        **{c: pl.Float64 for c in CONTROLS}, "industry_l1": pl.String, "next_open_label": pl.Float64,
        "factor": pl.String, "frequency": pl.String, "directed_text": pl.Float64,
        "residual_text": pl.Float64}
    return pl.from_dicts(rows, schema=row_schema), (
        pl.concat(support, how="vertical_relaxed").cast(pl.Schema(support_schema)) if support
        else pl.DataFrame(schema=support_schema))


def summarize_incremental(points: pl.DataFrame, *, sessions: tuple[dt.date, ...],
                          settings: dict, design: dict) -> list[dict]:
    rows = []
    ranges = {"full": (design["start"], design["end"]),
              "train": (design["start"], design["time_slices"]["train_end"]),
              "validation": (design["time_slices"]["train_end"] + dt.timedelta(days=1),
                             design["time_slices"]["validation_end"]),
              "test": (design["time_slices"]["validation_end"] + dt.timedelta(days=1), design["end"])}
    for group in points.partition_by("factor", "frequency", "comparator"):
        for split, (start, end) in ranges.items():
            part = group.filter(pl.col("trade_date").is_between(start, end)).sort("trade_date")
            dates, values = part["trade_date"].to_list(), part["rank_ic"].to_list()
            frequency = group["frequency"][0]
            stats = (monthly_ic_summary(dates, values, lag=settings["monthly_newey_west_lag"],
                        minimum_months_per_year=settings["minimum_months_per_year"])
                     if frequency == "monthly" else session_ic_summary(dates, values, sessions=sessions,
                        lag=settings["daily_20_session_newey_west_lag"]))
            rows.append({"factor": group["factor"][0], "frequency": frequency,
                "comparator": group["comparator"][0], "split": split, **stats,
                "median_common_symbols": part["common_count"].median(),
                "mean_text_complete_case_fraction": part["text_complete_case_fraction"].mean(),
                "existing_minimum_months": settings["admission"]["minimum_months"],
                "use": "incremental_diagnostic_only"})
    return rows
