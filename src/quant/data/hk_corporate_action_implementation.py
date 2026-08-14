"""Offline capability for source-confirmed HK corporate-action implementation facts.

This module deliberately consumes only explicitly supplied retained bytes.  It
does not infer implementation from dates and does not calculate adjustment or
total-return series.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Never, Protocol, SupportsIndex

import pandera.errors
import polars as pl

from quant.data.hk_corporate_actions import (
    HkCorporateActionSelectionResult,
    VerifiedHkCorporateActionProjection,
    verify_hk_corporate_action_selection_result,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain import HkCorporateActionImplementationEvidenceSchema

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HK_SYMBOL = re.compile(r"^[0-9]{5}\.HK$", flags=re.ASCII)
_RAW_ROLES = frozenset({"MAIN", "SUPPLEMENT", "CORRECTION"})
_REQUIRED_CAPABILITIES = (
    "retained_bytes_verifiable",
    "exact_scope_complete",
    "implementation_status_available",
    "stable_revision_identity_available",
    "correction_history_complete",
    "withdrawal_history_complete",
    "official_confirmed_at_available",
    "source_observed_at_available",
)
_ERROR_CODES = frozenset(
    {
        "HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED",
        "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID",
        "HK_CA_IMPLEMENTATION_SCOPE_INVALID",
        "HK_CA_IMPLEMENTATION_VERIFY_FAILED",
    }
)
_EVIDENCE_COLUMNS = (
    "event_id",
    "symbol",
    "action_type",
    "source",
    "source_event_id",
    "source_revision_id",
    "implementation_status",
    "implementation_effective_date",
    "implementation_confirmed_at",
    "source_observed_at",
    "source_record_id",
    "raw_selector",
    "raw_file_sha256",
    "raw_metadata_sha256",
    "raw_bundle_sha256",
    "p0_actions_content_sha256",
    "p0_evidence_content_sha256",
    "p0_query_sha256",
    "implementation_evidence_sha256",
)
_SEAL = object()
_ATTESTATION_KEY = secrets.token_bytes(32)
_CAPABILITY_KEY = secrets.token_bytes(32)


class HkCorporateActionImplementationError(ValueError):
    """Stable redacted implementation-capability error."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown HK implementation error code")
        self.code = code
        super().__init__(code)


def _fail(code: str) -> HkCorporateActionImplementationError:
    return HkCorporateActionImplementationError(code)


class _ImplementationAttestation:
    __slots__ = ("_digest",)

    def __init__(self, digest: bytes) -> None:
        self._digest = digest

    def __repr__(self) -> str:
        return "<process-local-hk-ca-implementation-attestation>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("process-local HK corporate-action implementation attestation")


@dataclass(frozen=True)
class HkCorporateActionImplementationQuery:
    """Exact P0 result identity and event scope to be implementation-verified."""

    p0_query_sha256: str
    p0_actions_content_sha256: str
    p0_evidence_content_sha256: str
    event_ids: tuple[str, ...]
    as_of: dt.datetime

    def __post_init__(self) -> None:
        if (
            not _digest(self.p0_query_sha256)
            or not _digest(self.p0_actions_content_sha256)
            or not _digest(self.p0_evidence_content_sha256)
            or type(self.event_ids) is not tuple
            or not self.event_ids
            or tuple(sorted(self.event_ids)) != self.event_ids
            or len(set(self.event_ids)) != len(self.event_ids)
            or any(not _digest(item) for item in self.event_ids)
            or not _utc(self.as_of)
        ):
            raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")

    @property
    def identity_sha256(self) -> str:
        return _sha_payload(
            {
                "algorithm": "hk-ca-implementation-query-v1",
                "p0_query_sha256": self.p0_query_sha256,
                "p0_actions_content_sha256": self.p0_actions_content_sha256,
                "p0_evidence_content_sha256": self.p0_evidence_content_sha256,
                "event_ids": self.event_ids,
                "as_of": _json_value(self.as_of),
            }
        )


@dataclass(frozen=True)
class HkCorporateActionImplementationCapability:
    """Source claims required for a complete implementation-fact projection."""

    source: str
    adapter_version: str
    retained_bytes_verifiable: bool
    exact_scope_complete: bool
    implementation_status_available: bool
    stable_revision_identity_available: bool
    correction_history_complete: bool
    withdrawal_history_complete: bool
    official_confirmed_at_available: bool
    source_observed_at_available: bool
    _construction_attestation: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _nonempty(self.source) or not _nonempty(self.adapter_version):
            raise _fail("HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED")
        if any(type(getattr(self, name)) is not bool for name in _REQUIRED_CAPABILITIES):
            raise _fail("HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED")
        object.__setattr__(
            self,
            "_construction_attestation",
            _capability_attestation_digest(self),
        )


@dataclass(frozen=True)
class HkCorporateActionImplementationRawFile:
    """One explicitly supplied implementation source file and metadata."""

    role: str
    content: bytes = field(repr=False)
    metadata: bytes = field(repr=False)
    content_sha256: str
    metadata_sha256: str

    def __post_init__(self) -> None:
        _validate_raw_file(self)

    @classmethod
    def create(
        cls, *, role: str, content: bytes, metadata: bytes
    ) -> HkCorporateActionImplementationRawFile:
        if type(content) is not bytes or type(metadata) is not bytes:
            raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
        return cls(
            role=role,
            content=content,
            metadata=metadata,
            content_sha256=hashlib.sha256(content).hexdigest(),
            metadata_sha256=hashlib.sha256(metadata).hexdigest(),
        )


@dataclass(frozen=True)
class HkCorporateActionImplementationRawBundle:
    """Canonical retained implementation bundle for one exact P0 query."""

    query: HkCorporateActionImplementationQuery
    source: str
    source_issue_id: str
    files: tuple[HkCorporateActionImplementationRawFile, ...]
    source_observed_at: dt.datetime
    coverage_as_of: dt.datetime
    bundle_sha256: str

    def __post_init__(self) -> None:
        _validate_bundle(self)

    @classmethod
    def create(
        cls,
        *,
        query: HkCorporateActionImplementationQuery,
        source: str,
        source_issue_id: str,
        files: tuple[HkCorporateActionImplementationRawFile, ...],
        source_observed_at: dt.datetime,
        coverage_as_of: dt.datetime,
    ) -> HkCorporateActionImplementationRawBundle:
        digest = _bundle_sha256(
            query=query,
            source=source,
            source_issue_id=source_issue_id,
            files=files,
            source_observed_at=source_observed_at,
            coverage_as_of=coverage_as_of,
        )
        return cls(
            query=query,
            source=source,
            source_issue_id=source_issue_id,
            files=files,
            source_observed_at=source_observed_at,
            coverage_as_of=coverage_as_of,
            bundle_sha256=digest,
        )


@dataclass(frozen=True, init=False)
class VerifiedHkCorporateActionImplementationProjection:
    """Parsed or source-verified implementation evidence projection."""

    capability: HkCorporateActionImplementationCapability
    query: HkCorporateActionImplementationQuery
    bundle: HkCorporateActionImplementationRawBundle
    evidence: pl.DataFrame
    evidence_content_sha256: str
    projection_sha256: str
    _seal: object = field(repr=False, compare=False)
    _attestation: _ImplementationAttestation | None = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        capability: HkCorporateActionImplementationCapability,
        query: HkCorporateActionImplementationQuery,
        bundle: HkCorporateActionImplementationRawBundle,
        evidence: pl.DataFrame,
        evidence_content_sha256: str,
        projection_sha256: str,
        _seal: object,
        _attestation: _ImplementationAttestation | None,
    ) -> None:
        if _seal is not _SEAL:
            raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "bundle", bundle)
        object.__setattr__(self, "evidence", evidence.clone())
        object.__setattr__(self, "evidence_content_sha256", evidence_content_sha256)
        object.__setattr__(self, "projection_sha256", projection_sha256)
        object.__setattr__(self, "_seal", _SEAL)
        object.__setattr__(self, "_attestation", _attestation)

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("process-local HK implementation projection")


@dataclass(frozen=True, init=False)
class VerifiedImplementedHkCorporateActionSet:
    """Exact P0 actions paired one-to-one with source-confirmed implementation facts."""

    actions: pl.DataFrame
    implementation_evidence: pl.DataFrame
    p0_query_sha256: str
    p0_actions_content_sha256: str
    p0_evidence_content_sha256: str
    implementation_evidence_content_sha256: str
    projection_sha256: str
    _seal: object = field(repr=False, compare=False)
    _attestation: _ImplementationAttestation = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        actions: pl.DataFrame,
        implementation_evidence: pl.DataFrame,
        p0_query_sha256: str,
        p0_actions_content_sha256: str,
        p0_evidence_content_sha256: str,
        implementation_evidence_content_sha256: str,
        projection_sha256: str,
        _seal: object,
        _attestation: _ImplementationAttestation,
    ) -> None:
        if _seal is not _SEAL:
            raise _fail("HK_CA_IMPLEMENTATION_VERIFY_FAILED")
        object.__setattr__(self, "actions", actions.clone())
        object.__setattr__(self, "implementation_evidence", implementation_evidence.clone())
        object.__setattr__(self, "p0_query_sha256", p0_query_sha256)
        object.__setattr__(self, "p0_actions_content_sha256", p0_actions_content_sha256)
        object.__setattr__(self, "p0_evidence_content_sha256", p0_evidence_content_sha256)
        object.__setattr__(
            self,
            "implementation_evidence_content_sha256",
            implementation_evidence_content_sha256,
        )
        object.__setattr__(self, "projection_sha256", projection_sha256)
        object.__setattr__(self, "_seal", _SEAL)
        object.__setattr__(self, "_attestation", _attestation)

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("process-local verified HK implementation set")


class HkCorporateActionImplementationSourceAdapter(Protocol):
    """Retained-bytes-only implementation source verifier."""

    source: str
    capability: HkCorporateActionImplementationCapability

    def verify_retained(
        self,
        *,
        query: HkCorporateActionImplementationQuery,
        bundle: HkCorporateActionImplementationRawBundle,
    ) -> VerifiedHkCorporateActionImplementationProjection: ...


def build_hk_corporate_action_implementation_projection(
    *,
    capability: HkCorporateActionImplementationCapability,
    query: HkCorporateActionImplementationQuery,
    bundle: HkCorporateActionImplementationRawBundle,
    evidence: pl.DataFrame,
) -> VerifiedHkCorporateActionImplementationProjection:
    """Adapter-facing parsed-only factory; it never signs a consumer capability."""
    error_code: str | None = None
    result: VerifiedHkCorporateActionImplementationProjection | None = None
    try:
        _preflight(capability)
        _validate_bundle(bundle)
        if bundle.query != query or bundle.source != capability.source:
            raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")
        frame = _validate_evidence(evidence, capability, query, bundle)
        content_sha256 = _table_sha256("hk_ca_implementation_evidence", frame)
        result = VerifiedHkCorporateActionImplementationProjection(
            capability=capability,
            query=query,
            bundle=bundle,
            evidence=frame,
            evidence_content_sha256=content_sha256,
            projection_sha256=_projection_sha256(
                capability, query, bundle, content_sha256
            ),
            _seal=_SEAL,
            _attestation=None,
        )
    except HkCorporateActionImplementationError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if result is None:
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    return result


def verify_hk_corporate_action_implementation_source(
    *,
    adapter: HkCorporateActionImplementationSourceAdapter,
    query: HkCorporateActionImplementationQuery,
    bundle: HkCorporateActionImplementationRawBundle,
    p0_result: HkCorporateActionSelectionResult,
    p0_projection: VerifiedHkCorporateActionProjection,
) -> VerifiedHkCorporateActionImplementationProjection:
    """Fresh-verify P0 and retained implementation bytes before signing."""
    error_code: str | None = None
    result: VerifiedHkCorporateActionImplementationProjection | None = None
    try:
        _verify_p0(query, p0_result, p0_projection)
        capability = adapter.capability
        _preflight(capability)
        _validate_bundle(bundle)
        if (
            adapter.source != capability.source
            or bundle.query != query
            or bundle.source != adapter.source
        ):
            raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")
        parsed = adapter.verify_retained(query=query, bundle=bundle)
        _verify_projection_contents(parsed, require_attestation=False)
        _validate_evidence_against_actions(parsed.evidence, p0_result.actions)
        if (
            parsed.capability != capability
            or parsed.query != query
            or parsed.bundle != bundle
        ):
            raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")
        result = VerifiedHkCorporateActionImplementationProjection(
            capability=parsed.capability,
            query=parsed.query,
            bundle=parsed.bundle,
            evidence=parsed.evidence,
            evidence_content_sha256=parsed.evidence_content_sha256,
            projection_sha256=parsed.projection_sha256,
            _seal=_SEAL,
            _attestation=_ImplementationAttestation(
                _projection_attestation_digest(parsed)
            ),
        )
    except HkCorporateActionImplementationError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if result is None:
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    return result


def select_implemented_hk_corporate_actions(
    *,
    projection: VerifiedHkCorporateActionImplementationProjection,
    p0_result: HkCorporateActionSelectionResult,
    p0_projection: VerifiedHkCorporateActionProjection,
) -> VerifiedImplementedHkCorporateActionSet:
    """Issue the exact implemented set after fresh P0 and source verification."""
    error_code: str | None = None
    result: VerifiedImplementedHkCorporateActionSet | None = None
    try:
        _verify_p0(projection.query, p0_result, p0_projection)
        _verify_projection_contents(projection, require_attestation=True)
        result = _build_set(projection, p0_result)
    except HkCorporateActionImplementationError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_IMPLEMENTATION_VERIFY_FAILED"
    if error_code is not None:
        raise _fail(error_code) from None
    if result is None:
        raise _fail("HK_CA_IMPLEMENTATION_VERIFY_FAILED")
    return result


def verify_implemented_hk_corporate_action_set(
    *,
    implemented: VerifiedImplementedHkCorporateActionSet,
    projection: VerifiedHkCorporateActionImplementationProjection,
    p0_result: HkCorporateActionSelectionResult,
    p0_projection: VerifiedHkCorporateActionProjection,
) -> None:
    """Fresh-rebuild the implemented set and compare every bound value."""
    error_code: str | None = None
    try:
        if not isinstance(implemented, VerifiedImplementedHkCorporateActionSet):
            raise _fail("HK_CA_IMPLEMENTATION_VERIFY_FAILED")
        _verify_p0(projection.query, p0_result, p0_projection)
        _verify_projection_contents(projection, require_attestation=True)
        expected = _build_set(projection, p0_result)
        if (
            implemented._seal is not _SEAL
            or not implemented.actions.equals(expected.actions)
            or not implemented.implementation_evidence.equals(
                expected.implementation_evidence
            )
            or implemented.p0_query_sha256 != expected.p0_query_sha256
            or implemented.p0_actions_content_sha256
            != expected.p0_actions_content_sha256
            or implemented.p0_evidence_content_sha256
            != expected.p0_evidence_content_sha256
            or implemented.implementation_evidence_content_sha256
            != expected.implementation_evidence_content_sha256
            or implemented.projection_sha256 != expected.projection_sha256
            or not isinstance(implemented._attestation, _ImplementationAttestation)
            or not hmac.compare_digest(
                implemented._attestation._digest,
                _set_attestation_digest(implemented),
            )
        ):
            raise _fail("HK_CA_IMPLEMENTATION_VERIFY_FAILED")
    except HkCorporateActionImplementationError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_IMPLEMENTATION_VERIFY_FAILED"
    if error_code is not None:
        raise _fail(error_code) from None


def _build_set(
    projection: VerifiedHkCorporateActionImplementationProjection,
    p0_result: HkCorporateActionSelectionResult,
) -> VerifiedImplementedHkCorporateActionSet:
    _validate_evidence_against_actions(projection.evidence, p0_result.actions)
    unsigned = VerifiedImplementedHkCorporateActionSet(
        actions=p0_result.actions,
        implementation_evidence=projection.evidence,
        p0_query_sha256=p0_result.query_identity_sha256,
        p0_actions_content_sha256=p0_result.actions_sha256,
        p0_evidence_content_sha256=p0_result.revision_evidence_sha256,
        implementation_evidence_content_sha256=projection.evidence_content_sha256,
        projection_sha256=projection.projection_sha256,
        _seal=_SEAL,
        _attestation=_ImplementationAttestation(b""),
    )
    return VerifiedImplementedHkCorporateActionSet(
        actions=p0_result.actions,
        implementation_evidence=projection.evidence,
        p0_query_sha256=p0_result.query_identity_sha256,
        p0_actions_content_sha256=p0_result.actions_sha256,
        p0_evidence_content_sha256=p0_result.revision_evidence_sha256,
        implementation_evidence_content_sha256=projection.evidence_content_sha256,
        projection_sha256=projection.projection_sha256,
        _seal=_SEAL,
        _attestation=_ImplementationAttestation(_set_attestation_digest(unsigned)),
    )


def _verify_p0(
    query: HkCorporateActionImplementationQuery,
    p0_result: HkCorporateActionSelectionResult,
    p0_projection: VerifiedHkCorporateActionProjection,
) -> None:
    try:
        verify_hk_corporate_action_selection_result(
            result=p0_result, projection=p0_projection
        )
    except Exception:
        raise _fail("HK_CA_IMPLEMENTATION_VERIFY_FAILED") from None
    event_ids = tuple(sorted(p0_result.actions.get_column("event_id").to_list()))
    if (
        query.p0_query_sha256 != p0_result.query_identity_sha256
        or query.p0_actions_content_sha256 != p0_result.actions_sha256
        or query.p0_evidence_content_sha256 != p0_result.revision_evidence_sha256
        or query.event_ids != event_ids
        or query.as_of != p0_projection.query.as_of
    ):
        raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")


def _verify_projection_contents(
    projection: object, *, require_attestation: bool
) -> None:
    if (
        not isinstance(projection, VerifiedHkCorporateActionImplementationProjection)
        or projection._seal is not _SEAL
    ):
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    _preflight(projection.capability)
    _validate_bundle(projection.bundle)
    if (
        projection.bundle.query != projection.query
        or projection.bundle.source != projection.capability.source
    ):
        raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")
    frame = _validate_evidence(
        projection.evidence,
        projection.capability,
        projection.query,
        projection.bundle,
    )
    content_sha256 = _table_sha256("hk_ca_implementation_evidence", frame)
    if (
        projection.evidence_content_sha256 != content_sha256
        or projection.projection_sha256
        != _projection_sha256(
            projection.capability,
            projection.query,
            projection.bundle,
            content_sha256,
        )
    ):
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    if require_attestation:
        if not isinstance(projection._attestation, _ImplementationAttestation) or not hmac.compare_digest(
            projection._attestation._digest,
            _projection_attestation_digest(projection),
        ):
            raise _fail("HK_CA_IMPLEMENTATION_VERIFY_FAILED")
    elif projection._attestation is not None:
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")


def _validate_evidence(
    evidence: object,
    capability: HkCorporateActionImplementationCapability,
    query: HkCorporateActionImplementationQuery,
    bundle: HkCorporateActionImplementationRawBundle,
) -> pl.DataFrame:
    if not isinstance(evidence, pl.DataFrame) or tuple(evidence.columns) != _EVIDENCE_COLUMNS:
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    frame = evidence.clone()
    expected = frame.sort("event_id")
    if not frame.equals(expected):
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    if tuple(frame.get_column("event_id").to_list()) != query.event_ids:
        raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")
    valid_files = {
        (item.content_sha256, item.metadata_sha256) for item in bundle.files
    }
    for row in frame.iter_rows(named=True):
        if (
            not _HK_SYMBOL.fullmatch(row["symbol"])
            or row["source"] != capability.source
            or row["implementation_status"] != "IMPLEMENTED"
            or not _utc(row["implementation_confirmed_at"])
            or not _utc(row["source_observed_at"])
            or row["implementation_confirmed_at"] > query.as_of
            or row["source_observed_at"] < row["implementation_confirmed_at"]
            or row["source_observed_at"] != bundle.source_observed_at
            or row["implementation_effective_date"]
            > row["implementation_confirmed_at"].date()
            or not _nonempty(row["source_event_id"])
            or not _nonempty(row["source_revision_id"])
            or not _nonempty(row["source_record_id"])
            or not _nonempty(row["raw_selector"])
            or (row["raw_file_sha256"], row["raw_metadata_sha256"])
            not in valid_files
            or row["raw_bundle_sha256"] != bundle.bundle_sha256
            or row["p0_actions_content_sha256"]
            != query.p0_actions_content_sha256
            or row["p0_evidence_content_sha256"]
            != query.p0_evidence_content_sha256
            or row["p0_query_sha256"] != query.p0_query_sha256
            or row["implementation_evidence_sha256"]
            != _implementation_evidence_sha256(row)
        ):
            raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    try:
        HkCorporateActionImplementationEvidenceSchema.validate(frame)
    except (
        pandera.errors.SchemaError,
        pandera.errors.SchemaErrors,
        pl.exceptions.PolarsError,
    ):
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID") from None
    return frame


def _validate_evidence_against_actions(
    evidence: pl.DataFrame, actions: pl.DataFrame
) -> None:
    action_rows = {row["event_id"]: row for row in actions.iter_rows(named=True)}
    if set(action_rows) != set(evidence.get_column("event_id").to_list()):
        raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")
    for row in evidence.iter_rows(named=True):
        action = action_rows[row["event_id"]]
        if any(
            row[name] != action[name]
            for name in (
                "symbol",
                "action_type",
                "source",
                "source_event_id",
                "source_revision_id",
            )
        ):
            raise _fail("HK_CA_IMPLEMENTATION_SCOPE_INVALID")


def _preflight(capability: object) -> None:
    if (
        type(capability) is not HkCorporateActionImplementationCapability
        or not _nonempty(capability.source)
        or not _nonempty(capability.adapter_version)
        or type(capability._construction_attestation) is not bytes
        or not hmac.compare_digest(
            capability._construction_attestation,
            _capability_attestation_digest(capability),
        )
        or any(
            type(getattr(capability, name)) is not bool
            or getattr(capability, name) is not True
            for name in _REQUIRED_CAPABILITIES
        )
    ):
        raise _fail("HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED")


def _capability_attestation_digest(
    capability: HkCorporateActionImplementationCapability,
) -> bytes:
    payload = {
        "algorithm": "hk-ca-implementation-capability-construction-v1",
        "source": capability.source,
        "adapter_version": capability.adapter_version,
        "required_capabilities": {
            name: getattr(capability, name) for name in _REQUIRED_CAPABILITIES
        },
    }
    return hmac.digest(_CAPABILITY_KEY, _canonical_bytes(payload), "sha256")


def _validate_raw_file(item: object) -> None:
    if (
        not isinstance(item, HkCorporateActionImplementationRawFile)
        or type(item.role) is not str
        or item.role not in _RAW_ROLES
        or type(item.content) is not bytes
        or not item.content
        or type(item.metadata) is not bytes
        or not item.metadata
        or hashlib.sha256(item.content).hexdigest() != item.content_sha256
        or hashlib.sha256(item.metadata).hexdigest() != item.metadata_sha256
    ):
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")


def _validate_bundle(bundle: object) -> None:
    if not isinstance(bundle, HkCorporateActionImplementationRawBundle):
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
    if type(bundle.files) is tuple:
        for item in bundle.files:
            _validate_raw_file(item)
    if (
        not isinstance(bundle.query, HkCorporateActionImplementationQuery)
        or not _nonempty(bundle.source)
        or not _nonempty(bundle.source_issue_id)
        or type(bundle.files) is not tuple
        or not bundle.files
        or tuple(
            sorted(
                bundle.files,
                key=lambda item: (
                    item.role,
                    item.content_sha256,
                    item.metadata_sha256,
                ),
            )
        )
        != bundle.files
        or len(
            {
                (item.role, item.content_sha256, item.metadata_sha256)
                for item in bundle.files
            }
        )
        != len(bundle.files)
        or not _utc(bundle.source_observed_at)
        or not _utc(bundle.coverage_as_of)
        or bundle.coverage_as_of < bundle.query.as_of
        or bundle.bundle_sha256
        != _bundle_sha256(
            query=bundle.query,
            source=bundle.source,
            source_issue_id=bundle.source_issue_id,
            files=bundle.files,
            source_observed_at=bundle.source_observed_at,
            coverage_as_of=bundle.coverage_as_of,
        )
    ):
        raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")


def _bundle_sha256(**values: Any) -> str:
    return _sha_payload(
        {
            "algorithm": "hk-ca-implementation-raw-bundle-v1",
            "query_sha256": values["query"].identity_sha256,
            "source": values["source"],
            "source_issue_id": values["source_issue_id"],
            "files": [
                [item.role, item.content_sha256, item.metadata_sha256]
                for item in values["files"]
            ],
            "source_observed_at": _json_value(values["source_observed_at"]),
            "coverage_as_of": _json_value(values["coverage_as_of"]),
        }
    )


def _implementation_evidence_sha256(row: dict[str, Any]) -> str:
    return _sha_payload(
        {
            "algorithm": "hk-ca-implementation-evidence-v1",
            **{
                name: _json_value(row[name])
                for name in _EVIDENCE_COLUMNS
                if name != "implementation_evidence_sha256"
            },
        }
    )


def _projection_sha256(
    capability: HkCorporateActionImplementationCapability,
    query: HkCorporateActionImplementationQuery,
    bundle: HkCorporateActionImplementationRawBundle,
    evidence_content_sha256: str,
) -> str:
    return _sha_payload(
        {
            "algorithm": "hk-ca-implementation-projection-v1",
            "source": capability.source,
            "adapter_version": capability.adapter_version,
            "query_sha256": query.identity_sha256,
            "bundle_sha256": bundle.bundle_sha256,
            "evidence_content_sha256": evidence_content_sha256,
        }
    )


def _projection_attestation_digest(
    projection: VerifiedHkCorporateActionImplementationProjection,
) -> bytes:
    payload = {
        "algorithm": "hk-ca-implementation-process-attestation-v1",
        "source": projection.capability.source,
        "adapter_version": projection.capability.adapter_version,
        "query_sha256": projection.query.identity_sha256,
        "bundle_sha256": projection.bundle.bundle_sha256,
        "evidence_content_sha256": projection.evidence_content_sha256,
        "projection_sha256": projection.projection_sha256,
    }
    return hmac.digest(_ATTESTATION_KEY, _canonical_bytes(payload), "sha256")


def _set_attestation_digest(value: VerifiedImplementedHkCorporateActionSet) -> bytes:
    payload = {
        "algorithm": "hk-ca-implemented-set-process-attestation-v1",
        "p0_query_sha256": value.p0_query_sha256,
        "p0_actions_content_sha256": value.p0_actions_content_sha256,
        "p0_evidence_content_sha256": value.p0_evidence_content_sha256,
        "implementation_evidence_content_sha256": value.implementation_evidence_content_sha256,
        "projection_sha256": value.projection_sha256,
    }
    return hmac.digest(_ATTESTATION_KEY, _canonical_bytes(payload), "sha256")


def _table_sha256(table_name: str, frame: pl.DataFrame) -> str:
    expressions: list[pl.Expr] = []
    for name, dtype in frame.schema.items():
        if isinstance(dtype, pl.Datetime):
            expressions.append(
                pl.col(name).dt.strftime("%Y-%m-%dT%H:%M:%S%.9fZ").alias(name)
            )
    normalized = frame.with_columns(expressions) if expressions else frame
    return clean_table_content_sha256(table_name=table_name, frame=normalized)


def _evidence_schema() -> dict[str, pl.DataType]:
    string = pl.String()
    return {
        "event_id": string,
        "symbol": string,
        "action_type": string,
        "source": string,
        "source_event_id": string,
        "source_revision_id": string,
        "implementation_status": string,
        "implementation_effective_date": pl.Date(),
        "implementation_confirmed_at": pl.Datetime(time_zone="UTC"),
        "source_observed_at": pl.Datetime(time_zone="UTC"),
        "source_record_id": string,
        "raw_selector": string,
        "raw_file_sha256": string,
        "raw_metadata_sha256": string,
        "raw_bundle_sha256": string,
        "p0_actions_content_sha256": string,
        "p0_evidence_content_sha256": string,
        "p0_query_sha256": string,
        "implementation_evidence_sha256": string,
    }


def _sha_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _json_value(value: object) -> object:
    if isinstance(value, dt.datetime):
        if not _utc(value):
            raise _fail("HK_CA_IMPLEMENTATION_EVIDENCE_INVALID")
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if type(value) is dt.date:
        return value.isoformat()
    return value


def _digest(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _utc(value: object) -> bool:
    return (
        isinstance(value, dt.datetime)
        and value.tzinfo is not None
        and value.utcoffset() == dt.timedelta(0)
    )


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


__all__ = [
    "HkCorporateActionImplementationCapability",
    "HkCorporateActionImplementationError",
    "HkCorporateActionImplementationQuery",
    "HkCorporateActionImplementationRawBundle",
    "HkCorporateActionImplementationRawFile",
    "HkCorporateActionImplementationSourceAdapter",
    "VerifiedHkCorporateActionImplementationProjection",
    "VerifiedImplementedHkCorporateActionSet",
    "build_hk_corporate_action_implementation_projection",
    "select_implemented_hk_corporate_actions",
    "verify_hk_corporate_action_implementation_source",
    "verify_implemented_hk_corporate_action_set",
]
