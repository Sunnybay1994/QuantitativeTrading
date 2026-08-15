"""Point-in-time signal construction for first-batch financial quality factors."""

from __future__ import annotations

import datetime as dt
import calendar
from dataclasses import dataclass
from typing import cast

import polars as pl
from polars.exceptions import PolarsError

from quant.data.financial_clean import project_selected_financial_factor_frame
from quant.data.financial_pit import (
    FinancialDataset,
    FinancialPITSelection,
    select_financial_revisions_as_of,
)
from quant.factors.pit_quality import (
    PIT_QUALITY_ELIGIBILITY_STATUSES,
    PIT_QUALITY_FACTOR_NAMES,
    compute_pit_quality_factor_diagnostics,
)

_QUARANTINE_COLUMNS = [
    "dataset",
    "as_of",
    "symbol",
    "end_date",
    "available_date",
    "quarantine_reason",
]
_ELIGIBILITY_COLUMNS = [
    "as_of",
    "symbol",
    "factor",
    "financial_period_end",
    "status",
]
_FACTOR_DATASETS = {
    "income": PIT_QUALITY_FACTOR_NAMES,
    "balancesheet": (
        "pit_roe_ttm",
        "pit_roa_ttm",
        "pit_total_accruals_ttm",
    ),
    "cashflow": (
        "pit_cash_profit_quality_ttm",
        "pit_total_accruals_ttm",
    ),
}


@dataclass(frozen=True, slots=True)
class PITQualitySignalResult:
    """Sparse signal-date factor values and PIT conflict evidence."""

    factors: pl.DataFrame
    eligibility: pl.DataFrame
    quarantined: pl.DataFrame


def monthly_signal_sessions(
    sessions: tuple[dt.date, ...], *, start: dt.date, end: dt.date
) -> tuple[dt.date, ...]:
    """Return proven calendar-month-end exchange sessions.

    A truncated final calendar month is excluded because its last observed bar
    is not evidence that the month has ended.  Historical months are closed by
    a later month in the supplied session sequence; the final month is accepted
    only when ``end`` reaches the calendar month end.
    """
    try:
        if (
            type(sessions) is not tuple
            or not sessions
            or any(type(value) is not dt.date for value in sessions)
            or sessions != tuple(sorted(sessions))
            or len(sessions) != len(set(sessions))
            or type(start) is not dt.date
            or type(end) is not dt.date
            or end < start
        ):
            raise ValueError
        selected = [value for value in sessions if start <= value <= end]
        result: dict[tuple[int, int], dt.date] = {}
        for value in selected:
            result[(value.year, value.month)] = value
        if result:
            final_month = next(reversed(result))
            calendar_end = calendar.monthrange(end.year, end.month)[1]
            if final_month == (end.year, end.month) and end.day < calendar_end:
                result.pop(final_month)
        return tuple(result.values())
    except (TypeError, ValueError):
        pass
    raise ValueError("PIT_QUALITY_RESEARCH_INVALID") from None


def build_pit_quality_signal_values(
    *,
    income_history: pl.DataFrame,
    balance_history: pl.DataFrame,
    cash_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    """Build sparse cross-sections using only revisions known before each signal."""
    try:
        return _build(
            income_history=income_history,
            balance_history=balance_history,
            cash_history=cash_history,
            signal_dates=signal_dates,
            candidate_symbols=candidate_symbols,
        )
    except (PolarsError, TypeError, ValueError):
        pass
    raise ValueError("PIT_QUALITY_RESEARCH_INVALID") from None


def _build(
    *,
    income_history: pl.DataFrame,
    balance_history: pl.DataFrame,
    cash_history: pl.DataFrame,
    signal_dates: tuple[dt.date, ...],
    candidate_symbols: tuple[str, ...],
) -> PITQualitySignalResult:
    histories = {
        "income": income_history,
        "balancesheet": balance_history,
        "cashflow": cash_history,
    }
    if (
        any(not isinstance(frame, pl.DataFrame) for frame in histories.values())
        or type(signal_dates) is not tuple
        or not signal_dates
        or any(type(value) is not dt.date for value in signal_dates)
        or signal_dates != tuple(sorted(signal_dates))
        or len(signal_dates) != len(set(signal_dates))
        or type(candidate_symbols) is not tuple
        or not candidate_symbols
        or any(type(symbol) is not str or not symbol for symbol in candidate_symbols)
        or candidate_symbols != tuple(sorted(candidate_symbols))
        or len(candidate_symbols) != len(set(candidate_symbols))
    ):
        raise ValueError

    factor_frames: list[pl.DataFrame] = []
    eligibility_frames: list[pl.DataFrame] = []
    quarantine_frames: list[pl.DataFrame] = []
    for as_of in signal_dates:
        selections = {
            dataset: select_financial_revisions_as_of(
                frame, dataset=cast(FinancialDataset, dataset), as_of=as_of
            )
            for dataset, frame in histories.items()
        }
        for dataset, selection in selections.items():
            if not selection.quarantined.is_empty():
                quarantine_frames.append(
                    _quarantine_projection(selection.quarantined, dataset=dataset, as_of=as_of)
                )
        eligibility = _missing_eligibility(as_of=as_of, candidate_symbols=candidate_symbols)
        latest = _empty_diagnostics()
        if all(not selection.selected.is_empty() for selection in selections.values()):
            income = project_selected_financial_factor_frame(
                selections["income"].selected, dataset="income"
            )
            balance = project_selected_financial_factor_frame(
                selections["balancesheet"].selected, dataset="balancesheet"
            )
            cash = project_selected_financial_factor_frame(
                selections["cashflow"].selected, dataset="cashflow"
            )
            diagnostics = compute_pit_quality_factor_diagnostics(
                income=income,
                balance_sheet=balance,
                cash_flow=cash,
            ).filter(pl.col("report_type") == "1")
            latest = (
                diagnostics.sort(["symbol", "factor", "end_date"])
                .group_by("symbol", "factor", maintain_order=True)
                .tail(1)
                .rename({"end_date": "financial_period_end"})
                .select(
                    "symbol",
                    "factor",
                    "financial_period_end",
                    "factor_value",
                    "status",
                )
            )
            eligibility = (
                eligibility.join(
                    latest.rename(
                        {
                            "financial_period_end": "_period",
                            "status": "_status",
                        }
                    ).drop("factor_value"),
                    on=["symbol", "factor"],
                    how="left",
                    validate="1:1",
                )
                .with_columns(
                    pl.coalesce("_period", "financial_period_end").alias("financial_period_end"),
                    pl.coalesce("_status", "status").alias("status"),
                )
                .drop("_period", "_status")
            )
        conflicts = _factor_conflicts(selections)
        if not conflicts.is_empty():
            eligibility = (
                eligibility.join(
                    conflicts,
                    on=["symbol", "factor"],
                    how="left",
                    validate="1:1",
                )
                .with_columns(
                    pl.when(
                        pl.col("_conflict_end").is_not_null()
                        & (
                            pl.col("financial_period_end").is_null()
                            | (pl.col("_conflict_end") >= pl.col("financial_period_end"))
                        )
                    )
                    .then(pl.lit("QUARANTINED"))
                    .otherwise(pl.col("status"))
                    .alias("status")
                )
                .drop("_conflict_end")
            )
        eligibility_frames.append(eligibility.select(_ELIGIBILITY_COLUMNS))
        factor_frames.append(_factor_values(eligibility=eligibility, latest=latest))
    factors = (
        pl.concat(factor_frames).sort("trade_date", "symbol") if factor_frames else _empty_factors()
    )
    eligibility = (
        pl.concat(eligibility_frames).sort("as_of", "symbol", "factor")
        if eligibility_frames
        else _empty_eligibility()
    )
    quarantined = (
        pl.concat(quarantine_frames, how="diagonal_relaxed")
        .unique(maintain_order=False)
        .sort(_QUARANTINE_COLUMNS)
        if quarantine_frames
        else _empty_quarantine()
    )
    if factors.select(pl.struct("symbol", "trade_date").is_duplicated().any()).item():
        raise ValueError
    if (
        eligibility.height
        != len(signal_dates) * len(candidate_symbols) * len(PIT_QUALITY_FACTOR_NAMES)
        or eligibility.select(pl.struct("as_of", "symbol", "factor").is_duplicated().any()).item()
        or not set(eligibility.get_column("status").unique().to_list())
        <= set(PIT_QUALITY_ELIGIBILITY_STATUSES)
    ):
        raise ValueError
    return PITQualitySignalResult(
        factors=factors,
        eligibility=eligibility,
        quarantined=quarantined,
    )


def _quarantine_projection(frame: pl.DataFrame, *, dataset: str, as_of: dt.date) -> pl.DataFrame:
    symbol = "symbol" if "symbol" in frame.columns else "ts_code"
    return frame.select(
        pl.lit(dataset).alias("dataset"),
        pl.lit(as_of).alias("as_of"),
        pl.col(symbol).alias("symbol"),
        "end_date",
        "available_date",
        "quarantine_reason",
    )


def _factor_conflicts(selections: dict[str, FinancialPITSelection]) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for dataset, factors in _FACTOR_DATASETS.items():
        selection = selections[dataset]
        quarantined = selection.quarantined
        if quarantined.is_empty():
            continue
        symbol = "symbol" if "symbol" in quarantined.columns else "ts_code"
        conflicts = quarantined.filter(pl.col("quarantine_reason") == "LATEST_REVISION_CONFLICT")
        if conflicts.is_empty():
            continue
        for factor in factors:
            frames.append(
                conflicts.select(
                    pl.col(symbol).alias("symbol"),
                    pl.lit(factor).alias("factor"),
                    pl.col("end_date").alias("_conflict_end"),
                )
            )
    if not frames:
        return pl.DataFrame(
            schema={
                "symbol": pl.String(),
                "factor": pl.String(),
                "_conflict_end": pl.Date(),
            }
        )
    return (
        pl.concat(frames)
        .group_by("symbol", "factor")
        .agg(pl.col("_conflict_end").max())
        .sort("symbol", "factor")
    )


def _missing_eligibility(*, as_of: dt.date, candidate_symbols: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "as_of": [as_of] * (len(candidate_symbols) * len(PIT_QUALITY_FACTOR_NAMES)),
            "symbol": [symbol for symbol in candidate_symbols for _ in PIT_QUALITY_FACTOR_NAMES],
            "factor": list(PIT_QUALITY_FACTOR_NAMES) * len(candidate_symbols),
            "financial_period_end": [None]
            * (len(candidate_symbols) * len(PIT_QUALITY_FACTOR_NAMES)),
            "status": ["MISSING_CHAIN"] * (len(candidate_symbols) * len(PIT_QUALITY_FACTOR_NAMES)),
        },
        schema={
            "as_of": pl.Date(),
            "symbol": pl.String(),
            "factor": pl.String(),
            "financial_period_end": pl.Date(),
            "status": pl.String(),
        },
    )


def _factor_values(*, eligibility: pl.DataFrame, latest: pl.DataFrame) -> pl.DataFrame:
    values = eligibility.join(
        latest.select("symbol", "factor", "factor_value"),
        on=["symbol", "factor"],
        how="left",
        validate="1:1",
    ).with_columns(
        pl.when(pl.col("status") == "VALID")
        .then(pl.col("factor_value"))
        .otherwise(None)
        .alias("factor_value")
    )
    periods = values.group_by("as_of", "symbol").agg(pl.col("financial_period_end").max())
    wide = values.pivot(
        on="factor",
        index=["as_of", "symbol"],
        values="factor_value",
        aggregate_function=None,
        maintain_order=True,
    )
    return (
        wide.join(periods, on=["as_of", "symbol"], how="left", validate="1:1")
        .rename({"as_of": "trade_date"})
        .select(
            "symbol",
            "trade_date",
            "financial_period_end",
            *PIT_QUALITY_FACTOR_NAMES,
        )
        .sort("trade_date", "symbol")
    )


def _empty_diagnostics() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.String(),
            "factor": pl.String(),
            "financial_period_end": pl.Date(),
            "factor_value": pl.Float64(),
            "status": pl.String(),
        }
    )


def _empty_factors() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.String(),
            "trade_date": pl.Date(),
            "financial_period_end": pl.Date(),
            **{name: pl.Float64() for name in PIT_QUALITY_FACTOR_NAMES},
        }
    )


def _empty_quarantine() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "dataset": pl.String(),
            "as_of": pl.Date(),
            "symbol": pl.String(),
            "end_date": pl.Date(),
            "available_date": pl.Date(),
            "quarantine_reason": pl.String(),
        }
    )


def _empty_eligibility() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "as_of": pl.Date(),
            "symbol": pl.String(),
            "factor": pl.String(),
            "financial_period_end": pl.Date(),
            "status": pl.String(),
        }
    )


__all__ = [
    "PITQualitySignalResult",
    "build_pit_quality_signal_values",
    "monthly_signal_sessions",
]
