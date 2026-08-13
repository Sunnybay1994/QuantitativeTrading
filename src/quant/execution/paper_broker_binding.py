"""Process-local binding of a formal PAPER runtime and execution policy."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, NoReturn, SupportsIndex

from quant.execution.paper_policy import (
    VerifiedPaperExecutionPolicy,
    verify_existing_paper_execution_policy,
)
from quant.execution.paper_runtime import (
    FormalPaperRuntimeConfig,
    VerifiedPaperRuntimeEnvironment,
    verify_existing_paper_runtime_preflight,
)

_SCHEMA_VERSION = "formal-paper-broker-policy-binding-v1"
_CLASSIFICATION: Literal["formal-paper-simulation"] = "formal-paper-simulation"


class FormalPaperBrokerPolicyBindingError(ValueError):
    """Stable, sanitized formal PAPER broker binding failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"FormalPaperBrokerPolicyBindingError({self.code!r})"


@dataclass(frozen=True, slots=True)
class _BindingAttestation:
    token: bytes = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER broker binding is process-local")


@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperBrokerPolicyBinding:
    """Exact process-local proof of one formal runtime and policy binding."""

    schema_version: str
    classification: Literal["formal-paper-simulation"]
    session_date: dt.date
    runtime_environment_identity: str
    runtime_config_identity: str
    execution_policy_identity: str
    adapter_policy_version: str
    fill_policy_version: str
    fault_policy_version: str
    finality_policy_version: str
    clock_policy_version: str
    cost_schedule_identity: str
    fx_snapshot_identity: None
    binding_identity: str
    verified_at: dt.datetime
    _attestation: _BindingAttestation = field(repr=False, compare=False)

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("formal PAPER broker binding is process-local")


class _Failure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _create_binding_api():  # type: ignore[no-untyped-def]
    key = secrets.token_bytes(32)

    def _token(payload: Mapping[str, object]) -> bytes:
        return hmac.new(key, _canonical_json(payload), hashlib.sha256).digest()

    def _verify_token(binding: VerifiedFormalPaperBrokerPolicyBinding) -> bool:
        try:
            if type(binding._attestation) is not _BindingAttestation:
                return False
            token = binding._attestation.token
            if type(token) is not bytes:
                return False
            return hmac.compare_digest(token, _token(_binding_payload(binding)))
        except Exception:
            return False

    def _mint(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        verified_at: dt.datetime,
    ) -> VerifiedFormalPaperBrokerPolicyBinding:
        identity_payload = _identity_payload(
            environment=environment,
            policy=policy,
            verified_at=verified_at,
        )
        result = VerifiedFormalPaperBrokerPolicyBinding(
            schema_version=_SCHEMA_VERSION,
            classification=_CLASSIFICATION,
            session_date=policy.session_date,
            runtime_environment_identity=environment.verification_identity,
            runtime_config_identity=environment.config.config_identity,
            execution_policy_identity=policy.policy_identity,
            adapter_policy_version=policy.adapter_policy_version,
            fill_policy_version=policy.fill_policy_version,
            fault_policy_version=policy.fault_policy_version,
            finality_policy_version=policy.finality_policy_version,
            clock_policy_version=policy.clock_policy_version,
            cost_schedule_identity=policy.cost_schedule_identity,
            fx_snapshot_identity=policy.fx_snapshot_identity,
            binding_identity=_sha256(identity_payload),
            verified_at=verified_at,
            _attestation=_BindingAttestation(b""),
        )
        object.__setattr__(
            result,
            "_attestation",
            _BindingAttestation(_token(_binding_payload(result))),
        )
        if not _verify_token(result):
            raise _Failure("PAPER_BROKER_BINDING_INVALID")
        return result

    def bind_verified_formal_paper_broker_policy(
        *,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        now: dt.datetime,
    ) -> VerifiedFormalPaperBrokerPolicyBinding:
        """Fresh-check and bind the exact formal runtime and policy capabilities."""
        failure: str | None = None
        result: VerifiedFormalPaperBrokerPolicyBinding | None = None
        try:
            timestamp = _require_public_inputs(environment, policy, now)
            _fresh_environment(environment, timestamp)
            fresh_policy = _fresh_policy(policy, environment, timestamp)
            _require_not_early(timestamp, environment, fresh_policy)
            result = _mint(
                environment=environment,
                policy=fresh_policy,
                verified_at=timestamp,
            )
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_BROKER_BINDING_INVALID"
        if failure is not None or result is None:
            raise FormalPaperBrokerPolicyBindingError(
                failure or "PAPER_BROKER_BINDING_INVALID"
            ) from None
        return result

    def verify_existing_formal_paper_broker_policy_binding(
        *,
        binding: VerifiedFormalPaperBrokerPolicyBinding,
        environment: VerifiedPaperRuntimeEnvironment,
        policy: VerifiedPaperExecutionPolicy,
        now: dt.datetime,
    ) -> VerifiedFormalPaperBrokerPolicyBinding:
        """Fresh-check and exact-compare an existing formal broker binding."""
        failure: str | None = None
        result: VerifiedFormalPaperBrokerPolicyBinding | None = None
        try:
            if (
                type(binding) is not VerifiedFormalPaperBrokerPolicyBinding
                or not _verify_token(binding)
            ):
                raise _Failure("PAPER_BROKER_BINDING_INVALID")
            timestamp = _require_public_inputs(environment, policy, now)
            _require_utc(binding.verified_at)
            if timestamp < binding.verified_at:
                raise _Failure("PAPER_BROKER_BINDING_STALE")
            try:
                _fresh_environment(environment, timestamp)
                fresh_policy = _fresh_policy(policy, environment, timestamp)
                _require_not_early(timestamp, environment, fresh_policy)
                rebuilt = _mint(
                    environment=environment,
                    policy=fresh_policy,
                    verified_at=binding.verified_at,
                )
            except _Failure:
                raise _Failure("PAPER_BROKER_BINDING_STALE") from None
            if rebuilt != binding:
                raise _Failure("PAPER_BROKER_BINDING_STALE")
            result = binding
        except _Failure as exc:
            failure = exc.code
        except Exception:
            failure = "PAPER_BROKER_BINDING_INVALID"
        if failure is not None or result is None:
            raise FormalPaperBrokerPolicyBindingError(
                failure or "PAPER_BROKER_BINDING_INVALID"
            ) from None
        return result

    return (
        bind_verified_formal_paper_broker_policy,
        verify_existing_formal_paper_broker_policy_binding,
    )


(
    bind_verified_formal_paper_broker_policy,
    verify_existing_formal_paper_broker_policy_binding,
) = _create_binding_api()
del _create_binding_api


def _require_public_inputs(
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    now: dt.datetime,
) -> dt.datetime:
    if type(environment) is not VerifiedPaperRuntimeEnvironment:
        raise _Failure("PAPER_BROKER_BINDING_ENVIRONMENT_INVALID")
    if type(policy) is not VerifiedPaperExecutionPolicy:
        raise _Failure("PAPER_BROKER_BINDING_POLICY_INVALID")
    return _require_utc(now)


def _require_utc(value: dt.datetime) -> dt.datetime:
    try:
        if (
            type(value) is not dt.datetime
            or value.tzinfo is None
            or value.utcoffset() != dt.timedelta(0)
        ):
            raise ValueError
    except Exception:
        raise _Failure("PAPER_BROKER_BINDING_STALE") from None
    return value


def _fresh_environment(
    environment: VerifiedPaperRuntimeEnvironment,
    now: dt.datetime,
) -> VerifiedPaperRuntimeEnvironment:
    try:
        if type(environment.config) is not FormalPaperRuntimeConfig:
            raise ValueError
        verify_existing_paper_runtime_preflight(
            environment,
            config_path=environment.config.source_path,
            now=now,
        )
    except Exception:
        raise _Failure("PAPER_BROKER_BINDING_ENVIRONMENT_INVALID") from None
    return environment


def _fresh_policy(
    policy: VerifiedPaperExecutionPolicy,
    environment: VerifiedPaperRuntimeEnvironment,
    now: dt.datetime,
) -> VerifiedPaperExecutionPolicy:
    try:
        fresh = verify_existing_paper_execution_policy(
            policy=policy,
            environment=environment,
            now=now,
        )
        if type(fresh) is not VerifiedPaperExecutionPolicy or fresh != policy:
            raise ValueError
    except Exception:
        raise _Failure("PAPER_BROKER_BINDING_POLICY_INVALID") from None
    return fresh


def _require_not_early(
    now: dt.datetime,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
) -> None:
    try:
        environment_time = _require_utc(environment.verified_at)
        policy_time = _require_utc(policy.verified_at)
    except _Failure:
        raise _Failure("PAPER_BROKER_BINDING_STALE") from None
    if now < environment_time or now < policy_time:
        raise _Failure("PAPER_BROKER_BINDING_STALE")


def _identity_payload(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    verified_at: dt.datetime,
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "classification": _CLASSIFICATION,
        "session_date": policy.session_date.isoformat(),
        "runtime_environment_identity": environment.verification_identity,
        "runtime_config_identity": environment.config.config_identity,
        "execution_policy_identity": policy.policy_identity,
        "adapter_policy_version": policy.adapter_policy_version,
        "fill_policy_version": policy.fill_policy_version,
        "fault_policy_version": policy.fault_policy_version,
        "finality_policy_version": policy.finality_policy_version,
        "clock_policy_version": policy.clock_policy_version,
        "cost_schedule_identity": policy.cost_schedule_identity,
        "fx_snapshot_identity": policy.fx_snapshot_identity,
        "verified_at": verified_at.isoformat(timespec="microseconds"),
    }


def _binding_payload(
    binding: VerifiedFormalPaperBrokerPolicyBinding,
) -> dict[str, object]:
    return {
        "schema_version": binding.schema_version,
        "classification": binding.classification,
        "session_date": binding.session_date.isoformat(),
        "runtime_environment_identity": binding.runtime_environment_identity,
        "runtime_config_identity": binding.runtime_config_identity,
        "execution_policy_identity": binding.execution_policy_identity,
        "adapter_policy_version": binding.adapter_policy_version,
        "fill_policy_version": binding.fill_policy_version,
        "fault_policy_version": binding.fault_policy_version,
        "finality_policy_version": binding.finality_policy_version,
        "clock_policy_version": binding.clock_policy_version,
        "cost_schedule_identity": binding.cost_schedule_identity,
        "fx_snapshot_identity": binding.fx_snapshot_identity,
        "binding_identity": binding.binding_identity,
        "verified_at": binding.verified_at.isoformat(timespec="microseconds"),
    }


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


__all__ = [
    "FormalPaperBrokerPolicyBindingError",
    "VerifiedFormalPaperBrokerPolicyBinding",
    "bind_verified_formal_paper_broker_policy",
    "verify_existing_formal_paper_broker_policy_binding",
]
