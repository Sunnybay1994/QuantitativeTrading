"""M3 编排层的稳定值对象，不依赖 Qlib、LightGBM 或 MLflow。"""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    bytes: int
    version: str

    def __post_init__(self) -> None:
        if not self.url or not self.version:
            raise ValueError("Qlib dump tool URL and version must not be empty")
        if len(self.sha256) != 64 or any(char not in "0123456789abcdef" for char in self.sha256):
            raise ValueError("Qlib dump tool SHA-256 must be 64 lowercase hexadecimal characters")
        if self.bytes <= 0:
            raise ValueError("Qlib dump tool byte count must be positive")


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


def _validate_snapshot_dates(value: object) -> None:
    dates = tuple(getattr(value, name) for name in (
        "history_start", "history_end", "signal_start", "signal_end"
    ))
    if any(type(item) is not dt.date for item in dates):
        raise ValueError("snapshot 日期必须为精确 date")
    history_start, history_end, signal_start, signal_end = dates
    if not history_start <= signal_start <= signal_end <= history_end:
        raise ValueError("snapshot history/signal 日期闭包非法")
