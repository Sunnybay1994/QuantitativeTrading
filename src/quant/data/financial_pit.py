"""Point-in-time revision selection for normalized Tushare financial rows."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal, cast

import polars as pl
from polars.exceptions import PolarsError

FinancialDataset = Literal["income", "balancesheet", "cashflow", "fina_indicator"]

_STATEMENT_DATASETS = frozenset({"income", "balancesheet", "cashflow"})
_ALL_DATASETS = _STATEMENT_DATASETS | {"fina_indicator"}
_STATEMENT_REQUIRED = frozenset(
    {
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
    }
)
_INDICATOR_REQUIRED = frozenset({"ts_code", "ann_date", "end_date"})
_CLEAN_STATEMENT_REQUIRED = frozenset(
    {
        "symbol",
        "ann_date",
        "f_ann_date",
        "available_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
    }
)
_CLEAN_INDICATOR_REQUIRED = frozenset({"symbol", "ann_date", "available_date", "end_date"})
_NON_ECONOMIC_COLUMNS = frozenset(
    {
        "ts_code",
        "symbol",
        "ann_date",
        "f_ann_date",
        "available_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
        "request",
        "source",
    }
)


class FinancialPITError(ValueError):
    """Stable failure raised for an invalid PIT financial selection."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_FINANCIAL_PIT_INVALID")


@dataclass(frozen=True, slots=True)
class FinancialPITSelection:
    """Latest unambiguous rows known strictly before one signal date."""

    dataset: FinancialDataset
    as_of: dt.date
    selected: pl.DataFrame
    quarantined: pl.DataFrame


def select_financial_revisions_as_of(
    frame: pl.DataFrame, *, dataset: FinancialDataset, as_of: dt.date
) -> FinancialPITSelection:
    """Select the latest known revision without resolving economic conflicts by order."""
    try:
        return _select(frame=frame, dataset=dataset, as_of=as_of)
    except (FinancialPITError, PolarsError, TypeError, ValueError):
        pass
    raise FinancialPITError() from None


def select_pit_quality_revisions_as_of(
    frame: pl.DataFrame,
    *,
    dataset: Literal["income", "balancesheet", "cashflow"],
    as_of: dt.date,
    allowed_report_types: tuple[str, ...],
    history_quarters: int = 5,
) -> FinancialPITSelection:
    """Select the industrial-statement revision chain used by PIT quality factors."""
    try:
        if (
            type(history_quarters) is not int or not 5 <= history_quarters <= 32
            or type(allowed_report_types) is not tuple
            or not allowed_report_types
            or allowed_report_types != tuple(sorted(allowed_report_types))
            or len(allowed_report_types) != len(set(allowed_report_types))
            or any(type(value) is not str or not value.isdigit() for value in allowed_report_types)
        ):
            raise FinancialPITError()
        return _select(
            frame=frame,
            dataset=dataset,
            as_of=as_of,
            allowed_report_types=allowed_report_types,
            required_comp_type="1",
            bind_flow_chain=dataset in {"income", "cashflow"},
            history_quarters=history_quarters,
        )
    except (FinancialPITError, PolarsError, TypeError, ValueError):
        pass
    raise FinancialPITError() from None


def _select(
    *,
    frame: pl.DataFrame,
    dataset: FinancialDataset,
    as_of: dt.date,
    allowed_report_types: tuple[str, ...] | None = None,
    required_comp_type: str | None = None,
    bind_flow_chain: bool = False,
    history_quarters: int = 5,
) -> FinancialPITSelection:
    if (
        not isinstance(frame, pl.DataFrame)
        or type(dataset) is not str
        or dataset not in _ALL_DATASETS
        or type(as_of) is not dt.date
    ):
        raise FinancialPITError()
    clean_contract = "symbol" in frame.columns and "ts_code" not in frame.columns
    if clean_contract:
        required = (
            _CLEAN_STATEMENT_REQUIRED
            if dataset in _STATEMENT_DATASETS
            else _CLEAN_INDICATOR_REQUIRED
        )
    else:
        required = _STATEMENT_REQUIRED if dataset in _STATEMENT_DATASETS else _INDICATOR_REQUIRED
    if not required <= set(frame.columns):
        raise FinancialPITError()
    for column in required:
        expected = (
            pl.Date
            if clean_contract and column in {"ann_date", "f_ann_date", "available_date", "end_date"}
            else pl.String
        )
        if frame.schema[column] != expected:
            raise FinancialPITError()

    original_columns = frame.columns
    prepared = (
        _prepare_clean_dates(frame, statement=dataset in _STATEMENT_DATASETS)
        if clean_contract
        else _prepare_dates(frame, statement=dataset in _STATEMENT_DATASETS)
    )
    structural_bad = prepared.filter(pl.col("_quarantine_reason").is_not_null())
    known = prepared.filter(
        pl.col("_quarantine_reason").is_null() & (pl.col("available_date") < pl.lit(as_of))
    )
    if allowed_report_types is not None:
        known = known.filter(pl.col("report_type").is_in(allowed_report_types))
    if required_comp_type is not None:
        known = known.filter(pl.col("comp_type") == required_comp_type)
    keys = (
        [
            "symbol" if clean_contract else "ts_code",
            "end_date",
            "report_type",
            "comp_type",
        ]
        if dataset in _STATEMENT_DATASETS
        else ["symbol" if clean_contract else "ts_code", "end_date"]
    )
    if known.is_empty():
        return FinancialPITSelection(
            dataset=dataset,
            as_of=as_of,
            selected=_empty_selected(frame),
            quarantined=_canonical_quarantine(structural_bad, original_columns),
        )

    economic = [name for name in original_columns if name not in _NON_ECONOMIC_COLUMNS]
    if not economic:
        raise FinancialPITError()
    if bind_flow_chain:
        unambiguous, conflict_rows = _select_flow_revision_chains(
            known,
            symbol="symbol" if clean_contract else "ts_code",
            economic=economic,
            as_of=as_of,
            history_quarters=history_quarters,
        )
    else:
        latest = known.group_by(keys).agg(pl.col("available_date").max())
        candidates = known.join(latest, on=[*keys, "available_date"], how="inner")
        unambiguous, conflict_rows = _split_latest_conflicts(
            candidates,
            keys=[*keys, "available_date"],
            economic=economic,
        )

    if dataset in _STATEMENT_DATASETS:
        unambiguous = unambiguous.with_columns(
            (pl.col("update_flag") == "1").cast(pl.Int8).alias("_update_rank")
        ).sort([*keys, "available_date", "_update_rank", *economic])
    else:
        unambiguous = unambiguous.with_columns(pl.lit(0, dtype=pl.Int8).alias("_update_rank")).sort(
            [*keys, "available_date", "_update_rank", *economic]
        )
    selected = (
        unambiguous.unique(subset=keys, keep="last", maintain_order=True)
        .select(
            original_columns
            if "available_date" in original_columns
            else [*original_columns, "available_date"]
        )
        .sort(keys)
    )
    quarantine = _canonical_quarantine(
        pl.concat([structural_bad, conflict_rows], how="diagonal_relaxed"),
        original_columns,
    )
    return FinancialPITSelection(
        dataset=cast(FinancialDataset, dataset),
        as_of=as_of,
        selected=selected,
        quarantined=quarantine,
    )


def _select_flow_revision_chains(
    known: pl.DataFrame,
    *,
    symbol: str,
    economic: list[str],
    as_of: dt.date,
    history_quarters: int = 5,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Bind each cumulative flow row to the predecessor known by its successor."""
    group = [symbol, "report_type", "comp_type"]
    period_end = "end_date" if known.schema["end_date"] == pl.Date else "_end_date"
    quarter = (
        pl.when((pl.col(period_end).dt.month() == 3) & (pl.col(period_end).dt.day() == 31))
        .then(1)
        .when((pl.col(period_end).dt.month() == 6) & (pl.col(period_end).dt.day() == 30))
        .then(2)
        .when((pl.col(period_end).dt.month() == 9) & (pl.col(period_end).dt.day() == 30))
        .then(3)
        .when((pl.col(period_end).dt.month() == 12) & (pl.col(period_end).dt.day() == 31))
        .then(4)
        .otherwise(None)
    )
    work = known.with_columns(
        pl.col(period_end).alias("_period_end"),
        (pl.col(period_end).dt.year() * 4 + quarter).cast(pl.Int32).alias("_quarter_index"),
    )
    anchor_dates = work.group_by(group).agg(pl.col("_period_end").max().alias("_anchor_end_date"))
    active = (
        anchor_dates.join(
            work.select([*group, "_period_end", "_quarter_index"]).unique(),
            left_on=[*group, "_anchor_end_date"],
            right_on=[*group, "_period_end"],
            how="inner",
            validate="1:1",
        )
        .select(
            *group,
            pl.col("_quarter_index").alias("_desired_quarter"),
            pl.lit(as_of).alias("_cutoff"),
        )
        .with_columns(pl.lit(0, dtype=pl.Int8).alias("_depth"))
    )
    selected_frames: list[pl.DataFrame] = []
    conflict_frames: list[pl.DataFrame] = []
    resolved_frames: list[pl.DataFrame] = []
    request_keys = [*group, "_desired_quarter", "_depth", "_cutoff"]
    for depth in range(history_quarters):
        if active.is_empty():
            break
        eligible = (
            active.join(
                work,
                left_on=[*group, "_desired_quarter"],
                right_on=[*group, "_quarter_index"],
                how="inner",
                validate="1:m",
            )
            .filter(pl.col("available_date") <= pl.col("_cutoff"))
            .with_columns(
                pl.col("available_date").max().over(request_keys).alias("_latest_available_date")
            )
            .filter(pl.col("available_date") == pl.col("_latest_available_date"))
        )
        if eligible.is_empty():
            break
        unambiguous, conflicts = _split_latest_conflicts(
            eligible,
            keys=[*request_keys, "available_date"],
            economic=economic,
        )
        if not conflicts.is_empty():
            conflicts = conflicts.with_columns(
                pl.when(pl.col("_depth") == 0)
                .then(pl.col("_quarantine_reason"))
                .otherwise(pl.lit("REVISION_CHAIN_CONFLICT"))
                .alias("_quarantine_reason")
            )
            conflict_frames.append(conflicts)
        chosen = unambiguous.head(0)
        if not unambiguous.is_empty():
            chosen = (
                unambiguous.with_columns(
                    (pl.col("update_flag") == "1").cast(pl.Int8).alias("_update_rank")
                )
                .sort([*request_keys, "_update_rank", *economic])
                .unique(subset=request_keys, keep="last", maintain_order=True)
            )
            selected_frames.append(chosen)
        resolved = pl.concat(
            [
                chosen.select(request_keys),
                conflicts.select(request_keys).unique(),
            ],
            how="diagonal_relaxed",
        ).unique()
        resolved_frames.append(resolved)
        next_from_selected = chosen.select(
            *group,
            (pl.col("_desired_quarter") - 1).alias("_desired_quarter"),
            pl.col("available_date").alias("_cutoff"),
        )
        next_from_conflicts = conflicts.select(
            *group,
            (pl.col("_desired_quarter") - 1).alias("_desired_quarter"),
            pl.col("available_date").alias("_cutoff"),
        ).unique()
        active = pl.concat(
            [next_from_selected, next_from_conflicts], how="diagonal_relaxed"
        ).with_columns(
            pl.lit(depth + 1, dtype=pl.Int8).alias("_depth")
        )

    if not resolved_frames:
        selected = known.head(0)
    else:
        complete = (
            pl.concat(resolved_frames, how="diagonal_relaxed")
            .group_by(group)
            .agg(pl.col("_depth").n_unique().alias("_chain_depths"))
            .filter(pl.col("_chain_depths") == history_quarters)
            .select(group)
        )
        selected = (
            pl.concat(selected_frames, how="diagonal_relaxed").join(
                complete, on=group, how="semi"
            )
            if selected_frames
            else known.head(0)
        )
    conflicts = (
        pl.concat(conflict_frames, how="diagonal_relaxed")
        if conflict_frames
        else known.head(0)
    )
    return selected, conflicts


def _split_latest_conflicts(
    candidates: pl.DataFrame,
    *,
    keys: list[str],
    economic: list[str],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    conflicts = (
        candidates.group_by(keys)
        .agg(pl.struct(economic).n_unique().alias("_economic_versions"))
        .filter(pl.col("_economic_versions") > 1)
        .select(keys)
    )
    if conflicts.is_empty():
        return candidates, candidates.head(0)
    conflict_rows = candidates.join(conflicts, on=keys, how="semi").with_columns(
        pl.lit("LATEST_REVISION_CONFLICT").alias("_quarantine_reason")
    )
    return candidates.join(conflicts, on=keys, how="anti"), conflict_rows


def _prepare_dates(frame: pl.DataFrame, *, statement: bool) -> pl.DataFrame:
    prepared = frame.with_columns(
        pl.col("ann_date").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("_ann_date"),
        pl.col("end_date").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("_end_date"),
    )
    if statement:
        prepared = prepared.with_columns(
            pl.col("f_ann_date").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("_f_ann_date")
        ).with_columns(pl.max_horizontal("_ann_date", "_f_ann_date").alias("available_date"))
    else:
        prepared = prepared.with_columns(pl.col("_ann_date").alias("available_date"))
    return prepared.with_columns(
        pl.when(
            pl.col("ts_code").is_null() | ~pl.col("ts_code").str.contains(r"^[0-9]{6}\.(SH|SZ)$")
        )
        .then(pl.lit("SYMBOL_INVALID"))
        .when(pl.col("_end_date").is_null())
        .then(pl.lit("END_DATE_INVALID"))
        .when(pl.col("available_date").is_null())
        .then(pl.lit("AVAILABLE_DATE_INVALID"))
        .when(pl.col("_end_date") > pl.col("available_date"))
        .then(pl.lit("END_AFTER_AVAILABLE"))
        .otherwise(None)
        .alias("_quarantine_reason")
    )


def _prepare_clean_dates(frame: pl.DataFrame, *, statement: bool) -> pl.DataFrame:
    prepared = frame.with_columns(
        pl.col("ann_date").alias("_ann_date"),
        pl.col("end_date").alias("_end_date"),
    )
    if statement:
        prepared = prepared.with_columns(pl.col("f_ann_date").alias("_f_ann_date"))
    symbol = pl.col("symbol")
    return prepared.with_columns(
        pl.when(symbol.is_null() | ~symbol.str.contains(r"^[0-9]{6}\.(SH|SZ)$"))
        .then(pl.lit("SYMBOL_INVALID"))
        .when(pl.col("_end_date").is_null())
        .then(pl.lit("END_DATE_INVALID"))
        .when(pl.col("available_date").is_null())
        .then(pl.lit("AVAILABLE_DATE_INVALID"))
        .when(pl.col("_end_date") > pl.col("available_date"))
        .then(pl.lit("END_AFTER_AVAILABLE"))
        .otherwise(None)
        .alias("_quarantine_reason")
    )


def _empty_selected(frame: pl.DataFrame) -> pl.DataFrame:
    if "available_date" in frame.columns:
        return frame.head(0)
    return frame.head(0).with_columns(pl.lit(None, dtype=pl.Date).alias("available_date"))


def _canonical_quarantine(frame: pl.DataFrame, original_columns: list[str]) -> pl.DataFrame:
    selected_columns = (
        original_columns
        if "available_date" in original_columns
        else [*original_columns, "available_date"]
    )
    columns = [*selected_columns, "quarantine_reason"]
    if frame.is_empty():
        return frame.select(selected_columns).with_columns(
            pl.lit(None, dtype=pl.String).alias("quarantine_reason")
        )
    result = frame.select([*selected_columns, "_quarantine_reason"]).rename(
        {"_quarantine_reason": "quarantine_reason"}
    )
    return result.unique(maintain_order=False).sort(columns)


__all__ = [
    "FinancialDataset",
    "FinancialPITError",
    "FinancialPITSelection",
    "select_pit_quality_revisions_as_of",
    "select_financial_revisions_as_of",
]
