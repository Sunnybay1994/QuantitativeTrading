"""Evaluate a factor year using the fixed battery preprocessing and labels."""
import datetime as dt
from dataclasses import dataclass

import numpy as np
import polars as pl

from quant.research.factor_battery_groups import assign_groups, group_returns, persistence, summarize_groups
from quant.research.factor_battery_statistics import (
    monthly_ic_summary, preprocess_cross_section, rank_ic_by_date, session_ic_summary,
)


@dataclass
class FactorYearStatistics:
    daily_ic: pl.DataFrame
    monthly_ic: pl.DataFrame
    monthly_groups: pl.DataFrame
    monthly_scores: pl.DataFrame


def evaluate_factor_year(*, universe: pl.DataFrame, values: pl.DataFrame, daily_labels: pl.DataFrame,
                         monthly_labels: pl.DataFrame, direction: int, settings: dict) -> FactorYearStatistics:
    """Scores use signal-date inputs; future returns are joined only afterwards."""
    daily_dates = tuple(universe["trade_date"].unique().sort().to_list())
    monthly_dates = tuple(monthly_labels["trade_date"].unique().sort().to_list())
    keys = ["symbol", "trade_date"]
    panel = universe.filter(pl.col("eligible")).select(*keys,"total_market_value","industry_l1").join(
        values.select(*keys, "value"),on=keys,how="left",validate="1:1")
    frames = []
    variants = settings["variants"]
    if direction not in (-1,1) or not variants or set(variants)-{"raw","size_industry_neutral"}:
        raise ValueError("Unknown battery direction or score variant")
    preprocessing = settings["preprocessing"]
    for section in panel.partition_by("trade_date"):
        scores = []
        size_values = section["total_market_value"].to_numpy()
        size = np.log(np.where(size_values > 0, size_values, np.nan))
        for variant in variants:
            y = preprocess_cross_section(section["value"].to_numpy()*direction, size,
                section["industry_l1"].to_numpy(),neutralize=variant == "size_industry_neutral",
                mad_multiplier=preprocessing["mad_multiplier"],mad_normal_scale=preprocessing["mad_normal_scale"])
            scores.append(pl.Series(variant,y).fill_nan(None))
        frames.append(section.select(keys).with_columns(scores))
    scored = (pl.concat(frames) if frames else pl.DataFrame(schema={"symbol":pl.String,"trade_date":pl.Date,
        **{variant:pl.Float64 for variant in variants}}))
    daily = scored.join(daily_labels,on=keys,how="left",validate="1:1")
    monthly = scored.filter(pl.col("trade_date").is_in(monthly_dates)).join(monthly_labels,on=keys,
        how="left",validate="1:1")
    daily_frames, monthly_frames, group_frames = [], [], []
    for variant in variants:
        kwargs = dict(score=variant,minimum_symbols=settings["minimum_symbols"],
            minimum_paired_coverage=settings["minimum_paired_coverage"])
        for horizon in settings["decay_sessions"]:
            ic = rank_ic_by_date(daily,label=f"label_{horizon}",**kwargs)
            daily_frames.append(_pad_dates(ic,daily_dates).with_columns(
                pl.lit(variant).alias("variant"),pl.lit(horizon).alias("horizon")))
        ic = rank_ic_by_date(monthly,label="label_rebalance",**kwargs)
        monthly_frames.append(_pad_dates(ic,monthly_dates).with_columns(pl.lit(variant).alias("variant")))
        if monthly_dates:
            cohort = assign_groups(monthly,score=variant,groups=settings["groups"],minimum_symbols=settings["minimum_symbols"])
            group_frames.append(group_returns(cohort,monthly_labels,label="label_rebalance",
                signal_dates=monthly_dates,groups=settings["groups"],
                minimum_paired_coverage=settings["minimum_paired_coverage"]).with_columns(pl.lit(variant).alias("variant")))
    empty_groups = pl.DataFrame(schema={"trade_date":pl.Date,"group":pl.Int64,"members":pl.UInt32,
        "paired":pl.UInt32,"mean_return":pl.Float64,"paired_coverage":pl.Float64,"variant":pl.String})
    return FactorYearStatistics(pl.concat(daily_frames),pl.concat(monthly_frames),
        pl.concat(group_frames) if group_frames else empty_groups,
        scored.filter(pl.col("trade_date").is_in(monthly_dates)))


def summarize_factor_statistics(parts: list[FactorYearStatistics], *, sessions: tuple[dt.date,...],
                                settings: dict) -> tuple[list[dict], pl.DataFrame]:
    """Join years before persistence and HAC, preserving year-boundary transitions."""
    daily = pl.concat([p.daily_ic for p in parts])
    monthly = pl.concat([p.monthly_ic for p in parts])
    groups = pl.concat([p.monthly_groups for p in parts])
    scores = pl.concat([p.monthly_scores for p in parts])
    signal_dates = tuple(monthly["trade_date"].unique().sort().to_list())
    rows, persistence_frames = [], []
    for variant in settings["variants"]:
        m = monthly.filter(pl.col("variant") == variant).sort("trade_date")
        summary = monthly_ic_summary(m["trade_date"].to_list(),m["rank_ic"].to_list(),
            lag=settings["monthly_newey_west_lag"],minimum_months_per_year=settings["minimum_months_per_year"])
        valid_months = m.filter(pl.col("rank_ic").is_not_null())
        annual = m.with_columns(pl.col("trade_date").dt.year().alias("year")).group_by("year").agg(
            pl.col("rank_ic").count().alias("months"),pl.col("rank_ic").mean().alias("mean_ic")).sort("year")
        decay = {}
        for horizon in settings["decay_sessions"]:
            d = daily.filter((pl.col("variant") == variant) & (pl.col("horizon") == horizon)).sort("trade_date")
            decay[str(horizon)] = session_ic_summary(d["trade_date"].to_list(),d["rank_ic"].to_list(),sessions=sessions,
                lag=settings["daily_20_session_newey_west_lag"] if horizon == 20 else horizon)
        cohort = assign_groups(scores,score=variant,groups=settings["groups"],minimum_symbols=settings["minimum_symbols"])
        p = persistence(cohort,signal_dates=signal_dates,groups=settings["groups"],minimum_symbols=settings["minimum_symbols"])
        persistence_frames.append(p.with_columns(pl.lit(variant).alias("variant")))
        rows.append({"variant":variant,**summary,"decay":decay,
            "first_valid_month":str(valid_months["trade_date"].min()) if valid_months.height else None,
            "last_valid_month":str(valid_months["trade_date"].max()) if valid_months.height else None,
            "median_paired_stocks":valid_months["paired_count"].median(),"annual_ic":annual.to_dicts(),
            "group_statistics":summarize_groups(groups.filter(pl.col("variant") == variant),groups=settings["groups"]),
            "mean_monthly_rank_autocorrelation":p["rank_autocorrelation"].mean(),
            "mean_top_target_turnover":p["top_target_turnover"].mean()})
    return rows,pl.concat(persistence_frames)


def _pad_dates(frame: pl.DataFrame, dates: tuple[dt.date,...]) -> pl.DataFrame:
    return pl.DataFrame({"trade_date":dates},schema={"trade_date":pl.Date}).join(
        frame,on="trade_date",how="left",validate="1:1").with_columns(
            pl.col("signal_count","paired_count").fill_null(0),pl.col("paired_coverage").fill_null(0)).sort("trade_date")
