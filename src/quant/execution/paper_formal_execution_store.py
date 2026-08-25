"""Formal runtime-root materialization and OMS ExecutionStore capability."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import NoReturn, SupportsIndex

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
from quant.execution.paper_account import (
    VerifiedFormalPaperAccountDescriptor,
    load_verified_formal_paper_account_descriptor,
)
from quant.execution.paper_broker_binding import (
    VerifiedFormalPaperBrokerPolicyBinding,
    bind_verified_formal_paper_broker_policy,
)
from quant.execution.paper_formal_broker_store import (
    VerifiedFormalPaperBrokerStoreCapability,
    open_verified_formal_paper_broker_store,
    verify_existing_formal_paper_broker_store_capability,
)
from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    load_verified_paper_execution_policy,
)
from quant.execution.paper_runtime import (
    VerifiedPaperRuntimeEnvironment,
    verify_paper_runtime_environment,
)
from quant.execution.session_barrier import (
    SessionBarrierCapability,
    SessionBarrierError,
    build_session_barrier_capability,
    recover_session_barrier_closure_capability,
    require_matching_barrier_handle,
    unpack_session_barrier_capability,
)
from quant.execution.store import CURRENT_SCHEMA_VERSION, ExecutionStore

_SCHEMA = "formal-paper-execution-store-v2"
_DESCRIPTOR = "execution-store-instance.json"
_BARRIER_SCHEMA = "m4-session-barrier-v1"


class FormalPaperExecutionStoreError(ValueError):
    """Stable, sanitized formal OMS store failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class _Attestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER execution store capability is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperExecutionStoreCapability:
    """Process-local proof of the opened formal OMS store and full chain."""

    schema_version: str
    store_identity: str
    runtime_root_identity: str
    database_identity: str
    database_filename: str
    execution_schema_version: int
    account_id: str
    policy_descriptor_identity: str
    gateway_identity: str
    barrier_epoch: str
    barrier_capability_identity: str
    verified_at: dt.datetime
    environment: VerifiedPaperRuntimeEnvironment = field(repr=False, compare=False)
    policy: VerifiedPaperExecutionPolicy = field(repr=False, compare=False)
    binding: VerifiedFormalPaperBrokerPolicyBinding = field(repr=False, compare=False)
    account: VerifiedFormalPaperAccountDescriptor = field(repr=False, compare=False)
    broker_store: VerifiedFormalPaperBrokerStoreCapability = field(
        repr=False, compare=False
    )
    _store: ExecutionStore = field(repr=False, compare=False)
    _session_barrier: object = field(repr=False, compare=False)
    _attestation: _Attestation = field(repr=False, compare=False)

    @property
    def store(self) -> ExecutionStore:
        return self._store

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER execution store capability is process-local")


class _Failure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _create_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def token(value: VerifiedFormalPaperExecutionStoreCapability) -> bytes:
        return hmac.new(key, canonical_json_bytes(_capability_payload(value)), hashlib.sha256).digest()

    def valid_token(value: VerifiedFormalPaperExecutionStoreCapability) -> bool:
        try:
            return type(value._attestation) is _Attestation and hmac.compare_digest(
                value._attestation.token, token(value)
            )
        except Exception:
            return False

    def mint(
        *,
        store: ExecutionStore,
        descriptor: dict[str, object],
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        account: VerifiedFormalPaperAccountDescriptor,
        broker_store: VerifiedFormalPaperBrokerStoreCapability,
        session_barrier: object,
        now: dt.datetime,
    ) -> VerifiedFormalPaperExecutionStoreCapability:
        barrier = unpack_session_barrier_capability(session_barrier)
        value = VerifiedFormalPaperExecutionStoreCapability(
            schema_version=_SCHEMA,
            store_identity=_text(descriptor, "store_identity"),
            runtime_root_identity=_text(descriptor, "runtime_root_identity"),
            database_identity=_text(descriptor, "database_identity"),
            database_filename=_text(descriptor, "database_filename"),
            execution_schema_version=_integer(descriptor, "execution_schema_version"),
            account_id=account.account_id,
            policy_descriptor_identity=_text(descriptor, "policy_descriptor_identity"),
            gateway_identity=broker_store.gateway_identity,
            barrier_epoch=_text(descriptor, "barrier_epoch"),
            barrier_capability_identity=_text(descriptor, "barrier_capability_identity"),
            verified_at=now,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            broker_store=broker_store,
            _store=store,
            _session_barrier=barrier,
            _attestation=_Attestation(b""),
        )
        object.__setattr__(value, "_attestation", _Attestation(token(value)))
        if not valid_token(value):
            raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
        if (
            value.barrier_epoch != barrier.barrier_epoch
            or value.barrier_capability_identity != barrier.capability_identity
            or not store.session_barrier_enabled()
        ):
            raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
        return value

    def initialize_verified_formal_paper_execution_store(
        *,
        broker_store: VerifiedFormalPaperBrokerStoreCapability,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        account: VerifiedFormalPaperAccountDescriptor,
        now: dt.datetime,
    ) -> VerifiedFormalPaperExecutionStoreCapability:
        root_created = False
        root_identity: tuple[int, int, int] | None = None
        owned: dict[Path, tuple[int, int, int]] = {}
        store: ExecutionStore | None = None
        root = environment.config.runtime_root
        try:
            timestamp = _utc(now)
            verified_broker = _fresh_broker(
                broker_store, environment, policy, binding, account, timestamp
            )
            if root.exists():
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_ALREADY_EXISTS")
            root.mkdir(mode=0o700)
            root_created = True
            root_identity = _object_identity(root, directory=True)
            chain = _materialized_chain(environment, policy, account, timestamp)
            fresh_broker = open_verified_formal_paper_broker_store(
                environment=chain[0], policy=chain[1], binding=chain[2],
                account=chain[3], now=timestamp,
            )
            if fresh_broker.gateway_identity != verified_broker.gateway_identity:
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            db_path = root / chain[0].config.oms_sqlite_filename
            descriptor_path = root / _DESCRIPTOR
            fd = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
            owned[db_path] = _object_identity(db_path, directory=False)
            barrier_epoch = secrets.token_hex(32)
            body = _descriptor_body(
                environment=chain[0],
                account=chain[3],
                broker_store=fresh_broker,
                created_at=timestamp,
                execution_schema_version=CURRENT_SCHEMA_VERSION,
                barrier_epoch=barrier_epoch,
            )
            store_identity = _sha256(body)
            session_barrier = _build_formal_barrier(
                environment=chain[0],
                policy=chain[1],
                account=chain[3],
                broker_store=fresh_broker,
                oms_store_identity=store_identity,
                barrier_epoch=barrier_epoch,
            )
            store = ExecutionStore.open(
                f"sqlite:///{db_path.name}",
                trusted_root=root,
                session_barrier=session_barrier,
                initialize_barrier=True,
                barrier_created_at=timestamp,
            )
            if store.schema_version() != CURRENT_SCHEMA_VERSION:
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
            _record_owned_sidecars(owned, db_path)
            descriptor = _descriptor(
                environment=chain[0],
                policy=chain[1],
                account=chain[3],
                broker_store=fresh_broker,
                store=store,
                created_at=timestamp,
                barrier_epoch=barrier_epoch,
                barrier_capability_identity=session_barrier.capability_identity,
            )
            if descriptor["store_identity"] != store_identity:
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            _write_exclusive(descriptor_path, canonical_json_bytes(descriptor))
            owned[descriptor_path] = _object_identity(
                descriptor_path, directory=False
            )
            _verify_descriptor(descriptor_path, descriptor, store, chain[0])
            _bind_formal_broker_barrier(fresh_broker, store, session_barrier)
            return mint(
                store=store,
                descriptor=descriptor,
                environment=chain[0],
                policy=chain[1],
                binding=chain[2],
                account=chain[3],
                broker_store=fresh_broker,
                session_barrier=session_barrier,
                now=timestamp,
            )
        except _Failure as exc:
            failure = exc.code
        except SessionBarrierError as exc:
            failure = str(exc) if str(exc).startswith("BARRIER_") else (
                "PAPER_FORMAL_EXECUTION_STORE_INVALID"
            )
        except FileExistsError:
            failure = "PAPER_FORMAL_EXECUTION_STORE_ALREADY_EXISTS"
        except Exception:
            failure = "PAPER_FORMAL_EXECUTION_STORE_INVALID"
        cleaned = (
            _rollback(root, root_identity, owned, store) if root_created else True
        )
        if not cleaned:
            failure = "PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED"
        raise FormalPaperExecutionStoreError(failure) from None

    def open_verified_formal_paper_execution_store(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        account: VerifiedFormalPaperAccountDescriptor,
        broker_store: VerifiedFormalPaperBrokerStoreCapability,
        now: dt.datetime,
    ) -> VerifiedFormalPaperExecutionStoreCapability:
        store: ExecutionStore | None = None
        try:
            timestamp = _utc(now)
            fresh_broker = _fresh_broker(
                broker_store, environment, policy, binding, account, timestamp
            )
            root = environment.config.runtime_root
            descriptor_path = root / _DESCRIPTOR
            descriptor = _read_descriptor(descriptor_path)
            session_barrier = _build_formal_barrier(
                environment=environment,
                policy=policy,
                account=account,
                broker_store=fresh_broker,
                oms_store_identity=_text(descriptor, "store_identity"),
                barrier_epoch=_text(descriptor, "barrier_epoch"),
            )
            if (
                session_barrier.capability_identity
                != _text(descriptor, "barrier_capability_identity")
            ):
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            store = ExecutionStore.open(
                f"sqlite:///{environment.config.oms_sqlite_filename}",
                trusted_root=root,
                session_barrier=session_barrier,
                initialize_barrier=False,
            )
            expected = _descriptor(
                environment=environment,
                policy=policy,
                account=account,
                broker_store=fresh_broker,
                store=store,
                created_at=dt.datetime.fromisoformat(
                    _text(descriptor, "created_at").replace("Z", "+00:00")
                ),
                barrier_epoch=_text(descriptor, "barrier_epoch"),
                barrier_capability_identity=session_barrier.capability_identity,
            )
            if descriptor != expected:
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            _verify_descriptor(descriptor_path, expected, store, environment)
            _bind_formal_broker_barrier(fresh_broker, store, session_barrier)
            require_matching_barrier_handle(
                oms_handle=store.session_barrier_oms_handle(),
                capability=session_barrier,
            )
            return mint(
                store=store,
                descriptor=expected,
                environment=environment,
                policy=policy,
                binding=binding,
                account=account,
                broker_store=fresh_broker,
                session_barrier=session_barrier,
                now=timestamp,
            )
        except _Failure as exc:
            failure = exc.code
        except SessionBarrierError as exc:
            failure = str(exc) if str(exc).startswith("BARRIER_") else (
                "PAPER_FORMAL_EXECUTION_STORE_NOT_FOUND"
            )
        except Exception:
            failure = "PAPER_FORMAL_EXECUTION_STORE_NOT_FOUND"
        if store is not None:
            store.close()
        raise FormalPaperExecutionStoreError(failure) from None

    def verify_existing_formal_paper_execution_store_capability(
        *, capability: VerifiedFormalPaperExecutionStoreCapability, now: dt.datetime
    ) -> VerifiedFormalPaperExecutionStoreCapability:
        try:
            timestamp = _utc(now)
            if (
                type(capability) is not VerifiedFormalPaperExecutionStoreCapability
                or not valid_token(capability)
                or timestamp < capability.verified_at
            ):
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
            fresh_broker = _fresh_broker(
                capability.broker_store, capability.environment, capability.policy,
                capability.binding, capability.account, timestamp,
            )
            if fresh_broker is not capability.broker_store:
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            if (
                not capability._store.session_barrier_enabled()
                or not fresh_broker.store.session_barrier_enabled()
            ):
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
            barrier = unpack_session_barrier_capability(capability._session_barrier)
            require_matching_barrier_handle(
                oms_handle=capability._store.session_barrier_oms_handle(),
                capability=barrier,
            )
            descriptor_path = capability.environment.config.runtime_root / _DESCRIPTOR
            descriptor = _read_descriptor(descriptor_path)
            _verify_descriptor(
                descriptor_path, descriptor, capability._store, capability.environment
            )
            if _stable_projection(capability) != _descriptor_projection(descriptor):
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            if (
                _text(descriptor, "barrier_epoch") != capability.barrier_epoch
                or _text(descriptor, "barrier_capability_identity")
                != capability.barrier_capability_identity
                or barrier.capability_identity != capability.barrier_capability_identity
            ):
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            return capability
        except _Failure as exc:
            failure = exc.code
        except SessionBarrierError as exc:
            failure = str(exc) if str(exc).startswith("BARRIER_") else (
                "PAPER_FORMAL_EXECUTION_STORE_STALE"
            )
        except Exception:
            failure = "PAPER_FORMAL_EXECUTION_STORE_STALE"
        raise FormalPaperExecutionStoreError(failure) from None

    return (
        initialize_verified_formal_paper_execution_store,
        open_verified_formal_paper_execution_store,
        verify_existing_formal_paper_execution_store_capability,
    )


(
    initialize_verified_formal_paper_execution_store,
    open_verified_formal_paper_execution_store,
    verify_existing_formal_paper_execution_store_capability,
) = _create_api()
del _create_api


def _fresh_broker(
    broker_store: VerifiedFormalPaperBrokerStoreCapability,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> VerifiedFormalPaperBrokerStoreCapability:
    if (
        type(broker_store) is not VerifiedFormalPaperBrokerStoreCapability
        or type(environment) is not VerifiedPaperRuntimeEnvironment
        or type(policy) is not VerifiedPaperExecutionPolicy
        or type(binding) is not VerifiedFormalPaperBrokerPolicyBinding
        or type(account) is not VerifiedFormalPaperAccountDescriptor
    ):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
    value = verify_existing_formal_paper_broker_store_capability(
        capability=broker_store, environment=environment, policy=policy,
        binding=binding, account=account, now=now,
    )
    if value is not broker_store:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    return value


def _materialized_chain(
    previous: VerifiedPaperRuntimeEnvironment,
    previous_policy: VerifiedPaperExecutionPolicy,
    previous_account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> tuple[
    VerifiedPaperRuntimeEnvironment,
    VerifiedPaperExecutionPolicy,
    VerifiedFormalPaperBrokerPolicyBinding,
    VerifiedFormalPaperAccountDescriptor,
]:
    environment = verify_paper_runtime_environment(config=previous.config, now=now)
    policy = load_verified_paper_execution_policy(
        environment=environment, session_date=previous_policy.session_date, now=now
    )
    binding = bind_verified_formal_paper_broker_policy(
        environment=environment, policy=policy, now=now
    )
    account = load_verified_formal_paper_account_descriptor(
        environment=environment, policy=policy, binding=binding, now=now
    )
    if account.account_id != previous_account.account_id:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    return environment, policy, binding, account


def _descriptor(
    *, environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    account: VerifiedFormalPaperAccountDescriptor,
    broker_store: VerifiedFormalPaperBrokerStoreCapability,
    store: ExecutionStore,
    created_at: dt.datetime,
    barrier_epoch: str,
    barrier_capability_identity: str,
) -> dict[str, object]:
    del policy
    body = _descriptor_body(
        environment=environment,
        account=account,
        broker_store=broker_store,
        created_at=created_at,
        execution_schema_version=store.schema_version(),
        barrier_epoch=barrier_epoch,
    )
    store_identity = _sha256(body)
    return {
        **body,
        "barrier_capability_identity": barrier_capability_identity,
        "store_identity": store_identity,
    }


def _descriptor_body(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    account: VerifiedFormalPaperAccountDescriptor,
    broker_store: VerifiedFormalPaperBrokerStoreCapability,
    created_at: dt.datetime,
    execution_schema_version: int,
    barrier_epoch: str,
    barrier_capability_identity: str | None = None,
) -> dict[str, object]:
    del barrier_capability_identity
    root = environment.config.runtime_root
    database = root / environment.config.oms_sqlite_filename
    return {
        "schema_version": _SCHEMA,
        "runtime_config_identity": environment.config.config_identity,
        "runtime_root_identity": _identity_text(root, directory=True),
        "database_identity": _identity_text(database, directory=False),
        "database_filename": database.name,
        "execution_schema_version": execution_schema_version,
        "account_id": account.account_id,
        "policy_descriptor_identity": broker_store.policy_descriptor_identity,
        "gateway_identity": broker_store.gateway_identity,
        "barrier_schema": _BARRIER_SCHEMA,
        "barrier_epoch": barrier_epoch,
        "created_at": utc_datetime_text(created_at),
    }


def _build_formal_barrier(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    account: VerifiedFormalPaperAccountDescriptor,
    broker_store: VerifiedFormalPaperBrokerStoreCapability,
    oms_store_identity: str,
    barrier_epoch: str,
) -> SessionBarrierCapability:
    root = environment.config.runtime_root
    if type(root) is not type(Path()) or not root.is_absolute():
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
    try:
        return build_session_barrier_capability(
            barrier_epoch=barrier_epoch,
            session_date=policy.session_date,
            account_identity=account.descriptor_identity,
            oms_store_identity=oms_store_identity,
            broker_store_identity=broker_store.store.descriptor.descriptor_identity,
            gateway_identity=broker_store.gateway_identity,
            config_identity=environment.config.config_identity,
            lock_root=root,
            terminal_policy="FORMAL_CLOSURE_ONLY",
        )
    except SessionBarrierError as exc:
        raise _Failure(str(exc)) from None


def _bind_formal_broker_barrier(
    broker_store: VerifiedFormalPaperBrokerStoreCapability,
    store: ExecutionStore,
    session_barrier: object,
) -> None:
    try:
        broker_store.store.bind_session_barrier(
            session_barrier,
            oms_handle=store.session_barrier_oms_handle(),
        )
    except SessionBarrierError as exc:
        raise _Failure(str(exc)) from None
    except Exception as exc:
        code = getattr(exc, "code", None)
        if type(code) is str and code.startswith("BARRIER_"):
            raise _Failure(code) from None
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID") from None
    if not broker_store.store.session_barrier_enabled():
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")


def _verify_descriptor(
    path: Path, expected: dict[str, object], store: ExecutionStore,
    environment: VerifiedPaperRuntimeEnvironment,
) -> None:
    if _read_descriptor(path) != expected or store.schema_version() != _integer(expected, "execution_schema_version"):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    if _identity_text(environment.config.runtime_root, directory=True) != _text(expected, "runtime_root_identity"):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    if not store.session_barrier_enabled():
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")


def _capability_payload(value: VerifiedFormalPaperExecutionStoreCapability) -> dict[str, object]:
    return {
        **_stable_projection(value),
        "environment_identity": value.environment.verification_identity,
        "policy_identity": value.policy.policy_identity,
        "binding_identity": value.binding.binding_identity,
        "account_verification_identity": value.account.verification_identity,
        "broker_capability_identity": value.broker_store.capability_identity,
        "verified_at": utc_datetime_text(value.verified_at),
    }


def _stable_projection(value: VerifiedFormalPaperExecutionStoreCapability) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "store_identity": value.store_identity,
        "runtime_root_identity": value.runtime_root_identity,
        "database_identity": value.database_identity,
        "database_filename": value.database_filename,
        "execution_schema_version": value.execution_schema_version,
        "account_id": value.account_id,
        "policy_descriptor_identity": value.policy_descriptor_identity,
        "gateway_identity": value.gateway_identity,
        "barrier_epoch": value.barrier_epoch,
        "barrier_capability_identity": value.barrier_capability_identity,
    }


def _descriptor_projection(value: dict[str, object]) -> dict[str, object]:
    names = (
        "schema_version",
        "store_identity",
        "runtime_root_identity",
        "database_identity",
        "database_filename",
        "execution_schema_version",
        "account_id",
        "policy_descriptor_identity",
        "gateway_identity",
        "barrier_epoch",
        "barrier_capability_identity",
    )
    return {name: value[name] for name in names}


def _read_descriptor(path: Path) -> dict[str, object]:
    before = _object_identity(path, directory=False)
    raw = path.read_bytes()
    if path.read_bytes() != raw or _object_identity(path, directory=False) != before:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    value = json.loads(raw)
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    expected_keys = {
        "schema_version", "runtime_config_identity", "runtime_root_identity",
        "database_identity", "database_filename", "execution_schema_version",
        "account_id", "policy_descriptor_identity", "gateway_identity",
        "barrier_schema", "barrier_epoch", "barrier_capability_identity",
        "created_at", "store_identity",
    }
    if set(value) != expected_keys or value["schema_version"] != _SCHEMA:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    if value["barrier_schema"] != _BARRIER_SCHEMA:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    body = {
        name: item
        for name, item in value.items()
        if name not in {"store_identity", "barrier_capability_identity"}
    }
    if value["store_identity"] != _sha256(body):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    return value


def _write_exclusive(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _record_owned_sidecars(
    owned: dict[Path, tuple[int, int, int]], db_path: Path
) -> None:
    """Record WAL/SHM object identities only when present after this attempt."""
    for sidecar in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if sidecar.exists() and sidecar not in owned:
            owned[sidecar] = _object_identity(sidecar, directory=False)


def _rollback(
    root: Path,
    root_identity: tuple[int, int, int] | None,
    owned: Mapping[Path, tuple[int, int, int]],
    store: ExecutionStore | None,
) -> bool:
    """Best-effort half-init cleanup for this attempt's OMS artifacts only.

    Deletes only paths whose object identities were recorded during this
    initialize attempt (main sqlite, optional WAL/SHM snapshot after open,
    descriptor immediately after ``_write_exclusive``). Fresh identity must
    match before unlink. Unrecorded WAL/SHM or any other residue is never
    deleted by name/“in new root”; returns False so callers surface
    ``PAPER_FORMAL_EXECUTION_STORE_ROLLBACK_REQUIRED``. Never deletes the
    broker root.
    """
    try:
        if store is not None:
            store.close()
        if root_identity is None or _object_identity(root, directory=True) != root_identity:
            return False
        present = list(root.iterdir())
        # Refuse any present path without a recorded identity (incl. unrecorded WAL/SHM).
        if any(item not in owned for item in present):
            return False
        for path, identity in owned.items():
            if not path.exists():
                continue
            if _object_identity(path, directory=False) != identity:
                return False
        for path, identity in owned.items():
            if not path.exists():
                continue
            if _object_identity(path, directory=False) != identity:
                return False
            path.unlink()
        if any(True for _ in root.iterdir()):
            return False
        root.rmdir()
        return True
    except Exception:
        return False


def _object_identity(path: Path, *, directory: bool) -> tuple[int, int, int]:
    value = path.lstat()
    mode = stat.S_IFMT(value.st_mode)
    if (directory and not stat.S_ISDIR(value.st_mode)) or (not directory and not stat.S_ISREG(value.st_mode)):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
    if not directory and getattr(value, "st_nlink", 1) != 1:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
    return value.st_dev, value.st_ino, mode


def _identity_text(path: Path, *, directory: bool) -> str:
    device, inode, mode = _object_identity(path, directory=directory)
    return _sha256({"path": os.path.normcase(os.path.abspath(path)), "device": device, "inode": inode, "mode": mode})


def _sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_INVALID")
    return value


def _text(value: dict[str, object], name: str) -> str:
    item = value.get(name)
    if type(item) is not str:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    return item


def _integer(value: dict[str, object], name: str) -> int:
    item = value.get(name)
    if type(item) is not int:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    return item


__all__ = [
    "FormalPaperExecutionStoreError",
    "VerifiedFormalPaperExecutionStoreCapability",
    "initialize_verified_formal_paper_execution_store",
    "open_verified_formal_paper_execution_store",
    "recover_formal_session_barrier_closure",
    "transition_formal_session_barrier_to_closing",
    "verify_existing_formal_paper_execution_store_capability",
    "verify_formal_session_barrier_closing_row",
]


def transition_formal_session_barrier_to_closing(
    *,
    capability: VerifiedFormalPaperExecutionStoreCapability,
    nonce: str,
    now: dt.datetime,
) -> tuple[object, object]:
    """Formal OPEN→CLOSING; returns ``(row, closure)`` only — no raw token.

    Closure is issue-only: no terminal broker/OMS writes and no CLOSING→CLOSED.
    Formal barriers use ``FORMAL_CLOSURE_ONLY``; ``.store`` raw CLOSED remains
    rejected with ``BARRIER_CLOSURE_REQUIRED``.
    """
    try:
        timestamp = _utc(now)
        verified = verify_existing_formal_paper_execution_store_capability(
            capability=capability, now=timestamp
        )
        if verified is not capability:
            raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
        row, _token, closure = verified.store.transition_session_barrier_to_closing(
            nonce=nonce, now=timestamp
        )
        return row, closure
    except _Failure as exc:
        raise FormalPaperExecutionStoreError(exc.code) from None
    except FormalPaperExecutionStoreError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", None)
        if type(code) is str:
            raise FormalPaperExecutionStoreError(code) from None
        raise FormalPaperExecutionStoreError(
            "PAPER_FORMAL_EXECUTION_STORE_INVALID"
        ) from None


def verify_formal_session_barrier_closing_row(
    *,
    capability: VerifiedFormalPaperExecutionStoreCapability,
    now: dt.datetime,
) -> object:
    """Fresh-verify formal capability and return the durable barrier row only."""
    try:
        timestamp = _utc(now)
        verified = verify_existing_formal_paper_execution_store_capability(
            capability=capability, now=timestamp
        )
        if verified is not capability:
            raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
        return verified.store.read_session_barrier_row()
    except _Failure as exc:
        raise FormalPaperExecutionStoreError(exc.code) from None
    except FormalPaperExecutionStoreError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", None)
        if type(code) is str:
            raise FormalPaperExecutionStoreError(code) from None
        raise FormalPaperExecutionStoreError(
            "PAPER_FORMAL_EXECUTION_STORE_INVALID"
        ) from None


def recover_formal_session_barrier_closure(
    *,
    capability: VerifiedFormalPaperExecutionStoreCapability,
    close_token_identity: str,
    now: dt.datetime,
) -> object:
    """Recover CLOSING closure via private barrier; never exposes live capability."""
    try:
        timestamp = _utc(now)
        verified = verify_existing_formal_paper_execution_store_capability(
            capability=capability, now=timestamp
        )
        if verified is not capability:
            raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
        return recover_session_barrier_closure_capability(
            capability=verified._session_barrier,
            oms_handle=verified.store.session_barrier_oms_handle(),
            close_token_identity=close_token_identity,
        )
    except _Failure as exc:
        raise FormalPaperExecutionStoreError(exc.code) from None
    except FormalPaperExecutionStoreError:
        raise
    except SessionBarrierError as exc:
        raise FormalPaperExecutionStoreError(str(exc)) from None
    except Exception as exc:
        code = getattr(exc, "code", None)
        if type(code) is str:
            raise FormalPaperExecutionStoreError(code) from None
        raise FormalPaperExecutionStoreError(
            "PAPER_FORMAL_EXECUTION_STORE_INVALID"
        ) from None
