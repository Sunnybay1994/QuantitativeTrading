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
from quant.execution.store import ExecutionStore

_SCHEMA = "formal-paper-execution-store-v1"
_DESCRIPTOR = "execution-store-instance.json"


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
    verified_at: dt.datetime
    environment: VerifiedPaperRuntimeEnvironment = field(repr=False, compare=False)
    policy: VerifiedPaperExecutionPolicy = field(repr=False, compare=False)
    binding: VerifiedFormalPaperBrokerPolicyBinding = field(repr=False, compare=False)
    account: VerifiedFormalPaperAccountDescriptor = field(repr=False, compare=False)
    broker_store: VerifiedFormalPaperBrokerStoreCapability = field(
        repr=False, compare=False
    )
    _store: ExecutionStore = field(repr=False, compare=False)
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
        now: dt.datetime,
    ) -> VerifiedFormalPaperExecutionStoreCapability:
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
            verified_at=now,
            environment=environment,
            policy=policy,
            binding=binding,
            account=account,
            broker_store=broker_store,
            _store=store,
            _attestation=_Attestation(b""),
        )
        object.__setattr__(value, "_attestation", _Attestation(token(value)))
        if not valid_token(value):
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
        db_identity: tuple[int, int, int] | None = None
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
            db_identity = _object_identity(db_path, directory=False)
            store = ExecutionStore.open(
                f"sqlite:///{db_path.name}", trusted_root=root
            )
            descriptor = _descriptor(
                environment=chain[0], policy=chain[1], account=chain[3],
                broker_store=fresh_broker, store=store, created_at=timestamp,
            )
            _write_exclusive(descriptor_path, canonical_json_bytes(descriptor))
            _verify_descriptor(descriptor_path, descriptor, store, chain[0])
            return mint(
                store=store, descriptor=descriptor, environment=chain[0],
                policy=chain[1], binding=chain[2], account=chain[3],
                broker_store=fresh_broker, now=timestamp,
            )
        except _Failure as exc:
            failure = exc.code
        except FileExistsError:
            failure = "PAPER_FORMAL_EXECUTION_STORE_ALREADY_EXISTS"
        except Exception:
            failure = "PAPER_FORMAL_EXECUTION_STORE_INVALID"
        db_path = root / environment.config.oms_sqlite_filename
        cleaned = (
            _rollback(root, root_identity, db_path, db_identity, store)
            if root_created
            else True
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
            store = ExecutionStore.open(
                f"sqlite:///{environment.config.oms_sqlite_filename}", trusted_root=root
            )
            expected = _descriptor(
                environment=environment, policy=policy, account=account,
                broker_store=fresh_broker, store=store,
                created_at=dt.datetime.fromisoformat(_text(descriptor, "created_at").replace("Z", "+00:00")),
            )
            if descriptor != expected:
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            _verify_descriptor(descriptor_path, expected, store, environment)
            return mint(
                store=store, descriptor=expected, environment=environment,
                policy=policy, binding=binding, account=account,
                broker_store=fresh_broker, now=timestamp,
            )
        except _Failure as exc:
            failure = exc.code
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
            descriptor_path = capability.environment.config.runtime_root / _DESCRIPTOR
            descriptor = _read_descriptor(descriptor_path)
            _verify_descriptor(
                descriptor_path, descriptor, capability._store, capability.environment
            )
            if _stable_projection(capability) != _descriptor_projection(descriptor):
                raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
            with capability._store.transaction():
                pass
            return capability
        except _Failure as exc:
            failure = exc.code
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
) -> dict[str, object]:
    root = environment.config.runtime_root
    database = root / environment.config.oms_sqlite_filename
    del policy
    body: dict[str, object] = {
        "schema_version": _SCHEMA,
        "runtime_config_identity": environment.config.config_identity,
        "runtime_root_identity": _identity_text(root, directory=True),
        "database_identity": _identity_text(database, directory=False),
        "database_filename": database.name,
        "execution_schema_version": store.schema_version(),
        "account_id": account.account_id,
        "policy_descriptor_identity": broker_store.policy_descriptor_identity,
        "gateway_identity": broker_store.gateway_identity,
        "created_at": utc_datetime_text(created_at),
    }
    return {**body, "store_identity": _sha256(body)}


def _verify_descriptor(
    path: Path, expected: dict[str, object], store: ExecutionStore,
    environment: VerifiedPaperRuntimeEnvironment,
) -> None:
    if _read_descriptor(path) != expected or store.schema_version() != _integer(expected, "execution_schema_version"):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    if _identity_text(environment.config.runtime_root, directory=True) != _text(expected, "runtime_root_identity"):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")


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
        "created_at", "store_identity",
    }
    if set(value) != expected_keys or value["schema_version"] != _SCHEMA:
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    body = {name: item for name, item in value.items() if name != "store_identity"}
    if value["store_identity"] != _sha256(body):
        raise _Failure("PAPER_FORMAL_EXECUTION_STORE_STALE")
    return value


def _write_exclusive(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _rollback(
    root: Path, root_identity: tuple[int, int, int] | None,
    db_path: Path, db_identity: tuple[int, int, int] | None,
    store: ExecutionStore | None,
) -> bool:
    try:
        if store is not None:
            store.close()
        if root_identity is None or _object_identity(root, directory=True) != root_identity:
            return False
        db_paths = (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm"))
        allowed = {root / _DESCRIPTOR, *db_paths}
        if any(item not in allowed for item in root.iterdir()):
            return False
        for item in (root / _DESCRIPTOR, *db_paths):
            if item.exists():
                if item.name.endswith(".sqlite3") and db_identity is not None and _object_identity(item, directory=False) != db_identity:
                    return False
                item.unlink()
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
    "verify_existing_formal_paper_execution_store_capability",
]
