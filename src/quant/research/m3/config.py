"""Strict, single-source loader and identity hashes for the M3 research config."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import stat
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TypeAlias, cast
from urllib.parse import unquote, urlsplit

ConfigSelector = Literal[
    "full",
    "g1",
    "snapshot",
    "provider",
    "scientific",
    "provider-validation",
    "label-reconciliation",
    "acceptance",
]
FieldKind: TypeAlias = Literal[
    "string", "bool", "int", "float", "date", "str_array", "int_array", "float_array"
]

_DERIVED_SELECTORS = frozenset({
    "g1",
    "snapshot",
    "provider",
    "scientific",
    "provider-validation",
    "label-reconciliation",
    "acceptance",
    "tracking-target",
})
_CONFIG_SELECTORS = frozenset(_DERIVED_SELECTORS - {"tracking-target"})
_HASH_VERSION = "m3-config-hash-v1"
_MISSING = object()


@dataclass(frozen=True, order=True)
class ConfigIssue:
    """One sanitized, deterministic configuration violation."""

    code: str
    dotted_path: str
    message: str


class M3ConfigError(ValueError):
    """All independently detectable M3 configuration issues."""

    def __init__(self, issues: Iterable[ConfigIssue]) -> None:
        ordered = tuple(sorted(set(issues), key=lambda item: (
            item.dotted_path,
            item.code,
            item.message,
        )))
        if not ordered:
            raise ValueError("M3ConfigError requires at least one issue")
        self.issues = ordered
        super().__init__(f"M3 configuration rejected with {len(ordered)} issue(s)")

    def __repr__(self) -> str:
        return f"M3ConfigError(issue_count={len(self.issues)})"


@dataclass(frozen=True)
class FieldSpec:
    """Machine-readable contract for one normalized TOML assignment shape."""

    kind: FieldKind
    selectors: frozenset[str]
    required: bool = True
    literal: object = _MISSING
    minimum: int | float | None = None
    maximum: int | float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True
    non_empty: bool = False


def _field_specs() -> dict[str, FieldSpec]:
    specs: dict[str, FieldSpec] = {}

    def add(
        path: str,
        kind: FieldKind,
        selectors: str = "",
        *,
        required: bool = True,
        literal: object = _MISSING,
        minimum: int | float | None = None,
        maximum: int | float | None = None,
        minimum_inclusive: bool = True,
        maximum_inclusive: bool = True,
        non_empty: bool = False,
    ) -> None:
        if path in specs:
            raise AssertionError(f"duplicate M3 field spec: {path}")
        specs[path] = FieldSpec(
            kind=kind,
            selectors=frozenset(selectors.split()) if selectors else frozenset(),
            required=required,
            literal=literal,
            minimum=minimum,
            maximum=maximum,
            minimum_inclusive=minimum_inclusive,
            maximum_inclusive=maximum_inclusive,
            non_empty=non_empty,
        )

    # meta
    add(
        "meta.config_version",
        "string",
        "g1 snapshot provider scientific provider-validation label-reconciliation acceptance",
        literal="1.0.0",
    )
    add("meta.purpose", "string", non_empty=True)
    add("meta.enabled", "bool")

    # data
    add("data.universe", "string", "snapshot scientific", literal="CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1")
    add("data.benchmark", "string", "snapshot scientific", literal="510300.SH")
    add("data.source", "string", "snapshot scientific", literal="tushare")
    add("data.start_date", "date", "snapshot scientific")
    add("data.end_date", "date", "snapshot scientific")
    add("data.market", "string", "snapshot provider scientific", literal="CN")
    add("data.frequency", "string", "snapshot provider scientific", literal="day")
    add("data.minimum_train_sessions", "int", "snapshot scientific", minimum=1)
    add("data.minimum_cross_section_symbols", "int", "snapshot scientific", minimum=2)
    add(
        "data.required_fields",
        "str_array",
        "snapshot scientific",
        literal=("open", "high", "low", "close", "volume", "amount", "adj_factor"),
    )
    add(
        "data.provider_fields",
        "str_array",
        "provider scientific",
        literal=("open", "high", "low", "close", "vwap", "volume", "factor"),
    )
    add("data.provider_format", "string", "provider scientific", literal="qlib_bin")
    add("data.snapshot_hash", "string", "snapshot scientific", literal="sha256")

    # Qlib supply-chain and runtime policy
    add("runtime.qlib.version", "string", "scientific", literal="0.9.7")
    add("runtime.qlib.supported_python", "string", literal=">=3.8,<3.13")
    add(
        "runtime.qlib.dump_script_url",
        "string",
        literal="https://raw.githubusercontent.com/microsoft/qlib/v0.9.7/scripts/dump_bin.py",
    )
    add(
        "runtime.qlib.dump_script_sha256",
        "string",
        literal="b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f",
    )
    add("runtime.qlib.dump_script_bytes", "int", literal=21847)

    # feature and label science
    add("features.handler", "string", "scientific", literal="Alpha158")
    add("features.feature_version", "string", "scientific", literal="alpha158_v1")
    add("features.expected_feature_count", "int", "scientific", literal=158)
    add("features.minimum_scorable_coverage", "float", "scientific", minimum=0.0, maximum=1.0)
    add("features.processor_policy", "string", "scientific", literal="none_raw_features")
    add("features.missing_value_policy", "string", "scientific", literal="inf_to_nan_lightgbm_native")
    add(
        "features.authoritative_label_source",
        "string",
        "scientific",
        literal="quant_forward_return_label",
    )
    add("labels.horizons_sessions", "int_array", "scientific", literal=(5, 10))
    add("labels.entry_offset_sessions", "int", "scientific", literal=1)
    add("labels.entry_field", "string", "scientific", literal="open")
    add("labels.exit_field", "string", "scientific", literal="close")
    add("labels.relative_to_benchmark", "bool", "scientific", literal=True)
    add(
        "labels.label_version",
        "string",
        "scientific",
        literal="theoretical_next_open_to_h_close_510300_etf_hfq_proxy_excess_v3",
    )

    # G1 identity; retry/rate fields deliberately have no derived selector.
    g1_literals: tuple[tuple[str, str, object], ...] = (
        ("index_weight_code", "string", "000300.SH"),
        ("benchmark_code", "string", "510300.SH"),
        (
            "benchmark_mode",
            "string",
            "TRADEABLE_ETF_TOTAL_RETURN_PROXY",
        ),
        (
            "benchmark_method_version",
            "string",
            "tushare_510300_fund_daily_fund_adj_hfq_v1",
        ),
        (
            "benchmark_dividend_reconciliation_version",
            "string",
            "tushare_fund_div_implemented_cash_v1",
        ),
        ("membership_method_version", "string", "tushare_monthly_observed_next_session_close_v1"),
        ("session_market", "string", "SH"),
        ("expected_constituent_count", "int", 300),
        ("membership_warmup_months", "int", 1),
    )
    for name, kind, value in g1_literals:
        add(f"g1_backfill.{name}", cast(FieldKind, kind), "g1", literal=value)
    add("g1_backfill.feature_warmup_sessions", "int", "g1 snapshot", literal=60)
    add("g1_backfill.label_tail_sessions", "int", "g1 snapshot", minimum=1)
    add("g1_backfill.request_rate_per_minute", "int", minimum=1)
    add("g1_backfill.max_attempts", "int", minimum=1)
    add("g1_backfill.retry_base_seconds", "float", minimum=0.0)
    endpoint_limits = {
        "daily": 6000,
        "adj_factor": 6000,
        "index_daily": 5000,
        "index_weight": 5000,
        "suspend_d": 5000,
        "stk_limit": 5800,
        "dividend": 5000,
        "fund_daily": 5000,
        "fund_adj": 2000,
        "fund_div": 5000,
    }
    for name, value in endpoint_limits.items():
        add(f"g1_backfill.endpoint_row_limits.{name}", "int", "g1", literal=value)
    add("g1_backfill.reconciliation.reference_source", "string", "g1", literal="baostock")
    add("g1_backfill.reconciliation.sample_symbols", "int", "g1", literal=30)
    add("g1_backfill.reconciliation.dates_per_symbol", "int", "g1", literal=20)
    add("g1_backfill.reconciliation.price_atol", "float", "g1", minimum=0.0)
    add("g1_backfill.reconciliation.price_rtol", "float", "g1", minimum=0.0)
    add("g1_backfill.reconciliation.volume_rtol", "float", "g1", minimum=0.0)
    add(
        "g1_backfill.reconciliation.max_mismatch_rate",
        "float",
        "g1",
        minimum=0.0,
        maximum=1.0,
    )
    add(
        "g1_backfill.corporate_action_reconciliation.factor_ratio_rtol",
        "float",
        "g1",
        minimum=0.0,
        maximum=0.01,
    )

    # walk-forward
    for name in ("train_sessions", "validation_sessions", "test_sessions", "step_sessions", "embargo_sessions"):
        add(f"walk_forward.{name}", "int", "scientific", minimum=1)
    add("walk_forward.selection_metric", "string", "scientific", literal="validation_l2")
    add("walk_forward.test_overlap_policy", "string", "scientific", literal="ERROR")

    # LightGBM
    fixed_model_strings = {
        "model_version": "alpha158_lgb_v1",
        "objective": "regression",
        "metric": "l2",
        "device_type": "cpu",
    }
    for name, value in fixed_model_strings.items():
        add(f"model.lightgbm.{name}", "string", "scientific", literal=value)
    add("model.lightgbm.learning_rate", "float", "scientific", minimum=0.0, minimum_inclusive=False)
    add("model.lightgbm.num_leaves", "int", "scientific", minimum=2)
    add("model.lightgbm.max_depth", "int", "scientific")
    add("model.lightgbm.feature_fraction", "float", "scientific", minimum=0.0, maximum=1.0, minimum_inclusive=False)
    add("model.lightgbm.bagging_fraction", "float", "scientific", minimum=0.0, maximum=1.0, minimum_inclusive=False)
    add("model.lightgbm.bagging_freq", "int", "scientific", minimum=0)
    add("model.lightgbm.num_boost_round", "int", "scientific", minimum=1)
    add("model.lightgbm.early_stopping_rounds", "int", "scientific", minimum=1)
    add("model.lightgbm.early_stopping_min_delta", "float", "scientific", minimum=0.0)
    for name in ("seed", "data_random_seed", "feature_fraction_seed", "bagging_seed"):
        add(f"model.lightgbm.{name}", "int", "scientific", minimum=0)
    add("model.lightgbm.deterministic", "bool", "scientific", literal=True)
    add("model.lightgbm.force_col_wise", "bool", "scientific", literal=True)
    add("model.lightgbm.num_threads", "int", "scientific", minimum=1)

    # portfolio, backtest, evaluation
    add("portfolio.strategy", "string", "scientific", literal="topk")
    add("portfolio.strategy_version", "string", "scientific", literal="m3_topk_v1")
    add("portfolio.top_k", "int", "scientific", minimum=1)
    add("portfolio.cash_buffer", "float", "scientific", minimum=0.0, maximum=1.0, maximum_inclusive=False)
    add("portfolio.max_weight", "float", "scientific", minimum=0.0, maximum=1.0, minimum_inclusive=False)
    add("portfolio.rebalance", "string", "scientific", literal="daily_signal_next_session_open")
    add("backtest.a_share.initial_cash", "float", "scientific", minimum=0.0, minimum_inclusive=False)
    add("backtest.a_share.price_tick", "float", "scientific", minimum=0.0, minimum_inclusive=False)
    add("backtest.a_share.target_omission_means_zero", "bool", "scientific", literal=True)
    backtest_strings = {
        "cash_entitlement_fallback": "ERROR",
        "stock_entitlement_fallback": "ERROR",
        "unexplained_factor_change": "ERROR",
        "partial_suspension_open_policy": "REQUIRE_EXPLICIT_OPEN_TRADABLE",
        "dividend_tax_policy": "GROSS_IGNORE_PERSONAL_HOLDING_PERIOD_TAX",
        "rights_policy": "ERROR_IF_RELEVANT",
    }
    for name, value in backtest_strings.items():
        add(f"backtest.a_share.{name}", "string", "scientific", literal=value)
    add("backtest.a_share.force_liquidation", "bool", "scientific", literal=False)
    add("backtest.a_share.friction_multipliers", "float_array", "scientific", literal=(0.5, 1.0, 2.0))
    add("evaluation.minimum_ic_symbols", "int", "scientific", minimum=2)

    # independent validation identities
    add("validation.provider.sample_symbols", "int", "provider-validation", literal=3)
    add("validation.provider.sample_dates_per_symbol", "int", "provider-validation", literal=20)
    add("validation.provider.gap_dates_per_symbol", "int", "provider-validation", literal=5)
    add(
        "validation.provider.sampling_policy_version",
        "string",
        "provider-validation",
        literal="provider_market_stratified_hash_first_last_v1",
    )
    add(
        "validation.labels.reconciliation_version",
        "string",
        "label-reconciliation",
        literal="qlib_raw_plus_independent_benchmark_v1",
    )
    for name in ("qlib_expression_atol", "benchmark_return_atol", "label_return_atol"):
        add(f"validation.labels.{name}", "float", "label-reconciliation", minimum=0.0)

    # cost schedule
    add("costs.schedule_version", "string", "scientific", literal="a_share_research_cost_schedule_v1")
    add(
        "costs.stamp_tax_source",
        "string",
        "scientific",
        literal="https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm",
    )
    add(
        "costs.transfer_fee_source",
        "string",
        "scientific",
        literal="https://www.xinhuanet.com/2022-04/28/c_1128605983.htm",
    )
    add(
        "costs.scaled_components",
        "str_array",
        "scientific",
        literal=("commission_rate", "commission_min", "slippage"),
    )
    add("costs.a_share_periods[].effective_from", "date", "scientific")
    add("costs.a_share_periods[].effective_to", "date", "scientific", required=False)
    for name in ("commission_rate", "commission_min", "stamp_tax_sell", "transfer_fee", "slippage"):
        add(f"costs.a_share_periods[].{name}", "float", "scientific", minimum=0.0)

    # tracking target and non-identity runtime output policy
    add("tracking.experiment_name", "string", "tracking-target", non_empty=True)
    add("tracking.tracking_uri", "string", "tracking-target", non_empty=True)
    add("tracking.artifact_root", "string", non_empty=True)
    add("tracking.log_model", "bool", literal=True)
    add("tracking.log_predictions", "bool", literal=True)
    add("tracking.log_dataset_manifest", "bool", literal=True)

    # acceptance
    add("acceptance.reproducibility_score_atol", "float", "acceptance", minimum=0.0)
    add("acceptance.reproducibility_metric_atol", "float", "acceptance", minimum=0.0)
    add(
        "acceptance.required_metrics",
        "str_array",
        "acceptance",
        literal=(
            "evaluation.test_rank_ic",
            "evaluation.test_rank_icir",
            "backtest.1p0x.test_net_excess_return",
            "backtest.1p0x.test_turnover",
            "backtest.1p0x.test_max_drawdown",
        ),
    )
    for name in (
        "minimum_feature_coverage",
        "minimum_prediction_coverage",
        "minimum_label_coverage",
        "minimum_evaluation_coverage",
        "minimum_computable_ic_date_ratio",
    ):
        add(f"acceptance.{name}", "float", "acceptance", minimum=0.0, maximum=1.0)

    if len(specs) != 144:
        raise AssertionError(f"M3 field spec closure must contain 144 shapes, got {len(specs)}")
    return specs


_FIELD_SPECS = MappingProxyType(_field_specs())


@dataclass(frozen=True)
class LoadedM3Config:
    """Validated, recursively immutable M3 document and its nine identities."""

    document: Mapping[str, object]
    config_version: str
    full_config_sha256: str
    g1_config_sha256: str
    snapshot_config_sha256: str
    provider_config_sha256: str
    scientific_config_sha256: str
    provider_validation_config_sha256: str
    label_reconciliation_config_sha256: str
    acceptance_config_sha256: str
    canonical_tracking_uri: str
    tracking_target_key: str

    def section(self, name: str) -> Mapping[str, object]:
        """Return one required, read-only root section without implicit defaults."""
        value = self.document[name]
        if not isinstance(value, Mapping):
            raise TypeError(f"M3 section is not a mapping: {name}")
        return cast(Mapping[str, object], value)


def load_m3_config(path: Path) -> LoadedM3Config:
    """Read, strictly validate, normalize, freeze, and hash one M3 TOML file."""
    raw = _read_config_bytes(path)
    if raw is None:
        raise M3ConfigError((ConfigIssue(
            "CONFIG_IO_ERROR",
            "config",
            "configuration must be a readable regular UTF-8 TOML file",
        ),))

    parsed = _parse_toml(raw)
    if parsed is None:
        raise M3ConfigError((ConfigIssue(
            "TOML_PARSE_ERROR",
            "config",
            "configuration must be valid UTF-8 TOML",
        ),))

    normalized = _validate_and_normalize(parsed)
    return _loaded_from_normalized(normalized)


def _read_config_bytes(path: Path) -> bytes | None:
    """Return bytes or a sentinel so the public error has no sensitive exception chain."""
    try:
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            raise OSError
        return path.read_bytes()
    except (OSError, ValueError, TypeError):
        return None


def _parse_toml(raw: bytes) -> dict[str, object] | None:
    """Parse without allowing the parser's value-bearing exception to escape."""
    try:
        return cast(dict[str, object], tomllib.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def canonical_config_sha256(
    *, selector: ConfigSelector, document: Mapping[str, object]
) -> str:
    """Validate a complete document and hash its internally selected projection."""
    if selector not in _CONFIG_SELECTORS | {"full"}:
        raise ValueError(f"unknown M3 config selector: {selector}")
    normalized = _validate_and_normalize(document)
    return _trusted_config_sha256(selector, normalized)


def canonical_tracking_target_key(*, tracking_uri: str, experiment_name: str) -> str:
    """Validate and hash a canonical MLflow target without retaining URI plaintext."""
    issues: list[ConfigIssue] = []
    if type(experiment_name) is not str:
        issues.append(ConfigIssue("TYPE_ERROR", "tracking.experiment_name", "expected string"))
    elif not experiment_name.strip():
        issues.append(ConfigIssue("EMPTY_STRING", "tracking.experiment_name", "expected non-empty string"))
    else:
        _validate_safe_string("tracking.experiment_name", experiment_name, issues)

    canonical_uri: str | None = None
    if type(tracking_uri) is not str:
        issues.append(ConfigIssue("TYPE_ERROR", "tracking.tracking_uri", "expected string"))
    elif not tracking_uri.strip():
        issues.append(ConfigIssue("EMPTY_STRING", "tracking.tracking_uri", "expected non-empty string"))
    else:
        _validate_safe_string("tracking.tracking_uri", tracking_uri, issues)
        canonical_uri = _canonical_tracking_uri(tracking_uri, issues)
    if issues:
        raise M3ConfigError(issues)
    assert canonical_uri is not None
    envelope = {
        "hash_version": _HASH_VERSION,
        "selector": "tracking-target",
        "canonical_tracking_uri": canonical_uri,
        "experiment_name": experiment_name,
    }
    return _sha256_json(envelope)


def _loaded_from_normalized(document: dict[str, object]) -> LoadedM3Config:
    tracking = cast(dict[str, object], document["tracking"])
    uri = cast(str, tracking["tracking_uri"])
    experiment = cast(str, tracking["experiment_name"])
    frozen = cast(Mapping[str, object], _freeze(document))
    return LoadedM3Config(
        document=frozen,
        config_version=cast(str, cast(Mapping[str, object], frozen["meta"])["config_version"]),
        full_config_sha256=_trusted_config_sha256("full", document),
        g1_config_sha256=_trusted_config_sha256("g1", document),
        snapshot_config_sha256=_trusted_config_sha256("snapshot", document),
        provider_config_sha256=_trusted_config_sha256("provider", document),
        scientific_config_sha256=_trusted_config_sha256("scientific", document),
        provider_validation_config_sha256=_trusted_config_sha256("provider-validation", document),
        label_reconciliation_config_sha256=_trusted_config_sha256("label-reconciliation", document),
        acceptance_config_sha256=_trusted_config_sha256("acceptance", document),
        canonical_tracking_uri=uri,
        tracking_target_key=canonical_tracking_target_key(
            tracking_uri=uri,
            experiment_name=experiment,
        ),
    )


def _validate_and_normalize(document: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise M3ConfigError((ConfigIssue("TYPE_ERROR", "config", "expected mapping"),))
    mutable = _thaw(document)
    if not isinstance(mutable, dict):
        raise M3ConfigError((ConfigIssue("TYPE_ERROR", "config", "expected mapping"),))
    issues: list[ConfigIssue] = []

    _scan_secrets(mutable, issues)
    observed = list(_iter_assignment_leaves(mutable, issues))
    observed_shapes: dict[str, list[tuple[tuple[str | int, ...], object]]] = {}
    for tokens, value in observed:
        shape = _shape(tokens)
        observed_shapes.setdefault(shape, []).append((tokens, value))
        if shape not in _FIELD_SPECS:
            issues.append(ConfigIssue("UNKNOWN_KEY", _display_path(tokens), "key is not allowed"))

    for shape, spec in _FIELD_SPECS.items():
        entries = observed_shapes.get(shape, [])
        if "[]" not in shape:
            if not entries and spec.required:
                issues.append(ConfigIssue("MISSING_KEY", shape, "required key is missing"))
            elif len(entries) > 1:
                issues.append(ConfigIssue("VALUE_ERROR", shape, "key must occur exactly once"))
        for tokens, value in entries:
            _validate_field(_display_path(tokens), value, spec, issues)

    periods = _get_path(mutable, ("costs", "a_share_periods"))
    _validate_period_container(periods, issues)
    _validate_cross_fields(mutable, issues)

    tracking_uri = _get_path(mutable, ("tracking", "tracking_uri"))
    if type(tracking_uri) is str:
        canonical_uri = _canonical_tracking_uri(tracking_uri, issues)
        if canonical_uri is not None:
            cast(dict[str, object], mutable["tracking"])["tracking_uri"] = canonical_uri
    artifact_root = _get_path(mutable, ("tracking", "artifact_root"))
    if type(artifact_root) is str:
        _validate_relative_posix_path(
            artifact_root,
            "tracking.artifact_root",
            issues,
            code="UNSAFE_PATH",
        )

    if issues:
        raise M3ConfigError(issues)
    return cast(dict[str, object], _normalize_scalars(mutable))


def _iter_assignment_leaves(
    value: object,
    issues: list[ConfigIssue],
    tokens: tuple[str | int, ...] = (),
) -> Iterable[tuple[tuple[str | int, ...], object]]:
    if isinstance(value, Mapping):
        if not value and tokens:
            yield tokens, value
        for key, child in value.items():
            if type(key) is not str:
                issues.append(ConfigIssue("TYPE_ERROR", _display_path(tokens), "mapping keys must be strings"))
                continue
            yield from _iter_assignment_leaves(child, issues, (*tokens, key))
        return
    if isinstance(value, (list, tuple)) and _shape(tokens) == "costs.a_share_periods":
        if not value:
            yield tokens, value
        for index, child in enumerate(value):
            if not isinstance(child, Mapping):
                yield (*tokens, index), child
            else:
                yield from _iter_assignment_leaves(child, issues, (*tokens, index))
        return
    yield tokens, value


def _validate_field(path: str, value: object, spec: FieldSpec, issues: list[ConfigIssue]) -> None:
    expected = spec.kind
    valid_type = False
    comparable: object = value
    if expected == "string":
        valid_type = type(value) is str
    elif expected == "bool":
        valid_type = type(value) is bool
    elif expected == "int":
        valid_type = type(value) is int
    elif expected == "float":
        valid_type = type(value) is float
    elif expected == "date":
        valid_type = type(value) is dt.date
    elif expected in {"str_array", "int_array", "float_array"}:
        valid_type = isinstance(value, (list, tuple))
        if valid_type:
            item_type = {"str_array": str, "int_array": int, "float_array": float}[expected]
            valid_type = all(type(item) is item_type for item in cast(Sequence[object], value))
            comparable = tuple(cast(Sequence[object], value))

    if not valid_type:
        issues.append(ConfigIssue("TYPE_ERROR", path, f"expected strict {expected}"))
        return
    if expected == "string" and not cast(str, value).strip():
        issues.append(ConfigIssue("EMPTY_STRING", path, "expected non-empty string"))
    if expected in {"float", "float_array"}:
        values = (value,) if expected == "float" else cast(Sequence[object], value)
        if any(not math.isfinite(cast(float, item)) for item in values):
            issues.append(ConfigIssue("NON_FINITE", path, "expected finite float"))
            return
    if spec.non_empty and isinstance(comparable, (str, tuple)) and not comparable:
        issues.append(ConfigIssue("EMPTY_STRING", path, "expected non-empty value"))
    if spec.literal is not _MISSING and comparable != spec.literal:
        issues.append(ConfigIssue("VALUE_ERROR", path, "value does not match the versioned contract"))
    if spec.minimum is not None and isinstance(value, (int, float)) and type(value) is not bool:
        bad = value < spec.minimum if spec.minimum_inclusive else value <= spec.minimum
        if bad:
            issues.append(ConfigIssue("VALUE_ERROR", path, "value is below the allowed range"))
    if spec.maximum is not None and isinstance(value, (int, float)) and type(value) is not bool:
        bad = value > spec.maximum if spec.maximum_inclusive else value >= spec.maximum
        if bad:
            issues.append(ConfigIssue("VALUE_ERROR", path, "value is above the allowed range"))


def _validate_period_container(
    periods: object,
    issues: list[ConfigIssue],
) -> None:
    path = "costs.a_share_periods"
    if periods is _MISSING:
        issues.append(ConfigIssue("MISSING_KEY", path, "required array table is missing"))
        return
    if not isinstance(periods, (list, tuple)):
        issues.append(ConfigIssue("TYPE_ERROR", path, "expected non-empty array of tables"))
        return
    if not periods:
        issues.append(ConfigIssue("VALUE_ERROR", path, "expected non-empty array of tables"))
        return
    for index, period in enumerate(periods):
        item_path = f"{path}[{index}]"
        if not isinstance(period, Mapping):
            issues.append(ConfigIssue("TYPE_ERROR", item_path, "expected table"))
            continue
        required_names = {
            "effective_from",
            "commission_rate",
            "commission_min",
            "stamp_tax_sell",
            "transfer_fee",
            "slippage",
        }
        if index < len(periods) - 1:
            required_names.add("effective_to")
        for name in required_names:
            if name not in period:
                issues.append(ConfigIssue("MISSING_KEY", f"{item_path}.{name}", "required key is missing"))
        if index == len(periods) - 1 and "effective_to" in period:
            issues.append(ConfigIssue(
                "CROSS_FIELD_ERROR",
                f"{item_path}.effective_to",
                "final cost period must remain open-ended",
            ))


def _validate_cross_fields(document: dict[str, object], issues: list[ConfigIssue]) -> None:
    def value(*parts: str) -> object:
        return _get_path(document, tuple(parts))

    start = value("data", "start_date")
    end = value("data", "end_date")
    if type(start) is dt.date and type(end) is dt.date and start > end:
        issues.append(ConfigIssue("CROSS_FIELD_ERROR", "data.end_date", "end date must not precede start date"))

    horizons = value("labels", "horizons_sessions")
    embargo = value("walk_forward", "embargo_sessions")
    label_tail = value("g1_backfill", "label_tail_sessions")
    if _strict_int_sequence(horizons):
        horizon_values = cast(Sequence[int], horizons)
        if type(embargo) is int and embargo < max(horizon_values):
            issues.append(ConfigIssue("CROSS_FIELD_ERROR", "walk_forward.embargo_sessions", "embargo must cover the maximum label horizon"))
        if type(label_tail) is int and label_tail < max(horizon_values):
            issues.append(ConfigIssue("CROSS_FIELD_ERROR", "g1_backfill.label_tail_sessions", "label tail must cover the maximum label horizon"))

    test_sessions = value("walk_forward", "test_sessions")
    step_sessions = value("walk_forward", "step_sessions")
    if type(test_sessions) is int and type(step_sessions) is int and step_sessions < test_sessions:
        issues.append(ConfigIssue("CROSS_FIELD_ERROR", "walk_forward.step_sessions", "step must prevent overlapping test folds"))
    train = value("walk_forward", "train_sessions")
    minimum_train = value("data", "minimum_train_sessions")
    if type(train) is int and type(minimum_train) is int and train < minimum_train:
        issues.append(ConfigIssue("CROSS_FIELD_ERROR", "walk_forward.train_sessions", "training window must meet readiness minimum"))

    top_k = value("portfolio", "top_k")
    minimum_cross = value("data", "minimum_cross_section_symbols")
    expected_count = value("g1_backfill", "expected_constituent_count")
    if type(top_k) is int and type(minimum_cross) is int and top_k > minimum_cross:
        issues.append(ConfigIssue("CROSS_FIELD_ERROR", "portfolio.top_k", "top_k must not exceed the readiness cross-section minimum"))
    if type(minimum_cross) is int and type(expected_count) is int and minimum_cross > expected_count:
        issues.append(ConfigIssue("CROSS_FIELD_ERROR", "data.minimum_cross_section_symbols", "cross-section minimum must not exceed expected constituents"))

    expression_atol = value("validation", "labels", "qlib_expression_atol")
    benchmark_atol = value("validation", "labels", "benchmark_return_atol")
    label_atol = value("validation", "labels", "label_return_atol")
    if all(type(item) is float and math.isfinite(item) for item in (expression_atol, benchmark_atol, label_atol)):
        if cast(float, expression_atol) > cast(float, label_atol):
            issues.append(ConfigIssue("CROSS_FIELD_ERROR", "validation.labels.qlib_expression_atol", "expression tolerance must not exceed label tolerance"))
        if cast(float, benchmark_atol) > cast(float, label_atol):
            issues.append(ConfigIssue("CROSS_FIELD_ERROR", "validation.labels.benchmark_return_atol", "benchmark tolerance must not exceed label tolerance"))

    rounds = value("model", "lightgbm", "num_boost_round")
    early = value("model", "lightgbm", "early_stopping_rounds")
    depth = value("model", "lightgbm", "max_depth")
    if type(rounds) is int and type(early) is int and early >= rounds:
        issues.append(ConfigIssue("CROSS_FIELD_ERROR", "model.lightgbm.early_stopping_rounds", "early stopping must be less than boost rounds"))
    if type(depth) is int and depth != -1 and depth <= 0:
        issues.append(ConfigIssue("VALUE_ERROR", "model.lightgbm.max_depth", "depth must be -1 or positive"))

    periods = value("costs", "a_share_periods")
    if isinstance(periods, (list, tuple)) and periods and all(isinstance(item, Mapping) for item in periods):
        typed_periods = cast(Sequence[Mapping[str, object]], periods)
        first_from = typed_periods[0].get("effective_from")
        if type(start) is dt.date and type(first_from) is dt.date and first_from > start:
            issues.append(ConfigIssue("CROSS_FIELD_ERROR", "costs.a_share_periods[0].effective_from", "cost schedule must cover data start"))
        for index in range(len(typed_periods) - 1):
            current_to = typed_periods[index].get("effective_to")
            next_from = typed_periods[index + 1].get("effective_from")
            if type(current_to) is dt.date and type(next_from) is dt.date:
                if next_from != current_to + dt.timedelta(days=1):
                    issues.append(ConfigIssue("CROSS_FIELD_ERROR", f"costs.a_share_periods[{index + 1}].effective_from", "cost periods must be consecutive calendar days"))
            from_date = typed_periods[index].get("effective_from")
            if type(from_date) is dt.date and type(current_to) is dt.date and current_to < from_date:
                issues.append(ConfigIssue("CROSS_FIELD_ERROR", f"costs.a_share_periods[{index}].effective_to", "cost period end must not precede start"))


def _scan_secrets(value: object, issues: list[ConfigIssue], tokens: tuple[str | int, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str:
                _scan_secrets(child, issues, (*tokens, "<non-string-key>"))
                continue
            child_tokens = (*tokens, key)
            if _is_sensitive_key(key):
                issues.append(ConfigIssue("SECRET_VALUE", _display_path(child_tokens), "credential keys are forbidden"))
            _scan_secrets(child, issues, child_tokens)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _scan_secrets(child, issues, (*tokens, index))
    elif type(value) is str:
        _validate_safe_string(_display_path(tokens), value, issues)


def _validate_safe_string(path: str, value: str, issues: list[ConfigIssue]) -> None:
    """Apply the same secret/control/path safety domain at every public entry."""
    _scan_secret_value(path, value, issues)
    _scan_unsafe_path_value(path, value, issues)


def _scan_secret_value(path: str, value: str, issues: list[ConfigIssue]) -> None:
    decoded = _controlled_percent_decode(value)
    patterns = (
        r"\bbearer\s+\S+",
        r"\btoken\s*=",
        r"\bapi[_-]?key\s*=",
        r"\bpassword\s*=",
        r"\bsecret\s*=",
        r"\bsk-[A-Za-z0-9_-]+",
    )
    if any(re.search(pattern, decoded, flags=re.IGNORECASE) for pattern in patterns):
        issues.append(ConfigIssue("SECRET_VALUE", path, "credential-like values are forbidden"))
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        issues.append(ConfigIssue("SECRET_VALUE", path, "control characters are forbidden"))


def _is_sensitive_key(key: str) -> bool:
    normalized = _controlled_percent_decode(key).lower().replace("-", "_")
    return normalized in {
        "token",
        "api_token",
        "api_key",
        "apikey",
        "secret",
        "password",
        "passwd",
        "authorization",
        "cookie",
        "credential",
        "private_key",
    }


def _scan_unsafe_path_value(path: str, value: str, issues: list[ConfigIssue]) -> None:
    """Reject path-like absolute/non-POSIX strings without mistaking URLs for paths."""
    if "://" in value:
        return
    decoded = _controlled_percent_decode(value)
    if (
        value.startswith("/")
        or decoded.startswith("/")
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
        or value.startswith("\\\\")
        or "\\" in value
        or "\\" in decoded
    ):
        issues.append(ConfigIssue("UNSAFE_PATH", path, "absolute and non-POSIX paths are forbidden"))


def _controlled_percent_decode(value: str) -> str:
    """Decode at most three percent-encoding layers without interpreting other syntax."""
    decoded = value
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _canonical_tracking_uri(uri: str, issues: list[ConfigIssue]) -> str | None:
    path = "tracking.tracking_uri"
    if "%" in uri or "\\" in uri or any(ord(char) < 32 or ord(char) == 127 for char in uri):
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI contains forbidden encoding or separators"))
        return None
    sqlite_match = re.fullmatch(r"sqlite:///([^?#]+)", uri, flags=re.IGNORECASE)
    if sqlite_match:
        relative = sqlite_match.group(1)
        if relative.startswith("/"):
            issues.append(ConfigIssue("UNSAFE_URI", path, "SQLite URI must use a relative logical path"))
            return None
        if not _validate_relative_posix_path(relative, path, issues, code="UNSAFE_URI"):
            return None
        return f"sqlite:///{relative}"

    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError:
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI authority is invalid"))
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI must be relative SQLite or HTTP(S)"))
        return None
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI credentials, query, and fragment are forbidden"))
        return None
    host = parsed.hostname.lower()
    request_path = parsed.path or "/"
    segments = request_path.split("/")
    if any(segment in {".", ".."} for segment in segments):
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI dot segments are forbidden"))
        return None
    if request_path != "/" and ("//" in request_path or request_path.endswith("/")):
        issues.append(ConfigIssue("UNSAFE_URI", path, "URI path must be canonical"))
        return None
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    authority = host if port is None or default_port else f"{host}:{port}"
    return f"{scheme}://{authority}{request_path}"


def _validate_relative_posix_path(
    value: str,
    path: str,
    issues: list[ConfigIssue],
    *,
    code: Literal["UNSAFE_PATH", "UNSAFE_URI"],
) -> bool:
    decoded = _controlled_percent_decode(value)
    invalid = (
        not value
        or value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or "%" in value
        or re.match(r"^[A-Za-z]:", value) is not None
        or value.startswith("//")
        or any(segment in {"", ".", ".."} for segment in value.split("/"))
        or any(segment in {"", ".", ".."} for segment in decoded.replace("\\", "/").split("/"))
    )
    if invalid:
        issues.append(ConfigIssue(code, path, "expected a canonical relative POSIX path"))
        return False
    return True


def _trusted_config_sha256(selector: ConfigSelector, document: Mapping[str, object]) -> str:
    config_version = cast(str, cast(Mapping[str, object], document["meta"])["config_version"])
    payload = document if selector == "full" else _project(document, selector)
    return _sha256_json({
        "hash_version": _HASH_VERSION,
        "selector": selector,
        "config_version": config_version,
        "payload": payload,
    })


def _project(document: Mapping[str, object], selector: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for tokens, value in _iter_assignment_leaves(document, []):
        spec = _FIELD_SPECS.get(_shape(tokens))
        # config_version belongs to every config identity as the envelope namespace,
        # not as a duplicated payload field.
        if tokens == ("meta", "config_version"):
            continue
        if spec is not None and selector in spec.selectors:
            _set_path(result, tokens, _thaw(value))
    return result


def _set_path(root: dict[str, object], tokens: tuple[str | int, ...], value: object) -> None:
    current: object = root
    for position, token in enumerate(tokens):
        last = position == len(tokens) - 1
        next_token = None if last else tokens[position + 1]
        if isinstance(token, str):
            mapping = cast(dict[str, object], current)
            if last:
                mapping[token] = value
            elif token not in mapping:
                mapping[token] = [] if isinstance(next_token, int) else {}
            current = mapping[token]
        else:
            sequence = cast(list[object], current)
            while len(sequence) <= token:
                sequence.append({} if not isinstance(next_token, int) else [])
            if last:
                sequence[token] = value
            else:
                current = sequence[token]


def _sha256_json(value: object) -> str:
    canonical = _json_value(value)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {cast(str, key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is float and value == 0.0:
        return 0.0
    return value


def _normalize_scalars(value: object) -> object:
    if isinstance(value, Mapping):
        return {cast(str, key): _normalize_scalars(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_scalars(child) for child in value]
    if type(value) is float and value == 0.0:
        return 0.0
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({cast(str, key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(child) for child in value]
    return value


def _get_path(root: object, tokens: tuple[str, ...]) -> object:
    current = root
    for token in tokens:
        if not isinstance(current, Mapping) or token not in current:
            return _MISSING
        current = current[token]
    return current


def _shape(tokens: tuple[str | int, ...]) -> str:
    parts: list[str] = []
    for token in tokens:
        if isinstance(token, int):
            if parts:
                parts[-1] += "[]"
        else:
            parts.append(token)
    return ".".join(parts)


def _display_path(tokens: tuple[str | int, ...]) -> str:
    output = ""
    for token in tokens:
        if isinstance(token, int):
            output += f"[{token}]"
        else:
            output += ("." if output else "") + token
    return output or "config"


def _strict_int_sequence(value: object) -> bool:
    return isinstance(value, (list, tuple)) and bool(value) and all(type(item) is int for item in value)


__all__ = [
    "ConfigIssue",
    "ConfigSelector",
    "LoadedM3Config",
    "M3ConfigError",
    "canonical_config_sha256",
    "canonical_tracking_target_key",
    "load_m3_config",
]
