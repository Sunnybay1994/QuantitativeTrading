"""Formal A-share market facts verification and development projections."""

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
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast, final

import polars as pl

from quant.domain import (
    Bar1dSchema,
    BenchmarkBar1dSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    InstrumentSchema,
    OpenExecutionStateSchema,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TradeCalendarSchema,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.m3_release import (
    G1ManifestV5,
    G1Release,
    VerifiedG1Release,
    verify_g1_release,
)
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
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
from quant.backtest.a_share_execution_formal_fact_specs import (
    _FACT_FILES,
    _FORMAL_CAPABILITY_FRAME_BINDINGS,
    _FORMAL_CAPABILITY_FRAME_SLOTS,
    _FORMAL_FACT_SPECS,
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

def _initialize_formal_facts_capability(
    *, registry_module_name: str,
) -> tuple[type[Any], Any]:
    signing_key = secrets.token_bytes(32)
    issued: weakref.WeakSet[Any] = weakref.WeakSet()

    def reject() -> NoReturn:
        raise ValueError(_FORMAL_FACTS_ERROR) from None

    def verify(instance: Any) -> None:
        try:
            module = sys.modules.get(registry_module_name)
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
    _VerifiedAShareMarketFacts.__module__ = registry_module_name

    def public_loader(
        *,
        release: VerifiedG1Release,
        plan: VerifiedBacktestPlanArtifact,
        fresh_context: AShareMarketFactsFreshVerificationContext,
        artifact_roots: Mapping[str, Path],
    ) -> Any:
        try:
            # Resolve via registry module so tests can monkeypatch the facade.
            registry = sys.modules.get(registry_module_name)
            prepare = getattr(
                registry, "_prepare_verified_a_share_market_facts", None
            )
            if prepare is None:
                prepare = _prepare_verified_a_share_market_facts
            identity, selected, provenance = prepare(
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
    registry = sys.modules.get(registry_module_name)
    if registry is None:
        reject()
    setattr(registry, "VerifiedAShareMarketFacts", _VerifiedAShareMarketFacts)
    setattr(registry, "load_verified_a_share_market_facts", public_loader)
    return _VerifiedAShareMarketFacts, public_loader


def _registry_attr(name: str, default: Any) -> Any:
    """Prefer the a_share_execution facade binding so tests can monkeypatch it."""
    registry = sys.modules.get("quant.backtest.a_share_execution")
    if registry is not None and hasattr(registry, name):
        return getattr(registry, name)
    return default


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
    validate_outer = _registry_attr(
        "_validate_formal_facts_outer", _validate_formal_facts_outer
    )
    snapshot_directory = _registry_attr("_snapshot_directory", _snapshot_directory)
    snapshot_file = _registry_attr("_snapshot_regular_file", _snapshot_regular_file)
    verify_g1 = _registry_attr("verify_g1_release", verify_g1_release)
    verify_plan = _registry_attr(
        "verify_backtest_plan_artifact", verify_backtest_plan_artifact
    )
    read_files = _registry_attr("_read_formal_fact_files", _read_formal_fact_files)
    select_facts = _registry_attr(
        "_select_and_validate_formal_facts", _select_and_validate_formal_facts
    )
    fact_digests = _registry_attr("_formal_fact_digests", _formal_fact_digests)

    validate_outer(release, plan, fresh_context, artifact_roots)
    release_root_before = snapshot_directory(release.release.root)
    plan_root_before = snapshot_directory(plan.root)

    fresh_release = verify_g1(release=release.release)
    if not _same_verified_g1(fresh_release, release):
        raise ValueError
    fresh_plan = verify_plan(
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

    raw_frames, raw_bytes, file_entities = read_files(
        fresh_release, artifact_roots
    )
    selected = select_facts(
        raw_frames, fresh_plan, benchmark=benchmark_selector
    )
    digests = fact_digests(
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
        snapshot_directory(release.release.root) != release_root_before
        or snapshot_directory(plan.root) != plan_root_before
        or any(snapshot_file(path) != entity
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


def rebind_capability_for_a_share_execution() -> tuple[type[Any], Any]:
    """(Re)issue the formal facts capability against the a_share_execution facade."""
    global VerifiedAShareMarketFacts, load_verified_a_share_market_facts
    VerifiedAShareMarketFacts, load_verified_a_share_market_facts = (
        _initialize_formal_facts_capability(
            registry_module_name="quant.backtest.a_share_execution",
        )
    )
    # Consumers that imported the class by value must see the rotated type.
    open_mod = sys.modules.get("quant.backtest.a_share_execution_formal_open")
    if open_mod is not None:
        setattr(open_mod, "VerifiedAShareMarketFacts", VerifiedAShareMarketFacts)
    matching = sys.modules.get("quant.backtest.a_share_execution_formal_matching")
    if matching is not None:
        setattr(matching, "VerifiedAShareMarketFacts", VerifiedAShareMarketFacts)
    session = sys.modules.get("quant.backtest.a_share_execution_formal_session")
    if session is not None:
        setattr(session, "VerifiedAShareMarketFacts", VerifiedAShareMarketFacts)
    return VerifiedAShareMarketFacts, load_verified_a_share_market_facts


VerifiedAShareMarketFacts, load_verified_a_share_market_facts = (
    _initialize_formal_facts_capability(
        registry_module_name="quant.backtest.a_share_execution",
    )
)

