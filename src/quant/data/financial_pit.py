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


def _select(
    *, frame: pl.DataFrame, dataset: FinancialDataset, as_of: dt.date
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

    latest = known.group_by(keys).agg(pl.col("available_date").max())
    candidates = known.join(latest, on=[*keys, "available_date"], how="inner")
    economic = [name for name in original_columns if name not in _NON_ECONOMIC_COLUMNS]
    if not economic:
        raise FinancialPITError()
    conflicts = (
        candidates.group_by([*keys, "available_date"])
        .agg(pl.struct(economic).n_unique().alias("_economic_versions"))
        .filter(pl.col("_economic_versions") > 1)
        .select([*keys, "available_date"])
    )
    if conflicts.is_empty():
        conflict_rows = candidates.head(0)
        unambiguous = candidates
    else:
        conflict_rows = candidates.join(
            conflicts, on=[*keys, "available_date"], how="semi"
        ).with_columns(pl.lit("LATEST_REVISION_CONFLICT").alias("_quarantine_reason"))
        unambiguous = candidates.join(conflicts, on=[*keys, "available_date"], how="anti")

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
    "select_financial_revisions_as_of",
]
