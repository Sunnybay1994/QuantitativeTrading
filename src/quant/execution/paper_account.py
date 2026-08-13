"""Fresh, read-only formal A-share PAPER account genesis capability."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal, NoReturn, SupportsIndex, cast

from quant.domain.enums import Currency
from quant.execution.contracts import (
    AccountSnapshot,
    CashBalance,
    build_account_snapshot,
    build_account_snapshot_identity,
)
from quant.execution.paper_broker_binding import (
    FormalPaperBrokerPolicyBindingError,
    VerifiedFormalPaperBrokerPolicyBinding,
    verify_existing_formal_paper_broker_policy_binding,
)
from quant.execution.paper_broker_store import (
    PaperAccountDescriptor,
    build_paper_account_descriptor,
)
from quant.execution.paper_policy import VerifiedPaperExecutionPolicy
from quant.execution.paper_runtime import (
    FormalPaperRuntimeConfig,
    VerifiedPaperRuntimeEnvironment,
)

_SCHEMA_VERSION = "formal-paper-account-v1"
_FORMAL_SELECTOR = "formal_paper_a_share_v1"
_CLASSIFICATION: Literal["formal-paper-simulation"] = "formal-paper-simulation"
_ASSUMPTION_NOTICE = "FORMAL PAPER SIMULATION ONLY; NOT A LIVE BROKER ACCOUNT"
_ACCOUNT_LABEL = "FORMAL_PAPER_A_SHARE"
_GENESIS_AS_OF_TEXT = "2026-08-10T00:00:00Z"
_SETTLED_CNY = "500000.00"
_AVAILABLE_CNY = "500000.00"
_RECEIVABLE_CNY = "0.00"
_PAYABLE_CNY = "0.00"
_SELECTOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_FORBIDDEN_SELECTOR_PARTS = ("development", "example", "fixture", "unknown")
_DECIMAL_RE = re.compile(r"^\d+\.\d{2}$")
_REPARSE_POINT = 0x400
_SCOPE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class FormalPaperAccountError(ValueError):
    """Stable, sanitized formal PAPER account failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"FormalPaperAccountError({self.code!r})"


@dataclass(frozen=True, slots=True)
class _AccountAttestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER account capability is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperAccountDescriptor:
    """Exact process-local proof of one formal PAPER account genesis."""

    schema_version: str
    classification: Literal["formal-paper-simulation"]
    session_date: dt.date
    selector: str
    source_path: Path
    source_file_identity: str
    source_parent_identity: str
    raw_sha256: str
    runtime_environment_identity: str
    runtime_config_identity: str
    execution_policy_identity: str
    broker_binding_identity: str
    account_descriptor: PaperAccountDescriptor
    account_id: str
    initial_snapshot_identity: str
    descriptor_identity: str
    risk_counter_scope: str
    verification_identity: str
    verified_at: dt.datetime
    _attestation: _AccountAttestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER account capability is process-local")


@dataclass(slots=True)
class _AnchoredAccountFile:
    descriptor: int
    source_path: Path
    parent_path: Path
    project_root: Path
    raw: bytes
    raw_sha256: str
    source_file_identity: str
    source_parent_identity: str
    project_root_identity: str
    object_identity: tuple[int, int, int]

    def close(self) -> None:
        os.close(self.descriptor)


@dataclass(frozen=True, slots=True)
class _ParsedAccount:
    account_label: str
    base_currency: Currency
    as_of: dt.datetime
    settled_cny: Decimal
    available_cny: Decimal
    receivable_cny: Decimal
    payable_cny: Decimal


class _Failure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _create_account_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def _verify_token(capability: VerifiedFormalPaperAccountDescriptor) -> bool:
        try:
            if type(capability._attestation) is not _AccountAttestation:
                return False
            token = capability._attestation.token
            if type(token) is not bytes:
                return False
            expected = hmac.new(
                key,
                _canonical_json(_capability_payload(capability)),
                hashlib.sha256,
            ).digest()
            return hmac.compare_digest(token, expected)
        except Exception:
            return False

    def _load_impl(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        now: dt.datetime,
        verified_at: dt.datetime,
    ) -> VerifiedFormalPaperAccountDescriptor:
        anchored: _AnchoredAccountFile | None = None
        try:
            timestamp = _require_public_inputs(environment, policy, binding, now)
            fresh_binding = _fresh_binding(binding, environment, policy, timestamp)
            selector = _require_formal_selector(environment.config.account_selector)
            source = (
                environment.config.project_root
                / "configs"
                / "trading"
                / "accounts"
                / f"{selector}.toml"
            )
            anchored = _open_anchored_account(source, environment.config.project_root)
            parsed = _parse_account(anchored.raw, selector)
            snapshot = _build_snapshot(parsed)
            build_account_snapshot_identity(snapshot)
            account_descriptor = build_paper_account_descriptor(
                account_label=parsed.account_label,
                created_at=parsed.as_of,
                base_currency=parsed.base_currency,
                initial_snapshot=snapshot,
            )
            _before_account_mint_hook(anchored.source_path)
            _fresh_binding(fresh_binding, environment, policy, timestamp)
            _fresh_verify_anchored_account(anchored)
            risk_counter_scope = f"paper-{account_descriptor.account_id}"
            if _SCOPE_RE.fullmatch(risk_counter_scope) is None:
                raise _Failure("PAPER_ACCOUNT_SEMANTICS_INVALID")
            identity_payload = _identity_payload(
                environment=environment,
                policy=policy,
                binding=fresh_binding,
                anchored=anchored,
                parsed=parsed,
                account_descriptor=account_descriptor,
                selector=selector,
                risk_counter_scope=risk_counter_scope,
                verified_at=verified_at,
            )
            result = VerifiedFormalPaperAccountDescriptor(
                schema_version=_SCHEMA_VERSION,
                classification=_CLASSIFICATION,
                session_date=fresh_binding.session_date,
                selector=selector,
                source_path=anchored.source_path,
                source_file_identity=anchored.source_file_identity,
                source_parent_identity=anchored.source_parent_identity,
                raw_sha256=anchored.raw_sha256,
                runtime_environment_identity=environment.verification_identity,
                runtime_config_identity=environment.config.config_identity,
                execution_policy_identity=policy.policy_identity,
                broker_binding_identity=fresh_binding.binding_identity,
                account_descriptor=account_descriptor,
                account_id=account_descriptor.account_id,
                initial_snapshot_identity=account_descriptor.initial_snapshot_identity,
                descriptor_identity=account_descriptor.descriptor_identity,
                risk_counter_scope=risk_counter_scope,
                verification_identity=_sha256(identity_payload),
                verified_at=verified_at,
                _attestation=_AccountAttestation(b""),
            )
            attestation_payload = _capability_payload(result)
            attestation_token = hmac.new(
                key,
                _canonical_json(attestation_payload),
                hashlib.sha256,
            ).digest()
            object.__setattr__(
                result,
                "_attestation",
                _AccountAttestation(attestation_token),
            )
            if not _verify_token(result):
                raise _Failure("PAPER_ACCOUNT_INVALID")
            return result
        finally:
            if anchored is not None:
                anchored.close()

    def load_verified_formal_paper_account_descriptor(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        now: dt.datetime,
    ) -> VerifiedFormalPaperAccountDescriptor:
        """Fresh-load and mint the sole formal A-share PAPER account capability."""
        failure: str | None = None
        result: VerifiedFormalPaperAccountDescriptor | None = None
        try:
            timestamp = _require_public_inputs(environment, policy, binding, now)
            result = _load_impl(
                environment=environment,
                policy=policy,
                binding=binding,
                now=timestamp,
                verified_at=timestamp,
            )
        except FormalPaperAccountError as exc:
            failure = exc.code
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_ACCOUNT_INVALID"
        if failure is not None or result is None:
            raise FormalPaperAccountError(failure or "PAPER_ACCOUNT_INVALID") from None
        return result

    def _verify_impl(
        *,
        capability: VerifiedFormalPaperAccountDescriptor,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        now: dt.datetime,
    ) -> VerifiedFormalPaperAccountDescriptor:
        if (
            type(capability) is not VerifiedFormalPaperAccountDescriptor
            or not _verify_token(capability)
        ):
            raise _Failure("PAPER_ACCOUNT_INVALID")
        timestamp = _require_public_inputs(environment, policy, binding, now)
        _require_utc(capability.verified_at)
        if timestamp < capability.verified_at:
            raise _Failure("PAPER_ACCOUNT_STALE")
        try:
            rebuilt = _load_impl(
                environment=environment,
                policy=policy,
                binding=binding,
                now=timestamp,
                verified_at=capability.verified_at,
            )
        except _Failure:
            raise _Failure("PAPER_ACCOUNT_STALE") from None
        if rebuilt != capability:
            raise _Failure("PAPER_ACCOUNT_STALE")
        return capability

    def verify_existing_formal_paper_account_descriptor(
        *,
        capability: VerifiedFormalPaperAccountDescriptor,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        now: dt.datetime,
    ) -> VerifiedFormalPaperAccountDescriptor:
        """Fresh-load and exact-compare an existing process-local account proof."""
        failure: str | None = None
        result: VerifiedFormalPaperAccountDescriptor | None = None
        try:
            result = _verify_impl(
                capability=capability,
                environment=environment,
                policy=policy,
                binding=binding,
                now=now,
            )
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_ACCOUNT_INVALID"
        if failure is not None or result is None:
            raise FormalPaperAccountError(failure or "PAPER_ACCOUNT_INVALID") from None
        return result

    return (
        load_verified_formal_paper_account_descriptor,
        verify_existing_formal_paper_account_descriptor,
    )


(
    load_verified_formal_paper_account_descriptor,
    verify_existing_formal_paper_account_descriptor,
) = _create_account_api()
del _create_account_api


def _require_public_inputs(
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    now: dt.datetime,
) -> dt.datetime:
    if type(environment) is not VerifiedPaperRuntimeEnvironment:
        raise _Failure("PAPER_ACCOUNT_ENVIRONMENT_INVALID")
    if type(policy) is not VerifiedPaperExecutionPolicy:
        raise _Failure("PAPER_ACCOUNT_POLICY_BINDING_INVALID")
    if type(binding) is not VerifiedFormalPaperBrokerPolicyBinding:
        raise _Failure("PAPER_ACCOUNT_POLICY_BINDING_INVALID")
    try:
        if type(environment.config) is not FormalPaperRuntimeConfig:
            raise ValueError
        environment_time = _require_utc(environment.verified_at)
        policy_time = _require_utc(policy.verified_at)
        binding_time = _require_utc(binding.verified_at)
    except _Failure:
        raise _Failure("PAPER_ACCOUNT_ENVIRONMENT_INVALID") from None
    except Exception:
        raise _Failure("PAPER_ACCOUNT_ENVIRONMENT_INVALID") from None
    timestamp = _require_utc(now)
    if (
        timestamp < environment_time
        or timestamp < policy_time
        or timestamp < binding_time
    ):
        raise _Failure("PAPER_ACCOUNT_STALE")
    return timestamp


def _require_utc(value: dt.datetime) -> dt.datetime:
    try:
        if (
            type(value) is not dt.datetime
            or value.tzinfo is None
            or value.utcoffset() != dt.timedelta(0)
        ):
            raise ValueError
    except Exception:
        raise _Failure("PAPER_ACCOUNT_STALE") from None
    return value


def _require_formal_selector(value: object) -> str:
    if (
        type(value) is not str
        or _SELECTOR_RE.fullmatch(value) is None
        or any(part in value.lower() for part in _FORBIDDEN_SELECTOR_PARTS)
        or value != _FORMAL_SELECTOR
    ):
        raise _Failure("PAPER_ACCOUNT_SELECTOR_UNSUPPORTED")
    return value


def _fresh_binding(
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    now: dt.datetime,
) -> VerifiedFormalPaperBrokerPolicyBinding:
    try:
        fresh = verify_existing_formal_paper_broker_policy_binding(
            binding=binding,
            environment=environment,
            policy=policy,
            now=now,
        )
        if type(fresh) is not VerifiedFormalPaperBrokerPolicyBinding or fresh != binding:
            raise ValueError
    except FormalPaperBrokerPolicyBindingError as exc:
        if exc.code == "PAPER_BROKER_BINDING_ENVIRONMENT_INVALID":
            raise _Failure("PAPER_ACCOUNT_ENVIRONMENT_INVALID") from None
        if exc.code == "PAPER_BROKER_BINDING_STALE":
            raise _Failure("PAPER_ACCOUNT_STALE") from None
        raise _Failure("PAPER_ACCOUNT_POLICY_BINDING_INVALID") from None
    except Exception:
        raise _Failure("PAPER_ACCOUNT_POLICY_BINDING_INVALID") from None
    return fresh


def _open_anchored_account(source: Path, project_root: Path) -> _AnchoredAccountFile:
    descriptor: int | None = None
    try:
        if not isinstance(source, Path) or not isinstance(project_root, Path):
            raise ValueError
        root = Path(os.path.abspath(os.fspath(project_root)))
        absolute = Path(os.path.abspath(os.fspath(source)))
        if not _is_within(absolute, root):
            raise ValueError
        _reject_link_chain(root)
        root_status = os.lstat(root)
        _require_directory_status(root_status)
        root_identity = _directory_identity(root, root_status)
        parent = absolute.parent
        _reject_link_chain(parent)
        parent_status = os.lstat(parent)
        _require_directory_status(parent_status)
        parent_identity = _directory_identity(parent, parent_status)
        path_status = os.lstat(absolute)
        _require_regular_status(path_status)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(absolute, flags)
        opened = os.fstat(descriptor)
        _require_regular_status(opened)
        object_identity = _object_identity(opened)
        if _object_identity(path_status) != object_identity:
            raise ValueError
        raw = _read_descriptor(descriptor)
        after = os.fstat(descriptor)
        if _object_identity(after) != object_identity or len(raw) != after.st_size:
            raise ValueError
        return _AnchoredAccountFile(
            descriptor=descriptor,
            source_path=absolute,
            parent_path=parent,
            project_root=root,
            raw=raw,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            source_file_identity=_file_identity(absolute, after),
            source_parent_identity=parent_identity,
            project_root_identity=root_identity,
            object_identity=object_identity,
        )
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise _Failure("PAPER_ACCOUNT_SOURCE_INVALID") from None


def _fresh_verify_anchored_account(anchored: _AnchoredAccountFile) -> None:
    try:
        opened = os.fstat(anchored.descriptor)
        if _object_identity(opened) != anchored.object_identity:
            raise ValueError
        os.lseek(anchored.descriptor, 0, os.SEEK_SET)
        current = _read_descriptor(anchored.descriptor)
        if current != anchored.raw or len(current) != opened.st_size:
            raise ValueError
        path_status = os.lstat(anchored.source_path)
        parent_status = os.lstat(anchored.parent_path)
        root_status = os.lstat(anchored.project_root)
        if (
            _object_identity(path_status) != anchored.object_identity
            or _file_identity(anchored.source_path, path_status)
            != anchored.source_file_identity
            or _directory_identity(anchored.parent_path, parent_status)
            != anchored.source_parent_identity
            or _directory_identity(anchored.project_root, root_status)
            != anchored.project_root_identity
            or hashlib.sha256(current).hexdigest() != anchored.raw_sha256
        ):
            raise ValueError
    except Exception:
        raise _Failure("PAPER_ACCOUNT_SOURCE_INVALID") from None


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _parse_account(raw: bytes, selector: str) -> _ParsedAccount:
    try:
        text = raw.decode("utf-8")
        document = cast(dict[str, object], tomllib.loads(text))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise _Failure("PAPER_ACCOUNT_SOURCE_INVALID") from None
    try:
        _require_document_shape(document)
        if text != _render_canonical(document):
            raise _Failure("PAPER_ACCOUNT_SOURCE_INVALID")
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_ACCOUNT_SOURCE_INVALID") from None
    try:
        return _validate_semantics(document, selector)
    except Exception:
        raise _Failure("PAPER_ACCOUNT_SEMANTICS_INVALID") from None


def _require_document_shape(document: object) -> None:
    root = _table(document, {"meta", "account", "initial_state"})
    _table(
        root["meta"],
        {
            "schema_version",
            "account_version",
            "classification",
            "assumption_notice",
        },
    )
    _table(root["account"], {"account_label", "base_currency"})
    _table(
        root["initial_state"],
        {
            "as_of",
            "settled_cny",
            "available_cny",
            "receivable_cny",
            "payable_cny",
            "positions",
        },
    )


def _validate_semantics(document: dict[str, object], selector: str) -> _ParsedAccount:
    meta = _mapping(document["meta"])
    account = _mapping(document["account"])
    initial = _mapping(document["initial_state"])
    expected_meta = {
        "schema_version": _SCHEMA_VERSION,
        "account_version": selector,
        "classification": _CLASSIFICATION,
        "assumption_notice": _ASSUMPTION_NOTICE,
    }
    if meta != expected_meta:
        raise ValueError
    if account["account_label"] != _ACCOUNT_LABEL or account["base_currency"] != "CNY":
        raise ValueError
    if initial["as_of"] != _GENESIS_AS_OF_TEXT:
        raise ValueError
    for field_name, expected in (
        ("settled_cny", _SETTLED_CNY),
        ("available_cny", _AVAILABLE_CNY),
        ("receivable_cny", _RECEIVABLE_CNY),
        ("payable_cny", _PAYABLE_CNY),
    ):
        if initial[field_name] != expected:
            raise ValueError
    positions = _sequence(initial["positions"])
    if positions:
        raise ValueError
    settled = _decimal_amount(initial["settled_cny"], positive=True)
    available = _decimal_amount(initial["available_cny"], positive=True)
    receivable = _decimal_amount(initial["receivable_cny"], positive=False)
    payable = _decimal_amount(initial["payable_cny"], positive=False)
    if available != settled:
        raise ValueError
    if receivable != Decimal("0.00") or payable != Decimal("0.00"):
        raise ValueError
    as_of = _parse_genesis_as_of(cast(str, initial["as_of"]))
    return _ParsedAccount(
        account_label=cast(str, account["account_label"]),
        base_currency=Currency.CNY,
        as_of=as_of,
        settled_cny=settled,
        available_cny=available,
        receivable_cny=receivable,
        payable_cny=payable,
    )


def _build_snapshot(parsed: _ParsedAccount) -> AccountSnapshot:
    cash = CashBalance(
        currency=parsed.base_currency,
        settled=parsed.settled_cny,
        available=parsed.available_cny,
        receivable=parsed.receivable_cny,
        payable=parsed.payable_cny,
    )
    return build_account_snapshot(
        as_of=parsed.as_of,
        positions=(),
        cash=(cash,),
    )


def _render_canonical(document: dict[str, object]) -> str:
    meta = _mapping(document["meta"])
    account = _mapping(document["account"])
    initial = _mapping(document["initial_state"])
    lines = [
        "[meta]",
        f"schema_version = {_quote(meta['schema_version'])}",
        f"account_version = {_quote(meta['account_version'])}",
        f"classification = {_quote(meta['classification'])}",
        f"assumption_notice = {_quote(meta['assumption_notice'])}",
        "",
        "[account]",
        f"account_label = {_quote(account['account_label'])}",
        f"base_currency = {_quote(account['base_currency'])}",
        "",
        "[initial_state]",
        f"as_of = {_quote(initial['as_of'])}",
        f"settled_cny = {_quote(initial['settled_cny'])}",
        f"available_cny = {_quote(initial['available_cny'])}",
        f"receivable_cny = {_quote(initial['receivable_cny'])}",
        f"payable_cny = {_quote(initial['payable_cny'])}",
        "positions = []",
        "",
    ]
    return "\n".join(lines)


def _identity_payload(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    anchored: _AnchoredAccountFile,
    parsed: _ParsedAccount,
    account_descriptor: PaperAccountDescriptor,
    selector: str,
    risk_counter_scope: str,
    verified_at: dt.datetime,
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "classification": _CLASSIFICATION,
        "session_date": binding.session_date.isoformat(),
        "selector": selector,
        "source_file_identity": anchored.source_file_identity,
        "source_parent_identity": anchored.source_parent_identity,
        "raw_sha256": anchored.raw_sha256,
        "runtime_environment_identity": environment.verification_identity,
        "runtime_config_identity": environment.config.config_identity,
        "execution_policy_identity": policy.policy_identity,
        "broker_binding_identity": binding.binding_identity,
        "account_id": account_descriptor.account_id,
        "initial_snapshot_identity": account_descriptor.initial_snapshot_identity,
        "descriptor_identity": account_descriptor.descriptor_identity,
        "account_label": parsed.account_label,
        "base_currency": parsed.base_currency.value,
        "genesis_as_of": parsed.as_of.isoformat(timespec="microseconds"),
        "risk_counter_scope": risk_counter_scope,
        "verified_at": verified_at.isoformat(timespec="microseconds"),
    }


def _capability_payload(
    capability: VerifiedFormalPaperAccountDescriptor,
) -> dict[str, object]:
    return {
        "schema_version": capability.schema_version,
        "classification": capability.classification,
        "session_date": capability.session_date.isoformat(),
        "selector": capability.selector,
        "source_file_identity": capability.source_file_identity,
        "source_parent_identity": capability.source_parent_identity,
        "raw_sha256": capability.raw_sha256,
        "runtime_environment_identity": capability.runtime_environment_identity,
        "runtime_config_identity": capability.runtime_config_identity,
        "execution_policy_identity": capability.execution_policy_identity,
        "broker_binding_identity": capability.broker_binding_identity,
        "account_id": capability.account_id,
        "initial_snapshot_identity": capability.initial_snapshot_identity,
        "descriptor_identity": capability.descriptor_identity,
        "risk_counter_scope": capability.risk_counter_scope,
        "verification_identity": capability.verification_identity,
        "verified_at": capability.verified_at.isoformat(timespec="microseconds"),
    }


def _table(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(cast(dict[object, object], value)) != keys:
        raise ValueError
    return cast(dict[str, object], value)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if type(value) is not list:
        raise ValueError
    return cast(Sequence[object], value)


def _quote(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return json.dumps(value, ensure_ascii=True)


def _decimal_amount(value: object, *, positive: bool) -> Decimal:
    if type(value) is not str or _DECIMAL_RE.fullmatch(value) is None:
        raise ValueError
    amount = Decimal(value)
    if positive and amount <= Decimal("0"):
        raise ValueError
    if not positive and amount < Decimal("0"):
        raise ValueError
    if format(amount, "f") != value:
        raise ValueError
    return amount


def _parse_genesis_as_of(value: str) -> dt.datetime:
    if value != _GENESIS_AS_OF_TEXT:
        raise ValueError
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != dt.timedelta(0):
        raise ValueError
    return parsed


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _object_identity(status: os.stat_result) -> tuple[int, int, int]:
    return status.st_dev, status.st_ino, stat.S_IFMT(status.st_mode)


def _file_identity(path: Path, status: os.stat_result) -> str:
    return _sha256(
        {
            "type": "paper-account-file-v1",
            "path": os.path.normcase(os.path.abspath(os.fspath(path))),
            "device": status.st_dev,
            "inode": status.st_ino,
            "mode": stat.S_IFMT(status.st_mode),
        }
    )


def _directory_identity(path: Path, status: os.stat_result) -> str:
    _require_directory_status(status)
    return _sha256(
        {
            "type": "paper-account-directory-v1",
            "path": os.path.normcase(os.path.abspath(os.fspath(path))),
            "device": status.st_dev,
            "inode": status.st_ino,
            "mode": stat.S_IFMT(status.st_mode),
        }
    )


def _is_reparse(status: os.stat_result) -> bool:
    return bool(getattr(status, "st_file_attributes", 0) & _REPARSE_POINT)


def _require_regular_status(status: os.stat_result) -> None:
    if (
        not stat.S_ISREG(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or _is_reparse(status)
        or status.st_nlink != 1
    ):
        raise ValueError


def _require_directory_status(status: os.stat_result) -> None:
    if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode) or _is_reparse(status):
        raise ValueError


def _reject_link_chain(path: Path) -> None:
    current = Path(os.path.abspath(os.fspath(path)))
    for candidate in (current, *current.parents):
        status = os.lstat(candidate)
        if stat.S_ISLNK(status.st_mode) or _is_reparse(status):
            raise ValueError


def _is_within(candidate: Path, boundary: Path) -> bool:
    try:
        return os.path.commonpath((candidate, boundary)) == os.path.commonpath(
            (boundary, boundary)
        )
    except ValueError:
        return False


def _before_account_mint_hook(path: Path) -> None:
    del path


__all__ = [
    "FormalPaperAccountError",
    "VerifiedFormalPaperAccountDescriptor",
    "load_verified_formal_paper_account_descriptor",
    "verify_existing_formal_paper_account_descriptor",
]
