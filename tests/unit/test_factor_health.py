import datetime as dt
import json
import math

import numpy as np
import polars as pl
import pytest

from quant.reporting.factor_health import HealthParameters, diagnose_factor_health

AS_OF = dt.date(2026, 9, 11)
PARAMETERS = HealthParameters(minimum_symbols=4, minimum_reference_months=12)


def current(values: list[float | None], *, industries: list[str | None] | None = None,
            sizes: list[float | None] | None = None) -> pl.DataFrame:
    n = len(values)
    return pl.DataFrame({"symbol": [f"s{i}" for i in range(n)], "trade_date": [AS_OF] * n,
        "value": values, "industry_l1": industries if industries is not None else ["a"] * n,
        "total_market_value": sizes if sizes is not None else list(range(1, n + 1))},
        schema_overrides={"symbol": pl.String, "trade_date": pl.Date, "value": pl.Float64,
            "industry_l1": pl.String, "total_market_value": pl.Float64})


def reference(values: list[float | None], months: int = 12) -> pl.DataFrame:
    return pl.concat([current(values).select("symbol", "trade_date", "value").with_columns(
        pl.lit(dt.date(2025 if i < 4 else 2026, 9 + i if i < 4 else i - 3, 1)).alias("trade_date"))
        for i in range(months)])


def test_missing_counts_separate_null_nan_and_infinities_and_are_json_safe() -> None:
    result = diagnose_factor_health(current([None, float("nan"), float("inf"), -float("inf"), 0., 1.]),
        reference([0., 1., 2., 3.]), as_of=AS_OF, parameters=PARAMETERS)
    counts = result["counts"]
    assert counts["null"] == counts["nan"] == counts["positive_inf"] == counts["negative_inf"] == 1
    assert counts["finite"] == 2
    assert counts["nonfinite_rate"] == .5
    assert counts["missing_or_nonfinite_rate"] == pytest.approx(4 / 6)
    assert result["distribution"]["mean"] == .5
    assert result["distribution"]["skewness"] is None
    json.dumps(result, allow_nan=False)


def test_population_distribution_and_actual_mad_thresholds() -> None:
    values = [-2., -1., 0., 1., 2., 100.]
    result = diagnose_factor_health(current(values), reference(values), as_of=AS_OF, parameters=PARAMETERS)
    dist, mad = result["distribution"], result["mad_clipping"]
    y = np.array(values)
    assert dist["std"] == pytest.approx(np.std(y, ddof=0))
    assert dist["p01"] == pytest.approx(np.quantile(y, .01))
    assert dist["skewness"] == pytest.approx(np.mean(((y - y.mean()) / y.std()) ** 3))
    assert dist["excess_kurtosis"] == pytest.approx(np.mean(((y - y.mean()) / y.std()) ** 4) - 3)
    assert mad["median"] == .5 and mad["mad"] == 1.5
    assert mad["lower"] == pytest.approx(.5 - 3 * 1.4826 * 1.5)
    assert mad["upper"] == pytest.approx(.5 + 3 * 1.4826 * 1.5)
    assert mad["clipped_n"] == 1 and mad["clipped_fraction"] == pytest.approx(1 / 6)


def test_zero_mad_skips_clipping_even_when_a_large_outlier_exists() -> None:
    result = diagnose_factor_health(current([0., 0., 0., 0., 100.]), reference([0., 1., 2., 3.]),
        as_of=AS_OF, parameters=PARAMETERS)
    assert result["mad_clipping"]["reason"] == "zero_mad_skip"
    assert result["mad_clipping"]["clipped_fraction"] is None
    assert result["mad_clipping"]["upper"] is None


def test_actual_neutralization_mad_uses_only_rows_with_both_controls() -> None:
    values = [-2., -1., 0., 1., 2., 100.]
    result = diagnose_factor_health(current(values, industries=["a", "a", "a", "a", "a", None]),
        reference(values), as_of=AS_OF, parameters=PARAMETERS)
    whole, controlled = result["mad_clipping"], result["mad_clipping_valid_controls"]
    assert whole["clipped_n"] == 1 and whole["n"] == 6
    assert controlled["n"] == 5 and controlled["median"] == 0
    assert controlled["mad"] == 1 and controlled["clipped_n"] == 0
    assert controlled["upper"] == pytest.approx(3 * 1.4826)
    assert controlled["pool"] == "eligible_finite_raw_with_valid_size_and_industry"


def test_size_rank_correlation_and_industry_eta_are_not_score_correlations() -> None:
    result = diagnose_factor_health(current([0., 0., 10., 10.], industries=["a", "a", "b", "b"],
        sizes=[1., 1., 2., 2.]), reference([0., 1., 2., 3.]), as_of=AS_OF, parameters=PARAMETERS)
    assert result["controls"]["size"]["spearman"] == pytest.approx(1)
    industry = result["controls"]["industry"]
    assert industry["eta_squared"] == pytest.approx(1)
    assert industry["max_absolute_dummy_pearson"] == pytest.approx(1)


def test_missing_controls_count_only_finite_values_and_insufficient_pairs_are_none() -> None:
    result = diagnose_factor_health(current([1., 2., 3., 4., None],
        industries=["a", "b", None, "", None], sizes=[1., None, 0., float("inf"), None]),
        reference([0., 1., 2., 3.]), as_of=AS_OF, parameters=PARAMETERS)
    assert result["controls"]["size"]["missing_control_n"] == 3
    assert result["controls"]["industry"]["missing_control_n"] == 2
    assert result["controls"]["size"]["spearman"] is None
    assert result["controls"]["industry"]["reason"] == "insufficient_paired_samples"


def test_psi_uses_fixed_reference_bins_jeffreys_counts_and_responds_to_tails() -> None:
    parameters = HealthParameters(minimum_symbols=4, reference_bins=2)
    past = reference([0., 1., 2., 3.])
    result = diagnose_factor_health(current([100., 101., 102., 103.]), past,
        as_of=AS_OF, parameters=parameters)["drift"]
    assert result["bin_edges"] == [None, 1.5, None]
    assert result["reference_bin_counts"] == [24, 24]
    assert result["current_bin_counts"] == [0, 4]
    p = np.array([24.5, 24.5]) / 49
    q = np.array([.5, 4.5]) / 5
    assert result["psi"] == pytest.approx(np.sum((q - p) * np.log(q / p)))
    assert result["median_shift_iqr"] == pytest.approx(100 / 1.5)


def test_repeated_quantile_edges_merge_and_zero_iqr_is_not_a_zero_shift() -> None:
    values = [0.] * 9 + [10.]
    result = diagnose_factor_health(current(values), reference(values),
        as_of=AS_OF, parameters=PARAMETERS)["drift"]
    assert result["actual_bins"] < 10
    edges = result["bin_edges"][1:-1]
    assert edges == sorted(set(edges))
    assert result["median_shift_iqr"] is None
    assert result["median_shift_reason"] == "zero_reference_iqr"
    assert result["psi"] is not None


def test_short_history_and_constant_reference_have_explicit_reasons() -> None:
    result = diagnose_factor_health(current([0., 1., 2., 3.]), reference([0., 1., 2., 3.], 11),
        as_of=AS_OF, parameters=PARAMETERS)["drift"]
    assert result["psi"] is None and result["psi_reason"] == "insufficient_reference_months"
    result = diagnose_factor_health(current([0., 1., 2., 3.]), reference([1., 1., 1., 1.]),
        as_of=AS_OF, parameters=PARAMETERS)["drift"]
    assert result["psi"] is None and result["psi_reason"] == "reference_zero_variance"
    assert result["median_shift_iqr"] is None


@pytest.mark.parametrize("valid_rows", [0, 3])
def test_reference_month_with_missing_or_too_few_values_does_not_qualify(valid_rows: int) -> None:
    past = reference([0., 1., 2., 3.]).with_columns(
        pl.when((pl.col("trade_date") == dt.date(2025, 9, 1))
                & ~pl.col("symbol").is_in([f"s{i}" for i in range(valid_rows)]))
        .then(None).otherwise(pl.col("value")).alias("value"))
    result = diagnose_factor_health(current([0., 1., 2., 3.]), past,
        as_of=AS_OF, parameters=PARAMETERS)["drift"]
    assert result["total_reference_months"] == 12
    assert result["finite_reference_months"] == (11 if valid_rows == 0 else 12)
    assert result["qualified_reference_months"] == 11
    assert result["bad_reference_months"] == ["2025-09"]
    assert result["psi"] is None and result["psi_reason"] == "insufficient_qualified_reference_months"


def test_constant_current_correlation_and_shape_are_not_fabricated_zeros() -> None:
    result = diagnose_factor_health(current([1., 1., 1., 1.], industries=["a", "a", "b", "b"]),
        reference([0., 1., 2., 3.]), as_of=AS_OF, parameters=PARAMETERS)
    assert result["distribution"]["std"] == 0
    assert result["distribution"]["skewness"] is None
    assert result["distribution"]["skewness_reason"] == "zero_variance"
    assert result["controls"]["industry"]["eta_squared"] is None
    assert result["controls"]["size"]["reason"] == "value_zero_variance"


@pytest.mark.parametrize("reference_date", [AS_OF, dt.date(2026, 9, 12)])
def test_same_day_or_future_reference_is_rejected(reference_date: dt.date) -> None:
    past = reference([0., 1., 2., 3.], 1).with_columns(pl.lit(reference_date).alias("trade_date"))
    with pytest.raises(ValueError, match="strictly past"):
        diagnose_factor_health(current([0., 1., 2., 3.]), past, as_of=AS_OF)


def test_current_wrong_date_and_duplicate_keys_fail() -> None:
    now, past = current([0., 1., 2., 3.]), reference([0., 1., 2., 3.])
    with pytest.raises(ValueError, match="current dates"):
        diagnose_factor_health(now.with_columns(pl.lit(dt.date(2026, 9, 10)).alias("trade_date")), past, as_of=AS_OF)
    with pytest.raises(ValueError, match="unique"):
        diagnose_factor_health(pl.concat([now, now.head(1)]), past, as_of=AS_OF)


def test_empty_data_retains_safe_missing_results() -> None:
    result = diagnose_factor_health(current([]), reference([0., 1., 2., 3.]).head(0), as_of=AS_OF)
    assert result["counts"]["missing_or_nonfinite_rate"] is None
    assert result["distribution"]["median"] is None
    assert result["distribution"]["reason"] == "no_finite_values"
    json.dumps(result, allow_nan=False)


def test_large_finite_values_produce_overflow_reasons_instead_of_silent_null_or_zero() -> None:
    values = [-1.7e308, -1.6e308, 1.6e308, 1.7e308]
    result = diagnose_factor_health(current(values, industries=["a", "a", "b", "b"]),
        reference(values), as_of=AS_OF, parameters=PARAMETERS)
    assert result["counts"]["finite"] == 4
    assert result["controls"]["industry"]["eta_squared"] is None
    assert result["controls"]["industry"]["reason"] == "numeric_overflow"
    assert result["drift"]["median_shift_iqr"] is None
    assert result["drift"]["median_shift_reason"] == "numeric_overflow"
    assert result["distribution"]["reason"] == "numeric_overflow"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field,value", [("psi_smoothing", 0), ("reference_bins", 1),
    ("minimum_reference_months", 0), ("mad_normal_scale", math.inf)])
def test_invalid_parameters_fail(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        HealthParameters(**{field: value})
