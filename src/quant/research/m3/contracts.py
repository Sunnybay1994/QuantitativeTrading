"""M3 编排层的稳定值对象，不依赖 Qlib、LightGBM 或 MLflow。"""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import polars as pl

from quant.research.m3.run_state import ArtifactDigest

_HEX64 = frozenset("0123456789abcdef")


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


def _validate_snapshot_dates(value: object) -> None:
    dates = tuple(getattr(value, name) for name in (
        "history_start", "history_end", "signal_start", "signal_end"
    ))
    if any(type(item) is not dt.date for item in dates):
        raise ValueError("snapshot 日期必须为精确 date")
    history_start, history_end, signal_start, signal_end = dates
    if not history_start <= signal_start <= signal_end <= history_end:
        raise ValueError("snapshot history/signal 日期闭包非法")
