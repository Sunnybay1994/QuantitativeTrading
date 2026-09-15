"""Offline, source-neutral HK corporate-action PIT selection contract.

The module consumes only explicitly supplied retained bytes.  It intentionally
contains no connector, path discovery, network, adjustment-factor, total-return,
or account-ledger behavior.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Never, Protocol, SupportsIndex

import pandera.errors
import polars as pl

from quant.data.m3_identity import clean_table_content_sha256
from quant.domain import (
    CorporateActionSchema,
    CorporateActionType,
    Currency,
    HkCorporateActionRevisionEvidenceSchema,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HK_SYMBOL = re.compile(r"^[0-9]{5}\.HK$", flags=re.ASCII)
_RAW_ROLES = frozenset({"MAIN", "SUPPLEMENT", "CORRECTION"})
_REQUIRED_CAPABILITIES = (
    "retained_bytes_verifiable",
    "official_published_at_available",
    "stable_event_identity_available",
    "stable_revision_identity_available",
    "revision_predecessor_available",
    "withdrawal_history_complete",
    "correction_supplement_closure_complete",
    "scope_completeness_verifiable",
)
_ERROR_CODES = frozenset(
    {
        "HK_CA_INPUT_INVALID",
        "HK_CA_CAPABILITY_UNSUPPORTED",
        "HK_CA_EVIDENCE_INVALID",
        "HK_CA_REVISION_CONFLICT",
        "HK_CA_ACTION_UNSUPPORTED",
        "HK_CA_RESULT_INVALID",
    }
)
_CANDIDATE_COLUMNS = (
    "economic_event_key_sha256",
    "candidate_id",
    "symbol",
    "action_type",
    "source",
    "source_event_id",
    "source_revision_id",
    "revision_sequence",
    "predecessor_candidate_id",
    "revision_status",
    "published_at",
    "source_observed_at",
    "record_date",
    "ex_date",
    "pay_date",
    "stock_list_date",
    "declared_currency",
    "cash_per_share_gross",
    "stock_ratio",
    "share_multiplier",
    "rights_ratio",
    "rights_subscription_price",
    "rights_subscription_start",
    "rights_subscription_end",
    "raw_bundle_sha256",
    "raw_file_sha256",
    "raw_metadata_sha256",
    "raw_selector",
)
_ACTION_COLUMNS = (
    "event_id",
    "symbol",
    "action_type",
    "record_date",
    "ex_date",
    "pay_date",
    "stock_list_date",
    "declared_currency",
    "cash_per_share_gross",
    "stock_ratio",
    "share_multiplier",
    "rights_ratio",
    "rights_subscription_price",
    "rights_subscription_start",
    "rights_subscription_end",
    "announce_time",
    "source",
    "source_event_id",
    "source_revision_id",
    "source_snapshot_sha256",
)
_SEAL = object()
_ATTESTATION_KEY = secrets.token_bytes(32)


class _ProjectionAttestation:
    """Opaque process-local proof that the source wrapper verified exact content."""

    __slots__ = ("_digest",)

    def __init__(self, digest: bytes) -> None:
        self._digest = digest

    def __repr__(self) -> str:
        return "<process-local-hk-ca-attestation>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("process-local HK corporate-action attestation")


class HkCorporateActionError(ValueError):
    """Stable, redacted HK corporate-action boundary error."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown HK corporate-action error code")
        self.code = code
        super().__init__(code)


def _fail(code: str) -> HkCorporateActionError:
    return HkCorporateActionError(code)


@dataclass(frozen=True)
class HkCorporateActionQuery:
    """Strict, deterministic HK corporate-action PIT query."""

    symbols: tuple[str, ...]
    event_date_start: dt.date
    event_date_end: dt.date
    as_of: dt.datetime
    required_action_types: tuple[CorporateActionType, ...]
    accepted_currencies: tuple[Currency, ...]

    def __post_init__(self) -> None:
        try:
            _validate_query(self)
        except HkCorporateActionError:
            raise
        except Exception:
            raise _fail("HK_CA_INPUT_INVALID") from None

    @property
    def identity_sha256(self) -> str:
        return _query_sha256(self)


@dataclass(frozen=True)
class HkCorporateActionCapability:
    """Source claims required for complete offline PIT projection."""

    source: str
    adapter_version: str
    supported_action_types: tuple[CorporateActionType, ...]
    supported_currencies: tuple[Currency, ...]
    retained_bytes_verifiable: bool
    official_published_at_available: bool
    stable_event_identity_available: bool
    stable_revision_identity_available: bool
    revision_predecessor_available: bool
    withdrawal_history_complete: bool
    correction_supplement_closure_complete: bool
    scope_completeness_verifiable: bool

    def __post_init__(self) -> None:
        if not _nonempty(self.source) or not _nonempty(self.adapter_version):
            raise _fail("HK_CA_INPUT_INVALID")
        _validate_sorted_enums(self.supported_action_types, CorporateActionType)
        _validate_sorted_enums(self.supported_currencies, Currency)
        for name in _REQUIRED_CAPABILITIES:
            if type(getattr(self, name)) is not bool:
                raise _fail("HK_CA_INPUT_INVALID")


@dataclass(frozen=True)
class HkCorporateActionRawFile:
    """One explicit retained source file and its retained metadata bytes."""

    role: str
    content: bytes = field(repr=False)
    metadata: bytes = field(repr=False)
    content_sha256: str
    metadata_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.role) is not str
            or self.role not in _RAW_ROLES
            or type(self.content) is not bytes
            or not self.content
            or type(self.metadata) is not bytes
            or not self.metadata
            or self.content_sha256 != hashlib.sha256(self.content).hexdigest()
            or self.metadata_sha256 != hashlib.sha256(self.metadata).hexdigest()
        ):
            raise _fail("HK_CA_EVIDENCE_INVALID")

    @classmethod
    def create(cls, *, role: str, content: bytes, metadata: bytes) -> HkCorporateActionRawFile:
        """Create a file while deriving both declared digests from retained bytes."""
        if type(content) is not bytes or type(metadata) is not bytes:
            raise _fail("HK_CA_EVIDENCE_INVALID")
        return cls(
            role=role,
            content=content,
            metadata=metadata,
            content_sha256=hashlib.sha256(content).hexdigest(),
            metadata_sha256=hashlib.sha256(metadata).hexdigest(),
        )


@dataclass(frozen=True)
class HkCorporateActionRawBundle:
    """Canonical explicit retained-file bundle bound to one query and source issue."""

    query: HkCorporateActionQuery
    source: str
    source_issue_id: str
    files: tuple[HkCorporateActionRawFile, ...]
    source_observed_at: dt.datetime
    coverage_as_of: dt.datetime
    bundle_sha256: str

    def __post_init__(self) -> None:
        _validate_bundle(self)

    @classmethod
    def create(
        cls,
        *,
        query: HkCorporateActionQuery,
        source: str,
        source_issue_id: str,
        files: tuple[HkCorporateActionRawFile, ...],
        source_observed_at: dt.datetime,
        coverage_as_of: dt.datetime,
    ) -> HkCorporateActionRawBundle:
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
class VerifiedHkCorporateActionProjection:
    """Fresh-verifiable full revision projection created by an adapter verifier."""

    capability: HkCorporateActionCapability
    query: HkCorporateActionQuery
    bundle: HkCorporateActionRawBundle
    candidates: pl.DataFrame
    projection_sha256: str
    _seal: object = field(repr=False, compare=False)
    _attestation: _ProjectionAttestation | None = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        capability: HkCorporateActionCapability,
        query: HkCorporateActionQuery,
        bundle: HkCorporateActionRawBundle,
        candidates: pl.DataFrame,
        projection_sha256: str,
        _seal: object,
        _attestation: _ProjectionAttestation | None,
    ) -> None:
        if _seal is not _SEAL:
            raise _fail("HK_CA_EVIDENCE_INVALID")
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "bundle", bundle)
        object.__setattr__(self, "candidates", candidates.clone())
        object.__setattr__(self, "projection_sha256", projection_sha256)
        object.__setattr__(self, "_seal", _SEAL)
        object.__setattr__(self, "_attestation", _attestation)

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("process-local HK corporate-action projection")


@dataclass(frozen=True, init=False)
class HkCorporateActionSelectionResult:
    """Canonical actions plus complete per-revision selection evidence."""

    actions: pl.DataFrame
    revision_evidence: pl.DataFrame
    actions_sha256: str
    revision_evidence_sha256: str
    query_identity_sha256: str
    _seal: object = field(repr=False, compare=False)

    def __init__(
        self,
        *,
        actions: pl.DataFrame,
        revision_evidence: pl.DataFrame,
        actions_sha256: str,
        revision_evidence_sha256: str,
        query_identity_sha256: str,
        _seal: object,
    ) -> None:
        if _seal is not _SEAL:
            raise _fail("HK_CA_RESULT_INVALID")
        object.__setattr__(self, "actions", actions.clone())
        object.__setattr__(self, "revision_evidence", revision_evidence.clone())
        object.__setattr__(self, "actions_sha256", actions_sha256)
        object.__setattr__(self, "revision_evidence_sha256", revision_evidence_sha256)
        object.__setattr__(self, "query_identity_sha256", query_identity_sha256)
        object.__setattr__(self, "_seal", _SEAL)


class HkCorporateActionSourceAdapter(Protocol):
    """Narrow retained-bytes-only source verifier protocol."""

    source: str
    capability: HkCorporateActionCapability

    def verify_retained(
        self,
        *,
        query: HkCorporateActionQuery,
        bundle: HkCorporateActionRawBundle,
    ) -> VerifiedHkCorporateActionProjection: ...


def verify_hk_corporate_action_source(
    *,
    adapter: HkCorporateActionSourceAdapter,
    query: HkCorporateActionQuery,
    bundle: HkCorporateActionRawBundle,
) -> VerifiedHkCorporateActionProjection:
    """Preflight capability before allowing an adapter to parse retained bytes."""
    error_code: str | None = None
    verified: VerifiedHkCorporateActionProjection | None = None
    try:
        if not isinstance(query, HkCorporateActionQuery) or not isinstance(
            bundle, HkCorporateActionRawBundle
        ):
            raise _fail("HK_CA_INPUT_INVALID")
        capability = adapter.capability
        if adapter.source != capability.source:
            raise _fail("HK_CA_EVIDENCE_INVALID")
        _preflight(capability, query)
        _validate_bundle(bundle)
        if bundle.query != query or bundle.source != adapter.source:
            raise _fail("HK_CA_EVIDENCE_INVALID")
        candidate = adapter.verify_retained(query=query, bundle=bundle)
        _verify_adapter_parsed_projection(candidate)
        if (
            candidate.capability != capability
            or candidate.query != query
            or candidate.bundle != bundle
        ):
            raise _fail("HK_CA_EVIDENCE_INVALID")
        verified = VerifiedHkCorporateActionProjection(
            capability=candidate.capability,
            query=candidate.query,
            bundle=candidate.bundle,
            candidates=candidate.candidates,
            projection_sha256=candidate.projection_sha256,
            _seal=_SEAL,
            _attestation=_ProjectionAttestation(
                _projection_attestation_digest(candidate)
            ),
        )
    except HkCorporateActionError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_EVIDENCE_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if verified is None:
        raise _fail("HK_CA_EVIDENCE_INVALID")
    return verified


def build_verified_hk_corporate_action_projection(
    *,
    capability: HkCorporateActionCapability,
    query: HkCorporateActionQuery,
    bundle: HkCorporateActionRawBundle,
    candidates: pl.DataFrame,
) -> VerifiedHkCorporateActionProjection:
    """Adapter-facing factory that validates complete parsed revision evidence."""
    error_code: str | None = None
    verified: VerifiedHkCorporateActionProjection | None = None
    try:
        _preflight(capability, query)
        _validate_bundle(bundle)
        if bundle.query != query or bundle.source != capability.source:
            raise _fail("HK_CA_EVIDENCE_INVALID")
        frame = _validate_and_clone_candidates(candidates, capability, query, bundle)
        _select_frames(frame, query, bundle)
        digest = _projection_sha256(capability, query, bundle, frame)
        verified = VerifiedHkCorporateActionProjection(
            capability=capability,
            query=query,
            bundle=bundle,
            candidates=frame,
            projection_sha256=digest,
            _seal=_SEAL,
            _attestation=None,
        )
    except HkCorporateActionError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_EVIDENCE_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if verified is None:
        raise _fail("HK_CA_EVIDENCE_INVALID")
    return verified


def select_hk_corporate_actions(
    *, projection: VerifiedHkCorporateActionProjection
) -> HkCorporateActionSelectionResult:
    """Fresh-verify a projection and deterministically select revisions as of query time."""
    error_code: str | None = None
    result: HkCorporateActionSelectionResult | None = None
    try:
        _verify_projection(projection)
        actions, evidence = _select_frames(
            projection.candidates, projection.query, projection.bundle
        )
        result = HkCorporateActionSelectionResult(
            actions=actions,
            revision_evidence=evidence,
            actions_sha256=_table_sha256("hk_corporate_actions", actions),
            revision_evidence_sha256=_table_sha256(
                "hk_corporate_action_revision_evidence", evidence
            ),
            query_identity_sha256=projection.query.identity_sha256,
            _seal=_SEAL,
        )
    except HkCorporateActionError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_EVIDENCE_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if result is None:
        raise _fail("HK_CA_EVIDENCE_INVALID")
    return result


def verify_hk_corporate_action_selection_result(
    *,
    result: HkCorporateActionSelectionResult,
    projection: VerifiedHkCorporateActionProjection,
) -> None:
    """Fresh-rebuild all output rows, ordering, identities, links and content digests."""
    error_code: str | None = None
    try:
        if not isinstance(result, HkCorporateActionSelectionResult):
            error_code = "HK_CA_RESULT_INVALID"
        else:
            _verify_projection(projection)
            actions, evidence = _select_frames(
                projection.candidates, projection.query, projection.bundle
            )
            if (
                result.query_identity_sha256 != projection.query.identity_sha256
                or not result.actions.equals(actions)
                or not result.revision_evidence.equals(evidence)
                or result.actions_sha256 != _table_sha256("hk_corporate_actions", actions)
                or result.revision_evidence_sha256
                != _table_sha256("hk_corporate_action_revision_evidence", evidence)
            ):
                error_code = "HK_CA_RESULT_INVALID"
    except HkCorporateActionError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_CA_RESULT_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None


def _verify_projection(projection: object) -> None:
    _verify_projection_contents(projection)
    if not isinstance(projection, VerifiedHkCorporateActionProjection):
        raise _fail("HK_CA_EVIDENCE_INVALID")
    attestation = projection._attestation
    if not isinstance(attestation, _ProjectionAttestation) or not hmac.compare_digest(
        attestation._digest, _projection_attestation_digest(projection)
    ):
        raise _fail("HK_CA_EVIDENCE_INVALID")


def _verify_adapter_parsed_projection(projection: object) -> None:
    _verify_projection_contents(projection)
    if (
        not isinstance(projection, VerifiedHkCorporateActionProjection)
        or projection._attestation is not None
    ):
        raise _fail("HK_CA_EVIDENCE_INVALID")


def _verify_projection_contents(projection: object) -> None:
    if (
        not isinstance(projection, VerifiedHkCorporateActionProjection)
        or projection._seal is not _SEAL
    ):
        raise _fail("HK_CA_EVIDENCE_INVALID")
    _preflight(projection.capability, projection.query)
    _validate_bundle(projection.bundle)
    if (
        projection.bundle.query != projection.query
        or projection.bundle.source != projection.capability.source
    ):
        raise _fail("HK_CA_EVIDENCE_INVALID")
    frame = _validate_and_clone_candidates(
        projection.candidates,
        projection.capability,
        projection.query,
        projection.bundle,
    )
    if projection.projection_sha256 != _projection_sha256(
        projection.capability, projection.query, projection.bundle, frame
    ):
        raise _fail("HK_CA_EVIDENCE_INVALID")
    _select_frames(frame, projection.query, projection.bundle)


def _projection_attestation_digest(
    projection: VerifiedHkCorporateActionProjection,
) -> bytes:
    payload = {
        "algorithm": "hk-corporate-action-process-attestation-v1",
        "source": projection.capability.source,
        "adapter_version": projection.capability.adapter_version,
        "query_sha256": projection.query.identity_sha256,
        "bundle_sha256": projection.bundle.bundle_sha256,
        "candidates_sha256": _table_sha256(
            "hk_corporate_action_candidates", projection.candidates
        ),
        "projection_sha256": projection.projection_sha256,
    }
    message = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hmac.digest(_ATTESTATION_KEY, message, "sha256")


def _select_frames(
    candidates: pl.DataFrame,
    query: HkCorporateActionQuery,
    bundle: HkCorporateActionRawBundle,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    rows = candidates.to_dicts()
    by_event: dict[tuple[str, str], list[dict[str, Any]]] = {}
    revision_ids: dict[tuple[str, str], str] = {}
    candidate_ids: dict[str, tuple[str, str]] = {}
    for row in rows:
        event = (row["source"], row["source_event_id"])
        prior_event = revision_ids.get((row["source"], row["source_revision_id"]))
        if prior_event is not None and prior_event != row["source_event_id"]:
            raise _fail("HK_CA_REVISION_CONFLICT")
        revision_ids[(row["source"], row["source_revision_id"])] = row["source_event_id"]
        if row["candidate_id"] in candidate_ids:
            raise _fail("HK_CA_REVISION_CONFLICT")
        candidate_ids[row["candidate_id"]] = event
        by_event.setdefault(event, []).append(row)

    action_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for event in sorted(by_event):
        group = sorted(by_event[event], key=lambda item: item["revision_sequence"])
        first = group[0]
        expected_key = _event_key(first)
        previous_id: str | None = None
        previous_published: dt.datetime | None = None
        for sequence, row in enumerate(group, start=1):
            if (
                row["revision_sequence"] != sequence
                or row["predecessor_candidate_id"] != previous_id
                or row["economic_event_key_sha256"] != expected_key
                or row["symbol"] != first["symbol"]
                or row["action_type"] != first["action_type"]
                or row["candidate_id"] != _candidate_id(row)
            ):
                raise _fail("HK_CA_REVISION_CONFLICT")
            published = row["published_at"]
            if previous_published is not None and published <= previous_published:
                raise _fail("HK_CA_REVISION_CONFLICT")
            previous_id = row["candidate_id"]
            previous_published = published

        known = [item for item in group if item["published_at"] <= query.as_of]
        selected = known[-1] if known else None
        for row in group:
            is_selected = row is selected
            if row["published_at"] > query.as_of:
                reason = "FUTURE_AS_OF"
            elif is_selected and row["revision_status"] == "ACTIVE":
                reason = "SELECTED_AS_OF"
            elif is_selected:
                reason = "WITHDRAWN_AS_OF"
            else:
                reason = "SUPERSEDED_AS_OF"
            evidence_rows.append(
                {**row, "selected": is_selected, "selection_reason": reason, "query_as_of": query.as_of}
            )
        if selected is not None and selected["revision_status"] == "ACTIVE":
            action_rows.append(_canonical_action(selected, bundle.bundle_sha256))

    actions = _actions_frame(action_rows)
    evidence = _evidence_frame(evidence_rows)
    try:
        CorporateActionSchema.validate(actions)
        HkCorporateActionRevisionEvidenceSchema.validate(evidence)
    except (pandera.errors.SchemaError, pandera.errors.SchemaErrors, pl.exceptions.PolarsError):
        raise _fail("HK_CA_REVISION_CONFLICT") from None
    return actions, evidence


def _validate_and_clone_candidates(
    candidates: object,
    capability: HkCorporateActionCapability,
    query: HkCorporateActionQuery,
    bundle: HkCorporateActionRawBundle,
) -> pl.DataFrame:
    if not isinstance(candidates, pl.DataFrame) or tuple(candidates.columns) != _CANDIDATE_COLUMNS:
        raise _fail("HK_CA_EVIDENCE_INVALID")
    frame = candidates.clone()
    if frame.height == 0:
        return _candidate_frame([])
    valid_files = {
        (item.content_sha256, item.metadata_sha256) for item in bundle.files
    }
    for row in frame.iter_rows(named=True):
        _validate_candidate_row(row, capability, query, bundle, valid_files)
    expected = frame.sort(["source", "source_event_id", "revision_sequence"])
    if not frame.equals(expected):
        raise _fail("HK_CA_EVIDENCE_INVALID")
    return frame


def _validate_candidate_row(
    row: dict[str, Any],
    capability: HkCorporateActionCapability,
    query: HkCorporateActionQuery,
    bundle: HkCorporateActionRawBundle,
    valid_files: set[tuple[str, str]],
) -> None:
    if (
        type(row["symbol"]) is not str
        or not _HK_SYMBOL.fullmatch(row["symbol"])
        or row["symbol"] not in query.symbols
        or row["action_type"] not in {item.value for item in query.required_action_types}
        or row["action_type"] not in {item.value for item in capability.supported_action_types}
        or row["source"] != capability.source
        or not _nonempty(row["source_event_id"])
        or not _nonempty(row["source_revision_id"])
        or type(row["revision_sequence"]) is not int
        or row["revision_sequence"] <= 0
        or row["revision_status"] not in {"ACTIVE", "WITHDRAWN"}
        or not _utc(row["published_at"])
        or not _utc(row["source_observed_at"])
        or row["source_observed_at"] < row["published_at"]
        or row["source_observed_at"] != bundle.source_observed_at
        or row["raw_bundle_sha256"] != bundle.bundle_sha256
        or (row["raw_file_sha256"], row["raw_metadata_sha256"]) not in valid_files
        or not _nonempty(row["raw_selector"])
        or not _HEX64.fullmatch(row["economic_event_key_sha256"])
        or not _HEX64.fullmatch(row["candidate_id"])
    ):
        raise _fail("HK_CA_EVIDENCE_INVALID")
    if row["predecessor_candidate_id"] is not None and (
        type(row["predecessor_candidate_id"]) is not str
        or not _HEX64.fullmatch(row["predecessor_candidate_id"])
    ):
        raise _fail("HK_CA_REVISION_CONFLICT")
    if (
        type(row["record_date"]) is not dt.date
        or type(row["record_date"]) is dt.datetime
        or type(row["ex_date"]) is not dt.date
        or type(row["ex_date"]) is dt.datetime
        or not (query.event_date_start <= row["ex_date"] <= query.event_date_end)
    ):
        raise _fail("HK_CA_ACTION_UNSUPPORTED")
    _validate_economics(row, query)


def _validate_economics(row: dict[str, Any], query: HkCorporateActionQuery) -> None:
    date_names = (
        "record_date", "ex_date", "pay_date", "stock_list_date",
        "rights_subscription_start", "rights_subscription_end",
    )
    for name in date_names:
        value = row[name]
        if value is not None and (type(value) is not dt.date or type(value) is dt.datetime):
            raise _fail("HK_CA_ACTION_UNSUPPORTED")
    number_names = (
        "cash_per_share_gross", "stock_ratio", "share_multiplier",
        "rights_ratio", "rights_subscription_price",
    )
    for name in number_names:
        value = row[name]
        if value is not None and (
            type(value) not in {int, float} or not math.isfinite(float(value)) or value <= 0
        ):
            raise _fail("HK_CA_ACTION_UNSUPPORTED")
    if row["record_date"] > row["ex_date"]:
        raise _fail("HK_CA_ACTION_UNSUPPORTED")
    currency = row["declared_currency"]
    if currency is not None and currency not in {item.value for item in query.accepted_currencies}:
        raise _fail("HK_CA_ACTION_UNSUPPORTED")
    action = row["action_type"]
    def null(*names: str) -> bool:
        return all(row[name] is None for name in names)
    if action == "DIVIDEND":
        valid = (
            currency is not None
            and row["cash_per_share_gross"] is not None
            and row["pay_date"] is not None
            and row["pay_date"] >= row["ex_date"]
            and null("stock_list_date", "stock_ratio", "share_multiplier", "rights_ratio", "rights_subscription_price", "rights_subscription_start", "rights_subscription_end")
        )
    elif action == "BONUS":
        valid = (
            currency is None and row["stock_ratio"] is not None
            and row["stock_list_date"] is not None and row["stock_list_date"] >= row["ex_date"]
            and null("pay_date", "cash_per_share_gross", "share_multiplier", "rights_ratio", "rights_subscription_price", "rights_subscription_start", "rights_subscription_end")
        )
    elif action == "SPLIT":
        valid = (
            currency is None and row["share_multiplier"] is not None
            and row["share_multiplier"] != 1
            and row["stock_list_date"] is not None and row["stock_list_date"] >= row["ex_date"]
            and null("pay_date", "cash_per_share_gross", "stock_ratio", "rights_ratio", "rights_subscription_price", "rights_subscription_start", "rights_subscription_end")
        )
    elif action == "RIGHTS":
        start, end, listed = row["rights_subscription_start"], row["rights_subscription_end"], row["stock_list_date"]
        valid = (
            currency is not None and row["rights_ratio"] is not None
            and row["rights_subscription_price"] is not None
            and start is not None and end is not None and listed is not None
            and row["ex_date"] <= start <= end <= listed
            and null("pay_date", "cash_per_share_gross", "stock_ratio", "share_multiplier")
        )
    else:
        raise _fail("HK_CA_ACTION_UNSUPPORTED")
    if not valid:
        raise _fail("HK_CA_ACTION_UNSUPPORTED")


def _canonical_action(row: dict[str, Any], snapshot: str) -> dict[str, Any]:
    return {
        "event_id": _sha_payload(["hk-corporate-action-event-v1", row["economic_event_key_sha256"], row["candidate_id"]]),
        "symbol": row["symbol"], "action_type": row["action_type"],
        "record_date": row["record_date"], "ex_date": row["ex_date"],
        "pay_date": row["pay_date"], "stock_list_date": row["stock_list_date"],
        "declared_currency": row["declared_currency"],
        "cash_per_share_gross": row["cash_per_share_gross"], "stock_ratio": row["stock_ratio"],
        "share_multiplier": row["share_multiplier"], "rights_ratio": row["rights_ratio"],
        "rights_subscription_price": row["rights_subscription_price"],
        "rights_subscription_start": row["rights_subscription_start"],
        "rights_subscription_end": row["rights_subscription_end"],
        "announce_time": row["published_at"], "source": row["source"],
        "source_event_id": row["source_event_id"], "source_revision_id": row["source_revision_id"],
        "source_snapshot_sha256": snapshot,
    }


def _event_key(row: dict[str, Any]) -> str:
    return _sha_payload(["hk-corporate-action-economic-event-v1", row["source"], row["source_event_id"], row["symbol"], row["action_type"]])


def _candidate_id(row: dict[str, Any]) -> str:
    values = ["hk-corporate-action-candidate-v1", row["economic_event_key_sha256"]]
    for name in _CANDIDATE_COLUMNS[2:]:
        if name != "candidate_id":
            values.append(_json_value(row[name]))
    return _sha_payload(values)


def _preflight(capability: HkCorporateActionCapability, query: HkCorporateActionQuery) -> None:
    if not isinstance(capability, HkCorporateActionCapability):
        raise _fail("HK_CA_CAPABILITY_UNSUPPORTED")
    if any(getattr(capability, name) is not True for name in _REQUIRED_CAPABILITIES):
        raise _fail("HK_CA_CAPABILITY_UNSUPPORTED")
    if not set(query.required_action_types).issubset(capability.supported_action_types) or not set(
        query.accepted_currencies
    ).issubset(capability.supported_currencies):
        raise _fail("HK_CA_CAPABILITY_UNSUPPORTED")


def _validate_query(query: HkCorporateActionQuery) -> None:
    if (
        type(query.symbols) is not tuple or not query.symbols
        or any(type(item) is not str or not _HK_SYMBOL.fullmatch(item) for item in query.symbols)
        or tuple(sorted(query.symbols)) != query.symbols or len(set(query.symbols)) != len(query.symbols)
        or type(query.event_date_start) is not dt.date or type(query.event_date_start) is dt.datetime
        or type(query.event_date_end) is not dt.date or type(query.event_date_end) is dt.datetime
        or query.event_date_start > query.event_date_end or not _utc(query.as_of)
    ):
        raise _fail("HK_CA_INPUT_INVALID")
    _validate_sorted_enums(query.required_action_types, CorporateActionType)
    _validate_sorted_enums(query.accepted_currencies, Currency)


def _validate_sorted_enums(values: object, enum_type: type[Any]) -> None:
    if (
        type(values) is not tuple or not values
        or any(type(item) is not enum_type for item in values)
        or tuple(sorted(values, key=lambda item: item.value)) != values
        or len(set(values)) != len(values)
    ):
        raise _fail("HK_CA_INPUT_INVALID")


def _validate_bundle(bundle: HkCorporateActionRawBundle) -> None:
    if not isinstance(bundle, HkCorporateActionRawBundle):
        raise _fail("HK_CA_EVIDENCE_INVALID")
    for item in bundle.files if type(bundle.files) is tuple else ():
        if (
            not isinstance(item, HkCorporateActionRawFile)
            or type(item.role) is not str
            or item.role not in _RAW_ROLES
            or type(item.content) is not bytes
            or not item.content
            or type(item.metadata) is not bytes
            or not item.metadata
            or type(item.content_sha256) is not str
            or not _HEX64.fullmatch(item.content_sha256)
            or type(item.metadata_sha256) is not str
            or not _HEX64.fullmatch(item.metadata_sha256)
            or hashlib.sha256(item.content).hexdigest() != item.content_sha256
            or hashlib.sha256(item.metadata).hexdigest() != item.metadata_sha256
        ):
            raise _fail("HK_CA_EVIDENCE_INVALID")
    if (
        not isinstance(bundle.query, HkCorporateActionQuery)
        or not _nonempty(bundle.source) or not _nonempty(bundle.source_issue_id)
        or type(bundle.files) is not tuple or not bundle.files
        or any(not isinstance(item, HkCorporateActionRawFile) for item in bundle.files)
        or tuple(sorted(bundle.files, key=lambda item: (item.role, item.content_sha256, item.metadata_sha256))) != bundle.files
        or len({(item.role, item.content_sha256, item.metadata_sha256) for item in bundle.files}) != len(bundle.files)
        or not _utc(bundle.source_observed_at) or not _utc(bundle.coverage_as_of)
        or bundle.coverage_as_of < bundle.query.as_of
        or bundle.bundle_sha256 != _bundle_sha256(
            query=bundle.query, source=bundle.source, source_issue_id=bundle.source_issue_id,
            files=bundle.files, source_observed_at=bundle.source_observed_at,
            coverage_as_of=bundle.coverage_as_of,
        )
    ):
        raise _fail("HK_CA_EVIDENCE_INVALID")


def _bundle_sha256(**values: Any) -> str:
    query = values["query"]
    return _sha_payload(
        {
            "algorithm": "hk-corporate-action-raw-bundle-v1",
            "query_sha256": query.identity_sha256,
            "source": values["source"], "source_issue_id": values["source_issue_id"],
            "files": [[f.role, f.content_sha256, f.metadata_sha256] for f in values["files"]],
            "source_observed_at": _json_value(values["source_observed_at"]),
            "coverage_as_of": _json_value(values["coverage_as_of"]),
        }
    )


def _query_sha256(query: HkCorporateActionQuery) -> str:
    return _sha_payload(
        {"algorithm": "hk-corporate-action-query-v1", "symbols": query.symbols,
         "event_date_start": query.event_date_start.isoformat(), "event_date_end": query.event_date_end.isoformat(),
         "as_of": _json_value(query.as_of), "required_action_types": [x.value for x in query.required_action_types],
         "accepted_currencies": [x.value for x in query.accepted_currencies]}
    )


def _projection_sha256(capability: HkCorporateActionCapability, query: HkCorporateActionQuery, bundle: HkCorporateActionRawBundle, candidates: pl.DataFrame) -> str:
    return _sha_payload(
        {"algorithm": "hk-corporate-action-projection-v1", "source": capability.source,
         "adapter_version": capability.adapter_version, "query_sha256": query.identity_sha256,
         "bundle_sha256": bundle.bundle_sha256,
         "candidates_sha256": _table_sha256("hk_corporate_action_candidates", candidates)}
    )


def _table_sha256(table_name: str, frame: pl.DataFrame) -> str:
    expressions: list[pl.Expr] = []
    for name, dtype in frame.schema.items():
        if isinstance(dtype, pl.Datetime):
            expressions.append(pl.col(name).dt.strftime("%Y-%m-%dT%H:%M:%S%.9fZ").alias(name))
    normalized = frame.with_columns(expressions) if expressions else frame
    return clean_table_content_sha256(table_name=table_name, frame=normalized)


def _candidate_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_candidate_schema(), orient="row")


def _actions_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_action_schema(), orient="row").sort(["symbol", "ex_date", "event_id"])


def _evidence_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {
        **_candidate_schema(),
        "selected": pl.Boolean(),
        "selection_reason": pl.String(),
        "query_as_of": pl.Datetime(time_zone="UTC"),
    }
    return pl.DataFrame(rows, schema=schema, orient="row").sort(["source", "source_event_id", "revision_sequence"])


def _candidate_schema() -> dict[str, pl.DataType]:
    string = pl.String()
    date = pl.Date()
    number = pl.Float64()
    return {
        "economic_event_key_sha256": string, "candidate_id": string, "symbol": string,
        "action_type": string, "source": string, "source_event_id": string,
        "source_revision_id": string, "revision_sequence": pl.Int64(),
        "predecessor_candidate_id": string, "revision_status": string,
        "published_at": pl.Datetime(time_zone="UTC"), "source_observed_at": pl.Datetime(time_zone="UTC"),
        "record_date": date, "ex_date": date, "pay_date": date, "stock_list_date": date,
        "declared_currency": string, "cash_per_share_gross": number, "stock_ratio": number,
        "share_multiplier": number, "rights_ratio": number, "rights_subscription_price": number,
        "rights_subscription_start": date, "rights_subscription_end": date,
        "raw_bundle_sha256": string, "raw_file_sha256": string,
        "raw_metadata_sha256": string, "raw_selector": string,
    }


def _action_schema() -> dict[str, pl.DataType]:
    candidate = _candidate_schema()
    return {
        "event_id": pl.String(), "symbol": pl.String(), "action_type": pl.String(),
        "record_date": pl.Date(), "ex_date": pl.Date(), "pay_date": pl.Date(),
        "stock_list_date": pl.Date(), "declared_currency": pl.String(),
        "cash_per_share_gross": pl.Float64(), "stock_ratio": pl.Float64(),
        "share_multiplier": pl.Float64(), "rights_ratio": pl.Float64(),
        "rights_subscription_price": pl.Float64(), "rights_subscription_start": pl.Date(),
        "rights_subscription_end": pl.Date(), "announce_time": candidate["published_at"],
        "source": pl.String(), "source_event_id": pl.String(), "source_revision_id": pl.String(),
        "source_snapshot_sha256": pl.String(),
    }


def _sha_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, dt.datetime):
        if not _utc(value):
            raise _fail("HK_CA_INPUT_INVALID")
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is float:
        if not math.isfinite(value):
            raise _fail("HK_CA_ACTION_UNSUPPORTED")
        return format(0.0 if value == 0.0 else value, ".17g")
    return value


def _utc(value: object) -> bool:
    return isinstance(value, dt.datetime) and value.tzinfo is not None and value.utcoffset() == dt.timedelta(0)


def _nonempty(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


__all__ = [
    "HkCorporateActionCapability", "HkCorporateActionError", "HkCorporateActionQuery",
    "HkCorporateActionRawBundle", "HkCorporateActionRawFile", "HkCorporateActionSelectionResult",
    "HkCorporateActionSourceAdapter", "VerifiedHkCorporateActionProjection",
    "build_verified_hk_corporate_action_projection", "select_hk_corporate_actions",
    "verify_hk_corporate_action_selection_result", "verify_hk_corporate_action_source",
]
