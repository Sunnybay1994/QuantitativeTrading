"""Admission gates and config validation for classic factor runs."""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import tomllib
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.factors import (
    CLASSIC_FACTOR_NAMES,
    SECOND_BATCH_FACTOR_NAMES,
    THIRD_BATCH_FACTOR_NAMES,
)
from quant.factors.classic_fifth_batch import FIFTH_BATCH_FACTOR_NAMES
from quant.factors.classic_fourth_batch import FOURTH_BATCH_FACTOR_NAMES
from quant.factors.classic_market_risk import (
    DOWNSIDE_BETA_FACTOR_NAMES,
    MARKET_RISK_CONTROL_NAMES,
)
from quant.factors.classic_sixth_batch import SIXTH_BATCH_FACTOR_NAMES
from quant.research.lightweight_run import (
    ResearchFoldV1,
    ResearchInputDigestV1,
    canonical_json_bytes,
)
from quant.research.m3.contracts import AShareCostPeriod

_SIXTH_BATCH_CATALOG = "alpha101_price_volume_geometry_sixth_batch_v1"


def _inside(root: Path, path: Path, *, strict: bool = True) -> Path:
    candidate = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if strict and not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes project root: {path}")
    return candidate
_SIXTH_BATCH_HYPOTHESIS_ID = "m2-alpha101-price-volume-geometry-sixth-batch-v1"
_SIXTH_BATCH_SNAPSHOT_ID = (
    "b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2"
)
_SIXTH_BATCH_COST_SEMANTIC_SHA256 = (
    "b2041d8495aa408de0bd264d6c03eb7e4d174e03f120289bc8471cbb5ea0a959"
)
_SIXTH_BATCH_REFERENCE_NAMES = (
    CLASSIC_FACTOR_NAMES
    + SECOND_BATCH_FACTOR_NAMES
    + THIRD_BATCH_FACTOR_NAMES
    + FOURTH_BATCH_FACTOR_NAMES
    + FIFTH_BATCH_FACTOR_NAMES
    + ("liquidity_20",)
)
_SIXTH_BATCH_SECTION_KEYS = frozenset(
    {
        "schema_version",
        "hypothesis_id",
        "factors",
        "correlation_window_sessions",
        "delta_lag_sessions",
        "alpha041_price_basis",
        "alpha041_vwap_formula",
        "direction_policy",
        "trial_budget",
        "trial_delta",
        "attempt_ordinal",
    }
)
_SIXTH_BATCH_FROZEN_FOLDS: tuple[dict[str, dt.date], ...] = (
    {
        "train_start": dt.date(2020, 1, 1),
        "train_end": dt.date(2020, 12, 31),
        "validation_start": dt.date(2021, 1, 1),
        "validation_end": dt.date(2021, 12, 31),
        "test_start": dt.date(2022, 1, 1),
        "test_end": dt.date(2022, 12, 31),
    },
    {
        "train_start": dt.date(2020, 1, 1),
        "train_end": dt.date(2022, 12, 31),
        "validation_start": dt.date(2023, 1, 1),
        "validation_end": dt.date(2023, 12, 31),
        "test_start": dt.date(2024, 1, 1),
        "test_end": dt.date(2024, 12, 31),
    },
    {
        "train_start": dt.date(2020, 1, 1),
        "train_end": dt.date(2024, 12, 31),
        "validation_start": dt.date(2025, 1, 1),
        "validation_end": dt.date(2025, 12, 31),
        "test_start": dt.date(2026, 1, 1),
        "test_end": dt.date(2026, 8, 13),
    },
)
_FROZEN_MAX_R15_CONFIG_SHA256 = (
    "baa384bbdcc1406fa53b6b7c689087ac03eeebf99db852f37ba9d03e40ca2c6e"
)
_COST_SECTION_KEYS = frozenset(
    {
        "schedule_version",
        "stamp_tax_source",
        "transfer_fee_source",
        "scaled_components",
        "a_share_periods",
    }
)
_COST_PERIOD_REQUIRED_KEYS = frozenset(
    {
        "effective_from",
        "commission_rate",
        "commission_min",
        "stamp_tax_sell",
        "transfer_fee",
        "slippage",
    }
)
_COST_PERIOD_KEYS = _COST_PERIOD_REQUIRED_KEYS | {"effective_to"}
_COST_DECIMAL_FIELDS = (
    "commission_rate",
    "commission_min",
    "stamp_tax_sell",
    "transfer_fee",
    "slippage",
)
_COST_SCALED_COMPONENTS = ("commission_rate", "commission_min", "slippage")


def _folds(config: Mapping[str, Any]) -> tuple[ResearchFoldV1, ...]:
    rows = cast(list[Mapping[str, Any]], config["walk_forward"]["folds"])
    return tuple(ResearchFoldV1(fold=index, **dict(row)) for index, row in enumerate(rows, 1))


def _normalize_main_config_payload(payload: bytes) -> str:
    if type(payload) is not bytes:
        raise ValueError("invalid classic config payload")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("classic config payload has a leading BOM")
    if b"\x00" in payload:
        raise ValueError("classic config payload contains NUL")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("classic config payload is not valid UTF-8") from None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _cost_periods(project_root: Path, portfolio: Mapping[str, Any]) -> tuple[AShareCostPeriod, ...]:
    return _cost_schedule_binding(project_root, portfolio)[0]


def _cost_schedule_binding(
    project_root: Path, portfolio: Mapping[str, Any]
) -> tuple[tuple[AShareCostPeriod, ...], str]:
    relative_path = portfolio.get("cost_config_relative_path")
    if type(relative_path) is not str or not relative_path:
        raise ValueError("invalid A-share cost schedule")
    path = _inside(project_root, Path(relative_path))
    return _cost_schedule_binding_from_payload(path.read_bytes())


def _cost_schedule_binding_from_payload(
    payload: bytes,
) -> tuple[tuple[AShareCostPeriod, ...], str]:
    if type(payload) is not bytes:
        raise ValueError("invalid A-share cost schedule")
    try:
        config = tomllib.loads(payload.decode("utf-8"), parse_float=Decimal)
        costs = config["costs"]
        if type(costs) is not dict or frozenset(costs) != _COST_SECTION_KEYS:
            raise ValueError
        if (
            type(costs["schedule_version"]) is not str
            or not costs["schedule_version"]
            or type(costs["stamp_tax_source"]) is not str
            or not costs["stamp_tax_source"]
            or type(costs["transfer_fee_source"]) is not str
            or not costs["transfer_fee_source"]
            or type(costs["scaled_components"]) is not list
            or tuple(costs["scaled_components"]) != _COST_SCALED_COMPONENTS
            or type(costs["a_share_periods"]) is not list
            or not costs["a_share_periods"]
        ):
            raise ValueError

        periods: list[AShareCostPeriod] = []
        canonical_periods: list[dict[str, str | None]] = []
        for row in costs["a_share_periods"]:
            if (
                type(row) is not dict
                or not _COST_PERIOD_REQUIRED_KEYS <= frozenset(row)
                or not frozenset(row) <= _COST_PERIOD_KEYS
                or type(row["effective_from"]) is not dt.date
                or (
                    "effective_to" in row
                    and type(row["effective_to"]) is not dt.date
                )
            ):
                raise ValueError
            decimals = {
                name: _cost_decimal(row[name]) for name in _COST_DECIMAL_FIELDS
            }
            period = AShareCostPeriod(
                effective_from=row["effective_from"],
                effective_to=row.get("effective_to"),
                commission_rate=decimals["commission_rate"],
                commission_min=decimals["commission_min"],
                stamp_tax_sell=decimals["stamp_tax_sell"],
                transfer_fee=decimals["transfer_fee"],
                slippage=decimals["slippage"],
            )
            periods.append(period)
            canonical_periods.append(
                {
                    "effective_from": period.effective_from.isoformat(),
                    "effective_to": (
                        None
                        if period.effective_to is None
                        else period.effective_to.isoformat()
                    ),
                    **{
                        name: _cost_decimal_text(decimals[name])
                        for name in _COST_DECIMAL_FIELDS
                    },
                }
            )
        for current, following in zip(periods, periods[1:], strict=False):
            if (
                current.effective_to is None
                or current.effective_to.toordinal() + 1
                != following.effective_from.toordinal()
            ):
                raise ValueError

        semantic_payload = {
            "schema_version": "m2-a-share-cost-semantic-v1",
            "schedule_version": costs["schedule_version"],
            "sources": {
                "stamp_tax": costs["stamp_tax_source"],
                "transfer_fee": costs["transfer_fee_source"],
            },
            "scaled_components": list(_COST_SCALED_COMPONENTS),
            "periods": canonical_periods,
        }
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, tomllib.TOMLDecodeError):
        raise ValueError("invalid A-share cost schedule") from None
    semantic_sha256 = hashlib.sha256(canonical_json_bytes(semantic_payload)).hexdigest()
    return tuple(periods), semantic_sha256


def _cost_decimal(value: object) -> Decimal:
    if type(value) is int:
        result = Decimal(cast(int, value))
    elif type(value) is Decimal:
        result = cast(Decimal, value)
    else:
        raise ValueError
    if not result.is_finite() or result < 0:
        raise ValueError
    return result


def _cost_decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _cost_schedule_input_digest(
    periods: tuple[AShareCostPeriod, ...], semantic_sha256: str
) -> ResearchInputDigestV1:
    return ResearchInputDigestV1(
        name="a-share-cost-schedule",
        rows=len(periods),
        min_date=None,
        max_date=None,
        content_sha256=semantic_sha256,
    )


def _build_input_digests(
    market_input_digests: tuple[ResearchInputDigestV1, ...],
    *,
    fifth_batch: bool,
    cost_periods: tuple[AShareCostPeriod, ...] | None,
    cost_semantic_sha256: str | None,
    sixth_batch: bool = False,
) -> tuple[ResearchInputDigestV1, ...]:
    if not fifth_batch and not sixth_batch:
        return market_input_digests
    if cost_periods is None or cost_semantic_sha256 is None:
        raise ValueError(
            "missing frozen MAX cost identity"
            if fifth_batch
            else "missing frozen sixth-batch cost identity"
        )
    return (
        _cost_schedule_input_digest(cost_periods, cost_semantic_sha256),
        *market_input_digests,
    )


def _is_lower_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and all(character in "0123456789abcdef" for character in cast(str, value))
    )


def _is_exact_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _is_exact_float(value: object, expected: float) -> bool:
    if type(value) is int:
        try:
            numeric_value = float(value)
        except OverflowError:
            return False
    elif type(value) is float:
        numeric_value = value
    else:
        return False
    return math.isfinite(numeric_value) and numeric_value == expected


def _is_non_empty_string(value: object) -> bool:
    return type(value) is str and bool(value)


def _has_exact_keys(value: object, keys: frozenset[str]) -> bool:
    return isinstance(value, Mapping) and frozenset(value) == keys


def _is_exact_sixth_fold(value: object, expected: Mapping[str, dt.date]) -> bool:
    if not _has_exact_keys(value, frozenset(expected)):
        return False
    row = cast(Mapping[str, object], value)
    return all(
        type(row[key]) is dt.date and row[key] == expected[key]
        for key in expected
    )


def _validate_sixth_batch_config(
    config: Mapping[str, Any], *, threads: int
) -> None:
    required_sections = frozenset(
        {
            "research",
            "data",
            "universe",
            "factors",
            "alpha101_sixth_batch",
            "coverage",
            "portfolio",
            "admission",
            "walk_forward",
        }
    )
    valid = False
    try:
        if not _has_exact_keys(config, required_sections):
            raise ValueError
        research = cast(Mapping[str, Any], config["research"])
        data = cast(Mapping[str, Any], config["data"])
        universe = cast(Mapping[str, Any], config["universe"])
        factors = cast(Mapping[str, Any], config["factors"])
        sixth = cast(Mapping[str, Any], config["alpha101_sixth_batch"])
        coverage = cast(Mapping[str, Any], config["coverage"])
        portfolio = cast(Mapping[str, Any], config["portfolio"])
        admission = cast(Mapping[str, Any], config["admission"])
        walk_forward = cast(Mapping[str, Any], config["walk_forward"])
        expected_research_keys = frozenset(
            {"hypothesis_id", "hypothesis", "strategy_name", "strategy_version", "random_seed"}
        )
        expected_data_keys = frozenset(
            {"snapshot_id", "warmup_start", "research_start", "research_end"}
        )
        expected_universe_keys = frozenset(
            {"freeze_start", "freeze_end", "top_n", "minimum_observations", "minimum_average_amount"}
        )
        expected_factor_keys = frozenset(
            {
                "catalog",
                "names",
                "redundancy_reference_names",
                "horizons",
                "minimum_history_rows",
                "minimum_daily_symbols",
                "groups",
                "maximum_median_absolute_rank_correlation",
            }
        )
        expected_coverage_keys = frozenset(
            {"minimum_rebalance_symbols", "minimum_median_coverage"}
        )
        expected_portfolio_keys = frozenset(
            {
                "selection_horizon_sessions",
                "rebalance_every_sessions",
                "top_k",
                "initial_cash",
                "cost_multipliers",
                "cost_config_relative_path",
                "cost_schedule_semantic_sha256",
            }
        )
        expected_admission_keys = frozenset(
            {
                "minimum_mean_test_rank_ic",
                "minimum_positive_test_folds",
                "require_direction_consistency",
                "require_positive_2x_cost_return",
            }
        )
        if not all(
            (
                _has_exact_keys(research, expected_research_keys),
                _has_exact_keys(data, expected_data_keys),
                _has_exact_keys(universe, expected_universe_keys),
                _has_exact_keys(factors, expected_factor_keys),
                _has_exact_keys(sixth, _SIXTH_BATCH_SECTION_KEYS),
                _has_exact_keys(coverage, expected_coverage_keys),
                _has_exact_keys(portfolio, expected_portfolio_keys),
                _has_exact_keys(admission, expected_admission_keys),
                _has_exact_keys(walk_forward, frozenset({"folds"})),
            )
        ):
            raise ValueError

        folds = walk_forward["folds"]
        valid = (
            _is_non_empty_string(research["hypothesis_id"])
            and research["hypothesis_id"] == _SIXTH_BATCH_HYPOTHESIS_ID
            and _is_non_empty_string(research["hypothesis"])
            and _is_non_empty_string(research["strategy_name"])
            and _is_non_empty_string(research["strategy_version"])
            and type(research["random_seed"]) is int
            and data["snapshot_id"] == _SIXTH_BATCH_SNAPSHOT_ID
            and type(data["warmup_start"]) is dt.date
            and data["warmup_start"] == dt.date(2019, 1, 1)
            and type(data["research_start"]) is dt.date
            and data["research_start"] == dt.date(2020, 1, 1)
            and type(data["research_end"]) is dt.date
            and data["research_end"] == dt.date(2026, 8, 13)
            and _is_exact_sixth_universe(universe)
            and factors["catalog"] == _SIXTH_BATCH_CATALOG
            and type(factors["names"]) is list
            and tuple(factors["names"]) == SIXTH_BATCH_FACTOR_NAMES
            and type(factors["redundancy_reference_names"]) is list
            and tuple(factors["redundancy_reference_names"])
            == _SIXTH_BATCH_REFERENCE_NAMES
            and type(factors["horizons"]) is list
            and all(type(value) is int for value in factors["horizons"])
            and tuple(factors["horizons"]) == (1, 5, 20)
            and _is_exact_int(factors["minimum_history_rows"], 120)
            and _is_exact_int(factors["minimum_daily_symbols"], 100)
            and _is_exact_int(factors["groups"], 5)
            and _is_exact_float(
                factors["maximum_median_absolute_rank_correlation"], 0.80
            )
            and sixth["schema_version"] == "m2-alpha101-sixth-batch-v1"
            and sixth["hypothesis_id"] == _SIXTH_BATCH_HYPOTHESIS_ID
            and type(sixth["factors"]) is list
            and tuple(sixth["factors"]) == SIXTH_BATCH_FACTOR_NAMES
            and _is_exact_int(sixth["correlation_window_sessions"], 10)
            and _is_exact_int(sixth["delta_lag_sessions"], 1)
            and sixth["alpha041_price_basis"] == "raw_cny_per_share"
            and sixth["alpha041_vwap_formula"] == "amount_div_volume"
            and sixth["direction_policy"] == "validation_only_per_fold"
            and _is_exact_int(sixth["trial_budget"], 3)
            and _is_exact_int(sixth["trial_delta"], 3)
            and _is_exact_int(sixth["attempt_ordinal"], 1)
            and _is_exact_int(coverage["minimum_rebalance_symbols"], 100)
            and _is_exact_float(coverage["minimum_median_coverage"], 0.80)
            and _is_exact_int(portfolio["selection_horizon_sessions"], 20)
            and _is_exact_int(portfolio["rebalance_every_sessions"], 20)
            and _is_exact_int(portfolio["top_k"], 50)
            and _is_exact_float(portfolio["initial_cash"], 1_000_000.0)
            and type(portfolio["cost_multipliers"]) is list
            and tuple(
                _is_exact_float(value, expected)
                for value, expected in zip(
                    portfolio["cost_multipliers"], (0.5, 1.0, 2.0), strict=False
                )
            )
            == (True, True, True)
            and len(portfolio["cost_multipliers"]) == 3
            and portfolio["cost_config_relative_path"]
            == "configs/research/m3_qlib_example.toml"
            and portfolio["cost_schedule_semantic_sha256"]
            == _SIXTH_BATCH_COST_SEMANTIC_SHA256
            and _is_exact_float(admission["minimum_mean_test_rank_ic"], 0.01)
            and _is_exact_int(admission["minimum_positive_test_folds"], 2)
            and admission["require_direction_consistency"] is True
            and admission["require_positive_2x_cost_return"] is True
            and type(folds) is list
            and len(folds) == 3
            and all(
                _is_exact_sixth_fold(value, expected)
                for value, expected in zip(
                    folds, _SIXTH_BATCH_FROZEN_FOLDS, strict=True
                )
            )
            and type(threads) is int
            and 1 <= threads <= 2
        )
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        valid = False
    if not valid:
        raise ValueError("invalid classic-factor config")


def _is_exact_sixth_universe(universe: Mapping[str, Any]) -> bool:
    return (
        type(universe["freeze_start"]) is dt.date
        and universe["freeze_start"] == dt.date(2019, 1, 1)
        and type(universe["freeze_end"]) is dt.date
        and universe["freeze_end"] == dt.date(2019, 12, 31)
        and _is_exact_int(universe["top_n"], 800)
        and _is_exact_int(universe["minimum_observations"], 120)
        and _is_exact_float(universe["minimum_average_amount"], 20_000_000.0)
    )


def _validate_config(config: Mapping[str, Any], *, threads: int) -> None:
    sixth_factors = config.get("factors") if isinstance(config, Mapping) else None
    if (
        isinstance(sixth_factors, Mapping)
        and type(sixth_factors.get("names")) is list
        and tuple(sixth_factors["names"]) == SIXTH_BATCH_FACTOR_NAMES
    ):
        _validate_sixth_batch_config(config, threads=threads)
        return
    factor_config = cast(Mapping[str, Any], config["factors"])
    market_risk = cast(Mapping[str, Any], config.get("market_risk", {}))
    max_lottery = cast(Mapping[str, Any], config.get("max_lottery", {}))
    coverage = cast(Mapping[str, Any], config.get("coverage", {}))
    portfolio = cast(Mapping[str, Any], config["portfolio"])
    names = tuple(cast(list[str], factor_config["names"]))
    first_batch = names == CLASSIC_FACTOR_NAMES and "catalog" not in factor_config
    second_batch = (
        names == SECOND_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "alpha158_second_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
    )
    third_batch = (
        names == THIRD_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "alpha158_third_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES + SECOND_BATCH_FACTOR_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
    )
    fourth_batch = (
        names == FOURTH_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "alpha158_fourth_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES + SECOND_BATCH_FACTOR_NAMES + THIRD_BATCH_FACTOR_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
        and coverage.get("minimum_rebalance_symbols") == 100
        and float(coverage.get("minimum_median_coverage", 0.0)) == 0.80
    )
    downside_beta = (
        names == DOWNSIDE_BETA_FACTOR_NAMES
        and factor_config.get("catalog") == "downside_beta_60_vs_510300_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES + MARKET_RISK_CONTROL_NAMES
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
        and market_risk.get("benchmark") == "510300.SH"
        and market_risk.get("window_sessions") == 60
        and market_risk.get("minimum_down_market_observations") == 15
        and market_risk.get("annualization_sessions") == 252
        and float(market_risk.get("minimum_market_variance", 0.0)) == 1e-12
        and market_risk.get("expected_direction") == -1
        and coverage.get("minimum_rebalance_symbols") == 100
        and float(coverage.get("minimum_median_coverage", 0.0)) == 0.80
    )
    fifth_batch = (
        names == FIFTH_BATCH_FACTOR_NAMES
        and factor_config.get("catalog") == "max_lottery_fifth_batch_v1"
        and tuple(cast(list[str], factor_config["redundancy_reference_names"]))
        == CLASSIC_FACTOR_NAMES
        + SECOND_BATCH_FACTOR_NAMES
        + THIRD_BATCH_FACTOR_NAMES
        + FOURTH_BATCH_FACTOR_NAMES
        + ("liquidity_20",)
        and float(factor_config["maximum_median_absolute_rank_correlation"]) == 0.80
        and max_lottery.get("window_sessions") == 20
        and max_lottery.get("return_type") == "simple_adjusted_close"
        and max_lottery.get("expected_direction") == -1
        and max_lottery.get("trial_budget") == 1
        and max_lottery.get("trial_delta") == 0
        and coverage.get("minimum_rebalance_symbols") == 100
        and float(coverage.get("minimum_median_coverage", 0.0)) == 0.80
        and _is_lower_hex64(portfolio.get("cost_schedule_semantic_sha256"))
    )
    if (
        not (
            first_batch
            or second_batch
            or third_batch
            or fourth_batch
            or downside_beta
            or fifth_batch
        )
        or tuple(cast(list[int], config["factors"]["horizons"])) != (1, 5, 20)
        or tuple(float(value) for value in portfolio["cost_multipliers"])
        != (0.5, 1.0, 2.0)
        or portfolio["selection_horizon_sessions"] != 20
        or type(threads) is not int
        or not 1 <= threads <= (2 if fifth_batch else 4)
    ):
        raise ValueError("invalid classic-factor config")


