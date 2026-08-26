"""Fresh formal PAPER runtime bootstrap: new root / new epoch composition.

Composes already-merged public loaders, initializers and verifiers only.
Does not mint session barriers directly, copy P2 projections, adopt old roots,
or return raw tokens / secrets / SQLite connections / private store objects.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn, SupportsIndex

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text
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
from quant.execution.paper_formal_broker_store import (
    FormalPaperBrokerStoreError,
    VerifiedFormalPaperBrokerStoreCapability,
    initialize_verified_formal_paper_broker_store,
    open_verified_formal_paper_broker_store,
    verify_existing_formal_paper_broker_store_capability,
)
from quant.execution.paper_formal_execution_store import (
    FormalPaperExecutionStoreError,
    VerifiedFormalPaperExecutionStoreCapability,
    initialize_verified_formal_paper_execution_store,
    open_verified_formal_paper_execution_store,
    verify_existing_formal_paper_execution_store_capability,
)
from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    load_verified_paper_execution_policy,
    verify_existing_paper_execution_policy,
)
from quant.execution.paper_runtime import (
    FormalPaperRuntimeConfig,
    PaperRuntimeError,
    VerifiedPaperRuntimeEnvironment,
    load_paper_runtime_config,
    verify_existing_paper_runtime_preflight,
    verify_paper_runtime_environment,
)
from quant.execution.session_barrier import SessionBarrierRow

_SCHEMA = "formal-paper-runtime-bootstrap-v1"
_CLASSIFICATION = "formal-paper-simulation"


class FormalPaperBootstrapError(ValueError):
    """Stable, sanitized formal bootstrap failure; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"FormalPaperBootstrapError({self.code!r})"

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
        raise TypeError("formal PAPER runtime bootstrap is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperRuntimeBootstrap:
    """Process-local proof of a fresh or reopened formal PAPER runtime."""

    schema_version: str
    classification: str
    bootstrap_identity: str
    session_date: dt.date
    config_path: Path = field(repr=False, compare=False)
    config_identity: str
    config_raw_sha256: str
    source_file_identity: str
    runtime_environment_identity: str
    runtime_layout_identity: str
    execution_policy_identity: str
    broker_binding_identity: str
    account_verification_identity: str
    account_id: str
    broker_capability_identity: str
    gateway_identity: str
    execution_store_identity: str
    barrier_epoch: str
    barrier_capability_identity: str
    barrier_lock_identity: str
    verified_at: dt.datetime
    environment: VerifiedPaperRuntimeEnvironment = field(repr=False, compare=False)
    policy: VerifiedPaperExecutionPolicy = field(repr=False, compare=False)
    binding: VerifiedFormalPaperBrokerPolicyBinding = field(repr=False, compare=False)
    account: VerifiedFormalPaperAccountDescriptor = field(repr=False, compare=False)
    broker_store: VerifiedFormalPaperBrokerStoreCapability = field(
        repr=False, compare=False
    )
    execution_store: VerifiedFormalPaperExecutionStoreCapability = field(
        repr=False, compare=False
    )
    _attestation: _Attestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER runtime bootstrap is process-local")

    def __copy__(self) -> NoReturn:
        raise TypeError("formal PAPER runtime bootstrap is process-local")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("formal PAPER runtime bootstrap is process-local")

    def __replace__(self, **changes: object) -> NoReturn:
        del changes
        raise TypeError("formal PAPER runtime bootstrap is process-local")


class _Failure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


@dataclass(frozen=True, slots=True)
class _FreshChain:
    environment: VerifiedPaperRuntimeEnvironment
    policy: VerifiedPaperExecutionPolicy
    binding: VerifiedFormalPaperBrokerPolicyBinding
    account: VerifiedFormalPaperAccountDescriptor


def _create_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def token(value: VerifiedFormalPaperRuntimeBootstrap) -> bytes:
        return hmac.new(
            key, canonical_json_bytes(_capability_payload(value)), hashlib.sha256
        ).digest()

    def valid(value: VerifiedFormalPaperRuntimeBootstrap) -> bool:
        try:
            return type(value._attestation) is _Attestation and hmac.compare_digest(
                value._attestation.token, token(value)
            )
        except Exception:
            return False

    def mint(
        *,
        chain: _FreshChain,
        broker_store: VerifiedFormalPaperBrokerStoreCapability,
        execution_store: VerifiedFormalPaperExecutionStoreCapability,
        now: dt.datetime,
    ) -> VerifiedFormalPaperRuntimeBootstrap:
        config = chain.environment.config
        if type(config) is not FormalPaperRuntimeConfig:
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID")
        if (
            execution_store.environment is not chain.environment
            or execution_store.policy is not chain.policy
            or execution_store.binding is not chain.binding
            or execution_store.account is not chain.account
            or execution_store.broker_store is not broker_store
        ):
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
        _require_broker_matches_chain(broker_store, chain)
        if (
            broker_store.capability_identity
            != execution_store.broker_store.capability_identity
            or execution_store.account_id != chain.account.account_id
            or execution_store.gateway_identity != broker_store.gateway_identity
            or execution_store.policy_descriptor_identity
            != broker_store.policy_descriptor_identity
        ):
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
        lock_identity = _require_open_barrier(execution_store)
        payload = _identity_payload(
            chain=chain,
            broker_store=broker_store,
            execution_store=execution_store,
            barrier_lock_identity=lock_identity,
            verified_at=now,
        )
        value = VerifiedFormalPaperRuntimeBootstrap(
            schema_version=_SCHEMA,
            classification=_CLASSIFICATION,
            bootstrap_identity=_sha256(payload),
            session_date=chain.policy.session_date,
            config_path=config.source_path,
            config_identity=config.config_identity,
            config_raw_sha256=config.raw_sha256,
            source_file_identity=config.source_file_identity,
            runtime_environment_identity=chain.environment.verification_identity,
            runtime_layout_identity=chain.environment.layout.layout_identity,
            execution_policy_identity=chain.policy.policy_identity,
            broker_binding_identity=chain.binding.binding_identity,
            account_verification_identity=chain.account.verification_identity,
            account_id=chain.account.account_id,
            broker_capability_identity=broker_store.capability_identity,
            gateway_identity=broker_store.gateway_identity,
            execution_store_identity=execution_store.store_identity,
            barrier_epoch=execution_store.barrier_epoch,
            barrier_capability_identity=execution_store.barrier_capability_identity,
            barrier_lock_identity=lock_identity,
            verified_at=now,
            environment=chain.environment,
            policy=chain.policy,
            binding=chain.binding,
            account=chain.account,
            broker_store=broker_store,
            execution_store=execution_store,
            _attestation=_Attestation(b""),
        )
        object.__setattr__(value, "_attestation", _Attestation(token(value)))
        if not valid(value):
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_INVALID")
        if _stable_projection(value) != _stable_identity_projection(payload):
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_INVALID")
        _require_result_broker_field_closure(value)
        return value

    def bootstrap_fresh_formal_paper_runtime(
        *,
        config_path: Path,
        session_date: dt.date,
        now: dt.datetime,
    ) -> VerifiedFormalPaperRuntimeBootstrap:
        """Create a new formal root/epoch by composing public initializers only."""
        broker: VerifiedFormalPaperBrokerStoreCapability | None = None
        execution: VerifiedFormalPaperExecutionStoreCapability | None = None
        broker_materialized = False
        try:
            timestamp = _require_utc(now)
            path = _require_exact_config_path(config_path)
            if type(session_date) is not dt.date:
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_CHAIN_INVALID")
            config = _load_formal_config(path)
            _require_absent_runtime_roots(config)
            cold = _load_cold_chain(config=config, session_date=session_date, now=timestamp)
            _require_absent_runtime_roots(cold.environment.config)
            broker = initialize_verified_formal_paper_broker_store(
                environment=cold.environment,
                policy=cold.policy,
                binding=cold.binding,
                account=cold.account,
                now=timestamp,
            )
            broker_materialized = True
            materialized = _reload_materialized_chain(cold, timestamp)
            _require_materialized_left_cold(cold, materialized)
            _require_public_chain_join(materialized)
            _require_economic_stability(cold, materialized)
            broker = verify_existing_formal_paper_broker_store_capability(
                capability=broker,
                environment=materialized.environment,
                policy=materialized.policy,
                binding=materialized.binding,
                account=materialized.account,
                now=timestamp,
            )
            _require_broker_matches_chain(broker, materialized)
            if (
                broker.runtime_environment_identity
                == cold.environment.verification_identity
                or broker.execution_policy_identity == cold.policy.policy_identity
                or broker.broker_binding_identity == cold.binding.binding_identity
                or broker.account_verification_identity
                == cold.account.verification_identity
            ):
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            execution = initialize_verified_formal_paper_execution_store(
                broker_store=broker,
                environment=materialized.environment,
                policy=materialized.policy,
                binding=materialized.binding,
                account=materialized.account,
                now=timestamp,
            )
            if execution.broker_store is not broker:
                _close_quiet(broker)
                broker = execution.broker_store
            final_broker = verify_existing_formal_paper_broker_store_capability(
                capability=execution.broker_store,
                environment=execution.environment,
                policy=execution.policy,
                binding=execution.binding,
                account=execution.account,
                now=timestamp,
            )
            if final_broker is not execution.broker_store:
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            final_execution = verify_existing_formal_paper_execution_store_capability(
                capability=execution, now=timestamp
            )
            if final_execution is not execution:
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            final_chain = _FreshChain(
                execution.environment,
                execution.policy,
                execution.binding,
                execution.account,
            )
            return mint(
                chain=final_chain,
                broker_store=final_broker,
                execution_store=final_execution,
                now=timestamp,
            )
        except _Failure as exc:
            failure = exc.code
        except FormalPaperBootstrapError as exc:
            failure = exc.code
        except FormalPaperBrokerStoreError as exc:
            failure = _map_broker_error(exc.code, materialized=broker_materialized)
        except FormalPaperExecutionStoreError as exc:
            failure = _map_execution_error(exc.code, materialized=broker_materialized)
        except PaperRuntimeError as exc:
            failure = _map_runtime_error(exc.code)
        except Exception:
            failure = "PAPER_FORMAL_BOOTSTRAP_INVALID"
        _close_quiet(execution)
        _close_quiet(broker)
        if broker_materialized and execution is None:
            failure = "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED"
        raise FormalPaperBootstrapError(failure) from None

    def reopen_verified_formal_paper_runtime(
        *,
        config_path: Path,
        session_date: dt.date,
        now: dt.datetime,
    ) -> VerifiedFormalPaperRuntimeBootstrap:
        """Exact reopen of a complete OPEN formal bundle; never re-runs initializers."""
        broker: VerifiedFormalPaperBrokerStoreCapability | None = None
        execution: VerifiedFormalPaperExecutionStoreCapability | None = None
        try:
            timestamp = _require_utc(now)
            path = _require_exact_config_path(config_path)
            if type(session_date) is not dt.date:
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_CHAIN_INVALID")
            config = _load_formal_config(path)
            chain = _load_materialized_open_chain(
                config=config, session_date=session_date, now=timestamp
            )
            broker = open_verified_formal_paper_broker_store(
                environment=chain.environment,
                policy=chain.policy,
                binding=chain.binding,
                account=chain.account,
                now=timestamp,
            )
            execution = open_verified_formal_paper_execution_store(
                environment=chain.environment,
                policy=chain.policy,
                binding=chain.binding,
                account=chain.account,
                broker_store=broker,
                now=timestamp,
            )
            final_broker = verify_existing_formal_paper_broker_store_capability(
                capability=execution.broker_store,
                environment=execution.environment,
                policy=execution.policy,
                binding=execution.binding,
                account=execution.account,
                now=timestamp,
            )
            if final_broker is not execution.broker_store:
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            final_execution = verify_existing_formal_paper_execution_store_capability(
                capability=execution, now=timestamp
            )
            if final_execution is not execution:
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            final_chain = _FreshChain(
                execution.environment,
                execution.policy,
                execution.binding,
                execution.account,
            )
            return mint(
                chain=final_chain,
                broker_store=final_broker,
                execution_store=final_execution,
                now=timestamp,
            )
        except _Failure as exc:
            failure = exc.code
        except FormalPaperBootstrapError as exc:
            failure = exc.code
        except FormalPaperBrokerStoreError as exc:
            failure = _map_broker_error(exc.code, materialized=True)
        except FormalPaperExecutionStoreError as exc:
            failure = _map_execution_error(exc.code, materialized=True)
        except PaperRuntimeError as exc:
            failure = _map_runtime_error(exc.code)
        except Exception:
            failure = "PAPER_FORMAL_BOOTSTRAP_NOT_FOUND"
        _close_quiet(execution)
        _close_quiet(broker)
        raise FormalPaperBootstrapError(failure) from None

    def verify_existing_formal_paper_runtime_bootstrap(
        *,
        bootstrap: VerifiedFormalPaperRuntimeBootstrap,
        now: dt.datetime,
    ) -> VerifiedFormalPaperRuntimeBootstrap:
        """Fresh-verify a retained process-local OPEN bootstrap bundle."""
        try:
            timestamp = _require_utc(now)
            if (
                type(bootstrap) is not VerifiedFormalPaperRuntimeBootstrap
                or not valid(bootstrap)
                or timestamp < bootstrap.verified_at
            ):
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_INVALID")
            verify_existing_paper_runtime_preflight(
                bootstrap.environment,
                config_path=bootstrap.config_path,
                now=timestamp,
            )
            policy = verify_existing_paper_execution_policy(
                policy=bootstrap.policy,
                environment=bootstrap.environment,
                now=timestamp,
            )
            binding = verify_existing_formal_paper_broker_policy_binding(
                binding=bootstrap.binding,
                environment=bootstrap.environment,
                policy=policy,
                now=timestamp,
            )
            account = verify_existing_formal_paper_account_descriptor(
                capability=bootstrap.account,
                environment=bootstrap.environment,
                policy=policy,
                binding=binding,
                now=timestamp,
            )
            if (
                policy is not bootstrap.policy
                or binding is not bootstrap.binding
                or account is not bootstrap.account
            ):
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            broker = verify_existing_formal_paper_broker_store_capability(
                capability=bootstrap.broker_store,
                environment=bootstrap.environment,
                policy=bootstrap.policy,
                binding=bootstrap.binding,
                account=bootstrap.account,
                now=timestamp,
            )
            execution = verify_existing_formal_paper_execution_store_capability(
                capability=bootstrap.execution_store, now=timestamp
            )
            if (
                broker is not bootstrap.broker_store
                or execution is not bootstrap.execution_store
                or execution.broker_store is not broker
            ):
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            chain = _FreshChain(
                bootstrap.environment,
                bootstrap.policy,
                bootstrap.binding,
                bootstrap.account,
            )
            _require_public_chain_join(chain)
            _require_broker_matches_chain(broker, chain)
            _require_open_barrier(
                execution, expected_lock_identity=bootstrap.barrier_lock_identity
            )
            rebuilt = _identity_payload(
                chain=chain,
                broker_store=broker,
                execution_store=execution,
                barrier_lock_identity=bootstrap.barrier_lock_identity,
                verified_at=bootstrap.verified_at,
            )
            if (
                bootstrap.bootstrap_identity != _sha256(rebuilt)
                or _stable_projection(bootstrap) != _stable_identity_projection(rebuilt)
            ):
                raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
            _require_result_broker_field_closure(bootstrap)
            return bootstrap
        except _Failure as exc:
            failure = exc.code
        except FormalPaperBootstrapError as exc:
            failure = exc.code
        except FormalPaperBrokerStoreError:
            failure = "PAPER_FORMAL_BOOTSTRAP_STALE"
        except FormalPaperExecutionStoreError:
            failure = "PAPER_FORMAL_BOOTSTRAP_STALE"
        except PaperRuntimeError:
            failure = "PAPER_FORMAL_BOOTSTRAP_STALE"
        except Exception:
            failure = "PAPER_FORMAL_BOOTSTRAP_STALE"
        raise FormalPaperBootstrapError(failure) from None

    return (
        bootstrap_fresh_formal_paper_runtime,
        reopen_verified_formal_paper_runtime,
        verify_existing_formal_paper_runtime_bootstrap,
    )


(
    bootstrap_fresh_formal_paper_runtime,
    reopen_verified_formal_paper_runtime,
    verify_existing_formal_paper_runtime_bootstrap,
) = _create_api()
del _create_api


def _require_exact_config_path(path: object) -> Path:
    """Accept only the current-platform concrete Path; reject PurePath and subclasses."""
    if type(path) is not type(Path()):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_PATH_INVALID")
    if not path.is_absolute() or path != path.absolute():
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_PATH_INVALID")
    return path


def _load_formal_config(path: Path) -> FormalPaperRuntimeConfig:
    try:
        config = load_paper_runtime_config(path)
    except PaperRuntimeError as exc:
        raise _Failure(_map_runtime_error(exc.code)) from None
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID") from None
    if type(config) is not FormalPaperRuntimeConfig:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID")
    fresh = load_paper_runtime_config(path)
    if type(fresh) is not FormalPaperRuntimeConfig or fresh != config:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID")
    if fresh.source_path != config.source_path or fresh.raw_sha256 != config.raw_sha256:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID")
    return config


def _require_absent_runtime_roots(config: FormalPaperRuntimeConfig) -> None:
    roots = (
        config.runtime_root,
        config.broker_root,
        config.evidence_root,
        config.anchor_root,
        config.log_root,
    )
    parents = {root.parent for root in roots}
    if len(parents) != 1:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID")
    parent = next(iter(parents))
    if not parent.is_absolute() or any(not root.is_absolute() for root in roots):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID")
    if len({root for root in roots}) != 5:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID")
    for root in roots:
        if root.exists():
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_ROOTS_NOT_ABSENT")
        if root.parent != parent:
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID")


def _load_cold_chain(
    *,
    config: FormalPaperRuntimeConfig,
    session_date: dt.date,
    now: dt.datetime,
) -> _FreshChain:
    try:
        environment = verify_paper_runtime_environment(config=config, now=now)
    except PaperRuntimeError as exc:
        raise _Failure(_map_runtime_error(exc.code)) from None
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID") from None
    return _build_chain_from_environment(
        environment=environment, session_date=session_date, now=now
    )


def _load_materialized_open_chain(
    *,
    config: FormalPaperRuntimeConfig,
    session_date: dt.date,
    now: dt.datetime,
) -> _FreshChain:
    if not config.broker_root.is_dir() or not config.runtime_root.is_dir():
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_NOT_FOUND")
    try:
        environment = verify_paper_runtime_environment(config=config, now=now)
    except PaperRuntimeError as exc:
        raise _Failure(_map_runtime_error(exc.code)) from None
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID") from None
    return _build_chain_from_environment(
        environment=environment, session_date=session_date, now=now
    )


def _build_chain_from_environment(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    session_date: dt.date,
    now: dt.datetime,
) -> _FreshChain:
    try:
        policy = load_verified_paper_execution_policy(
            environment=environment, session_date=session_date, now=now
        )
        binding = bind_verified_formal_paper_broker_policy(
            environment=environment, policy=policy, now=now
        )
        account = load_verified_formal_paper_account_descriptor(
            environment=environment, policy=policy, binding=binding, now=now
        )
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_CHAIN_INVALID") from None
    return _FreshChain(environment, policy, binding, account)


def _reload_materialized_chain(cold: _FreshChain, now: dt.datetime) -> _FreshChain:
    try:
        environment = verify_paper_runtime_environment(
            config=cold.environment.config, now=now
        )
        policy = load_verified_paper_execution_policy(
            environment=environment,
            session_date=cold.policy.session_date,
            now=now,
        )
        binding = bind_verified_formal_paper_broker_policy(
            environment=environment, policy=policy, now=now
        )
        account = load_verified_formal_paper_account_descriptor(
            environment=environment, policy=policy, binding=binding, now=now
        )
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE") from None
    current = _FreshChain(environment, policy, binding, account)
    _require_materialized_left_cold(cold, current)
    _require_public_chain_join(current)
    _require_economic_stability(cold, current)
    if (
        environment.verification_identity == cold.environment.verification_identity
        or environment.layout.layout_identity == cold.environment.layout.layout_identity
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
    return current


def _require_materialized_left_cold(cold: _FreshChain, current: _FreshChain) -> None:
    """Reject fresh reload that still carries cold policy/binding/account identities."""
    if (
        current.environment.config != cold.environment.config
        or current.account.account_id != cold.account.account_id
        or current.policy.session_date != cold.policy.session_date
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
    if (
        current.policy.policy_identity == cold.policy.policy_identity
        or current.binding.binding_identity == cold.binding.binding_identity
        or current.account.verification_identity == cold.account.verification_identity
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")


def _require_public_chain_join(chain: _FreshChain) -> None:
    """Join materialized siblings using only public capability fields."""
    environment = chain.environment
    policy = chain.policy
    binding = chain.binding
    account = chain.account
    config = environment.config
    if type(config) is not FormalPaperRuntimeConfig:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
    if (
        binding.runtime_environment_identity != environment.verification_identity
        or binding.runtime_config_identity != config.config_identity
        or binding.execution_policy_identity != policy.policy_identity
        or binding.cost_schedule_identity != policy.cost_schedule_identity
        or binding.session_date != policy.session_date
        or account.runtime_environment_identity != environment.verification_identity
        or account.runtime_config_identity != config.config_identity
        or account.execution_policy_identity != policy.policy_identity
        or account.broker_binding_identity != binding.binding_identity
        or account.session_date != policy.session_date
        or account.session_date != binding.session_date
        or account.account_id != account.account_descriptor.account_id
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")


def _require_economic_stability(cold: _FreshChain, current: _FreshChain) -> None:
    """Stable economic public fields must survive materialization; env attestations may change."""
    cold_policy = cold.policy
    current_policy = current.policy
    cold_binding = cold.binding
    current_binding = current.binding
    cold_account = cold.account
    current_account = current.account
    if (
        cold.environment.config.config_identity
        != current.environment.config.config_identity
        or cold.environment.config.raw_sha256 != current.environment.config.raw_sha256
        or cold.environment.config.source_file_identity
        != current.environment.config.source_file_identity
        or cold_policy.source_path != current_policy.source_path
        or cold_policy.source_file_identity != current_policy.source_file_identity
        or cold_policy.raw_sha256 != current_policy.raw_sha256
        or cold_policy.cost_schedule_identity != current_policy.cost_schedule_identity
        or cold_policy.trading_config_identity != current_policy.trading_config_identity
        or cold_policy.selector != current_policy.selector
        or cold_binding.cost_schedule_identity != current_binding.cost_schedule_identity
        or cold_account.source_path != current_account.source_path
        or cold_account.source_file_identity != current_account.source_file_identity
        or cold_account.raw_sha256 != current_account.raw_sha256
        or cold_account.account_descriptor != current_account.account_descriptor
        or cold_account.descriptor_identity != current_account.descriptor_identity
        or cold_account.initial_snapshot_identity
        != current_account.initial_snapshot_identity
        or cold_account.selector != current_account.selector
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")


def _require_broker_matches_chain(
    broker_store: VerifiedFormalPaperBrokerStoreCapability, chain: _FreshChain
) -> None:
    """Field-level broker capability ↔ materialized chain closure (no P2 private helpers)."""
    config = chain.environment.config
    if type(broker_store) is not VerifiedFormalPaperBrokerStoreCapability:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
    if type(config) is not FormalPaperRuntimeConfig:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")
    try:
        broker_root_identity = dict(chain.environment.layout.root_identities)["broker"]
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE") from None
    if (
        broker_store.runtime_environment_identity
        != chain.environment.verification_identity
        or broker_store.runtime_layout_identity
        != chain.environment.layout.layout_identity
        or broker_store.runtime_config_identity != config.config_identity
        or broker_store.execution_policy_identity != chain.policy.policy_identity
        or broker_store.broker_binding_identity != chain.binding.binding_identity
        or broker_store.account_verification_identity
        != chain.account.verification_identity
        or broker_store.session_date != chain.policy.session_date
        or broker_store.session_date != chain.account.session_date
        or broker_store.account_id != chain.account.account_id
        or broker_store.account_descriptor_identity != chain.account.descriptor_identity
        or broker_store.broker_root_identity != broker_root_identity
        or broker_store.database_filename != config.broker_sqlite_filename
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")


def _require_result_broker_field_closure(
    value: VerifiedFormalPaperRuntimeBootstrap,
) -> None:
    broker = value.broker_store
    if (
        value.runtime_environment_identity != broker.runtime_environment_identity
        or value.runtime_layout_identity != broker.runtime_layout_identity
        or value.config_identity != broker.runtime_config_identity
        or value.execution_policy_identity != broker.execution_policy_identity
        or value.broker_binding_identity != broker.broker_binding_identity
        or value.account_verification_identity != broker.account_verification_identity
        or value.account_id != broker.account_id
        or value.session_date != broker.session_date
        or value.gateway_identity != broker.gateway_identity
        or value.broker_capability_identity != broker.capability_identity
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_STALE")


def _require_open_barrier(
    execution_store: VerifiedFormalPaperExecutionStoreCapability,
    *,
    expected_lock_identity: str | None = None,
) -> str:
    try:
        if not execution_store.store.session_barrier_enabled():
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID")
        if not execution_store.broker_store.store.session_barrier_enabled():
            raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID")
        row = execution_store.store.read_session_barrier_row()
        again = execution_store.store.read_session_barrier_row()
    except _Failure:
        raise
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID") from None
    if type(row) is not SessionBarrierRow or type(again) is not SessionBarrierRow:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID")
    if row != again or row.state != "OPEN":
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID")
    try:
        broker_store_identity = (
            execution_store.broker_store.store.descriptor.descriptor_identity
        )
    except Exception:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID") from None
    session_text = execution_store.policy.session_date.isoformat()
    if (
        row.barrier_epoch != execution_store.barrier_epoch
        or row.session_date != session_text
        or row.account_identity != execution_store.account.descriptor_identity
        or row.oms_store_identity != execution_store.store_identity
        or row.broker_store_identity != broker_store_identity
        or row.gateway_identity != execution_store.gateway_identity
        or row.config_identity != execution_store.environment.config.config_identity
        or type(row.lock_identity) is not str
        or len(row.lock_identity) != 64
        or any(character not in "0123456789abcdef" for character in row.lock_identity)
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID")
    if (
        expected_lock_identity is not None
        and row.lock_identity != expected_lock_identity
    ):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID")
    return row.lock_identity


def _close_quiet(capability: object | None) -> None:
    if capability is None:
        return
    store = getattr(capability, "store", None)
    if store is None:
        return
    closer = getattr(store, "close", None)
    if closer is None:
        return
    try:
        closer()
    except Exception:
        return


def _map_runtime_error(code: str) -> str:
    mapping = {
        "PAPER_RUNTIME_CONFIG_INVALID": "PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID",
        "PAPER_RUNTIME_MODE_INVALID": "PAPER_FORMAL_BOOTSTRAP_CONFIG_INVALID",
        "PAPER_RUNTIME_LAYOUT_INVALID": "PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID",
        "PAPER_RUNTIME_PLATFORM_UNSUPPORTED": "PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID",
        "PAPER_RUNTIME_VERIFY_FAILED": "PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID",
        "PAPER_RUNTIME_PREFLIGHT_INVALID": "PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID",
    }
    return mapping.get(code, "PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID")


def _map_broker_error(code: str, *, materialized: bool) -> str:
    if code == "PAPER_FORMAL_STORE_ROLLBACK_REQUIRED" or (
        materialized and code in {"PAPER_FORMAL_STORE_INVALID", "PAPER_FORMAL_STORE_STALE"}
    ):
        return "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED"
    mapping = {
        "PAPER_FORMAL_STORE_ALREADY_EXISTS": "PAPER_FORMAL_BOOTSTRAP_ROOTS_NOT_ABSENT",
        "PAPER_FORMAL_STORE_NOT_FOUND": "PAPER_FORMAL_BOOTSTRAP_NOT_FOUND",
        "PAPER_FORMAL_STORE_ENVIRONMENT_INVALID": (
            "PAPER_FORMAL_BOOTSTRAP_ENVIRONMENT_INVALID"
        ),
        "PAPER_FORMAL_STORE_POLICY_BINDING_INVALID": (
            "PAPER_FORMAL_BOOTSTRAP_CHAIN_INVALID"
        ),
        "PAPER_FORMAL_STORE_ACCOUNT_INVALID": "PAPER_FORMAL_BOOTSTRAP_CHAIN_INVALID",
        "PAPER_FORMAL_STORE_STALE": "PAPER_FORMAL_BOOTSTRAP_STALE",
        "PAPER_FORMAL_STORE_LAYOUT_INVALID": "PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID",
        "PAPER_FORMAL_STORE_SEPARATION_INVALID": "PAPER_FORMAL_BOOTSTRAP_LAYOUT_INVALID",
        "PAPER_FORMAL_STORE_GENESIS_MISMATCH": "PAPER_FORMAL_BOOTSTRAP_STALE",
        "PAPER_FORMAL_STORE_INVALID": "PAPER_FORMAL_BOOTSTRAP_INVALID",
    }
    return mapping.get(code, "PAPER_FORMAL_BOOTSTRAP_INVALID")


def _map_execution_error(code: str, *, materialized: bool) -> str:
    if code.endswith("ROLLBACK_REQUIRED") or (
        materialized
        and code
        in {
            "PAPER_FORMAL_EXECUTION_STORE_INVALID",
            "PAPER_FORMAL_EXECUTION_STORE_STALE",
        }
    ):
        return "PAPER_FORMAL_BOOTSTRAP_ROLLBACK_REQUIRED"
    if code.startswith("BARRIER_"):
        return "PAPER_FORMAL_BOOTSTRAP_BARRIER_STATE_INVALID"
    mapping = {
        "PAPER_FORMAL_EXECUTION_STORE_ALREADY_EXISTS": (
            "PAPER_FORMAL_BOOTSTRAP_ROOTS_NOT_ABSENT"
        ),
        "PAPER_FORMAL_EXECUTION_STORE_NOT_FOUND": "PAPER_FORMAL_BOOTSTRAP_NOT_FOUND",
        "PAPER_FORMAL_EXECUTION_STORE_STALE": "PAPER_FORMAL_BOOTSTRAP_STALE",
        "PAPER_FORMAL_EXECUTION_STORE_INVALID": "PAPER_FORMAL_BOOTSTRAP_INVALID",
    }
    return mapping.get(code, "PAPER_FORMAL_BOOTSTRAP_INVALID")


def _require_utc(value: dt.datetime) -> dt.datetime:
    if type(value) is not dt.datetime or value.tzinfo is None:
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_INVALID")
    if value.utcoffset() != dt.timedelta(0):
        raise _Failure("PAPER_FORMAL_BOOTSTRAP_INVALID")
    return value.astimezone(dt.timezone.utc).replace(tzinfo=dt.timezone.utc)


def _identity_payload(
    *,
    chain: _FreshChain,
    broker_store: VerifiedFormalPaperBrokerStoreCapability,
    execution_store: VerifiedFormalPaperExecutionStoreCapability,
    barrier_lock_identity: str,
    verified_at: dt.datetime,
) -> dict[str, object]:
    config = chain.environment.config
    return {
        "schema_version": _SCHEMA,
        "classification": _CLASSIFICATION,
        "session_date": chain.policy.session_date.isoformat(),
        "config_identity": config.config_identity,
        "config_raw_sha256": config.raw_sha256,
        "source_file_identity": config.source_file_identity,
        "runtime_environment_identity": chain.environment.verification_identity,
        "runtime_layout_identity": chain.environment.layout.layout_identity,
        "execution_policy_identity": chain.policy.policy_identity,
        "broker_binding_identity": chain.binding.binding_identity,
        "account_verification_identity": chain.account.verification_identity,
        "account_id": chain.account.account_id,
        "broker_capability_identity": broker_store.capability_identity,
        "gateway_identity": broker_store.gateway_identity,
        "execution_store_identity": execution_store.store_identity,
        "barrier_epoch": execution_store.barrier_epoch,
        "barrier_capability_identity": execution_store.barrier_capability_identity,
        "barrier_lock_identity": barrier_lock_identity,
        "verified_at": utc_datetime_text(verified_at),
    }


def _capability_payload(value: VerifiedFormalPaperRuntimeBootstrap) -> dict[str, object]:
    return {
        **_stable_projection(value),
        "verified_at": utc_datetime_text(value.verified_at),
    }


def _stable_projection(value: VerifiedFormalPaperRuntimeBootstrap) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "classification": value.classification,
        "bootstrap_identity": value.bootstrap_identity,
        "session_date": value.session_date.isoformat(),
        "config_identity": value.config_identity,
        "config_raw_sha256": value.config_raw_sha256,
        "source_file_identity": value.source_file_identity,
        "runtime_environment_identity": value.runtime_environment_identity,
        "runtime_layout_identity": value.runtime_layout_identity,
        "execution_policy_identity": value.execution_policy_identity,
        "broker_binding_identity": value.broker_binding_identity,
        "account_verification_identity": value.account_verification_identity,
        "account_id": value.account_id,
        "broker_capability_identity": value.broker_capability_identity,
        "gateway_identity": value.gateway_identity,
        "execution_store_identity": value.execution_store_identity,
        "barrier_epoch": value.barrier_epoch,
        "barrier_capability_identity": value.barrier_capability_identity,
        "barrier_lock_identity": value.barrier_lock_identity,
    }


def _stable_identity_projection(payload: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": payload["schema_version"],
        "classification": payload["classification"],
        "bootstrap_identity": _sha256(payload),
        "session_date": payload["session_date"],
        "config_identity": payload["config_identity"],
        "config_raw_sha256": payload["config_raw_sha256"],
        "source_file_identity": payload["source_file_identity"],
        "runtime_environment_identity": payload["runtime_environment_identity"],
        "runtime_layout_identity": payload["runtime_layout_identity"],
        "execution_policy_identity": payload["execution_policy_identity"],
        "broker_binding_identity": payload["broker_binding_identity"],
        "account_verification_identity": payload["account_verification_identity"],
        "account_id": payload["account_id"],
        "broker_capability_identity": payload["broker_capability_identity"],
        "gateway_identity": payload["gateway_identity"],
        "execution_store_identity": payload["execution_store_identity"],
        "barrier_epoch": payload["barrier_epoch"],
        "barrier_capability_identity": payload["barrier_capability_identity"],
        "barrier_lock_identity": payload["barrier_lock_identity"],
    }


def _sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "FormalPaperBootstrapError",
    "VerifiedFormalPaperRuntimeBootstrap",
    "bootstrap_fresh_formal_paper_runtime",
    "reopen_verified_formal_paper_runtime",
    "verify_existing_formal_paper_runtime_bootstrap",
]
