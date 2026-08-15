"""Canonical in-memory projection for Tushare financial raw rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

import polars as pl
from polars.exceptions import PolarsError

FinancialCleanDataset = Literal["income", "balancesheet", "cashflow", "fina_indicator"]
FinancialFactorDataset = Literal["income", "balancesheet", "cashflow"]

_STATEMENTS = frozenset({"income", "balancesheet", "cashflow"})
_ALL_DATASETS = _STATEMENTS | {"fina_indicator"}
_STRUCTURAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "income": (
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
    ),
    "balancesheet": (
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
    ),
    "cashflow": (
        "ts_code",
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "comp_type",
        "update_flag",
    ),
    "fina_indicator": ("ts_code", "ann_date", "end_date"),
}
_ECONOMIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "income": ("n_income", "n_income_attr_p"),
    "balancesheet": ("total_assets", "total_hldr_eqy_exc_min_int"),
    "cashflow": ("n_cashflow_act",),
    "fina_indicator": (),
}


class FinancialCleanError(ValueError):
    """Stable failure raised for an invalid financial clean projection."""

    def __init__(self) -> None:
        super().__init__("TUSHARE_FINANCIAL_CLEAN_INVALID")


@dataclass(frozen=True, slots=True)
class FinancialNormalization:
    """Canonical eligible rows and explicitly quarantined source rows."""

    dataset: FinancialCleanDataset
    clean: pl.DataFrame
    quarantined: pl.DataFrame


def normalize_tushare_financial_frame(
    frame: pl.DataFrame, *, dataset: FinancialCleanDataset
) -> FinancialNormalization:
    """Normalize required fields without silently coercing malformed economics."""
    try:
        return _normalize(frame=frame, dataset=dataset)
    except (FinancialCleanError, PolarsError, TypeError, ValueError):
        pass
    raise FinancialCleanError() from None


def project_selected_financial_factor_frame(
    frame: pl.DataFrame, *, dataset: FinancialFactorDataset
) -> pl.DataFrame:
    """Project one PIT-selected statement view into the factor input contract."""
    try:
        return _project_factor_frame(frame=frame, dataset=dataset)
    except (FinancialCleanError, PolarsError, TypeError, ValueError):
        pass
    raise FinancialCleanError() from None


def _normalize(*, frame: pl.DataFrame, dataset: FinancialCleanDataset) -> FinancialNormalization:
    if (
        not isinstance(frame, pl.DataFrame)
        or type(dataset) is not str
        or dataset not in _ALL_DATASETS
    ):
        raise FinancialCleanError()
    structural = _STRUCTURAL_COLUMNS[dataset]
    economics = _ECONOMIC_COLUMNS[dataset]
    required = {*structural, *economics}
    if not required <= set(frame.columns):
        raise FinancialCleanError()

    work = frame.select([*structural, *economics]).with_row_index("_source_row")
    work = work.with_columns(
        *[
            pl.col(name).cast(pl.String, strict=False).str.strip_chars().alias(name)
            for name in structural
        ],
        *[
            pl.col(name).cast(pl.String, strict=False).str.strip_chars().alias(f"_text_{name}")
            for name in economics
        ],
    )
    work = work.with_columns(
        *[
            pl.when(pl.col(f"_text_{name}").is_null() | (pl.col(f"_text_{name}") == ""))
            .then(None)
            .otherwise(pl.col(f"_text_{name}").cast(pl.Float64, strict=False))
            .alias(name)
            for name in economics
        ],
        pl.col("ann_date").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("_ann_date"),
        pl.col("end_date").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("_end_date"),
    )
    if dataset in _STATEMENTS:
        work = work.with_columns(
            pl.col("f_ann_date").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("_f_ann_date")
        ).with_columns(pl.max_horizontal("_ann_date", "_f_ann_date").alias("_available_date"))
    else:
        work = work.with_columns(pl.col("_ann_date").alias("_available_date"))

    numeric_invalid = pl.lit(False)
    for name in economics:
        present = pl.col(f"_text_{name}").is_not_null() & (pl.col(f"_text_{name}") != "")
        numeric_invalid = numeric_invalid | (
            present & (pl.col(name).is_null() | ~pl.col(name).is_finite())
        )

    reason = (
        pl.when(
            pl.col("ts_code").is_null() | ~pl.col("ts_code").str.contains(r"^[0-9]{6}\.(SH|SZ)$")
        )
        .then(pl.lit("SYMBOL_INVALID"))
        .when(pl.col("_ann_date").is_null())
        .then(pl.lit("ANN_DATE_INVALID"))
        .when(pl.col("_end_date").is_null())
        .then(pl.lit("END_DATE_INVALID"))
    )
    if dataset in _STATEMENTS:
        reason = (
            reason.when(
                (pl.col("f_ann_date").is_not_null())
                & (pl.col("f_ann_date") != "")
                & pl.col("_f_ann_date").is_null()
            )
            .then(pl.lit("F_ANN_DATE_INVALID"))
            .when(pl.col("report_type").is_null() | (pl.col("report_type") == ""))
            .then(pl.lit("REPORT_TYPE_MISSING"))
            .when(pl.col("comp_type").is_null() | (pl.col("comp_type") == ""))
            .then(pl.lit("COMP_TYPE_MISSING"))
            .when(pl.col("update_flag").is_null() | ~pl.col("update_flag").is_in(["0", "1"]))
            .then(pl.lit("UPDATE_FLAG_INVALID"))
        )
    reason = (
        reason.when(pl.col("_available_date").is_null())
        .then(pl.lit("AVAILABLE_DATE_INVALID"))
        .when(pl.col("_end_date") > pl.col("_available_date"))
        .then(pl.lit("END_AFTER_AVAILABLE"))
        .when(numeric_invalid)
        .then(pl.lit("REQUIRED_NUMERIC_INVALID"))
        .otherwise(None)
        .alias("quarantine_reason")
    )
    work = work.with_columns(reason)
    canonical = [*structural, *economics]
    sort_keys = ["ts_code", "end_date", "ann_date"]
    if dataset in _STATEMENTS:
        sort_keys.extend(["f_ann_date", "report_type", "comp_type", "update_flag"])
    clean = (
        work.filter(pl.col("quarantine_reason").is_null())
        .select(canonical)
        .with_columns(pl.lit("tushare").alias("source"))
        .sort(sort_keys)
    )
    quarantined = (
        work.filter(pl.col("quarantine_reason").is_not_null())
        .select(["_source_row", *canonical, "quarantine_reason"])
        .sort("_source_row")
    )
    return FinancialNormalization(
        dataset=cast(FinancialCleanDataset, dataset),
        clean=clean,
        quarantined=quarantined,
    )


def _project_factor_frame(*, frame: pl.DataFrame, dataset: FinancialFactorDataset) -> pl.DataFrame:
    if (
        not isinstance(frame, pl.DataFrame)
        or type(dataset) is not str
        or dataset not in _STATEMENTS
    ):
        raise FinancialCleanError()
    economics = _ECONOMIC_COLUMNS[dataset]
    symbol_column = "symbol" if "symbol" in frame.columns else "ts_code"
    required = {
        symbol_column,
        "end_date",
        "report_type",
        "comp_type",
        *economics,
    }
    if not required <= set(frame.columns):
        raise FinancialCleanError()
    if frame.schema["end_date"] == pl.Date:
        projected = frame.select(
            pl.col(symbol_column).alias("symbol"),
            "end_date",
            "report_type",
            "comp_type",
            *economics,
        )
    elif frame.schema["end_date"] == pl.String:
        projected = frame.select(
            pl.col(symbol_column).alias("symbol"),
            pl.col("end_date").str.strptime(pl.Date, "%Y%m%d", strict=False).alias("end_date"),
            "report_type",
            "comp_type",
            *economics,
        )
    else:
        raise FinancialCleanError()
    if projected.select(
        pl.any_horizontal(
            pl.col("symbol").is_null(),
            pl.col("end_date").is_null(),
            pl.col("report_type").is_null(),
            pl.col("comp_type").is_null(),
        ).any()
    ).item():
        raise FinancialCleanError()
    for name in economics:
        if projected.schema[name] != pl.Float64:
            raise FinancialCleanError()
    keys = ["symbol", "end_date", "report_type", "comp_type"]
    if projected.select(pl.struct(keys).is_duplicated().any()).item():
        raise FinancialCleanError()
    return projected.sort(keys)


__all__ = [
    "FinancialCleanDataset",
    "FinancialCleanError",
    "FinancialFactorDataset",
    "FinancialNormalization",
    "normalize_tushare_financial_frame",
    "project_selected_financial_factor_frame",
]
