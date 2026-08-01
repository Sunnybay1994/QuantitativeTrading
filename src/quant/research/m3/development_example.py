"""Strict, non-production G1-shaped fixture for downstream M3 development.

The package deliberately cannot become :class:`VerifiedG1Release`.  It preserves
the formal G1 artifact registry and digest shapes while carrying an explicit
``development_example`` identity at every stable boundary.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping, cast

import polars as pl

from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_release import (
    _ARTIFACT_BY_PATH,
    _ARTIFACT_REGISTRY,
    _DETAIL_COLUMNS,
    _DETAIL_DTYPES,
    _frame_to_parquet_bytes,
    _read_exact_parquet,
)
from quant.domain.schemas import (
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
from quant.research.m3.contracts import (
    AlignmentManifestV1,
    BacktestPlanManifestV1,
    EvaluationManifestV1,
    EvaluationMetricsV1,
    ExperimentIdentityManifestV1,
    FeatureManifestV1,
    FoldPlanManifestV1,
    LabelArtifactManifest,
    LabelReconciliationSummaryV1,
    ModelManifestV1,
    PredictionManifestV1,
    ProviderManifestV1,
    ProviderValidationSummaryV1,
    ResearchSummaryManifestV1,
    ResearchSummaryMetricsV1,
    SnapshotManifestV1,
    SnapshotRequestRecordV1,
    TargetManifestV1,
)
from quant.research.m3.config import (
    LoadedM3Config,
    _loaded_from_normalized,
    _validate_and_normalize,
)
from quant.research.m3.run_state import ArtifactDigest

if TYPE_CHECKING:
    from quant.backtest.a_share_execution import AShareMarketFactsIdentityV1

_KIND: Literal["development_example"] = "development_example"
_FIXTURE_VERSION = "m3-a-share-development-example-v2"
_UNIVERSE: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"] = (
    "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
)
_SOURCE: Literal["tushare"] = "tushare"
_HEX_A = "a" * 64
_HEX_B = "b" * 64
_HEX_C = "c" * 64
_D1 = dt.date(2026, 1, 5)
_D2 = dt.date(2026, 1, 6)
_SESSIONS = tuple(
    _D1 + dt.timedelta(days=offset)
    for offset in range(52)
    if (_D1 + dt.timedelta(days=offset)).weekday() < 5
)
_D3 = _SESSIONS[-1]
_SIGNAL_END = _SESSIONS[27]
_PARQUET_WRITE_KWARGS: Mapping[str, object] = {
    "compression": "zstd",
    "compression_level": 3,
    "statistics": True,
    "row_group_size": 65536,
    "use_pyarrow": False,
}


class M3DevelopmentExampleError(ValueError):
    """Stable boundary error for the isolated development fixture."""

    _CODES = {
        "DEVELOPMENT_EXAMPLE_INPUT_INVALID",
        "DEVELOPMENT_EXAMPLE_OUTPUT_INVALID",
        "DEVELOPMENT_EXAMPLE_IDENTITY_MISMATCH",
        "DEVELOPMENT_EXAMPLE_ARTIFACT_INVALID",
    }

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown development example error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DevelopmentG1ArtifactEntryV1:
    """G1-shaped file metadata with an explicit development schema domain."""

    path: str
    sha256: str
    content_sha256: str
    size_bytes: int
    row_count: int
    schema_name: str
    table_schema_version: Literal["development-v1"]
    key_columns: tuple[str, ...]
    min_key: tuple[str, ...] | None
    max_key: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if type(self.path) is not str or self.path not in _ARTIFACT_BY_PATH:
            raise ValueError("development artifact path 非法")
        _require_hex64(self.sha256)
        _require_hex64(self.content_sha256)
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("development artifact size 非法")
        if type(self.row_count) is not int or self.row_count < 0:
            raise ValueError("development artifact rows 非法")
        spec = _ARTIFACT_BY_PATH[self.path]
        expected_schema = {
            "detail": "DevelopmentCrossSourceReconciliationDetailV1",
            "summary": "DevelopmentCrossSourceSummaryV1",
            "quality": "DevelopmentG1QualityV1",
        }.get(spec.kind, spec.schema_name)
        if self.schema_name != expected_schema:
            raise ValueError("development artifact schema 非法")
        if self.table_schema_version != "development-v1":
            raise ValueError("development artifact schema version 非法")
        if self.key_columns != spec.key_columns:
            raise ValueError("development artifact keys 非法")
        if spec.kind in {"summary", "quality"}:
            if self.row_count != 1 or self.min_key is not None or self.max_key is not None:
                raise ValueError("development JSON entry 非法")
        elif self.row_count == 0:
            if self.min_key is not None or self.max_key is not None:
                raise ValueError("development empty entry 非法")
        else:
            _validate_key_range(self.min_key, self.max_key, len(self.key_columns))


@dataclass(frozen=True)
class DevelopmentExampleG1ManifestV1:
    schema_version: Literal["m3-development-example-g1-manifest-v1"]
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    fixture_version: str
    contract_release_id: str
    source: Literal["tushare"]
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    input_summary_sha256: str
    output_summary_sha256: str
    files: tuple[DevelopmentG1ArtifactEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-development-example-g1-manifest-v1":
            raise ValueError("development manifest schema 非法")
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("development manifest kind 非法")
        _require_example_id(self.example_id)
        if self.fixture_version != _FIXTURE_VERSION:
            raise ValueError("development fixture version 非法")
        for value in (
            self.contract_release_id,
            self.input_summary_sha256,
            self.output_summary_sha256,
        ):
            _require_hex64(value)
        if self.source != _SOURCE or self.universe != _UNIVERSE:
            raise ValueError("development source/universe 非法")
        if not (
            self.history_start
            <= self.signal_start
            <= self.signal_end
            <= self.history_end
        ):
            raise ValueError("development 日期闭包非法")
        if type(self.files) is not tuple:
            raise ValueError("development files 非法")
        rebuilt = tuple(
            DevelopmentG1ArtifactEntryV1(**asdict(item))
            for item in self.files
            if type(item) is DevelopmentG1ArtifactEntryV1
        )
        if len(rebuilt) != len(_ARTIFACT_REGISTRY):
            raise ValueError("development files 数量非法")
        ordered = tuple(sorted(rebuilt, key=lambda item: item.path))
        if rebuilt != ordered:
            raise ValueError("development files 必须排序")
        if tuple(item.path for item in ordered) != tuple(
            sorted(spec.path for spec in _ARTIFACT_REGISTRY)
        ):
            raise ValueError("development files 闭包非法")
        object.__setattr__(self, "files", ordered)

    @property
    def release_id(self) -> str:
        """G2 identity view; this is not a formal G1 release identity."""
        return self.contract_release_id


@dataclass(frozen=True)
class DevelopmentExampleG1RequestV1:
    schema_version: Literal["m3-development-example-g1-request-v1"]
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_request_key: str
    example_id: str
    fixture_version: str
    manifest_sha256: str
    history_start: dt.date
    history_end: dt.date

    def __post_init__(self) -> None:
        if self.schema_version != "m3-development-example-g1-request-v1":
            raise ValueError("development request schema 非法")
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("development request kind 非法")
        _require_hex64(self.example_request_key)
        _require_example_id(self.example_id)
        _require_hex64(self.manifest_sha256)
        if self.fixture_version != _FIXTURE_VERSION:
            raise ValueError("development request fixture 非法")
        if self.history_end < self.history_start:
            raise ValueError("development request 日期非法")


@dataclass(frozen=True)
class DevelopmentExampleG1ReceiptV1:
    schema_version: Literal["m3-development-example-g1-receipt-v1"]
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    stage: Literal["development-example-g1"]
    scope: Literal["DEVELOPMENT_EXAMPLE"]
    scope_key: str
    example_id: str
    request_sha256: str
    manifest_sha256: str
    inputs: tuple[ArtifactDigest, ...]
    outputs: tuple[ArtifactDigest, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-development-example-g1-receipt-v1":
            raise ValueError("development receipt schema 非法")
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("development receipt kind 非法")
        if self.stage != "development-example-g1" or self.scope != "DEVELOPMENT_EXAMPLE":
            raise ValueError("development receipt stage/scope 非法")
        _require_hex64(self.scope_key)
        _require_example_id(self.example_id)
        _require_hex64(self.request_sha256)
        _require_hex64(self.manifest_sha256)
        object.__setattr__(self, "inputs", _rebuild_digests(self.inputs))
        object.__setattr__(self, "outputs", _rebuild_digests(self.outputs))


@dataclass(frozen=True)
class DevelopmentExampleReleaseHandle:
    root: Path
    manifest_path: Path

    def __post_init__(self) -> None:
        root = self.root.resolve(strict=True)
        manifest = self.manifest_path.resolve(strict=True)
        if manifest != root / "manifest.json":
            raise ValueError("development release handle 非法")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "manifest_path", manifest)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleG1Release:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    release: DevelopmentExampleReleaseHandle
    manifest: DevelopmentExampleG1ManifestV1
    manifest_sha256: str
    request: DevelopmentExampleG1RequestV1
    request_sha256: str
    receipt: DevelopmentExampleG1ReceiptV1
    receipt_sha256: str
    artifact_paths: tuple[tuple[str, Path], ...]

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development kind 非法")
        if type(self.release) is not DevelopmentExampleReleaseHandle:
            raise ValueError("verified development handle 非法")
        if type(self.manifest) is not DevelopmentExampleG1ManifestV1:
            raise ValueError("verified development manifest 非法")
        if type(self.request) is not DevelopmentExampleG1RequestV1:
            raise ValueError("verified development request 非法")
        if type(self.receipt) is not DevelopmentExampleG1ReceiptV1:
            raise ValueError("verified development receipt 非法")
        for value in (self.manifest_sha256, self.request_sha256, self.receipt_sha256):
            _require_hex64(value)
        if type(self.artifact_paths) is not tuple:
            raise ValueError("verified development paths 非法")
        contract_root = self.release.root / "contract"
        rebuilt = tuple(
            (name, path.resolve(strict=True)) for name, path in self.artifact_paths
        )
        if rebuilt != tuple(sorted(rebuilt, key=lambda item: item[0])):
            raise ValueError("verified development paths 必须排序")
        if tuple(name for name, _ in rebuilt) != tuple(
            sorted(spec.path for spec in _ARTIFACT_REGISTRY)
        ):
            raise ValueError("verified development paths 闭包非法")
        if any(path.parent != contract_root for _, path in rebuilt):
            raise ValueError("verified development paths 越界")
        object.__setattr__(self, "artifact_paths", rebuilt)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleSnapshotArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    request: SnapshotRequestRecordV1
    request_sha256: str
    manifest: SnapshotManifestV1
    manifest_sha256: str
    snapshot_receipt_sha256: str
    session_calendar_path: Path
    staging_paths: tuple[Path, ...]

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development snapshot kind 非法")
        _require_example_id(self.example_id)
        for value in (
            self.request_sha256,
            self.manifest_sha256,
            self.snapshot_receipt_sha256,
        ):
            _require_hex64(value)
        if type(self.request) is not SnapshotRequestRecordV1:
            raise ValueError("verified development snapshot request 非法")
        if type(self.manifest) is not SnapshotManifestV1:
            raise ValueError("verified development snapshot manifest 非法")
        root = self.root.resolve(strict=True)
        calendar = self.session_calendar_path.resolve(strict=True)
        staging = tuple(path.resolve(strict=True) for path in self.staging_paths)
        if calendar != root / "session_calendar.parquet":
            raise ValueError("verified development snapshot calendar 非法")
        if staging != tuple(sorted(staging)) or any(
            path.parent != root / "staging" for path in staging
        ):
            raise ValueError("verified development snapshot staging 非法")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "session_calendar_path", calendar)
        object.__setattr__(self, "staging_paths", staging)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleProviderArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    qlib_dir: Path
    manifest: ProviderManifestV1
    manifest_sha256: str
    provider_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development provider kind 非法")
        _require_example_id(self.example_id)
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.provider_receipt_sha256)
        if type(self.manifest) is not ProviderManifestV1:
            raise ValueError("verified development provider manifest 非法")
        root = self.root.resolve(strict=True)
        qlib_dir = self.qlib_dir.resolve(strict=True)
        _require_development_root_name(root)
        if qlib_dir != root / "provider":
            raise ValueError("verified development provider paths 非法")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "qlib_dir", qlib_dir)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleProviderValidationArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    details: pl.DataFrame
    summary: ProviderValidationSummaryV1
    summary_sha256: str
    validation_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development provider validation kind 非法")
        _require_example_id(self.example_id)
        if not isinstance(self.details, pl.DataFrame):
            raise ValueError("verified development provider validation details 非法")
        if type(self.summary) is not ProviderValidationSummaryV1:
            raise ValueError("verified development provider validation summary 非法")
        _require_hex64(self.summary_sha256)
        _require_hex64(self.validation_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleExperimentIdentity:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    manifest: ExperimentIdentityManifestV1
    manifest_sha256: str
    experiment_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development experiment kind 非法")
        _require_example_id(self.example_id)
        if type(self.manifest) is not ExperimentIdentityManifestV1:
            raise ValueError("verified development experiment manifest 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.experiment_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleFoldPlanArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    manifest: FoldPlanManifestV1
    manifest_sha256: str
    folds_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development fold plan kind 非法")
        _require_example_id(self.example_id)
        if type(self.manifest) is not FoldPlanManifestV1:
            raise ValueError("verified development fold plan manifest 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.folds_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleFeatureArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    manifest: FeatureManifestV1
    manifest_sha256: str
    feature_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development feature kind 非法")
        _require_example_id(self.example_id)
        if type(self.manifest) is not FeatureManifestV1:
            raise ValueError("verified development feature manifest 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.feature_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleAlignmentArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    manifest: AlignmentManifestV1
    manifest_sha256: str
    alignment_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development alignment kind 非法")
        _require_example_id(self.example_id)
        if type(self.manifest) is not AlignmentManifestV1:
            raise ValueError("verified development alignment manifest 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.alignment_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleModelArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    manifest: ModelManifestV1
    manifest_sha256: str
    model_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development model kind 非法")
        _require_example_id(self.example_id)
        if type(self.manifest) is not ModelManifestV1:
            raise ValueError("verified development model manifest 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.model_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExamplePredictionArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    predictions: pl.DataFrame
    manifest: PredictionManifestV1
    manifest_sha256: str
    prediction_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development prediction kind 非法")
        _require_example_id(self.example_id)
        if (
            not isinstance(self.predictions, pl.DataFrame)
            or type(self.manifest) is not PredictionManifestV1
        ):
            raise ValueError("verified development prediction artifact 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.prediction_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleTargetArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    targets: pl.DataFrame
    target_daily: pl.DataFrame
    manifest: TargetManifestV1
    manifest_sha256: str
    target_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development target kind 非法")
        _require_example_id(self.example_id)
        if (
            not isinstance(self.targets, pl.DataFrame)
            or not isinstance(self.target_daily, pl.DataFrame)
            or type(self.manifest) is not TargetManifestV1
        ):
            raise ValueError("verified development target artifact 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.target_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleAShareMarketFacts:
    """Read-only G1 market facts carrying an unmistakable development identity."""

    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    identity: AShareMarketFactsIdentityV1
    instruments: pl.DataFrame
    calendar: pl.DataFrame
    bars: pl.DataFrame
    limits: pl.DataFrame
    suspensions: pl.DataFrame
    corporate_actions: pl.DataFrame
    corporate_action_reconciliation: pl.DataFrame
    benchmark_bars: pl.DataFrame

    def __post_init__(self) -> None:
        from quant.backtest.a_share_execution import AShareMarketFactsIdentityV1

        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development market facts kind invalid")
        _require_example_id(self.example_id)
        frames = (
            self.instruments,
            self.calendar,
            self.bars,
            self.limits,
            self.suspensions,
            self.corporate_actions,
            self.corporate_action_reconciliation,
            self.benchmark_bars,
        )
        if type(self.identity) is not AShareMarketFactsIdentityV1 or any(
            not isinstance(frame, pl.DataFrame) for frame in frames
        ):
            raise ValueError("verified development market facts invalid")


@dataclass(frozen=True)
class VerifiedDevelopmentExampleBacktestPlanArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    scheduled_targets: pl.DataFrame
    manifest: BacktestPlanManifestV1
    manifest_sha256: str
    plan_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development backtest plan kind invalid")
        _require_example_id(self.example_id)
        if (
            not isinstance(self.scheduled_targets, pl.DataFrame)
            or type(self.manifest) is not BacktestPlanManifestV1
        ):
            raise ValueError("verified development backtest plan artifact invalid")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.plan_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleEvaluationArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    daily: pl.DataFrame
    metrics: EvaluationMetricsV1
    manifest: EvaluationManifestV1
    manifest_sha256: str
    evaluation_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development evaluation kind 非法")
        _require_example_id(self.example_id)
        if (
            not isinstance(self.daily, pl.DataFrame)
            or type(self.metrics) is not EvaluationMetricsV1
            or type(self.manifest) is not EvaluationManifestV1
        ):
            raise ValueError("verified development evaluation artifact 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.evaluation_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleResearchSummaryArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    daily: pl.DataFrame
    fold_metrics: pl.DataFrame
    metrics: ResearchSummaryMetricsV1
    manifest: ResearchSummaryManifestV1
    manifest_sha256: str
    summary_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development research summary kind 非法")
        _require_example_id(self.example_id)
        if (
            not isinstance(self.daily, pl.DataFrame)
            or not isinstance(self.fold_metrics, pl.DataFrame)
            or type(self.metrics) is not ResearchSummaryMetricsV1
            or type(self.manifest) is not ResearchSummaryManifestV1
        ):
            raise ValueError("verified development research summary artifact 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.summary_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleLabelArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    labels: pl.DataFrame
    diagnostics: pl.DataFrame
    manifest: LabelArtifactManifest
    manifest_sha256: str
    label_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development label kind 非法")
        _require_example_id(self.example_id)
        if not isinstance(self.labels, pl.DataFrame) or not isinstance(
            self.diagnostics, pl.DataFrame
        ):
            raise ValueError("verified development label frames 非法")
        if type(self.manifest) is not LabelArtifactManifest:
            raise ValueError("verified development label manifest 非法")
        _require_hex64(self.manifest_sha256)
        _require_hex64(self.label_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


@dataclass(frozen=True)
class VerifiedDevelopmentExampleLabelReconciliationArtifact:
    release_kind: Literal["development_example"]
    formal_gate_eligible: Literal[False]
    example_id: str
    root: Path
    details: pl.DataFrame
    summary: LabelReconciliationSummaryV1
    summary_sha256: str
    reconciliation_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.release_kind != _KIND or self.formal_gate_eligible is not False:
            raise ValueError("verified development reconciliation kind 非法")
        _require_example_id(self.example_id)
        if not isinstance(self.details, pl.DataFrame):
            raise ValueError("verified development reconciliation details 非法")
        if type(self.summary) is not LabelReconciliationSummaryV1:
            raise ValueError("verified development reconciliation summary 非法")
        _require_hex64(self.summary_sha256)
        _require_hex64(self.reconciliation_receipt_sha256)
        root = self.root.resolve(strict=True)
        _require_development_root_name(root)
        object.__setattr__(self, "root", root)


def build_development_example_g1_release(
    *, output_root: Path,
) -> VerifiedDevelopmentExampleG1Release:
    """Build and strictly re-read one deterministic, network-free A-share package."""
    try:
        _require_development_root_name(output_root)
        _require_empty_directory(output_root)
        contract_root = output_root / "contract"
        contract_root.mkdir()
        fixture = _fixture_spec()
        fixture_bytes = _canonical_bytes(fixture)
        _write_exclusive(output_root / "fixture-spec.json", fixture_bytes)
        frames = _fixture_frames()
        json_payloads = {
            "quality.json": _canonical_bytes(_quality_payload()),
            "cross_source_reconciliation.json": _canonical_bytes(
                _summary_payload()
            ),
        }
        entries: list[DevelopmentG1ArtifactEntryV1] = []
        for spec in _ARTIFACT_REGISTRY:
            path = contract_root / spec.path
            if spec.kind in {"quality", "summary"}:
                raw = json_payloads[spec.path]
                _write_exclusive(path, raw)
                entries.append(_development_json_entry(
                    path_name=spec.path,
                    payload=raw,
                    schema_name={
                        "summary": "DevelopmentCrossSourceSummaryV1",
                        "quality": "DevelopmentG1QualityV1",
                    }[spec.kind],
                ))
                continue
            frame = frames[spec.path]
            raw = _frame_to_parquet_bytes(frame)
            _write_exclusive(path, raw)
            entries.append(_development_parquet_entry(
                path_name=spec.path,
                raw=raw,
                frame=frame,
                content_sha256=clean_table_content_sha256(
                    table_name=spec.logical_table, frame=frame
                ),
                schema_name=(
                    "DevelopmentCrossSourceReconciliationDetailV1"
                    if spec.kind == "detail"
                    else spec.schema_name
                ),
                key_columns=spec.key_columns,
            ))
        ordered_entries = tuple(sorted(entries, key=lambda item: item.path))
        input_sha = hashlib.sha256(fixture_bytes).hexdigest()
        output_sha = _sha256_json([asdict(item) for item in ordered_entries])
        contract_release_id = _sha256_json({
            "schema_version": "m3-development-example-g1-contract-identity-v1",
            "fixture_sha256": input_sha,
            "output_summary_sha256": output_sha,
        })
        example_id = f"development-example-{contract_release_id}"
        manifest = DevelopmentExampleG1ManifestV1(
            schema_version="m3-development-example-g1-manifest-v1",
            release_kind=_KIND,
            formal_gate_eligible=False,
            example_id=example_id,
            fixture_version=_FIXTURE_VERSION,
            contract_release_id=contract_release_id,
            source=_SOURCE,
            universe=_UNIVERSE,
            signal_start=_D1,
            signal_end=_SIGNAL_END,
            history_start=_D1,
            history_end=_D3,
            input_summary_sha256=input_sha,
            output_summary_sha256=output_sha,
            files=ordered_entries,
        )
        manifest_bytes = _canonical_bytes(asdict(manifest))
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        _write_exclusive(output_root / "manifest.json", manifest_bytes)
        request_key = _sha256_json({
            "schema_version": "m3-development-example-g1-request-identity-v1",
            "fixture_version": _FIXTURE_VERSION,
            "input_summary_sha256": input_sha,
        })
        request = DevelopmentExampleG1RequestV1(
            schema_version="m3-development-example-g1-request-v1",
            release_kind=_KIND,
            formal_gate_eligible=False,
            example_request_key=request_key,
            example_id=example_id,
            fixture_version=_FIXTURE_VERSION,
            manifest_sha256=manifest_sha,
            history_start=_D1,
            history_end=_D3,
        )
        request_bytes = _canonical_bytes(asdict(request))
        request_sha = hashlib.sha256(request_bytes).hexdigest()
        _write_exclusive(output_root / "request.json", request_bytes)
        inputs = (_digest(output_root, output_root / "fixture-spec.json"),)
        output_paths = (
            output_root / "manifest.json",
            output_root / "request.json",
            *(contract_root / item.path for item in ordered_entries),
        )
        outputs = tuple(sorted(
            (_digest(output_root, path) for path in output_paths),
            key=lambda item: (item.root_alias, item.relative_path),
        ))
        receipt = DevelopmentExampleG1ReceiptV1(
            schema_version="m3-development-example-g1-receipt-v1",
            release_kind=_KIND,
            formal_gate_eligible=False,
            stage="development-example-g1",
            scope="DEVELOPMENT_EXAMPLE",
            scope_key=request_key,
            example_id=example_id,
            request_sha256=request_sha,
            manifest_sha256=manifest_sha,
            inputs=inputs,
            outputs=outputs,
        )
        _write_exclusive(output_root / "receipt.json", _canonical_bytes(asdict(receipt)))
        return verify_development_example_g1_release(root=output_root)
    except M3DevelopmentExampleError:
        raise
    except Exception:
        raise M3DevelopmentExampleError("DEVELOPMENT_EXAMPLE_OUTPUT_INVALID") from None


def compute_development_snapshot_request_key(
    *, release: VerifiedDevelopmentExampleG1Release,
    snapshot_config_sha256: str,
    code_version: str,
) -> str:
    """Compute a domain-separated key that formal G2A will never accept."""
    if type(release) is not VerifiedDevelopmentExampleG1Release:
        raise M3DevelopmentExampleError("DEVELOPMENT_EXAMPLE_INPUT_INVALID")
    return compute_development_snapshot_request_key_from_parts(
        development_request_key=release.request.example_request_key,
        contract_release_id=release.manifest.contract_release_id,
        manifest_sha256=release.manifest_sha256,
        snapshot_config_sha256=snapshot_config_sha256,
        code_version=code_version,
    )


def derive_development_example_m3_config(
    *, base: LoadedM3Config,
) -> LoadedM3Config:
    """Derive a strict in-memory config without duplicating the 144-field TOML SSOT."""
    if type(base) is not LoadedM3Config:
        raise M3DevelopmentExampleError("DEVELOPMENT_EXAMPLE_INPUT_INVALID")
    document = _thaw(base.document)
    meta = cast(dict[str, object], document["meta"])
    data = cast(dict[str, object], document["data"])
    features = cast(dict[str, object], document["features"])
    portfolio = cast(dict[str, object], document["portfolio"])
    tracking = cast(dict[str, object], document["tracking"])
    meta["purpose"] = "M3 DEVELOPMENT EXAMPLE ONLY; NOT FORMAL GATE EVIDENCE"
    meta["enabled"] = False
    data["start_date"] = _D1
    data["end_date"] = _SIGNAL_END
    data["minimum_train_sessions"] = 2
    data["minimum_cross_section_symbols"] = 2
    # The deliberately tiny fixture retains one unscorable eligible row.  Keep
    # the development-only coverage gate meaningful without inheriting the
    # production threshold that assumes a broad cross-section.
    features["minimum_scorable_coverage"] = 0.5
    portfolio["top_k"] = 2
    walk_forward = cast(dict[str, object], document["walk_forward"])
    walk_forward["train_sessions"] = 2
    walk_forward["validation_sessions"] = 2
    walk_forward["test_sessions"] = 2
    walk_forward["step_sessions"] = 2
    walk_forward["embargo_sessions"] = 10
    tracking["experiment_name"] = "m3_development_example_only"
    tracking["tracking_uri"] = (
        "sqlite:///artifacts/research/m3-development-example/mlflow.db"
    )
    tracking["artifact_root"] = "artifacts/research/m3-development-example"
    try:
        return _loaded_from_normalized(_validate_and_normalize(document))
    except Exception:
        raise M3DevelopmentExampleError("DEVELOPMENT_EXAMPLE_INPUT_INVALID") from None


def compute_development_snapshot_request_key_from_parts(
    *, development_request_key: str, contract_release_id: str,
    manifest_sha256: str, snapshot_config_sha256: str, code_version: str,
) -> str:
    """Single SSOT for the development-only snapshot request identity."""
    for value in (
        development_request_key,
        contract_release_id,
        manifest_sha256,
        snapshot_config_sha256,
    ):
        _require_hex64(value)
    if type(code_version) is not str or not code_version.startswith(
        "development-example/"
    ):
        raise M3DevelopmentExampleError("DEVELOPMENT_EXAMPLE_INPUT_INVALID")
    return _sha256_json([
        "m3-development-example-snapshot-request-v1",
        development_request_key,
        contract_release_id,
        manifest_sha256,
        snapshot_config_sha256,
        code_version,
    ])


def compute_development_provider_key(
    *, example_id: str, snapshot_id: str, snapshot_manifest_sha256: str,
    provider_config_sha256: str, dump_tool_sha256: str, qlib_version: str,
    provider_runtime_fingerprint_sha256: str, code_version: str,
) -> str:
    """Domain-separated identity for a development-only Provider artifact."""
    _require_example_id(example_id)
    for value in (
        snapshot_id, snapshot_manifest_sha256, provider_config_sha256,
        dump_tool_sha256, provider_runtime_fingerprint_sha256,
    ):
        _require_hex64(value)
    if qlib_version != "0.9.7":
        raise ValueError("development provider qlib version 非法")
    if type(code_version) is not str or not code_version.startswith(
        "development-example/"
    ):
        raise ValueError("development provider code version 非法")
    return _sha256_json([
        "m3-development-example-provider-key-v1",
        example_id,
        snapshot_id,
        snapshot_manifest_sha256,
        provider_config_sha256,
        dump_tool_sha256,
        qlib_version,
        provider_runtime_fingerprint_sha256,
        code_version,
    ])


def compute_development_provider_validation_key(
    *, example_id: str, provider_key: str, provider_receipt_sha256: str,
    provider_validation_config_sha256: str,
    provider_runtime_fingerprint_sha256: str, code_version: str,
) -> str:
    """Domain-separated identity for development-only Provider validation."""
    _require_example_id(example_id)
    for value in (
        provider_key,
        provider_receipt_sha256,
        provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256,
    ):
        _require_hex64(value)
    if type(code_version) is not str or not code_version.startswith(
        "development-example/"
    ):
        raise ValueError("development provider validation code version 非法")
    return _sha256_json([
        "m3-development-example-provider-validation-key-v1",
        example_id,
        provider_key,
        provider_receipt_sha256,
        provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256,
        code_version,
    ])


def compute_development_experiment_key(
    *, example_id: str, snapshot_id: str, provider_receipt_sha256: str,
    scientific_config_sha256: str, code_version: str,
    dependency_fingerprint_sha256: str,
) -> str:
    """Domain-separated identity for a development-only experiment."""
    _require_example_id(example_id)
    for value in (
        snapshot_id, provider_receipt_sha256, scientific_config_sha256,
        dependency_fingerprint_sha256,
    ):
        _require_hex64(value)
    if type(code_version) is not str or not code_version.startswith(
        "development-example/"
    ):
        raise ValueError("development experiment code version 非法")
    return _sha256_json([
        "m3-development-example-experiment-key-v1", example_id, snapshot_id,
        provider_receipt_sha256, scientific_config_sha256, code_version,
        dependency_fingerprint_sha256,
    ])


def compute_development_label_reconciliation_key(
    *, example_id: str, experiment_key: str, horizon: int,
    provider_validation_receipt_sha256: str,
    label_manifest_sha256: str,
    label_reconciliation_config_sha256: str,
    dependency_fingerprint_sha256: str, code_version: str,
) -> str:
    """Domain-separated identity for development-only label reconciliation."""
    _require_example_id(example_id)
    for value in (
        experiment_key, provider_validation_receipt_sha256,
        label_manifest_sha256, label_reconciliation_config_sha256,
        dependency_fingerprint_sha256,
    ):
        _require_hex64(value)
    if type(horizon) is not int or horizon not in {5, 10}:
        raise ValueError("development reconciliation horizon 非法")
    if type(code_version) is not str or not code_version.startswith(
        "development-example/"
    ):
        raise ValueError("development reconciliation code version 非法")
    return _sha256_json([
        "m3-development-example-label-reconciliation-key-v1", example_id,
        experiment_key, horizon, provider_validation_receipt_sha256,
        label_manifest_sha256, label_reconciliation_config_sha256,
        dependency_fingerprint_sha256, code_version,
    ])


def verify_development_example_g1_release(
    *, root: Path,
) -> VerifiedDevelopmentExampleG1Release:
    """Verify the complete development package without creating formal G1 types."""
    try:
        _require_development_root_name(root)
        _require_real_directory(root)
        expected_root = {
            "contract", "fixture-spec.json", "manifest.json", "request.json",
            "receipt.json",
        }
        if {entry.name for entry in os.scandir(root)} != expected_root:
            raise ValueError
        contract_root = root / "contract"
        _require_real_directory(contract_root)
        if {entry.name for entry in os.scandir(contract_root)} != {
            spec.path for spec in _ARTIFACT_REGISTRY
        }:
            raise ValueError
        fixture_raw = _read_file(root / "fixture-spec.json")
        if _strict_json(fixture_raw) != _fixture_spec():
            raise ValueError
        manifest_raw = _read_file(root / "manifest.json")
        manifest = _parse_manifest(manifest_raw)
        request_raw = _read_file(root / "request.json")
        request = _parse_request(request_raw)
        receipt_raw = _read_file(root / "receipt.json")
        receipt = _parse_receipt(receipt_raw)
        manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
        request_sha = hashlib.sha256(request_raw).hexdigest()
        if request.manifest_sha256 != manifest_sha:
            raise ValueError
        if request.example_id != manifest.example_id:
            raise ValueError
        if receipt.scope_key != request.example_request_key:
            raise ValueError
        if (
            receipt.example_id != manifest.example_id
            or receipt.manifest_sha256 != manifest_sha
            or receipt.request_sha256 != request_sha
        ):
            raise ValueError
        recomputed: list[DevelopmentG1ArtifactEntryV1] = []
        artifact_paths: list[tuple[str, Path]] = []
        frames: dict[str, pl.DataFrame] = {}
        for entry in manifest.files:
            spec = _ARTIFACT_BY_PATH[entry.path]
            path = contract_root / entry.path
            raw = _read_file(path)
            if spec.kind in {"quality", "summary"}:
                payload = _strict_json(raw)
                if payload.get("release_kind") != _KIND:
                    raise ValueError
                expected_payload = (
                    _quality_payload() if spec.kind == "quality" else _summary_payload()
                )
                if payload != expected_payload:
                    raise ValueError
                current = _development_json_entry(
                    path_name=entry.path,
                    payload=raw,
                    schema_name=entry.schema_name,
                )
            else:
                frame = _read_development_parquet(path, spec.path)
                frames[spec.path] = frame
                current = _development_parquet_entry(
                    path_name=entry.path,
                    raw=raw,
                    frame=frame,
                    content_sha256=clean_table_content_sha256(
                        table_name=spec.logical_table, frame=frame
                    ),
                    schema_name=entry.schema_name,
                    key_columns=spec.key_columns,
                )
            if current != entry:
                raise ValueError
            recomputed.append(current)
            artifact_paths.append((entry.path, path.resolve(strict=True)))
        _verify_fixture_semantics(frames)
        if _sha256_json([asdict(item) for item in recomputed]) != (
            manifest.output_summary_sha256
        ):
            raise ValueError
        if hashlib.sha256(fixture_raw).hexdigest() != manifest.input_summary_sha256:
            raise ValueError
        expected_contract_id = _sha256_json({
            "schema_version": "m3-development-example-g1-contract-identity-v1",
            "fixture_sha256": manifest.input_summary_sha256,
            "output_summary_sha256": manifest.output_summary_sha256,
        })
        if manifest.contract_release_id != expected_contract_id:
            raise ValueError
        if manifest.example_id != f"development-example-{expected_contract_id}":
            raise ValueError
        expected_request_key = _sha256_json({
            "schema_version": "m3-development-example-g1-request-identity-v1",
            "fixture_version": _FIXTURE_VERSION,
            "input_summary_sha256": manifest.input_summary_sha256,
        })
        if request.example_request_key != expected_request_key:
            raise ValueError
        expected_inputs = (_digest(root, root / "fixture-spec.json"),)
        expected_outputs = tuple(sorted(
            (
                _digest(root, root / "manifest.json"),
                _digest(root, root / "request.json"),
                *(_digest(root, path) for _, path in artifact_paths),
            ),
            key=lambda item: (item.root_alias, item.relative_path),
        ))
        if receipt.inputs != expected_inputs or receipt.outputs != expected_outputs:
            raise ValueError
        return VerifiedDevelopmentExampleG1Release(
            release_kind=_KIND,
            formal_gate_eligible=False,
            release=DevelopmentExampleReleaseHandle(
                root=root, manifest_path=root / "manifest.json"
            ),
            manifest=manifest,
            manifest_sha256=manifest_sha,
            request=request,
            request_sha256=request_sha,
            receipt=receipt,
            receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
            artifact_paths=tuple(sorted(artifact_paths)),
        )
    except M3DevelopmentExampleError:
        raise
    except Exception:
        raise M3DevelopmentExampleError("DEVELOPMENT_EXAMPLE_ARTIFACT_INVALID") from None


def _fixture_spec() -> dict[str, object]:
    return {
        "schema_version": "m3-a-share-development-example-spec-v1",
        "release_kind": _KIND,
        "formal_gate_eligible": False,
        "fixture_version": _FIXTURE_VERSION,
        "symbols": ["000001.SZ", "000002.SZ", "600000.SH"],
        "sessions": [day.isoformat() for day in _SESSIONS],
        "boundaries": [
            "adjustment_and_cash_dividend_on_2026-01-06",
            "full_day_suspension_on_2026-01-06",
            "membership_and_delist_lifecycle",
        ],
    }


def _quality_payload() -> dict[str, object]:
    return {
        "schema_version": "m3-development-example-quality-v1",
        "release_kind": _KIND,
        "formal_gate_eligible": False,
        "passed": True,
        "checks": [
            "cross_table_semantics",
            "physical_hash",
            "receipt_closure",
            "schema",
        ],
    }


def _summary_payload() -> dict[str, object]:
    return {
        "schema_version": "m3-development-example-input-output-summary-v1",
        "release_kind": _KIND,
        "formal_gate_eligible": False,
        "symbol_count": 3,
        "session_count": len(_SESSIONS),
        "comparison_count": 15,
        "boundaries": _fixture_spec()["boundaries"],
    }


def _fixture_frames() -> dict[str, pl.DataFrame]:
    ratio = 10.0 / 9.9
    symbols = ("000001.SZ", "000002.SZ", "600000.SH")
    membership = _validated(UniverseMembershipSchema, [
        {"universe": _UNIVERSE, "symbol": "000001.SZ", "effective_from": _D1, "effective_to": None},
        {"universe": _UNIVERSE, "symbol": "000002.SZ", "effective_from": _D1, "effective_to": _D3},
        {"universe": _UNIVERSE, "symbol": "600000.SH", "effective_from": _D1, "effective_to": None},
    ], ["universe", "symbol", "effective_from"])
    eligible_rows = [
        {"as_of": day, "symbol": symbol}
        for day in _SESSIONS
        for symbol in symbols
        if not (day == _D2 and symbol == "000001.SZ")
    ]
    eligible = pl.DataFrame(eligible_rows).with_columns(
        pl.col("as_of").cast(pl.Date), pl.col("symbol").cast(pl.Utf8)
    ).sort(["as_of", "symbol"])
    bar_rows: list[dict[str, object]] = []
    for symbol in symbols:
        for day in _SESSIONS:
            if symbol == "000001.SZ" and day == _D2:
                continue
            base = 8.0 if symbol == "000001.SZ" else (6.0 if symbol == "000002.SZ" else 10.0)
            factor = ratio if symbol == "600000.SH" and day >= _D2 else 1.0
            bar_rows.append({
                "symbol": symbol, "trade_date": day, "open": base,
                "high": base + 0.2, "low": base - 0.2, "close": base,
                "volume": 1000.0, "amount": base * 1000.0,
                "adj_factor": factor, "source": _SOURCE,
            })
    bars = _validated(Bar1dSchema, bar_rows, ["symbol", "trade_date", "source"])
    factors = _validated(AdjustmentFactorSchema, [
        {
            "symbol": row["symbol"], "effective_date": row["trade_date"],
            "adj_factor": row["adj_factor"], "source": _SOURCE,
        }
        for row in bar_rows
    ], ["symbol", "effective_date", "source"])
    matches = _validated(AdjustmentFactorMatchSchema, [
        {
            "symbol": row["symbol"], "trade_date": row["trade_date"],
            "source": _SOURCE, "adj_factor": row["adj_factor"],
            "bar_request_id": _HEX_A,
            "bar_stable_response_sha256": _HEX_B,
            "factor_request_id": _HEX_B,
            "factor_stable_response_sha256": _HEX_C,
        }
        for row in bar_rows
    ], ["symbol", "trade_date", "source"])
    benchmark = _validated(BenchmarkBar1dSchema, [
        {
            "benchmark": "510300.SH", "trade_date": day, "open": 4.0,
            "high": 4.1, "low": 3.9, "close": 4.0,
            "source": _SOURCE, "source_snapshot_id": _HEX_A,
        }
        for day in _SESSIONS
    ], ["benchmark", "trade_date", "source"])
    suspensions = _validated(Suspension1dSchema, [{
        "symbol": "000001.SZ", "trade_date": _D2,
        "suspension_scope": "FULL_DAY", "suspension_detail": None,
        "source": _SOURCE, "source_snapshot_id": _HEX_A,
    }], ["symbol", "trade_date", "source"])
    calendars = _validated(TradeCalendarSchema, [
        {
            "market": market, "date": day, "is_open": True,
            "is_connect_open": False, "is_half_day": False,
        }
        for day in _SESSIONS for market in ("SH", "SZ")
    ], ["market", "date"])
    instruments = _validated(InstrumentSchema, [
        {
            "symbol": symbol, "market": symbol[-2:], "name": f"DEV {symbol}",
            "instrument_type": "STOCK", "currency": "CNY",
            "list_date": dt.date(2020, 1, 2),
            "delist_date": _D3 if symbol == "000002.SZ" else None,
            "board_lot": 100,
            "status": "DELISTED" if symbol == "000002.SZ" else "LISTED",
        }
        for symbol in symbols
    ], ["symbol"])
    observations = _validated(IndexConstituentObservationSchema, [
        {
            "universe": _UNIVERSE, "observation_date": _D1, "symbol": symbol,
            "weight": weight, "source": _SOURCE, "source_snapshot_id": _HEX_A,
        }
        for symbol, weight in zip(symbols, (30.0, 30.0, 40.0), strict=True)
    ], ["universe", "observation_date", "symbol", "source"])
    limits = _validated(PriceLimit1dSchema, [
        {
            "symbol": row["symbol"], "trade_date": row["trade_date"],
            "pre_close": row["close"], "has_price_limit": True,
            "up_limit": cast(float, row["close"]) * 1.1,
            "down_limit": cast(float, row["close"]) * 0.9,
            "source": _SOURCE, "source_snapshot_id": _HEX_A,
        }
        for row in bar_rows
    ], ["symbol", "trade_date", "source"])
    event_id = "dev-dividend-600000-20260106"
    ledger = _validated(CorporateActionLedgerSchema, [{
        "event_id": event_id, "symbol": "600000.SH", "ex_date": _D2,
        "action_type": "DIVIDEND_DISTRIBUTION", "cash_per_share_gross": 0.1,
        "stock_ratio": 0.0, "rights_price": None, "rights_ratio": 0.0,
        "rights_actual_shares": None, "rights_pre_shares": None,
        "rights_post_shares": None, "rights_pre_circulating_shares": None,
        "rights_post_circulating_shares": None,
        "rights_mixed_change_proof_sha256": None, "record_date": _D1,
        "pay_date": _D3, "stock_list_date": None, "vendor_record_id": "dev-1",
        "source": _SOURCE, "source_snapshot_id": _HEX_A,
    }], ["event_id"])
    selection = _validated(CorporateActionSelectionEvidenceSchema, [{
        "economic_event_key_sha256": _HEX_A, "candidate_id": _HEX_B,
        "symbol": "600000.SH", "action_type": "DIVIDEND_DISTRIBUTION",
        "end_date": _D1, "record_date": _D1, "ex_date": _D2,
        "imp_ann_date": _D1, "ann_date": _D1,
        "cash_per_share_gross": 0.1, "stock_ratio": 0.0,
        "rights_price": None, "rights_ratio": 0.0,
        "rights_actual_shares": None, "rights_pre_shares": None,
        "rights_post_shares": None, "rights_pre_circulating_shares": None,
        "rights_post_circulating_shares": None,
        "rights_mixed_change_proof_sha256": None,
        "rights_mixed_change_proof_json": None, "pay_date": _D3,
        "stock_list_date": None, "vendor_record_id": "dev-1",
        "candidate_rank": 1, "candidate_count": 1, "raw_row_count": 1,
        "selected": True, "selection_reason": "SELECTED_LATEST",
        "source": _SOURCE, "source_request_id": _HEX_A,
        "source_snapshot_id": _HEX_A,
    }], ["candidate_id"])
    event_ids_json = _canonical_bytes([event_id]).decode("utf-8")
    ratio_terms_json = _canonical_bytes([0.0]).decode("utf-8")
    reconciliation = _validated(CorporateActionReconciliationSchema, [{
        "symbol": "600000.SH", "previous_factor_date": _D1,
        "effective_date": _D2, "previous_close_date": _D1,
        "previous_close": 10.0, "ex_reference_price": 9.9,
        "daily_request_id": _HEX_A, "daily_stable_response_sha256": _HEX_B,
        "event_count": 1, "event_ids_json": event_ids_json,
        "event_ids_sha256": hashlib.sha256(event_ids_json.encode()).hexdigest(),
        "stock_ratio_terms_json": ratio_terms_json,
        "stock_ratio_terms_sha256": hashlib.sha256(ratio_terms_json.encode()).hexdigest(),
        "cash_per_share_gross": 0.1, "stock_ratio": 0.0, "rights_ratio": 0.0,
        "rights_subscription_cash_per_share": 0.0,
        "declared_dividend_factor_ratio": ratio,
        "market_reference_factor_ratio": ratio, "actual_factor_ratio": ratio,
        "market_reference_relative_error": 0.0,
        "declared_dividend_relative_error": 0.0, "factor_ratio_rtol": 0.001,
        "status": "MATCHED_EVENT_DECLARED_FORMULA", "source": _SOURCE,
    }], ["symbol", "previous_factor_date", "effective_date"])
    detail_rows = []
    for symbol in symbols:
        for field in ("open", "high", "low", "close", "volume"):
            value = 1000.0 if field == "volume" else 10.0
            detail_rows.append({
                "symbol": symbol, "trade_date": _D1, "field": field,
                "primary_value": value, "reference_value": value,
                "abs_diff": 0.0, "relative_diff": 0.0, "tolerance": 0.0,
                "missing_side": "NONE", "matched": True,
            })
    detail = pl.DataFrame(detail_rows, schema=_DETAIL_DTYPES).select(
        list(_DETAIL_COLUMNS)
    ).sort(["symbol", "trade_date", "field"])
    return {
        "universe_membership.parquet": membership,
        "eligible_keys.parquet": eligible,
        "bar_1d.parquet": bars,
        "adjustment_factor.parquet": factors,
        "adjustment_factor_match.parquet": matches,
        "benchmark_bar_1d.parquet": benchmark,
        "suspension_1d.parquet": suspensions,
        "trade_calendar.parquet": calendars,
        "instrument.parquet": instruments,
        "index_constituent_observation.parquet": observations,
        "price_limit_1d.parquet": limits,
        "corporate_action_ledger.parquet": ledger,
        "corporate_action_selection_evidence.parquet": selection,
        "corporate_action_reconciliation.parquet": reconciliation,
        "cross_source_reconciliation.parquet": detail,
    }


def _verify_fixture_semantics(frames: Mapping[str, pl.DataFrame]) -> None:
    bars = frames["bar_1d.parquet"]
    factors = frames["adjustment_factor.parquet"]
    matches = frames["adjustment_factor_match.parquet"]
    eligible = frames["eligible_keys.parquet"]
    limits = frames["price_limit_1d.parquet"]
    suspensions = frames["suspension_1d.parquet"]
    calendars = frames["trade_calendar.parquet"]
    instruments = frames["instrument.parquet"]
    membership = frames["universe_membership.parquet"]
    ledger = frames["corporate_action_ledger.parquet"]
    evidence = frames["corporate_action_selection_evidence.parquet"]
    reconciliation = frames["corporate_action_reconciliation.parquet"]
    detail = frames["cross_source_reconciliation.parquet"]

    bar_keys = set(bars.select("symbol", "trade_date").iter_rows())
    factor_keys = set(
        factors.select("symbol", pl.col("effective_date").alias("trade_date")).iter_rows()
    )
    match_keys = set(matches.select("symbol", "trade_date").iter_rows())
    eligible_keys = set(eligible.select("symbol", "as_of").iter_rows())
    limit_keys = set(limits.select("symbol", "trade_date").iter_rows())
    full_day_keys = set(
        suspensions.filter(pl.col("suspension_scope") == "FULL_DAY")
        .select("symbol", "trade_date")
        .iter_rows()
    )
    if bar_keys != factor_keys or bar_keys != match_keys or bar_keys != limit_keys:
        raise ValueError("development bar/factor/limit closure 非法")
    if bar_keys & full_day_keys:
        raise ValueError("development full-day suspension 与 bar 冲突")
    if eligible_keys - full_day_keys != bar_keys:
        raise ValueError("development eligible/suspension closure 非法")
    sessions = calendars.filter(
        (pl.col("market") == "SH") & pl.col("is_open")
    ).get_column("date").to_list()
    if sessions != list(_SESSIONS):
        raise ValueError("development SH sessions 非法")
    emitted_counts = bars.group_by("symbol").len().sort("symbol")
    if emitted_counts.filter(pl.col("len") < 20).height:
        raise ValueError("development emitted session count 非法")
    if set(instruments.get_column("symbol")) != {
        "000001.SZ", "000002.SZ", "600000.SH"
    }:
        raise ValueError("development instruments 非法")
    lifecycle = instruments.filter(pl.col("symbol") == "000002.SZ")
    member = membership.filter(pl.col("symbol") == "000002.SZ")
    if lifecycle.item(0, "delist_date") != _D3 or member.item(0, "effective_to") != _D3:
        raise ValueError("development lifecycle closure 非法")
    if ledger.height != 1 or evidence.height != 1 or reconciliation.height != 1:
        raise ValueError("development corporate-action closure 非法")
    if (
        ledger.item(0, "symbol") != "600000.SH"
        or evidence.item(0, "symbol") != "600000.SH"
        or reconciliation.item(0, "symbol") != "600000.SH"
        or ledger.item(0, "ex_date") != _D2
        or reconciliation.item(0, "effective_date") != _D2
    ):
        raise ValueError("development corporate-action identity 非法")
    factor_rows = factors.filter(pl.col("symbol") == "600000.SH").sort(
        "effective_date"
    )
    actual_ratio = factor_rows.item(1, "adj_factor") / factor_rows.item(0, "adj_factor")
    if not math.isclose(
        actual_ratio,
        reconciliation.item(0, "actual_factor_ratio"),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("development adjustment reconciliation 非法")
    if detail.height != 15 or detail.get_column("symbol").n_unique() != 3:
        raise ValueError("development cross-source detail 非法")
    if not detail.get_column("matched").all():
        raise ValueError("development cross-source detail mismatch")


def _validated(schema: Any, rows: list[dict[str, object]], sort: list[str]) -> pl.DataFrame:
    return cast(pl.DataFrame, schema.validate(pl.DataFrame(rows))).sort(sort)


def _development_json_entry(
    *, path_name: str, payload: bytes, schema_name: str,
) -> DevelopmentG1ArtifactEntryV1:
    digest = hashlib.sha256(payload).hexdigest()
    return DevelopmentG1ArtifactEntryV1(
        path=path_name,
        sha256=digest,
        content_sha256=digest,
        size_bytes=len(payload),
        row_count=1,
        schema_name=schema_name,
        table_schema_version="development-v1",
        key_columns=(),
        min_key=None,
        max_key=None,
    )


def _development_parquet_entry(
    *, path_name: str, raw: bytes, frame: pl.DataFrame,
    content_sha256: str, schema_name: str, key_columns: tuple[str, ...],
) -> DevelopmentG1ArtifactEntryV1:
    min_key, max_key = _development_key_range(frame, key_columns)
    return DevelopmentG1ArtifactEntryV1(
        path=path_name,
        sha256=hashlib.sha256(raw).hexdigest(),
        content_sha256=content_sha256,
        size_bytes=len(raw),
        row_count=frame.height,
        schema_name=schema_name,
        table_schema_version="development-v1",
        key_columns=key_columns,
        min_key=min_key,
        max_key=max_key,
    )


def _development_key_range(
    frame: pl.DataFrame, key_columns: tuple[str, ...],
) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    if frame.is_empty():
        return None, None
    keys = []
    for row in frame.select(list(key_columns)).iter_rows():
        encoded = tuple(
            value.isoformat() if type(value) is dt.date else cast(str, value)
            for value in row
        )
        if any(type(value) is not str for value in encoded):
            raise ValueError("development key 非法")
        keys.append(encoded)
    return min(keys), max(keys)


def _validate_key_range(
    min_key: tuple[str, ...] | None,
    max_key: tuple[str, ...] | None,
    width: int,
) -> None:
    if type(min_key) is not tuple or type(max_key) is not tuple:
        raise ValueError("development key range 非法")
    if len(min_key) != width or len(max_key) != width:
        raise ValueError("development key range width 非法")
    if any(type(value) is not str for value in (*min_key, *max_key)):
        raise ValueError("development key range value 非法")
    if min_key > max_key:
        raise ValueError("development key range order 非法")


def _read_development_parquet(path: Path, name: str) -> pl.DataFrame:
    spec = _ARTIFACT_BY_PATH[name]
    if spec.kind == "detail":
        frame = pl.read_parquet(path)
        if list(frame.columns) != list(_DETAIL_COLUMNS):
            raise ValueError
        if any(frame.schema[key] != value for key, value in _DETAIL_DTYPES.items()):
            raise ValueError
        if frame.is_empty():
            raise ValueError
        return frame
    return _read_exact_parquet(path, spec)


def _parse_manifest(raw: bytes) -> DevelopmentExampleG1ManifestV1:
    payload = _strict_json(raw)
    expected = {
        "schema_version", "release_kind", "formal_gate_eligible", "example_id",
        "fixture_version", "contract_release_id", "source", "universe",
        "signal_start", "signal_end", "history_start", "history_end",
        "input_summary_sha256", "output_summary_sha256", "files",
    }
    if set(payload) != expected or type(payload["files"]) is not list:
        raise ValueError
    files_list: list[DevelopmentG1ArtifactEntryV1] = []
    for raw_item in payload["files"]:
        if type(raw_item) is not dict:
            raise ValueError
        item = dict(raw_item)
        item["key_columns"] = tuple(item["key_columns"])
        item["min_key"] = None if item["min_key"] is None else tuple(item["min_key"])
        item["max_key"] = None if item["max_key"] is None else tuple(item["max_key"])
        files_list.append(DevelopmentG1ArtifactEntryV1(**item))
    files = tuple(files_list)
    values = dict(payload)
    values["files"] = files
    for name in ("signal_start", "signal_end", "history_start", "history_end"):
        values[name] = dt.date.fromisoformat(values[name])
    manifest = DevelopmentExampleG1ManifestV1(**cast(Any, values))
    if _canonical_bytes(asdict(manifest)) != raw:
        raise ValueError
    return manifest


def _parse_request(raw: bytes) -> DevelopmentExampleG1RequestV1:
    payload = _strict_json(raw)
    expected = {
        "schema_version", "release_kind", "formal_gate_eligible",
        "example_request_key", "example_id", "fixture_version", "manifest_sha256",
        "history_start", "history_end",
    }
    if set(payload) != expected:
        raise ValueError
    payload["history_start"] = dt.date.fromisoformat(payload["history_start"])
    payload["history_end"] = dt.date.fromisoformat(payload["history_end"])
    request = DevelopmentExampleG1RequestV1(**cast(Any, payload))
    if _canonical_bytes(asdict(request)) != raw:
        raise ValueError
    return request


def _parse_receipt(raw: bytes) -> DevelopmentExampleG1ReceiptV1:
    payload = _strict_json(raw)
    expected = {
        "schema_version", "release_kind", "formal_gate_eligible", "stage", "scope",
        "scope_key", "example_id", "request_sha256", "manifest_sha256",
        "inputs", "outputs",
    }
    if set(payload) != expected:
        raise ValueError
    payload["inputs"] = tuple(ArtifactDigest(**item) for item in payload["inputs"])
    payload["outputs"] = tuple(ArtifactDigest(**item) for item in payload["outputs"])
    receipt = DevelopmentExampleG1ReceiptV1(**cast(Any, payload))
    if _canonical_bytes(asdict(receipt)) != raw:
        raise ValueError
    return receipt


def _digest(root: Path, path: Path) -> ArtifactDigest:
    raw = _read_file(path)
    return ArtifactDigest(
        root_alias="development_example",
        relative_path=path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix(),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _rebuild_digests(value: tuple[ArtifactDigest, ...]) -> tuple[ArtifactDigest, ...]:
    if type(value) is not tuple:
        raise ValueError("development receipt digests 非法")
    rebuilt = tuple(ArtifactDigest(
        root_alias=item.root_alias,
        relative_path=item.relative_path,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
    ) for item in value if type(item) is ArtifactDigest)
    if len(rebuilt) != len(value):
        raise ValueError("development receipt digest 类型非法")
    ordered = tuple(sorted(rebuilt, key=lambda item: (item.root_alias, item.relative_path)))
    if rebuilt != ordered or len({(x.root_alias, x.relative_path) for x in rebuilt}) != len(rebuilt):
        raise ValueError("development receipt digests 必须唯一排序")
    return rebuilt


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        default=lambda item: item.isoformat() if type(item) is dt.date else None,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _thaw(value: object) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _strict_json(raw: bytes) -> dict[str, Any]:
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError
            out[key] = value
        return out

    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=hook)
    if type(value) is not dict:
        raise ValueError
    return value


def _read_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError
    return path.read_bytes()


def _write_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _require_empty_directory(path: Path) -> None:
    _require_real_directory(path)
    if any(os.scandir(path)):
        raise M3DevelopmentExampleError("DEVELOPMENT_EXAMPLE_OUTPUT_INVALID")


def _require_development_root_name(path: Path) -> None:
    if not isinstance(path, Path):
        raise ValueError
    tokens = path.name.lower().replace("_", "-").split("-")
    if "development" not in tokens or "example" not in tokens:
        raise ValueError("development example root 必须显式标记信任域")


def _require_real_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError
    path.resolve(strict=True)


def _require_hex64(value: object) -> None:
    if type(value) is not str or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError("expected bare sha256")


def _require_example_id(value: object) -> None:
    if type(value) is not str or not value.startswith("development-example-"):
        raise ValueError("development example id 非法")
    _require_hex64(value.removeprefix("development-example-"))


def _is_finite_float(value: object) -> bool:
    return type(value) is float and math.isfinite(value)
