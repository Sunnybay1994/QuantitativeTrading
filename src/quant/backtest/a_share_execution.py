"""Pure A-share target-to-order and fee contracts for M3 G7D."""

from __future__ import annotations

import datetime as dt
import hmac
import hashlib
import io
import json
import os
import re
import secrets
import stat
import sys
import weakref
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, TypeAlias, cast, final

import polars as pl

from quant.domain import (
    AShareBoard,
    Bar1dSchema,
    BenchmarkBar1dSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    ExecutionRejectReason,
    InstrumentSchema,
    OpenExecutionStateSchema,
    OrderSide,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TargetWeightSchema,
    TradeCalendarSchema,
)
from quant.domain.enums import Currency, InstrumentType, Market
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_release import (
    G1ManifestV5,
    G1Release,
    VerifiedG1Release,
    verify_g1_release,
)
from quant.execution.contracts import (
    OrderIntent,
    PositionBalance,
    RuleDecision,
    SymbolMarketState,
    build_order_intent,
    build_position_balance,
    build_rule_decision,
    build_symbol_market_state,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    AShareCostPeriod,
    VerifiedBacktestPlanArtifact,
    VerifiedExperimentIdentity,
    VerifiedFoldPlanArtifact,
    VerifiedTargetArtifact,
)
from quant.research.m3.run_state import ArtifactDigest, select_artifact_root
from quant.backtest.a_share_plan import (
    BacktestPlanFreshVerificationContext,
    verify_backtest_plan_artifact,
)

if TYPE_CHECKING:
    from quant.research.m3.development_example import (
        VerifiedDevelopmentExampleAShareMarketFacts,
        VerifiedDevelopmentExampleBacktestPlanArtifact,
        VerifiedDevelopmentExampleG1Release,
    )

_RULE_VERSION: Literal["sse_szse_limit_order_quantity_v1"] = (
    "sse_szse_limit_order_quantity_v1"
)
_CENT = Decimal("0.01")
_PRICE_TICK = Decimal("0.01")
_FORMAL_HALF_PRICE_TICK = Decimal("0.005")
_FACT_FILES = (
    "bar_1d.parquet",
    "benchmark_bar_1d.parquet",
    "corporate_action_ledger.parquet",
    "corporate_action_reconciliation.parquet",
    "instrument.parquet",
    "price_limit_1d.parquet",
    "suspension_1d.parquet",
    "trade_calendar.parquet",
)
_PARTIAL_INTERVAL = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")
_FORMAL_FACTS_ERROR = "M3_A_SHARE_MARKET_FACTS_INVALID"
_FORMAL_EXECUTION_ERROR = "M3_A_SHARE_EXECUTION_INVALID"
_FORMAL_FACTS_SCHEMA: Literal["m3-formal-a-share-market-facts-v1"] = (
    "m3-formal-a-share-market-facts-v1"
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MATCHED_RECONCILIATION_STATUSES = frozenset(
    {
        "MATCHED_EVENT_DECLARED_FORMULA",
        "MATCHED_EVENT_MARKET_REFERENCE",
        "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE",
        "MATCHED_EVENT_BASIS_NORMALIZED_DECLARED_FORMULA",
    }
)
_FORMAL_FACT_SPECS: dict[
    str, tuple[str, Any, tuple[str, ...], tuple[str, ...]]
] = {
    "instrument.parquet": (
        "instrument", InstrumentSchema, ("symbol",), ("symbol",)
    ),
    "trade_calendar.parquet": (
        "trade_calendar", TradeCalendarSchema,
        ("market", "date"), ("market", "date"),
    ),
    "bar_1d.parquet": (
        "bar_1d", Bar1dSchema,
        ("symbol", "trade_date", "source"),
        ("symbol", "trade_date", "source"),
    ),
    "price_limit_1d.parquet": (
        "price_limit_1d", PriceLimit1dSchema,
        ("symbol", "trade_date", "source"),
        ("symbol", "trade_date", "source"),
    ),
    "suspension_1d.parquet": (
        "suspension_1d", Suspension1dSchema,
        ("symbol", "trade_date", "source"),
        ("symbol", "trade_date", "source"),
    ),
    "corporate_action_ledger.parquet": (
        "corporate_action_ledger", CorporateActionLedgerSchema,
        ("event_id",), ("symbol", "ex_date", "event_id"),
    ),
    "corporate_action_reconciliation.parquet": (
        "corporate_action_reconciliation", CorporateActionReconciliationSchema,
        ("symbol", "previous_factor_date", "effective_date"),
        ("symbol", "previous_factor_date", "effective_date"),
    ),
    "benchmark_bar_1d.parquet": (
        "benchmark_bar_1d", BenchmarkBar1dSchema,
        ("benchmark", "trade_date", "source"),
        ("benchmark", "trade_date", "source"),
    ),
}
_FORMAL_CAPABILITY_FRAME_BINDINGS = (
    ("_instruments", "instrument.parquet"),
    ("_calendar", "trade_calendar.parquet"),
    ("_bars", "bar_1d.parquet"),
    ("_limits", "price_limit_1d.parquet"),
    ("_suspensions", "suspension_1d.parquet"),
    ("_corporate_actions", "corporate_action_ledger.parquet"),
    (
        "_corporate_action_reconciliation",
        "corporate_action_reconciliation.parquet",
    ),
    ("_benchmark_bars", "benchmark_bar_1d.parquet"),
)
_FORMAL_CAPABILITY_FRAME_SLOTS = tuple(
    slot for slot, _ in _FORMAL_CAPABILITY_FRAME_BINDINGS
)


class AShareExecutionError(ValueError):
    """Stable fail-closed error for formal A-share execution projections."""


@dataclass(frozen=True)
class FormalAShareMarketFactArtifactDigestV1:
    """Portable identity for one full G1 file and its selected facts view."""

    root_alias: str
    relative_path: str
    size_bytes: int
    sha256: str
    table_name: str
    row_count: int
    content_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.root_alias) is not str
            or not self.root_alias
            or type(self.relative_path) is not str
            or not self.relative_path
            or "\\" in self.relative_path
            or self.relative_path.startswith(("/", "../"))
            or type(self.size_bytes) is not int
            or self.size_bytes < 0
            or type(self.table_name) is not str
            or self.table_name not in {
                spec[0] for spec in _FORMAL_FACT_SPECS.values()
            }
            or type(self.row_count) is not int
            or self.row_count < 0
            or _HEX64.fullmatch(self.sha256) is None
            or _HEX64.fullmatch(self.content_sha256) is None
        ):
            raise ValueError(_FORMAL_FACTS_ERROR)


@dataclass(frozen=True)
class FormalAShareMarketFactsIdentityV1:
    schema_version: Literal["m3-formal-a-share-market-facts-v1"]
    g1_release_id: str
    g1_release_manifest_sha256: str
    backtest_plan_manifest_sha256: str
    backtest_plan_receipt_sha256: str
    window_sha256: str
    artifact_digests: tuple[FormalAShareMarketFactArtifactDigestV1, ...]
    input_market_facts_sha256: str

    def __post_init__(self) -> None:
        digests = tuple(
            FormalAShareMarketFactArtifactDigestV1(**asdict(item))
            for item in self.artifact_digests
            if type(item) is FormalAShareMarketFactArtifactDigestV1
        )
        hex_values = (
            self.g1_release_id,
            self.g1_release_manifest_sha256,
            self.backtest_plan_manifest_sha256,
            self.backtest_plan_receipt_sha256,
            self.window_sha256,
            self.input_market_facts_sha256,
        )
        if (
            self.schema_version != _FORMAL_FACTS_SCHEMA
            or any(type(value) is not str or _HEX64.fullmatch(value) is None
                   for value in hex_values)
            or len(digests) != len(_FORMAL_FACT_SPECS)
            or digests != tuple(
                sorted(digests, key=lambda item: (item.root_alias, item.relative_path))
            )
            or len({item.table_name for item in digests}) != len(digests)
        ):
            raise ValueError(_FORMAL_FACTS_ERROR)
        object.__setattr__(self, "artifact_digests", digests)


@dataclass(frozen=True)
class AShareMarketFactsFreshVerificationContext:
    """Process-local complete arguments needed to freshly verify G7B."""

    target: VerifiedTargetArtifact
    folds: VerifiedFoldPlanArtifact
    experiment: VerifiedExperimentIdentity
    config: LoadedM3Config
    plan_fresh_context: BacktestPlanFreshVerificationContext
    plan_receipt_path: Path

    def __post_init__(self) -> None:
        if (
            type(self.target) is not VerifiedTargetArtifact
            or type(self.folds) is not VerifiedFoldPlanArtifact
            or type(self.experiment) is not VerifiedExperimentIdentity
            or type(self.config) is not LoadedM3Config
            or type(self.plan_fresh_context)
            is not BacktestPlanFreshVerificationContext
            or not isinstance(self.plan_receipt_path, Path)
        ):
            raise ValueError(_FORMAL_FACTS_ERROR)

    def __reduce__(self) -> Any:
        raise TypeError(_FORMAL_FACTS_ERROR)


@dataclass(frozen=True)
class _PathEntity:
    path: Path
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int


if TYPE_CHECKING:
    @final
    class VerifiedAShareMarketFacts:
        """Type-checking view of the runtime closure-produced exact class."""

        @property
        def identity(self) -> FormalAShareMarketFactsIdentityV1: ...
        @property
        def instruments(self) -> pl.DataFrame: ...
        @property
        def calendar(self) -> pl.DataFrame: ...
        @property
        def bars(self) -> pl.DataFrame: ...
        @property
        def limits(self) -> pl.DataFrame: ...
        @property
        def suspensions(self) -> pl.DataFrame: ...
        @property
        def corporate_actions(self) -> pl.DataFrame: ...
        @property
        def corporate_action_reconciliation(self) -> pl.DataFrame: ...
        @property
        def benchmark_bars(self) -> pl.DataFrame: ...


    def load_verified_a_share_market_facts(
        *,
        release: VerifiedG1Release,
        plan: VerifiedBacktestPlanArtifact,
        fresh_context: AShareMarketFactsFreshVerificationContext,
        artifact_roots: Mapping[str, Path],
    ) -> VerifiedAShareMarketFacts: ...


def _initialize_formal_facts_capability() -> tuple[type[Any], Any]:
    signing_key = secrets.token_bytes(32)
    issued: weakref.WeakSet[Any] = weakref.WeakSet()

    def reject() -> NoReturn:
        raise ValueError(_FORMAL_FACTS_ERROR) from None

    def verify(instance: Any) -> None:
        try:
            module = sys.modules.get(__name__)
            if (
                module is None
                or getattr(module, "VerifiedAShareMarketFacts", None)
                is not _VerifiedAShareMarketFacts
                or type(instance) is not _VerifiedAShareMarketFacts
                or instance not in issued
            ):
                raise ValueError
            identity = object.__getattribute__(instance, "_identity")
            frames = tuple(
                object.__getattribute__(instance, slot)
                for slot in _FORMAL_CAPABILITY_FRAME_SLOTS
            )
            provenance = object.__getattribute__(instance, "_provenance")
            nonce = object.__getattribute__(instance, "_nonce")
            whole_hash = object.__getattribute__(instance, "_whole_hash")
            attestation = object.__getattribute__(instance, "_attestation")
            if (
                type(identity) is not FormalAShareMarketFactsIdentityV1
                or any(type(frame) is not pl.DataFrame for frame in frames)
                or not _formal_provenance_valid(provenance)
                or type(nonce) is not bytes
                or len(nonce) != 16
                or type(whole_hash) is not str
                or _HEX64.fullmatch(whole_hash) is None
                or type(attestation) is not bytes
                or len(attestation) != hashlib.sha256().digest_size
            ):
                raise ValueError
            descriptors, rebuilt_whole = _formal_capability_content(
                identity, frames
            )
            if not hmac.compare_digest(whole_hash, rebuilt_whole):
                raise ValueError
            payload = _formal_attestation_payload(
                identity=identity,
                descriptors=descriptors,
                whole_hash=whole_hash,
                provenance=provenance,
                nonce=nonce,
            )
            expected = hmac.digest(signing_key, payload, "sha256")
            if not hmac.compare_digest(attestation, expected):
                raise ValueError
            return
        except Exception:
            pass
        reject()

    def consume(instance: Any, slot: str, *, clone: bool) -> Any:
        try:
            verify(instance)
            value = object.__getattribute__(instance, slot)
            return value.clone() if clone else value
        except Exception:
            pass
        reject()

    @final
    class _VerifiedAShareMarketFacts:
        __slots__ = (
            "_identity", "_instruments", "_calendar", "_bars", "_limits",
            "_suspensions", "_corporate_actions",
            "_corporate_action_reconciliation", "_benchmark_bars",
            "_provenance", "_nonce", "_whole_hash", "_attestation",
            "__weakref__",
        )

        def __new__(cls, *args: object, **kwargs: object) -> Any:
            reject()

        def __init__(self, *args: object, **kwargs: object) -> None:
            reject()

        @property
        def identity(self) -> FormalAShareMarketFactsIdentityV1:
            return cast(
                FormalAShareMarketFactsIdentityV1,
                consume(self, "_identity", clone=False),
            )

        @property
        def instruments(self) -> pl.DataFrame:
            return cast(pl.DataFrame, consume(self, "_instruments", clone=True))

        @property
        def calendar(self) -> pl.DataFrame:
            return cast(pl.DataFrame, consume(self, "_calendar", clone=True))

        @property
        def bars(self) -> pl.DataFrame:
            return cast(pl.DataFrame, consume(self, "_bars", clone=True))

        @property
        def limits(self) -> pl.DataFrame:
            return cast(pl.DataFrame, consume(self, "_limits", clone=True))

        @property
        def suspensions(self) -> pl.DataFrame:
            return cast(pl.DataFrame, consume(self, "_suspensions", clone=True))

        @property
        def corporate_actions(self) -> pl.DataFrame:
            return cast(
                pl.DataFrame, consume(self, "_corporate_actions", clone=True)
            )

        @property
        def corporate_action_reconciliation(self) -> pl.DataFrame:
            return cast(
                pl.DataFrame,
                consume(self, "_corporate_action_reconciliation", clone=True),
            )

        @property
        def benchmark_bars(self) -> pl.DataFrame:
            return cast(
                pl.DataFrame, consume(self, "_benchmark_bars", clone=True)
            )

        def __reduce__(self) -> Any:
            reject()

        def __repr__(self) -> str:
            try:
                identity = cast(
                    FormalAShareMarketFactsIdentityV1,
                    consume(self, "_identity", clone=False),
                )
                return (
                    "VerifiedAShareMarketFacts("
                    "input_market_facts_sha256="
                    f"'{identity.input_market_facts_sha256}')"
                )
            except Exception:
                pass
            reject()

    _VerifiedAShareMarketFacts.__name__ = "VerifiedAShareMarketFacts"
    _VerifiedAShareMarketFacts.__qualname__ = "VerifiedAShareMarketFacts"
    _VerifiedAShareMarketFacts.__module__ = __name__

    def public_loader(
        *,
        release: VerifiedG1Release,
        plan: VerifiedBacktestPlanArtifact,
        fresh_context: AShareMarketFactsFreshVerificationContext,
        artifact_roots: Mapping[str, Path],
    ) -> Any:
        try:
            identity, selected, provenance = _prepare_verified_a_share_market_facts(
                release=release,
                plan=plan,
                fresh_context=fresh_context,
                artifact_roots=artifact_roots,
            )
            instance = object.__new__(_VerifiedAShareMarketFacts)
            frames = tuple(
                selected[file_name].clone()
                for _, file_name in _FORMAL_CAPABILITY_FRAME_BINDINGS
            )
            descriptors, whole_hash = _formal_capability_content(identity, frames)
            nonce = secrets.token_bytes(16)
            payload = _formal_attestation_payload(
                identity=identity,
                descriptors=descriptors,
                whole_hash=whole_hash,
                provenance=provenance,
                nonce=nonce,
            )
            values: tuple[tuple[str, object], ...] = (
                ("_identity", identity),
                *tuple(zip(_FORMAL_CAPABILITY_FRAME_SLOTS, frames, strict=True)),
                ("_provenance", provenance),
                ("_nonce", nonce),
                ("_whole_hash", whole_hash),
                ("_attestation", hmac.digest(signing_key, payload, "sha256")),
            )
            for slot, value in values:
                object.__setattr__(instance, slot, value)
            issued.add(instance)
            try:
                verify(instance)
            except Exception:
                issued.discard(instance)
            else:
                return instance
        except Exception:
            pass
        reject()

    public_loader.__name__ = "load_verified_a_share_market_facts"
    public_loader.__qualname__ = "load_verified_a_share_market_facts"
    public_loader.__doc__ = (
        "Freshly verify G1/G7B, then issue an attested formal eight-table view."
    )
    return _VerifiedAShareMarketFacts, public_loader


if not TYPE_CHECKING:
    VerifiedAShareMarketFacts, load_verified_a_share_market_facts = (
        _initialize_formal_facts_capability()
    )
    del _initialize_formal_facts_capability


def _prepare_verified_a_share_market_facts(
    *,
    release: VerifiedG1Release,
    plan: VerifiedBacktestPlanArtifact,
    fresh_context: AShareMarketFactsFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> tuple[
    FormalAShareMarketFactsIdentityV1,
    dict[str, pl.DataFrame],
    tuple[_PathEntity, _PathEntity, tuple[_PathEntity, ...]],
]:
    _validate_formal_facts_outer(release, plan, fresh_context, artifact_roots)
    release_root_before = _snapshot_directory(release.release.root)
    plan_root_before = _snapshot_directory(plan.root)

    fresh_release = verify_g1_release(release=release.release)
    if not _same_verified_g1(fresh_release, release):
        raise ValueError
    fresh_plan = verify_backtest_plan_artifact(
        root=plan.root,
        receipt_path=fresh_context.plan_receipt_path,
        target=fresh_context.target,
        release=fresh_release,
        folds=fresh_context.folds,
        experiment=fresh_context.experiment,
        config=fresh_context.config,
        fresh_context=fresh_context.plan_fresh_context,
        artifact_roots=artifact_roots,
    )
    if not _same_verified_plan(fresh_plan, plan):
        raise ValueError

    data_section = fresh_context.config.section("data")
    benchmark_selector = data_section["benchmark"]
    if type(benchmark_selector) is not str or benchmark_selector != "510300.SH":
        raise ValueError

    raw_frames, raw_bytes, file_entities = _read_formal_fact_files(
        fresh_release, artifact_roots
    )
    selected = _select_and_validate_formal_facts(
        raw_frames, fresh_plan, benchmark=benchmark_selector
    )
    digests = _formal_fact_digests(
        fresh_release, selected, raw_bytes, artifact_roots
    )
    window_sha256 = hashlib.sha256(
        _canonical_json_bytes(asdict(fresh_plan.manifest.window))
    ).hexdigest()
    payload = {
        "artifact_digests": [asdict(item) for item in digests],
        "backtest_plan_manifest_sha256": fresh_plan.manifest_sha256,
        "backtest_plan_receipt_sha256": fresh_plan.plan_receipt_sha256,
        "g1_release_id": fresh_release.manifest.release_id,
        "g1_release_manifest_sha256": fresh_release.manifest_sha256,
        "schema_version": _FORMAL_FACTS_SCHEMA,
        "window_sha256": window_sha256,
    }
    identity = FormalAShareMarketFactsIdentityV1(
        schema_version=_FORMAL_FACTS_SCHEMA,
        g1_release_id=fresh_release.manifest.release_id,
        g1_release_manifest_sha256=fresh_release.manifest_sha256,
        backtest_plan_manifest_sha256=fresh_plan.manifest_sha256,
        backtest_plan_receipt_sha256=fresh_plan.plan_receipt_sha256,
        window_sha256=window_sha256,
        artifact_digests=digests,
        input_market_facts_sha256=hashlib.sha256(
            _canonical_json_bytes(payload)
        ).hexdigest(),
    )
    if (
        _snapshot_directory(release.release.root) != release_root_before
        or _snapshot_directory(plan.root) != plan_root_before
        or any(_snapshot_regular_file(path) != entity
               for path, entity in file_entities.items())
    ):
        raise ValueError
    return (
        identity,
        selected,
        (release_root_before, plan_root_before, tuple(file_entities.values())),
    )


def _formal_provenance_valid(value: object) -> bool:
    return bool(
        type(value) is tuple
        and len(value) == 3
        and type(value[0]) is _PathEntity
        and type(value[1]) is _PathEntity
        and type(value[2]) is tuple
        and len(value[2]) == len(_FORMAL_FACT_SPECS)
        and all(type(item) is _PathEntity for item in value[2])
        and len({item.path for item in value[2]}) == len(value[2])
    )


def _formal_capability_content(
    identity: FormalAShareMarketFactsIdentityV1,
    frames: tuple[pl.DataFrame, ...],
) -> tuple[tuple[dict[str, object], ...], str]:
    if (
        type(identity) is not FormalAShareMarketFactsIdentityV1
        or type(frames) is not tuple
        or len(frames) != len(_FORMAL_CAPABILITY_FRAME_BINDINGS)
    ):
        raise ValueError
    descriptors: list[dict[str, object]] = []
    for frame, (_, file_name) in zip(
        frames, _FORMAL_CAPABILITY_FRAME_BINDINGS, strict=True
    ):
        logical, schema, identity_keys, physical_keys = _FORMAL_FACT_SPECS[file_name]
        if type(frame) is not pl.DataFrame:
            raise ValueError
        validated = schema.validate(frame)
        if (
            frame.columns != validated.columns
            or frame.dtypes != validated.dtypes
            or not frame.equals(validated)
            or frame.height != frame.unique(subset=list(identity_keys)).height
            or not frame.equals(frame.sort(list(physical_keys)))
        ):
            raise ValueError
        descriptors.append(
            {
                "columns": tuple(frame.columns),
                "content_sha256": clean_table_content_sha256(
                    table_name=logical, frame=frame
                ),
                "dtypes": tuple(str(dtype) for dtype in frame.dtypes),
                "file_name": file_name,
                "identity_keys": identity_keys,
                "physical_keys": physical_keys,
                "row_count": frame.height,
                "schema_name": schema.__name__,
                "table_name": logical,
            }
        )
    frozen = tuple(descriptors)
    whole_hash = hashlib.sha256(
        _canonical_json_bytes(
            {
                "frames": frozen,
                "identity": asdict(identity),
                "schema_version": "m3-formal-a-share-market-facts-whole-v1",
            }
        )
    ).hexdigest()
    return frozen, whole_hash


def _formal_attestation_payload(
    *,
    identity: FormalAShareMarketFactsIdentityV1,
    descriptors: tuple[dict[str, object], ...],
    whole_hash: str,
    provenance: tuple[_PathEntity, _PathEntity, tuple[_PathEntity, ...]],
    nonce: bytes,
) -> bytes:
    if (
        type(identity) is not FormalAShareMarketFactsIdentityV1
        or type(descriptors) is not tuple
        or len(descriptors) != len(_FORMAL_FACT_SPECS)
        or _HEX64.fullmatch(whole_hash) is None
        or not _formal_provenance_valid(provenance)
        or type(nonce) is not bytes
        or len(nonce) != 16
    ):
        raise ValueError
    return _canonical_json_bytes(
        {
            "frames": descriptors,
            "identity": asdict(identity),
            "nonce": nonce.hex(),
            "process_provenance": {
                "files": tuple(asdict(item) for item in provenance[2]),
                "plan_root": asdict(provenance[1]),
                "release_root": asdict(provenance[0]),
            },
            "schema_version": "m3-formal-a-share-market-facts-attestation-v1",
            "whole_hash": whole_hash,
        }
    )


def _validate_formal_facts_outer(
    release: VerifiedG1Release,
    plan: VerifiedBacktestPlanArtifact,
    context: AShareMarketFactsFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> None:
    if (
        type(release) is not VerifiedG1Release
        or type(release.release) is not G1Release
        or type(release.manifest) is not G1ManifestV5
        or type(plan) is not VerifiedBacktestPlanArtifact
        or type(context) is not AShareMarketFactsFreshVerificationContext
        or not isinstance(artifact_roots, Mapping)
        or not artifact_roots
        or any(
            type(alias) is not str or not isinstance(root, Path)
            for alias, root in artifact_roots.items()
        )
    ):
        raise ValueError
    if (
        plan.manifest.g1_release_id != release.manifest.release_id
        or plan.manifest.g1_release_manifest_sha256 != release.manifest_sha256
        or plan.manifest.target_manifest_sha256 != context.target.manifest_sha256
        or plan.manifest.target_receipt_sha256
        != context.target.target_receipt_sha256
        or plan.manifest.fold_plan_manifest_sha256
        != context.folds.manifest_sha256
        or plan.manifest.experiment_key
        != context.experiment.manifest.experiment_key
        or plan.manifest.experiment_manifest_sha256
        != context.experiment.manifest_sha256
        or plan.manifest.scientific_config_sha256
        != context.config.scientific_config_sha256
    ):
        raise ValueError
    # Public root selection rejects unknown roots and ambiguous path escapes.
    select_artifact_root(release.release.root, artifact_roots=artifact_roots)
    select_artifact_root(plan.root, artifact_roots=artifact_roots)
    select_artifact_root(context.plan_receipt_path, artifact_roots=artifact_roots)


def _same_verified_g1(left: object, right: VerifiedG1Release) -> bool:
    return bool(
        type(left) is VerifiedG1Release
        and left.release == right.release
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.quality == right.quality
        and left.quality_sha256 == right.quality_sha256
        and left.artifact_paths == right.artifact_paths
    )


def _same_verified_plan(
    left: object, right: VerifiedBacktestPlanArtifact
) -> bool:
    return bool(
        type(left) is VerifiedBacktestPlanArtifact
        and left.root == right.root
        and left.scheduled_targets.equals(right.scheduled_targets)
        and left.manifest == right.manifest
        and left.manifest_sha256 == right.manifest_sha256
        and left.plan_receipt_sha256 == right.plan_receipt_sha256
    )


def _path_has_reparse_attribute(path: Path) -> bool:
    attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _snapshot_path(path: Path, *, directory: bool) -> _PathEntity:
    absolute = Path(os.path.abspath(path))
    current = absolute
    while True:
        st = os.lstat(current)
        if stat.S_ISLNK(st.st_mode) or _path_has_reparse_attribute(current):
            raise ValueError
        if current.parent == current:
            break
        current = current.parent
    st = os.lstat(absolute)
    if directory != stat.S_ISDIR(st.st_mode):
        raise ValueError
    if not directory and (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1):
        raise ValueError
    return _PathEntity(
        path=absolute,
        device=st.st_dev,
        inode=st.st_ino,
        mode=st.st_mode,
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        ctime_ns=st.st_ctime_ns,
    )


def _snapshot_directory(path: Path) -> _PathEntity:
    return _snapshot_path(path, directory=True)


def _snapshot_regular_file(path: Path) -> _PathEntity:
    return _snapshot_path(path, directory=False)


def _stable_regular_bytes(path: Path) -> tuple[bytes, _PathEntity]:
    before = _snapshot_regular_file(path)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.device, before.inode):
            raise ValueError
        first = stream.read()
        stream.seek(0)
        second = stream.read()
        after_fd = os.fstat(stream.fileno())
    after = _snapshot_regular_file(path)
    if (
        first != second
        or before != after
        or (after_fd.st_dev, after_fd.st_ino) != (before.device, before.inode)
        or len(first) != before.size
    ):
        raise ValueError
    return first, before


def _read_formal_fact_files(
    release: VerifiedG1Release, artifact_roots: Mapping[str, Path]
) -> tuple[
    dict[str, pl.DataFrame], dict[str, bytes], dict[Path, _PathEntity]
]:
    source_paths = dict(release.artifact_paths)
    manifest_entries = {entry.path: entry for entry in release.manifest.files}
    frames: dict[str, pl.DataFrame] = {}
    raw_by_name: dict[str, bytes] = {}
    entities: dict[Path, _PathEntity] = {}
    physical_identities: set[tuple[int, int]] = set()
    for name, (logical, schema, identity_keys, physical_keys) in (
        _FORMAL_FACT_SPECS.items()
    ):
        path = source_paths.get(name)
        entry = manifest_entries.get(name)
        if (
            path is None
            or entry is None
            or path != release.release.root / name
            or entry.schema_name != schema.__name__
            or entry.table_schema_version != "v3"
            or entry.key_columns != identity_keys
        ):
            raise ValueError
        select_artifact_root(path, artifact_roots=artifact_roots)
        raw, entity = _stable_regular_bytes(path)
        physical_identity = (entity.device, entity.inode)
        if physical_identity in physical_identities:
            raise ValueError
        physical_identities.add(physical_identity)
        if (
            len(raw) != entry.size_bytes
            or hashlib.sha256(raw).hexdigest() != entry.sha256
        ):
            raise ValueError
        parsed = pl.read_parquet(io.BytesIO(raw))
        validated = schema.validate(parsed)
        if (
            parsed.columns != validated.columns
            or parsed.dtypes != validated.dtypes
            or not parsed.equals(validated)
            or parsed.height != parsed.unique(subset=list(identity_keys)).height
            or not parsed.equals(parsed.sort(list(physical_keys)))
            or clean_table_content_sha256(table_name=logical, frame=parsed)
            != entry.content_sha256
        ):
            raise ValueError
        frames[name] = parsed
        raw_by_name[name] = raw
        entities[path] = entity
    return frames, raw_by_name, entities


def _select_and_validate_formal_facts(
    frames: dict[str, pl.DataFrame],
    plan: VerifiedBacktestPlanArtifact,
    *,
    benchmark: str,
) -> dict[str, pl.DataFrame]:
    if type(benchmark) is not str or benchmark != "510300.SH":
        raise ValueError
    execution_dates = plan.manifest.window.execution_dates
    if not execution_dates:
        raise ValueError
    execution_set = set(execution_dates)
    scheduled = plan.scheduled_targets
    if scheduled.is_empty() or any(
        column not in scheduled.columns
        for column in ("symbol", "weight", "execution_date")
    ):
        raise ValueError
    scheduled_rows = scheduled.select(
        "symbol", "weight", "execution_date"
    ).iter_rows(named=True)
    rows = list(scheduled_rows)
    if any(row["execution_date"] not in execution_set for row in rows):
        raise ValueError
    symbols = tuple(sorted({cast(str, row["symbol"]) for row in rows}))
    if not symbols:
        raise ValueError
    symbol_set = set(symbols)

    domain: set[tuple[str, dt.date]] = {
        (cast(str, row["symbol"]), cast(dt.date, row["execution_date"]))
        for row in rows
    }
    for symbol in symbols:
        positive_dates: list[dt.date] = []
        for row in rows:
            if row["symbol"] != symbol:
                continue
            weight = Decimal(str(row["weight"]))
            if not weight.is_finite() or weight < 0:
                raise ValueError
            if weight > 0:
                positive_dates.append(cast(dt.date, row["execution_date"]))
        if positive_dates:
            first = min(positive_dates)
            domain.update((symbol, day) for day in execution_dates if day >= first)

    instruments = frames["instrument.parquet"].filter(
        pl.col("symbol").is_in(symbols)
    )
    if set(instruments.get_column("symbol").to_list()) != symbol_set:
        raise ValueError
    instrument_by_symbol = {
        cast(str, row["symbol"]): row for row in instruments.iter_rows(named=True)
    }
    for symbol, day in domain:
        instrument = instrument_by_symbol[symbol]
        if (
            instrument["instrument_type"] != "STOCK"
            or instrument["currency"] != "CNY"
            or instrument["market"] not in {"SH", "SZ"}
            or day < instrument["list_date"]
            or (
                instrument["delist_date"] is not None
                and day > instrument["delist_date"]
            )
        ):
            raise ValueError

    domain_frame = pl.DataFrame(
        sorted(domain), schema={"symbol": pl.Utf8, "trade_date": pl.Date},
        orient="row",
    )
    bars = frames["bar_1d.parquet"].join(
        domain_frame, on=["symbol", "trade_date"], how="semi",
        maintain_order="left",
    )
    limits = frames["price_limit_1d.parquet"].join(
        domain_frame, on=["symbol", "trade_date"], how="semi",
        maintain_order="left",
    )
    suspensions = frames["suspension_1d.parquet"].join(
        domain_frame, on=["symbol", "trade_date"], how="semi",
        maintain_order="left",
    )

    ledger = frames["corporate_action_ledger.parquet"].filter(
        pl.col("symbol").is_in(symbols)
        & (
            pl.col("record_date").is_in(execution_dates)
            | pl.col("ex_date").is_in(execution_dates)
        )
    )
    reconciliation = frames[
        "corporate_action_reconciliation.parquet"
    ].filter(
        pl.col("symbol").is_in(symbols)
        & pl.col("effective_date").is_in(execution_dates)
    )

    calendar_dates: set[dt.date] = {
        plan.manifest.window.first_execution_date,
        plan.manifest.window.terminal_valuation_date,
        *execution_dates,
    }
    for date_pair in ledger.select("record_date", "ex_date").iter_rows():
        calendar_dates.update(cast(tuple[dt.date, dt.date], date_pair))
    calendar_start, calendar_end = min(calendar_dates), max(calendar_dates)
    calendar = frames["trade_calendar.parquet"].filter(
        (pl.col("market") == "SH")
        & pl.col("date").is_between(calendar_start, calendar_end, closed="both")
    )
    if calendar.is_empty() or not calendar.equals(calendar.sort("date")):
        raise ValueError
    open_dates = set(
        calendar.filter(pl.col("is_open")).get_column("date").to_list()
    )
    if not calendar_dates <= open_dates:
        raise ValueError
    terminal = plan.manifest.window.terminal_valuation_date
    for column in ("pay_date", "stock_list_date"):
        for value in ledger.get_column(column).drop_nulls().to_list():
            if value <= terminal and not any(value <= day <= terminal for day in open_dates):
                raise ValueError

    benchmark_frame = frames["benchmark_bar_1d.parquet"].filter(
        (pl.col("benchmark") == benchmark)
        & pl.col("trade_date").is_in(execution_dates)
    )
    if (
        benchmark_frame.height != len(execution_dates)
        or set(benchmark_frame.get_column("trade_date").to_list())
        != execution_set
        or benchmark_frame.select("benchmark", "trade_date").unique().height
        != len(execution_dates)
    ):
        raise ValueError

    _validate_execution_fact_domain(domain, bars, limits, suspensions)
    _validate_reconciliation_closure(
        domain, bars, suspensions, ledger, reconciliation
    )
    return {
        "instrument.parquet": instruments,
        "trade_calendar.parquet": calendar,
        "bar_1d.parquet": bars,
        "price_limit_1d.parquet": limits,
        "suspension_1d.parquet": suspensions,
        "corporate_action_ledger.parquet": ledger,
        "corporate_action_reconciliation.parquet": reconciliation,
        "benchmark_bar_1d.parquet": benchmark_frame,
    }


def _validate_execution_fact_domain(
    domain: set[tuple[str, dt.date]],
    bars: pl.DataFrame,
    limits: pl.DataFrame,
    suspensions: pl.DataFrame,
) -> None:
    def grouped(frame: pl.DataFrame, date_column: str) -> dict[tuple[str, dt.date], int]:
        result: dict[tuple[str, dt.date], int] = {}
        for symbol, day in frame.select("symbol", date_column).iter_rows():
            key = (cast(str, symbol), cast(dt.date, day))
            result[key] = result.get(key, 0) + 1
        return result

    bar_counts = grouped(bars, "trade_date")
    limit_counts = grouped(limits, "trade_date")
    full_counts = grouped(
        suspensions.filter(pl.col("suspension_scope") == "FULL_DAY"),
        "trade_date",
    )
    partial_counts = grouped(
        suspensions.filter(pl.col("suspension_scope") == "PARTIAL"),
        "trade_date",
    )
    for key in domain:
        bar_count = bar_counts.get(key, 0)
        full_count = full_counts.get(key, 0)
        partial_count = partial_counts.get(key, 0)
        if bar_count + full_count != 1 or partial_count > 1:
            raise ValueError
        if partial_count and bar_count != 1:
            raise ValueError
        matching_limits = limits.filter(
            (pl.col("symbol") == key[0]) & (pl.col("trade_date") == key[1])
        )
        if full_count:
            if limit_counts.get(key, 0) > 1:
                raise ValueError
        elif (
            limit_counts.get(key, 0) != 1
            or matching_limits.row(0, named=True)["has_price_limit"] is not True
            or matching_limits.row(0, named=True)["up_limit"] is None
            or matching_limits.row(0, named=True)["down_limit"] is None
        ):
            raise ValueError


def _parse_canonical_event_ids(value: object) -> tuple[str, ...]:
    if type(value) is not str:
        raise ValueError
    parsed = json.loads(value)
    if (
        type(parsed) is not list
        or any(type(item) is not str or _HEX64.fullmatch(item) is None for item in parsed)
        or parsed != sorted(set(parsed))
        or value != json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    ):
        raise ValueError
    return tuple(parsed)


def _event_set_sha256(event_ids: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            ["m3-g1-corporate-action-event-set-v1", *event_ids],
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _validate_reconciliation_closure(
    domain: set[tuple[str, dt.date]],
    bars: pl.DataFrame,
    suspensions: pl.DataFrame,
    ledger: pl.DataFrame,
    reconciliation: pl.DataFrame,
) -> None:
    bar_keys = set(bars.select("symbol", "trade_date").iter_rows())
    full_keys = set(
        suspensions.filter(pl.col("suspension_scope") == "FULL_DAY")
        .select("symbol", "trade_date").iter_rows()
    )
    ledger_groups: dict[tuple[str, dt.date], tuple[str, ...]] = {}
    for row in ledger.select("symbol", "ex_date", "event_id").iter_rows(named=True):
        key = (cast(str, row["symbol"]), cast(dt.date, row["ex_date"]))
        ledger_groups[key] = tuple(sorted((*ledger_groups.get(key, ()), row["event_id"])))
    reconciliation_rows: dict[tuple[str, dt.date], dict[str, object]] = {}
    for row in reconciliation.iter_rows(named=True):
        key = (cast(str, row["symbol"]), cast(dt.date, row["effective_date"]))
        if key in reconciliation_rows:
            raise ValueError
        reconciliation_rows[key] = row
        ids = _parse_canonical_event_ids(row["event_ids_json"])
        if (
            row["event_count"] != len(ids)
            or row["event_ids_sha256"] != _event_set_sha256(ids)
        ):
            raise ValueError
        if row["event_count"] > 0:
            if (
                row["status"] not in _MATCHED_RECONCILIATION_STATUSES
                or row["actual_factor_ratio"] <= 0
                or ledger_groups.get(key) != ids
            ):
                raise ValueError
        elif row["status"] != "NO_EVENT_STABLE_FACTOR" or key in ledger_groups:
            raise ValueError
    for key, ids in ledger_groups.items():
        if key not in domain:
            continue
        has_bar, has_full = key in bar_keys, key in full_keys
        if has_bar and has_full:
            raise ValueError
        if not has_bar:
            matching_reconciliation = reconciliation_rows.get(key)
            if (
                not has_full
                or matching_reconciliation is None
                or cast(int, matching_reconciliation["event_count"]) <= 0
                or tuple(_parse_canonical_event_ids(
                    matching_reconciliation["event_ids_json"]
                )) != ids
            ):
                raise ValueError


def _formal_fact_digests(
    release: VerifiedG1Release,
    selected: dict[str, pl.DataFrame],
    raw_by_name: dict[str, bytes],
    artifact_roots: Mapping[str, Path],
) -> tuple[FormalAShareMarketFactArtifactDigestV1, ...]:
    paths = dict(release.artifact_paths)
    result: list[FormalAShareMarketFactArtifactDigestV1] = []
    for name, frame in selected.items():
        path = paths[name]
        alias, root = select_artifact_root(path, artifact_roots=artifact_roots)
        relative = path.relative_to(root).as_posix()
        logical = _FORMAL_FACT_SPECS[name][0]
        raw = raw_by_name[name]
        result.append(
            FormalAShareMarketFactArtifactDigestV1(
                root_alias=alias,
                relative_path=relative,
                size_bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                table_name=logical,
                row_count=frame.height,
                content_sha256=clean_table_content_sha256(
                    table_name=logical, frame=frame
                ),
            )
        )
    return tuple(sorted(result, key=lambda item: (item.root_alias, item.relative_path)))


@dataclass(frozen=True)
class AShareMarketFactsIdentityV1:
    schema_version: Literal["m3-a-share-market-facts-v1"]
    g1_release_id: str
    g1_release_manifest_sha256: str
    window_sha256: str
    artifact_digests: tuple[ArtifactDigest, ...]
    input_market_facts_sha256: str

    def __post_init__(self) -> None:
        digests = tuple(
            ArtifactDigest(**asdict(item))
            for item in self.artifact_digests
            if type(item) is ArtifactDigest
        )
        if (
            self.schema_version != "m3-a-share-market-facts-v1"
            or any(
                type(value) is not str
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in (
                    self.g1_release_id,
                    self.g1_release_manifest_sha256,
                    self.window_sha256,
                    self.input_market_facts_sha256,
                )
            )
            or len(digests) != len(_FACT_FILES)
            or digests != tuple(
                sorted(digests, key=lambda item: item.relative_path)
            )
        ):
            raise ValueError("A-share market facts identity invalid")
        object.__setattr__(self, "artifact_digests", digests)


def build_a_share_market_facts(
    *,
    release: VerifiedDevelopmentExampleG1Release,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
) -> VerifiedDevelopmentExampleAShareMarketFacts:
    """Rebuild a read-only development market-facts view from verified bundles."""
    from quant.research.m3.development_example import (
        VerifiedDevelopmentExampleAShareMarketFacts,
        VerifiedDevelopmentExampleBacktestPlanArtifact,
        VerifiedDevelopmentExampleG1Release,
    )

    if (
        type(release) is not VerifiedDevelopmentExampleG1Release
        or type(plan) is not VerifiedDevelopmentExampleBacktestPlanArtifact
        or release.release_kind != "development_example"
        or plan.release_kind != "development_example"
        or release.formal_gate_eligible is not False
        or plan.formal_gate_eligible is not False
        or release.manifest.example_id != plan.example_id
        or plan.manifest.g1_release_id != release.manifest.release_id
        or plan.manifest.g1_release_manifest_sha256 != release.manifest_sha256
    ):
        raise ValueError("A-share market facts upstream identity mismatch")
    source_paths = dict(release.artifact_paths)
    entries = {item.path: item for item in release.manifest.files}
    schemas = {
        "instrument.parquet": InstrumentSchema,
        "trade_calendar.parquet": TradeCalendarSchema,
        "bar_1d.parquet": Bar1dSchema,
        "price_limit_1d.parquet": PriceLimit1dSchema,
        "suspension_1d.parquet": Suspension1dSchema,
        "corporate_action_ledger.parquet": CorporateActionLedgerSchema,
        "corporate_action_reconciliation.parquet": CorporateActionReconciliationSchema,
        "benchmark_bar_1d.parquet": BenchmarkBar1dSchema,
    }
    frames: dict[str, pl.DataFrame] = {}
    digests: list[ArtifactDigest] = []
    for name in _FACT_FILES:
        path = source_paths.get(name)
        entry = entries.get(name)
        if path is None or entry is None or path.name != name:
            raise ValueError("A-share market facts artifact closure invalid")
        raw = path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        if len(raw) != entry.size_bytes or sha256 != entry.sha256:
            raise ValueError("A-share market facts artifact digest drift")
        frames[name] = schemas[name].validate(pl.read_parquet(path))
        digests.append(
            ArtifactDigest(
                root_alias="development_g1_release",
                relative_path=f"contract/{name}",
                size_bytes=len(raw),
                sha256=sha256,
            )
        )
    _validate_market_fact_closure(frames)
    window_sha256 = hashlib.sha256(
        _canonical_json_bytes(asdict(plan.manifest.window))
    ).hexdigest()
    ordered_digests = tuple(sorted(digests, key=lambda item: item.relative_path))
    identity_payload = {
        "artifact_digests": [asdict(item) for item in ordered_digests],
        "g1_release_id": release.manifest.release_id,
        "g1_release_manifest_sha256": release.manifest_sha256,
        "schema_version": "m3-a-share-market-facts-v1",
        "window_sha256": window_sha256,
    }
    identity = AShareMarketFactsIdentityV1(
        schema_version="m3-a-share-market-facts-v1",
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        window_sha256=window_sha256,
        artifact_digests=ordered_digests,
        input_market_facts_sha256=hashlib.sha256(
            _canonical_json_bytes(identity_payload)
        ).hexdigest(),
    )
    return VerifiedDevelopmentExampleAShareMarketFacts(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=release.manifest.example_id,
        identity=identity,
        instruments=frames["instrument.parquet"],
        calendar=frames["trade_calendar.parquet"],
        bars=frames["bar_1d.parquet"],
        limits=frames["price_limit_1d.parquet"],
        suspensions=frames["suspension_1d.parquet"],
        corporate_actions=frames["corporate_action_ledger.parquet"],
        corporate_action_reconciliation=frames[
            "corporate_action_reconciliation.parquet"
        ],
        benchmark_bars=frames["benchmark_bar_1d.parquet"],
    )


def build_open_execution_states(
    *,
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
    date: dt.date,
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    """Project opening-only execution facts; later OHLCV fields are ignored."""
    from quant.research.m3.development_example import (
        VerifiedDevelopmentExampleAShareMarketFacts,
    )

    if (
        type(facts) is not VerifiedDevelopmentExampleAShareMarketFacts
        or type(date) is not dt.date
        or type(symbols) is not tuple
        or len(set(symbols)) != len(symbols)
        or any(type(symbol) is not str for symbol in symbols)
    ):
        raise ValueError("open execution state inputs invalid")
    bars = facts.bars.filter(pl.col("trade_date") == date)
    limits = facts.limits.filter(pl.col("trade_date") == date)
    suspensions = facts.suspensions.filter(pl.col("trade_date") == date)
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        bar_rows = bars.filter(pl.col("symbol") == symbol)
        limit_rows = limits.filter(pl.col("symbol") == symbol)
        suspension_rows = suspensions.filter(pl.col("symbol") == symbol)
        if max(bar_rows.height, limit_rows.height, suspension_rows.height) > 1:
            raise ValueError("open execution state key not unique")
        suspension = (
            None if suspension_rows.is_empty() else suspension_rows.row(0, named=True)
        )
        full_day = bool(
            suspension is not None
            and suspension["suspension_scope"] == "FULL_DAY"
        )
        bar = None if bar_rows.is_empty() else bar_rows.row(0, named=True)
        if full_day:
            rows.append(_open_state_row(
                date=date,
                symbol=symbol,
                open_value=None,
                full_day=True,
                partial_status="NOT_APPLICABLE",
                limit=None,
                buy_allowed=False,
                sell_allowed=False,
                reason="SUSPENDED",
            ))
            continue
        if limit_rows.height != 1:
            raise ValueError("non-full-day price limit missing")
        limit = limit_rows.row(0, named=True)
        if (
            limit["has_price_limit"] is not True
            or limit["up_limit"] is None
            or limit["down_limit"] is None
        ):
            raise ValueError("non-full-day price limit invalid")
        partial_status = "NOT_APPLICABLE"
        reason: str | None = None
        allowed = True
        if suspension is not None:
            partial_status = _partial_open_status(cast(str, suspension["suspension_detail"]))
            if partial_status == "SUSPENDED_AT_OPEN":
                allowed, reason = False, "SUSPENDED"
            elif partial_status == "OPEN_UNKNOWN":
                allowed, reason = False, "OPEN_UNKNOWN"
        if bar is None:
            allowed, reason = False, "MISSING_OPEN"
        open_value = None if bar is None else cast(float, bar["open"])
        buy_allowed = allowed
        sell_allowed = allowed
        if allowed and open_value is not None:
            open_decimal = Decimal(str(open_value))
            if open_decimal >= Decimal(str(limit["up_limit"])) - _PRICE_TICK / 2:
                buy_allowed = False
            if open_decimal <= Decimal(str(limit["down_limit"])) + _PRICE_TICK / 2:
                sell_allowed = False
        rows.append(_open_state_row(
            date=date,
            symbol=symbol,
            open_value=open_value,
            full_day=False,
            partial_status=partial_status,
            limit=limit,
            buy_allowed=buy_allowed,
            sell_allowed=sell_allowed,
            reason=reason,
        ))
    frame = pl.DataFrame(rows, schema={
        "date": pl.Date,
        "symbol": pl.Utf8,
        "open": pl.Float64,
        "has_open": pl.Boolean,
        "full_day_suspended": pl.Boolean,
        "partial_open_status": pl.Utf8,
        "has_price_limit": pl.Boolean,
        "up_limit": pl.Float64,
        "down_limit": pl.Float64,
        "buy_allowed": pl.Boolean,
        "sell_allowed": pl.Boolean,
        "reason": pl.Utf8,
    })
    return OpenExecutionStateSchema.validate(frame)


def _validate_market_fact_closure(frames: dict[str, pl.DataFrame]) -> None:
    bars = frames["bar_1d.parquet"]
    limits = frames["price_limit_1d.parquet"]
    suspensions = frames["suspension_1d.parquet"]
    bar_keys = set(bars.select("symbol", "trade_date").iter_rows())
    limit_keys = set(limits.select("symbol", "trade_date").iter_rows())
    full_day_keys = set(
        suspensions.filter(pl.col("suspension_scope") == "FULL_DAY")
        .select("symbol", "trade_date")
        .iter_rows()
    )
    if bar_keys != limit_keys or bar_keys & full_day_keys:
        raise ValueError("A-share market facts execution closure invalid")
    actions = frames["corporate_action_ledger.parquet"]
    reconciliations = frames["corporate_action_reconciliation.parquet"]
    reconciliation_keys = set(
        reconciliations.select(
            "symbol", pl.col("effective_date").alias("trade_date")
        ).iter_rows()
    )
    for symbol, ex_date in actions.select("symbol", "ex_date").iter_rows():
        key = (symbol, ex_date)
        if key not in bar_keys and not (
            key in full_day_keys and key in reconciliation_keys
        ):
            raise ValueError("A-share corporate action market fact missing")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.isoformat()
        if isinstance(item, (dt.date, dt.datetime))
        else str(item),
    ).encode("utf-8")


def _partial_open_status(detail: str) -> str:
    if type(detail) is not str or not detail:
        return "OPEN_UNKNOWN"
    intervals = detail.split(" | ")
    if " | ".join(intervals) != detail:
        return "OPEN_UNKNOWN"
    open_minute = 9 * 60 + 30
    parsed: list[tuple[int, int]] = []
    for interval in intervals:
        match = _PARTIAL_INTERVAL.fullmatch(interval)
        if match is None:
            return "OPEN_UNKNOWN"
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        if (
            start_hour > 23
            or end_hour > 23
            or start_minute > 59
            or end_minute > 59
        ):
            return "OPEN_UNKNOWN"
        start = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute
        if start >= end:
            return "OPEN_UNKNOWN"
        parsed.append((start, end))
    if any(start <= open_minute < end for start, end in parsed):
        return "SUSPENDED_AT_OPEN"
    return "PROVEN_OPEN_TRADABLE"


def _open_state_row(
    *,
    date: dt.date,
    symbol: str,
    open_value: float | None,
    full_day: bool,
    partial_status: str,
    limit: dict[str, object] | None,
    buy_allowed: bool,
    sell_allowed: bool,
    reason: str | None,
) -> dict[str, object]:
    return {
        "date": date,
        "symbol": symbol,
        "open": open_value,
        "has_open": open_value is not None,
        "full_day_suspended": full_day,
        "partial_open_status": partial_status,
        "has_price_limit": limit is not None,
        "up_limit": None if limit is None else limit["up_limit"],
        "down_limit": None if limit is None else limit["down_limit"],
        "buy_allowed": buy_allowed,
        "sell_allowed": sell_allowed,
        "reason": reason,
    }


@dataclass(frozen=True)
class AccountPosition:
    symbol: str
    quantity: int
    sellable_quantity: int
    unsettled_quantity: int
    mark_price: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.symbol) is not str
            or not self.symbol.endswith((".SH", ".SZ"))
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.quantity,
                    self.sellable_quantity,
                    self.unsettled_quantity,
                )
            )
            or self.sellable_quantity + self.unsettled_quantity != self.quantity
            or type(self.mark_price) is not Decimal
            or not self.mark_price.is_finite()
            or self.mark_price <= 0
        ):
            raise ValueError("account position invalid")


PositionBook: TypeAlias = tuple[AccountPosition, ...]


@dataclass(frozen=True)
class AShareFeeComponents:
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal

    def __post_init__(self) -> None:
        if any(
            type(value) is not Decimal or not value.is_finite() or value < 0
            for value in (self.commission, self.stamp_tax, self.transfer_fee)
        ):
            raise ValueError("A-share fees invalid")


@dataclass(frozen=True)
class AShareOrderQuantityRule:
    rule_version: Literal["sse_szse_limit_order_quantity_v1"]
    board: AShareBoard
    buy_min_quantity: int
    buy_increment: int
    sell_min_quantity: int
    sell_increment: int
    odd_lot_sell_policy: Literal[
        "MATCH_POSITION_REMAINDER", "FULL_BALANCE_BELOW_MIN"
    ]

    def __post_init__(self) -> None:
        if (
            self.rule_version != _RULE_VERSION
            or type(self.board) is not AShareBoard
            or any(
                type(value) is not int or value <= 0
                for value in (
                    self.buy_min_quantity,
                    self.buy_increment,
                    self.sell_min_quantity,
                    self.sell_increment,
                )
            )
            or self.odd_lot_sell_policy
            not in {"MATCH_POSITION_REMAINDER", "FULL_BALANCE_BELOW_MIN"}
        ):
            raise ValueError("A-share quantity rule invalid")


@dataclass(frozen=True)
class TargetOrderIntent:
    symbol: str
    side: OrderSide
    target_weight: Decimal
    target_notional: Decimal
    raw_target_quantity: int | None
    target_position_quantity: int | None
    requested_quantity: int | None
    quantity_rule: AShareOrderQuantityRule

    def __post_init__(self) -> None:
        quantities = (
            self.raw_target_quantity,
            self.target_position_quantity,
            self.requested_quantity,
        )
        if (
            type(self.symbol) is not str
            or type(self.side) is not OrderSide
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (self.target_weight, self.target_notional)
            )
            or any(value is not None and (type(value) is not int or value < 0) for value in quantities)
            or type(self.quantity_rule) is not AShareOrderQuantityRule
        ):
            raise ValueError("target order intent invalid")


@dataclass(frozen=True)
class ExecutionFill:
    symbol: str
    side: OrderSide
    quantity: int
    reference_open: Decimal
    execution_price: Decimal
    notional: Decimal
    fees: AShareFeeComponents
    slippage_cost: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.side) is not OrderSide
            or type(self.quantity) is not int
            or self.quantity <= 0
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (
                    self.reference_open,
                    self.execution_price,
                    self.notional,
                    self.slippage_cost,
                )
            )
            or type(self.fees) is not AShareFeeComponents
        ):
            raise ValueError("execution fill invalid")


@dataclass(frozen=True)
class ExecutionRejection:
    symbol: str
    side: OrderSide
    reason: ExecutionRejectReason
    requested_quantity: int | None
    filled_quantity: int
    rejected_quantity: int | None
    rejected_notional: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.side) is not OrderSide
            or type(self.reason) is not ExecutionRejectReason
            or type(self.filled_quantity) is not int
            or self.filled_quantity < 0
            or self.requested_quantity is not None
            and (type(self.requested_quantity) is not int or self.requested_quantity < 0)
            or self.rejected_quantity is not None
            and (type(self.rejected_quantity) is not int or self.rejected_quantity < 0)
            or self.requested_quantity is not None
            and self.rejected_quantity is not None
            and self.requested_quantity
            != self.filled_quantity + self.rejected_quantity
            or type(self.rejected_notional) is not Decimal
            or not self.rejected_notional.is_finite()
            or self.rejected_notional < 0
        ):
            raise ValueError("execution rejection invalid")


@dataclass(frozen=True)
class ExecutionBatch:
    cash: Decimal
    positions: PositionBook
    fills: tuple[ExecutionFill, ...]
    rejections: tuple[ExecutionRejection, ...]

    def __post_init__(self) -> None:
        if (
            type(self.cash) is not Decimal
            or not self.cash.is_finite()
            or self.cash < 0
            or any(type(item) is not AccountPosition for item in self.positions)
            or len({item.symbol for item in self.positions}) != len(self.positions)
            or any(type(item) is not ExecutionFill for item in self.fills)
            or any(type(item) is not ExecutionRejection for item in self.rejections)
        ):
            raise ValueError("execution batch invalid")


@dataclass(frozen=True)
class BuyAllocation:
    lambda_fraction: Fraction | None
    batch: ExecutionBatch

    def __post_init__(self) -> None:
        if (
            self.lambda_fraction is not None
            and (
                type(self.lambda_fraction) is not Fraction
                or not Fraction(0) <= self.lambda_fraction <= Fraction(1)
            )
            or type(self.batch) is not ExecutionBatch
        ):
            raise ValueError("buy allocation invalid")


@dataclass(frozen=True)
class AShareSessionExecutionTransition:
    """Immutable result of one formal A-share execution session."""

    input_market_facts_sha256: str
    date: dt.date
    pre_trade_cash: Decimal
    pre_trade_positions: PositionBook
    pre_trade_equity: Decimal
    base_cost_period: AShareCostPeriod
    friction_multiplier: Decimal
    effective_cost_period: AShareCostPeriod
    reference_opens: tuple[tuple[str, Decimal], ...]
    reference_opens_sha256: str
    intents: tuple[TargetOrderIntent, ...]
    post_trade_cash: Decimal
    post_trade_positions: PositionBook
    fills: tuple[ExecutionFill, ...]
    rejections: tuple[ExecutionRejection, ...]
    buy_allocation_lambda: Fraction | None

    def __post_init__(self) -> None:
        _validate_formal_session_transition(self)


def resolve_a_share_order_quantity_rule(
    *, symbol: str, date: dt.date
) -> AShareOrderQuantityRule:
    if type(symbol) is not str or type(date) is not dt.date:
        raise ValueError("A-share rule lookup invalid")
    prefix, suffix = symbol[:3], symbol[-3:]
    if len(symbol) != 9 or symbol[6] != ".":
        raise ValueError("A-share symbol invalid")
    if suffix == ".SH" and prefix in {"600", "601", "603", "605"}:
        board = AShareBoard.SSE_MAIN
    elif suffix == ".SH" and prefix in {"688", "689"}:
        if date < dt.date(2019, 7, 22):
            raise ValueError("STAR rule not effective")
        board = AShareBoard.SSE_STAR
    elif suffix == ".SZ" and prefix in {"000", "001", "002", "003"}:
        board = AShareBoard.SZSE_MAIN
    elif suffix == ".SZ" and prefix in {"300", "301"}:
        board = AShareBoard.SZSE_CHINEXT
    else:
        raise ValueError("unsupported A-share board")
    if board is AShareBoard.SSE_STAR:
        return AShareOrderQuantityRule(
            _RULE_VERSION, board, 200, 1, 200, 1, "FULL_BALANCE_BELOW_MIN"
        )
    return AShareOrderQuantityRule(
        _RULE_VERSION, board, 100, 100, 100, 100, "MATCH_POSITION_REMAINDER"
    )


_OPEN_EXECUTION_FRAME_SCHEMA: Mapping[
    str, pl.DataType | type[pl.DataType]
] = {
    "date": pl.Date,
    "symbol": pl.Utf8,
    "open": pl.Float64,
    "has_open": pl.Boolean,
    "full_day_suspended": pl.Boolean,
    "partial_open_status": pl.Utf8,
    "has_price_limit": pl.Boolean,
    "up_limit": pl.Float64,
    "down_limit": pl.Float64,
    "buy_allowed": pl.Boolean,
    "sell_allowed": pl.Boolean,
    "reason": pl.Utf8,
}


def _formal_execution_frames(
    facts: VerifiedAShareMarketFacts, *, include_limits: bool
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame | None]:
    instruments = facts.instruments
    bars = facts.bars
    suspensions = facts.suspensions
    limits = facts.limits if include_limits else None
    if (
        type(instruments) is not pl.DataFrame
        or type(bars) is not pl.DataFrame
        or type(suspensions) is not pl.DataFrame
        or include_limits
        and type(limits) is not pl.DataFrame
    ):
        raise ValueError
    return instruments, bars, suspensions, limits


def _formal_execution_benchmark(
    facts: VerifiedAShareMarketFacts,
) -> pl.DataFrame:
    _ = facts.identity
    benchmark = facts.benchmark_bars
    if type(benchmark) is not pl.DataFrame:
        raise ValueError
    return benchmark


def _validate_formal_execution_date(
    benchmark: pl.DataFrame, date: dt.date
) -> None:
    benchmark_keys = benchmark.select("benchmark", "trade_date")
    if benchmark_keys.filter(
        pl.col("trade_date") == date
    ).height != 1:
        raise ValueError


def _formal_request_domain(
    *,
    instruments: pl.DataFrame,
    bars: pl.DataFrame,
    suspensions: pl.DataFrame,
    date: dt.date,
    symbol: str,
) -> tuple[
    dict[str, object],
    dict[str, object] | None,
    dict[str, object] | None,
    AShareOrderQuantityRule,
]:
    instrument_rows = instruments.select(
        "symbol", "market", "instrument_type", "currency",
        "list_date", "delist_date",
    ).filter(pl.col("symbol") == symbol)
    if instrument_rows.height != 1:
        raise ValueError
    instrument = instrument_rows.row(0, named=True)
    market = instrument["market"]
    expected_suffix = (
        ".SH" if market == Market.SH.value
        else ".SZ" if market == Market.SZ.value
        else None
    )
    list_date = instrument["list_date"]
    delist_date = instrument["delist_date"]
    if (
        instrument["instrument_type"] != InstrumentType.STOCK.value
        or instrument["currency"] != Currency.CNY.value
        or expected_suffix is None
        or not symbol.endswith(expected_suffix)
        or re.fullmatch(r"\d{6}\.(SH|SZ)", symbol) is None
        or type(list_date) is not dt.date
        or delist_date is not None and type(delist_date) is not dt.date
        or date < list_date
        or delist_date is not None and date > delist_date
    ):
        raise ValueError
    quantity_rule = resolve_a_share_order_quantity_rule(
        symbol=symbol, date=date
    )

    bar_rows = bars.select(
        "symbol", "trade_date", "source", "open"
    ).filter((pl.col("symbol") == symbol) & (pl.col("trade_date") == date))
    suspension_rows = suspensions.select(
        "symbol", "trade_date", "source",
        "suspension_scope", "suspension_detail",
    ).filter((pl.col("symbol") == symbol) & (pl.col("trade_date") == date))
    if bar_rows.height > 1 or suspension_rows.height > 1:
        raise ValueError
    bar = None if bar_rows.is_empty() else bar_rows.row(0, named=True)
    suspension = (
        None if suspension_rows.is_empty()
        else suspension_rows.row(0, named=True)
    )
    if (
        bar is not None
        and (type(bar["source"]) is not str or not bar["source"])
        or suspension is not None
        and (
            type(suspension["source"]) is not str
            or not suspension["source"]
            or suspension["suspension_scope"] not in {"FULL_DAY", "PARTIAL"}
        )
    ):
        raise ValueError
    full_day = bool(
        suspension is not None
        and suspension["suspension_scope"] == "FULL_DAY"
    )
    if (bar is None) == (not full_day):
        raise ValueError
    if suspension is not None and not full_day and bar is None:
        raise ValueError
    return instrument, bar, suspension, quantity_rule


def _formal_price(value: object) -> Decimal:
    if type(value) is not float:
        raise ValueError
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError
    return result


def _formal_limit_fields(
    row: dict[str, object] | None,
) -> tuple[bool, float | None, float | None, Decimal | None, Decimal | None]:
    if row is None:
        return False, None, None, None, None
    if type(row["source"]) is not str or not row["source"]:
        raise ValueError
    has_limit = row["has_price_limit"]
    if type(has_limit) is not bool:
        raise ValueError
    if not has_limit:
        if row["up_limit"] is not None or row["down_limit"] is not None:
            raise ValueError
        return False, None, None, None, None
    upper = _formal_price(row["up_limit"])
    lower = _formal_price(row["down_limit"])
    if lower >= upper:
        raise ValueError
    return (
        True,
        cast(float, row["up_limit"]),
        cast(float, row["down_limit"]),
        upper,
        lower,
    )


def _validate_formal_open_execution_frame(frame: pl.DataFrame) -> pl.DataFrame:
    validated = OpenExecutionStateSchema.validate(frame)
    if (
        frame.columns != list(_OPEN_EXECUTION_FRAME_SCHEMA)
        or frame.dtypes != list(_OPEN_EXECUTION_FRAME_SCHEMA.values())
        or validated.columns != frame.columns
        or validated.dtypes != frame.dtypes
        or not validated.equals(frame)
        or frame.height != frame.unique(subset=["date", "symbol"]).height
        or not frame.equals(frame.sort("date", "symbol"))
    ):
        raise ValueError
    return frame


def _build_formal_open_execution_states(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    benchmark = _formal_execution_benchmark(facts)
    _validate_formal_execution_date(benchmark, date)
    if not symbols:
        return _validate_formal_open_execution_frame(
            pl.DataFrame(schema=_OPEN_EXECUTION_FRAME_SCHEMA)
        )
    instruments, bars, suspensions, limits = _formal_execution_frames(
        facts, include_limits=True
    )
    if type(limits) is not pl.DataFrame:
        raise ValueError
    limit_view = limits.select(
        "symbol", "trade_date", "source",
        "has_price_limit", "up_limit", "down_limit",
    )
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        _, bar, suspension, _ = _formal_request_domain(
            instruments=instruments,
            bars=bars,
            suspensions=suspensions,
            date=date,
            symbol=symbol,
        )
        matching_limits = limit_view.filter(
            (pl.col("symbol") == symbol) & (pl.col("trade_date") == date)
        )
        if matching_limits.height > 1:
            raise ValueError
        limit_row = (
            None if matching_limits.is_empty()
            else matching_limits.row(0, named=True)
        )
        has_limit, upper_value, lower_value, upper, lower = (
            _formal_limit_fields(limit_row)
        )
        full_day = bool(
            suspension is not None
            and suspension["suspension_scope"] == "FULL_DAY"
        )
        if full_day:
            rows.append({
                "date": date,
                "symbol": symbol,
                "open": None,
                "has_open": False,
                "full_day_suspended": True,
                "partial_open_status": "NOT_APPLICABLE",
                "has_price_limit": has_limit,
                "up_limit": upper_value,
                "down_limit": lower_value,
                "buy_allowed": False,
                "sell_allowed": False,
                "reason": ExecutionRejectReason.SUSPENDED.value,
            })
            continue
        if bar is None or not has_limit or upper is None or lower is None:
            raise ValueError
        open_value = cast(float, bar["open"])
        open_price = _formal_price(open_value)
        partial_status = "NOT_APPLICABLE"
        reason: str | None = None
        allowed = True
        if suspension is not None:
            partial_status = _partial_open_status(
                cast(str, suspension["suspension_detail"])
            )
            if partial_status == "SUSPENDED_AT_OPEN":
                allowed = False
                reason = ExecutionRejectReason.SUSPENDED.value
            elif partial_status == "OPEN_UNKNOWN":
                allowed = False
                reason = ExecutionRejectReason.OPEN_UNKNOWN.value
        buy_allowed = allowed and open_price < _formal_subtract(
            upper, _FORMAL_HALF_PRICE_TICK
        )
        sell_allowed = allowed and open_price > _formal_add(
            lower, _FORMAL_HALF_PRICE_TICK
        )
        rows.append({
            "date": date,
            "symbol": symbol,
            "open": open_value,
            "has_open": True,
            "full_day_suspended": False,
            "partial_open_status": partial_status,
            "has_price_limit": True,
            "up_limit": upper_value,
            "down_limit": lower_value,
            "buy_allowed": buy_allowed,
            "sell_allowed": sell_allowed,
            "reason": reason,
        })
    return _validate_formal_open_execution_frame(
        pl.DataFrame(rows, schema=_OPEN_EXECUTION_FRAME_SCHEMA)
    )


def build_formal_a_share_open_execution_states(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    """Project formal opening facts from one exact verified capability."""
    try:
        if (
            type(facts) is not VerifiedAShareMarketFacts
            or type(date) is not dt.date
            or type(symbols) is not tuple
            or any(type(symbol) is not str for symbol in symbols)
            or any(left >= right for left, right in zip(symbols, symbols[1:]))
        ):
            raise ValueError
        return _build_formal_open_execution_states(
            facts=facts, date=date, symbols=symbols
        )
    except Exception:
        pass
    raise AShareExecutionError(_FORMAL_EXECUTION_ERROR) from None


def resolve_formal_a_share_order_quantity_rule(
    *, facts: VerifiedAShareMarketFacts, date: dt.date, symbol: str
) -> AShareOrderQuantityRule:
    """Resolve one formal rule only after verifying its requested facts domain."""
    try:
        if (
            type(facts) is not VerifiedAShareMarketFacts
            or type(date) is not dt.date
            or type(symbol) is not str
        ):
            raise ValueError
        benchmark = _formal_execution_benchmark(facts)
        _validate_formal_execution_date(benchmark, date)
        instruments, bars, suspensions, _ = _formal_execution_frames(
            facts, include_limits=False
        )
        _, _, _, rule = _formal_request_domain(
            instruments=instruments,
            bars=bars,
            suspensions=suspensions,
            date=date,
            symbol=symbol,
        )
        return rule
    except Exception:
        pass
    raise AShareExecutionError(_FORMAL_EXECUTION_ERROR) from None


def largest_valid_buy_quantity(
    *, requested_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("quantity rule invalid")
    if requested_quantity < rule.buy_min_quantity:
        return 0
    if rule.board is AShareBoard.SSE_STAR:
        return requested_quantity
    return requested_quantity - requested_quantity % rule.buy_increment


def largest_valid_sell_quantity(
    *, requested_quantity: int, position_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    _validate_quantity(position_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("sell quantity invalid")
    capped_quantity = min(requested_quantity, position_quantity)
    if capped_quantity == position_quantity:
        return capped_quantity
    if rule.board is AShareBoard.SSE_STAR:
        return capped_quantity if capped_quantity >= rule.sell_min_quantity else 0
    round_lot = capped_quantity - capped_quantity % rule.sell_increment
    remainder = position_quantity % rule.sell_increment
    odd_lot = 0
    if remainder and capped_quantity >= remainder:
        odd_lot = capped_quantity - (capped_quantity - remainder) % rule.sell_increment
    return max(round_lot, odd_lot)


def compute_a_share_fee_components(
    *, notional: Decimal, side: OrderSide, cost_period: AShareCostPeriod
) -> AShareFeeComponents:
    if (
        type(notional) is not Decimal
        or not notional.is_finite()
        or notional < 0
        or type(side) is not OrderSide
        or type(cost_period) is not AShareCostPeriod
    ):
        raise ValueError("fee inputs invalid")
    commission = max(
        notional * cost_period.commission_rate, cost_period.commission_min
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    stamp = (
        notional * cost_period.stamp_tax_sell
        if side is OrderSide.SELL
        else Decimal("0")
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    transfer = (notional * cost_period.transfer_fee).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    return AShareFeeComponents(commission, stamp, transfer)


def build_target_order_intents(
    *,
    date: dt.date,
    targets: pl.DataFrame,
    positions: PositionBook,
    open_states: pl.DataFrame,
    pre_trade_equity: Decimal,
) -> tuple[TargetOrderIntent, ...]:
    if (
        type(date) is not dt.date
        or type(pre_trade_equity) is not Decimal
        or not pre_trade_equity.is_finite()
        or pre_trade_equity <= 0
    ):
        raise ValueError("target intent inputs invalid")
    clean = TargetWeightSchema.validate(targets)
    if clean["as_of"].n_unique() != 1 or clean["symbol"].n_unique() != clean.height:
        raise ValueError("target intent target domain invalid")
    _validate_open_states(open_states, date)
    if len({item.symbol for item in positions}) != len(positions):
        raise ValueError("position book duplicate symbols")
    by_position = {item.symbol: item for item in positions}
    by_open = {cast(str, row["symbol"]): row for row in open_states.iter_rows(named=True)}
    intents: list[TargetOrderIntent] = []
    for row in clean.sort("symbol").iter_rows(named=True):
        symbol = cast(str, row["symbol"])
        if symbol not in by_open:
            raise ValueError("target open state missing")
        rule = resolve_a_share_order_quantity_rule(symbol=symbol, date=date)
        position = by_position.get(symbol)
        current_quantity = 0 if position is None else position.quantity
        weight = Decimal(str(row["weight"]))
        target_notional = weight * pre_trade_equity
        state = by_open[symbol]
        open_value = state["open"]
        if open_value is None or not cast(bool, state["has_open"]):
            current_value = (
                Decimal("0")
                if position is None
                else Decimal(position.quantity) * position.mark_price
            )
            if target_notional == current_value:
                continue
            side = OrderSide.BUY if target_notional > current_value else OrderSide.SELL
            intents.append(
                TargetOrderIntent(
                    symbol, side, weight, target_notional, None, None, None, rule
                )
            )
            continue
        open_price = Decimal(str(open_value))
        if open_price <= 0:
            raise ValueError("target open price invalid")
        raw = int((target_notional / open_price).to_integral_value(rounding=ROUND_FLOOR))
        target_quantity = (
            0 if weight == 0 else largest_valid_buy_quantity(requested_quantity=raw, rule=rule)
        )
        lot_constrained_buy = (
            weight > 0 and raw > 0 and target_quantity == 0 and current_quantity == 0
        )
        if target_quantity == current_quantity and not lot_constrained_buy:
            continue
        side = (
            OrderSide.BUY
            if target_quantity > current_quantity or lot_constrained_buy
            else OrderSide.SELL
        )
        intents.append(
            TargetOrderIntent(
                symbol=symbol,
                side=side,
                target_weight=weight,
                target_notional=target_notional,
                raw_target_quantity=raw,
                target_position_quantity=target_quantity,
                requested_quantity=abs(target_quantity - current_quantity),
                quantity_rule=rule,
            )
        )
    return tuple(intents)


def execute_sell_intents(
    *,
    intents: tuple[TargetOrderIntent, ...],
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> ExecutionBatch:
    """Execute valid sell quantities while preserving T+1 and lot residuals."""
    _validate_execution_inputs(
        intents=intents,
        side=OrderSide.SELL,
        open_states=open_states,
        positions=positions,
        cash=cash,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    state_by_symbol = _state_map(open_states)
    position_by_symbol = {item.symbol: item for item in positions}
    fills: list[ExecutionFill] = []
    rejections: list[ExecutionRejection] = []
    updated_cash = cash
    for intent in sorted(intents, key=lambda item: item.symbol):
        state = state_by_symbol[intent.symbol]
        blocked = _blocked_reason(state=state, side=OrderSide.SELL)
        if blocked is not None:
            rejections.append(_whole_rejection(intent, state, blocked))
            continue
        position = position_by_symbol.get(intent.symbol)
        if position is None:
            raise ValueError("sell position missing")
        requested = intent.requested_quantity
        if requested is None:
            raise ValueError("sell requested quantity unknown with trusted open")
        sellable_cap = min(requested, position.sellable_quantity)
        t1_residual = requested - sellable_cap
        valid = largest_valid_sell_quantity(
            requested_quantity=sellable_cap,
            position_quantity=position.quantity,
            rule=intent.quantity_rule,
        )
        lot_residual = sellable_cap - valid
        open_price = Decimal(str(state["open"]))
        if valid:
            execution_price = _execution_price(
                open_price=open_price,
                side=OrderSide.SELL,
                slippage=cost_period.slippage,
                price_tick=price_tick,
                lower=Decimal(str(state["down_limit"])),
                upper=Decimal(str(state["up_limit"])),
            )
            notional = execution_price * valid
            fees = compute_a_share_fee_components(
                notional=notional,
                side=OrderSide.SELL,
                cost_period=cost_period,
            )
            fill = ExecutionFill(
                symbol=intent.symbol,
                side=OrderSide.SELL,
                quantity=valid,
                reference_open=open_price,
                execution_price=execution_price,
                notional=notional,
                fees=fees,
                slippage_cost=(open_price - execution_price) * valid,
            )
            fills.append(fill)
            updated_cash += notional - _fee_total(fees)
            position_by_symbol[intent.symbol] = AccountPosition(
                symbol=position.symbol,
                quantity=position.quantity - valid,
                sellable_quantity=position.sellable_quantity - valid,
                unsettled_quantity=position.unsettled_quantity,
                mark_price=position.mark_price,
            )
        if t1_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.T_PLUS_ONE,
                quantity=t1_residual,
                open_price=open_price,
            ))
        if lot_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                open_price=open_price,
            ))
    return ExecutionBatch(
        cash=updated_cash,
        positions=tuple(sorted(position_by_symbol.values(), key=lambda item: item.symbol)),
        fills=tuple(fills),
        rejections=tuple(rejections),
    )


def allocate_buy_lots(
    *,
    intents: tuple[TargetOrderIntent, ...],
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> BuyAllocation:
    """Allocate discrete buy quantities by exact Fraction breakpoints."""
    _validate_execution_inputs(
        intents=intents,
        side=OrderSide.BUY,
        open_states=open_states,
        positions=positions,
        cash=cash,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    states = _state_map(open_states)
    positions_by_symbol = {item.symbol: item for item in positions}
    rejections: list[ExecutionRejection] = []
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]] = []
    for intent in sorted(intents, key=lambda item: item.symbol):
        state = states[intent.symbol]
        blocked = _blocked_reason(state=state, side=OrderSide.BUY)
        if blocked is not None:
            rejections.append(_whole_rejection(intent, state, blocked))
            continue
        if intent.requested_quantity is None:
            raise ValueError("buy requested quantity unknown with trusted open")
        desired = largest_valid_buy_quantity(
            requested_quantity=intent.requested_quantity,
            rule=intent.quantity_rule,
        )
        raw_gap_base = max(
            intent.requested_quantity,
            0 if intent.raw_target_quantity is None else intent.raw_target_quantity,
        )
        lot_residual = raw_gap_base - desired
        if lot_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                open_price=Decimal(str(state["open"])),
            ))
        if desired:
            executable.append((intent, state, desired))
    if not executable:
        return BuyAllocation(
            lambda_fraction=None,
            batch=ExecutionBatch(
                cash=cash,
                positions=tuple(sorted(positions, key=lambda item: item.symbol)),
                fills=(),
                rejections=tuple(rejections),
            ),
        )
    breakpoints = {Fraction(0), Fraction(1)}
    for intent, _, desired in executable:
        breakpoints.update(
            Fraction(quantity, desired)
            for quantity in _valid_buy_quantities(desired, intent.quantity_rule)
        )
    chosen = Fraction(0)
    quantities: dict[str, int] = {}
    for candidate in sorted(breakpoints):
        candidate_quantities = {
            intent.symbol: _quantity_at_fraction(
                desired=desired,
                rule=intent.quantity_rule,
                fraction=candidate,
            )
            for intent, _, desired in executable
        }
        if _buy_total_cost(executable, candidate_quantities, cost_period, price_tick) <= cash:
            chosen = candidate
            quantities = candidate_quantities
        else:
            break
    remaining = cash - _buy_total_cost(executable, quantities, cost_period, price_tick)
    while True:
        candidates: list[tuple[Fraction, str, int, Decimal]] = []
        for intent, state, desired in executable:
            current = quantities.get(intent.symbol, 0)
            next_quantity = _next_valid_buy_quantity(
                current=current, desired=desired, rule=intent.quantity_rule
            )
            if next_quantity is None:
                continue
            incremental = _buy_cost(
                intent=intent,
                state=state,
                quantity=next_quantity,
                cost_period=cost_period,
                price_tick=price_tick,
            ) - _buy_cost(
                intent=intent,
                state=state,
                quantity=current,
                cost_period=cost_period,
                price_tick=price_tick,
            )
            candidates.append(
                (Fraction(desired - current, desired), intent.symbol, next_quantity, incremental)
            )
        affordable = [item for item in candidates if item[3] <= remaining]
        if not affordable:
            break
        _, symbol, next_quantity, incremental = sorted(
            affordable, key=lambda item: (-item[0], item[1])
        )[0]
        quantities[symbol] = next_quantity
        remaining -= incremental
    fills: list[ExecutionFill] = []
    for intent, state, desired in executable:
        quantity = quantities.get(intent.symbol, 0)
        if quantity:
            fill = _buy_fill(
                intent=intent,
                state=state,
                quantity=quantity,
                cost_period=cost_period,
                price_tick=price_tick,
            )
            fills.append(fill)
            current_position = positions_by_symbol.get(intent.symbol)
            positions_by_symbol[intent.symbol] = AccountPosition(
                symbol=intent.symbol,
                quantity=quantity
                + (0 if current_position is None else current_position.quantity),
                sellable_quantity=(
                    0
                    if current_position is None
                    else current_position.sellable_quantity
                ),
                unsettled_quantity=quantity
                + (
                    0
                    if current_position is None
                    else current_position.unsettled_quantity
                ),
                mark_price=(
                    fill.execution_price
                    if current_position is None
                    else current_position.mark_price
                ),
            )
        cash_residual = desired - quantity
        if cash_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.CASH_CONSTRAINT,
                quantity=cash_residual,
                open_price=Decimal(str(state["open"])),
            ))
    spent = sum((fill.notional + _fee_total(fill.fees) for fill in fills), Decimal(0))
    return BuyAllocation(
        lambda_fraction=chosen,
        batch=ExecutionBatch(
            cash=cash - spent,
            positions=tuple(
                sorted(positions_by_symbol.values(), key=lambda item: item.symbol)
            ),
            fills=tuple(fills),
            rejections=tuple(rejections),
        ),
    )


def _validate_execution_inputs(
    *,
    intents: tuple[TargetOrderIntent, ...],
    side: OrderSide,
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> None:
    if (
        type(intents) is not tuple
        or any(type(intent) is not TargetOrderIntent or intent.side is not side for intent in intents)
        or len({intent.symbol for intent in intents}) != len(intents)
        or any(type(position) is not AccountPosition for position in positions)
        or len({position.symbol for position in positions}) != len(positions)
        or type(cash) is not Decimal
        or not cash.is_finite()
        or cash < 0
        or type(cost_period) is not AShareCostPeriod
        or type(price_tick) is not Decimal
        or not price_tick.is_finite()
        or price_tick <= 0
    ):
        raise ValueError("execution inputs invalid")
    if not intents:
        return
    dates = open_states.get_column("date").unique()
    if len(dates) != 1:
        raise ValueError("execution open-state date invalid")
    _validate_open_states(open_states, dates.item())
    if {intent.symbol for intent in intents} - set(open_states.get_column("symbol")):
        raise ValueError("execution open state missing")


def _state_map(frame: pl.DataFrame) -> dict[str, dict[str, object]]:
    return {
        cast(str, row["symbol"]): row for row in frame.iter_rows(named=True)
    }


def _blocked_reason(
    *, state: dict[str, object], side: OrderSide
) -> ExecutionRejectReason | None:
    reason = state["reason"]
    if reason in {"MISSING_OPEN", "OPEN_UNKNOWN", "SUSPENDED"}:
        return ExecutionRejectReason(cast(str, reason))
    allowed_field = "buy_allowed" if side is OrderSide.BUY else "sell_allowed"
    if not cast(bool, state[allowed_field]):
        return (
            ExecutionRejectReason.BUY_AT_UPPER_LIMIT
            if side is OrderSide.BUY
            else ExecutionRejectReason.SELL_AT_LOWER_LIMIT
        )
    return None


def _whole_rejection(
    intent: TargetOrderIntent,
    state: dict[str, object],
    reason: ExecutionRejectReason,
) -> ExecutionRejection:
    requested = intent.requested_quantity
    open_value = state["open"]
    rejected_notional = (
        intent.target_notional
        if requested is None or open_value is None
        else Decimal(requested) * Decimal(str(open_value))
    )
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=requested,
        filled_quantity=0,
        rejected_quantity=requested,
        rejected_notional=rejected_notional,
    )


def _quantity_rejection(
    *,
    intent: TargetOrderIntent,
    reason: ExecutionRejectReason,
    quantity: int,
    open_price: Decimal,
) -> ExecutionRejection:
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=quantity,
        filled_quantity=0,
        rejected_quantity=quantity,
        rejected_notional=open_price * quantity,
    )


def _execution_price(
    *,
    open_price: Decimal,
    side: OrderSide,
    slippage: Decimal,
    price_tick: Decimal,
    lower: Decimal,
    upper: Decimal,
) -> Decimal:
    raw = open_price * (
        Decimal(1) + slippage if side is OrderSide.BUY else Decimal(1) - slippage
    )
    rounding = ROUND_CEILING if side is OrderSide.BUY else ROUND_FLOOR
    ticked = (raw / price_tick).to_integral_value(rounding=rounding) * price_tick
    return min(max(ticked, lower), upper)


def _fee_total(fees: AShareFeeComponents) -> Decimal:
    return fees.commission + fees.stamp_tax + fees.transfer_fee


def _valid_buy_quantities(
    desired: int, rule: AShareOrderQuantityRule
) -> tuple[int, ...]:
    if rule.board is AShareBoard.SSE_STAR:
        return tuple(range(rule.buy_min_quantity, desired + 1))
    return tuple(range(rule.buy_min_quantity, desired + 1, rule.buy_increment))


def _quantity_at_fraction(
    *, desired: int, rule: AShareOrderQuantityRule, fraction: Fraction
) -> int:
    cap = (desired * fraction.numerator) // fraction.denominator
    return largest_valid_buy_quantity(requested_quantity=cap, rule=rule)


def _next_valid_buy_quantity(
    *, current: int, desired: int, rule: AShareOrderQuantityRule
) -> int | None:
    if current >= desired:
        return None
    if current == 0:
        candidate = rule.buy_min_quantity
    else:
        candidate = current + rule.buy_increment
    return candidate if candidate <= desired else None


def _buy_fill(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> ExecutionFill:
    open_price = Decimal(str(state["open"]))
    execution_price = _execution_price(
        open_price=open_price,
        side=OrderSide.BUY,
        slippage=cost_period.slippage,
        price_tick=price_tick,
        lower=Decimal(str(state["down_limit"])),
        upper=Decimal(str(state["up_limit"])),
    )
    notional = execution_price * quantity
    fees = compute_a_share_fee_components(
        notional=notional, side=OrderSide.BUY, cost_period=cost_period
    )
    return ExecutionFill(
        symbol=intent.symbol,
        side=OrderSide.BUY,
        quantity=quantity,
        reference_open=open_price,
        execution_price=execution_price,
        notional=notional,
        fees=fees,
        slippage_cost=(execution_price - open_price) * quantity,
    )


def _buy_cost(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> Decimal:
    if quantity == 0:
        return Decimal(0)
    fill = _buy_fill(
        intent=intent,
        state=state,
        quantity=quantity,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    return fill.notional + _fee_total(fill.fees)


def _buy_total_cost(
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
    quantities: dict[str, int],
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> Decimal:
    return sum(
        (
            _buy_cost(
                intent=intent,
                state=state,
                quantity=quantities.get(intent.symbol, 0),
                cost_period=cost_period,
                price_tick=price_tick,
            )
            for intent, state, _ in executable
        ),
        Decimal(0),
    )


def _validate_quantity(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("quantity invalid")


def _validate_open_states(frame: pl.DataFrame, date: dt.date) -> None:
    required = [
        "date", "symbol", "open", "has_open", "full_day_suspended",
        "partial_open_status", "has_price_limit", "up_limit", "down_limit",
        "buy_allowed", "sell_allowed", "reason",
    ]
    if (
        set(frame.columns) != set(required)
        or frame["symbol"].n_unique() != frame.height
        or any(day != date for day in frame["date"])
    ):
        raise ValueError("open execution states invalid")


_FORMAL_TARGET_COLUMNS = [
    "as_of", "strategy", "strategy_version", "symbol", "weight",
]
_FORMAL_TARGET_DTYPES = [
    pl.Date, pl.Utf8, pl.Utf8, pl.Utf8, pl.Float64,
]
_FORMAL_REJECTION_PRIORITY = {
    ExecutionRejectReason.SUSPENDED: 0,
    ExecutionRejectReason.OPEN_UNKNOWN: 0,
    ExecutionRejectReason.MISSING_OPEN: 0,
    ExecutionRejectReason.BUY_AT_UPPER_LIMIT: 1,
    ExecutionRejectReason.SELL_AT_LOWER_LIMIT: 1,
    ExecutionRejectReason.T_PLUS_ONE: 2,
    ExecutionRejectReason.LOT_CONSTRAINT: 3,
    ExecutionRejectReason.CASH_CONSTRAINT: 4,
}


def _formal_math_context() -> Any:
    context = localcontext()
    active = context.__enter__()
    active.prec = 80
    active.rounding = ROUND_HALF_UP
    active.Emax = 999999
    active.Emin = -999999
    active.capitals = 1
    active.clamp = 0
    active.clear_flags()
    for signal in active.traps:
        active.traps[signal] = False
    return context, active


def _formal_decimal(value: object, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError
    if value < 0 or positive and value <= 0:
        raise ValueError
    return value


def _formal_add(left: Decimal, right: Decimal) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return left + right
    finally:
        context.__exit__(None, None, None)


def _formal_subtract(left: Decimal, right: Decimal) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return left - right
    finally:
        context.__exit__(None, None, None)


def _formal_multiply(left: Decimal, right: Decimal | int) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return left * right
    finally:
        context.__exit__(None, None, None)


def _formal_positions(positions: PositionBook) -> PositionBook:
    if (
        type(positions) is not tuple
        or any(type(item) is not AccountPosition for item in positions)
        or any(item.quantity <= 0 for item in positions)
        or any(
            left.symbol >= right.symbol
            for left, right in zip(positions, positions[1:])
        )
    ):
        raise ValueError
    return positions


def _formal_reference_opens(
    reference_opens: tuple[tuple[str, Decimal], ...],
) -> tuple[tuple[str, Decimal], ...]:
    if type(reference_opens) is not tuple:
        raise ValueError
    for item in reference_opens:
        if (
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not Decimal
            or not item[1].is_finite()
            or item[1] <= 0
        ):
            raise ValueError
    if any(
        left[0] >= right[0]
        for left, right in zip(reference_opens, reference_opens[1:])
    ):
        raise ValueError
    return reference_opens


def _formal_decimal_plain_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise ValueError
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    if not result or "e" in result.lower():
        raise ValueError
    return result


def _formal_reference_opens_sha256(
    reference_opens: tuple[tuple[str, Decimal], ...],
) -> str:
    validated = _formal_reference_opens(reference_opens)
    payload = [
        "m3-formal-reference-opens-v1",
        [
            [symbol, _formal_decimal_plain_text(open_price)]
            for symbol, open_price in validated
        ],
    ]
    raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _formal_target_rows(
    targets: pl.DataFrame, *, date: dt.date
) -> tuple[dict[str, object], ...]:
    if (
        targets.columns != _FORMAL_TARGET_COLUMNS
        or targets.dtypes != _FORMAL_TARGET_DTYPES
        or targets.is_empty()
        or any(targets.get_column(name).null_count() for name in targets.columns)
    ):
        raise ValueError
    validated = TargetWeightSchema.validate(targets)
    if (
        validated.columns != targets.columns
        or validated.dtypes != targets.dtypes
        or not validated.equals(targets)
    ):
        raise ValueError
    rows = tuple(targets.iter_rows(named=True))
    symbols = tuple(row["symbol"] for row in rows)
    if (
        any(type(symbol) is not str for symbol in symbols)
        or any(left >= right for left, right in zip(symbols, symbols[1:]))
    ):
        raise ValueError
    as_of_values = {row["as_of"] for row in rows}
    strategies = {row["strategy"] for row in rows}
    versions = {row["strategy_version"] for row in rows}
    if (
        len(as_of_values) != 1
        or len(strategies) != 1
        or len(versions) != 1
        or any(type(value) is not str or not value for value in strategies | versions)
    ):
        raise ValueError
    as_of = next(iter(as_of_values))
    if type(as_of) is not dt.date or as_of >= date:
        raise ValueError
    weights: list[Decimal] = []
    for row in rows:
        raw = row["weight"]
        if type(raw) is not float:
            raise ValueError
        weight = Decimal(str(raw))
        if not weight.is_finite() or weight < 0:
            raise ValueError
        weights.append(weight)
    context, _ = _formal_math_context()
    try:
        total = sum(weights, Decimal(0))
    finally:
        context.__exit__(None, None, None)
    if not total.is_finite() or total > Decimal(1):
        raise ValueError
    return rows


def _formal_effective_cost_period(
    *, base: AShareCostPeriod, multiplier: Decimal, date: dt.date
) -> AShareCostPeriod:
    if (
        type(base) is not AShareCostPeriod
        or type(multiplier) is not Decimal
        or not multiplier.is_finite()
        or multiplier not in {Decimal("0.5"), Decimal(1), Decimal(2)}
        or base.effective_from > date
        or base.effective_to is not None and date > base.effective_to
    ):
        raise ValueError
    context, _ = _formal_math_context()
    try:
        return AShareCostPeriod(
            effective_from=base.effective_from,
            effective_to=base.effective_to,
            commission_rate=base.commission_rate * multiplier,
            commission_min=base.commission_min * multiplier,
            stamp_tax_sell=base.stamp_tax_sell,
            transfer_fee=base.transfer_fee,
            slippage=base.slippage * multiplier,
        )
    finally:
        context.__exit__(None, None, None)


def _formal_fee_components(
    *, notional: Decimal, side: OrderSide, cost_period: AShareCostPeriod
) -> AShareFeeComponents:
    context, _ = _formal_math_context()
    try:
        commission = max(
            notional * cost_period.commission_rate,
            cost_period.commission_min,
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        stamp = (
            notional * cost_period.stamp_tax_sell
            if side is OrderSide.SELL
            else Decimal(0)
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
        transfer = (notional * cost_period.transfer_fee).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        return AShareFeeComponents(commission, stamp, transfer)
    finally:
        context.__exit__(None, None, None)


def _formal_execution_price(
    *, state: dict[str, object], side: OrderSide, slippage: Decimal
) -> tuple[Decimal, Decimal]:
    open_value = state["open"]
    lower_value = state["down_limit"]
    upper_value = state["up_limit"]
    if any(type(value) is not float for value in (open_value, lower_value, upper_value)):
        raise ValueError
    open_price = Decimal(str(open_value))
    lower = Decimal(str(lower_value))
    upper = Decimal(str(upper_value))
    context, _ = _formal_math_context()
    try:
        raw = open_price * (
            Decimal(1) + slippage
            if side is OrderSide.BUY
            else Decimal(1) - slippage
        )
        rounding = ROUND_CEILING if side is OrderSide.BUY else ROUND_FLOOR
        ticked = (
            (raw / _PRICE_TICK).to_integral_value(rounding=rounding)
            * _PRICE_TICK
        )
        return open_price, min(max(ticked, lower), upper)
    finally:
        context.__exit__(None, None, None)


def _formal_fill(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
) -> ExecutionFill:
    open_price, execution_price = _formal_execution_price(
        state=state, side=intent.side, slippage=cost_period.slippage
    )
    context, _ = _formal_math_context()
    try:
        notional = execution_price * quantity
        fees = _formal_fee_components(
            notional=notional, side=intent.side, cost_period=cost_period
        )
        slippage_cost = quantity * (
            execution_price - open_price
            if intent.side is OrderSide.BUY
            else open_price - execution_price
        )
        return ExecutionFill(
            symbol=intent.symbol,
            side=intent.side,
            quantity=quantity,
            reference_open=open_price,
            execution_price=execution_price,
            notional=notional,
            fees=fees,
            slippage_cost=slippage_cost,
        )
    finally:
        context.__exit__(None, None, None)


def _formal_quantity_rejection(
    *,
    intent: TargetOrderIntent,
    reason: ExecutionRejectReason,
    quantity: int,
    rejected_notional: Decimal,
) -> ExecutionRejection:
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=quantity,
        filled_quantity=0,
        rejected_quantity=quantity,
        rejected_notional=rejected_notional,
    )


def _formal_rejection_key(item: ExecutionRejection) -> tuple[int, str, int]:
    return (
        0 if item.side is OrderSide.SELL else 1,
        item.symbol,
        _FORMAL_REJECTION_PRIORITY[item.reason],
    )


def _formal_blocked_reason(
    *, state: dict[str, object], side: OrderSide
) -> ExecutionRejectReason | None:
    raw_reason = state["reason"]
    if raw_reason in {"SUSPENDED", "OPEN_UNKNOWN", "MISSING_OPEN"}:
        return ExecutionRejectReason(cast(str, raw_reason))
    allowed = state["sell_allowed" if side is OrderSide.SELL else "buy_allowed"]
    if type(allowed) is not bool:
        raise ValueError
    if allowed:
        return None
    return (
        ExecutionRejectReason.SELL_AT_LOWER_LIMIT
        if side is OrderSide.SELL
        else ExecutionRejectReason.BUY_AT_UPPER_LIMIT
    )


def _formal_buy_quantity_at_fraction(
    *, desired: int, rule: AShareOrderQuantityRule, fraction: Fraction
) -> int:
    cap = desired * fraction.numerator // fraction.denominator
    return largest_valid_buy_quantity(requested_quantity=cap, rule=rule)


def _formal_next_buy_breakpoint(
    *,
    low: Fraction,
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
) -> Fraction | None:
    result: Fraction | None = None
    for intent, _, desired in executable:
        current = _formal_buy_quantity_at_fraction(
            desired=desired, rule=intent.quantity_rule, fraction=low
        )
        next_quantity = _next_valid_buy_quantity(
            current=current, desired=desired, rule=intent.quantity_rule
        )
        if next_quantity is None:
            continue
        candidate = Fraction(next_quantity, desired)
        result = candidate if result is None else min(result, candidate)
    return result


def _formal_previous_buy_breakpoint(
    *,
    value: Fraction,
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
) -> Fraction:
    result = Fraction(0)
    for intent, _, desired in executable:
        quantity = _formal_buy_quantity_at_fraction(
            desired=desired, rule=intent.quantity_rule, fraction=value
        )
        if quantity:
            result = max(result, Fraction(quantity, desired))
    return result


def _formal_buy_cost(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
) -> Decimal:
    if quantity == 0:
        return Decimal(0)
    fill = _formal_fill(
        intent=intent, state=state, quantity=quantity, cost_period=cost_period
    )
    context, _ = _formal_math_context()
    try:
        return fill.notional + _fee_total(fill.fees)
    finally:
        context.__exit__(None, None, None)


def _formal_buy_total_cost(
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
    quantities: dict[str, int],
    cost_period: AShareCostPeriod,
) -> Decimal:
    context, _ = _formal_math_context()
    try:
        return sum(
            (
                _formal_buy_cost(
                    intent=intent,
                    state=state,
                    quantity=quantities.get(intent.symbol, 0),
                    cost_period=cost_period,
                )
                for intent, state, _ in executable
            ),
            Decimal(0),
        )
    finally:
        context.__exit__(None, None, None)


def _formal_allocate_buys(
    *,
    intents: tuple[TargetOrderIntent, ...],
    states: dict[str, dict[str, object]],
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
) -> tuple[Decimal, PositionBook, tuple[ExecutionFill, ...], tuple[ExecutionRejection, ...], Fraction | None]:
    positions_by_symbol = {item.symbol: item for item in positions}
    rejections: list[ExecutionRejection] = []
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]] = []
    for intent in intents:
        state = states[intent.symbol]
        requested = intent.requested_quantity
        raw = intent.raw_target_quantity
        target = intent.target_position_quantity
        if requested is None or raw is None or target is None:
            raise ValueError
        existing_position = positions_by_symbol.get(intent.symbol)
        current_quantity = (
            0 if existing_position is None else existing_position.quantity
        )
        target_delta = max(target - current_quantity, 0)
        desired = largest_valid_buy_quantity(
            requested_quantity=target_delta, rule=intent.quantity_rule
        )
        lot_residual = requested - desired
        if lot_residual < 0:
            raise ValueError
        if target == 0 and intent.target_weight > 0:
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                rejected_notional=intent.target_notional,
            ))
            continue
        blocked = _formal_blocked_reason(state=state, side=OrderSide.BUY)
        if blocked is not None and requested:
            open_price = Decimal(str(state["open"]))
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=blocked,
                quantity=requested,
                rejected_notional=_formal_multiply(open_price, requested),
            ))
            continue
        if lot_residual:
            rejected_notional = _formal_multiply(
                Decimal(str(state["open"])), lot_residual
            )
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                rejected_notional=rejected_notional,
            ))
        if desired:
            executable.append((intent, state, desired))
    if not executable:
        return cash, positions, (), tuple(rejections), None

    full_quantities = {intent.symbol: desired for intent, _, desired in executable}
    full_cost = _formal_buy_total_cost(executable, full_quantities, cost_period)
    if full_cost <= cash:
        chosen = Fraction(1)
        quantities = full_quantities
    else:
        low = Fraction(0)
        high = Fraction(1)
        for _ in range(4096):
            next_breakpoint = _formal_next_buy_breakpoint(
                low=low, executable=executable
            )
            if next_breakpoint is None or next_breakpoint >= high:
                break
            next_quantities = {
                intent.symbol: _formal_buy_quantity_at_fraction(
                    desired=desired,
                    rule=intent.quantity_rule,
                    fraction=next_breakpoint,
                )
                for intent, _, desired in executable
            }
            if _formal_buy_total_cost(
                executable, next_quantities, cost_period
            ) > cash:
                break
            middle = (low + high) / 2
            candidate_quantities = {
                intent.symbol: _formal_buy_quantity_at_fraction(
                    desired=desired,
                    rule=intent.quantity_rule,
                    fraction=middle,
                )
                for intent, _, desired in executable
            }
            if _formal_buy_total_cost(
                executable, candidate_quantities, cost_period
            ) <= cash:
                low = middle
            else:
                high = middle
        else:
            raise ValueError
        chosen = _formal_previous_buy_breakpoint(
            value=low, executable=executable
        )
        quantities = {
            intent.symbol: _formal_buy_quantity_at_fraction(
                desired=desired,
                rule=intent.quantity_rule,
                fraction=chosen,
            )
            for intent, _, desired in executable
        }

    spent = _formal_buy_total_cost(executable, quantities, cost_period)
    remaining = _formal_subtract(cash, spent)
    while True:
        candidates: list[tuple[Fraction, str, int, Decimal]] = []
        for intent, state, desired in executable:
            allocated_quantity = quantities.get(intent.symbol, 0)
            next_quantity = _next_valid_buy_quantity(
                current=allocated_quantity,
                desired=desired,
                rule=intent.quantity_rule,
            )
            if next_quantity is None:
                continue
            incremental = _formal_subtract(_formal_buy_cost(
                intent=intent,
                state=state,
                quantity=next_quantity,
                cost_period=cost_period,
            ), _formal_buy_cost(
                intent=intent,
                state=state,
                quantity=allocated_quantity,
                cost_period=cost_period,
            ))
            candidates.append((
                Fraction(desired - allocated_quantity, desired),
                intent.symbol,
                next_quantity,
                incremental,
            ))
        affordable = [item for item in candidates if item[3] <= remaining]
        if not affordable:
            break
        _, symbol, quantity, incremental = min(
            affordable, key=lambda item: (-item[0], item[1])
        )
        quantities[symbol] = quantity
        remaining = _formal_subtract(remaining, incremental)

    fills: list[ExecutionFill] = []
    for intent, state, desired in executable:
        quantity = quantities.get(intent.symbol, 0)
        if quantity:
            fill = _formal_fill(
                intent=intent,
                state=state,
                quantity=quantity,
                cost_period=cost_period,
            )
            fills.append(fill)
            current = positions_by_symbol.get(intent.symbol)
            positions_by_symbol[intent.symbol] = AccountPosition(
                symbol=intent.symbol,
                quantity=quantity + (0 if current is None else current.quantity),
                sellable_quantity=(
                    0 if current is None else current.sellable_quantity
                ),
                unsettled_quantity=quantity + (
                    0 if current is None else current.unsettled_quantity
                ),
                mark_price=(
                    fill.execution_price if current is None else current.mark_price
                ),
            )
        cash_residual = desired - quantity
        if cash_residual:
            rejections.append(_formal_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.CASH_CONSTRAINT,
                quantity=cash_residual,
                rejected_notional=_formal_multiply(
                    Decimal(str(state["open"])), cash_residual
                ),
            ))
    return (
        remaining,
        tuple(sorted(positions_by_symbol.values(), key=lambda item: item.symbol)),
        tuple(fills),
        tuple(rejections),
        chosen,
    )


def _formal_build_intents(
    *,
    rows: tuple[dict[str, object], ...],
    positions: PositionBook,
    states: dict[str, dict[str, object]],
    rules: dict[str, AShareOrderQuantityRule],
    pre_trade_equity: Decimal,
) -> tuple[tuple[TargetOrderIntent, ...], tuple[ExecutionRejection, ...]]:
    weights = {
        cast(str, row["symbol"]): Decimal(str(row["weight"])) for row in rows
    }
    positions_by_symbol = {item.symbol: item for item in positions}
    symbols = tuple(sorted(set(weights) | set(positions_by_symbol)))
    intents: list[TargetOrderIntent] = []
    target_diagnostics: list[ExecutionRejection] = []
    context, _ = _formal_math_context()
    try:
        for symbol in symbols:
            weight = weights.get(symbol, Decimal(0))
            target_notional = weight * pre_trade_equity
            position = positions_by_symbol.get(symbol)
            current_quantity = 0 if position is None else position.quantity
            current_value = (
                Decimal(0)
                if position is None
                else Decimal(position.quantity) * position.mark_price
            )
            state = states[symbol]
            rule = rules[symbol]
            if not cast(bool, state["has_open"]):
                if target_notional == current_value:
                    continue
                side = (
                    OrderSide.BUY
                    if target_notional > current_value
                    else OrderSide.SELL
                )
                intents.append(TargetOrderIntent(
                    symbol=symbol,
                    side=side,
                    target_weight=weight,
                    target_notional=target_notional,
                    raw_target_quantity=None,
                    target_position_quantity=None,
                    requested_quantity=None,
                    quantity_rule=rule,
                ))
                reason = _formal_blocked_reason(state=state, side=side)
                if reason is None:
                    raise ValueError
                target_diagnostics.append(ExecutionRejection(
                    symbol=symbol,
                    side=side,
                    reason=reason,
                    requested_quantity=None,
                    filled_quantity=0,
                    rejected_quantity=None,
                    rejected_notional=(target_notional - current_value).copy_abs(),
                ))
                continue

            open_price = Decimal(str(state["open"]))
            raw = int(
                (target_notional / open_price).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )
            target_quantity = (
                0
                if weight == 0
                else largest_valid_buy_quantity(
                    requested_quantity=raw, rule=rule
                )
            )
            if target_quantity == current_quantity:
                if not (weight > 0 and target_quantity == 0):
                    continue
                intent = TargetOrderIntent(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    target_weight=weight,
                    target_notional=target_notional,
                    raw_target_quantity=raw,
                    target_position_quantity=0,
                    requested_quantity=raw,
                    quantity_rule=rule,
                )
                intents.append(intent)
                continue
            if target_quantity < current_quantity:
                intent = TargetOrderIntent(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    target_weight=weight,
                    target_notional=target_notional,
                    raw_target_quantity=raw,
                    target_position_quantity=target_quantity,
                    requested_quantity=current_quantity - target_quantity,
                    quantity_rule=rule,
                )
                intents.append(intent)
                if weight > 0 and target_quantity == 0:
                    target_diagnostics.append(ExecutionRejection(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        reason=ExecutionRejectReason.LOT_CONSTRAINT,
                        requested_quantity=raw,
                        filled_quantity=0,
                        rejected_quantity=raw,
                        rejected_notional=target_notional,
                    ))
                continue
            requested = raw - current_quantity
            if requested < 0:
                raise ValueError
            intents.append(TargetOrderIntent(
                symbol=symbol,
                side=OrderSide.BUY,
                target_weight=weight,
                target_notional=target_notional,
                raw_target_quantity=raw,
                target_position_quantity=target_quantity,
                requested_quantity=requested,
                quantity_rule=rule,
            ))
    finally:
        context.__exit__(None, None, None)
    return tuple(intents), tuple(target_diagnostics)


def _formal_execute_sells(
    *,
    intents: tuple[TargetOrderIntent, ...],
    states: dict[str, dict[str, object]],
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
) -> tuple[Decimal, PositionBook, tuple[ExecutionFill, ...], tuple[ExecutionRejection, ...]]:
    positions_by_symbol = {item.symbol: item for item in positions}
    fills: list[ExecutionFill] = []
    rejections: list[ExecutionRejection] = []
    updated_cash = cash
    context, _ = _formal_math_context()
    try:
        for intent in intents:
            requested = intent.requested_quantity
            if requested is None:
                raise ValueError
            state = states[intent.symbol]
            blocked = _formal_blocked_reason(state=state, side=OrderSide.SELL)
            open_price = Decimal(str(state["open"]))
            if blocked is not None:
                rejections.append(_formal_quantity_rejection(
                    intent=intent,
                    reason=blocked,
                    quantity=requested,
                    rejected_notional=open_price * requested,
                ))
                continue
            position = positions_by_symbol.get(intent.symbol)
            if position is None:
                raise ValueError
            sellable_cap = min(requested, position.sellable_quantity)
            t1_residual = requested - sellable_cap
            valid = largest_valid_sell_quantity(
                requested_quantity=sellable_cap,
                position_quantity=position.quantity,
                rule=intent.quantity_rule,
            )
            lot_residual = sellable_cap - valid
            if valid:
                fill = _formal_fill(
                    intent=intent,
                    state=state,
                    quantity=valid,
                    cost_period=cost_period,
                )
                fills.append(fill)
                updated_cash += fill.notional - _fee_total(fill.fees)
                remaining_quantity = position.quantity - valid
                if remaining_quantity:
                    positions_by_symbol[intent.symbol] = AccountPosition(
                        symbol=position.symbol,
                        quantity=remaining_quantity,
                        sellable_quantity=position.sellable_quantity - valid,
                        unsettled_quantity=position.unsettled_quantity,
                        mark_price=position.mark_price,
                    )
                else:
                    del positions_by_symbol[intent.symbol]
            if t1_residual:
                rejections.append(_formal_quantity_rejection(
                    intent=intent,
                    reason=ExecutionRejectReason.T_PLUS_ONE,
                    quantity=t1_residual,
                    rejected_notional=open_price * t1_residual,
                ))
            if lot_residual:
                rejections.append(_formal_quantity_rejection(
                    intent=intent,
                    reason=ExecutionRejectReason.LOT_CONSTRAINT,
                    quantity=lot_residual,
                    rejected_notional=open_price * lot_residual,
                ))
    finally:
        context.__exit__(None, None, None)
    return (
        updated_cash,
        tuple(sorted(positions_by_symbol.values(), key=lambda item: item.symbol)),
        tuple(fills),
        tuple(rejections),
    )


def _validate_formal_session_transition(
    transition: AShareSessionExecutionTransition,
) -> None:
    if (
        type(transition.input_market_facts_sha256) is not str
        or _HEX64.fullmatch(transition.input_market_facts_sha256) is None
        or type(transition.date) is not dt.date
        or type(transition.pre_trade_cash) is not Decimal
        or type(transition.pre_trade_equity) is not Decimal
        or type(transition.post_trade_cash) is not Decimal
        or type(transition.base_cost_period) is not AShareCostPeriod
        or type(transition.friction_multiplier) is not Decimal
        or type(transition.effective_cost_period) is not AShareCostPeriod
        or type(transition.reference_opens) is not tuple
        or type(transition.reference_opens_sha256) is not str
        or _HEX64.fullmatch(transition.reference_opens_sha256) is None
        or type(transition.intents) is not tuple
        or type(transition.fills) is not tuple
        or type(transition.rejections) is not tuple
        or transition.buy_allocation_lambda is not None
        and type(transition.buy_allocation_lambda) is not Fraction
    ):
        raise ValueError("formal A-share session transition invalid")
    _formal_decimal(transition.pre_trade_cash)
    _formal_decimal(transition.pre_trade_equity, positive=True)
    _formal_decimal(transition.post_trade_cash)
    pre_positions = _formal_positions(transition.pre_trade_positions)
    post_positions = _formal_positions(transition.post_trade_positions)
    reference_opens = _formal_reference_opens(transition.reference_opens)
    expected_reference_digest = _formal_reference_opens_sha256(reference_opens)
    if not hmac.compare_digest(
        transition.reference_opens_sha256, expected_reference_digest
    ):
        raise ValueError("formal A-share session transition invalid")
    if (
        any(type(item) is not TargetOrderIntent for item in transition.intents)
        or any(type(item) is not ExecutionFill for item in transition.fills)
        or any(type(item) is not ExecutionRejection for item in transition.rejections)
        or any(type(item.symbol) is not str for item in transition.fills)
        or any(
            type(item.symbol) is not str
            or item.reason not in _FORMAL_REJECTION_PRIORITY
            or item.filled_quantity != 0
            or item.requested_quantity != item.rejected_quantity
            for item in transition.rejections
        )
        or len({(item.symbol, item.side) for item in transition.fills})
        != len(transition.fills)
        or len({(item.symbol, item.side, item.reason) for item in transition.rejections})
        != len(transition.rejections)
        or any(
            left.symbol >= right.symbol
            for left, right in zip(transition.intents, transition.intents[1:])
        )
        or tuple(sorted(transition.rejections, key=_formal_rejection_key))
        != transition.rejections
        or transition.buy_allocation_lambda is not None
        and not Fraction(0) <= transition.buy_allocation_lambda <= Fraction(1)
    ):
        raise ValueError("formal A-share session transition invalid")
    effective = _formal_effective_cost_period(
        base=transition.base_cost_period,
        multiplier=transition.friction_multiplier,
        date=transition.date,
    )
    if effective != transition.effective_cost_period:
        raise ValueError("formal A-share session transition invalid")
    reference_open_by_symbol = dict(reference_opens)
    non_null_intent_symbols = {
        item.symbol for item in transition.intents
        if item.requested_quantity is not None
    }
    if set(reference_open_by_symbol) != non_null_intent_symbols:
        raise ValueError("formal A-share session transition invalid")
    side_keys = [
        (0 if fill.side is OrderSide.SELL else 1, fill.symbol)
        for fill in transition.fills
    ]
    if side_keys != sorted(side_keys):
        raise ValueError("formal A-share session transition invalid")

    context, _ = _formal_math_context()
    try:
        marked = transition.pre_trade_cash + sum(
            (
                Decimal(item.quantity) * item.mark_price
                for item in pre_positions
            ),
            Decimal(0),
        )
        if transition.pre_trade_equity < marked:
            raise ValueError
        sell_cash = Decimal(0)
        buy_cash = Decimal(0)
        for fill in transition.fills:
            if (
                fill.reference_open
                != reference_open_by_symbol.get(fill.symbol)
                or
                fill.notional != fill.execution_price * fill.quantity
                or fill.execution_price % _PRICE_TICK != 0
                or fill.fees != _formal_fee_components(
                    notional=fill.notional,
                    side=fill.side,
                    cost_period=effective,
                )
                or fill.slippage_cost != fill.quantity * (
                    fill.reference_open - fill.execution_price
                    if fill.side is OrderSide.SELL
                    else fill.execution_price - fill.reference_open
                )
            ):
                raise ValueError
            amount = fill.notional + _fee_total(fill.fees)
            if fill.side is OrderSide.SELL:
                sell_cash += fill.notional - _fee_total(fill.fees)
            else:
                buy_cash += amount
        if (
            transition.post_trade_cash
            != transition.pre_trade_cash + sell_cash - buy_cash
            or transition.post_trade_cash < 0
        ):
            raise ValueError
    finally:
        context.__exit__(None, None, None)

    expected = {item.symbol: item for item in pre_positions}
    for fill in transition.fills:
        current = expected.get(fill.symbol)
        if fill.side is OrderSide.SELL:
            if current is None or fill.quantity > current.sellable_quantity:
                raise ValueError("formal A-share session transition invalid")
            remaining = current.quantity - fill.quantity
            if remaining:
                expected[fill.symbol] = AccountPosition(
                    symbol=current.symbol,
                    quantity=remaining,
                    sellable_quantity=current.sellable_quantity - fill.quantity,
                    unsettled_quantity=current.unsettled_quantity,
                    mark_price=current.mark_price,
                )
            else:
                del expected[fill.symbol]
        else:
            expected[fill.symbol] = AccountPosition(
                symbol=fill.symbol,
                quantity=fill.quantity + (0 if current is None else current.quantity),
                sellable_quantity=0 if current is None else current.sellable_quantity,
                unsettled_quantity=fill.quantity + (
                    0 if current is None else current.unsettled_quantity
                ),
                mark_price=fill.execution_price if current is None else current.mark_price,
            )
    if tuple(sorted(expected.values(), key=lambda item: item.symbol)) != post_positions:
        raise ValueError("formal A-share session transition invalid")

    intents = {(item.symbol, item.side): item for item in transition.intents}
    fills_by_intent: dict[tuple[str, OrderSide], int] = {}
    for fill in transition.fills:
        key = (fill.symbol, fill.side)
        if key not in intents:
            raise ValueError("formal A-share session transition invalid")
        fills_by_intent[key] = fills_by_intent.get(key, 0) + fill.quantity
    residuals: dict[tuple[str, OrderSide], int] = {}
    target_lot_symbols: set[str] = set()
    null_rejection_keys: set[tuple[str, OrderSide]] = set()
    for rejection in transition.rejections:
        key = (rejection.symbol, rejection.side)
        intent = intents.get(key)
        special = False
        if (
            rejection.side is OrderSide.BUY
            and rejection.reason is ExecutionRejectReason.LOT_CONSTRAINT
        ):
            source = intents.get((rejection.symbol, OrderSide.SELL)) or intent
            special = bool(
                source is not None
                and source.target_weight > 0
                and source.target_position_quantity == 0
                and source.raw_target_quantity is not None
                and rejection.requested_quantity == source.raw_target_quantity
                and rejection.rejected_quantity == source.raw_target_quantity
                and rejection.rejected_notional == source.target_notional
            )
        if special:
            if rejection.symbol in target_lot_symbols:
                raise ValueError("formal A-share session transition invalid")
            target_lot_symbols.add(rejection.symbol)
            continue
        if intent is None:
            raise ValueError("formal A-share session transition invalid")
        if intent.requested_quantity is None:
            if (
                rejection.requested_quantity is not None
                or rejection.rejected_quantity is not None
                or rejection.filled_quantity != 0
                or key in null_rejection_keys
            ):
                raise ValueError("formal A-share session transition invalid")
            position = next(
                (
                    item for item in pre_positions
                    if item.symbol == rejection.symbol
                ),
                None,
            )
            current_value = (
                Decimal(0)
                if position is None
                else _formal_multiply(position.mark_price, position.quantity)
            )
            if rejection.rejected_notional != _formal_subtract(
                intent.target_notional, current_value
            ).copy_abs():
                raise ValueError("formal A-share session transition invalid")
            null_rejection_keys.add(key)
            continue
        if rejection.rejected_quantity is None:
            raise ValueError("formal A-share session transition invalid")
        reference_open = reference_open_by_symbol.get(rejection.symbol)
        if (
            reference_open is None
            or rejection.rejected_notional
            != _formal_multiply(reference_open, rejection.rejected_quantity)
        ):
            raise ValueError("formal A-share session transition invalid")
        residuals[key] = residuals.get(key, 0) + rejection.rejected_quantity
    for key, intent in intents.items():
        if intent.requested_quantity is None:
            if fills_by_intent.get(key, 0) or key not in null_rejection_keys:
                raise ValueError("formal A-share session transition invalid")
            continue
        if (
            intent.side is OrderSide.BUY
            and intent.target_weight > 0
            and intent.target_position_quantity == 0
            and intent.raw_target_quantity == intent.requested_quantity
        ):
            if (
                intent.symbol not in target_lot_symbols
                or fills_by_intent.get(key, 0)
                or residuals.get(key, 0)
            ):
                raise ValueError("formal A-share session transition invalid")
            continue
        if (
            fills_by_intent.get(key, 0) + residuals.get(key, 0)
            != intent.requested_quantity
        ):
            raise ValueError("formal A-share session transition invalid")
    for intent in transition.intents:
        if (
            intent.side is OrderSide.SELL
            and intent.target_weight > 0
            and intent.target_position_quantity == 0
            and intent.symbol not in target_lot_symbols
        ):
            raise ValueError("formal A-share session transition invalid")
    if any(fill.side is OrderSide.BUY for fill in transition.fills) and (
        transition.buy_allocation_lambda is None
    ):
        raise ValueError("formal A-share session transition invalid")


def execute_formal_a_share_session(
    *,
    facts: VerifiedAShareMarketFacts,
    date: dt.date,
    targets: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    pre_trade_equity: Decimal,
    base_cost_period: AShareCostPeriod,
    friction_multiplier: Decimal,
) -> AShareSessionExecutionTransition:
    """Execute one formal in-memory A-share target-to-account transition."""
    try:
        if (
            type(facts) is not VerifiedAShareMarketFacts
            or type(date) is not dt.date
            or type(targets) is not pl.DataFrame
            or type(positions) is not tuple
            or type(cash) is not Decimal
            or type(pre_trade_equity) is not Decimal
            or type(base_cost_period) is not AShareCostPeriod
            or type(friction_multiplier) is not Decimal
        ):
            raise ValueError
        identity = facts.identity
        if type(identity) is not FormalAShareMarketFactsIdentityV1:
            raise ValueError
        rows = _formal_target_rows(targets, date=date)
        clean_positions = _formal_positions(positions)
        clean_cash = _formal_decimal(cash)
        clean_equity = _formal_decimal(pre_trade_equity, positive=True)
        effective_cost = _formal_effective_cost_period(
            base=base_cost_period, multiplier=friction_multiplier, date=date
        )
        symbols = tuple(sorted(
            {cast(str, row["symbol"]) for row in rows}
            | {item.symbol for item in clean_positions}
        ))
        open_states = build_formal_a_share_open_execution_states(
            facts=facts, date=date, symbols=symbols
        )
        if _validate_formal_open_execution_frame(open_states) is not open_states:
            raise ValueError
        states = _state_map(open_states)
        if set(states) != set(symbols):
            raise ValueError
        rules = {
            symbol: resolve_formal_a_share_order_quantity_rule(
                facts=facts, date=date, symbol=symbol
            )
            for symbol in symbols
        }
        if any(type(rule) is not AShareOrderQuantityRule for rule in rules.values()):
            raise ValueError
        intents, diagnostics = _formal_build_intents(
            rows=rows,
            positions=clean_positions,
            states=states,
            rules=rules,
            pre_trade_equity=clean_equity,
        )
        sell_intents = tuple(
            item for item in intents if item.side is OrderSide.SELL
        )
        buy_intents = tuple(
            item for item in intents
            if item.side is OrderSide.BUY and item.requested_quantity is not None
        )
        null_rejections = tuple(
            item for item in diagnostics
            if item.requested_quantity is None
        )
        target_diagnostics = tuple(
            item for item in diagnostics
            if item.requested_quantity is not None
        )
        known_sell_intents = tuple(
            item for item in sell_intents if item.requested_quantity is not None
        )
        sell_cash, sell_positions, sell_fills, sell_rejections = (
            _formal_execute_sells(
                intents=known_sell_intents,
                states=states,
                positions=clean_positions,
                cash=clean_cash,
                cost_period=effective_cost,
            )
        )
        (
            post_cash,
            post_positions,
            buy_fills,
            buy_rejections,
            allocation_lambda,
        ) = _formal_allocate_buys(
            intents=buy_intents,
            states=states,
            positions=sell_positions,
            cash=sell_cash,
            cost_period=effective_cost,
        )
        rejections = tuple(sorted(
            sell_rejections
            + null_rejections
            + target_diagnostics
            + buy_rejections,
            key=_formal_rejection_key,
        ))
        reference_opens = tuple(
            (
                intent.symbol,
                Decimal(str(states[intent.symbol]["open"])),
            )
            for intent in intents
            if intent.requested_quantity is not None
        )
        reference_opens_sha256 = _formal_reference_opens_sha256(reference_opens)
        return AShareSessionExecutionTransition(
            input_market_facts_sha256=identity.input_market_facts_sha256,
            date=date,
            pre_trade_cash=clean_cash,
            pre_trade_positions=clean_positions,
            pre_trade_equity=clean_equity,
            base_cost_period=base_cost_period,
            friction_multiplier=friction_multiplier,
            effective_cost_period=effective_cost,
            reference_opens=reference_opens,
            reference_opens_sha256=reference_opens_sha256,
            intents=intents,
            post_trade_cash=post_cash,
            post_trade_positions=post_positions,
            fills=sell_fills + buy_fills,
            rejections=rejections,
            buy_allocation_lambda=allocation_lambda,
        )
    except Exception:
        pass
    raise AShareExecutionError(_FORMAL_EXECUTION_ERROR) from None


_A_SHARE_RULE_HASH_VERSION = "a-share-rule-hash-v1"
_A_SHARE_RULE_ACCEPTED = "ACCEPTED"
_A_SHARE_RULE_INPUT_INVALID = "A_SHARE_RULE_INPUT_INVALID"


class AShareRuleInputError(ValueError):
    """Typed M4 A-share rule contract failure with a stable message code."""


@dataclass(frozen=True, slots=True)
class AShareRuleConfig:
    """Versioned selector window for the pure A-share rule adapter."""

    rule_identity: str
    selector: str
    effective_from: dt.date
    effective_to: dt.date | None

    def __post_init__(self) -> None:
        if (
            type(self.selector) is not str
            or not self.selector
            or any(ord(char) < 32 or ord(char) == 127 for char in self.selector)
            or "/" in self.selector
            or "\\" in self.selector
            or "://" in self.selector
            or self.selector.startswith("~")
            or (len(self.selector) >= 2 and self.selector[1] == ":")
            or type(self.effective_from) is not dt.date
            or self.effective_to is not None
            and type(self.effective_to) is not dt.date
            or self.effective_to is not None
            and self.effective_to < self.effective_from
            or type(self.rule_identity) is not str
            or len(self.rule_identity) != 64
            or any(char not in "0123456789abcdef" for char in self.rule_identity)
            or self.rule_identity
            != _a_share_rule_config_identity(
                selector=self.selector,
                effective_from=self.effective_from,
                effective_to=self.effective_to,
            )
        ):
            raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)


def _a_share_rule_config_identity(
    *, selector: str, effective_from: dt.date, effective_to: dt.date | None
) -> str:
    envelope = {
        "hash_version": _A_SHARE_RULE_HASH_VERSION,
        "type": "AShareRuleConfig",
        "payload": {
            "effective_from": effective_from,
            "effective_to": effective_to,
            "selector": selector,
        },
    }
    return hashlib.sha256(_canonical_json_bytes(envelope)).hexdigest()


def build_a_share_rule_config(
    *, selector: str, effective_from: dt.date, effective_to: dt.date | None
) -> AShareRuleConfig:
    """Build a strict rule config whose identity is package-computed."""
    try:
        identity = _a_share_rule_config_identity(
            selector=selector,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        return AShareRuleConfig(identity, selector, effective_from, effective_to)
    except Exception:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID) from None


def _prove_a_share_rule_inputs(
    intent: OrderIntent,
    state: SymbolMarketState,
    position: PositionBalance | None,
    rule_config: AShareRuleConfig,
) -> tuple[OrderIntent, SymbolMarketState, PositionBalance | None, AShareRuleConfig]:
    try:
        if type(intent) is not OrderIntent or type(state) is not SymbolMarketState:
            raise ValueError
        if position is not None and type(position) is not PositionBalance:
            raise ValueError
        if type(rule_config) is not AShareRuleConfig:
            raise ValueError
        proven_intent = build_order_intent(
            plan_id=intent.plan_id,
            symbol=intent.symbol,
            market=intent.market,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            quote_currency=intent.quote_currency,
            session_date=intent.session_date,
            generated_at=intent.generated_at,
            target_identity=intent.target_identity,
            market_snapshot_id=intent.market_snapshot_id,
            account_snapshot_id=intent.account_snapshot_id,
            config_identity=intent.config_identity,
            connect_route=intent.connect_route,
        )
        proven_state = build_symbol_market_state(
            symbol=state.symbol,
            market=state.market,
            session_date=state.session_date,
            quote_currency=state.quote_currency,
            reference_price=state.reference_price,
            limit_up=state.limit_up,
            limit_down=state.limit_down,
            suspended=state.suspended,
            board_lot=state.board_lot,
            tick_size=state.tick_size,
            rule_version=state.rule_version,
        )
        proven_position = (
            None
            if position is None
            else build_position_balance(
                symbol=position.symbol,
                market=position.market,
                quantity=position.quantity,
                sellable_quantity=position.sellable_quantity,
                avg_cost=position.avg_cost,
            )
        )
        proven_config = build_a_share_rule_config(
            selector=rule_config.selector,
            effective_from=rule_config.effective_from,
            effective_to=rule_config.effective_to,
        )
        if (
            proven_intent != intent
            or proven_state != state
            or proven_position != position
            or proven_config != rule_config
        ):
            raise ValueError
        return proven_intent, proven_state, proven_position, proven_config
    except Exception:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID) from None


def _a_share_rule_reject(
    reason: ExecutionRejectReason, selector: str
) -> RuleDecision:
    return build_rule_decision(
        accepted=False,
        code=reason.value,
        normalized_quantity=0,
        normalized_limit_price=Decimal("0"),
        rule_version=selector,
    )


def _a_share_tick_multiple(price: Decimal, tick: Decimal) -> bool:
    """Check an exact decimal multiple without depending on Decimal context."""
    price_parts, tick_parts = price.as_tuple(), tick.as_tuple()
    if type(price_parts.exponent) is not int or type(tick_parts.exponent) is not int:
        return False
    price_coeff = int("".join(str(item) for item in price_parts.digits))
    tick_coeff = int("".join(str(item) for item in tick_parts.digits))
    if price_coeff <= 0 or tick_coeff <= 0:
        return False
    exponent_delta = price_parts.exponent - tick_parts.exponent
    if exponent_delta >= 0:
        return price_coeff * 10**exponent_delta % tick_coeff == 0
    return price_coeff % (tick_coeff * 10 ** (-exponent_delta)) == 0


def evaluate_a_share_intent(
    intent: OrderIntent,
    state: SymbolMarketState,
    position: PositionBalance | None,
    rule_config: AShareRuleConfig,
) -> RuleDecision:
    """Evaluate a send-ready A-share limit intent using the shared G7 rules."""
    intent, state, position, rule_config = _prove_a_share_rule_inputs(
        intent, state, position, rule_config
    )
    if (
        intent.market not in {Market.SH, Market.SZ}
        or intent.quote_currency is not Currency.CNY
        or intent.connect_route is not None
        or state.market is not intent.market
        or state.quote_currency is not Currency.CNY
        or state.symbol != intent.symbol
        or state.session_date != intent.session_date
        or position is not None
        and (position.market is not intent.market or position.symbol != intent.symbol)
    ):
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)

    selector = rule_config.selector
    session = intent.session_date
    if session < rule_config.effective_from or (
        rule_config.effective_to is not None and session > rule_config.effective_to
    ):
        return _a_share_rule_reject(ExecutionRejectReason.RULE_NOT_EFFECTIVE, selector)
    if state.rule_version != selector:
        return _a_share_rule_reject(
            ExecutionRejectReason.RULE_VERSION_MISMATCH, selector
        )

    try:
        quantity_rule = resolve_a_share_order_quantity_rule(
            symbol=intent.symbol, date=session
        )
    except Exception:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID) from None
    if state.board_lot != quantity_rule.buy_min_quantity:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)
    if state.suspended:
        return _a_share_rule_reject(ExecutionRejectReason.SUSPENDED, selector)

    if intent.side is OrderSide.BUY:
        valid_quantity = largest_valid_buy_quantity(
            requested_quantity=intent.quantity, rule=quantity_rule
        )
    elif intent.side is OrderSide.SELL:
        if position is None or intent.quantity > position.sellable_quantity:
            return _a_share_rule_reject(ExecutionRejectReason.T_PLUS_ONE, selector)
        valid_quantity = largest_valid_sell_quantity(
            requested_quantity=intent.quantity,
            position_quantity=position.quantity,
            rule=quantity_rule,
        )
    else:
        raise AShareRuleInputError(_A_SHARE_RULE_INPUT_INVALID)
    if valid_quantity != intent.quantity:
        return _a_share_rule_reject(ExecutionRejectReason.LOT_CONSTRAINT, selector)

    if state.limit_up is None or state.limit_down is None:
        return _a_share_rule_reject(ExecutionRejectReason.PRICE_BAND_MISSING, selector)
    if not _a_share_tick_multiple(intent.limit_price, state.tick_size):
        return _a_share_rule_reject(ExecutionRejectReason.PRICE_TICK_INVALID, selector)
    if intent.side is OrderSide.BUY and intent.limit_price >= state.limit_up:
        return _a_share_rule_reject(ExecutionRejectReason.BUY_AT_UPPER_LIMIT, selector)
    if intent.side is OrderSide.SELL and intent.limit_price <= state.limit_down:
        return _a_share_rule_reject(ExecutionRejectReason.SELL_AT_LOWER_LIMIT, selector)
    if not state.limit_down <= intent.limit_price <= state.limit_up:
        return _a_share_rule_reject(ExecutionRejectReason.PRICE_OUT_OF_RANGE, selector)
    return build_rule_decision(
        accepted=True,
        code=_A_SHARE_RULE_ACCEPTED,
        normalized_quantity=intent.quantity,
        normalized_limit_price=intent.limit_price,
        rule_version=selector,
    )


__all__ = [
    "AShareExecutionError",
    "AShareSessionExecutionTransition",
    "AShareMarketFactsFreshVerificationContext",
    "AShareRuleConfig", "AShareRuleInputError",
    "AShareBoard", "AShareFeeComponents", "AShareMarketFactsIdentityV1",
    "AShareOrderQuantityRule",
    "AccountPosition", "BuyAllocation", "ExecutionBatch", "ExecutionFill",
    "ExecutionRejectReason", "ExecutionRejection",
    "FormalAShareMarketFactArtifactDigestV1",
    "FormalAShareMarketFactsIdentityV1", "PositionBook",
    "TargetOrderIntent", "allocate_buy_lots", "build_a_share_market_facts",
    "build_a_share_rule_config", "build_formal_a_share_open_execution_states",
    "build_open_execution_states",
    "build_target_order_intents",
    "compute_a_share_fee_components", "largest_valid_buy_quantity",
    "execute_formal_a_share_session",
    "evaluate_a_share_intent", "execute_sell_intents",
    "largest_valid_sell_quantity",
    "load_verified_a_share_market_facts",
    "resolve_formal_a_share_order_quantity_rule",
    "resolve_a_share_order_quantity_rule",
    "VerifiedAShareMarketFacts",
]
