"""M3 G1-R1A: deterministic runtime identity and staged request-plan skeleton."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import stat
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

import polars as pl

from quant.data.index_membership import (
    M3IndexMembershipError,
    build_observed_membership,
    normalize_index_weight_observations,
    verify_observed_membership_result,
)
from quant.data.m3_backfill import (
    EndpointPolicy,
    G1RequestPlan,
    HistoryWindow,
    TushareRequestBatch,
    TushareRequestSpec,
    TUSHARE_FIELDS,
    VerifiedRawResponse,
    plan_fund_adj_requests,
    plan_history_requests,
    plan_index_weight_requests,
    resolve_history_window,
)
from quant.data.m3_backfill import (
    _batch_hash as _tushare_batch_hash,
    _plan_hash as _tushare_plan_hash,
)
from quant.data.m3_execution_facts import (
    G1_CORPORATE_ACTION_RECONCILIATION_VERSION,
    G1_CORPORATE_ACTION_SELECTION_VERSION,
    G1_PRICE_LIMIT_METHOD_VERSION,
)
from quant.data.m3_g1_candidate import G1_MEMBERSHIP_METHOD_VERSION, G1BuildSpec
from quant.data.m3_reference import G1CrossSourcePolicy
from quant.domain import InstrumentSchema, TradeCalendarSchema
from quant.research.m3.config import (
    LoadedM3Config,
    M3ConfigError,
    canonical_config_sha256,
    canonical_tracking_target_key,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

_SOURCE_TREE_SCHEMA = "m3-g1-source-tree-v1"
_DEP_FP_SCHEMA = "m3-g1-dependency-fingerprint-v1"
_STATIC_ID_SCHEMA = "m3-g1-static-plan-identity-v1"
_DERIVED_ID_SCHEMA = "m3-g1-derived-history-plan-identity-v2"
_MAPPER_VERSION = "m3-g1-tushare-mapper-v4"
_SCHEMA_VERSION = "m3-g1-schema-v2"
_UNIVERSE: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"] = (
    "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
)
_BENCHMARK: Literal["510300.SH"] = "510300.SH"
_BENCHMARK_MODE: Literal["TRADEABLE_ETF_TOTAL_RETURN_PROXY"] = (
    "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
)
_BENCHMARK_METHOD_VERSION: Literal["tushare_510300_fund_daily_fund_adj_hfq_v1"] = (
    "tushare_510300_fund_daily_fund_adj_hfq_v1"
)
_BENCHMARK_DIVIDEND_RECONCILIATION_VERSION: Literal[
    "tushare_fund_div_implemented_cash_v1"
] = "tushare_fund_div_implemented_cash_v1"
_INDEX_CODE: Literal["000300.SH"] = "000300.SH"
_EXPECTED_COUNT: Literal[300] = 300

_DEPENDENCY_DISTRIBUTIONS = (
    "baostock",
    "numpy",
    "pandas",
    "pandera",
    "polars",
    "pyarrow",
    "tushare",
)

_EMPTY_REJECT = frozenset(
    {
        "index_weight",
        "daily",
        "adj_factor",
        "index_daily",
        "stk_limit",
        "fund_daily",
        "fund_adj",
        "fund_div",
    }
)
_EMPTY_ALLOW = frozenset({"suspend_d", "dividend"})
_ALL_ENDPOINTS = tuple(sorted(_EMPTY_REJECT | _EMPTY_ALLOW))

_ERROR_CODES = frozenset(
    {
        "G1_PLANNING_INPUT_INVALID",
        "G1_PLANNING_PROJECT_ROOT_INVALID",
        "G1_PLANNING_SOURCE_TREE_INVALID",
        "G1_PLANNING_DEPENDENCY_INVALID",
        "G1_PLANNING_CONFIG_INVALID",
        "G1_PLANNING_CALENDAR_INVALID",
        "G1_PLANNING_MEMBERSHIP_INVALID",
        "G1_PLANNING_IDENTITY_MISMATCH",
    }
)

_CONFIG_SELECTORS = (
    ("full", "full_config_sha256"),
    ("g1", "g1_config_sha256"),
    ("snapshot", "snapshot_config_sha256"),
    ("provider", "provider_config_sha256"),
    ("scientific", "scientific_config_sha256"),
    ("provider-validation", "provider_validation_config_sha256"),
    ("label-reconciliation", "label_reconciliation_config_sha256"),
    ("acceptance", "acceptance_config_sha256"),
)


class M3G1PlanningError(ValueError):
    """Stable R1A planning boundary error; ``str(error)`` equals ``code``."""

    code: Literal[
        "G1_PLANNING_INPUT_INVALID",
        "G1_PLANNING_PROJECT_ROOT_INVALID",
        "G1_PLANNING_SOURCE_TREE_INVALID",
        "G1_PLANNING_DEPENDENCY_INVALID",
        "G1_PLANNING_CONFIG_INVALID",
        "G1_PLANNING_CALENDAR_INVALID",
        "G1_PLANNING_MEMBERSHIP_INVALID",
        "G1_PLANNING_IDENTITY_MISMATCH",
    ]

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown g1 planning error code")
        self.code = cast(Any, code)
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3G1PlanningError({self.code!r})"


@dataclass(frozen=True)
class G1DependencyVersionV1:
    distribution: str
    version: str

    def __post_init__(self) -> None:
        if type(self.distribution) is not str or not self.distribution:
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        if type(self.version) is not str or not self.version:
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        if _CTRL.search(self.distribution) or _CTRL.search(self.version):
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")


@dataclass(frozen=True)
class G1SourceDigestV1:
    relative_path: str
    sha256: str

    def __post_init__(self) -> None:
        if type(self.relative_path) is not str or not self.relative_path:
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        if "\\" in self.relative_path or self.relative_path.startswith("/"):
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        try:
            pure = PurePosixPath(self.relative_path)
        except Exception:
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID") from None
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != self.relative_path:
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        if type(self.sha256) is not str or not _HEX64.fullmatch(self.sha256):
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")


@dataclass(frozen=True)
class G1RuntimeIdentityV1:
    schema_version: Literal["m3-g1-runtime-identity-v1"]
    code_version: str
    source_tree_sha256: str
    source_files: tuple[G1SourceDigestV1, ...]
    pyproject_sha256: str
    python_implementation: str
    python_version: str
    sys_platform: str
    machine: str
    kernel_release: str
    dependencies: tuple[G1DependencyVersionV1, ...]
    dependency_fingerprint_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-runtime-identity-v1":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if type(self.source_files) is not tuple or not self.source_files:
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        if type(self.dependencies) is not tuple or not self.dependencies:
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        for source_digest in self.source_files:
            if type(source_digest) is not G1SourceDigestV1:
                raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
            G1SourceDigestV1(source_digest.relative_path, source_digest.sha256)
        for dependency in self.dependencies:
            if type(dependency) is not G1DependencyVersionV1:
                raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
            G1DependencyVersionV1(dependency.distribution, dependency.version)
        ordered_files = tuple(
            sorted(self.source_files, key=lambda item: item.relative_path.encode("utf-8"))
        )
        if self.source_files != ordered_files:
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        paths = [item.relative_path for item in self.source_files]
        if len(paths) != len(set(paths)):
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        ordered_deps = tuple(
            sorted(self.dependencies, key=lambda item: item.distribution.encode("utf-8"))
        )
        if self.dependencies != ordered_deps:
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        dep_names = [item.distribution for item in self.dependencies]
        if dep_names != list(_DEPENDENCY_DISTRIBUTIONS):
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        if len(dep_names) != len(set(dep_names)):
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        for name in (
            "code_version",
            "python_implementation",
            "python_version",
            "sys_platform",
            "machine",
            "kernel_release",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value or _CTRL.search(value):
                raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        for name in (
            "source_tree_sha256",
            "pyproject_sha256",
            "dependency_fingerprint_sha256",
        ):
            value = getattr(self, name)
            if type(value) is not str or not _HEX64.fullmatch(value):
                raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        expected_tree = _source_tree_sha256(self.source_files)
        if self.source_tree_sha256 != expected_tree:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if self.code_version != f"m3-g1-code-v1-{expected_tree}":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        expected_fp = _dependency_fingerprint_sha256(
            pyproject_sha256=self.pyproject_sha256,
            python_implementation=self.python_implementation,
            python_version=self.python_version,
            sys_platform=self.sys_platform,
            machine=self.machine,
            kernel_release=self.kernel_release,
            dependencies=self.dependencies,
        )
        if self.dependency_fingerprint_sha256 != expected_fp:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")


@dataclass(frozen=True)
class G1StaticPlanV1:
    schema_version: Literal["m3-g1-static-plan-v1"]
    config_version: str
    g1_config_sha256: str
    runtime: G1RuntimeIdentityV1
    signal_start: dt.date
    signal_end: dt.date
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    benchmark: Literal["510300.SH"]
    index_code: Literal["000300.SH"]
    index_weight_batch: TushareRequestBatch
    endpoint_policies: tuple[tuple[str, EndpointPolicy], ...]
    request_rate_per_minute: int
    max_attempts: int
    retry_base_seconds: float
    feature_warmup_sessions: int
    label_tail_sessions: int
    expected_constituent_count: Literal[300]
    factor_ratio_rtol: float
    build_spec: G1BuildSpec
    cross_source_policy: G1CrossSourcePolicy

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-static-plan-v1":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if type(self.config_version) is not str or not self.config_version:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(self.g1_config_sha256) is not str or not _HEX64.fullmatch(
            self.g1_config_sha256
        ):
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(self.runtime) is not G1RuntimeIdentityV1:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        runtime = _rebuild_runtime(self.runtime)
        if type(self.signal_start) is not dt.date or type(self.signal_end) is not dt.date:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if self.signal_start > self.signal_end:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if self.universe != _UNIVERSE:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if self.benchmark != _BENCHMARK:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if self.index_code != _INDEX_CODE:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if self.expected_constituent_count != _EXPECTED_COUNT:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        batch = _rebuild_batch(self.index_weight_batch)
        if batch.phase != "INDEX_WEIGHT":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        policies = _rebuild_endpoint_policies(self.endpoint_policies)
        if type(self.request_rate_per_minute) is not int or self.request_rate_per_minute < 1:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(self.retry_base_seconds) is not float or not math.isfinite(
            self.retry_base_seconds
        ) or self.retry_base_seconds < 0.0:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(self.feature_warmup_sessions) is not int or self.feature_warmup_sessions < 0:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(self.label_tail_sessions) is not int or self.label_tail_sessions < 1:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(self.factor_ratio_rtol) is bool or type(self.factor_ratio_rtol) is not float:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if (
            not math.isfinite(self.factor_ratio_rtol)
            or self.factor_ratio_rtol < 0.0
            or self.factor_ratio_rtol > 0.01
        ):
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        build_spec = _rebuild_build_spec(self.build_spec)
        cross = _rebuild_cross_source(self.cross_source_policy)
        if build_spec.config_version != self.config_version:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.g1_config_sha256 != self.g1_config_sha256:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.build_code_version != runtime.code_version:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.dependency_fingerprint_sha256 != runtime.dependency_fingerprint_sha256:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.mapper_version != _MAPPER_VERSION:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.schema_version != _SCHEMA_VERSION:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.benchmark_mode != _BENCHMARK_MODE:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.benchmark_method_version != _BENCHMARK_METHOD_VERSION:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if (
            build_spec.benchmark_dividend_reconciliation_version
            != _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
        ):
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.membership_method_version != G1_MEMBERSHIP_METHOD_VERSION:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if build_spec.price_limit_method_version != G1_PRICE_LIMIT_METHOD_VERSION:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if (
            build_spec.corporate_action_selection_version
            != G1_CORPORATE_ACTION_SELECTION_VERSION
        ):
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if (
            build_spec.corporate_action_reconciliation_version
            != G1_CORPORATE_ACTION_RECONCILIATION_VERSION
        ):
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if cross.reference_source != "baostock":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "index_weight_batch", batch)
        object.__setattr__(self, "endpoint_policies", policies)
        object.__setattr__(self, "build_spec", build_spec)
        object.__setattr__(self, "cross_source_policy", cross)


@dataclass(frozen=True)
class G1DerivedHistoryPlanV1:
    schema_version: Literal["m3-g1-derived-history-plan-v2"]
    static_plan_sha256: str
    observations_sha256: str
    membership_sha256: str
    eligible_keys_sha256: str
    history_symbols: tuple[str, ...]
    history: HistoryWindow
    request_plan: G1RequestPlan
    derived_plan_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-derived-history-plan-v2":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        for name in (
            "static_plan_sha256",
            "observations_sha256",
            "membership_sha256",
            "eligible_keys_sha256",
            "derived_plan_sha256",
        ):
            value = getattr(self, name)
            if type(value) is not str or not _HEX64.fullmatch(value):
                raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if type(self.history_symbols) is not tuple or not self.history_symbols:
            raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID")
        if any(
            type(symbol) is not str or not _A_SHARE.fullmatch(symbol)
            for symbol in self.history_symbols
        ):
            raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID")
        ordered = tuple(sorted(set(self.history_symbols)))
        if self.history_symbols != ordered:
            raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID")
        history = _rebuild_history(self.history)
        plan = _rebuild_request_plan(self.request_plan)
        if plan.index_weight_batch.phase != "INDEX_WEIGHT":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        if plan.history_batch.phase != "HISTORY":
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        expected = _derived_plan_sha256(
            static_plan_sha256=self.static_plan_sha256,
            observations_sha256=self.observations_sha256,
            membership_sha256=self.membership_sha256,
            eligible_keys_sha256=self.eligible_keys_sha256,
            history_symbols=self.history_symbols,
            history=history,
            request_plan=plan,
        )
        if self.derived_plan_sha256 != expected:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "request_plan", plan)


def compute_g1_runtime_identity(*, project_root: Path) -> G1RuntimeIdentityV1:
    """Hash controlled source tree and base dependency fingerprint for G1."""
    try:
        root, root_id, ancestor_snap = _open_project_root(project_root)
        source_files = _collect_source_digests(root)
        pyproject_path = root / "pyproject.toml"
        pyproject_sha256 = _hash_regular_file(pyproject_path, code="G1_PLANNING_SOURCE_TREE_INVALID")
        dependencies = _read_dependencies()
        python_implementation = sys.implementation.name
        version_info = sys.version_info
        python_version = (
            f"{version_info.major}.{version_info.minor}.{version_info.micro}"
        )
        sys_platform = sys.platform
        machine = platform.machine()
        kernel_release = platform.release()
        for value in (
            python_implementation,
            python_version,
            sys_platform,
            machine,
            kernel_release,
        ):
            if type(value) is not str or not value or _CTRL.search(value):
                raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        source_tree_sha256 = _source_tree_sha256(source_files)
        dependency_fingerprint_sha256 = _dependency_fingerprint_sha256(
            pyproject_sha256=pyproject_sha256,
            python_implementation=python_implementation,
            python_version=python_version,
            sys_platform=sys_platform,
            machine=machine,
            kernel_release=kernel_release,
            dependencies=dependencies,
        )
        identity = G1RuntimeIdentityV1(
            schema_version="m3-g1-runtime-identity-v1",
            code_version=f"m3-g1-code-v1-{source_tree_sha256}",
            source_tree_sha256=source_tree_sha256,
            source_files=source_files,
            pyproject_sha256=pyproject_sha256,
            python_implementation=python_implementation,
            python_version=python_version,
            sys_platform=sys_platform,
            machine=machine,
            kernel_release=kernel_release,
            dependencies=dependencies,
            dependency_fingerprint_sha256=dependency_fingerprint_sha256,
        )
        # Fail-closed: first hash → return window must not deliver a stale source closure.
        rechecked_files = _collect_source_digests(root)
        rechecked_pyproject = _hash_regular_file(
            pyproject_path, code="G1_PLANNING_SOURCE_TREE_INVALID"
        )
        if rechecked_files != source_files or rechecked_pyproject != pyproject_sha256:
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        _assert_root_unchanged(root, root_id, ancestor_snap)
        return identity
    except M3G1PlanningError:
        raise
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID") from None


def build_g1_static_plan(
    *, config: LoadedM3Config, project_root: Path
) -> G1StaticPlanV1:
    """Build the static G1 plan from a rebuilt C0 config and runtime identity."""
    try:
        rebuilt_config = _rebuild_loaded_config(config)
        data = _require_mapping(rebuilt_config.section("data"), "G1_PLANNING_CONFIG_INVALID")
        g1 = _require_mapping(rebuilt_config.section("g1_backfill"), "G1_PLANNING_CONFIG_INVALID")
        signal_start = _require_date(data.get("start_date"), "G1_PLANNING_CONFIG_INVALID")
        signal_end = _require_date(data.get("end_date"), "G1_PLANNING_CONFIG_INVALID")
        if signal_start > signal_end:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        universe = data.get("universe")
        benchmark = data.get("benchmark")
        if universe != _UNIVERSE or benchmark != _BENCHMARK:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        index_code = g1.get("index_weight_code")
        benchmark_code = g1.get("benchmark_code")
        if index_code != _INDEX_CODE or benchmark_code != _BENCHMARK:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if g1.get("benchmark_mode") != _BENCHMARK_MODE:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if g1.get("benchmark_method_version") != _BENCHMARK_METHOD_VERSION:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if (
            g1.get("benchmark_dividend_reconciliation_version")
            != _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
        ):
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        membership_method = g1.get("membership_method_version")
        if membership_method != G1_MEMBERSHIP_METHOD_VERSION:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        expected_count = g1.get("expected_constituent_count")
        if expected_count != _EXPECTED_COUNT:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        warmup_months = g1.get("membership_warmup_months")
        if type(warmup_months) is not int or warmup_months < 0:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        feature_warmup = g1.get("feature_warmup_sessions")
        label_tail = g1.get("label_tail_sessions")
        if type(feature_warmup) is not int or feature_warmup < 0:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(label_tail) is not int or label_tail < 1:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        rate = g1.get("request_rate_per_minute")
        max_attempts = g1.get("max_attempts")
        retry_base = g1.get("retry_base_seconds")
        if type(rate) is not int or rate < 1:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(max_attempts) is not int or max_attempts < 1:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if type(retry_base) is not float or not math.isfinite(retry_base) or retry_base < 0.0:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        row_limits = _require_mapping(
            g1.get("endpoint_row_limits"), "G1_PLANNING_CONFIG_INVALID"
        )
        policies = _build_endpoint_policies(row_limits)
        reconciliation = _require_mapping(
            g1.get("reconciliation"), "G1_PLANNING_CONFIG_INVALID"
        )
        corporate = _require_mapping(
            g1.get("corporate_action_reconciliation"), "G1_PLANNING_CONFIG_INVALID"
        )
        factor_rtol = corporate.get("factor_ratio_rtol")
        if type(factor_rtol) is bool or type(factor_rtol) is not float:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if not math.isfinite(factor_rtol) or factor_rtol < 0.0 or factor_rtol > 0.01:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        cross = _build_cross_source_policy(reconciliation)
        runtime = compute_g1_runtime_identity(project_root=project_root)
        batch = plan_index_weight_requests(
            index_code=_INDEX_CODE,
            start=signal_start,
            end=signal_end,
            warmup_months=warmup_months,
        )
        build_spec = G1BuildSpec(
            config_version=rebuilt_config.config_version,
            g1_config_sha256=rebuilt_config.g1_config_sha256,
            mapper_version=_MAPPER_VERSION,
            schema_version=_SCHEMA_VERSION,
            membership_method_version=G1_MEMBERSHIP_METHOD_VERSION,
            price_limit_method_version=G1_PRICE_LIMIT_METHOD_VERSION,
            corporate_action_selection_version=G1_CORPORATE_ACTION_SELECTION_VERSION,
            corporate_action_reconciliation_version=G1_CORPORATE_ACTION_RECONCILIATION_VERSION,
            benchmark_mode=_BENCHMARK_MODE,
            benchmark_method_version=_BENCHMARK_METHOD_VERSION,
            benchmark_dividend_reconciliation_version=(
                _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
            ),
            build_code_version=runtime.code_version,
            dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
        )
        return G1StaticPlanV1(
            schema_version="m3-g1-static-plan-v1",
            config_version=rebuilt_config.config_version,
            g1_config_sha256=rebuilt_config.g1_config_sha256,
            runtime=runtime,
            signal_start=signal_start,
            signal_end=signal_end,
            universe=_UNIVERSE,
            benchmark=_BENCHMARK,
            index_code=_INDEX_CODE,
            index_weight_batch=batch,
            endpoint_policies=policies,
            request_rate_per_minute=rate,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base,
            feature_warmup_sessions=feature_warmup,
            label_tail_sessions=label_tail,
            expected_constituent_count=_EXPECTED_COUNT,
            factor_ratio_rtol=factor_rtol,
            build_spec=build_spec,
            cross_source_policy=cross,
        )
    except M3G1PlanningError:
        raise
    except (M3ConfigError, ValueError, TypeError, OSError, KeyError):
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID") from None
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID") from None


def plan_g1_etf_history_requests(
    *,
    index_weight_batch: TushareRequestBatch,
    symbols: Sequence[str],
    history: HistoryWindow,
) -> G1RequestPlan:
    """Compose HISTORY plan: unchanged equity requests + 510300 ETF fund closure."""
    # Reuse equity request construction via plan_history_requests, then replace the
    # legacy index_daily slot with fund_daily/fund_adj/fund_div. Stock request_ids
    # are independent of the temporary CSI benchmark argument.
    base = plan_history_requests(
        index_weight_batch=index_weight_batch,
        symbols=symbols,
        benchmark="H00300.CSI",
        history=history,
    )
    equity_requests = tuple(
        item
        for item in base.history_batch.requests
        if item.endpoint != "index_daily"
    )
    if any(item.endpoint == "index_daily" for item in equity_requests):
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    if any(
        item.endpoint in {"fund_daily", "fund_adj", "fund_div"}
        for item in equity_requests
    ):
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    start_text = history.start.strftime("%Y%m%d")
    end_text = history.end.strftime("%Y%m%d")
    fund_daily = TushareRequestSpec.create(
        endpoint="fund_daily",
        parameters={
            "fields": TUSHARE_FIELDS["fund_daily"],
            "ts_code": _BENCHMARK,
            "start_date": start_text,
            "end_date": end_text,
        },
    )
    fund_adj = plan_fund_adj_requests(
        symbol=_BENCHMARK, start=history.start, end=history.end
    )
    fund_div = TushareRequestSpec.create(
        endpoint="fund_div",
        parameters={
            "fields": TUSHARE_FIELDS["fund_div"],
            "ts_code": _BENCHMARK,
        },
    )
    merged = tuple(
        sorted(
            (*equity_requests, fund_daily, *fund_adj, fund_div),
            key=lambda item: item.request_id,
        )
    )
    history_batch = TushareRequestBatch(
        "m3-g1-tushare-request-batch-v1",
        "HISTORY",
        merged,
        _tushare_batch_hash("HISTORY", merged),
    )
    cninfo_rights_batch = base.cninfo_rights_batch
    return G1RequestPlan(
        "m3-g1-request-plan-v2",
        index_weight_batch,
        history_batch,
        cninfo_rights_batch,
        _tushare_plan_hash(index_weight_batch, history_batch, cninfo_rights_batch),
    )


def derive_g1_history_plan(
    *,
    config: LoadedM3Config,
    project_root: Path,
    static_plan: G1StaticPlanV1,
    index_responses: Sequence[VerifiedRawResponse],
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
) -> G1DerivedHistoryPlanV1:
    """Derive the unique history request plan from verified index-weight responses."""
    try:
        if type(static_plan) is not G1StaticPlanV1:
            raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID")
        rebuilt_static = build_g1_static_plan(config=config, project_root=project_root)
        if rebuilt_static != static_plan:
            raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
        static_plan = G1StaticPlanV1(
            schema_version=static_plan.schema_version,
            config_version=static_plan.config_version,
            g1_config_sha256=static_plan.g1_config_sha256,
            runtime=static_plan.runtime,
            signal_start=static_plan.signal_start,
            signal_end=static_plan.signal_end,
            universe=static_plan.universe,
            benchmark=static_plan.benchmark,
            index_code=static_plan.index_code,
            index_weight_batch=static_plan.index_weight_batch,
            endpoint_policies=static_plan.endpoint_policies,
            request_rate_per_minute=static_plan.request_rate_per_minute,
            max_attempts=static_plan.max_attempts,
            retry_base_seconds=static_plan.retry_base_seconds,
            feature_warmup_sessions=static_plan.feature_warmup_sessions,
            label_tail_sessions=static_plan.label_tail_sessions,
            expected_constituent_count=static_plan.expected_constituent_count,
            factor_ratio_rtol=static_plan.factor_ratio_rtol,
            build_spec=static_plan.build_spec,
            cross_source_policy=static_plan.cross_source_policy,
        )
        responses = _consume_index_responses(index_responses)
        _match_index_response_set(static_plan.index_weight_batch, responses)
        calendar_frame, open_dates = _prepare_calendars(
            calendars,
            signal_start=static_plan.signal_start,
            signal_end=static_plan.signal_end,
            feature_warmup_sessions=static_plan.feature_warmup_sessions,
            label_tail_sessions=static_plan.label_tail_sessions,
        )
        instrument_frame = _validate_instruments(instruments)
        try:
            observations = normalize_index_weight_observations(
                batch=static_plan.index_weight_batch,
                responses=responses,
                universe=static_plan.universe,
            )
            membership = build_observed_membership(
                observations=observations,
                calendars=calendar_frame,
                instruments=instrument_frame,
                universe=static_plan.universe,
                signal_start=static_plan.signal_start,
                signal_end=static_plan.signal_end,
                expected_constituent_count=static_plan.expected_constituent_count,
            )
            verify_observed_membership_result(
                batch=static_plan.index_weight_batch,
                responses=responses,
                result=membership,
                calendars=calendar_frame,
                instruments=instrument_frame,
                universe=static_plan.universe,
                signal_start=static_plan.signal_start,
                signal_end=static_plan.signal_end,
                expected_constituent_count=static_plan.expected_constituent_count,
            )
        except M3IndexMembershipError:
            raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID") from None
        history_symbols = _history_symbols_from_observations(membership.observations)
        try:
            history = resolve_history_window(
                open_dates=open_dates,
                signal_start=static_plan.signal_start,
                signal_end=static_plan.signal_end,
                feature_warmup_sessions=static_plan.feature_warmup_sessions,
                label_tail_sessions=static_plan.label_tail_sessions,
            )
            request_plan = plan_g1_etf_history_requests(
                index_weight_batch=static_plan.index_weight_batch,
                symbols=history_symbols,
                history=history,
            )
        except ValueError:
            raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID") from None
        static_plan_sha256 = _static_plan_sha256(static_plan)
        derived = G1DerivedHistoryPlanV1(
            schema_version="m3-g1-derived-history-plan-v2",
            static_plan_sha256=static_plan_sha256,
            observations_sha256=membership.observations_sha256,
            membership_sha256=membership.membership_sha256,
            eligible_keys_sha256=membership.eligible_keys_sha256,
            history_symbols=history_symbols,
            history=history,
            request_plan=request_plan,
            derived_plan_sha256=_derived_plan_sha256(
                static_plan_sha256=static_plan_sha256,
                observations_sha256=membership.observations_sha256,
                membership_sha256=membership.membership_sha256,
                eligible_keys_sha256=membership.eligible_keys_sha256,
                history_symbols=history_symbols,
                history=history,
                request_plan=request_plan,
            ),
        )
        return derived
    except M3G1PlanningError:
        raise
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID") from None


def _rebuild_loaded_config(config: object) -> LoadedM3Config:
    if type(config) is not LoadedM3Config:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    try:
        recomputed: dict[str, str] = {}
        for selector, attr in _CONFIG_SELECTORS:
            recomputed[attr] = canonical_config_sha256(
                selector=cast(Any, selector), document=config.document
            )
        tracking = cast(Mapping[str, object], config.section("tracking"))
        tracking_uri = tracking.get("tracking_uri")
        experiment = tracking.get("experiment_name")
        if type(tracking_uri) is not str or type(experiment) is not str:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        tracking_key = canonical_tracking_target_key(
            tracking_uri=tracking_uri, experiment_name=experiment
        )
    except M3G1PlanningError:
        raise
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID") from None
    meta = cast(Mapping[str, object], config.section("meta"))
    config_version = meta.get("config_version")
    if type(config_version) is not str or config_version != config.config_version:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    if config.canonical_tracking_uri != tracking_uri:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    if config.tracking_target_key != tracking_key:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    for attr, expected in recomputed.items():
        if getattr(config, attr) != expected:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    return config


def _open_project_root(
    project_root: object,
) -> tuple[Path, tuple[int, int], tuple[tuple[str, tuple[int, int]], ...]]:
    if not isinstance(project_root, Path):
        raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID")
    try:
        root = Path(os.path.abspath(os.fspath(project_root)))
    except OSError:
        raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID") from None
    ancestor_snap = _snapshot_ancestors(root)
    root_id = _dir_identity(root, code="G1_PLANNING_PROJECT_ROOT_INVALID")
    return root, root_id, ancestor_snap


def _assert_root_unchanged(
    root: Path,
    root_id: tuple[int, int],
    ancestor_snap: tuple[tuple[str, tuple[int, int]], ...],
) -> None:
    current = _dir_identity(root, code="G1_PLANNING_PROJECT_ROOT_INVALID")
    if current != root_id:
        raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID")
    _assert_ancestors_unchanged(ancestor_snap)


def _snapshot_ancestors(
    path: Path,
) -> tuple[tuple[str, tuple[int, int]], ...]:
    current = Path(os.path.abspath(os.fspath(path)))
    snapshots: list[tuple[str, tuple[int, int]]] = []
    while True:
        abs_text = os.path.abspath(os.fspath(current))
        try:
            st = os.lstat(abs_text)
        except OSError:
            raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID") from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID")
        snapshots.append((abs_text, (st.st_dev, st.st_ino)))
        parent = Path(abs_text).parent
        if parent == Path(abs_text):
            break
        current = parent
    return tuple(snapshots)


def _assert_ancestors_unchanged(
    snapshot: tuple[tuple[str, tuple[int, int]], ...],
) -> None:
    for abs_text, expected in snapshot:
        try:
            st = os.lstat(abs_text)
        except OSError:
            raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID") from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID")
        if (st.st_dev, st.st_ino) != expected:
            raise M3G1PlanningError("G1_PLANNING_PROJECT_ROOT_INVALID")


def _dir_identity(path: Path, *, code: str) -> tuple[int, int]:
    try:
        st = os.lstat(path)
    except OSError:
        raise M3G1PlanningError(code) from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise M3G1PlanningError(code)
    return (st.st_dev, st.st_ino)


def _collect_source_digests(root: Path) -> tuple[G1SourceDigestV1, ...]:
    src_root = root / "src" / "quant"
    try:
        st = os.lstat(src_root)
    except OSError:
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
    digests: list[G1SourceDigestV1] = []
    seen_real: set[tuple[int, int]] = set()
    for dirpath, dirnames, filenames in os.walk(src_root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != "__pycache__")
        current = Path(dirpath)
        try:
            dir_st = os.lstat(current)
        except OSError:
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID") from None
        if stat.S_ISLNK(dir_st.st_mode):
            raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = current / name
            digest = _digest_source_file(root, path, seen_real)
            digests.append(digest)
    if not digests:
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
    ordered = tuple(sorted(digests, key=lambda item: item.relative_path.encode("utf-8")))
    paths = [item.relative_path for item in ordered]
    if len(paths) != len(set(paths)):
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
    return ordered


def _digest_source_file(
    root: Path, path: Path, seen_real: set[tuple[int, int]]
) -> G1SourceDigestV1:
    try:
        before = os.lstat(path)
    except OSError:
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID") from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
    real_id = (before.st_dev, before.st_ino)
    if real_id in seen_real:
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
    seen_real.add(real_id)
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID") from None
    rel_text = PurePosixPath(*relative.parts).as_posix()
    if ".." in PurePosixPath(rel_text).parts:
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
    try:
        payload = path.read_bytes()
        after = os.lstat(path)
    except OSError:
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID") from None
    if (
        stat.S_ISLNK(after.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or (after.st_dev, after.st_ino) != real_id
        or len(payload) != before.st_size
    ):
        raise M3G1PlanningError("G1_PLANNING_SOURCE_TREE_INVALID")
    return G1SourceDigestV1(
        relative_path=rel_text,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _hash_regular_file(path: Path, *, code: str) -> str:
    try:
        before = os.lstat(path)
    except OSError:
        raise M3G1PlanningError(code) from None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise M3G1PlanningError(code)
    try:
        payload = path.read_bytes()
        after = os.lstat(path)
    except OSError:
        raise M3G1PlanningError(code) from None
    if (
        stat.S_ISLNK(after.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        or len(payload) != before.st_size
    ):
        raise M3G1PlanningError(code)
    return hashlib.sha256(payload).hexdigest()


def _read_dependencies() -> tuple[G1DependencyVersionV1, ...]:
    items: list[G1DependencyVersionV1] = []
    for name in _DEPENDENCY_DISTRIBUTIONS:
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID") from None
        except Exception:
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID") from None
        if type(version) is not str or not version.strip() or _CTRL.search(version):
            raise M3G1PlanningError("G1_PLANNING_DEPENDENCY_INVALID")
        items.append(G1DependencyVersionV1(distribution=name, version=version))
    return tuple(items)


def _source_tree_sha256(files: Sequence[G1SourceDigestV1]) -> str:
    payload = {
        "schema_version": _SOURCE_TREE_SCHEMA,
        "files": [
            {"relative_path": item.relative_path, "sha256": item.sha256} for item in files
        ],
    }
    return _sha256_json(payload)


def _dependency_fingerprint_sha256(
    *,
    pyproject_sha256: str,
    python_implementation: str,
    python_version: str,
    sys_platform: str,
    machine: str,
    kernel_release: str,
    dependencies: Sequence[G1DependencyVersionV1],
) -> str:
    payload = {
        "schema_version": _DEP_FP_SCHEMA,
        "pyproject_sha256": pyproject_sha256,
        "python": {
            "implementation": python_implementation,
            "version": python_version,
        },
        "platform": {
            "sys_platform": sys_platform,
            "machine": machine,
            "kernel_release": kernel_release,
        },
        "dependencies": [
            {"distribution": item.distribution, "version": item.version}
            for item in dependencies
        ],
    }
    return _sha256_json(payload)


def _build_endpoint_policies(
    row_limits: Mapping[str, object],
) -> tuple[tuple[str, EndpointPolicy], ...]:
    items: list[tuple[str, EndpointPolicy]] = []
    keys = set(row_limits)
    if keys != set(_ALL_ENDPOINTS):
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    for endpoint in _ALL_ENDPOINTS:
        limit = row_limits.get(endpoint)
        if type(limit) is not int or limit <= 0:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        if endpoint in _EMPTY_REJECT:
            empty: Literal["ALLOW", "REJECT"] = "REJECT"
        elif endpoint in _EMPTY_ALLOW:
            empty = "ALLOW"
        else:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        items.append((endpoint, EndpointPolicy(row_limit=limit, empty_response=empty)))
    return tuple(items)


def _build_cross_source_policy(reconciliation: Mapping[str, object]) -> G1CrossSourcePolicy:
    reference = reconciliation.get("reference_source")
    sample_symbols = reconciliation.get("sample_symbols")
    dates_per_symbol = reconciliation.get("dates_per_symbol")
    price_atol = reconciliation.get("price_atol")
    price_rtol = reconciliation.get("price_rtol")
    volume_rtol = reconciliation.get("volume_rtol")
    max_mismatch_rate = reconciliation.get("max_mismatch_rate")
    if reference != "baostock":
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    if sample_symbols != 30 or dates_per_symbol != 20:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    if type(price_atol) is not float or type(price_rtol) is not float:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    if type(volume_rtol) is not float or type(max_mismatch_rate) is not float:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    try:
        return G1CrossSourcePolicy(
            reference_source="baostock",
            sample_symbols=30,
            dates_per_symbol=20,
            price_atol=price_atol,
            price_rtol=price_rtol,
            volume_rtol=volume_rtol,
            max_mismatch_rate=max_mismatch_rate,
        )
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID") from None


def _consume_index_responses(
    responses: Sequence[VerifiedRawResponse],
) -> tuple[VerifiedRawResponse, ...]:
    if not isinstance(responses, Sequence) or isinstance(responses, (str, bytes)):
        raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID")
    out: list[VerifiedRawResponse] = []
    for item in responses:
        out.append(_consume_verified(item))
    return tuple(out)


def _consume_verified(response: object) -> VerifiedRawResponse:
    if type(response) is not VerifiedRawResponse:
        raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID")
    try:
        rebuilt = VerifiedRawResponse(
            response.spec,
            response.receipt,
            response.receipt_sha256,
            response.frame,
        )
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID") from None
    return rebuilt


def _match_index_response_set(
    batch: TushareRequestBatch, responses: Sequence[VerifiedRawResponse]
) -> None:
    expected = Counter(spec.request_id for spec in batch.requests)
    actual = Counter(item.spec.request_id for item in responses)
    if expected != actual:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    for item in responses:
        if item.spec.endpoint != "index_weight" or item.receipt.endpoint != "index_weight":
            raise M3G1PlanningError("G1_PLANNING_INPUT_INVALID")


def _prepare_calendars(
    calendars: object,
    *,
    signal_start: dt.date,
    signal_end: dt.date,
    feature_warmup_sessions: int,
    label_tail_sessions: int,
) -> tuple[pl.DataFrame, tuple[dt.date, ...]]:
    if not isinstance(calendars, pl.DataFrame):
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    try:
        frame = TradeCalendarSchema.validate(calendars)
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID") from None
    markets = set(frame.get_column("market").unique().to_list())
    if markets != {"SH", "SZ"}:
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    sh = (
        frame.filter(pl.col("market") == "SH")
        .select(["date", "is_open"])
        .sort("date")
    )
    sz = (
        frame.filter(pl.col("market") == "SZ")
        .select(["date", "is_open"])
        .sort("date")
    )
    if sh.height == 0 or sz.height == 0:
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    if sh.get_column("date").to_list() != sz.get_column("date").to_list():
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    if sh.get_column("is_open").to_list() != sz.get_column("is_open").to_list():
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    dates = sh.get_column("date").to_list()
    if dates != sorted(set(dates)):
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    open_dates = tuple(
        day
        for day, is_open in zip(
            sh.get_column("date").to_list(),
            sh.get_column("is_open").to_list(),
            strict=True,
        )
        if is_open is True
    )
    if open_dates != tuple(sorted(set(open_dates))):
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    try:
        start_index = open_dates.index(signal_start)
        end_index = open_dates.index(signal_end)
    except ValueError:
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID") from None
    if start_index < feature_warmup_sessions:
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    if end_index + label_tail_sessions >= len(open_dates):
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    return frame, open_dates


def _validate_instruments(instruments: object) -> pl.DataFrame:
    if not isinstance(instruments, pl.DataFrame):
        raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID")
    try:
        return InstrumentSchema.validate(instruments)
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID") from None


def _history_symbols_from_observations(observations: pl.DataFrame) -> tuple[str, ...]:
    symbols = observations.get_column("symbol").to_list()
    if any(type(symbol) is not str or not _A_SHARE.fullmatch(symbol) for symbol in symbols):
        raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID")
    ordered = tuple(sorted(set(symbols)))
    if not ordered:
        raise M3G1PlanningError("G1_PLANNING_MEMBERSHIP_INVALID")
    return ordered


def _rebuild_runtime(runtime: G1RuntimeIdentityV1) -> G1RuntimeIdentityV1:
    return G1RuntimeIdentityV1(
        schema_version=runtime.schema_version,
        code_version=runtime.code_version,
        source_tree_sha256=runtime.source_tree_sha256,
        source_files=tuple(
            G1SourceDigestV1(item.relative_path, item.sha256) for item in runtime.source_files
        ),
        pyproject_sha256=runtime.pyproject_sha256,
        python_implementation=runtime.python_implementation,
        python_version=runtime.python_version,
        sys_platform=runtime.sys_platform,
        machine=runtime.machine,
        kernel_release=runtime.kernel_release,
        dependencies=tuple(
            G1DependencyVersionV1(item.distribution, item.version)
            for item in runtime.dependencies
        ),
        dependency_fingerprint_sha256=runtime.dependency_fingerprint_sha256,
    )


def _rebuild_batch(batch: object) -> TushareRequestBatch:
    if type(batch) is not TushareRequestBatch:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    try:
        return TushareRequestBatch(
            batch.schema_version,
            batch.phase,
            batch.requests,
            batch.batch_sha256,
        )
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH") from None


def _rebuild_endpoint_policies(
    policies: object,
) -> tuple[tuple[str, EndpointPolicy], ...]:
    if type(policies) is not tuple:
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    out: list[tuple[str, EndpointPolicy]] = []
    for item in policies:
        if type(item) is not tuple or len(item) != 2:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        endpoint, policy = item
        if type(endpoint) is not str or type(policy) is not EndpointPolicy:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        try:
            rebuilt = EndpointPolicy(policy.row_limit, policy.empty_response)
        except Exception:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID") from None
        expected_empty = "REJECT" if endpoint in _EMPTY_REJECT else "ALLOW"
        if endpoint not in _ALL_ENDPOINTS or rebuilt.empty_response != expected_empty:
            raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
        out.append((endpoint, rebuilt))
    ordered = tuple(sorted(out, key=lambda pair: pair[0]))
    if tuple(out) != ordered or [name for name, _ in ordered] != list(_ALL_ENDPOINTS):
        raise M3G1PlanningError("G1_PLANNING_CONFIG_INVALID")
    return ordered


def _rebuild_build_spec(spec: object) -> G1BuildSpec:
    if type(spec) is not G1BuildSpec:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    try:
        return G1BuildSpec(
            config_version=spec.config_version,
            g1_config_sha256=spec.g1_config_sha256,
            mapper_version=spec.mapper_version,
            schema_version=spec.schema_version,
            membership_method_version=spec.membership_method_version,
            price_limit_method_version=spec.price_limit_method_version,
            corporate_action_selection_version=spec.corporate_action_selection_version,
            corporate_action_reconciliation_version=(
                spec.corporate_action_reconciliation_version
            ),
            benchmark_mode=spec.benchmark_mode,
            benchmark_method_version=spec.benchmark_method_version,
            benchmark_dividend_reconciliation_version=(
                spec.benchmark_dividend_reconciliation_version
            ),
            build_code_version=spec.build_code_version,
            dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        )
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH") from None


def _rebuild_cross_source(policy: object) -> G1CrossSourcePolicy:
    if type(policy) is not G1CrossSourcePolicy:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    try:
        return G1CrossSourcePolicy(
            reference_source=policy.reference_source,
            sample_symbols=policy.sample_symbols,
            dates_per_symbol=policy.dates_per_symbol,
            price_atol=policy.price_atol,
            price_rtol=policy.price_rtol,
            volume_rtol=policy.volume_rtol,
            max_mismatch_rate=policy.max_mismatch_rate,
        )
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH") from None


def _rebuild_history(history: object) -> HistoryWindow:
    if type(history) is not HistoryWindow:
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID")
    try:
        return HistoryWindow(history.start, history.end)
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_CALENDAR_INVALID") from None


def _rebuild_request_plan(plan: object) -> G1RequestPlan:
    if type(plan) is not G1RequestPlan:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    try:
        return G1RequestPlan(
            plan.schema_version,
            plan.index_weight_batch,
            plan.history_batch,
            plan.cninfo_rights_batch,
            plan.plan_sha256,
        )
    except Exception:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH") from None


def _static_plan_sha256(plan: G1StaticPlanV1) -> str:
    payload = {
        "schema_version": _STATIC_ID_SCHEMA,
        "config_version": plan.config_version,
        "g1_config_sha256": plan.g1_config_sha256,
        "runtime": _runtime_to_jsonable(plan.runtime),
        "signal_start": plan.signal_start.isoformat(),
        "signal_end": plan.signal_end.isoformat(),
        "universe": plan.universe,
        "benchmark": plan.benchmark,
        "index_code": plan.index_code,
        "index_weight_batch": _batch_to_jsonable(plan.index_weight_batch),
        "endpoint_policies": [
            [endpoint, {"row_limit": policy.row_limit, "empty_response": policy.empty_response}]
            for endpoint, policy in plan.endpoint_policies
        ],
        "request_rate_per_minute": plan.request_rate_per_minute,
        "max_attempts": plan.max_attempts,
        "retry_base_seconds": plan.retry_base_seconds,
        "feature_warmup_sessions": plan.feature_warmup_sessions,
        "label_tail_sessions": plan.label_tail_sessions,
        "expected_constituent_count": plan.expected_constituent_count,
        "factor_ratio_rtol": plan.factor_ratio_rtol,
        "build_spec": {
            "config_version": plan.build_spec.config_version,
            "g1_config_sha256": plan.build_spec.g1_config_sha256,
            "mapper_version": plan.build_spec.mapper_version,
            "schema_version": plan.build_spec.schema_version,
            "membership_method_version": plan.build_spec.membership_method_version,
            "price_limit_method_version": plan.build_spec.price_limit_method_version,
            "corporate_action_selection_version": (
                plan.build_spec.corporate_action_selection_version
            ),
            "corporate_action_reconciliation_version": (
                plan.build_spec.corporate_action_reconciliation_version
            ),
            "benchmark_mode": plan.build_spec.benchmark_mode,
            "benchmark_method_version": plan.build_spec.benchmark_method_version,
            "benchmark_dividend_reconciliation_version": (
                plan.build_spec.benchmark_dividend_reconciliation_version
            ),
            "build_code_version": plan.build_spec.build_code_version,
            "dependency_fingerprint_sha256": (
                plan.build_spec.dependency_fingerprint_sha256
            ),
        },
        "cross_source_policy": {
            "reference_source": plan.cross_source_policy.reference_source,
            "sample_symbols": plan.cross_source_policy.sample_symbols,
            "dates_per_symbol": plan.cross_source_policy.dates_per_symbol,
            "price_atol": plan.cross_source_policy.price_atol,
            "price_rtol": plan.cross_source_policy.price_rtol,
            "volume_rtol": plan.cross_source_policy.volume_rtol,
            "max_mismatch_rate": plan.cross_source_policy.max_mismatch_rate,
        },
    }
    return _sha256_json(payload)


def _derived_plan_sha256(
    *,
    static_plan_sha256: str,
    observations_sha256: str,
    membership_sha256: str,
    eligible_keys_sha256: str,
    history_symbols: tuple[str, ...],
    history: HistoryWindow,
    request_plan: G1RequestPlan,
) -> str:
    payload = {
        "schema_version": _DERIVED_ID_SCHEMA,
        "static_plan_sha256": static_plan_sha256,
        "observations_sha256": observations_sha256,
        "membership_sha256": membership_sha256,
        "eligible_keys_sha256": eligible_keys_sha256,
        "history_symbols": list(history_symbols),
        "history": {
            "start": history.start.isoformat(),
            "end": history.end.isoformat(),
        },
        "request_plan": {
            "schema_version": request_plan.schema_version,
            "index_weight_batch": _batch_to_jsonable(request_plan.index_weight_batch),
            "history_batch": _batch_to_jsonable(request_plan.history_batch),
            "cninfo_rights_batch": _cninfo_batch_to_jsonable(
                request_plan.cninfo_rights_batch
            ),
            "plan_sha256": request_plan.plan_sha256,
        },
    }
    return _sha256_json(payload)


def _cninfo_batch_to_jsonable(batch: object) -> dict[str, Any]:
    from quant.data.m3_backfill import CninfoRequestBatch

    if type(batch) is not CninfoRequestBatch:
        raise M3G1PlanningError("G1_PLANNING_IDENTITY_MISMATCH")
    return {
        "schema_version": batch.schema_version,
        "phase": batch.phase,
        "requests": [
            {
                "schema_version": item.schema_version,
                "request_id": item.request_id,
                "source": item.source,
                "endpoint": item.endpoint,
                "adapter": item.adapter,
                "parameters": list(item.parameters),
            }
            for item in batch.requests
        ],
        "batch_sha256": batch.batch_sha256,
    }


def _runtime_to_jsonable(runtime: G1RuntimeIdentityV1) -> dict[str, Any]:
    return {
        "schema_version": runtime.schema_version,
        "code_version": runtime.code_version,
        "source_tree_sha256": runtime.source_tree_sha256,
        "source_files": [
            {"relative_path": item.relative_path, "sha256": item.sha256}
            for item in runtime.source_files
        ],
        "pyproject_sha256": runtime.pyproject_sha256,
        "python_implementation": runtime.python_implementation,
        "python_version": runtime.python_version,
        "sys_platform": runtime.sys_platform,
        "machine": runtime.machine,
        "kernel_release": runtime.kernel_release,
        "dependencies": [
            {"distribution": item.distribution, "version": item.version}
            for item in runtime.dependencies
        ],
        "dependency_fingerprint_sha256": runtime.dependency_fingerprint_sha256,
    }


def _batch_to_jsonable(batch: TushareRequestBatch) -> dict[str, Any]:
    return {
        "schema_version": batch.schema_version,
        "phase": batch.phase,
        "requests": [
            {
                "schema_version": spec.schema_version,
                "request_id": spec.request_id,
                "endpoint": spec.endpoint,
                "parameters": [list(pair) for pair in spec.parameters],
            }
            for spec in batch.requests
        ],
        "batch_sha256": batch.batch_sha256,
    }


def _require_mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise M3G1PlanningError(code)
    return cast(Mapping[str, object], value)


def _require_date(value: object, code: str) -> dt.date:
    if type(value) is not dt.date:
        raise M3G1PlanningError(code)
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "G1DependencyVersionV1",
    "G1SourceDigestV1",
    "G1RuntimeIdentityV1",
    "G1StaticPlanV1",
    "G1DerivedHistoryPlanV1",
    "M3G1PlanningError",
    "compute_g1_runtime_identity",
    "build_g1_static_plan",
    "derive_g1_history_plan",
]
