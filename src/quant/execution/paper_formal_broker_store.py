"""Capability-gated initializer and opener for the formal PAPER broker store."""

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
from typing import Literal, NoReturn, SupportsIndex

from quant.execution.paper_account import (
    VerifiedFormalPaperAccountDescriptor,
    load_verified_formal_paper_account_descriptor,
    verify_existing_formal_paper_account_descriptor,
)
from quant.execution.paper_broker_binding import (
    VerifiedFormalPaperBrokerPolicyBinding,
    bind_verified_formal_paper_broker_policy,
    verify_existing_formal_paper_broker_policy_binding,
)
from quant.execution.paper_broker_store import (
    PaperBrokerPolicyDescriptor,
    PaperBrokerStore,
    _rollback_fresh_store,
    build_formal_paper_broker_policy_descriptor,
    initialize_paper_broker_store,
    open_verified_paper_broker_store,
)
from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    load_verified_paper_execution_policy,
    verify_existing_paper_execution_policy,
)
from quant.execution.paper_runtime import (
    FormalPaperRuntimeConfig,
    VerifiedPaperRuntimeEnvironment,
    verify_existing_paper_runtime_preflight,
    verify_paper_runtime_environment,
)

_SCHEMA_VERSION = "formal-paper-broker-store-capability-v1"
_CLASSIFICATION: Literal["formal-paper-simulation"] = "formal-paper-simulation"
_REPARSE_POINT = 0x400


class FormalPaperBrokerStoreError(ValueError):
    """Stable, sanitized formal store failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"FormalPaperBrokerStoreError({self.code!r})"

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class _StoreAttestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER store capability is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperBrokerStoreCapability:
    """Process-local proof around one open, freshly verified B1 store."""

    schema_version: str
    classification: Literal["formal-paper-simulation"]
    session_date: dt.date
    runtime_environment_identity: str
    runtime_config_identity: str
    runtime_layout_identity: str
    execution_policy_identity: str
    broker_binding_identity: str
    account_verification_identity: str
    account_id: str
    account_descriptor_identity: str
    genesis_source_identity: str
    genesis_raw_sha256: str
    policy_descriptor_identity: str
    store_descriptor_identity: str
    gateway_identity: str
    broker_root_identity: str
    database_filename: str
    oms_separation_identity: str
    capability_identity: str
    verified_at: dt.datetime
    _store: PaperBrokerStore = field(repr=False, compare=False)
    _attestation: _StoreAttestation = field(repr=False, compare=False)

    @property
    def store(self) -> PaperBrokerStore:
        """Return the retained store; consumers must first run existing verification."""
        return self._store

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER store capability is process-local")


class _Failure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


@dataclass(frozen=True, slots=True)
class _FreshChain:
    environment: VerifiedPaperRuntimeEnvironment
    policy: VerifiedPaperExecutionPolicy
    binding: VerifiedFormalPaperBrokerPolicyBinding
    account: VerifiedFormalPaperAccountDescriptor


def _create_formal_store_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def _verify_token(capability: VerifiedFormalPaperBrokerStoreCapability) -> bool:
        try:
            if type(capability._attestation) is not _StoreAttestation:
                return False
            expected = hmac.new(
                key, _canonical_json(_capability_payload(capability)), hashlib.sha256
            ).digest()
            return hmac.compare_digest(capability._attestation.token, expected)
        except Exception:
            return False

    def initialize_verified_formal_paper_broker_store(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        account: VerifiedFormalPaperAccountDescriptor,
        now: dt.datetime,
    ) -> VerifiedFormalPaperBrokerStoreCapability:
        """Create the sole broker root, rebuild the chain, and initialize B1."""
        root_created = False
        root_identity: tuple[int, int, int] | None = None
        store: PaperBrokerStore | None = None
        try:
            timestamp = _require_inputs(environment, policy, binding, account, now)
            cold = _verify_existing_chain(environment, policy, binding, account, timestamp)
            config = cold.environment.config
            _require_separation(config)
            root = config.broker_root
            if root.exists():
                raise _Failure("PAPER_FORMAL_STORE_ALREADY_EXISTS")
            root.mkdir(mode=0o700)
            root_created = True
            root_identity = _path_identity(root)
            materialized_environment = verify_paper_runtime_environment(
                config=config, now=timestamp
            )
            materialized_policy = load_verified_paper_execution_policy(
                environment=materialized_environment,
                session_date=cold.policy.session_date,
                now=timestamp,
            )
            materialized_binding = bind_verified_formal_paper_broker_policy(
                environment=materialized_environment,
                policy=materialized_policy,
                now=timestamp,
            )
            materialized_account = load_verified_formal_paper_account_descriptor(
                environment=materialized_environment,
                policy=materialized_policy,
                binding=materialized_binding,
                now=timestamp,
            )
            materialized = _FreshChain(
                materialized_environment,
                materialized_policy,
                materialized_binding,
                materialized_account,
            )
            materialized = _verify_existing_chain(
                materialized.environment,
                materialized.policy,
                materialized.binding,
                materialized.account,
                timestamp,
            )
            _require_materialized(materialized.environment)
            _compare_cold_materialized(cold, materialized)
            descriptor = build_formal_paper_broker_policy_descriptor(
                policy=materialized.policy, binding=materialized.binding
            )
            store = initialize_paper_broker_store(
                root=config.broker_root,
                database_filename=config.broker_sqlite_filename,
                oms_store_path=config.runtime_root / config.oms_sqlite_filename,
                account=materialized.account.account_descriptor,
                policy=descriptor,
                created_at=materialized.account.account_descriptor.created_at,
            )
            _verify_store(store, materialized, descriptor)
            final = _reload_materialized_chain(materialized, timestamp)
            _verify_store(store, final, descriptor)
            result = _assemble_capability(
                chain=final, descriptor=descriptor, store=store, now=timestamp
            )
            object.__setattr__(
                result,
                "_attestation",
                _StoreAttestation(
                    hmac.new(
                        key,
                        _canonical_json(_capability_payload(result)),
                        hashlib.sha256,
                    ).digest()
                ),
            )
            if not _verify_token(result):
                raise _Failure("PAPER_FORMAL_STORE_INVALID")
            return result
        except _Failure as exc:
            failure = exc.code
        except FileExistsError:
            failure = "PAPER_FORMAL_STORE_ALREADY_EXISTS"
        except Exception:
            failure = "PAPER_FORMAL_STORE_INVALID"
        if store is not None:
            cleaned = _rollback_fresh_store(store)
        else:
            cleaned = True
        if root_created and not _remove_owned_empty_root(environment, root_identity):
            cleaned = False
        if not cleaned:
            failure = "PAPER_FORMAL_STORE_ROLLBACK_REQUIRED"
        raise FormalPaperBrokerStoreError(failure) from None

    def open_verified_formal_paper_broker_store(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        account: VerifiedFormalPaperAccountDescriptor,
        now: dt.datetime,
    ) -> VerifiedFormalPaperBrokerStoreCapability:
        """Fresh-open an existing store using only materialized runtime paths."""
        store: PaperBrokerStore | None = None
        try:
            timestamp = _require_inputs(environment, policy, binding, account, now)
            chain = _verify_existing_chain(
                environment, policy, binding, account, timestamp
            )
            _require_materialized(chain.environment)
            config = chain.environment.config
            _require_separation(config)
            descriptor = build_formal_paper_broker_policy_descriptor(
                policy=chain.policy, binding=chain.binding
            )
            store = open_verified_paper_broker_store(
                root=config.broker_root,
                database_filename=config.broker_sqlite_filename,
                oms_store_path=config.runtime_root / config.oms_sqlite_filename,
            )
            _verify_store(store, chain, descriptor)
            final = _reload_materialized_chain(chain, timestamp)
            _verify_store(store, final, descriptor)
            result = _assemble_capability(
                chain=final, descriptor=descriptor, store=store, now=timestamp
            )
            object.__setattr__(
                result,
                "_attestation",
                _StoreAttestation(
                    hmac.new(
                        key,
                        _canonical_json(_capability_payload(result)),
                        hashlib.sha256,
                    ).digest()
                ),
            )
            if not _verify_token(result):
                raise _Failure("PAPER_FORMAL_STORE_INVALID")
            return result
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_FORMAL_STORE_NOT_FOUND"
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
        raise FormalPaperBrokerStoreError(failure) from None

    def verify_existing_formal_paper_broker_store_capability(
        *,
        capability: VerifiedFormalPaperBrokerStoreCapability,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        account: VerifiedFormalPaperAccountDescriptor,
        now: dt.datetime,
    ) -> VerifiedFormalPaperBrokerStoreCapability:
        """Fresh-rebuild all inputs and exact-compare a retained open capability."""
        try:
            if (
                type(capability) is not VerifiedFormalPaperBrokerStoreCapability
                or not _verify_token(capability)
                or type(capability._store) is not PaperBrokerStore
            ):
                raise _Failure("PAPER_FORMAL_STORE_INVALID")
            timestamp = _require_inputs(environment, policy, binding, account, now)
            if timestamp < capability.verified_at:
                raise _Failure("PAPER_FORMAL_STORE_STALE")
            chain = _verify_existing_chain(
                environment, policy, binding, account, timestamp
            )
            _require_materialized(chain.environment)
            descriptor = build_formal_paper_broker_policy_descriptor(
                policy=chain.policy, binding=chain.binding
            )
            _verify_store(capability._store, chain, descriptor)
            rebuilt_payload = _identity_payload(
                chain=chain,
                descriptor=descriptor,
                store=capability._store,
                root_identity=dict(chain.environment.layout.root_identities)["broker"],
                separation=_separation_identity(chain.environment.config),
                verified_at=capability.verified_at,
            )
            if (
                capability.capability_identity != _sha256(rebuilt_payload)
                or _stable_capability_payload(capability)
                != _stable_identity_projection(rebuilt_payload)
            ):
                raise _Failure("PAPER_FORMAL_STORE_STALE")
            return capability
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_FORMAL_STORE_STALE"
        raise FormalPaperBrokerStoreError(failure) from None

    return (
        initialize_verified_formal_paper_broker_store,
        open_verified_formal_paper_broker_store,
        verify_existing_formal_paper_broker_store_capability,
    )


(
    initialize_verified_formal_paper_broker_store,
    open_verified_formal_paper_broker_store,
    verify_existing_formal_paper_broker_store_capability,
) = _create_formal_store_api()
del _create_formal_store_api


def _require_inputs(
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> dt.datetime:
    if type(environment) is not VerifiedPaperRuntimeEnvironment:
        raise _Failure("PAPER_FORMAL_STORE_ENVIRONMENT_INVALID")
    if type(environment.config) is not FormalPaperRuntimeConfig:
        raise _Failure("PAPER_FORMAL_STORE_ENVIRONMENT_INVALID")
    if (
        type(policy) is not VerifiedPaperExecutionPolicy
        or type(binding) is not VerifiedFormalPaperBrokerPolicyBinding
    ):
        raise _Failure("PAPER_FORMAL_STORE_POLICY_BINDING_INVALID")
    if type(account) is not VerifiedFormalPaperAccountDescriptor:
        raise _Failure("PAPER_FORMAL_STORE_ACCOUNT_INVALID")
    timestamp = _require_utc(now)
    try:
        times = (
            _require_utc(environment.verified_at),
            _require_utc(policy.verified_at),
            _require_utc(binding.verified_at),
            _require_utc(account.verified_at),
        )
    except _Failure:
        raise _Failure("PAPER_FORMAL_STORE_INVALID") from None
    if any(timestamp < value for value in times):
        raise _Failure("PAPER_FORMAL_STORE_STALE")
    return timestamp


def _verify_existing_chain(
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    account: VerifiedFormalPaperAccountDescriptor,
    now: dt.datetime,
) -> _FreshChain:
    try:
        verify_existing_paper_runtime_preflight(
            environment, config_path=environment.config.source_path, now=now
        )
    except Exception:
        raise _Failure("PAPER_FORMAL_STORE_ENVIRONMENT_INVALID") from None
    try:
        fresh_policy = verify_existing_paper_execution_policy(
            policy=policy, environment=environment, now=now
        )
        fresh_binding = verify_existing_formal_paper_broker_policy_binding(
            binding=binding, environment=environment, policy=fresh_policy, now=now
        )
    except Exception:
        raise _Failure("PAPER_FORMAL_STORE_POLICY_BINDING_INVALID") from None
    try:
        fresh_account = verify_existing_formal_paper_account_descriptor(
            capability=account,
            environment=environment,
            policy=fresh_policy,
            binding=fresh_binding,
            now=now,
        )
    except Exception:
        raise _Failure("PAPER_FORMAL_STORE_ACCOUNT_INVALID") from None
    return _FreshChain(environment, fresh_policy, fresh_binding, fresh_account)


def _reload_materialized_chain(chain: _FreshChain, now: dt.datetime) -> _FreshChain:
    environment = verify_paper_runtime_environment(config=chain.environment.config, now=now)
    policy = load_verified_paper_execution_policy(
        environment=environment, session_date=chain.policy.session_date, now=now
    )
    binding = bind_verified_formal_paper_broker_policy(
        environment=environment, policy=policy, now=now
    )
    account = load_verified_formal_paper_account_descriptor(
        environment=environment, policy=policy, binding=binding, now=now
    )
    rebuilt = _FreshChain(environment, policy, binding, account)
    _compare_materialized(chain, rebuilt)
    return rebuilt


def _compare_cold_materialized(cold: _FreshChain, current: _FreshChain) -> None:
    """Compare cold→materialized chains on economic semantics only.

    First broker-root materialization must change environment verification /
    layout identities and derived attestations. Physical presence is gated by
    ``_require_materialized`` after public ``_verify_existing_chain``; joins and
    derived-identity freshness are gated by ``_require_materialized_chain_closure``.
    """
    if (
        cold.environment.config != current.environment.config
        or cold.environment.verification_identity
        == current.environment.verification_identity
        or cold.environment.layout.layout_identity
        == current.environment.layout.layout_identity
        or _policy_economic(cold.policy) != _policy_economic(current.policy)
        or _binding_economic(cold.binding) != _binding_economic(current.binding)
        or _account_economic(cold.account) != _account_economic(current.account)
    ):
        raise _Failure("PAPER_FORMAL_STORE_STALE")
    _require_materialized_chain_closure(cold, current)


def _require_materialized_chain_closure(
    cold: _FreshChain, current: _FreshChain
) -> None:
    """Require materialized siblings join and derived attestations leave cold."""
    environment = current.environment
    policy = current.policy
    binding = current.binding
    account = current.account
    if (
        binding.runtime_environment_identity != environment.verification_identity
        or binding.runtime_config_identity != environment.config.config_identity
        or binding.execution_policy_identity != policy.policy_identity
        or account.runtime_environment_identity != environment.verification_identity
        or account.runtime_config_identity != environment.config.config_identity
        or account.execution_policy_identity != policy.policy_identity
        or account.broker_binding_identity != binding.binding_identity
        or policy.policy_identity == cold.policy.policy_identity
        or binding.binding_identity == cold.binding.binding_identity
        or account.verification_identity == cold.account.verification_identity
    ):
        raise _Failure("PAPER_FORMAL_STORE_STALE")


def _compare_materialized(left: _FreshChain, right: _FreshChain) -> None:
    if (
        left.environment.config != right.environment.config
        or left.environment.layout != right.environment.layout
        or _policy_business(left.policy) != _policy_business(right.policy)
        or _binding_business(left.binding) != _binding_business(right.binding)
        or _account_business(left.account) != _account_business(right.account)
    ):
        raise _Failure("PAPER_FORMAL_STORE_STALE")


def _policy_economic(value: VerifiedPaperExecutionPolicy) -> tuple[object, ...]:
    """Cold→materialized economic projection; excludes env-derived attestation."""
    return (
        value.schema_version,
        value.selector,
        value.session_date,
        value.source_path,
        value.source_file_identity,
        value.source_parent_identity,
        value.raw_sha256,
        value.trading_config,
        value.trading_config_identity,
        value.supported_markets,
        value.execution_cost_schedule,
        value.cost_schedule_identity,
        value.minimum_order_notionals,
        value.a_share_rule_selector,
        value.adapter_policy_version,
        value.fill_policy_version,
        value.fault_policy_version,
        value.finality_policy_version,
        value.clock_policy_version,
        value.fx_snapshot_identity,
    )


def _binding_economic(
    value: VerifiedFormalPaperBrokerPolicyBinding,
) -> tuple[object, ...]:
    """Cold→materialized economic projection; excludes env-derived identities."""
    return (
        value.schema_version,
        value.classification,
        value.session_date,
        value.runtime_config_identity,
        value.adapter_policy_version,
        value.fill_policy_version,
        value.fault_policy_version,
        value.finality_policy_version,
        value.clock_policy_version,
        value.cost_schedule_identity,
        value.fx_snapshot_identity,
    )


def _account_economic(
    value: VerifiedFormalPaperAccountDescriptor,
) -> tuple[object, ...]:
    """Cold→materialized economic projection; excludes env-derived attestations."""
    return (
        value.schema_version,
        value.classification,
        value.session_date,
        value.selector,
        value.source_path,
        value.source_file_identity,
        value.source_parent_identity,
        value.raw_sha256,
        value.runtime_config_identity,
        value.account_descriptor,
        value.account_id,
        value.initial_snapshot_identity,
        value.descriptor_identity,
        value.risk_counter_scope,
    )


def _policy_business(value: VerifiedPaperExecutionPolicy) -> tuple[object, ...]:
    return (
        value.session_date,
        value.raw_sha256,
        value.trading_config_identity,
        value.cost_schedule_identity,
        value.adapter_policy_version,
        value.fill_policy_version,
        value.fault_policy_version,
        value.finality_policy_version,
        value.clock_policy_version,
        value.fx_snapshot_identity,
        value.policy_identity,
    )


def _binding_business(
    value: VerifiedFormalPaperBrokerPolicyBinding,
) -> tuple[object, ...]:
    return (
        value.classification,
        value.session_date,
        value.execution_policy_identity,
        value.adapter_policy_version,
        value.fill_policy_version,
        value.fault_policy_version,
        value.finality_policy_version,
        value.clock_policy_version,
        value.cost_schedule_identity,
        value.fx_snapshot_identity,
    )


def _account_business(
    value: VerifiedFormalPaperAccountDescriptor,
) -> tuple[object, ...]:
    return (
        value.classification,
        value.session_date,
        value.selector,
        value.source_file_identity,
        value.raw_sha256,
        value.account_descriptor,
        value.account_id,
        value.initial_snapshot_identity,
        value.descriptor_identity,
        value.risk_counter_scope,
    )


def _verify_store(
    store: PaperBrokerStore,
    chain: _FreshChain,
    descriptor: PaperBrokerPolicyDescriptor,
) -> None:
    try:
        if type(store) is not PaperBrokerStore:
            raise ValueError
        store.verify_fresh()
        if (
            store.account_descriptor != chain.account.account_descriptor
            or store.descriptor.account_id != chain.account.account_id
            or store.descriptor.policy_identity != descriptor.descriptor_identity
            or store.policy_identity != descriptor.descriptor_identity
            or store.descriptor.created_at
            != chain.account.account_descriptor.created_at
            or store.descriptor.database_filename
            != chain.environment.config.broker_sqlite_filename
            or Path(store.descriptor.resolved_root)
            != chain.environment.config.broker_root.resolve(strict=True)
        ):
            raise ValueError
    except Exception:
        raise _Failure("PAPER_FORMAL_STORE_GENESIS_MISMATCH") from None


def _assemble_capability(
    *,
    chain: _FreshChain,
    descriptor: PaperBrokerPolicyDescriptor,
    store: PaperBrokerStore,
    now: dt.datetime,
) -> VerifiedFormalPaperBrokerStoreCapability:
    """Assemble an unattested value; only public verified paths can sign it."""
    root_identity = dict(chain.environment.layout.root_identities).get("broker")
    if type(root_identity) is not str:
        raise _Failure("PAPER_FORMAL_STORE_LAYOUT_INVALID")
    separation = _separation_identity(chain.environment.config)
    payload = _identity_payload(
        chain=chain,
        descriptor=descriptor,
        store=store,
        root_identity=root_identity,
        separation=separation,
        verified_at=now,
    )
    return VerifiedFormalPaperBrokerStoreCapability(
        schema_version=_SCHEMA_VERSION,
        classification=_CLASSIFICATION,
        session_date=chain.policy.session_date,
        runtime_environment_identity=chain.environment.verification_identity,
        runtime_config_identity=chain.environment.config.config_identity,
        runtime_layout_identity=chain.environment.layout.layout_identity,
        execution_policy_identity=chain.policy.policy_identity,
        broker_binding_identity=chain.binding.binding_identity,
        account_verification_identity=chain.account.verification_identity,
        account_id=chain.account.account_id,
        account_descriptor_identity=chain.account.descriptor_identity,
        genesis_source_identity=chain.account.source_file_identity,
        genesis_raw_sha256=chain.account.raw_sha256,
        policy_descriptor_identity=descriptor.descriptor_identity,
        store_descriptor_identity=store.descriptor.descriptor_identity,
        gateway_identity=store.gateway_identity,
        broker_root_identity=root_identity,
        database_filename=chain.environment.config.broker_sqlite_filename,
        oms_separation_identity=separation,
        capability_identity=_sha256(payload),
        verified_at=now,
        _store=store,
        _attestation=_StoreAttestation(b""),
    )


def _require_materialized(environment: VerifiedPaperRuntimeEnvironment) -> None:
    """Require the configured broker root to be a physical directory.

    Layout / attestation authenticity is supplied by public preflight inside
    ``_verify_existing_chain``; root identity bytes are opaque SHA256 digests.
    """
    if not environment.config.broker_root.is_dir():
        raise _Failure("PAPER_FORMAL_STORE_NOT_FOUND")


def _require_separation(config: FormalPaperRuntimeConfig) -> None:
    broker = config.broker_root.resolve(strict=False)
    oms = (config.runtime_root / config.oms_sqlite_filename).resolve(strict=False)
    if broker == oms or broker in oms.parents or oms in broker.parents:
        raise _Failure("PAPER_FORMAL_STORE_SEPARATION_INVALID")


def _separation_identity(config: FormalPaperRuntimeConfig) -> str:
    _require_separation(config)
    return _sha256(
        {
            "broker_root": os.path.normcase(os.path.abspath(config.broker_root)),
            "broker_sqlite_filename": config.broker_sqlite_filename,
            "oms_store": os.path.normcase(
                os.path.abspath(config.runtime_root / config.oms_sqlite_filename)
            ),
            "type": "formal-paper-store-separation-v1",
        }
    )


def _remove_owned_empty_root(
    environment: VerifiedPaperRuntimeEnvironment,
    identity: tuple[int, int, int] | None,
) -> bool:
    try:
        root = environment.config.broker_root
        if identity is None or _path_identity(root) != identity:
            return False
        if any(root.iterdir()):
            return False
        root.rmdir()
        return True
    except BaseException:
        return False


def _path_identity(path: Path) -> tuple[int, int, int]:
    status = path.lstat()
    if (
        not stat.S_ISDIR(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or bool(getattr(status, "st_file_attributes", 0) & _REPARSE_POINT)
    ):
        raise _Failure("PAPER_FORMAL_STORE_LAYOUT_INVALID")
    return status.st_dev, status.st_ino, stat.S_IFMT(status.st_mode)


def _identity_payload(
    *,
    chain: _FreshChain,
    descriptor: PaperBrokerPolicyDescriptor,
    store: PaperBrokerStore,
    root_identity: str,
    separation: str,
    verified_at: dt.datetime,
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "classification": _CLASSIFICATION,
        "session_date": chain.policy.session_date.isoformat(),
        "runtime_environment_identity": chain.environment.verification_identity,
        "runtime_config_identity": chain.environment.config.config_identity,
        "runtime_layout_identity": chain.environment.layout.layout_identity,
        "execution_policy_identity": chain.policy.policy_identity,
        "broker_binding_identity": chain.binding.binding_identity,
        "account_verification_identity": chain.account.verification_identity,
        "account_id": chain.account.account_id,
        "account_descriptor_identity": chain.account.descriptor_identity,
        "genesis_source_identity": chain.account.source_file_identity,
        "genesis_raw_sha256": chain.account.raw_sha256,
        "policy_descriptor_identity": descriptor.descriptor_identity,
        "store_descriptor_identity": store.descriptor.descriptor_identity,
        "gateway_identity": store.gateway_identity,
        "broker_root_identity": root_identity,
        "database_filename": chain.environment.config.broker_sqlite_filename,
        "oms_separation_identity": separation,
        "verified_at": verified_at.isoformat(timespec="microseconds"),
    }


def _stable_identity_projection(payload: dict[str, object]) -> dict[str, object]:
    return dict(payload)


def _stable_capability_payload(
    capability: VerifiedFormalPaperBrokerStoreCapability,
) -> dict[str, object]:
    return {
        key: value
        for key, value in _capability_payload(capability).items()
        if key != "capability_identity"
    }


def _capability_payload(
    capability: VerifiedFormalPaperBrokerStoreCapability,
) -> dict[str, object]:
    return {
        "schema_version": capability.schema_version,
        "classification": capability.classification,
        "session_date": capability.session_date.isoformat(),
        "runtime_environment_identity": capability.runtime_environment_identity,
        "runtime_config_identity": capability.runtime_config_identity,
        "runtime_layout_identity": capability.runtime_layout_identity,
        "execution_policy_identity": capability.execution_policy_identity,
        "broker_binding_identity": capability.broker_binding_identity,
        "account_verification_identity": capability.account_verification_identity,
        "account_id": capability.account_id,
        "account_descriptor_identity": capability.account_descriptor_identity,
        "genesis_source_identity": capability.genesis_source_identity,
        "genesis_raw_sha256": capability.genesis_raw_sha256,
        "policy_descriptor_identity": capability.policy_descriptor_identity,
        "store_descriptor_identity": capability.store_descriptor_identity,
        "gateway_identity": capability.gateway_identity,
        "broker_root_identity": capability.broker_root_identity,
        "database_filename": capability.database_filename,
        "oms_separation_identity": capability.oms_separation_identity,
        "capability_identity": capability.capability_identity,
        "verified_at": capability.verified_at.isoformat(timespec="microseconds"),
    }


def _require_utc(value: dt.datetime) -> dt.datetime:
    if (
        type(value) is not dt.datetime
        or value.tzinfo is None
        or value.utcoffset() != dt.timedelta(0)
    ):
        raise _Failure("PAPER_FORMAL_STORE_INVALID")
    return value


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


__all__ = [
    "FormalPaperBrokerStoreError",
    "VerifiedFormalPaperBrokerStoreCapability",
    "initialize_verified_formal_paper_broker_store",
    "open_verified_formal_paper_broker_store",
    "verify_existing_formal_paper_broker_store_capability",
]
