"""Frozen first-batch PIT profitability and earnings-quality factors."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
from polars.exceptions import PolarsError

_KEY = ["symbol", "end_date", "report_type", "comp_type"]
_GROUP = ["symbol", "report_type", "comp_type"]


@dataclass(frozen=True, slots=True)
class PITQualityFactorSpec:
    """Auditable formula, direction, and invalid-value rule."""

    name: str
    formula: str
    direction: str
    invalid_rule: str


PIT_QUALITY_FACTOR_SPECS: tuple[PITQualityFactorSpec, ...] = (
    PITQualityFactorSpec(
        "pit_roe_ttm",
        "NI_parent_TTM / mean(parent_equity_t, parent_equity_t-4q)",
        "higher",
        "null unless four consecutive quarters and positive average parent equity",
    ),
    PITQualityFactorSpec(
        "pit_roa_ttm",
        "NI_total_TTM / mean(total_assets_t, total_assets_t-4q)",
        "higher",
        "null unless four consecutive quarters and positive average total assets",
    ),
    PITQualityFactorSpec(
        "pit_cash_profit_quality_ttm",
        "OCF_TTM / NI_total_TTM",
        "higher",
        "null for missing quarters or non-positive TTM total net income",
    ),
    PITQualityFactorSpec(
        "pit_total_accruals_ttm",
        "(NI_total_TTM - OCF_TTM) / average_total_assets",
        "lower",
        "null unless four consecutive quarters and positive average total assets",
    ),
)
PIT_QUALITY_FACTOR_NAMES = tuple(spec.name for spec in PIT_QUALITY_FACTOR_SPECS)
PIT_QUALITY_ELIGIBILITY_STATUSES = (
    "VALID",
    "MISSING_CHAIN",
    "NON_INDUSTRIAL",
    "INVALID_DENOMINATOR",
    "QUARANTINED",
)


def compute_pit_quality_factors(
    *, income: pl.DataFrame, balance_sheet: pl.DataFrame, cash_flow: pl.DataFrame
) -> pl.DataFrame:
    """Compute frozen quality factors from three already PIT-selected statement views."""
    try:
        return _compute(income=income, balance_sheet=balance_sheet, cash_flow=cash_flow)
    except (PolarsError, TypeError, ValueError):
        pass
    raise ValueError("PIT_QUALITY_FACTOR_INVALID") from None


def compute_pit_quality_factor_diagnostics(
    *, income: pl.DataFrame, balance_sheet: pl.DataFrame, cash_flow: pl.DataFrame
) -> pl.DataFrame:
    """Return factor values with a mutually exclusive eligibility reason."""
    try:
        details = _compute_details(
            income=income,
            balance_sheet=balance_sheet,
            cash_flow=cash_flow,
        )
        frames = [
            _diagnostic_frame(
                details,
                factor="pit_roe_ttm",
                missing=(
                    ~pl.col("_income_ttm_complete").fill_null(False)
                    | pl.col("_average_parent_equity").is_null()
                ),
                invalid=pl.col("_average_parent_equity") <= 0,
            ),
            _diagnostic_frame(
                details,
                factor="pit_roa_ttm",
                missing=(
                    ~pl.col("_income_ttm_complete").fill_null(False)
                    | pl.col("_average_total_assets").is_null()
                ),
                invalid=pl.col("_average_total_assets") <= 0,
            ),
            _diagnostic_frame(
                details,
                factor="pit_cash_profit_quality_ttm",
                missing=(
                    ~pl.col("_cash_ttm_complete").fill_null(False)
                    | pl.col("_ttm_n_income").is_null()
                ),
                invalid=pl.col("_ttm_n_income") <= 0,
            ),
            _diagnostic_frame(
                details,
                factor="pit_total_accruals_ttm",
                missing=(
                    ~pl.col("_cash_ttm_complete").fill_null(False)
                    | pl.col("_average_total_assets").is_null()
                ),
                invalid=pl.col("_average_total_assets") <= 0,
            ),
        ]
        result = pl.concat(frames).sort([*_KEY, "factor"])
        if result.select(pl.struct([*_KEY, "factor"]).is_duplicated().any()).item():
            raise ValueError
        return result
    except (PolarsError, TypeError, ValueError):
        pass
    raise ValueError("PIT_QUALITY_FACTOR_INVALID") from None


def _compute(
    *, income: pl.DataFrame, balance_sheet: pl.DataFrame, cash_flow: pl.DataFrame
) -> pl.DataFrame:
    result = (
        _compute_details(
            income=income,
            balance_sheet=balance_sheet,
            cash_flow=cash_flow,
        )
        .filter(pl.col("comp_type") == "1")
        .select([*_KEY, *PIT_QUALITY_FACTOR_NAMES])
        .sort(_KEY)
    )
    if result.select(
        pl.any_horizontal(*[pl.col(name).is_infinite() for name in PIT_QUALITY_FACTOR_NAMES]).any()
    ).item():
        raise ValueError("PIT_QUALITY_FACTOR_INVALID")
    return result


def _compute_details(
    *, income: pl.DataFrame, balance_sheet: pl.DataFrame, cash_flow: pl.DataFrame
) -> pl.DataFrame:
    required = {
        "income": {
            *_KEY,
            "n_income",
            "n_income_attr_p",
        },
        "balance_sheet": {
            *_KEY,
            "total_assets",
            "total_hldr_eqy_exc_min_int",
        },
        "cash_flow": {
            *_KEY,
            "n_cashflow_act",
        },
    }
    frames = {
        "income": income,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
    }
    for name, frame in frames.items():
        if (
            not isinstance(frame, pl.DataFrame)
            or frame.is_empty()
            or not required[name] <= set(frame.columns)
            or frame.select(pl.struct(_KEY).is_duplicated().any()).item()
        ):
            raise ValueError("PIT_QUALITY_FACTOR_INVALID")
        if frame.schema["end_date"] != pl.Date:
            raise ValueError("PIT_QUALITY_FACTOR_INVALID")

    income_quarters = _single_quarters(
        income.select([*_KEY, "n_income", "n_income_attr_p"]),
        ["n_income", "n_income_attr_p"],
    )
    cash_quarters = _single_quarters(
        cash_flow.select([*_KEY, "n_cashflow_act"]), ["n_cashflow_act"]
    )
    flows = income_quarters.join(
        cash_quarters,
        on=[*_KEY, "_quarter", "_quarter_index"],
        how="left",
        validate="1:1",
    ).sort([*_GROUP, "_quarter_index"])
    flows = flows.with_columns(
        pl.col("_single_n_income")
        .rolling_sum(window_size=4, min_samples=4)
        .over(_GROUP)
        .alias("_ttm_n_income"),
        pl.col("_single_n_income_attr_p")
        .rolling_sum(window_size=4, min_samples=4)
        .over(_GROUP)
        .alias("_ttm_n_income_attr_p"),
        pl.col("_single_n_cashflow_act")
        .rolling_sum(window_size=4, min_samples=4)
        .over(_GROUP)
        .alias("_ttm_n_cashflow_act"),
        pl.col("_quarter_index").shift(3).over(_GROUP).alias("_quarter_lag3"),
    ).with_columns(
        (
            (pl.col("_quarter_index") - pl.col("_quarter_lag3") == 3)
            & pl.col("_ttm_n_income").is_not_null()
            & pl.col("_ttm_n_income_attr_p").is_not_null()
        ).alias("_income_ttm_complete"),
        (
            (pl.col("_quarter_index") - pl.col("_quarter_lag3") == 3)
            & pl.col("_ttm_n_income").is_not_null()
            & pl.col("_ttm_n_cashflow_act").is_not_null()
        ).alias("_cash_ttm_complete"),
    )

    balance = _quarter_coordinates(
        balance_sheet.select([*_KEY, "total_assets", "total_hldr_eqy_exc_min_int"])
    )
    prior = balance.select(
        [
            *_GROUP,
            (pl.col("_quarter_index") + 4).alias("_quarter_index"),
            pl.col("total_assets").alias("_prior_total_assets"),
            pl.col("total_hldr_eqy_exc_min_int").alias("_prior_parent_equity"),
        ]
    )
    result = (
        flows.join(
            balance.select(
                [
                    *_GROUP,
                    "_quarter_index",
                    "total_assets",
                    "total_hldr_eqy_exc_min_int",
                ]
            ),
            on=[*_GROUP, "_quarter_index"],
            how="left",
            validate="m:1",
        )
        .join(
            prior,
            on=[*_GROUP, "_quarter_index"],
            how="left",
            validate="m:1",
        )
        .with_columns(
            ((pl.col("total_assets") + pl.col("_prior_total_assets")) / 2.0).alias(
                "_average_total_assets"
            ),
            ((pl.col("total_hldr_eqy_exc_min_int") + pl.col("_prior_parent_equity")) / 2.0).alias(
                "_average_parent_equity"
            ),
        )
        .with_columns(
            pl.when(pl.col("_income_ttm_complete") & (pl.col("_average_parent_equity") > 0))
            .then(pl.col("_ttm_n_income_attr_p") / pl.col("_average_parent_equity"))
            .otherwise(None)
            .alias("pit_roe_ttm"),
            pl.when(pl.col("_income_ttm_complete") & (pl.col("_average_total_assets") > 0))
            .then(pl.col("_ttm_n_income") / pl.col("_average_total_assets"))
            .otherwise(None)
            .alias("pit_roa_ttm"),
            pl.when(pl.col("_cash_ttm_complete") & (pl.col("_ttm_n_income") > 0))
            .then(pl.col("_ttm_n_cashflow_act") / pl.col("_ttm_n_income"))
            .otherwise(None)
            .alias("pit_cash_profit_quality_ttm"),
            pl.when(pl.col("_cash_ttm_complete") & (pl.col("_average_total_assets") > 0))
            .then(
                (pl.col("_ttm_n_income") - pl.col("_ttm_n_cashflow_act"))
                / pl.col("_average_total_assets")
            )
            .otherwise(None)
            .alias("pit_total_accruals_ttm"),
        )
    )
    return result


def _diagnostic_frame(
    details: pl.DataFrame,
    *,
    factor: str,
    missing: pl.Expr,
    invalid: pl.Expr,
) -> pl.DataFrame:
    return details.select(
        *_KEY,
        pl.lit(factor).alias("factor"),
        pl.col(factor).alias("factor_value"),
        pl.when(pl.col("comp_type") != "1")
        .then(pl.lit("NON_INDUSTRIAL"))
        .when(missing)
        .then(pl.lit("MISSING_CHAIN"))
        .when(invalid)
        .then(pl.lit("INVALID_DENOMINATOR"))
        .otherwise(pl.lit("VALID"))
        .alias("status"),
    )


def _single_quarters(frame: pl.DataFrame, values: list[str]) -> pl.DataFrame:
    coordinated = _quarter_coordinates(frame)
    previous = coordinated.select(
        [
            *_GROUP,
            "_year",
            (pl.col("_quarter") + 1).alias("_quarter"),
            *[pl.col(name).alias(f"_previous_{name}") for name in values],
        ]
    )
    joined = coordinated.join(
        previous,
        on=[*_GROUP, "_year", "_quarter"],
        how="left",
        validate="m:1",
    )
    return joined.with_columns(
        *[
            pl.when(pl.col("_quarter") == 1)
            .then(pl.col(name))
            .when(pl.col(f"_previous_{name}").is_not_null())
            .then(pl.col(name) - pl.col(f"_previous_{name}"))
            .otherwise(None)
            .alias(f"_single_{name}")
            for name in values
        ]
    ).select(
        [
            *_KEY,
            "_quarter",
            "_quarter_index",
            *[f"_single_{name}" for name in values],
        ]
    )


def _quarter_coordinates(frame: pl.DataFrame) -> pl.DataFrame:
    result = frame.with_columns(
        pl.col("end_date").dt.year().alias("_year"),
        pl.when((pl.col("end_date").dt.month() == 3) & (pl.col("end_date").dt.day() == 31))
        .then(1)
        .when((pl.col("end_date").dt.month() == 6) & (pl.col("end_date").dt.day() == 30))
        .then(2)
        .when((pl.col("end_date").dt.month() == 9) & (pl.col("end_date").dt.day() == 30))
        .then(3)
        .when((pl.col("end_date").dt.month() == 12) & (pl.col("end_date").dt.day() == 31))
        .then(4)
        .otherwise(None)
        .cast(pl.Int8)
        .alias("_quarter"),
    ).filter(pl.col("_quarter").is_not_null())
    return result.with_columns(
        (pl.col("_year") * 4 + pl.col("_quarter")).alias("_quarter_index")
    ).sort([*_GROUP, "_quarter_index"])


__all__ = [
    "PIT_QUALITY_ELIGIBILITY_STATUSES",
    "PIT_QUALITY_FACTOR_NAMES",
    "PIT_QUALITY_FACTOR_SPECS",
    "PITQualityFactorSpec",
    "compute_pit_quality_factor_diagnostics",
    "compute_pit_quality_factors",
]
