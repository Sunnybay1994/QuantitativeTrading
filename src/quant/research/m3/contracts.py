"""M3 编排层的稳定值对象，不依赖 Qlib、LightGBM 或 MLflow。"""

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

import polars as pl
import pandas as pd  # type: ignore[import-untyped]

from quant.research.m3.run_state import ArtifactDigest

_HEX64 = frozenset("0123456789abcdef")

FEATURE_REQUEST_COMMON_KEYS = frozenset({
    "schema_version", "worker_protocol_version", "release_kind",
    "formal_gate_eligible", "experiment_key", "experiment_manifest_sha256",
    "g1_release_id", "g1_release_manifest_sha256", "snapshot_id",
    "snapshot_manifest_sha256", "provider_key", "provider_manifest_sha256",
    "provider_receipt_sha256", "provider_uri_sha256", "fold",
    "planned_fold_sha256", "scientific_config_sha256", "feature_version",
    "qlib_version", "history_start", "segments", "eligible_rows",
})
FEATURE_FORMAL_REQUEST_KEYS = FEATURE_REQUEST_COMMON_KEYS
FEATURE_DEVELOPMENT_REQUEST_KEYS = FEATURE_REQUEST_COMMON_KEYS | {"example_id"}
FEATURE_RESPONSE_EXTRA_KEYS = frozenset({
    "response_schema_version", "input_names", "expressions",
})


def _require_bare_hex64(name: str, value: str) -> None:
    if type(value) is not str:
        raise ValueError(f"{name} 必须为 str 类型的裸 64 位小写 hex")
    if len(value) != 64 or any(char not in _HEX64 for char in value):
        raise ValueError(f"{name} 必须为裸 64 位小写 hex")


@dataclass(frozen=True)
class QlibDumpToolSpec:
    """Validated supply-chain identity injected into the Qlib dump fetcher."""

    url: str
    sha256: str
    size_bytes: int
    qlib_version: Literal["0.9.7"]
    command: Literal["dump_all"]

    def __post_init__(self) -> None:
        if not self.url or self.qlib_version != "0.9.7":
            raise ValueError("Qlib dump tool URL and version must not be empty")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("Qlib dump tool SHA-256 must be 64 lowercase hexadecimal characters")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ValueError("Qlib dump tool byte count must be positive")
        if self.command != "dump_all":
            raise ValueError("Qlib dump tool command must be dump_all")


@dataclass(frozen=True)
class DateSegment:
    """包含首尾交易日的时间段。"""

    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("时间段结束日不得早于开始日")


@dataclass(frozen=True)
class TemporalFold:
    """严格有序且互不重叠的训练、验证、测试折。"""

    name: str
    train: DateSegment
    validation: DateSegment
    test: DateSegment

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("fold 名称不得为空")
        if self.train.end >= self.validation.start:
            raise ValueError("训练段必须早于验证段")
        if self.validation.end >= self.test.start:
            raise ValueError("验证段必须早于测试段")


@dataclass(frozen=True)
class DatasetSnapshot:
    """clean 数据导出后的不可变快照清单摘要。"""

    snapshot_id: str
    manifest_path: Path
    source_fingerprint: str
    row_count: int
    symbol_count: int
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        _require_bare_hex64("snapshot_id", self.snapshot_id)
        _require_bare_hex64("source_fingerprint", self.source_fingerprint)
        if self.row_count <= 0 or self.symbol_count <= 0:
            raise ValueError("快照行数和证券数必须大于 0")
        if self.end < self.start:
            raise ValueError("快照结束日不得早于开始日")


@dataclass(frozen=True)
class SnapshotBuildSpec:
    """All caller-controlled inputs to one deterministic G2A snapshot build."""

    snapshot_request_key: str
    config_version: str
    snapshot_config_sha256: str
    code_version: str
    history_start: dt.date
    history_end: dt.date
    staging_schema_version: str
    adjustment_formula_version: Literal["qlib_yahoo_like_v1"]

    def __post_init__(self) -> None:
        _require_bare_hex64("snapshot_request_key", self.snapshot_request_key)
        _require_bare_hex64("snapshot_config_sha256", self.snapshot_config_sha256)
        for name in ("config_version", "code_version", "staging_schema_version"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} 必须为非空字符串")
        if type(self.history_start) is not dt.date or type(self.history_end) is not dt.date:
            raise ValueError("history_start/history_end 必须为精确 date")
        if self.history_end < self.history_start:
            raise ValueError("history_end 不得早于 history_start")
        if self.adjustment_formula_version != "qlib_yahoo_like_v1":
            raise ValueError("adjustment_formula_version 非法")


@dataclass(frozen=True)
class SnapshotRequestRecordV1:
    schema_version: Literal["m3-snapshot-request-v1"]
    snapshot_request_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_config_sha256: str
    code_version: str
    history_start: dt.date
    history_end: dt.date
    signal_start: dt.date
    signal_end: dt.date

    def __post_init__(self) -> None:
        if self.schema_version != "m3-snapshot-request-v1":
            raise ValueError("snapshot request schema_version 非法")
        for name in (
            "snapshot_request_key", "snapshot_id", "snapshot_manifest_sha256",
            "g1_release_id", "g1_release_manifest_sha256", "snapshot_config_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("code_version 必须为非空字符串")
        _validate_snapshot_dates(self)


@dataclass(frozen=True)
class SnapshotArtifactEntryV1:
    path: str
    sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    symbol: str | None
    min_date: dt.date
    max_date: dt.date

    def __post_init__(self) -> None:
        if type(self.path) is not str or not self.path or "\\" in self.path:
            raise ValueError("snapshot file path 非法")
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != self.path:
            raise ValueError("snapshot file path 必须为规范相对 POSIX path")
        _require_bare_hex64("sha256", self.sha256)
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ValueError("snapshot file size_bytes 必须为正精确 int")
        if type(self.row_count) is not int or self.row_count <= 0:
            raise ValueError("snapshot file row_count 必须为正精确 int")
        if type(self.schema_name) is not str or not self.schema_name:
            raise ValueError("snapshot file schema_name 非法")
        if self.symbol is not None and (type(self.symbol) is not str or not self.symbol):
            raise ValueError("snapshot file symbol 非法")
        if type(self.min_date) is not dt.date or type(self.max_date) is not dt.date:
            raise ValueError("snapshot file 日期必须为精确 date")
        if self.max_date < self.min_date:
            raise ValueError("snapshot file 日期范围非法")


@dataclass(frozen=True)
class SnapshotManifestV1:
    schema_version: Literal["m3-snapshot-manifest-v1"]
    snapshot_id: str
    config_version: str
    snapshot_config_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    source: Literal["tushare"]
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    history_start: dt.date
    history_end: dt.date
    signal_start: dt.date
    signal_end: dt.date
    row_count: int
    symbol_count: int
    min_date: dt.date
    max_date: dt.date
    session_calendar_sha256: str
    session_count: int
    session_start: dt.date
    session_end: dt.date
    staging_format: Literal["parquet"]
    staging_schema_version: str
    adjustment_formula_version: Literal["qlib_yahoo_like_v1"]
    adjustment_spec_sha256: str
    files: tuple[SnapshotArtifactEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-snapshot-manifest-v1":
            raise ValueError("snapshot manifest schema_version 非法")
        for name in (
            "snapshot_id", "snapshot_config_sha256", "g1_release_id",
            "g1_release_manifest_sha256", "session_calendar_sha256",
            "adjustment_spec_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if self.source != "tushare":
            raise ValueError("snapshot source 非法")
        if self.universe != "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1":
            raise ValueError("snapshot universe 非法")
        if self.staging_format != "parquet":
            raise ValueError("snapshot staging_format 非法")
        if self.adjustment_formula_version != "qlib_yahoo_like_v1":
            raise ValueError("snapshot adjustment_formula_version 非法")
        for name in ("config_version", "staging_schema_version"):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"snapshot {name} 非法")
        _validate_snapshot_dates(self)
        for name in ("row_count", "symbol_count", "session_count"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"snapshot {name} 必须为正精确 int")
        for name in ("min_date", "max_date", "session_start", "session_end"):
            if type(getattr(self, name)) is not dt.date:
                raise ValueError(f"snapshot {name} 必须为精确 date")
        if self.max_date < self.min_date or self.session_end < self.session_start:
            raise ValueError("snapshot 日期范围非法")
        if type(self.files) is not tuple or not self.files:
            raise ValueError("snapshot files 不得为空")
        if any(type(item) is not SnapshotArtifactEntryV1 for item in self.files):
            raise ValueError("snapshot files 元素非法")
        paths = tuple(item.path for item in self.files)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise ValueError("snapshot files 必须按唯一 path 排序")


@dataclass(frozen=True)
class SnapshotBuildResult:
    root: Path
    manifest: SnapshotManifestV1
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or type(self.manifest) is not SnapshotManifestV1:
            raise ValueError("snapshot build result 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)


@dataclass(frozen=True)
class VerifiedSnapshotArtifact:
    root: Path
    request: SnapshotRequestRecordV1
    request_sha256: str
    manifest: SnapshotManifestV1
    manifest_sha256: str
    snapshot_receipt_sha256: str
    session_calendar_path: Path
    staging_paths: tuple[Path, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or type(self.request) is not SnapshotRequestRecordV1:
            raise ValueError("verified snapshot request 非法")
        if type(self.manifest) is not SnapshotManifestV1:
            raise ValueError("verified snapshot manifest 非法")
        for name in ("request_sha256", "manifest_sha256", "snapshot_receipt_sha256"):
            _require_bare_hex64(name, getattr(self, name))
        if not isinstance(self.session_calendar_path, Path):
            raise ValueError("verified session calendar path 非法")
        if type(self.staging_paths) is not tuple or not self.staging_paths:
            raise ValueError("verified staging_paths 非法")
        if any(not isinstance(path, Path) for path in self.staging_paths):
            raise ValueError("verified staging_paths 元素非法")


@dataclass(frozen=True)
class ProviderRuntimeFingerprint:
    python_version: str
    packages: tuple[tuple[str, str], ...]
    sha256: str

    def __post_init__(self) -> None:
        if type(self.python_version) is not str or not self.python_version:
            raise ValueError("provider python_version 非法")
        if type(self.packages) is not tuple or not self.packages:
            raise ValueError("provider packages 非法")
        if any(
            type(item) is not tuple
            or len(item) != 2
            or any(type(value) is not str or not value for value in item)
            for item in self.packages
        ):
            raise ValueError("provider package entry 非法")
        if self.packages != tuple(sorted(self.packages)):
            raise ValueError("provider packages 必须按 name 排序")
        expected_names = (
            "fire", "loguru", "numpy", "pandas", "pyarrow", "pyqlib", "python", "tqdm",
        )
        if tuple(name for name, _ in self.packages) != expected_names:
            raise ValueError("provider packages 闭包非法")
        if dict(self.packages)["python"] != self.python_version:
            raise ValueError("provider python version 闭包非法")
        _require_bare_hex64("runtime sha256", self.sha256)
        payload = json.dumps(
            {"packages": self.packages, "python_version": self.python_version},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != self.sha256:
            raise ValueError("provider runtime sha256 闭包非法")


@dataclass(frozen=True)
class ProviderBuildSpec:
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_config_sha256: str
    dump_tool: QlibDumpToolSpec
    qlib_version: Literal["0.9.7"]
    code_version: str
    runtime_fingerprint: ProviderRuntimeFingerprint
    fields: tuple[str, ...]
    frequency: Literal["day"]
    dump_contract_version: Literal["m3-qlib-dump-all-v1"]

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id", "snapshot_manifest_sha256", "provider_key",
            "provider_config_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if type(self.dump_tool) is not QlibDumpToolSpec:
            raise ValueError("provider dump_tool 非法")
        if self.qlib_version != "0.9.7" or self.dump_tool.qlib_version != self.qlib_version:
            raise ValueError("provider qlib_version 非法")
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("provider code_version 非法")
        if type(self.runtime_fingerprint) is not ProviderRuntimeFingerprint:
            raise ValueError("provider runtime fingerprint 非法")
        expected_fields = ("open", "high", "low", "close", "vwap", "volume", "factor")
        if self.fields != expected_fields:
            raise ValueError("provider fields 非法")
        if self.frequency != "day" or self.dump_contract_version != "m3-qlib-dump-all-v1":
            raise ValueError("provider dump contract 非法")


@dataclass(frozen=True)
class ProviderManifestV1:
    schema_version: Literal["m3-provider-manifest-v1"]
    provider_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_config_sha256: str
    qlib_version: str
    dump_tool_sha256: str
    dump_tool_bytes: int
    dump_contract_version: str
    provider_runtime_fingerprint_sha256: str
    code_version: str
    frequency: Literal["day"]
    fields: tuple[str, ...]
    storage_dtype: Literal["<f4"]
    calendar_sha256: str
    calendar_count: int
    calendar_start: dt.date
    calendar_end: dt.date
    instrument_count: int
    instrument_ranges_sha256: str
    output_tree_sha256: str
    logical_argv: tuple[str, ...]
    files: tuple[ArtifactDigest, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-provider-manifest-v1":
            raise ValueError("provider manifest schema 非法")
        for name in (
            "provider_key", "snapshot_id", "snapshot_manifest_sha256",
            "provider_config_sha256", "dump_tool_sha256",
            "provider_runtime_fingerprint_sha256", "calendar_sha256",
            "instrument_ranges_sha256", "output_tree_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if self.qlib_version != "0.9.7" or self.dump_contract_version != "m3-qlib-dump-all-v1":
            raise ValueError("provider manifest version 非法")
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("provider manifest code_version 非法")
        if self.frequency != "day" or self.storage_dtype != "<f4":
            raise ValueError("provider manifest storage 非法")
        expected_fields = ("open", "high", "low", "close", "vwap", "volume", "factor")
        if self.fields != expected_fields:
            raise ValueError("provider manifest fields 非法")
        if type(self.dump_tool_bytes) is not int or self.dump_tool_bytes <= 0:
            raise ValueError("provider dump_tool_bytes 非法")
        for name in ("calendar_count", "instrument_count"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"provider {name} 非法")
        if type(self.calendar_start) is not dt.date or type(self.calendar_end) is not dt.date:
            raise ValueError("provider calendar dates 非法")
        if self.calendar_end < self.calendar_start:
            raise ValueError("provider calendar range 非法")
        expected_argv = (
            "<PYTHON>", "<DUMP_TOOL>", "dump_all", "--data_path",
            "<SNAPSHOT_STAGING>", "--qlib_dir", "<PROVIDER_TEMP>/provider",
            "--freq", "day", "--file_suffix", ".parquet", "--date_field_name",
            "date", "--symbol_field_name", "symbol", "--include_fields",
            "open,high,low,close,vwap,volume,factor", "--max_workers", "1",
        )
        if self.logical_argv != expected_argv:
            raise ValueError("provider logical argv 非法")
        if type(self.files) is not tuple or not self.files:
            raise ValueError("provider files 非法")
        if any(type(item) is not ArtifactDigest for item in self.files):
            raise ValueError("provider file digest 非法")
        if any(
            item.root_alias != "provider"
            or not item.relative_path.startswith("provider/")
            for item in self.files
        ):
            raise ValueError("provider file digest trust domain 非法")
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("provider files 必须唯一排序")


@dataclass(frozen=True)
class ProviderBuildResult:
    root: Path
    qlib_dir: Path
    manifest: ProviderManifestV1
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not isinstance(self.qlib_dir, Path):
            raise ValueError("provider build paths 非法")
        if self.qlib_dir != self.root / "provider":
            raise ValueError("provider build path closure 非法")
        if type(self.manifest) is not ProviderManifestV1:
            raise ValueError("provider build manifest 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)


@dataclass(frozen=True)
class VerifiedProviderArtifact:
    root: Path
    qlib_dir: Path
    manifest: ProviderManifestV1
    manifest_sha256: str
    provider_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not isinstance(self.qlib_dir, Path):
            raise ValueError("verified provider paths 非法")
        if self.qlib_dir != self.root / "provider":
            raise ValueError("verified provider path closure 非法")
        if type(self.manifest) is not ProviderManifestV1:
            raise ValueError("verified provider manifest 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("provider_receipt_sha256", self.provider_receipt_sha256)


@dataclass(frozen=True)
class ProviderValidationSpec:
    provider_validation_key: str
    provider_validation_config_sha256: str
    code_version: str
    qlib_version: Literal["0.9.7"]
    sampling_policy_version: Literal[
        "provider_market_stratified_hash_first_last_v1"
    ]
    worker_protocol_version: Literal["m3-qlib-worker-v1"]

    def __post_init__(self) -> None:
        _require_bare_hex64("provider_validation_key", self.provider_validation_key)
        _require_bare_hex64(
            "provider_validation_config_sha256",
            self.provider_validation_config_sha256,
        )
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("provider validation code_version 非法")
        if self.qlib_version != "0.9.7":
            raise ValueError("provider validation qlib_version 非法")
        if (
            self.sampling_policy_version
            != "provider_market_stratified_hash_first_last_v1"
            or self.worker_protocol_version != "m3-qlib-worker-v1"
        ):
            raise ValueError("provider validation protocol 非法")


@dataclass(frozen=True)
class ProviderProbePlan:
    schema_version: Literal["m3-provider-probe-v1"]
    provider_validation_key: str
    provider_key: str
    snapshot_id: str
    sampling_policy_version: Literal[
        "provider_market_stratified_hash_first_last_v1"
    ]
    candidate_keys_sha256: str
    selected_rows: tuple[tuple[str, dt.date], ...]
    selected_gap_rows: tuple[tuple[str, dt.date], ...]
    emitted_keys_sha256: str
    gap_keys_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-provider-probe-v1":
            raise ValueError("provider probe schema 非法")
        for name in (
            "provider_validation_key", "provider_key", "snapshot_id",
            "candidate_keys_sha256", "emitted_keys_sha256", "gap_keys_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            self.sampling_policy_version
            != "provider_market_stratified_hash_first_last_v1"
        ):
            raise ValueError("provider probe sampling policy 非法")
        for rows, expected in ((self.selected_rows, 60), (self.selected_gap_rows, None)):
            if type(rows) is not tuple or rows != tuple(sorted(rows)):
                raise ValueError("provider probe rows 必须唯一排序")
            if len(rows) != len(set(rows)) or (expected is not None and len(rows) != expected):
                raise ValueError("provider probe rows 数量非法")
            if any(
                type(item) is not tuple or len(item) != 2
                or type(item[0]) is not str or type(item[1]) is not dt.date
                for item in rows
            ):
                raise ValueError("provider probe row 非法")
        if len(self.selected_gap_rows) > 15:
            raise ValueError("provider probe gap rows 数量非法")


@dataclass(frozen=True)
class ProviderValidationSummaryV1:
    schema_version: Literal["m3-provider-validation-v1"]
    provider_validation_key: str
    provider_key: str
    provider_receipt_sha256: str
    provider_manifest_sha256: str
    snapshot_id: str
    provider_validation_config_sha256: str
    provider_runtime_fingerprint_sha256: str
    qlib_version: str
    sampling_policy_version: str
    worker_protocol_version: str
    probe_plan_sha256: str
    candidate_keys_sha256: str
    emitted_keys_sha256: str
    gap_keys_sha256: str
    emitted_key_count: int
    gap_key_count: int
    emitted_comparison_count: int
    gap_comparison_count: int
    details_sha256: str
    details_row_count: int
    api_calendar_sha256: str
    api_instrument_ranges_sha256: str
    missing_emitted_cell_count: int
    extra_cell_count: int
    duplicate_cell_count: int
    non_finite_emitted_cell_count: int
    emitted_mismatch_cell_count: int
    gap_finite_cell_count: int
    calendar_mismatch_count: int
    instrument_mismatch_count: int
    provider_uri_sha256: str
    parent_import_audit_sha256: str
    read_audit_sha256: str
    passed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "m3-provider-validation-v1":
            raise ValueError("provider validation summary schema 非法")
        digest_fields = (
            "provider_validation_key", "provider_key", "provider_receipt_sha256",
            "provider_manifest_sha256", "snapshot_id",
            "provider_validation_config_sha256",
            "provider_runtime_fingerprint_sha256", "probe_plan_sha256",
            "candidate_keys_sha256", "emitted_keys_sha256", "gap_keys_sha256",
            "details_sha256", "api_calendar_sha256",
            "api_instrument_ranges_sha256", "provider_uri_sha256",
            "parent_import_audit_sha256", "read_audit_sha256",
        )
        for name in digest_fields:
            _require_bare_hex64(name, getattr(self, name))
        if self.qlib_version != "0.9.7" or (
            self.sampling_policy_version
            != "provider_market_stratified_hash_first_last_v1"
        ) or self.worker_protocol_version != "m3-qlib-worker-v1":
            raise ValueError("provider validation summary protocol 非法")
        count_fields = (
            "emitted_key_count", "gap_key_count", "emitted_comparison_count",
            "gap_comparison_count", "details_row_count",
            "missing_emitted_cell_count", "extra_cell_count",
            "duplicate_cell_count", "non_finite_emitted_cell_count",
            "emitted_mismatch_cell_count", "gap_finite_cell_count",
            "calendar_mismatch_count", "instrument_mismatch_count",
        )
        if any(type(getattr(self, name)) is not int or getattr(self, name) < 0 for name in count_fields):
            raise ValueError("provider validation summary count 非法")
        if type(self.passed) is not bool:
            raise ValueError("provider validation summary passed 非法")


@dataclass(frozen=True)
class ProviderValidationResult:
    details: pl.DataFrame
    summary: ProviderValidationSummaryV1

    def __post_init__(self) -> None:
        if not isinstance(self.details, pl.DataFrame):
            raise ValueError("provider validation details 非法")
        if type(self.summary) is not ProviderValidationSummaryV1:
            raise ValueError("provider validation summary 非法")


@dataclass(frozen=True)
class VerifiedProviderValidationArtifact:
    root: Path
    details: pl.DataFrame
    summary: ProviderValidationSummaryV1
    summary_sha256: str
    validation_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not isinstance(self.details, pl.DataFrame):
            raise ValueError("verified provider validation artifact 非法")
        if type(self.summary) is not ProviderValidationSummaryV1:
            raise ValueError("verified provider validation summary 非法")
        _require_bare_hex64("summary_sha256", self.summary_sha256)
        _require_bare_hex64("validation_receipt_sha256", self.validation_receipt_sha256)


@dataclass(frozen=True)
class ExperimentIdentitySpec:
    scientific_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str

    def __post_init__(self) -> None:
        _require_bare_hex64("scientific_config_sha256", self.scientific_config_sha256)
        _require_bare_hex64(
            "dependency_fingerprint_sha256", self.dependency_fingerprint_sha256
        )
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("experiment code_version 非法")


@dataclass(frozen=True)
class ExperimentIdentityManifestV1:
    schema_version: Literal["m3-experiment-identity-v1"]
    experiment_key: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    scientific_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-experiment-identity-v1":
            raise ValueError("experiment manifest schema 非法")
        for name in (
            "experiment_key", "snapshot_id", "snapshot_manifest_sha256",
            "provider_key", "provider_manifest_sha256", "provider_receipt_sha256",
            "scientific_config_sha256", "dependency_fingerprint_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("experiment manifest code_version 非法")


@dataclass(frozen=True)
class VerifiedExperimentIdentity:
    root: Path
    manifest: ExperimentIdentityManifestV1
    manifest_sha256: str
    experiment_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ValueError("verified experiment root 非法")
        if type(self.manifest) is not ExperimentIdentityManifestV1:
            raise ValueError("verified experiment manifest 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64(
            "experiment_receipt_sha256", self.experiment_receipt_sha256
        )


@dataclass(frozen=True)
class PlannedFold:
    name: str
    train_dates: tuple[dt.date, ...]
    train_validation_embargo_dates: tuple[dt.date, ...]
    validation_dates: tuple[dt.date, ...]
    validation_test_embargo_dates: tuple[dt.date, ...]
    test_dates: tuple[dt.date, ...]
    train_label_available_by: dt.date
    validation_label_available_by: dt.date
    planned_fold_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.name) is not str
            or len(self.name) != 8
            or not self.name.startswith("fold_")
            or not self.name[5:].isdigit()
        ):
            raise ValueError("planned fold name 非法")
        segments = (
            self.train_dates,
            self.train_validation_embargo_dates,
            self.validation_dates,
            self.validation_test_embargo_dates,
            self.test_dates,
        )
        if any(
            type(segment) is not tuple
            or not segment
            or any(type(day) is not dt.date for day in segment)
            or tuple(sorted(set(segment))) != segment
            for segment in segments
        ):
            raise ValueError("planned fold dates 非法")
        if any(
            left[-1] >= right[0]
            for left, right in zip(segments, segments[1:])
        ):
            raise ValueError("planned fold segment order 非法")
        if (
            type(self.train_label_available_by) is not dt.date
            or type(self.validation_label_available_by) is not dt.date
            or self.train_label_available_by
            != self.train_validation_embargo_dates[-1]
            or self.validation_label_available_by
            != self.validation_test_embargo_dates[-1]
        ):
            raise ValueError("planned fold label cutoff 非法")
        _require_bare_hex64("planned_fold_sha256", self.planned_fold_sha256)


@dataclass(frozen=True)
class FoldPlanBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    train_sessions: int
    validation_sessions: int
    test_sessions: int
    step_sessions: int
    embargo_sessions: int
    max_horizon_sessions: int

    def __post_init__(self) -> None:
        for name in (
            "experiment_key", "experiment_manifest_sha256", "snapshot_id",
            "snapshot_manifest_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.signal_start) is not dt.date
            or type(self.signal_end) is not dt.date
            or self.signal_end < self.signal_start
        ):
            raise ValueError("fold plan signal range 非法")
        counts = (
            self.train_sessions, self.validation_sessions, self.test_sessions,
            self.step_sessions, self.embargo_sessions, self.max_horizon_sessions,
        )
        if any(type(value) is not int or value <= 0 for value in counts):
            raise ValueError("fold plan session count 非法")
        if (
            self.embargo_sessions < self.max_horizon_sessions
            or self.step_sessions < self.test_sessions
        ):
            raise ValueError("fold plan embargo/step 非法")


@dataclass(frozen=True)
class FoldPlanUpstreamPaths:
    """Explicit upstream receipt locations; never infer a shared base from aliases."""

    snapshot_request_path: Path
    snapshot_receipt_path: Path
    provider_dump_tool_path: Path
    provider_receipt_path: Path
    experiment_receipt_path: Path

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, Path)
            for value in (
                self.snapshot_request_path,
                self.snapshot_receipt_path,
                self.provider_dump_tool_path,
                self.provider_receipt_path,
                self.experiment_receipt_path,
            )
        ):
            raise ValueError("fold plan upstream path 非法")


@dataclass(frozen=True)
class FoldPlanManifestV1:
    schema_version: Literal["m3-fold-plan-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    session_calendar_sha256: str
    signal_dates_sha256: str
    scientific_config_sha256: str
    signal_start: dt.date
    signal_end: dt.date
    max_horizon_sessions: int
    folds: tuple[PlannedFold, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-fold-plan-v1":
            raise ValueError("fold plan schema 非法")
        for name in (
            "experiment_key", "experiment_manifest_sha256", "snapshot_id",
            "snapshot_manifest_sha256", "session_calendar_sha256",
            "signal_dates_sha256", "scientific_config_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.signal_start) is not dt.date
            or type(self.signal_end) is not dt.date
            or self.signal_end < self.signal_start
            or type(self.max_horizon_sessions) is not int
            or self.max_horizon_sessions <= 0
            or type(self.folds) is not tuple
            or not self.folds
            or any(type(fold) is not PlannedFold for fold in self.folds)
            or tuple(fold.name for fold in self.folds)
            != tuple(f"fold_{index:03d}" for index in range(1, len(self.folds) + 1))
        ):
            raise ValueError("fold plan manifest 非法")
        test_dates = tuple(day for fold in self.folds for day in fold.test_dates)
        if len(test_dates) != len(set(test_dates)):
            raise ValueError("fold plan test dates overlap")


@dataclass(frozen=True)
class VerifiedFoldPlanArtifact:
    root: Path
    manifest: FoldPlanManifestV1
    manifest_sha256: str
    folds_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or type(self.manifest) is not FoldPlanManifestV1:
            raise ValueError("verified fold plan artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("folds_receipt_sha256", self.folds_receipt_sha256)


@dataclass(frozen=True)
class FeatureBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    fold: str
    planned_fold_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    feature_version: str
    expected_qlib_version: Literal["0.9.7"]
    worker_protocol_version: Literal["m3-qlib-worker-v1"]

    def __post_init__(self) -> None:
        for name in (
            "experiment_key", "experiment_manifest_sha256", "planned_fold_sha256",
            "provider_key", "provider_manifest_sha256", "provider_receipt_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or len(self.fold) != 8
            or not self.fold.startswith("fold_")
            or not self.fold[5:].isdigit()
            or type(self.feature_version) is not str
            or not self.feature_version.strip()
            or self.expected_qlib_version != "0.9.7"
            or self.worker_protocol_version != "m3-qlib-worker-v1"
        ):
            raise ValueError("feature build spec 非法")


@dataclass(frozen=True)
class FeatureUpstreamPaths:
    """Explicit feature inputs; physical paths are never inferred from aliases."""

    fold_receipt_path: Path
    fold_upstream_paths: FoldPlanUpstreamPaths

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fold_receipt_path, Path)
            or type(self.fold_upstream_paths) is not FoldPlanUpstreamPaths
        ):
            raise ValueError("feature upstream path 非法")


@dataclass(frozen=True)
class FeatureSchemaManifestV1:
    feature_version: str
    qlib_version: str
    input_names: tuple[str, ...]
    expressions: tuple[str, ...]
    input_schema_sha256: str
    selected_names: tuple[str, ...]
    selected_dtypes: tuple[str, ...]
    dropped_all_nan_train: tuple[str, ...]
    selected_schema_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.feature_version) is not str
            or not self.feature_version.strip()
            or self.qlib_version != "0.9.7"
            or type(self.input_names) is not tuple
            or len(self.input_names) != 158
            or len(set(self.input_names)) != 158
            or type(self.expressions) is not tuple
            or len(self.expressions) != 158
            or len(set(self.expressions)) != 158
            or any(type(value) is not str or not value for value in (*self.input_names, *self.expressions))
            or type(self.selected_names) is not tuple
            or not self.selected_names
            or len(set(self.selected_names)) != len(self.selected_names)
            or any(name not in self.input_names for name in self.selected_names)
            or self.selected_dtypes != ("Float64",) * len(self.selected_names)
            or type(self.dropped_all_nan_train) is not tuple
            or tuple(name for name in self.input_names if name not in self.selected_names)
            != self.dropped_all_nan_train
        ):
            raise ValueError("feature schema manifest 非法")
        _require_bare_hex64("input_schema_sha256", self.input_schema_sha256)
        _require_bare_hex64("selected_schema_sha256", self.selected_schema_sha256)


@dataclass(frozen=True)
class FeatureSegmentManifestV1:
    name: Literal["train", "validation", "test"]
    path: str
    bytes_sha256: str
    content_sha256: str
    eligible_keys_sha256: str
    feature_row_keys_sha256: str
    feature_matrix_sha256: str
    scorable_keys_sha256: str
    n_eligible: int
    n_feature_rows: int
    n_scorable: int

    def __post_init__(self) -> None:
        if (
            self.name not in {"train", "validation", "test"}
            or self.path != f"{self.name}.parquet"
            or type(self.n_eligible) is not int
            or type(self.n_feature_rows) is not int
            or type(self.n_scorable) is not int
            or not (0 <= self.n_scorable <= self.n_feature_rows <= self.n_eligible)
        ):
            raise ValueError("feature segment manifest 非法")
        for name in (
            "bytes_sha256", "content_sha256", "eligible_keys_sha256",
            "feature_row_keys_sha256", "feature_matrix_sha256",
            "scorable_keys_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))


@dataclass(frozen=True)
class FeatureManifestV1:
    schema_version: Literal["m3-feature-artifact-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    provider_key: str
    provider_manifest_sha256: str
    provider_receipt_sha256: str
    fold: str
    planned_fold_sha256: str
    scientific_config_sha256: str
    eligible_keys_sha256: str
    worker_protocol_version: str
    schema: FeatureSchemaManifestV1
    segments: tuple[FeatureSegmentManifestV1, ...]
    coverage_path: str
    coverage_sha256: str
    coverage_row_count: int

    def __post_init__(self) -> None:
        if self.schema_version != "m3-feature-artifact-v1":
            raise ValueError("feature manifest schema 非法")
        for name in (
            "experiment_key", "experiment_manifest_sha256", "g1_release_id",
            "g1_release_manifest_sha256", "snapshot_id", "snapshot_manifest_sha256",
            "provider_key", "provider_manifest_sha256", "provider_receipt_sha256",
            "planned_fold_sha256", "scientific_config_sha256", "eligible_keys_sha256",
            "coverage_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or len(self.fold) != 8
            or not self.fold.startswith("fold_")
            or self.worker_protocol_version != "m3-qlib-worker-v1"
            or type(self.schema) is not FeatureSchemaManifestV1
            or type(self.segments) is not tuple
            or tuple(segment.name for segment in self.segments)
            != ("train", "validation", "test")
            or any(type(segment) is not FeatureSegmentManifestV1 for segment in self.segments)
            or self.coverage_path != "coverage.parquet"
            or type(self.coverage_row_count) is not int
            or self.coverage_row_count <= 0
        ):
            raise ValueError("feature manifest 非法")


@dataclass(frozen=True)
class VerifiedFeatureArtifact:
    root: Path
    manifest: FeatureManifestV1
    manifest_sha256: str
    feature_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or type(self.manifest) is not FeatureManifestV1:
            raise ValueError("verified feature artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("feature_receipt_sha256", self.feature_receipt_sha256)


@dataclass(frozen=True)
class AlignmentBuildSpec:
    experiment_key: str
    work_key: str
    fold: str
    planned_fold_sha256: str
    horizon_sessions: Literal[5, 10]
    feature_manifest_sha256: str
    label_manifest_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "experiment_key", "work_key", "planned_fold_sha256",
            "feature_manifest_sha256", "label_manifest_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or len(self.fold) != 8
            or not self.fold.startswith("fold_")
            or not self.fold[5:].isdigit()
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
        ):
            raise ValueError("alignment build spec 非法")


@dataclass(frozen=True)
class AlignmentUpstreamPaths:
    feature_receipt_path: Path
    feature_upstream_paths: FeatureUpstreamPaths
    label_receipt_path: Path

    def __post_init__(self) -> None:
        if (
            not isinstance(self.feature_receipt_path, Path)
            or type(self.feature_upstream_paths) is not FeatureUpstreamPaths
            or not isinstance(self.label_receipt_path, Path)
        ):
            raise ValueError("alignment upstream paths 非法")


@dataclass(frozen=True)
class InferenceUpstreamPaths:
    feature_receipt_path: Path
    feature_upstream_paths: FeatureUpstreamPaths

    def __post_init__(self) -> None:
        if (
            not isinstance(self.feature_receipt_path, Path)
            or type(self.feature_upstream_paths) is not FeatureUpstreamPaths
        ):
            raise ValueError("inference upstream paths 非法")


@dataclass(frozen=True)
class AlignmentSegmentManifestV1:
    name: Literal["train", "validation"]
    path: str
    bytes_sha256: str
    row_keys_sha256: str
    matrix_sha256: str
    labels_sha256: str
    n_feature_scorable: int
    n_label_identity: int
    n_label_joined: int
    n_cutoff_dropped: int
    n_final: int

    def __post_init__(self) -> None:
        if self.name not in {"train", "validation"} or self.path != f"{self.name}.parquet":
            raise ValueError("alignment segment identity 非法")
        for name in ("bytes_sha256", "row_keys_sha256", "matrix_sha256", "labels_sha256"):
            _require_bare_hex64(name, getattr(self, name))
        counts = (
            self.n_feature_scorable, self.n_label_identity, self.n_label_joined,
            self.n_cutoff_dropped, self.n_final,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("alignment segment count 非法")
        if (
            self.n_label_joined > self.n_feature_scorable
            or self.n_label_joined > self.n_label_identity
            or self.n_cutoff_dropped > self.n_label_joined
            or self.n_final != self.n_label_joined - self.n_cutoff_dropped
        ):
            raise ValueError("alignment segment conservation 非法")


@dataclass(frozen=True)
class AlignmentManifestV1:
    schema_version: Literal["m3-alignment-artifact-v1"]
    experiment_key: str
    work_key: str
    fold: str
    planned_fold_sha256: str
    horizon_sessions: int
    feature_manifest_sha256: str
    label_manifest_sha256: str
    selected_feature_schema_sha256: str
    segments: tuple[AlignmentSegmentManifestV1, ...]
    diagnostics_path: str
    diagnostics_sha256: str
    diagnostics_row_count: int

    def __post_init__(self) -> None:
        if self.schema_version != "m3-alignment-artifact-v1":
            raise ValueError("alignment manifest schema 非法")
        for name in (
            "experiment_key", "work_key", "planned_fold_sha256",
            "feature_manifest_sha256", "label_manifest_sha256",
            "selected_feature_schema_sha256", "diagnostics_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or self.horizon_sessions not in {5, 10}
            or type(self.segments) is not tuple
            or tuple(item.name for item in self.segments) != ("train", "validation")
            or any(type(item) is not AlignmentSegmentManifestV1 for item in self.segments)
            or self.diagnostics_path != "diagnostics.parquet"
            or type(self.diagnostics_row_count) is not int
            or self.diagnostics_row_count < 0
        ):
            raise ValueError("alignment manifest 非法")


@dataclass(frozen=True)
class VerifiedAlignmentArtifact:
    root: Path
    manifest: AlignmentManifestV1
    manifest_sha256: str
    alignment_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or type(self.manifest) is not AlignmentManifestV1:
            raise ValueError("verified alignment artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("alignment_receipt_sha256", self.alignment_receipt_sha256)


@dataclass(frozen=True)
class SupervisedSegment:
    name: Literal["train", "validation"]
    features: pd.DataFrame
    labels: pd.Series
    metadata: pl.DataFrame

    def __post_init__(self) -> None:
        if (
            self.name not in {"train", "validation"}
            or not isinstance(self.features, pd.DataFrame)
            or not isinstance(self.labels, pd.Series)
            or not isinstance(self.metadata, pl.DataFrame)
            or len(self.features) != len(self.labels)
            or len(self.features) != self.metadata.height
        ):
            raise ValueError("supervised segment 非法")


@dataclass(frozen=True)
class InferenceSegment:
    name: Literal["test"]
    features: pd.DataFrame
    metadata: pl.DataFrame

    def __post_init__(self) -> None:
        if (
            self.name != "test"
            or not isinstance(self.features, pd.DataFrame)
            or not isinstance(self.metadata, pl.DataFrame)
            or len(self.features) != self.metadata.height
        ):
            raise ValueError("inference segment 非法")


@dataclass(frozen=True)
class LightgbmTrainingSpec:
    model_version: str
    booster_params: tuple[tuple[str, str | int | float | bool], ...]
    num_boost_round: int
    early_stopping_rounds: int
    early_stopping_min_delta: float

    def __post_init__(self) -> None:
        if type(self.model_version) is not str or not self.model_version.strip():
            raise ValueError("lightgbm model version 非法")
        if type(self.booster_params) is not tuple or not self.booster_params:
            raise ValueError("lightgbm booster params 非法")
        keys: list[str] = []
        for item in self.booster_params:
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("lightgbm booster param 非法")
            key, value = item
            if type(key) is not str or not key or type(value) not in {str, int, float, bool}:
                raise ValueError("lightgbm booster param 非法")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("lightgbm booster param non-finite")
            keys.append(key)
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("lightgbm booster params 必须唯一排序")
        if (
            type(self.num_boost_round) is not int
            or self.num_boost_round < 1
            or type(self.early_stopping_rounds) is not int
            or not 1 <= self.early_stopping_rounds < self.num_boost_round
            or type(self.early_stopping_min_delta) is not float
            or not math.isfinite(self.early_stopping_min_delta)
            or self.early_stopping_min_delta < 0.0
        ):
            raise ValueError("lightgbm training controls 非法")


@dataclass(frozen=True)
class ModelUpstreamPaths:
    alignment_receipt_path: Path
    alignment_upstream_paths: AlignmentUpstreamPaths

    def __post_init__(self) -> None:
        if (
            not isinstance(self.alignment_receipt_path, Path)
            or type(self.alignment_upstream_paths) is not AlignmentUpstreamPaths
        ):
            raise ValueError("model upstream paths 非法")


@dataclass(frozen=True)
class ModelManifestV1:
    schema_version: Literal["m3-lightgbm-model-v1"]
    experiment_key: str
    work_key: str
    snapshot_id: str
    provider_receipt_sha256: str
    fold: str
    horizon_sessions: int
    model: Literal["lightgbm"]
    model_version: str
    alignment_manifest_sha256: str
    feature_manifest_sha256: str
    label_manifest_sha256: str
    input_feature_schema_sha256: str
    selected_feature_names: tuple[str, ...]
    selected_feature_schema_sha256: str
    params_sha256: str
    train_row_keys_sha256: str
    validation_row_keys_sha256: str
    train_matrix_sha256: str
    validation_matrix_sha256: str
    train_labels_sha256: str
    validation_labels_sha256: str
    lightgbm_version: str
    best_iteration: int
    best_validation_l2: float
    model_sha256: str
    validation_curve_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-lightgbm-model-v1" or self.model != "lightgbm":
            raise ValueError("model manifest schema/model 非法")
        for name in (
            "experiment_key", "work_key", "snapshot_id", "provider_receipt_sha256",
            "alignment_manifest_sha256", "feature_manifest_sha256",
            "label_manifest_sha256", "input_feature_schema_sha256",
            "selected_feature_schema_sha256", "params_sha256",
            "train_row_keys_sha256", "validation_row_keys_sha256",
            "train_matrix_sha256", "validation_matrix_sha256",
            "train_labels_sha256", "validation_labels_sha256", "model_sha256",
            "validation_curve_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or self.horizon_sessions not in {5, 10}
            or type(self.model_version) is not str
            or not self.model_version
            or type(self.selected_feature_names) is not tuple
            or not self.selected_feature_names
            or len(set(self.selected_feature_names)) != len(self.selected_feature_names)
            or type(self.lightgbm_version) is not str
            or not self.lightgbm_version
            or type(self.best_iteration) is not int
            or self.best_iteration < 1
            or type(self.best_validation_l2) is not float
            or not math.isfinite(self.best_validation_l2)
        ):
            raise ValueError("model manifest 非法")


@dataclass(frozen=True)
class VerifiedModelArtifact:
    root: Path
    manifest: ModelManifestV1
    manifest_sha256: str
    model_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or type(self.manifest) is not ModelManifestV1:
            raise ValueError("verified model artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("model_receipt_sha256", self.model_receipt_sha256)


@dataclass(frozen=True)
class PredictionBuildSpec:
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: Literal[5, 10]
    model: Literal["lightgbm"]
    model_version: str

    def __post_init__(self) -> None:
        _require_bare_hex64("experiment_key", self.experiment_key)
        _require_bare_hex64("work_key", self.work_key)
        if (
            type(self.fold) is not str
            or len(self.fold) != 8
            or not self.fold.startswith("fold_")
            or not self.fold[5:].isdigit()
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or self.model != "lightgbm"
            or type(self.model_version) is not str
            or not self.model_version.strip()
        ):
            raise ValueError("prediction build spec 非法")


@dataclass(frozen=True)
class PredictionUpstreamPaths:
    model_receipt_path: Path
    model_upstream_paths: ModelUpstreamPaths
    feature_receipt_path: Path
    feature_upstream_paths: FeatureUpstreamPaths
    fold_receipt_path: Path

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model_receipt_path, Path)
            or type(self.model_upstream_paths) is not ModelUpstreamPaths
            or not isinstance(self.feature_receipt_path, Path)
            or type(self.feature_upstream_paths) is not FeatureUpstreamPaths
            or not isinstance(self.fold_receipt_path, Path)
        ):
            raise ValueError("prediction upstream paths 非法")


@dataclass(frozen=True)
class PredictionManifestV1:
    schema_version: Literal["m3-prediction-artifact-v1"]
    experiment_key: str
    work_key: str
    model_manifest_sha256: str
    model_sha256: str
    feature_manifest_sha256: str
    selected_feature_schema_sha256: str
    eligibility_sha256: str
    signal_dates_sha256: str
    snapshot_id: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    n_eligible: int
    n_scorable: int
    n_predicted: int
    prediction_keys_sha256: str
    predictions_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-prediction-artifact-v1":
            raise ValueError("prediction manifest schema 非法")
        for name in (
            "experiment_key", "work_key", "model_manifest_sha256", "model_sha256",
            "feature_manifest_sha256", "selected_feature_schema_sha256",
            "eligibility_sha256", "signal_dates_sha256", "snapshot_id",
            "prediction_keys_sha256", "predictions_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or not self.fold
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or self.model != "lightgbm"
            or type(self.model_version) is not str
            or not self.model_version
            or any(type(value) is not int or value < 0 for value in (
                self.n_eligible, self.n_scorable, self.n_predicted,
            ))
            or not 0 < self.n_predicted == self.n_scorable <= self.n_eligible
        ):
            raise ValueError("prediction manifest 非法")


@dataclass(frozen=True)
class VerifiedPredictionArtifact:
    root: Path
    predictions: pl.DataFrame
    manifest: PredictionManifestV1
    manifest_sha256: str
    prediction_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, Path)
            or not isinstance(self.predictions, pl.DataFrame)
            or type(self.manifest) is not PredictionManifestV1
        ):
            raise ValueError("verified prediction artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("prediction_receipt_sha256", self.prediction_receipt_sha256)


@dataclass(frozen=True)
class TargetBuildSpec:
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: Literal[5, 10]
    strategy: Literal["topk"]
    strategy_version: str
    top_k: int
    cash_buffer: float
    max_weight: float
    minimum_scorable_coverage: float

    def __post_init__(self) -> None:
        _require_bare_hex64("experiment_key", self.experiment_key)
        _require_bare_hex64("work_key", self.work_key)
        values = (self.cash_buffer, self.max_weight, self.minimum_scorable_coverage)
        if (
            type(self.fold) is not str
            or not self.fold
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or self.strategy != "topk"
            or type(self.strategy_version) is not str
            or not self.strategy_version
            or type(self.top_k) is not int
            or self.top_k < 1
            or any(type(value) is not float or not math.isfinite(value) for value in values)
            or not 0.0 <= self.cash_buffer < 1.0
            or not 0.0 < self.max_weight <= 1.0
            or not 0.0 <= self.minimum_scorable_coverage <= 1.0
        ):
            raise ValueError("target build spec 非法")


@dataclass(frozen=True)
class TargetUpstreamPaths:
    feature_receipt_path: Path
    prediction_receipt_path: Path
    prediction_upstream_paths: PredictionUpstreamPaths
    fold_receipt_path: Path
    experiment_receipt_path: Path

    def __post_init__(self) -> None:
        paths = (
            self.feature_receipt_path, self.prediction_receipt_path,
            self.fold_receipt_path, self.experiment_receipt_path,
        )
        if (
            any(not isinstance(path, Path) for path in paths)
            or type(self.prediction_upstream_paths) is not PredictionUpstreamPaths
            or len(set(paths)) != 4
        ):
            raise ValueError("target upstream paths 非法")


@dataclass(frozen=True)
class TargetManifestV1:
    schema_version: Literal["m3-target-artifact-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    work_key: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    scientific_config_sha256: str
    prediction_manifest_sha256: str
    feature_manifest_sha256: str
    fold_plan_manifest_sha256: str
    snapshot_id: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    strategy: str
    strategy_version: str
    eligible_keys_sha256: str
    signal_dates_sha256: str
    n_dates: int
    n_eligible: int
    n_scorable: int
    n_predicted: int
    n_selected: int
    target_keys_sha256: str
    targets_sha256: str
    target_daily_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-target-artifact-v1":
            raise ValueError("target manifest schema 非法")
        for name in (
            "experiment_key", "experiment_manifest_sha256", "work_key",
            "g1_release_id", "g1_release_manifest_sha256", "scientific_config_sha256",
            "prediction_manifest_sha256", "feature_manifest_sha256",
            "fold_plan_manifest_sha256", "snapshot_id", "eligible_keys_sha256",
            "signal_dates_sha256", "target_keys_sha256", "targets_sha256",
            "target_daily_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        counts = (
            self.n_dates, self.n_eligible, self.n_scorable,
            self.n_predicted, self.n_selected,
        )
        if (
            type(self.fold) is not str
            or not self.fold
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or any(type(value) is not str or not value for value in (
                self.model, self.model_version, self.strategy, self.strategy_version
            ))
            or any(type(value) is not int or value < 0 for value in counts)
            or self.n_selected > self.n_predicted
        ):
            raise ValueError("target manifest 非法")


@dataclass(frozen=True)
class AShareCostPeriod:
    effective_from: dt.date
    effective_to: dt.date | None
    commission_rate: Decimal
    commission_min: Decimal
    stamp_tax_sell: Decimal
    transfer_fee: Decimal
    slippage: Decimal

    def __post_init__(self) -> None:
        amounts = (
            self.commission_rate,
            self.commission_min,
            self.stamp_tax_sell,
            self.transfer_fee,
            self.slippage,
        )
        if (
            type(self.effective_from) is not dt.date
            or (self.effective_to is not None and type(self.effective_to) is not dt.date)
            or (self.effective_to is not None and self.effective_to < self.effective_from)
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in amounts
            )
        ):
            raise ValueError("A-share cost period invalid")


@dataclass(frozen=True)
class BacktestWindow:
    signal_dates: tuple[dt.date, ...]
    execution_dates: tuple[dt.date, ...]
    first_execution_date: dt.date
    terminal_valuation_date: dt.date
    force_liquidation: Literal[False]

    def __post_init__(self) -> None:
        if (
            not self.signal_dates
            or len(self.signal_dates) != len(self.execution_dates)
            or tuple(sorted(set(self.signal_dates))) != self.signal_dates
            or tuple(sorted(set(self.execution_dates))) != self.execution_dates
            or any(
                execution <= signal
                for signal, execution in zip(
                    self.signal_dates, self.execution_dates, strict=True
                )
            )
            or self.first_execution_date != self.execution_dates[0]
            or self.terminal_valuation_date != self.execution_dates[-1]
            or self.force_liquidation is not False
        ):
            raise ValueError("backtest window invalid")


@dataclass(frozen=True)
class BacktestPlanManifestV1:
    schema_version: Literal["m3-a-share-backtest-plan-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    work_key: str
    target_manifest_sha256: str
    target_receipt_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    scientific_config_sha256: str
    fold_plan_manifest_sha256: str
    fold: str
    horizon_sessions: int
    window: BacktestWindow
    session_calendar_sha256: str
    cost_schedule_sha256: str
    cost_schedule_version: str
    order_quantity_rule_version: str
    scheduled_targets_sha256: str
    schedule_diagnostics_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-a-share-backtest-plan-v1":
            raise ValueError("backtest plan schema invalid")
        for name in (
            "experiment_key",
            "experiment_manifest_sha256",
            "work_key",
            "target_manifest_sha256",
            "target_receipt_sha256",
            "g1_release_id",
            "g1_release_manifest_sha256",
            "scientific_config_sha256",
            "fold_plan_manifest_sha256",
            "session_calendar_sha256",
            "cost_schedule_sha256",
            "scheduled_targets_sha256",
            "schedule_diagnostics_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or not self.fold
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or type(self.window) is not BacktestWindow
            or type(self.cost_schedule_version) is not str
            or not self.cost_schedule_version
            or self.order_quantity_rule_version
            != "sse_szse_limit_order_quantity_v1"
        ):
            raise ValueError("backtest plan manifest invalid")


@dataclass(frozen=True)
class VerifiedTargetArtifact:
    root: Path
    targets: pl.DataFrame
    target_daily: pl.DataFrame
    manifest: TargetManifestV1
    manifest_sha256: str
    target_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, Path)
            or not isinstance(self.targets, pl.DataFrame)
            or not isinstance(self.target_daily, pl.DataFrame)
            or type(self.manifest) is not TargetManifestV1
        ):
            raise ValueError("verified target artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("target_receipt_sha256", self.target_receipt_sha256)


@dataclass(frozen=True)
class VerifiedBacktestPlanArtifact:
    root: Path
    scheduled_targets: pl.DataFrame
    manifest: BacktestPlanManifestV1
    manifest_sha256: str
    plan_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, Path)
            or not isinstance(self.scheduled_targets, pl.DataFrame)
            or type(self.manifest) is not BacktestPlanManifestV1
        ):
            raise ValueError("verified backtest plan artifact invalid")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("plan_receipt_sha256", self.plan_receipt_sha256)


ScenarioName = Literal["0p5x", "1p0x", "2p0x"]
_SCENARIOS: tuple[ScenarioName, ...] = ("0p5x", "1p0x", "2p0x")


@dataclass(frozen=True)
class AShareScenarioMetricsV1:
    schema_version: Literal["m3-a-share-scenario-metrics-v1"]
    experiment_key: str
    work_key: str
    scenario: ScenarioName
    multiplier: float
    n_sessions: int
    initial_cash: float
    terminal_equity: float
    portfolio_return: float
    annualized_return: float
    test_max_drawdown: float
    benchmark_return: float
    test_net_excess_return: float
    relative_wealth: float
    target_gross_turnover: float
    target_one_way_turnover: float
    realized_gross_turnover: float
    test_turnover: float
    commission_total: float
    stamp_tax_total: float
    transfer_fee_total: float
    total_fees: float
    slippage_cost_total: float
    total_trading_cost: float
    cash_rounding_delta_total: float
    requested_order_count: int
    rejection_count: int
    rejection_rate: float | None
    unfilled_notional: float
    average_cash_ratio: float
    corporate_action_posting_count: int
    unexecutable_date_count: int
    terminal_positions_market_value: float
    terminal_pending_exit_value: float
    terminal_estimated_exit_cost_1x: float

    def __post_init__(self) -> None:
        if self.schema_version != "m3-a-share-scenario-metrics-v1":
            raise ValueError("A-share scenario metrics schema invalid")
        _require_bare_hex64("experiment_key", self.experiment_key)
        _require_bare_hex64("work_key", self.work_key)
        expected = {"0p5x": 0.5, "1p0x": 1.0, "2p0x": 2.0}
        if self.scenario not in _SCENARIOS or self.multiplier != expected[self.scenario]:
            raise ValueError("A-share scenario identity invalid")
        if type(self.n_sessions) is not int or self.n_sessions <= 0:
            raise ValueError("A-share scenario session count invalid")
        for name in (
            "requested_order_count", "rejection_count",
            "corporate_action_posting_count", "unexecutable_date_count",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"A-share scenario {name} invalid")
        float_names = tuple(
            name for name in self.__dataclass_fields__
            if name not in {
                "schema_version", "experiment_key", "work_key", "scenario",
                "n_sessions", "requested_order_count", "rejection_count",
                "corporate_action_posting_count", "unexecutable_date_count",
                "rejection_rate",
            }
        )
        if any(
            type(getattr(self, name)) is not float
            or not math.isfinite(getattr(self, name))
            for name in float_names
        ):
            raise ValueError("A-share scenario metric must be finite float")
        if self.rejection_rate is not None and (
            type(self.rejection_rate) is not float
            or not math.isfinite(self.rejection_rate)
            or not 0.0 <= self.rejection_rate <= 1.0
        ):
            raise ValueError("A-share scenario rejection rate invalid")
        nonnegative = (
            "initial_cash", "terminal_equity", "target_gross_turnover",
            "target_one_way_turnover", "realized_gross_turnover", "test_turnover",
            "commission_total", "stamp_tax_total", "transfer_fee_total",
            "total_fees", "slippage_cost_total", "total_trading_cost",
            "unfilled_notional", "average_cash_ratio",
            "terminal_positions_market_value", "terminal_pending_exit_value",
            "terminal_estimated_exit_cost_1x",
        )
        if self.initial_cash <= 0.0 or any(getattr(self, name) < 0.0 for name in nonnegative):
            raise ValueError("A-share scenario nonnegative metric invalid")
        if self.rejection_count > self.requested_order_count:
            raise ValueError("A-share scenario rejection conservation invalid")


@dataclass(frozen=True)
class BacktestMetricsV1:
    schema_version: Literal["m3-a-share-backtest-metrics-v1"]
    experiment_key: str
    work_key: str
    scenarios: tuple[AShareScenarioMetricsV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-a-share-backtest-metrics-v1":
            raise ValueError("A-share backtest metrics schema invalid")
        _require_bare_hex64("experiment_key", self.experiment_key)
        _require_bare_hex64("work_key", self.work_key)
        if (
            type(self.scenarios) is not tuple
            or tuple(item.scenario for item in self.scenarios) != _SCENARIOS
            or any(type(item) is not AShareScenarioMetricsV1 for item in self.scenarios)
            or any(
                item.experiment_key != self.experiment_key or item.work_key != self.work_key
                for item in self.scenarios
            )
        ):
            raise ValueError("A-share backtest scenario closure invalid")


@dataclass(frozen=True)
class BacktestArtifactEntryV1:
    path: str
    sha256: str
    size_bytes: int
    row_count: int | None
    schema_name: str

    def __post_init__(self) -> None:
        if (
            type(self.path) is not str or not self.path or "\\" in self.path
            or self.path.startswith("/") or ".." in Path(self.path).parts
        ):
            raise ValueError("backtest artifact path invalid")
        _require_bare_hex64("sha256", self.sha256)
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("backtest artifact size invalid")
        if self.row_count is not None and (
            type(self.row_count) is not int or self.row_count < 0
        ):
            raise ValueError("backtest artifact row count invalid")
        if type(self.schema_name) is not str or not self.schema_name:
            raise ValueError("backtest artifact schema name invalid")


@dataclass(frozen=True)
class BacktestScenarioManifestV1:
    schema_version: Literal["m3-a-share-scenario-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    work_key: str
    scientific_config_sha256: str
    target_manifest_sha256: str
    backtest_plan_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    fold: str
    horizon_sessions: int
    scenario: ScenarioName
    multiplier: float
    cost_periods_sha256: str
    order_quantity_rule_version: str
    input_market_facts_sha256: str
    output_files: tuple[BacktestArtifactEntryV1, ...]
    metrics_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-a-share-scenario-v1":
            raise ValueError("backtest scenario manifest schema invalid")
        for name in (
            "experiment_key", "experiment_manifest_sha256", "work_key",
            "scientific_config_sha256", "target_manifest_sha256",
            "backtest_plan_manifest_sha256", "g1_release_id",
            "g1_release_manifest_sha256", "cost_periods_sha256",
            "input_market_facts_sha256", "metrics_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        expected = {"0p5x": 0.5, "1p0x": 1.0, "2p0x": 2.0}
        if (
            self.scenario not in _SCENARIOS or self.multiplier != expected[self.scenario]
            or type(self.fold) is not str or not self.fold
            or type(self.horizon_sessions) is not int or self.horizon_sessions not in {5, 10}
            or self.order_quantity_rule_version != "sse_szse_limit_order_quantity_v1"
            or type(self.output_files) is not tuple or len(self.output_files) != 8
            or any(type(item) is not BacktestArtifactEntryV1 for item in self.output_files)
            or tuple(item.path for item in self.output_files)
            != tuple(sorted(item.path for item in self.output_files))
        ):
            raise ValueError("backtest scenario manifest invalid")


@dataclass(frozen=True)
class BacktestBundleManifestV1:
    schema_version: Literal["m3-a-share-backtest-bundle-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    work_key: str
    scientific_config_sha256: str
    target_manifest_sha256: str
    backtest_plan_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    order_quantity_rule_version: str
    scenario_manifest_sha256s: tuple[tuple[str, str], ...]
    common_target_manifest_sha256: str
    common_market_facts_sha256: str
    backtest_metrics_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-a-share-backtest-bundle-v1":
            raise ValueError("backtest bundle manifest schema invalid")
        for name in (
            "experiment_key", "experiment_manifest_sha256", "work_key",
            "scientific_config_sha256", "target_manifest_sha256",
            "backtest_plan_manifest_sha256", "g1_release_id",
            "g1_release_manifest_sha256", "common_target_manifest_sha256",
            "common_market_facts_sha256", "backtest_metrics_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            self.order_quantity_rule_version != "sse_szse_limit_order_quantity_v1"
            or type(self.scenario_manifest_sha256s) is not tuple
            or tuple(name for name, _ in self.scenario_manifest_sha256s) != _SCENARIOS
        ):
            raise ValueError("backtest bundle manifest invalid")
        for _, digest in self.scenario_manifest_sha256s:
            _require_bare_hex64("scenario_manifest_sha256", digest)


@dataclass(frozen=True)
class VerifiedBacktestArtifact:
    root: Path
    metrics: BacktestMetricsV1
    manifest: BacktestBundleManifestV1
    manifest_sha256: str
    backtest_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or type(self.metrics) is not BacktestMetricsV1:
            raise ValueError("verified backtest artifact invalid")
        if type(self.manifest) is not BacktestBundleManifestV1:
            raise ValueError("verified backtest manifest invalid")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("backtest_receipt_sha256", self.backtest_receipt_sha256)


IcStatus = Literal[
    "NO_ELIGIBLE",
    "NO_LABELS",
    "NO_PREDICTIONS",
    "INSUFFICIENT_SYMBOLS",
    "BOTH_ZERO_VARIANCE",
    "SCORE_ZERO_VARIANCE",
    "LABEL_ZERO_VARIANCE",
    "COMPUTABLE",
]


@dataclass(frozen=True)
class EvaluationSpec:
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: Literal[5, 10]
    minimum_ic_symbols: int

    def __post_init__(self) -> None:
        _require_bare_hex64("experiment_key", self.experiment_key)
        _require_bare_hex64("work_key", self.work_key)
        if (
            type(self.fold) is not str
            or not self.fold
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or type(self.minimum_ic_symbols) is not int
            or self.minimum_ic_symbols < 2
        ):
            raise ValueError("evaluation spec 非法")


@dataclass(frozen=True)
class EvaluationUpstreamPaths:
    prediction_receipt_path: Path
    prediction_upstream_paths: PredictionUpstreamPaths
    label_receipt_path: Path
    feature_receipt_path: Path
    fold_receipt_path: Path

    def __post_init__(self) -> None:
        if (
            not isinstance(self.prediction_receipt_path, Path)
            or type(self.prediction_upstream_paths) is not PredictionUpstreamPaths
            or not isinstance(self.label_receipt_path, Path)
            or not isinstance(self.feature_receipt_path, Path)
            or not isinstance(self.fold_receipt_path, Path)
        ):
            raise ValueError("evaluation upstream paths 非法")


@dataclass(frozen=True)
class EvaluationMetricsV1:
    schema_version: Literal["m3-evaluation-metrics-v1"]
    experiment_key: str
    work_key: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    n_dates: int
    n_computable_dates: int
    n_eligible: int
    n_scorable: int
    n_predicted: int
    n_labeled: int
    n_evaluated: int
    feature_coverage: float | None
    prediction_coverage: float | None
    label_coverage: float | None
    evaluation_coverage: float | None
    pearson_ic_mean: float | None
    rank_ic_mean: float | None
    pearson_icir: float | None
    rank_icir: float | None
    status_counts: tuple[tuple[IcStatus, int], ...]
    daily_sha256: str

    def __post_init__(self) -> None:
        statuses = (
            "NO_ELIGIBLE", "NO_LABELS", "NO_PREDICTIONS",
            "INSUFFICIENT_SYMBOLS", "BOTH_ZERO_VARIANCE",
            "SCORE_ZERO_VARIANCE", "LABEL_ZERO_VARIANCE", "COMPUTABLE",
        )
        if self.schema_version != "m3-evaluation-metrics-v1":
            raise ValueError("evaluation metrics schema 非法")
        for name in ("experiment_key", "work_key", "daily_sha256"):
            _require_bare_hex64(name, getattr(self, name))
        counts = (
            self.n_dates, self.n_computable_dates, self.n_eligible,
            self.n_scorable, self.n_predicted, self.n_labeled, self.n_evaluated,
        )
        ratios = (
            self.feature_coverage, self.prediction_coverage, self.label_coverage,
            self.evaluation_coverage,
        )
        metrics = (
            self.pearson_ic_mean, self.rank_ic_mean, self.pearson_icir,
            self.rank_icir,
        )
        if (
            type(self.fold) is not str
            or not self.fold
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or type(self.model) is not str
            or not self.model
            or type(self.model_version) is not str
            or not self.model_version
            or any(type(value) is not int or value < 0 for value in counts)
            or self.n_computable_dates > self.n_dates
            or any(
                value is not None
                and (type(value) is not float or not math.isfinite(value) or not 0.0 <= value <= 1.0)
                for value in ratios
            )
            or any(
                value is not None
                and (type(value) is not float or not math.isfinite(value))
                for value in metrics
            )
            or tuple(name for name, _ in self.status_counts) != statuses
            or any(type(count) is not int or count < 0 for _, count in self.status_counts)
            or sum(count for _, count in self.status_counts) != self.n_dates
        ):
            raise ValueError("evaluation metrics 非法")


@dataclass(frozen=True)
class EvaluationManifestV1:
    schema_version: Literal["m3-evaluation-artifact-v1"]
    experiment_key: str
    work_key: str
    prediction_manifest_sha256: str
    label_manifest_sha256: str
    feature_manifest_sha256: str
    fold_plan_manifest_sha256: str
    eligible_keys_sha256: str
    evaluation_dates_sha256: str
    scientific_config_sha256: str
    fold: str
    horizon_sessions: int
    model: str
    model_version: str
    daily_sha256: str
    metrics_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-evaluation-artifact-v1":
            raise ValueError("evaluation manifest schema 非法")
        for name in (
            "experiment_key", "work_key", "prediction_manifest_sha256",
            "label_manifest_sha256", "feature_manifest_sha256",
            "fold_plan_manifest_sha256", "eligible_keys_sha256",
            "evaluation_dates_sha256", "scientific_config_sha256",
            "daily_sha256", "metrics_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.fold) is not str
            or not self.fold
            or type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or type(self.model) is not str
            or not self.model
            or type(self.model_version) is not str
            or not self.model_version
        ):
            raise ValueError("evaluation manifest 非法")


@dataclass(frozen=True)
class VerifiedEvaluationArtifact:
    root: Path
    daily: pl.DataFrame
    metrics: EvaluationMetricsV1
    manifest: EvaluationManifestV1
    manifest_sha256: str
    evaluation_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, Path)
            or not isinstance(self.daily, pl.DataFrame)
            or type(self.metrics) is not EvaluationMetricsV1
            or type(self.manifest) is not EvaluationManifestV1
        ):
            raise ValueError("verified evaluation artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("evaluation_receipt_sha256", self.evaluation_receipt_sha256)


@dataclass(frozen=True)
class ResearchSummaryUpstreamPaths:
    experiment_receipt_path: Path
    evaluation_receipt_paths: tuple[Path, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.experiment_receipt_path, Path)
            or not self.evaluation_receipt_paths
            or any(not isinstance(path, Path) for path in self.evaluation_receipt_paths)
            or len(set(self.evaluation_receipt_paths)) != len(self.evaluation_receipt_paths)
        ):
            raise ValueError("research summary upstream paths 非法")


@dataclass(frozen=True)
class ResearchSummaryMetricsV1:
    schema_version: Literal["m3-research-summary-metrics-v1"]
    experiment_key: str
    horizon_sessions: int
    model: str
    model_version: str
    folds: tuple[str, ...]
    n_dates: int
    n_computable_dates: int
    n_eligible: int
    n_scorable: int
    n_predicted: int
    n_labeled: int
    n_evaluated: int
    feature_coverage: float | None
    prediction_coverage: float | None
    label_coverage: float | None
    evaluation_coverage: float | None
    pearson_ic_mean: float | None
    rank_ic_mean: float | None
    pearson_icir: float | None
    rank_icir: float | None
    status_counts: tuple[tuple[IcStatus, int], ...]
    daily_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-research-summary-metrics-v1":
            raise ValueError("research summary metrics schema 非法")
        _require_bare_hex64("experiment_key", self.experiment_key)
        _require_bare_hex64("daily_sha256", self.daily_sha256)
        EvaluationMetricsV1(
            schema_version="m3-evaluation-metrics-v1",
            experiment_key=self.experiment_key,
            work_key="0" * 64,
            fold="summary",
            horizon_sessions=self.horizon_sessions,
            model=self.model,
            model_version=self.model_version,
            n_dates=self.n_dates,
            n_computable_dates=self.n_computable_dates,
            n_eligible=self.n_eligible,
            n_scorable=self.n_scorable,
            n_predicted=self.n_predicted,
            n_labeled=self.n_labeled,
            n_evaluated=self.n_evaluated,
            feature_coverage=self.feature_coverage,
            prediction_coverage=self.prediction_coverage,
            label_coverage=self.label_coverage,
            evaluation_coverage=self.evaluation_coverage,
            pearson_ic_mean=self.pearson_ic_mean,
            rank_ic_mean=self.rank_ic_mean,
            pearson_icir=self.pearson_icir,
            rank_icir=self.rank_icir,
            status_counts=self.status_counts,
            daily_sha256=self.daily_sha256,
        )
        if (
            not self.folds
            or tuple(sorted(self.folds)) != self.folds
            or len(set(self.folds)) != len(self.folds)
        ):
            raise ValueError("research summary folds 非法")


@dataclass(frozen=True)
class ResearchSummaryManifestV1:
    schema_version: Literal["m3-research-summary-v1"]
    experiment_key: str
    horizon_sessions: int
    model: str
    model_version: str
    scientific_config_sha256: str
    folds: tuple[str, ...]
    evaluation_manifest_sha256s: tuple[str, ...]
    evaluation_receipt_sha256s: tuple[str, ...]
    test_dates_sha256: str
    daily_sha256: str
    fold_metrics_sha256: str
    metrics_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-research-summary-v1":
            raise ValueError("research summary manifest schema 非法")
        for name in (
            "experiment_key", "scientific_config_sha256", "test_dates_sha256",
            "daily_sha256", "fold_metrics_sha256", "metrics_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        for value in (*self.evaluation_manifest_sha256s, *self.evaluation_receipt_sha256s):
            _require_bare_hex64("evaluation_sha256", value)
        if (
            type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or type(self.model) is not str
            or not self.model
            or type(self.model_version) is not str
            or not self.model_version
            or not self.folds
            or self.folds != tuple(sorted(self.folds))
            or len(set(self.folds)) != len(self.folds)
            or len(self.folds) != len(self.evaluation_manifest_sha256s)
            or len(self.folds) != len(self.evaluation_receipt_sha256s)
        ):
            raise ValueError("research summary manifest 非法")


@dataclass(frozen=True)
class VerifiedResearchSummaryArtifact:
    root: Path
    daily: pl.DataFrame
    fold_metrics: pl.DataFrame
    metrics: ResearchSummaryMetricsV1
    manifest: ResearchSummaryManifestV1
    manifest_sha256: str
    summary_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root, Path)
            or not isinstance(self.daily, pl.DataFrame)
            or not isinstance(self.fold_metrics, pl.DataFrame)
            or type(self.metrics) is not ResearchSummaryMetricsV1
            or type(self.manifest) is not ResearchSummaryManifestV1
        ):
            raise ValueError("verified research summary artifact 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("summary_receipt_sha256", self.summary_receipt_sha256)


@dataclass(frozen=True)
class LabelBuildSpec:
    experiment_key: str
    experiment_manifest_sha256: str
    horizon_sessions: Literal[5, 10]
    benchmark: Literal["510300.SH"]
    label_version: str
    label_build_code_version: str

    def __post_init__(self) -> None:
        _require_bare_hex64("experiment_key", self.experiment_key)
        _require_bare_hex64(
            "experiment_manifest_sha256", self.experiment_manifest_sha256
        )
        if (
            type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or self.benchmark != "510300.SH"
        ):
            raise ValueError("label spec horizon/benchmark 非法")
        for name in ("label_version", "label_build_code_version"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"label spec {name} 非法")


@dataclass(frozen=True)
class LabelArtifactManifest:
    schema_version: Literal["m3-label-artifact-v1"]
    experiment_key: str
    experiment_manifest_sha256: str
    g1_release_id: str
    g1_release_manifest_sha256: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    horizon_sessions: int
    benchmark: str
    label_version: str
    label_build_code_version: str
    eligible_keys_sha256: str
    bars_sha256: str
    session_calendar_sha256: str
    benchmark_bars_sha256: str
    labels_sha256: str
    labels_row_count: int
    label_key_sha256: str
    diagnostics_sha256: str
    diagnostics_row_count: int
    diagnostic_key_sha256: str
    candidate_count: int
    success_count: int
    diagnostic_count: int

    def __post_init__(self) -> None:
        if self.schema_version != "m3-label-artifact-v1":
            raise ValueError("label manifest schema 非法")
        for name in (
            "experiment_key", "experiment_manifest_sha256", "g1_release_id",
            "g1_release_manifest_sha256", "snapshot_id",
            "snapshot_manifest_sha256", "eligible_keys_sha256", "bars_sha256",
            "session_calendar_sha256", "benchmark_bars_sha256", "labels_sha256",
            "label_key_sha256", "diagnostics_sha256", "diagnostic_key_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if (
            type(self.horizon_sessions) is not int
            or self.horizon_sessions not in {5, 10}
            or self.benchmark != "510300.SH"
        ):
            raise ValueError("label manifest horizon/benchmark 非法")
        for name in ("label_version", "label_build_code_version"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"label manifest {name} 非法")
        for name in (
            "labels_row_count", "diagnostics_row_count", "candidate_count",
            "success_count", "diagnostic_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"label manifest {name} 非法")
        if self.success_count != self.labels_row_count:
            raise ValueError("label manifest success/labels count 漂移")
        if self.candidate_count != self.success_count + self.diagnostic_count:
            raise ValueError("label manifest conservation 非法")


@dataclass(frozen=True)
class VerifiedLabelArtifact:
    root: Path
    labels: pl.DataFrame
    diagnostics: pl.DataFrame
    manifest: LabelArtifactManifest
    manifest_sha256: str
    label_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ValueError("verified label root 非法")
        if not isinstance(self.labels, pl.DataFrame) or not isinstance(
            self.diagnostics, pl.DataFrame
        ):
            raise ValueError("verified label frames 非法")
        if type(self.manifest) is not LabelArtifactManifest:
            raise ValueError("verified label manifest 非法")
        _require_bare_hex64("manifest_sha256", self.manifest_sha256)
        _require_bare_hex64("label_receipt_sha256", self.label_receipt_sha256)


@dataclass(frozen=True)
class LabelReconciliationSpec:
    reconciliation_key: str
    experiment_key: str
    horizon_sessions: Literal[5, 10]
    provider_validation_receipt_sha256: str
    label_manifest_sha256: str
    label_reconciliation_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str
    worker_protocol_version: Literal["m3-qlib-worker-v1"]
    qlib_version: Literal["0.9.7"]
    qlib_expression_atol: float
    benchmark_return_atol: float
    label_return_atol: float

    def __post_init__(self) -> None:
        for name in (
            "reconciliation_key", "experiment_key",
            "provider_validation_receipt_sha256", "label_manifest_sha256",
            "label_reconciliation_config_sha256",
            "dependency_fingerprint_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if type(self.horizon_sessions) is not int or self.horizon_sessions not in {5, 10}:
            raise ValueError("label reconciliation horizon 非法")
        if type(self.code_version) is not str or not self.code_version.strip():
            raise ValueError("label reconciliation code_version 非法")
        if (
            self.worker_protocol_version != "m3-qlib-worker-v1"
            or self.qlib_version != "0.9.7"
        ):
            raise ValueError("label reconciliation protocol 非法")
        tolerances = (
            self.qlib_expression_atol,
            self.benchmark_return_atol,
            self.label_return_atol,
        )
        if any(
            type(value) is not float or not math.isfinite(value) or value < 0.0
            for value in tolerances
        ):
            raise ValueError("label reconciliation tolerance 非法")
        if (
            self.qlib_expression_atol > self.label_return_atol
            or self.benchmark_return_atol > self.label_return_atol
        ):
            raise ValueError("label reconciliation tolerance 层级非法")


@dataclass(frozen=True)
class LabelReconciliationReceiptPaths:
    """Explicit upstream receipts; reconciliation never scans or guesses them."""

    snapshot_receipt_path: Path
    provider_receipt_path: Path
    provider_validation_receipt_path: Path
    experiment_receipt_path: Path
    label_receipt_path: Path

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if not isinstance(getattr(self, name), Path):
                raise ValueError(f"label reconciliation {name} 非法")


@dataclass(frozen=True)
class LabelReconciliationSummaryV1:
    schema_version: Literal["m3-label-reconciliation-v1"]
    reconciliation_key: str
    experiment_key: str
    horizon_sessions: int
    provider_validation_receipt_sha256: str
    label_manifest_sha256: str
    label_reconciliation_config_sha256: str
    dependency_fingerprint_sha256: str
    code_version: str
    worker_protocol_version: str
    qlib_version: str
    qlib_expression: str
    details_sha256: str
    row_count: int
    row_key_sha256: str
    missing_key_count: int
    extra_key_count: int
    duplicate_key_count: int
    non_finite_count: int
    expression_direct_max_abs_error: float
    expression_direct_p99_abs_error: float
    benchmark_max_abs_error: float
    benchmark_p99_abs_error: float
    raw_label_max_abs_error: float
    raw_label_p99_abs_error: float
    relative_label_max_abs_error: float
    relative_label_p99_abs_error: float
    qlib_expression_atol: float
    benchmark_return_atol: float
    label_return_atol: float
    passed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "m3-label-reconciliation-v1":
            raise ValueError("label reconciliation summary schema 非法")
        for name in (
            "reconciliation_key", "experiment_key",
            "provider_validation_receipt_sha256", "label_manifest_sha256",
            "label_reconciliation_config_sha256",
            "dependency_fingerprint_sha256", "details_sha256",
            "row_key_sha256",
        ):
            _require_bare_hex64(name, getattr(self, name))
        if type(self.horizon_sessions) is not int or self.horizon_sessions not in {5, 10}:
            raise ValueError("label reconciliation summary horizon 非法")
        if (
            type(self.code_version) is not str or not self.code_version.strip()
            or self.worker_protocol_version != "m3-qlib-worker-v1"
            or self.qlib_version != "0.9.7"
            or self.qlib_expression
            != f"Ref($close,-{self.horizon_sessions})/Ref($open,-1)-1"
        ):
            raise ValueError("label reconciliation summary identity 非法")
        for name in (
            "row_count", "missing_key_count", "extra_key_count",
            "duplicate_key_count", "non_finite_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"label reconciliation {name} 非法")
        float_names = (
            "expression_direct_max_abs_error",
            "expression_direct_p99_abs_error", "benchmark_max_abs_error",
            "benchmark_p99_abs_error", "raw_label_max_abs_error",
            "raw_label_p99_abs_error", "relative_label_max_abs_error",
            "relative_label_p99_abs_error", "qlib_expression_atol",
            "benchmark_return_atol", "label_return_atol",
        )
        if any(
            type(getattr(self, name)) is not float
            or not math.isfinite(getattr(self, name))
            or getattr(self, name) < 0.0
            for name in float_names
        ):
            raise ValueError("label reconciliation summary float 非法")
        if type(self.passed) is not bool:
            raise ValueError("label reconciliation summary passed 非法")


@dataclass(frozen=True)
class LabelReconciliationResult:
    details: pl.DataFrame
    summary: LabelReconciliationSummaryV1

    def __post_init__(self) -> None:
        if not isinstance(self.details, pl.DataFrame):
            raise ValueError("label reconciliation details 非法")
        if type(self.summary) is not LabelReconciliationSummaryV1:
            raise ValueError("label reconciliation summary 非法")


@dataclass(frozen=True)
class VerifiedLabelReconciliationArtifact:
    root: Path
    details: pl.DataFrame
    summary: LabelReconciliationSummaryV1
    summary_sha256: str
    reconciliation_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not isinstance(self.details, pl.DataFrame):
            raise ValueError("verified label reconciliation artifact 非法")
        if type(self.summary) is not LabelReconciliationSummaryV1:
            raise ValueError("verified label reconciliation summary 非法")
        _require_bare_hex64("summary_sha256", self.summary_sha256)
        _require_bare_hex64(
            "reconciliation_receipt_sha256",
            self.reconciliation_receipt_sha256,
        )


def _validate_snapshot_dates(value: object) -> None:
    dates = tuple(getattr(value, name) for name in (
        "history_start", "history_end", "signal_start", "signal_end"
    ))
    if any(type(item) is not dt.date for item in dates):
        raise ValueError("snapshot 日期必须为精确 date")
    history_start, history_end, signal_start, signal_end = dates
    if not history_start <= signal_start <= signal_end <= history_end:
        raise ValueError("snapshot history/signal 日期闭包非法")
