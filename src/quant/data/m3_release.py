"""M3 G1-P4C: strict readers and immutable release publishing."""

from __future__ import annotations

import datetime as dt
import errno
import hashlib
import json
import math
import os
import re
import stat
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal, Mapping

import ctypes
import ctypes.util
import polars as pl

from quant.data.connectors.cninfo import (
    CNINFO_ENDPOINT,
    CNINFO_SOURCE,
    CNINFO_STOCK_ALLOTMENT_FIELDS,
)
from quant.data.m3_backfill import HistoryWindow
from quant.data.m3_execution_facts import require_g1_price_limit_coverage
from quant.data.m3_g1_candidate import (
    G1BuildInputs,
    G1BuildSpec,
    G1Candidate,
    G1PrimaryAuditResult,
    G1ReceiptProjectionV1,
    M3G1CandidateError,
    _primary_candidate_key,
    audit_g1_candidate,
    build_g1_candidate,
    verify_g1_candidate,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_reference import (
    CrossSourceFieldStatsV1,
    CrossSourceReconciliationBundle,
    CrossSourceSamplePlan,
    CrossSourceSummaryV1,
    G1CrossSourcePolicy,
    M3ReferenceError,
    VerifiedReferenceResponse,
    plan_baostock_reference_requests,
    plan_cross_source_reconciliation,
    reconcile_cross_source,
)
from quant.domain import (
    AdjustmentFactorMatchSchema,
    AdjustmentFactorSchema,
    Bar1dSchema,
    BenchmarkBar1dSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    CorporateActionSelectionEvidenceSchema,
    IndexConstituentObservationSchema,
    InstrumentSchema,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TradeCalendarSchema,
    UniverseMembershipSchema,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REL_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RELEASE_IDENTITY_SCHEMA = "m3-g1-release-identity-v1"
_QUALITY_SCHEMA: Literal["m3-g1-quality-v1"] = "m3-g1-quality-v1"
_MANIFEST_SCHEMA_V1: Literal["m3-g1-manifest-v1"] = "m3-g1-manifest-v1"
_MANIFEST_SCHEMA_V2: Literal["m3-g1-manifest-v2"] = "m3-g1-manifest-v2"
_MANIFEST_SCHEMA_V3: Literal["m3-g1-manifest-v3"] = "m3-g1-manifest-v3"
_MANIFEST_SCHEMA_V4: Literal["m3-g1-manifest-v4"] = "m3-g1-manifest-v4"
_MANIFEST_SCHEMA_V5: Literal["m3-g1-manifest-v5"] = "m3-g1-manifest-v5"
_MANIFEST_SCHEMA = _MANIFEST_SCHEMA_V5
# Manifest historical interpretation contract: exact mapper literal per schema.
_MANIFEST_MAPPER_VERSION_V1 = "m3-g1-tushare-mapper-v1"
_MANIFEST_MAPPER_VERSION_V2 = "m3-g1-tushare-mapper-v2"
_MANIFEST_MAPPER_VERSION_V3 = "m3-g1-tushare-mapper-v3"
_MANIFEST_MAPPER_VERSION_V4 = "m3-g1-tushare-mapper-v4"
_MANIFEST_MAPPER_VERSION_V5 = "m3-g1-tushare-mapper-v5"
_TABLE_SCHEMA_VERSION = "v3"
_TABLE_SCHEMA_VERSIONS_KNOWN = frozenset({"v2", "v3"})
_BENCHMARK_MODE = "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
_BENCHMARK_METHOD_VERSION = "tushare_510300_fund_daily_fund_adj_hfq_v1"
_BENCHMARK_DIVIDEND_RECONCILIATION_VERSION = "tushare_fund_div_implemented_cash_v1"
_SUMMARY_SCHEMA: Literal["m3-g1-cross-source-v1"] = "m3-g1-cross-source-v1"
_SAMPLE_SCHEMA: Literal["m3-g1-cross-source-sample-v1"] = "m3-g1-cross-source-sample-v1"
_SAMPLE_SYMBOLS: Literal[30] = 30
_DATES_PER_SYMBOL: Literal[20] = 20
_KEY_COUNT = 600
_COMPARISON_COUNT = 3000
_MANIFEST_NAME = "manifest.json"
_QUALITY_NAME = "quality.json"
_SUMMARY_NAME = "cross_source_reconciliation.json"
_DETAIL_NAME = "cross_source_reconciliation.parquet"
_PARQUET_WRITE_KWARGS: dict[str, Any] = {
    "compression": "zstd",
    "compression_level": 3,
    "statistics": True,
    "row_group_size": 65536,
    "use_pyarrow": False,
}
_RENAME_NOREPLACE = 1
_AT_FDCWD = -100
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# Windows defaults to text mode without O_BINARY; binary parquet/json would be corrupted.
_O_BINARY = getattr(os, "O_BINARY", 0)

_PRIMARY_TABLE_ORDER = (
    "adjustment_factor",
    "adjustment_factor_match",
    "bar_1d",
    "benchmark_bar_1d",
    "corporate_action_ledger",
    "corporate_action_reconciliation",
    "corporate_action_selection_evidence",
    "eligible_keys",
    "index_constituent_observation",
    "instrument",
    "price_limit_1d",
    "suspension_1d",
    "trade_calendar",
    "universe_membership",
)

_ISSUE_CODES = frozenset(
    {
        "REQUEST_PLAN_MISMATCH",
        "RECEIPT_INVALID",
        "SCHEMA_INVALID",
        "DUPLICATE_KEY",
        "UNKNOWN_INSTRUMENT",
        "MEMBERSHIP_MISSING_MONTH",
        "MEMBERSHIP_COUNT_MISMATCH",
        "MEMBERSHIP_WEIGHT_INVALID",
        "MEMBERSHIP_INTERVAL_OVERLAP",
        "CALENDAR_MISMATCH",
        "HISTORY_WINDOW_INCOMPLETE",
        "BAR_OR_SUSPENSION_MISSING",
        "BAR_FULL_SUSPENSION_CONFLICT",
        "PARTIAL_SUSPENSION_BAR_MISSING",
        "FACTOR_MISSING",
        "FACTOR_INVALID",
        "PRICE_LIMIT_MISSING",
        "PRICE_LIMIT_INVALID",
        "BENCHMARK_MISSING",
        "CORPORATE_ACTION_INVALID",
        "CORPORATE_ACTION_FACTOR_MISMATCH",
        "CROSS_SOURCE_INCOMPLETE",
        "CROSS_SOURCE_MISMATCH",
    }
)

_ERROR_CODES = frozenset(
    {
        "G1_RELEASE_INPUT_INVALID",
        "G1_RELEASE_QUALITY_FAILED",
        "G1_RELEASE_IDENTITY_MISMATCH",
        "G1_RELEASE_PATH_INVALID",
        "G1_RELEASE_JSON_INVALID",
        "G1_RELEASE_ARTIFACT_INVALID",
        "G1_RELEASE_IO_FAILED",
        "G1_RELEASE_PUBLISH_UNSUPPORTED",
        "G1_RELEASE_CONCURRENT_PUBLISH",
        "G1_RELEASE_VERIFY_FAILED",
    }
)

_DETAIL_COLUMNS = (
    "symbol",
    "trade_date",
    "field",
    "primary_value",
    "reference_value",
    "abs_diff",
    "relative_diff",
    "tolerance",
    "missing_side",
    "matched",
)
_DETAIL_DTYPES = {
    "symbol": pl.Utf8,
    "trade_date": pl.Date,
    "field": pl.Utf8,
    "primary_value": pl.Float64,
    "reference_value": pl.Float64,
    "abs_diff": pl.Float64,
    "relative_diff": pl.Float64,
    "tolerance": pl.Float64,
    "missing_side": pl.Utf8,
    "matched": pl.Boolean,
}


@dataclass(frozen=True)
class _ArtifactSpec:
    path: str
    kind: Literal["primary", "detail", "summary", "quality"]
    candidate_attr: str | None
    logical_table: str
    schema_name: str
    key_columns: tuple[str, ...]
    pandera_schema: Any | None


_ARTIFACT_REGISTRY: tuple[_ArtifactSpec, ...] = (
    _ArtifactSpec(
        "universe_membership.parquet",
        "primary",
        "membership",
        "universe_membership",
        "UniverseMembershipSchema",
        ("universe", "symbol", "effective_from"),
        UniverseMembershipSchema,
    ),
    _ArtifactSpec(
        "eligible_keys.parquet",
        "primary",
        "eligible_keys",
        "eligible_keys",
        "EligibleKeysV1",
        ("as_of", "symbol"),
        None,
    ),
    _ArtifactSpec(
        "bar_1d.parquet",
        "primary",
        "bars",
        "bar_1d",
        "Bar1dSchema",
        ("symbol", "trade_date", "source"),
        Bar1dSchema,
    ),
    _ArtifactSpec(
        "adjustment_factor.parquet",
        "primary",
        "adjustment_factors",
        "adjustment_factor",
        "AdjustmentFactorSchema",
        ("symbol", "effective_date", "source"),
        AdjustmentFactorSchema,
    ),
    _ArtifactSpec(
        "adjustment_factor_match.parquet",
        "primary",
        "factor_match_evidence",
        "adjustment_factor_match",
        "AdjustmentFactorMatchSchema",
        ("symbol", "trade_date", "source"),
        AdjustmentFactorMatchSchema,
    ),
    _ArtifactSpec(
        "benchmark_bar_1d.parquet",
        "primary",
        "benchmark_bars",
        "benchmark_bar_1d",
        "BenchmarkBar1dSchema",
        ("benchmark", "trade_date", "source"),
        BenchmarkBar1dSchema,
    ),
    _ArtifactSpec(
        "suspension_1d.parquet",
        "primary",
        "suspensions",
        "suspension_1d",
        "Suspension1dSchema",
        ("symbol", "trade_date", "source"),
        Suspension1dSchema,
    ),
    _ArtifactSpec(
        "trade_calendar.parquet",
        "primary",
        "calendars",
        "trade_calendar",
        "TradeCalendarSchema",
        ("market", "date"),
        TradeCalendarSchema,
    ),
    _ArtifactSpec(
        "instrument.parquet",
        "primary",
        "instruments",
        "instrument",
        "InstrumentSchema",
        ("symbol",),
        InstrumentSchema,
    ),
    _ArtifactSpec(
        "index_constituent_observation.parquet",
        "primary",
        "observations",
        "index_constituent_observation",
        "IndexConstituentObservationSchema",
        ("universe", "observation_date", "symbol", "source"),
        IndexConstituentObservationSchema,
    ),
    _ArtifactSpec(
        "price_limit_1d.parquet",
        "primary",
        "price_limits",
        "price_limit_1d",
        "PriceLimit1dSchema",
        ("symbol", "trade_date", "source"),
        PriceLimit1dSchema,
    ),
    _ArtifactSpec(
        "corporate_action_ledger.parquet",
        "primary",
        "corporate_actions",
        "corporate_action_ledger",
        "CorporateActionLedgerSchema",
        ("event_id",),
        CorporateActionLedgerSchema,
    ),
    _ArtifactSpec(
        "corporate_action_selection_evidence.parquet",
        "primary",
        "corporate_action_selection_evidence",
        "corporate_action_selection_evidence",
        "CorporateActionSelectionEvidenceSchema",
        ("candidate_id",),
        CorporateActionSelectionEvidenceSchema,
    ),
    _ArtifactSpec(
        "corporate_action_reconciliation.parquet",
        "primary",
        "corporate_action_reconciliation",
        "corporate_action_reconciliation",
        "CorporateActionReconciliationSchema",
        ("symbol", "previous_factor_date", "effective_date"),
        CorporateActionReconciliationSchema,
    ),
    _ArtifactSpec(
        _DETAIL_NAME,
        "detail",
        None,
        "cross_source_detail",
        "CrossSourceReconciliationDetailV1",
        ("symbol", "trade_date", "field"),
        None,
    ),
    _ArtifactSpec(
        _SUMMARY_NAME,
        "summary",
        None,
        "CrossSourceSummaryV1",
        "CrossSourceSummaryV1",
        (),
        None,
    ),
    _ArtifactSpec(
        _QUALITY_NAME,
        "quality",
        None,
        "G1QualityReportV1",
        "G1QualityReportV1",
        (),
        None,
    ),
)

_ARTIFACT_BY_PATH = {item.path: item for item in _ARTIFACT_REGISTRY}
_ARTIFACT_PATHS = tuple(item.path for item in _ARTIFACT_REGISTRY)
_FINAL_ENTRY_NAMES = frozenset({*_ARTIFACT_PATHS, _MANIFEST_NAME})


class M3ReleaseError(ValueError):
    """Stable P4C boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown g1 release error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3ReleaseError({self.code!r})"


@dataclass(frozen=True)
class G1ArtifactEntryV1:
    path: str
    sha256: str
    content_sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    table_schema_version: str
    key_columns: tuple[str, ...]
    min_key: tuple[str, ...] | None
    max_key: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if type(self.path) is not str or not _REL_PATH.fullmatch(self.path):
            raise ValueError("artifact path 非法")
        if self.path not in _ARTIFACT_BY_PATH:
            raise ValueError("artifact path 不在 registry")
        _require_hex64(self.sha256, "artifact sha256")
        _require_hex64(self.content_sha256, "artifact content_sha256")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("artifact size_bytes 非法")
        if type(self.row_count) is not int or self.row_count < 0:
            raise ValueError("artifact row_count 非法")
        if type(self.schema_name) is not str or not self.schema_name:
            raise ValueError("artifact schema_name 非法")
        if self.table_schema_version not in _TABLE_SCHEMA_VERSIONS_KNOWN:
            raise ValueError("artifact table_schema_version 非法")
        if type(self.key_columns) is not tuple or any(
            type(item) is not str for item in self.key_columns
        ):
            raise ValueError("artifact key_columns 非法")
        spec = _ARTIFACT_BY_PATH[self.path]
        if self.schema_name != spec.schema_name or self.key_columns != spec.key_columns:
            raise ValueError("artifact registry 字段不一致")
        if spec.kind in {"summary", "quality"}:
            if self.row_count != 1 or self.key_columns or self.min_key is not None or (
                self.max_key is not None
            ):
                raise ValueError("JSON artifact entry 约束非法")
        elif self.row_count == 0:
            if self.min_key is not None or self.max_key is not None:
                raise ValueError("空 parquet min/max 必须为 null")
        else:
            _validate_key_tuple(self.min_key, len(self.key_columns))
            _validate_key_tuple(self.max_key, len(self.key_columns))
            assert self.min_key is not None and self.max_key is not None
            if self.min_key > self.max_key:
                raise ValueError("artifact min_key/max_key 顺序非法")


@dataclass(frozen=True)
class G1QualityIssueV1:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    count: int
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.code) is not str or self.code not in _ISSUE_CODES:
            raise ValueError("quality issue code 非法")
        if self.severity not in {"ERROR", "WARNING"}:
            raise ValueError("quality issue severity 非法")
        if type(self.message) is not str or not self.message:
            raise ValueError("quality issue message 非法")
        if type(self.count) is not int or self.count < 0:
            raise ValueError("quality issue count 非法")
        if type(self.evidence) is not tuple or any(
            type(item) is not str for item in self.evidence
        ):
            raise ValueError("quality issue evidence 非法")
        if self.evidence != tuple(sorted(self.evidence)):
            raise ValueError("quality issue evidence 必须排序")


@dataclass(frozen=True)
class G1QualityReportV1:
    schema_version: Literal["m3-g1-quality-v1"]
    release_id: str
    primary_candidate_key: str
    plan_sha256: str
    error_count: int
    warning_count: int
    passed: bool
    issues: tuple[G1QualityIssueV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _QUALITY_SCHEMA:
            raise ValueError("quality schema_version 非法")
        _require_hex64(self.release_id, "quality release_id")
        _require_hex64(self.primary_candidate_key, "quality primary_candidate_key")
        _require_hex64(self.plan_sha256, "quality plan_sha256")
        if type(self.issues) is not tuple:
            raise ValueError("quality issues 非法")
        rebuilt: list[G1QualityIssueV1] = []
        for item in self.issues:
            if type(item) is not G1QualityIssueV1:
                raise ValueError("quality issues 元素非法")
            rebuilt.append(
                G1QualityIssueV1(
                    item.code, item.severity, item.message, item.count, item.evidence
                )
            )
        ordered = tuple(
            sorted(
                rebuilt,
                key=lambda value: (value.severity, value.code, value.message, value.evidence),
            )
        )
        if tuple(rebuilt) != ordered:
            raise ValueError("quality issues 必须排序")
        object.__setattr__(self, "issues", ordered)
        errors = sum(1 for item in ordered if item.severity == "ERROR")
        warnings = sum(1 for item in ordered if item.severity == "WARNING")
        if type(self.error_count) is not int or self.error_count != errors:
            raise ValueError("quality error_count 不一致")
        if type(self.warning_count) is not int or self.warning_count != warnings:
            raise ValueError("quality warning_count 不一致")
        if type(self.passed) is not bool:
            raise ValueError("quality passed 必须是 bool")
        if self.passed != (errors == 0):
            raise ValueError("quality passed 与 issues 不一致")


@dataclass(frozen=True)
class G1ManifestV1:
    schema_version: Literal["m3-g1-manifest-v1"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _MANIFEST_SCHEMA_V1:
            raise ValueError("manifest schema_version 非法")
        if self.mapper_version != _MANIFEST_MAPPER_VERSION_V1:
            raise ValueError("manifest mapper_version 非法")
        _validate_manifest_common(self)


@dataclass(frozen=True)
class G1ManifestV2:
    schema_version: Literal["m3-g1-manifest-v2"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    benchmark_mode: str
    benchmark_method_version: str
    benchmark_dividend_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _MANIFEST_SCHEMA_V2:
            raise ValueError("manifest schema_version 非法")
        if self.mapper_version != _MANIFEST_MAPPER_VERSION_V2:
            raise ValueError("manifest mapper_version 非法")
        if self.benchmark_mode != _BENCHMARK_MODE:
            raise ValueError("manifest benchmark_mode 非法")
        if self.benchmark_method_version != _BENCHMARK_METHOD_VERSION:
            raise ValueError("manifest benchmark_method_version 非法")
        if (
            self.benchmark_dividend_reconciliation_version
            != _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
        ):
            raise ValueError("manifest benchmark_dividend_reconciliation_version 非法")
        for name in (
            "benchmark_mode",
            "benchmark_method_version",
            "benchmark_dividend_reconciliation_version",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"manifest {name} 非法")
        _validate_manifest_common(self)


@dataclass(frozen=True)
class G1ManifestV3:
    schema_version: Literal["m3-g1-manifest-v3"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    benchmark_mode: str
    benchmark_method_version: str
    benchmark_dividend_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _MANIFEST_SCHEMA_V3:
            raise ValueError("manifest schema_version 非法")
        if self.mapper_version != _MANIFEST_MAPPER_VERSION_V3:
            raise ValueError("manifest mapper_version 非法")
        if self.benchmark_mode != _BENCHMARK_MODE:
            raise ValueError("manifest benchmark_mode 非法")
        if self.benchmark_method_version != _BENCHMARK_METHOD_VERSION:
            raise ValueError("manifest benchmark_method_version 非法")
        if (
            self.benchmark_dividend_reconciliation_version
            != _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
        ):
            raise ValueError("manifest benchmark_dividend_reconciliation_version 非法")
        for name in (
            "benchmark_mode",
            "benchmark_method_version",
            "benchmark_dividend_reconciliation_version",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"manifest {name} 非法")
        _validate_manifest_common(self)


@dataclass(frozen=True)
class G1ManifestV4:
    schema_version: Literal["m3-g1-manifest-v4"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    benchmark_mode: str
    benchmark_method_version: str
    benchmark_dividend_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _MANIFEST_SCHEMA_V4:
            raise ValueError("manifest schema_version 非法")
        if self.mapper_version != _MANIFEST_MAPPER_VERSION_V4:
            raise ValueError("manifest mapper_version 非法")
        if self.benchmark_mode != _BENCHMARK_MODE:
            raise ValueError("manifest benchmark_mode 非法")
        if self.benchmark_method_version != _BENCHMARK_METHOD_VERSION:
            raise ValueError("manifest benchmark_method_version 非法")
        if (
            self.benchmark_dividend_reconciliation_version
            != _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
        ):
            raise ValueError("manifest benchmark_dividend_reconciliation_version 非法")
        for name in (
            "benchmark_mode",
            "benchmark_method_version",
            "benchmark_dividend_reconciliation_version",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"manifest {name} 非法")
        _validate_manifest_common(self)
        if not any(item.source == "cninfo" for item in self.input_receipts):
            raise ValueError("manifest v4 必须包含 cninfo receipt 闭包")


@dataclass(frozen=True)
class G1ManifestV5:
    schema_version: Literal["m3-g1-manifest-v5"]
    release_id: str
    primary_candidate_key: str
    config_version: str
    g1_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    request_plan_sha256: str
    build_code_version: str
    dependency_fingerprint_sha256: str
    mapper_version: str
    clean_schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    benchmark_mode: str
    benchmark_method_version: str
    benchmark_dividend_reconciliation_version: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    price_limit_required_keys_sha256: str
    sample_plan_sha256: str
    cross_source_summary_sha256: str
    quality_sha256: str
    files: tuple[G1ArtifactEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _MANIFEST_SCHEMA_V5:
            raise ValueError("manifest schema_version 非法")
        if self.mapper_version != _MANIFEST_MAPPER_VERSION_V5:
            raise ValueError("manifest mapper_version 非法")
        if self.benchmark_mode != _BENCHMARK_MODE:
            raise ValueError("manifest benchmark_mode 非法")
        if self.benchmark_method_version != _BENCHMARK_METHOD_VERSION:
            raise ValueError("manifest benchmark_method_version 非法")
        if (
            self.benchmark_dividend_reconciliation_version
            != _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
        ):
            raise ValueError("manifest benchmark_dividend_reconciliation_version 非法")
        for name in (
            "benchmark_mode",
            "benchmark_method_version",
            "benchmark_dividend_reconciliation_version",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"manifest {name} 非法")
        _validate_manifest_common(self)
        if not any(
            item.source == CNINFO_SOURCE
            and item.endpoint == CNINFO_ENDPOINT
            and item.columns == CNINFO_STOCK_ALLOTMENT_FIELDS
            for item in self.input_receipts
        ):
            raise ValueError("manifest v5 必须包含完整官方列 cninfo stock_allotment receipt")
        if any(item.table_schema_version != _TABLE_SCHEMA_VERSION for item in self.files):
            raise ValueError("manifest v5 table_schema_version 必须为 v3")


def _validate_manifest_common(
    manifest: G1ManifestV1 | G1ManifestV2 | G1ManifestV3 | G1ManifestV4 | G1ManifestV5,
) -> None:
    for name in (
        "release_id",
        "primary_candidate_key",
        "g1_config_sha256",
        "request_plan_sha256",
        "dependency_fingerprint_sha256",
        "price_limit_required_keys_sha256",
        "sample_plan_sha256",
        "cross_source_summary_sha256",
        "quality_sha256",
    ):
        _require_hex64(getattr(manifest, name), f"manifest {name}")
    for name in (
        "config_version",
        "build_code_version",
        "mapper_version",
        "clean_schema_version",
        "membership_method_version",
        "price_limit_method_version",
        "corporate_action_selection_version",
        "corporate_action_reconciliation_version",
    ):
        value = getattr(manifest, name)
        if type(value) is not str or not value:
            raise ValueError(f"manifest {name} 非法")
    for name in ("signal_start", "signal_end", "history_start", "history_end"):
        if type(getattr(manifest, name)) is not dt.date:
            raise ValueError(f"manifest {name} 非法")
    if not (
        manifest.history_start
        <= manifest.signal_start
        <= manifest.signal_end
        <= manifest.history_end
    ):
        raise ValueError("manifest 日期关系非法")
    if type(manifest.input_receipts) is not tuple or not manifest.input_receipts:
        raise ValueError("manifest input_receipts 非法")
    rebuilt_receipts: list[G1ReceiptProjectionV1] = []
    for item in manifest.input_receipts:
        if type(item) is not G1ReceiptProjectionV1:
            raise ValueError("manifest input_receipts 元素非法")
        rebuilt_receipts.append(
            G1ReceiptProjectionV1(
                source=item.source,
                request_id=item.request_id,
                endpoint=item.endpoint,
                parameters_sha256=item.parameters_sha256,
                stable_response_sha256=item.stable_response_sha256,
                row_count=item.row_count,
                columns=item.columns,
            )
        )
    ordered_receipts = tuple(
        sorted(
            rebuilt_receipts,
            key=lambda value: (value.source, value.endpoint, value.request_id),
        )
    )
    if tuple(rebuilt_receipts) != ordered_receipts:
        raise ValueError("manifest input_receipts 必须排序")
    if len({(r.source, r.endpoint, r.request_id) for r in ordered_receipts}) != len(
        ordered_receipts
    ):
        raise ValueError("manifest input_receipts 必须唯一")
    object.__setattr__(manifest, "input_receipts", ordered_receipts)
    if type(manifest.files) is not tuple or len(manifest.files) != len(_ARTIFACT_REGISTRY):
        raise ValueError("manifest files 数量非法")
    rebuilt_files: list[G1ArtifactEntryV1] = []
    for file_item in manifest.files:
        if type(file_item) is not G1ArtifactEntryV1:
            raise ValueError("manifest files 元素非法")
        rebuilt_files.append(
            G1ArtifactEntryV1(
                file_item.path,
                file_item.sha256,
                file_item.content_sha256,
                file_item.size_bytes,
                file_item.row_count,
                file_item.schema_name,
                file_item.table_schema_version,
                file_item.key_columns,
                file_item.min_key,
                file_item.max_key,
            )
        )
    ordered_files = tuple(sorted(rebuilt_files, key=lambda value: value.path))
    if tuple(rebuilt_files) != ordered_files:
        raise ValueError("manifest files 必须按 path 排序")
    if tuple(item.path for item in ordered_files) != tuple(sorted(_ARTIFACT_PATHS)):
        raise ValueError("manifest files path 集合非法")
    object.__setattr__(manifest, "files", ordered_files)


@dataclass(frozen=True)
class G1Release:
    release_id: str
    root: Path
    manifest_path: Path
    quality_path: Path

    def __post_init__(self) -> None:
        _require_hex64(self.release_id, "release_id")
        if not isinstance(self.root, Path) or not isinstance(
            self.manifest_path, Path
        ) or not isinstance(self.quality_path, Path):
            raise ValueError("release path 类型非法")
        try:
            root = _absolute_path(self.root)
            if root.name != self.release_id:
                raise ValueError("release root.name 必须等于 release_id")
            manifest = _absolute_path(self.manifest_path)
            quality = _absolute_path(self.quality_path)
            if manifest != root / _MANIFEST_NAME or quality != root / _QUALITY_NAME:
                raise ValueError("release JSON path 必须是 root 直属文件")
            object.__setattr__(self, "root", root)
            object.__setattr__(self, "manifest_path", manifest)
            object.__setattr__(self, "quality_path", quality)
        except M3ReleaseError:
            raise
        except Exception as exc:
            raise ValueError("release path 自证失败") from exc


@dataclass(frozen=True)
class G1ReleaseInputs:
    build_inputs: G1BuildInputs
    cross_source_policy: G1CrossSourcePolicy
    reference_responses: tuple[VerifiedReferenceResponse, ...]

    def __post_init__(self) -> None:
        try:
            build_inputs = _consume_build_inputs(self.build_inputs)
            policy = _consume_policy(self.cross_source_policy)
            if type(self.reference_responses) is not tuple:
                raise M3ReleaseError("G1_RELEASE_INPUT_INVALID")
            responses = tuple(
                _consume_verified_reference(item) for item in self.reference_responses
            )
            object.__setattr__(self, "build_inputs", build_inputs)
            object.__setattr__(self, "cross_source_policy", policy)
            object.__setattr__(self, "reference_responses", responses)
        except M3ReleaseError:
            raise
        except (TypeError, ValueError, M3G1CandidateError, M3ReferenceError):
            raise M3ReleaseError("G1_RELEASE_INPUT_INVALID") from None


@dataclass(frozen=True)
class G1PreparedRelease:
    candidate: G1Candidate
    primary_audit: G1PrimaryAuditResult
    reconciliation: CrossSourceReconciliationBundle
    release_id: str
    quality: G1QualityReportV1

    def __post_init__(self) -> None:
        try:
            if type(self.candidate) is not G1Candidate:
                raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
            candidate = G1Candidate(
                build_spec=self.candidate.build_spec,
                request_plan=self.candidate.request_plan,
                signal_start=self.candidate.signal_start,
                signal_end=self.candidate.signal_end,
                history_start=self.candidate.history_start,
                history_end=self.candidate.history_end,
                input_receipts=self.candidate.input_receipts,
                calendars=self.candidate.calendars,
                instruments=self.candidate.instruments,
                observations=self.candidate.observations,
                membership=self.candidate.membership,
                eligible_keys=self.candidate.eligible_keys,
                bars=self.candidate.bars,
                adjustment_factors=self.candidate.adjustment_factors,
                factor_match_evidence=self.candidate.factor_match_evidence,
                benchmark_bars=self.candidate.benchmark_bars,
                suspensions=self.candidate.suspensions,
                price_limits=self.candidate.price_limits,
                corporate_actions=self.candidate.corporate_actions,
                corporate_action_selection_evidence=(
                    self.candidate.corporate_action_selection_evidence
                ),
                corporate_action_reconciliation=(
                    self.candidate.corporate_action_reconciliation
                ),
                table_content_digests=self.candidate.table_content_digests,
                price_limit_required_keys_sha256=(
                    self.candidate.price_limit_required_keys_sha256
                ),
                primary_candidate_key=self.candidate.primary_candidate_key,
            )
            if type(self.primary_audit) is not G1PrimaryAuditResult:
                raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
            audit = G1PrimaryAuditResult(
                primary_candidate_key=self.primary_audit.primary_candidate_key,
                plan_sha256=self.primary_audit.plan_sha256,
                input_receipts=self.primary_audit.input_receipts,
                table_content_digests=self.primary_audit.table_content_digests,
                issues=self.primary_audit.issues,
                passed=self.primary_audit.passed,
            )
            if type(self.reconciliation) is not CrossSourceReconciliationBundle:
                raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
            reconciliation = CrossSourceReconciliationBundle(
                sample_plan=self.reconciliation.sample_plan,
                reference_receipts=self.reconciliation.reference_receipts,
                detail=self.reconciliation.detail,
                detail_sha256=self.reconciliation.detail_sha256,
                summary=self.reconciliation.summary,
                summary_sha256=self.reconciliation.summary_sha256,
                issues=self.reconciliation.issues,
                passed=self.reconciliation.passed,
            )
            if not audit.passed or not reconciliation.passed:
                raise M3ReleaseError("G1_RELEASE_QUALITY_FAILED")
            if (
                audit.primary_candidate_key != candidate.primary_candidate_key
                or audit.plan_sha256 != candidate.request_plan.plan_sha256
                or audit.input_receipts != candidate.input_receipts
                or audit.table_content_digests != candidate.table_content_digests
            ):
                raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
            if (
                reconciliation.sample_plan.primary_candidate_key
                != candidate.primary_candidate_key
            ):
                raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
            release_id = _release_id_from_parts(
                primary_candidate_key=candidate.primary_candidate_key,
                sample_plan_sha256=reconciliation.sample_plan.sample_plan_sha256,
                reference_receipts=reconciliation.reference_receipts,
                cross_source_detail_sha256=reconciliation.detail_sha256,
                cross_source_summary_sha256=reconciliation.summary_sha256,
            )
            quality = _build_quality(
                release_id=release_id,
                primary_candidate_key=candidate.primary_candidate_key,
                plan_sha256=candidate.request_plan.plan_sha256,
            )
            if self.release_id != release_id:
                raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
            if type(self.quality) is not G1QualityReportV1 or self.quality != quality:
                raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
            object.__setattr__(self, "candidate", candidate)
            object.__setattr__(self, "primary_audit", audit)
            object.__setattr__(self, "reconciliation", reconciliation)
            object.__setattr__(self, "release_id", release_id)
            object.__setattr__(self, "quality", quality)
        except M3ReleaseError:
            raise
        except (TypeError, ValueError, M3G1CandidateError, M3ReferenceError):
            raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH") from None


@dataclass(frozen=True)
class VerifiedG1Release:
    release: G1Release
    manifest: G1ManifestV1 | G1ManifestV2 | G1ManifestV3 | G1ManifestV4 | G1ManifestV5
    manifest_sha256: str
    quality: G1QualityReportV1
    quality_sha256: str
    artifact_paths: tuple[tuple[str, Path], ...]

    def __post_init__(self) -> None:
        if type(self.release) is not G1Release:
            raise ValueError("verified release 类型非法")
        if type(self.manifest) not in {
            G1ManifestV1,
            G1ManifestV2,
            G1ManifestV3,
            G1ManifestV4,
            G1ManifestV5,
        }:
            raise ValueError("verified manifest 类型非法")
        if type(self.quality) is not G1QualityReportV1:
            raise ValueError("verified quality 类型非法")
        _require_hex64(self.manifest_sha256, "manifest_sha256")
        _require_hex64(self.quality_sha256, "quality_sha256")
        if type(self.artifact_paths) is not tuple or len(self.artifact_paths) != len(
            _ARTIFACT_REGISTRY
        ):
            raise ValueError("verified artifact_paths 数量非法")
        rebuilt: list[tuple[str, Path]] = []
        for item in self.artifact_paths:
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("verified artifact_paths 元素非法")
            name, path = item
            if type(name) is not str or not isinstance(path, Path):
                raise ValueError("verified artifact_paths 元素非法")
            abs_path = _absolute_path(path)
            if abs_path.parent != self.release.root or abs_path.name != name:
                raise ValueError("verified artifact_paths 必须受控于 release.root")
            rebuilt.append((name, abs_path))
        ordered = tuple(sorted(rebuilt, key=lambda value: value[0]))
        if tuple(rebuilt) != ordered:
            raise ValueError("verified artifact_paths 必须按 path 排序")
        if tuple(name for name, _ in ordered) != tuple(sorted(_ARTIFACT_PATHS)):
            raise ValueError("verified artifact_paths 集合非法")
        object.__setattr__(self, "artifact_paths", ordered)


def prepare_g1_release(*, inputs: G1ReleaseInputs) -> G1PreparedRelease:
    """Pure rebuild of P4A/P4B + release identity/quality; zero IO/network."""
    try:
        rebuilt_inputs = G1ReleaseInputs(
            build_inputs=inputs.build_inputs,
            cross_source_policy=inputs.cross_source_policy,
            reference_responses=inputs.reference_responses,
        )
        candidate = build_g1_candidate(inputs=rebuilt_inputs.build_inputs)
        verify_g1_candidate(inputs=rebuilt_inputs.build_inputs, candidate=candidate)
        audit = audit_g1_candidate(candidate=candidate)
        if not audit.passed:
            raise M3ReleaseError("G1_RELEASE_QUALITY_FAILED")
        sample_plan = plan_cross_source_reconciliation(
            candidate=candidate, policy=rebuilt_inputs.cross_source_policy
        )
        request_plan = plan_baostock_reference_requests(sample_plan=sample_plan)
        if len(rebuilt_inputs.reference_responses) != len(request_plan.requests):
            raise M3ReleaseError("G1_RELEASE_QUALITY_FAILED")
        expected_ids = {item.request_id for item in request_plan.requests}
        actual_ids = {item.spec.request_id for item in rebuilt_inputs.reference_responses}
        if expected_ids != actual_ids:
            raise M3ReleaseError("G1_RELEASE_QUALITY_FAILED")
        reconciliation = reconcile_cross_source(
            candidate=candidate,
            sample_plan=sample_plan,
            reference_responses=rebuilt_inputs.reference_responses,
            policy=rebuilt_inputs.cross_source_policy,
        )
        if not reconciliation.passed:
            raise M3ReleaseError("G1_RELEASE_QUALITY_FAILED")
        release_id = _release_id_from_parts(
            primary_candidate_key=candidate.primary_candidate_key,
            sample_plan_sha256=reconciliation.sample_plan.sample_plan_sha256,
            reference_receipts=reconciliation.reference_receipts,
            cross_source_detail_sha256=reconciliation.detail_sha256,
            cross_source_summary_sha256=reconciliation.summary_sha256,
        )
        quality = _build_quality(
            release_id=release_id,
            primary_candidate_key=candidate.primary_candidate_key,
            plan_sha256=candidate.request_plan.plan_sha256,
        )
        return G1PreparedRelease(
            candidate=candidate,
            primary_audit=audit,
            reconciliation=reconciliation,
            release_id=release_id,
            quality=quality,
        )
    except M3ReleaseError:
        raise
    except (M3G1CandidateError, M3ReferenceError, TypeError, ValueError):
        raise M3ReleaseError("G1_RELEASE_INPUT_INVALID") from None


def publish_g1_release(*, output_root: Path, inputs: G1ReleaseInputs) -> G1Release:
    """Prepare then atomically publish an immutable G1 release under output_root."""
    prepared = prepare_g1_release(inputs=inputs)
    staging_container: Path | None = None
    staging_identity: tuple[int, int] | None = None
    primary_error: BaseException | None = None
    try:
        root = _prepare_output_root(output_root)
        final_dir = root / prepared.release_id
        if _path_exists_nofollow(final_dir):
            return _reuse_existing_final(final_dir=final_dir, prepared=prepared)

        staging_container = root / f".m3-g1-staging.{prepared.release_id}.{uuid.uuid4().hex}"
        _mkdir_exclusive(staging_container, mode=0o700)
        staging_identity = _dir_identity(staging_container)
        stage_release = staging_container / prepared.release_id
        _mkdir_exclusive(stage_release, mode=0o700)

        files_entries, quality_sha, summary_sha = _write_stage_artifacts(
            stage_root=stage_release, prepared=prepared
        )
        manifest = _build_manifest(
            prepared=prepared,
            files=files_entries,
            quality_sha256=quality_sha,
            summary_sha256=summary_sha,
        )
        manifest_bytes = _canonical_json_bytes(_manifest_to_jsonable(manifest))
        _exclusive_write_bytes(stage_release / _MANIFEST_NAME, manifest_bytes)
        _fsync_directory(stage_release)
        _fsync_directory(staging_container)

        stage_release_obj = G1Release(
            release_id=prepared.release_id,
            root=stage_release,
            manifest_path=stage_release / _MANIFEST_NAME,
            quality_path=stage_release / _QUALITY_NAME,
        )
        verified_stage = verify_g1_release(release=stage_release_obj)
        _assert_prepared_matches_verified(prepared, verified_stage)

        try:
            _renameat2_noreplace(stage_release, final_dir)
        except M3ReleaseError as exc:
            if exc.code == "G1_RELEASE_CONCURRENT_PUBLISH":
                _cleanup_staging(staging_container, staging_identity)
                staging_container = None
                return _reuse_existing_final(final_dir=final_dir, prepared=prepared)
            raise

        _fsync_directory(root)
        release = G1Release(
            release_id=prepared.release_id,
            root=final_dir,
            manifest_path=final_dir / _MANIFEST_NAME,
            quality_path=final_dir / _QUALITY_NAME,
        )
        verified_final = verify_g1_release(release=release)
        _assert_prepared_matches_verified(prepared, verified_final)
        _cleanup_staging(staging_container, staging_identity)
        staging_container = None
        return release
    except M3ReleaseError as exc:
        primary_error = exc
        raise
    except OSError:
        primary_error = M3ReleaseError("G1_RELEASE_IO_FAILED")
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None
    finally:
        if staging_container is not None and staging_identity is not None:
            try:
                _cleanup_staging(staging_container, staging_identity)
            except M3ReleaseError:
                if primary_error is None:
                    raise


def verify_g1_release(*, release: G1Release) -> VerifiedG1Release:
    """Strict final-directory verification; never mutates final."""
    try:
        rebuilt_release = G1Release(
            release_id=release.release_id,
            root=release.root,
            manifest_path=release.manifest_path,
            quality_path=release.quality_path,
        )
        root = rebuilt_release.root
        _reject_ancestor_symlinks(root)
        # Physical identity of every ancestor from root.parent to filesystem root.
        # Entry path illegality keeps PATH_INVALID; mid-verify drift maps to VERIFY_FAILED.
        ancestor_before = _snapshot_ancestor_identities(
            root, code="G1_RELEASE_PATH_INVALID"
        )
        root_before = _dir_identity(root)
        if not stat.S_ISDIR(os.lstat(root).st_mode):
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")

        entries = _list_final_entries(root)
        if set(entries) != _FINAL_ENTRY_NAMES:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")

        file_idents: dict[str, tuple[int, int]] = {}
        for name in sorted(entries):
            path = root / name
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
            if st.st_nlink != 1:
                raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
            ident = (st.st_dev, st.st_ino)
            if ident in file_idents.values():
                raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
            file_idents[name] = ident

        manifest_bytes = _read_regular_file_bytes(root / _MANIFEST_NAME)
        quality_bytes = _read_regular_file_bytes(root / _QUALITY_NAME)
        summary_bytes = _read_regular_file_bytes(root / _SUMMARY_NAME)
        manifest = _parse_manifest_bytes(manifest_bytes)
        quality = _parse_quality_bytes(quality_bytes)
        summary = _parse_summary_bytes(summary_bytes)
        if _canonical_json_bytes(_manifest_to_jsonable(manifest)) != manifest_bytes:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        if _canonical_json_bytes(asdict(quality)) != quality_bytes:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        if _canonical_json_bytes(asdict(summary)) != summary_bytes:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")

        if manifest.release_id != rebuilt_release.release_id:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        quality_sha = hashlib.sha256(quality_bytes).hexdigest()
        summary_sha = hashlib.sha256(summary_bytes).hexdigest()
        if quality_sha != manifest.quality_sha256:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        if summary_sha != manifest.cross_source_summary_sha256:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        if quality.release_id != manifest.release_id:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        if quality.primary_candidate_key != manifest.primary_candidate_key:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        if quality.plan_sha256 != manifest.request_plan_sha256:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        if (
            not quality.passed
            or quality.issues
            or quality.error_count != 0
            or quality.warning_count != 0
        ):
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")

        frames: dict[str, pl.DataFrame] = {}
        recomputed_entries: list[G1ArtifactEntryV1] = []
        for entry in manifest.files:
            spec = _ARTIFACT_BY_PATH[entry.path]
            path = root / entry.path
            raw = _read_regular_file_bytes(path)
            if hashlib.sha256(raw).hexdigest() != entry.sha256:
                raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
            if len(raw) != entry.size_bytes:
                raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
            if spec.kind == "quality":
                if raw != quality_bytes:
                    raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
                recomputed = _json_artifact_entry(
                    path_name=entry.path,
                    payload=quality_bytes,
                    content_sha256=quality_sha,
                    schema_name=spec.schema_name,
                )
            elif spec.kind == "summary":
                if raw != summary_bytes:
                    raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
                recomputed = _json_artifact_entry(
                    path_name=entry.path,
                    payload=summary_bytes,
                    content_sha256=summary_sha,
                    schema_name=spec.schema_name,
                )
            else:
                frame = _read_exact_parquet(path, spec)
                frames[spec.logical_table] = frame
                content = clean_table_content_sha256(
                    table_name=spec.logical_table, frame=frame
                )
                recomputed = _parquet_artifact_entry(
                    path_name=entry.path,
                    raw=raw,
                    frame=frame,
                    content_sha256=content,
                    schema_name=spec.schema_name,
                    key_columns=spec.key_columns,
                )
            if recomputed != entry:
                raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
            recomputed_entries.append(recomputed)

        detail = frames["cross_source_detail"]
        sample_keys = _sample_keys_from_detail(detail)
        sample_plan = CrossSourceSamplePlan(
            schema_version=_SAMPLE_SCHEMA,
            primary_candidate_key=manifest.primary_candidate_key,
            sample_symbols=_SAMPLE_SYMBOLS,
            dates_per_symbol=_DATES_PER_SYMBOL,
            keys=sample_keys,
            sample_plan_sha256=manifest.sample_plan_sha256,
        )
        baostock_receipts = tuple(
            item for item in manifest.input_receipts if item.source == "baostock"
        )
        if len(baostock_receipts) != _SAMPLE_SYMBOLS:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        detail_sha = clean_table_content_sha256(
            table_name="cross_source_detail", frame=detail
        )
        if detail_sha != summary.detail_sha256:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        bundle = CrossSourceReconciliationBundle(
            sample_plan=sample_plan,
            reference_receipts=baostock_receipts,
            detail=detail,
            detail_sha256=detail_sha,
            summary=summary,
            summary_sha256=summary_sha,
            issues=(),
            passed=True,
        )
        if not bundle.passed:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")

        digests = tuple(
            (
                name,
                clean_table_content_sha256(
                    table_name=name, frame=frames[name]
                ),
            )
            for name in _PRIMARY_TABLE_ORDER
        )
        required = require_g1_price_limit_coverage(
            price_limits=frames["price_limit_1d"],
            eligible_keys=frames["eligible_keys"],
            suspensions=frames["suspension_1d"],
            calendars=frames["trade_calendar"],
            instruments=frames["instrument"],
            bars=frames["bar_1d"],
            history=HistoryWindow(manifest.history_start, manifest.history_end),
        )
        required_digest = clean_table_content_sha256(
            table_name="price_limit_required_keys", frame=required
        )
        if required_digest != manifest.price_limit_required_keys_sha256:
            raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
        tushare_receipts = tuple(
            item for item in manifest.input_receipts if item.source == "tushare"
        )
        primary_receipts = tuple(
            item
            for item in manifest.input_receipts
            if item.source in {"tushare", "cninfo"}
        )
        primary = _primary_from_manifest(
            manifest=manifest,
            tushare_receipts=tushare_receipts,
            primary_receipts=primary_receipts,
            table_content_digests=digests,
            price_limit_required_keys_sha256=required_digest,
        )
        if primary != manifest.primary_candidate_key:
            raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
        release_id = _release_id_from_parts(
            primary_candidate_key=primary,
            sample_plan_sha256=manifest.sample_plan_sha256,
            reference_receipts=baostock_receipts,
            cross_source_detail_sha256=detail_sha,
            cross_source_summary_sha256=summary_sha,
        )
        if release_id != manifest.release_id:
            raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")

        if _dir_identity(root) != root_before:
            raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        for name, ident in file_idents.items():
            st = os.lstat(root / name)
            if (st.st_dev, st.st_ino) != ident:
                raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
        _assert_ancestor_identities_unchanged(
            ancestor_before, code="G1_RELEASE_VERIFY_FAILED"
        )

        artifact_paths = tuple(
            (path, root / path) for path in sorted(_ARTIFACT_PATHS)
        )
        return VerifiedG1Release(
            release=rebuilt_release,
            manifest=manifest,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            quality=quality,
            quality_sha256=quality_sha,
            artifact_paths=artifact_paths,
        )
    except M3ReleaseError:
        raise
    except (TypeError, ValueError, OSError, pl.exceptions.PolarsError):
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED") from None


def read_g1_manifest(
    path: Path,
) -> G1ManifestV1 | G1ManifestV2 | G1ManifestV3 | G1ManifestV4 | G1ManifestV5:
    try:
        payload = _read_regular_file_bytes(_absolute_path(path))
        manifest = _parse_manifest_bytes(payload)
        if _canonical_json_bytes(_manifest_to_jsonable(manifest)) != payload:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        return manifest
    except M3ReleaseError:
        raise
    except (TypeError, ValueError, OSError):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID") from None


def read_g1_quality(path: Path) -> G1QualityReportV1:
    try:
        payload = _read_regular_file_bytes(_absolute_path(path))
        quality = _parse_quality_bytes(payload)
        if _canonical_json_bytes(asdict(quality)) != payload:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        return quality
    except M3ReleaseError:
        raise
    except (TypeError, ValueError, OSError):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID") from None


def read_cross_source_summary(path: Path) -> CrossSourceSummaryV1:
    try:
        payload = _read_regular_file_bytes(_absolute_path(path))
        summary = _parse_summary_bytes(payload)
        if _canonical_json_bytes(asdict(summary)) != payload:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        return summary
    except M3ReleaseError:
        raise
    except (TypeError, ValueError, OSError):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID") from None


def _build_quality(
    *, release_id: str, primary_candidate_key: str, plan_sha256: str
) -> G1QualityReportV1:
    return G1QualityReportV1(
        schema_version=_QUALITY_SCHEMA,
        release_id=release_id,
        primary_candidate_key=primary_candidate_key,
        plan_sha256=plan_sha256,
        error_count=0,
        warning_count=0,
        passed=True,
        issues=(),
    )


def _release_id_from_parts(
    *,
    primary_candidate_key: str,
    sample_plan_sha256: str,
    reference_receipts: tuple[G1ReceiptProjectionV1, ...],
    cross_source_detail_sha256: str,
    cross_source_summary_sha256: str,
) -> str:
    ordered = tuple(
        sorted(
            reference_receipts,
            key=lambda value: (value.source, value.endpoint, value.request_id),
        )
    )
    return _sha256_json(
        {
            "schema_version": _RELEASE_IDENTITY_SCHEMA,
            "primary_candidate_key": primary_candidate_key,
            "sample_plan_sha256": sample_plan_sha256,
            "reference_receipts": [asdict(item) for item in ordered],
            "cross_source_detail_sha256": cross_source_detail_sha256,
            "cross_source_summary_sha256": cross_source_summary_sha256,
        }
    )


def _build_manifest(
    *,
    prepared: G1PreparedRelease,
    files: tuple[G1ArtifactEntryV1, ...],
    quality_sha256: str,
    summary_sha256: str,
) -> G1ManifestV5:
    candidate = prepared.candidate
    receipts = tuple(
        sorted(
            (*candidate.input_receipts, *prepared.reconciliation.reference_receipts),
            key=lambda value: (value.source, value.endpoint, value.request_id),
        )
    )
    return G1ManifestV5(
        schema_version=_MANIFEST_SCHEMA_V5,
        release_id=prepared.release_id,
        primary_candidate_key=candidate.primary_candidate_key,
        config_version=candidate.build_spec.config_version,
        g1_config_sha256=candidate.build_spec.g1_config_sha256,
        signal_start=candidate.signal_start,
        signal_end=candidate.signal_end,
        history_start=candidate.history_start,
        history_end=candidate.history_end,
        request_plan_sha256=candidate.request_plan.plan_sha256,
        build_code_version=candidate.build_spec.build_code_version,
        dependency_fingerprint_sha256=candidate.build_spec.dependency_fingerprint_sha256,
        mapper_version=candidate.build_spec.mapper_version,
        clean_schema_version=candidate.build_spec.schema_version,
        membership_method_version=candidate.build_spec.membership_method_version,
        price_limit_method_version=candidate.build_spec.price_limit_method_version,
        corporate_action_selection_version=(
            candidate.build_spec.corporate_action_selection_version
        ),
        corporate_action_reconciliation_version=(
            candidate.build_spec.corporate_action_reconciliation_version
        ),
        benchmark_mode=candidate.build_spec.benchmark_mode,
        benchmark_method_version=candidate.build_spec.benchmark_method_version,
        benchmark_dividend_reconciliation_version=(
            candidate.build_spec.benchmark_dividend_reconciliation_version
        ),
        input_receipts=receipts,
        price_limit_required_keys_sha256=candidate.price_limit_required_keys_sha256,
        sample_plan_sha256=prepared.reconciliation.sample_plan.sample_plan_sha256,
        cross_source_summary_sha256=summary_sha256,
        quality_sha256=quality_sha256,
        files=tuple(sorted(files, key=lambda item: item.path)),
    )


def _write_stage_artifacts(
    *, stage_root: Path, prepared: G1PreparedRelease
) -> tuple[tuple[G1ArtifactEntryV1, ...], str, str]:
    quality_bytes = _canonical_json_bytes(asdict(prepared.quality))
    summary_bytes = _canonical_json_bytes(asdict(prepared.reconciliation.summary))
    quality_sha = hashlib.sha256(quality_bytes).hexdigest()
    summary_sha = hashlib.sha256(summary_bytes).hexdigest()
    if summary_sha != prepared.reconciliation.summary_sha256:
        raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
    entries: list[G1ArtifactEntryV1] = []
    for spec in _ARTIFACT_REGISTRY:
        target = stage_root / spec.path
        if spec.kind == "quality":
            _exclusive_write_bytes(target, quality_bytes)
            entries.append(
                _json_artifact_entry(
                    path_name=spec.path,
                    payload=quality_bytes,
                    content_sha256=quality_sha,
                    schema_name=spec.schema_name,
                )
            )
        elif spec.kind == "summary":
            _exclusive_write_bytes(target, summary_bytes)
            entries.append(
                _json_artifact_entry(
                    path_name=spec.path,
                    payload=summary_bytes,
                    content_sha256=summary_sha,
                    schema_name=spec.schema_name,
                )
            )
        elif spec.kind == "detail":
            frame = prepared.reconciliation.detail
            raw = _frame_to_parquet_bytes(frame)
            _exclusive_write_bytes(target, raw)
            content = clean_table_content_sha256(
                table_name=spec.logical_table, frame=frame
            )
            entries.append(
                _parquet_artifact_entry(
                    path_name=spec.path,
                    raw=raw,
                    frame=frame,
                    content_sha256=content,
                    schema_name=spec.schema_name,
                    key_columns=spec.key_columns,
                )
            )
        else:
            assert spec.candidate_attr is not None
            frame = getattr(prepared.candidate, spec.candidate_attr)
            raw = _frame_to_parquet_bytes(frame)
            _exclusive_write_bytes(target, raw)
            content = clean_table_content_sha256(
                table_name=spec.logical_table, frame=frame
            )
            entries.append(
                _parquet_artifact_entry(
                    path_name=spec.path,
                    raw=raw,
                    frame=frame,
                    content_sha256=content,
                    schema_name=spec.schema_name,
                    key_columns=spec.key_columns,
                )
            )
    return tuple(entries), quality_sha, summary_sha


def _frame_to_parquet_bytes(frame: pl.DataFrame) -> bytes:
    import io

    buffer = io.BytesIO()
    frame.write_parquet(buffer, **_PARQUET_WRITE_KWARGS)
    return buffer.getvalue()


def _json_artifact_entry(
    *, path_name: str, payload: bytes, content_sha256: str, schema_name: str
) -> G1ArtifactEntryV1:
    return G1ArtifactEntryV1(
        path=path_name,
        sha256=hashlib.sha256(payload).hexdigest(),
        content_sha256=content_sha256,
        size_bytes=len(payload),
        row_count=1,
        schema_name=schema_name,
        table_schema_version=_TABLE_SCHEMA_VERSION,
        key_columns=(),
        min_key=None,
        max_key=None,
    )


def _parquet_artifact_entry(
    *,
    path_name: str,
    raw: bytes,
    frame: pl.DataFrame,
    content_sha256: str,
    schema_name: str,
    key_columns: tuple[str, ...],
) -> G1ArtifactEntryV1:
    min_key, max_key = _key_range(frame, key_columns)
    return G1ArtifactEntryV1(
        path=path_name,
        sha256=hashlib.sha256(raw).hexdigest(),
        content_sha256=content_sha256,
        size_bytes=len(raw),
        row_count=frame.height,
        schema_name=schema_name,
        table_schema_version=_TABLE_SCHEMA_VERSION,
        key_columns=key_columns,
        min_key=min_key,
        max_key=max_key,
    )


def _key_range(
    frame: pl.DataFrame, key_columns: tuple[str, ...]
) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    if frame.height == 0:
        return None, None
    keys: list[tuple[str, ...]] = []
    for row in frame.select(list(key_columns)).iter_rows():
        encoded: list[str] = []
        for value in row:
            if type(value) is str:
                encoded.append(value)
            elif type(value) is dt.date and type(value) is not dt.datetime:
                encoded.append(value.isoformat())
            else:
                raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
        keys.append(tuple(encoded))
    keys.sort()
    return keys[0], keys[-1]


def _read_exact_parquet(path: Path, spec: _ArtifactSpec) -> pl.DataFrame:
    try:
        frame = pl.read_parquet(path)
    except Exception:
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID") from None
    if spec.kind == "detail":
        return _require_exact_detail(frame)
    if spec.logical_table == "eligible_keys":
        return _require_exact_eligible_keys(frame)
    assert spec.pandera_schema is not None
    return _require_exact_schema_frame(frame, spec.pandera_schema)


def _require_exact_schema_frame(frame: pl.DataFrame, schema: Any) -> pl.DataFrame:
    try:
        validated = schema.validate(frame)
    except Exception:
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID") from None
    if list(frame.columns) != list(validated.columns):
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    if list(frame.dtypes) != list(validated.dtypes):
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    if not frame.equals(validated):
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    return frame


def _require_exact_eligible_keys(frame: pl.DataFrame) -> pl.DataFrame:
    if list(frame.columns) != ["as_of", "symbol"]:
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    if list(frame.dtypes) != [pl.Date, pl.Utf8]:
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    if frame.is_empty():
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    if frame.height != frame.select(["as_of", "symbol"]).unique().height:
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    ordered = frame.sort(["as_of", "symbol"])
    if not frame.equals(ordered):
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    return frame


def _require_exact_detail(frame: pl.DataFrame) -> pl.DataFrame:
    if list(frame.columns) != list(_DETAIL_COLUMNS):
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    for name, dtype in zip(frame.columns, frame.dtypes, strict=True):
        if dtype != _DETAIL_DTYPES[name]:
            raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    if frame.height != _COMPARISON_COUNT:
        raise M3ReleaseError("G1_RELEASE_ARTIFACT_INVALID")
    return frame


def _sample_keys_from_detail(detail: pl.DataFrame) -> tuple[tuple[str, dt.date], ...]:
    pairs = {
        (row["symbol"], row["trade_date"])
        for row in detail.select(["symbol", "trade_date"]).iter_rows(named=True)
    }
    if len(pairs) != _KEY_COUNT:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    return tuple(sorted(pairs, key=lambda item: (item[0], item[1])))


def _reuse_existing_final(*, final_dir: Path, prepared: G1PreparedRelease) -> G1Release:
    release = G1Release(
        release_id=prepared.release_id,
        root=final_dir,
        manifest_path=final_dir / _MANIFEST_NAME,
        quality_path=final_dir / _QUALITY_NAME,
    )
    try:
        verified = verify_g1_release(release=release)
    except M3ReleaseError:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED") from None
    _assert_prepared_matches_verified(prepared, verified)
    return release


def _assert_prepared_matches_verified(
    prepared: G1PreparedRelease, verified: VerifiedG1Release
) -> None:
    if verified.manifest.release_id != prepared.release_id:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if verified.manifest.primary_candidate_key != prepared.candidate.primary_candidate_key:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if (
        verified.manifest.sample_plan_sha256
        != prepared.reconciliation.sample_plan.sample_plan_sha256
    ):
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if verified.quality_sha256 != hashlib.sha256(
        _canonical_json_bytes(asdict(prepared.quality))
    ).hexdigest():
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if verified.manifest.cross_source_summary_sha256 != prepared.reconciliation.summary_sha256:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if verified.quality != prepared.quality:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")


def _prepare_output_root(output_root: Path) -> Path:
    try:
        if not isinstance(output_root, Path):
            raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
        root = _absolute_path(output_root)
        _ensure_directory_tree(root)
        _reject_ancestor_symlinks(root)
        if not stat.S_ISDIR(os.lstat(root).st_mode):
            raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
        return root
    except M3ReleaseError:
        raise
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _ensure_directory_tree(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while True:
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
            current = parent
            continue
        except OSError:
            raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
        break
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o755)
        except FileExistsError:
            st = os.lstat(directory)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
        except OSError:
            raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _mkdir_exclusive(path: Path, *, mode: int) -> None:
    try:
        os.mkdir(path, mode)
    except FileExistsError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _exclusive_write_bytes(path: Path, payload: bytes) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW | _O_BINARY
    fd = -1
    try:
        fd = os.open(path, flags, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    except FileExistsError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _fsync_directory(directory: Path) -> None:
    # NTFS does not expose a portable directory-fd fsync; file writes already
    # FlushFileBuffers via _exclusive_write_bytes. Skipping dir fsync on Windows
    # is required for the authorized Windows-native publish track.
    if os.name == "nt":
        try:
            if not directory.is_dir():
                raise M3ReleaseError("G1_RELEASE_IO_FAILED")
        except OSError:
            raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None
        return
    fd = -1
    try:
        fd = os.open(directory, os.O_RDONLY)
        os.fsync(fd)
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _windows_movefileex_noreplace(src: Path, dst: Path) -> None:
    """Exclusive directory publish commit on Windows (no REPLACE_EXISTING)."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex_w = kernel32.MoveFileExW
        move_file_ex_w.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
        ]
        move_file_ex_w.restype = ctypes.c_bool
        # flags=0: fail if destination exists; do not copy; do not replace.
        if move_file_ex_w(os.fspath(src), os.fspath(dst), 0):
            return
        err = ctypes.get_last_error()
    except M3ReleaseError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        raise M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED") from None
    # ERROR_ALREADY_EXISTS=183, ERROR_FILE_EXISTS=80
    if err in {80, 183}:
        raise M3ReleaseError("G1_RELEASE_CONCURRENT_PUBLISH")
    raise M3ReleaseError("G1_RELEASE_IO_FAILED")


def _renameat2_noreplace(src: Path, dst: Path) -> None:
    if os.name == "nt":
        _windows_movefileex_noreplace(src, dst)
        return
    try:
        libc_name = ctypes.util.find_library("c")
        if libc_name is None:
            raise M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED")
        libc = ctypes.CDLL(libc_name, use_errno=True)
        if not hasattr(libc, "renameat2"):
            raise M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED")
        renameat2 = libc.renameat2
    except M3ReleaseError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        raise M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED") from None
    if not callable(renameat2):
        raise M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    src_b = os.fsencode(os.fspath(src))
    dst_b = os.fsencode(os.fspath(dst))
    ctypes.set_errno(0)
    result = renameat2(_AT_FDCWD, src_b, _AT_FDCWD, dst_b, _RENAME_NOREPLACE)
    if result == 0:
        return
    err = ctypes.get_errno()
    if err in {errno.EEXIST, errno.ENOTEMPTY}:
        raise M3ReleaseError("G1_RELEASE_CONCURRENT_PUBLISH")
    # WSL1 / older kernels / non-supporting filesystems reject the flag with EINVAL/ENOSYS.
    if err in {errno.EINVAL, errno.ENOSYS, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)}:
        raise M3ReleaseError("G1_RELEASE_PUBLISH_UNSUPPORTED")
    raise M3ReleaseError("G1_RELEASE_IO_FAILED")


def platform_supports_renameat2_noreplace() -> bool:
    """Probe whether exclusive directory publish commit works on this host."""
    import tempfile

    parent = Path(tempfile.mkdtemp(prefix="m3-g1-renameat2-probe-"))
    src = parent / "src"
    dst = parent / "dst"
    try:
        src.mkdir()
        try:
            _renameat2_noreplace(src, dst)
        except M3ReleaseError as exc:
            return exc.code != "G1_RELEASE_PUBLISH_UNSUPPORTED"
        return dst.is_dir() and not src.exists()
    finally:
        for path in (dst, src, parent):
            try:
                if path.is_dir():
                    path.rmdir()
            except OSError:
                pass


def _cleanup_staging(container: Path, identity: tuple[int, int]) -> None:
    try:
        if not _path_exists_nofollow(container):
            return
        current = _dir_identity(container)
        if current != identity:
            raise M3ReleaseError("G1_RELEASE_IO_FAILED")
        for child in list(container.iterdir()):
            st = os.lstat(child)
            if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
                for nested in list(child.iterdir()):
                    if not stat.S_ISREG(os.lstat(nested).st_mode):
                        raise M3ReleaseError("G1_RELEASE_IO_FAILED")
                    os.unlink(nested)
                os.rmdir(child)
            elif stat.S_ISREG(st.st_mode):
                os.unlink(child)
            else:
                raise M3ReleaseError("G1_RELEASE_IO_FAILED")
        if _dir_identity(container) != identity:
            raise M3ReleaseError("G1_RELEASE_IO_FAILED")
        os.rmdir(container)
    except M3ReleaseError:
        raise
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _list_final_entries(root: Path) -> set[str]:
    try:
        names: set[str] = set()
        for path in root.iterdir():
            name = path.name
            if name.startswith(".") or name not in _FINAL_ENTRY_NAMES:
                raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
            mode = os.lstat(path).st_mode
            if (
                stat.S_ISFIFO(mode)
                or stat.S_ISSOCK(mode)
                or stat.S_ISCHR(mode)
                or stat.S_ISBLK(mode)
                or stat.S_ISLNK(mode)
            ):
                raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
            names.add(name)
        return names
    except M3ReleaseError:
        raise
    except OSError:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED") from None


def _read_regular_file_bytes(path: Path) -> bytes:
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise M3ReleaseError("G1_RELEASE_IO_FAILED")
        with open(path, "rb") as handle:
            return handle.read()
    except M3ReleaseError:
        raise
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _dir_identity(path: Path) -> tuple[int, int]:
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
        return (st.st_dev, st.st_ino)
    except M3ReleaseError:
        raise
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _path_exists_nofollow(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise M3ReleaseError("G1_RELEASE_IO_FAILED") from None


def _absolute_path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
    try:
        absolute = path if path.is_absolute() else Path.cwd() / path
        return Path(os.path.abspath(absolute))
    except OSError:
        raise M3ReleaseError("G1_RELEASE_PATH_INVALID") from None


def _reject_ancestor_symlinks(path: Path) -> None:
    current = _absolute_path(path)
    while True:
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            parent = current.parent
            if parent == current:
                return
            current = parent
            continue
        except OSError:
            raise M3ReleaseError("G1_RELEASE_PATH_INVALID") from None
        if stat.S_ISLNK(st.st_mode):
            raise M3ReleaseError("G1_RELEASE_PATH_INVALID")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _snapshot_ancestor_identities(
    path: Path, *, code: str
) -> tuple[tuple[str, tuple[int, int]], ...]:
    """Record ``(abspath, (st_dev, st_ino))`` for every ancestor of ``path``.

    Walks from ``path.parent`` to the filesystem root using textual absolute paths
    and ``lstat`` only (never ``resolve()``). Symlink / non-directory / lstat
    failure maps to ``code``.
    """
    current = _absolute_path(path).parent
    snapshots: list[tuple[str, tuple[int, int]]] = []
    while True:
        abs_text = os.path.abspath(os.fspath(current))
        try:
            st = os.lstat(abs_text)
        except OSError:
            raise M3ReleaseError(code) from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3ReleaseError(code)
        snapshots.append((abs_text, (st.st_dev, st.st_ino)))
        parent = Path(abs_text).parent
        if parent == Path(abs_text):
            break
        current = parent
    return tuple(snapshots)


def _assert_ancestor_identities_unchanged(
    snapshot: tuple[tuple[str, tuple[int, int]], ...], *, code: str
) -> None:
    """Require each snapshotted ancestor path still matches physical identity."""
    for abs_text, expected in snapshot:
        try:
            st = os.lstat(abs_text)
        except OSError:
            raise M3ReleaseError(code) from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3ReleaseError(code)
        if (st.st_dev, st.st_ino) != expected:
            raise M3ReleaseError(code)


def _consume_build_inputs(value: object) -> G1BuildInputs:
    if type(value) is not G1BuildInputs:
        raise M3ReleaseError("G1_RELEASE_INPUT_INVALID")
    return G1BuildInputs(
        build_spec=value.build_spec,
        request_plan=value.request_plan,
        responses=value.responses,
        cninfo_responses=value.cninfo_responses,
        calendars=value.calendars,
        instruments=value.instruments,
        universe=value.universe,
        signal_start=value.signal_start,
        signal_end=value.signal_end,
        history=value.history,
        expected_constituent_count=value.expected_constituent_count,
        factor_ratio_rtol=value.factor_ratio_rtol,
    )


def _consume_policy(value: object) -> G1CrossSourcePolicy:
    if type(value) is not G1CrossSourcePolicy:
        raise M3ReleaseError("G1_RELEASE_INPUT_INVALID")
    return G1CrossSourcePolicy(
        reference_source=value.reference_source,
        sample_symbols=value.sample_symbols,
        dates_per_symbol=value.dates_per_symbol,
        price_atol=value.price_atol,
        price_rtol=value.price_rtol,
        volume_rtol=value.volume_rtol,
        max_mismatch_rate=value.max_mismatch_rate,
    )


def _consume_verified_reference(value: object) -> VerifiedReferenceResponse:
    if type(value) is not VerifiedReferenceResponse:
        raise M3ReleaseError("G1_RELEASE_INPUT_INVALID")
    return VerifiedReferenceResponse(
        value.spec, value.receipt, value.receipt_sha256, value.frame
    )


def _require_hex64(value: object, label: str) -> None:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError(f"{label} 必须是 64 位小写裸 hex")


def _validate_key_tuple(value: object, width: int) -> None:
    if type(value) is not tuple or len(value) != width:
        raise ValueError("artifact key tuple 非法")
    if any(type(item) is not str for item in value):
        raise ValueError("artifact key tuple 元素非法")


def _strict_json_object(payload: bytes) -> dict[str, Any]:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    try:
        text = payload.decode("utf-8", errors="strict")

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            output: dict[str, Any] = {}
            for key, value in items:
                if key in output:
                    raise ValueError("duplicate JSON key")
                output[key] = value
            return output

        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID") from None
    if type(value) is not dict:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    return value


def _exact_field_names(value: Mapping[str, Any], cls: type[Any]) -> None:
    expected = {item.name for item in fields(cls)}
    if set(value) != expected:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")


def _parse_quality_bytes(payload: bytes) -> G1QualityReportV1:
    raw = _strict_json_object(payload)
    _exact_field_names(raw, G1QualityReportV1)
    issues_raw = raw["issues"]
    if type(issues_raw) is not list:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    issues: list[G1QualityIssueV1] = []
    for item in issues_raw:
        if type(item) is not dict:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        _exact_field_names(item, G1QualityIssueV1)
        evidence = item["evidence"]
        if type(evidence) is not list or any(type(v) is not str for v in evidence):
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        issues.append(
            G1QualityIssueV1(
                code=item["code"],
                severity=item["severity"],
                message=item["message"],
                count=_exact_int(item["count"]),
                evidence=tuple(evidence),
            )
        )
    return G1QualityReportV1(
        schema_version=raw["schema_version"],
        release_id=raw["release_id"],
        primary_candidate_key=raw["primary_candidate_key"],
        plan_sha256=raw["plan_sha256"],
        error_count=_exact_int(raw["error_count"]),
        warning_count=_exact_int(raw["warning_count"]),
        passed=_exact_bool(raw["passed"]),
        issues=tuple(issues),
    )


def _parse_manifest_bytes(
    payload: bytes,
) -> G1ManifestV1 | G1ManifestV2 | G1ManifestV3 | G1ManifestV4 | G1ManifestV5:
    raw = _strict_json_object(payload)
    schema = raw.get("schema_version")
    if schema == _MANIFEST_SCHEMA_V1:
        _exact_field_names(raw, G1ManifestV1)
        cls: (
            type[G1ManifestV1]
            | type[G1ManifestV2]
            | type[G1ManifestV3]
            | type[G1ManifestV4]
            | type[G1ManifestV5]
        ) = G1ManifestV1
    elif schema == _MANIFEST_SCHEMA_V2:
        _exact_field_names(raw, G1ManifestV2)
        cls = G1ManifestV2
    elif schema == _MANIFEST_SCHEMA_V3:
        _exact_field_names(raw, G1ManifestV3)
        cls = G1ManifestV3
    elif schema == _MANIFEST_SCHEMA_V4:
        _exact_field_names(raw, G1ManifestV4)
        cls = G1ManifestV4
    elif schema == _MANIFEST_SCHEMA_V5:
        _exact_field_names(raw, G1ManifestV5)
        cls = G1ManifestV5
    else:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    receipts_raw = raw["input_receipts"]
    files_raw = raw["files"]
    if type(receipts_raw) is not list or type(files_raw) is not list:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    receipts: list[G1ReceiptProjectionV1] = []
    for item in receipts_raw:
        if type(item) is not dict:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        _exact_field_names(item, G1ReceiptProjectionV1)
        columns = item["columns"]
        if type(columns) is not list or any(type(v) is not str for v in columns):
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        receipts.append(
            G1ReceiptProjectionV1(
                source=item["source"],
                request_id=item["request_id"],
                endpoint=item["endpoint"],
                parameters_sha256=item["parameters_sha256"],
                stable_response_sha256=item["stable_response_sha256"],
                row_count=_exact_int(item["row_count"]),
                columns=tuple(columns),
            )
        )
    files: list[G1ArtifactEntryV1] = []
    for item in files_raw:
        if type(item) is not dict:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        _exact_field_names(item, G1ArtifactEntryV1)
        key_columns = item["key_columns"]
        if type(key_columns) is not list or any(type(v) is not str for v in key_columns):
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        files.append(
            G1ArtifactEntryV1(
                path=item["path"],
                sha256=item["sha256"],
                content_sha256=item["content_sha256"],
                size_bytes=_exact_int(item["size_bytes"]),
                row_count=_exact_int(item["row_count"]),
                schema_name=item["schema_name"],
                table_schema_version=item["table_schema_version"],
                key_columns=tuple(key_columns),
                min_key=_parse_optional_key(item["min_key"]),
                max_key=_parse_optional_key(item["max_key"]),
            )
        )
    common = dict(
        schema_version=raw["schema_version"],
        release_id=raw["release_id"],
        primary_candidate_key=raw["primary_candidate_key"],
        config_version=raw["config_version"],
        g1_config_sha256=raw["g1_config_sha256"],
        signal_start=_parse_iso_date(raw["signal_start"]),
        signal_end=_parse_iso_date(raw["signal_end"]),
        history_start=_parse_iso_date(raw["history_start"]),
        history_end=_parse_iso_date(raw["history_end"]),
        request_plan_sha256=raw["request_plan_sha256"],
        build_code_version=raw["build_code_version"],
        dependency_fingerprint_sha256=raw["dependency_fingerprint_sha256"],
        mapper_version=raw["mapper_version"],
        clean_schema_version=raw["clean_schema_version"],
        membership_method_version=raw["membership_method_version"],
        price_limit_method_version=raw["price_limit_method_version"],
        corporate_action_selection_version=raw["corporate_action_selection_version"],
        corporate_action_reconciliation_version=raw[
            "corporate_action_reconciliation_version"
        ],
        input_receipts=tuple(receipts),
        price_limit_required_keys_sha256=raw["price_limit_required_keys_sha256"],
        sample_plan_sha256=raw["sample_plan_sha256"],
        cross_source_summary_sha256=raw["cross_source_summary_sha256"],
        quality_sha256=raw["quality_sha256"],
        files=tuple(files),
    )
    if cls is G1ManifestV2:
        return G1ManifestV2(
            **common,
            benchmark_mode=raw["benchmark_mode"],
            benchmark_method_version=raw["benchmark_method_version"],
            benchmark_dividend_reconciliation_version=raw[
                "benchmark_dividend_reconciliation_version"
            ],
        )
    if cls is G1ManifestV3:
        return G1ManifestV3(
            **common,
            benchmark_mode=raw["benchmark_mode"],
            benchmark_method_version=raw["benchmark_method_version"],
            benchmark_dividend_reconciliation_version=raw[
                "benchmark_dividend_reconciliation_version"
            ],
        )
    if cls is G1ManifestV4:
        return G1ManifestV4(
            **common,
            benchmark_mode=raw["benchmark_mode"],
            benchmark_method_version=raw["benchmark_method_version"],
            benchmark_dividend_reconciliation_version=raw[
                "benchmark_dividend_reconciliation_version"
            ],
        )
    if cls is G1ManifestV5:
        return G1ManifestV5(
            **common,
            benchmark_mode=raw["benchmark_mode"],
            benchmark_method_version=raw["benchmark_method_version"],
            benchmark_dividend_reconciliation_version=raw[
                "benchmark_dividend_reconciliation_version"
            ],
        )
    return G1ManifestV1(**common)


def _primary_from_manifest(
    *,
    manifest: G1ManifestV1 | G1ManifestV2 | G1ManifestV3 | G1ManifestV4 | G1ManifestV5,
    tushare_receipts: tuple[G1ReceiptProjectionV1, ...],
    primary_receipts: tuple[G1ReceiptProjectionV1, ...] | None = None,
    table_content_digests: tuple[tuple[str, str], ...],
    price_limit_required_keys_sha256: str,
) -> str:
    if type(manifest) is G1ManifestV1:
        # Historical v1 identity: fixed H00300/index_daily/close-only field set.
        payload = {
            "schema_version": "m3-g1-primary-candidate-identity-v1",
            "build_spec": {
                "config_version": manifest.config_version,
                "g1_config_sha256": manifest.g1_config_sha256,
                "mapper_version": manifest.mapper_version,
                "schema_version": manifest.clean_schema_version,
                "membership_method_version": manifest.membership_method_version,
                "price_limit_method_version": manifest.price_limit_method_version,
                "corporate_action_selection_version": (
                    manifest.corporate_action_selection_version
                ),
                "corporate_action_reconciliation_version": (
                    manifest.corporate_action_reconciliation_version
                ),
                "build_code_version": manifest.build_code_version,
                "dependency_fingerprint_sha256": (
                    manifest.dependency_fingerprint_sha256
                ),
            },
            "request_plan_sha256": manifest.request_plan_sha256,
            "signal_start": manifest.signal_start.isoformat(),
            "signal_end": manifest.signal_end.isoformat(),
            "history_start": manifest.history_start.isoformat(),
            "history_end": manifest.history_end.isoformat(),
            "input_receipts": [asdict(item) for item in tushare_receipts],
            "table_content_digests": [list(item) for item in table_content_digests],
            "price_limit_required_keys_sha256": price_limit_required_keys_sha256,
        }
        return _sha256_json(payload)
    if type(manifest) is not G1ManifestV2 and type(manifest) is not G1ManifestV3 and type(manifest) is not G1ManifestV4 and type(manifest) is not G1ManifestV5:
        raise M3ReleaseError("G1_RELEASE_IDENTITY_MISMATCH")
    receipts_for_key = (
        primary_receipts
        if type(manifest) in {G1ManifestV4, G1ManifestV5} and primary_receipts is not None
        else tushare_receipts
    )
    build_spec = G1BuildSpec(
        config_version=manifest.config_version,
        g1_config_sha256=manifest.g1_config_sha256,
        mapper_version=manifest.mapper_version,
        schema_version=manifest.clean_schema_version,
        membership_method_version=manifest.membership_method_version,
        price_limit_method_version=manifest.price_limit_method_version,
        corporate_action_selection_version=manifest.corporate_action_selection_version,
        corporate_action_reconciliation_version=(
            manifest.corporate_action_reconciliation_version
        ),
        benchmark_mode=manifest.benchmark_mode,
        benchmark_method_version=manifest.benchmark_method_version,
        benchmark_dividend_reconciliation_version=(
            manifest.benchmark_dividend_reconciliation_version
        ),
        build_code_version=manifest.build_code_version,
        dependency_fingerprint_sha256=manifest.dependency_fingerprint_sha256,
    )
    return _primary_candidate_key(
        build_spec=build_spec,
        request_plan_sha256=manifest.request_plan_sha256,
        signal_start=manifest.signal_start,
        signal_end=manifest.signal_end,
        history_start=manifest.history_start,
        history_end=manifest.history_end,
        input_receipts=receipts_for_key,
        table_content_digests=table_content_digests,
        price_limit_required_keys_sha256=price_limit_required_keys_sha256,
    )


def _parse_summary_bytes(payload: bytes) -> CrossSourceSummaryV1:
    raw = _strict_json_object(payload)
    _exact_field_names(raw, CrossSourceSummaryV1)
    field_stats_raw = raw["field_stats"]
    if type(field_stats_raw) is not list:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    field_stats: list[CrossSourceFieldStatsV1] = []
    for item in field_stats_raw:
        if type(item) is not dict:
            raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
        _exact_field_names(item, CrossSourceFieldStatsV1)
        field_stats.append(
            CrossSourceFieldStatsV1(
                field=item["field"],
                comparison_count=_exact_int(item["comparison_count"]),
                mismatch_count=_exact_int(item["mismatch_count"]),
                max_abs_diff=_exact_float(item["max_abs_diff"]),
                max_relative_diff=_exact_float(item["max_relative_diff"]),
            )
        )
    primary_digests = raw["primary_receipt_digests"]
    reference_digests = raw["reference_receipt_digests"]
    if type(primary_digests) is not list or type(reference_digests) is not list:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    if any(type(v) is not str for v in primary_digests + reference_digests):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    return CrossSourceSummaryV1(
        schema_version=raw["schema_version"],
        primary_candidate_key=raw["primary_candidate_key"],
        sample_plan_sha256=raw["sample_plan_sha256"],
        sample_symbol_count=_exact_int(raw["sample_symbol_count"]),
        dates_per_symbol=_exact_int(raw["dates_per_symbol"]),
        key_count=_exact_int(raw["key_count"]),
        field_count=_exact_int(raw["field_count"]),
        comparison_count=_exact_int(raw["comparison_count"]),
        primary_receipt_digests=tuple(primary_digests),
        reference_receipt_digests=tuple(reference_digests),
        price_atol=_exact_float(raw["price_atol"]),
        price_rtol=_exact_float(raw["price_rtol"]),
        volume_rtol=_exact_float(raw["volume_rtol"]),
        max_mismatch_rate=_exact_float(raw["max_mismatch_rate"]),
        missing_primary_rows=_exact_int(raw["missing_primary_rows"]),
        missing_reference_rows=_exact_int(raw["missing_reference_rows"]),
        mismatch_cells=_exact_int(raw["mismatch_cells"]),
        mismatch_rate=_exact_float(raw["mismatch_rate"]),
        field_stats=tuple(field_stats),
        detail_sha256=raw["detail_sha256"],
        passed=_exact_bool(raw["passed"]),
    )


def _parse_optional_key(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if type(value) is not list or any(type(item) is not str for item in value):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    return tuple(value)


def _parse_iso_date(value: object) -> dt.date:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID") from None


def _exact_int(value: object) -> int:
    if type(value) is bool or type(value) is not int:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    return value


def _exact_bool(value: object) -> bool:
    if type(value) is not bool:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    return value


def _exact_float(value: object) -> float:
    if type(value) is bool or type(value) is not float:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    if not math.isfinite(value):
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    return value


def _manifest_to_jsonable(
    manifest: G1ManifestV1 | G1ManifestV2 | G1ManifestV3 | G1ManifestV4 | G1ManifestV5,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": manifest.schema_version,
        "release_id": manifest.release_id,
        "primary_candidate_key": manifest.primary_candidate_key,
        "config_version": manifest.config_version,
        "g1_config_sha256": manifest.g1_config_sha256,
        "signal_start": manifest.signal_start.isoformat(),
        "signal_end": manifest.signal_end.isoformat(),
        "history_start": manifest.history_start.isoformat(),
        "history_end": manifest.history_end.isoformat(),
        "request_plan_sha256": manifest.request_plan_sha256,
        "build_code_version": manifest.build_code_version,
        "dependency_fingerprint_sha256": manifest.dependency_fingerprint_sha256,
        "mapper_version": manifest.mapper_version,
        "clean_schema_version": manifest.clean_schema_version,
        "membership_method_version": manifest.membership_method_version,
        "price_limit_method_version": manifest.price_limit_method_version,
        "corporate_action_selection_version": (
            manifest.corporate_action_selection_version
        ),
        "corporate_action_reconciliation_version": (
            manifest.corporate_action_reconciliation_version
        ),
        "input_receipts": [asdict(item) for item in manifest.input_receipts],
        "price_limit_required_keys_sha256": manifest.price_limit_required_keys_sha256,
        "sample_plan_sha256": manifest.sample_plan_sha256,
        "cross_source_summary_sha256": manifest.cross_source_summary_sha256,
        "quality_sha256": manifest.quality_sha256,
        "files": [_artifact_entry_to_jsonable(item) for item in manifest.files],
    }
    if (
        type(manifest) is G1ManifestV2
        or type(manifest) is G1ManifestV3
        or type(manifest) is G1ManifestV4
        or type(manifest) is G1ManifestV5
    ):
        payload["benchmark_mode"] = manifest.benchmark_mode
        payload["benchmark_method_version"] = manifest.benchmark_method_version
        payload["benchmark_dividend_reconciliation_version"] = (
            manifest.benchmark_dividend_reconciliation_version
        )
    elif type(manifest) is not G1ManifestV1:
        raise M3ReleaseError("G1_RELEASE_JSON_INVALID")
    return payload


def _artifact_entry_to_jsonable(item: G1ArtifactEntryV1) -> dict[str, Any]:
    return {
        "path": item.path,
        "sha256": item.sha256,
        "content_sha256": item.content_sha256,
        "size_bytes": item.size_bytes,
        "row_count": item.row_count,
        "schema_name": item.schema_name,
        "table_schema_version": item.table_schema_version,
        "key_columns": list(item.key_columns),
        "min_key": _key_to_jsonable(item.min_key),
        "max_key": _key_to_jsonable(item.max_key),
    }


def _key_to_jsonable(value: tuple[object, ...] | None) -> list[object] | None:
    if value is None:
        return None
    out: list[object] = []
    for item in value:
        if type(item) is dt.date and type(item) is not dt.datetime:
            out.append(item.isoformat())
        else:
            out.append(item)
    return out


def _canonical_json_bytes(value: Any) -> bytes:
    return _canonical_json(value).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
