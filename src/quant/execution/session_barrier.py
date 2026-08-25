"""Shared session-close barrier substrate (OMS SSOT, anchored lock, write lease).

B1B1 adds process-local closure capability issuance on OPEN→CLOSING only.
Closure has no write/transaction interface and must not drive CLOSING→CLOSED.
UA-M4-006 remains OPEN.
"""

from __future__ import annotations

import datetime as dt
import errno
import hashlib
import hmac
import os
import secrets
import sqlite3
import stat
import sys
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal, NoReturn, SupportsIndex, TypeVar, cast
from weakref import WeakKeyDictionary, WeakValueDictionary

from quant.domain.canonical_wire import canonical_json_bytes, utc_datetime_text

BarrierState = Literal["OPEN", "CLOSING", "CLOSED"]
TerminalTransitionPolicy = Literal["SUBSTRATE_RAW_TOKEN", "FORMAL_CLOSURE_ONLY"]
_TERMINAL_POLICIES: Final[frozenset[str]] = frozenset(
    {"SUBSTRATE_RAW_TOKEN", "FORMAL_CLOSURE_ONLY"}
)
_FORMAL_ROW_POLICY_DOMAIN: Final[str] = "m4-formal-closure-only-row-v1"

_BARRIER_SCHEMA: Final[str] = "m4-session-barrier-v1"
_LOCK_NAME: Final[str] = ".session-barrier.lock"
_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")
_REPARSE: Final[int] = 0x400
_CAPABILITY_DOMAIN: Final[bytes] = b"m4-session-barrier-capability-v1\x00"
_OMS_HANDLE_DOMAIN: Final[bytes] = b"m4-session-barrier-oms-handle-v1\x00"
_LEASE_DOMAIN: Final[bytes] = b"m4-session-barrier-lease-v1\x00"
_TOKEN_DOMAIN: Final[bytes] = b"m4-session-barrier-close-token-v1\x00"
_CLOSURE_DOMAIN: Final[bytes] = b"m4-session-barrier-closure-v1\x00"
_OPERATION_PERMIT_DOMAIN: Final[bytes] = b"m4-session-barrier-operation-permit-v1\x00"
_PROCESS_PROOF_KEY: Final[bytes] = secrets.token_bytes(32)
_Identity = tuple[int, int]
_REGISTRY_LOCK = threading.Lock()
# Platform concrete Path only (WindowsPath / PosixPath); never bare Path or Pure*.
_CONCRETE_PATH_TYPE: Final[type[Path]] = type(Path())
_ACTIVE_OPERATION_PERMIT: ContextVar[SessionBarrierOperationPermit | None] = ContextVar(
    "session_barrier_active_operation_permit",
    default=None,
)


@dataclass(frozen=True, slots=True)
class _CapabilityBinding:
    seal: bytes
    proof: bytes


@dataclass(frozen=True, slots=True)
class _OmsHandleBinding:
    seal: bytes
    proof: bytes
    conn: sqlite3.Connection
    alive: bool


@dataclass(frozen=True, slots=True)
class _LeaseBinding:
    seal: bytes
    proof: bytes
    alive: bool


@dataclass(slots=True)
class _OperationPermitBinding:
    seal: bytes
    proof: bytes
    alive: bool
    lock_object: object
    oms_handle: SessionBarrierOmsHandle
    active_child: SessionBarrierWriteLease | None = None


@dataclass(frozen=True, slots=True)
class _ClosureBinding:
    seal: bytes
    proof: bytes
    lock_object: object
    mint_generation: int


# Exact minted object identity → process-local binding (no public escape hatch).
# Keys must be identity-hashed (dataclasses use eq=False); structural clones must
# not retrieve, pop, or invalidate a genuine referent via WeakKeyDictionary.
_CAPABILITY_BINDINGS: WeakKeyDictionary[SessionBarrierCapability, _CapabilityBinding] = (
    WeakKeyDictionary()
)
_OMS_HANDLE_BINDINGS: WeakKeyDictionary[SessionBarrierOmsHandle, _OmsHandleBinding] = (
    WeakKeyDictionary()
)
_LEASE_BINDINGS: WeakKeyDictionary[SessionBarrierWriteLease, _LeaseBinding] = (
    WeakKeyDictionary()
)
_OPERATION_PERMIT_BINDINGS: WeakKeyDictionary[
    SessionBarrierOperationPermit, _OperationPermitBinding
] = WeakKeyDictionary()
_CLOSURE_BINDINGS: WeakKeyDictionary[
    SessionBarrierClosureCapability, _ClosureBinding
] = WeakKeyDictionary()
# (barrier_capability_identity, close_token_identity) → live closure object.
_CLOSURE_BY_TOKEN: WeakValueDictionary[
    tuple[str, str], SessionBarrierClosureCapability
] = WeakValueDictionary()
# barrier_capability_identity → mint count (exact recover remint allowed once).
_CLOSURE_MINT_COUNT: dict[str, int] = {}


class SessionBarrierError(ValueError):
    """Stable, sanitized session-barrier failure; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"SessionBarrierError({self.code!r})"

    @property
    def __context__(self) -> None:
        return None

    @__context__.setter
    def __context__(self, value: BaseException | None) -> None:
        del value


@dataclass(frozen=True, slots=True)
class SessionBarrierRow:
    """Canonical durable barrier snapshot (OMS SSOT)."""

    barrier_schema: str
    barrier_epoch: str
    session_date: str
    account_identity: str
    oms_store_identity: str
    broker_store_identity: str
    gateway_identity: str
    config_identity: str
    lock_identity: str
    state: BarrierState
    close_token_identity: str | None
    created_at: str
    transitioned_at: str
    row_identity: str


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True, init=False)
class SessionBarrierCapability:
    """Process-local barrier binding; cannot be Protocol/dataclass forged.

    ``eq=False`` keeps object-identity hash/eq so WeakKeyDictionary keys cannot
    be retrieved or popped by a structurally equal ``object.__new__`` clone.
    """

    barrier_epoch: str
    session_date: str
    account_identity: str
    oms_store_identity: str
    broker_store_identity: str
    gateway_identity: str
    config_identity: str
    terminal_policy: TerminalTransitionPolicy
    lock_root: Path = field(repr=False, compare=False)
    capability_identity: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SessionBarrierError("BARRIER_CAPABILITY_INVALID") from None

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("session barrier capability is process-local")

    def __copy__(self) -> NoReturn:
        raise TypeError("session barrier capability is process-local")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("session barrier capability is process-local")

    def __replace__(self, **changes: object) -> NoReturn:
        del changes
        raise TypeError("session barrier capability is process-local")


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True, init=False)
class SessionBarrierWriteLease:
    """Exact process-local OPEN write lease; one transaction, one store.

    Identity-keyed (``eq=False``) for the module-private lease registry.
    """

    capability_identity: str
    barrier_epoch: str
    session_date: str
    state: Literal["OPEN"]
    lock_identity: str
    store_kind: Literal["oms", "broker"]
    transaction_nonce: str
    owner_pid: int
    owner_thread_id: int

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SessionBarrierError("BARRIER_LEASE_INVALID") from None

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("session barrier lease is process-local")

    def __copy__(self) -> NoReturn:
        raise TypeError("session barrier lease is process-local")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("session barrier lease is process-local")

    def __replace__(self, **changes: object) -> NoReturn:
        del changes
        raise TypeError("session barrier lease is process-local")


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True, init=False)
class SessionBarrierOperationPermit:
    """Process-local OPEN operation fence; holds one anchored OS lock.

    Identity-keyed (``eq=False``) for the module-private permit registry.
    Child write leases may nest under the permit without re-acquiring the lock.
    """

    capability_identity: str
    handle_identity: str
    lock_identity: str
    owner_pid: int
    owner_thread_id: int

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID") from None

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("session barrier operation permit is process-local")

    def __copy__(self) -> NoReturn:
        raise TypeError("session barrier operation permit is process-local")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("session barrier operation permit is process-local")

    def __replace__(self, **changes: object) -> NoReturn:
        del changes
        raise TypeError("session barrier operation permit is process-local")


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True, init=False)
class SessionBarrierOmsHandle:
    """Process-local OMS barrier reader; connection stays module-private.

    Identity-keyed (``eq=False``) so clones cannot fetch the private connection.
    """

    capability_identity: str
    handle_identity: str

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID") from None

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("session barrier OMS handle is process-local")

    def __copy__(self) -> NoReturn:
        raise TypeError("session barrier OMS handle is process-local")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("session barrier OMS handle is process-local")

    def __replace__(self, **changes: object) -> NoReturn:
        del changes
        raise TypeError("session barrier OMS handle is process-local")


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True, init=False)
class SessionBarrierClosureCapability:
    """Process-local OPEN→CLOSING closure proof; issue-only in B1B1 (no writes).

    Bound to close-token identity, barrier identities, lock object and CLOSING
    row. Direct construction, copy/pickle/replace, and raw tokens cannot mint
    trust. Has no transaction or terminal-write interface.
    """

    capability_identity: str
    barrier_epoch: str
    session_date: str
    account_identity: str
    oms_store_identity: str
    broker_store_identity: str
    gateway_identity: str
    config_identity: str
    close_token_identity: str
    closing_row_identity: str
    lock_identity: str
    closure_identity: str
    lock_root: Path = field(repr=False, compare=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SessionBarrierError("BARRIER_CLOSURE_INVALID") from None

    def __repr__(self) -> str:
        return (
            "SessionBarrierClosureCapability("
            f"closure_identity={self.closure_identity!r})"
        )

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("session barrier closure is process-local")

    def __copy__(self) -> NoReturn:
        raise TypeError("session barrier closure is process-local")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("session barrier closure is process-local")

    def __replace__(self, **changes: object) -> NoReturn:
        del changes
        raise TypeError("session barrier closure is process-local")


@dataclass(slots=True)
class _HeldBarrierLock:
    """Mutable held-lock handles; fds cleared to -1 after release."""

    lock_fd: int
    dir_fd: int
    root: Path
    lock_path: Path
    root_identity: _Identity
    ancestor_identities: dict[Path, _Identity]
    lock_identity_raw: _Identity
    lock_identity: str


def build_session_barrier_capability(
    *,
    barrier_epoch: str,
    session_date: dt.date | str,
    account_identity: str,
    oms_store_identity: str,
    broker_store_identity: str,
    gateway_identity: str,
    config_identity: str,
    lock_root: Path,
    terminal_policy: TerminalTransitionPolicy = "SUBSTRATE_RAW_TOKEN",
) -> SessionBarrierCapability:
    """Mint one process-local capability bound to barrier identities and lock root."""
    try:
        epoch = _hex64(barrier_epoch)
        session = _session_date_text(session_date)
        account = _hex64(account_identity)
        oms = _hex64(oms_store_identity)
        broker = _hex64(broker_store_identity)
        gateway = _hex64(gateway_identity)
        config = _hex64(config_identity)
        policy = _require_terminal_policy(terminal_policy)
        root = _require_absolute_path(lock_root)
        identity = _compute_capability_identity(
            barrier_epoch=epoch,
            session_date=session,
            account_identity=account,
            oms_store_identity=oms,
            broker_store_identity=broker,
            gateway_identity=gateway,
            config_identity=config,
            lock_root=root,
            terminal_policy=policy,
        )
        seal = secrets.token_bytes(32)
        proof = _capability_proof(
            barrier_epoch=epoch,
            session_date=session,
            account_identity=account,
            oms_store_identity=oms,
            broker_store_identity=broker,
            gateway_identity=gateway,
            config_identity=config,
            lock_root=root,
            terminal_policy=policy,
            capability_identity=identity,
            seal=seal,
        )
        capability = object.__new__(SessionBarrierCapability)
        object.__setattr__(capability, "barrier_epoch", epoch)
        object.__setattr__(capability, "session_date", session)
        object.__setattr__(capability, "account_identity", account)
        object.__setattr__(capability, "oms_store_identity", oms)
        object.__setattr__(capability, "broker_store_identity", broker)
        object.__setattr__(capability, "gateway_identity", gateway)
        object.__setattr__(capability, "config_identity", config)
        object.__setattr__(capability, "terminal_policy", policy)
        object.__setattr__(capability, "lock_root", root)
        object.__setattr__(capability, "capability_identity", identity)
        with _REGISTRY_LOCK:
            _CAPABILITY_BINDINGS[capability] = _CapabilityBinding(seal=seal, proof=proof)
        return capability
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_CAPABILITY_INVALID") from None


def unpack_session_barrier_capability(value: object) -> SessionBarrierCapability:
    """Validate one in-process capability; recompute identity from every field."""
    if type(value) is not SessionBarrierCapability:
        raise SessionBarrierError("BARRIER_CAPABILITY_INVALID") from None
    try:
        with _REGISTRY_LOCK:
            binding = _CAPABILITY_BINDINGS.get(value)
        if binding is None:
            raise SessionBarrierError("BARRIER_CAPABILITY_INVALID")
        for field_name in (
            "barrier_epoch",
            "session_date",
            "account_identity",
            "oms_store_identity",
            "broker_store_identity",
            "gateway_identity",
            "config_identity",
            "capability_identity",
        ):
            item = getattr(value, field_name)
            if type(item) is not str:
                raise SessionBarrierError("BARRIER_CAPABILITY_INVALID")
        policy = _require_terminal_policy(value.terminal_policy)
        if (
            type(value.lock_root) is not _CONCRETE_PATH_TYPE
            or not value.lock_root.is_absolute()
        ):
            raise SessionBarrierError("BARRIER_CAPABILITY_INVALID")
        expected_identity = _compute_capability_identity(
            barrier_epoch=value.barrier_epoch,
            session_date=value.session_date,
            account_identity=value.account_identity,
            oms_store_identity=value.oms_store_identity,
            broker_store_identity=value.broker_store_identity,
            gateway_identity=value.gateway_identity,
            config_identity=value.config_identity,
            lock_root=value.lock_root,
            terminal_policy=policy,
        )
        if not hmac.compare_digest(value.capability_identity, expected_identity):
            raise SessionBarrierError("BARRIER_CAPABILITY_INVALID")
        expected_proof = _capability_proof(
            barrier_epoch=value.barrier_epoch,
            session_date=value.session_date,
            account_identity=value.account_identity,
            oms_store_identity=value.oms_store_identity,
            broker_store_identity=value.broker_store_identity,
            gateway_identity=value.gateway_identity,
            config_identity=value.config_identity,
            lock_root=value.lock_root,
            terminal_policy=policy,
            capability_identity=expected_identity,
            seal=binding.seal,
        )
        if not hmac.compare_digest(binding.proof, expected_proof):
            raise SessionBarrierError("BARRIER_CAPABILITY_INVALID")
        return value
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_CAPABILITY_INVALID") from None


def issue_session_barrier_oms_handle(
    *,
    capability: object,
    conn: sqlite3.Connection,
) -> SessionBarrierOmsHandle:
    """Mint a process-local OMS handle; connection stays in the module registry."""
    cap = unpack_session_barrier_capability(capability)
    if type(conn) is not sqlite3.Connection:
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID") from None
    try:
        seal = secrets.token_bytes(32)
        handle_identity = _digest(
            {
                "capability_identity": cap.capability_identity,
                "seal": seal.hex(),
                "type": "session-barrier-oms-handle-v1",
            }
        )
        proof = _oms_handle_proof(
            capability_identity=cap.capability_identity,
            handle_identity=handle_identity,
            seal=seal,
        )
        handle = object.__new__(SessionBarrierOmsHandle)
        object.__setattr__(handle, "capability_identity", cap.capability_identity)
        object.__setattr__(handle, "handle_identity", handle_identity)
        with _REGISTRY_LOCK:
            _OMS_HANDLE_BINDINGS[handle] = _OmsHandleBinding(
                seal=seal, proof=proof, conn=conn, alive=True
            )
        return handle
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID") from None


def unpack_session_barrier_oms_handle(
    value: object,
    *,
    capability: object,
) -> SessionBarrierOmsHandle:
    """Validate one live OMS handle against the exact barrier capability."""
    cap = unpack_session_barrier_capability(capability)
    if type(value) is not SessionBarrierOmsHandle:
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID") from None
    handle = cast(SessionBarrierOmsHandle, value)
    try:
        with _REGISTRY_LOCK:
            binding = _OMS_HANDLE_BINDINGS.get(handle)
        if binding is None:
            raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")
        if binding.alive is not True:
            raise SessionBarrierError("BARRIER_OMS_HANDLE_EXPIRED")
        if handle.capability_identity != cap.capability_identity:
            raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")
        if type(handle.handle_identity) is not str:
            raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")
        expected_identity = _digest(
            {
                "capability_identity": cap.capability_identity,
                "seal": binding.seal.hex(),
                "type": "session-barrier-oms-handle-v1",
            }
        )
        if not hmac.compare_digest(handle.handle_identity, expected_identity):
            raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")
        expected = _oms_handle_proof(
            capability_identity=cap.capability_identity,
            handle_identity=handle.handle_identity,
            seal=binding.seal,
        )
        if not hmac.compare_digest(binding.proof, expected):
            raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")
        if type(binding.conn) is not sqlite3.Connection:
            raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID")
        return handle
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID") from None


def invalidate_session_barrier_oms_handle(handle: object) -> None:
    """Drop the module-private OMS binding when its owning store closes."""
    if type(handle) is not SessionBarrierOmsHandle:
        return
    with _REGISTRY_LOCK:
        _OMS_HANDLE_BINDINGS.pop(handle, None)


def fresh_read_session_barrier(
    *,
    oms_handle: object,
    capability: object,
) -> SessionBarrierRow:
    """Fresh-read the OMS barrier row through a verified handle (no connection escape)."""
    handle = unpack_session_barrier_oms_handle(oms_handle, capability=capability)
    return read_session_barrier(_oms_connection(handle))


def require_matching_barrier_handle(
    *,
    oms_handle: object,
    capability: object,
) -> SessionBarrierRow:
    """Require exact identity match via OMS handle."""
    cap = unpack_session_barrier_capability(capability)
    row = fresh_read_session_barrier(oms_handle=oms_handle, capability=cap)
    _require_identity_match(row, cap)
    return row


def compute_close_token_identity(
    *,
    capability: object,
    predecessor_state: BarrierState,
    nonce: str,
) -> str:
    """Derive durable close-token identity from barrier binding + nonce (no secret)."""
    cap = unpack_session_barrier_capability(capability)
    if predecessor_state not in {"OPEN", "CLOSING", "CLOSED"}:
        raise SessionBarrierError("BARRIER_TOKEN_INVALID")
    challenge = _require_nonce(nonce)
    return _digest(
        {
            "account_identity": cap.account_identity,
            "barrier_epoch": cap.barrier_epoch,
            "barrier_schema": _BARRIER_SCHEMA,
            "broker_store_identity": cap.broker_store_identity,
            "config_identity": cap.config_identity,
            "domain": _TOKEN_DOMAIN.decode("ascii"),
            "gateway_identity": cap.gateway_identity,
            "nonce": challenge,
            "oms_store_identity": cap.oms_store_identity,
            "predecessor_state": predecessor_state,
            "session_date": cap.session_date,
        }
    )


def initialize_open_barrier(
    conn: sqlite3.Connection,
    capability: object,
    *,
    created_at: dt.datetime,
) -> SessionBarrierRow:
    """Insert the unique OPEN row for a new barrier root.

    Order: anchored OS lock → BEGIN IMMEDIATE → work → COMMIT/ROLLBACK → unlock.
    Always refuses adoption/backfill when any economic OMS rows already exist.
    """
    cap = unpack_session_barrier_capability(capability)
    created = _utc_text(created_at)

    def _work(held: _HeldBarrierLock) -> SessionBarrierRow:
        if _oms_has_economic_rows(conn):
            raise SessionBarrierError("BARRIER_OLD_ROOT_REFUSED") from None
        existing = _load_barrier_rows(conn)
        if len(existing) > 1:
            raise SessionBarrierError("BARRIER_ROW_CORRUPT") from None
        if len(existing) == 1:
            raise SessionBarrierError("BARRIER_ALREADY_INITIALIZED") from None
        row = _build_open_row(cap, lock_identity=held.lock_identity, created_at=created)
        try:
            _insert_barrier_row(conn, row)
        except sqlite3.Error:
            raise SessionBarrierError("BARRIER_WRITE_FAILED") from None
        loaded = read_session_barrier(conn)
        if loaded != row:
            raise SessionBarrierError("BARRIER_ROW_CORRUPT") from None
        return loaded

    return _run_under_barrier_lock_transaction(cap, conn, _work)


def read_session_barrier(conn: sqlite3.Connection) -> SessionBarrierRow:
    """Fresh-read the unique barrier row; fail closed on missing/extra/corrupt."""
    rows = _load_barrier_rows(conn)
    if not rows:
        raise SessionBarrierError("BARRIER_MISSING") from None
    if len(rows) > 1:
        raise SessionBarrierError("BARRIER_ROW_CORRUPT") from None
    return _parse_barrier_row(rows[0])


def require_matching_barrier(
    conn: sqlite3.Connection,
    capability: object,
) -> SessionBarrierRow:
    """Read and require exact identity match with the capability (state free)."""
    cap = unpack_session_barrier_capability(capability)
    row = read_session_barrier(conn)
    _require_identity_match(row, cap)
    return row


def transition_open_to_closing(
    conn: sqlite3.Connection,
    capability: object,
    *,
    nonce: str,
    now: dt.datetime,
) -> tuple[SessionBarrierRow, str, SessionBarrierClosureCapability]:
    """OPEN → CLOSING with idempotent exact-token replay and closure issuance.

    Order: anchored OS lock → BEGIN IMMEDIATE → work → COMMIT/ROLLBACK → unlock.
    Issues (or recovers) one process-local closure capability; B1B1 does not
    consume it for terminal writes or CLOSING→CLOSED.
    """
    cap = unpack_session_barrier_capability(capability)
    token = compute_close_token_identity(
        capability=cap, predecessor_state="OPEN", nonce=nonce
    )
    transitioned = _utc_text(now)
    minted: list[SessionBarrierClosureCapability] = []

    def _work(held: _HeldBarrierLock) -> tuple[SessionBarrierRow, str, SessionBarrierClosureCapability]:
        current = read_session_barrier(conn)
        _require_identity_match(current, cap)
        if current.lock_identity != held.lock_identity:
            raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
        if current.state == "CLOSING":
            if current.close_token_identity == token:
                closure = _issue_or_recover_closure(
                    cap,
                    row=current,
                    close_token_identity=token,
                    lock_object=held,
                    allow_fresh_mint=False,
                )
                return current, token, closure
            raise SessionBarrierError("BARRIER_TOKEN_CONFLICT") from None
        if current.state != "OPEN":
            raise SessionBarrierError("BARRIER_TRANSITION_INVALID") from None
        updated = replace(
            current,
            state="CLOSING",
            close_token_identity=token,
            transitioned_at=transitioned,
            row_identity=_row_identity_for(
                current,
                state="CLOSING",
                close_token_identity=token,
                transitioned_at=transitioned,
                terminal_policy=cap.terminal_policy,
            ),
        )
        _replace_barrier_row(conn, previous=current, updated=updated)
        loaded = read_session_barrier(conn)
        closure = _issue_or_recover_closure(
            cap,
            row=loaded,
            close_token_identity=token,
            lock_object=held,
            allow_fresh_mint=True,
        )
        minted.append(closure)
        return loaded, token, closure

    try:
        return _run_under_barrier_lock_transaction(cap, conn, _work)
    except BaseException:
        for item in minted:
            _invalidate_closure_capability(item)
        raise


def unpack_session_barrier_closure_capability(
    value: object,
    *,
    capability: object,
) -> SessionBarrierClosureCapability:
    """Validate one live closure capability against the barrier capability."""
    cap = unpack_session_barrier_capability(capability)
    if type(value) is not SessionBarrierClosureCapability:
        raise SessionBarrierError("BARRIER_CLOSURE_INVALID") from None
    closure = cast(SessionBarrierClosureCapability, value)
    try:
        with _REGISTRY_LOCK:
            binding = _CLOSURE_BINDINGS.get(closure)
        if binding is None:
            raise SessionBarrierError("BARRIER_CLOSURE_INVALID")
        for field_name in (
            "capability_identity",
            "barrier_epoch",
            "session_date",
            "account_identity",
            "oms_store_identity",
            "broker_store_identity",
            "gateway_identity",
            "config_identity",
            "close_token_identity",
            "closing_row_identity",
            "lock_identity",
            "closure_identity",
        ):
            item = getattr(closure, field_name)
            if type(item) is not str:
                raise SessionBarrierError("BARRIER_CLOSURE_INVALID")
        if (
            type(closure.lock_root) is not _CONCRETE_PATH_TYPE
            or not closure.lock_root.is_absolute()
        ):
            raise SessionBarrierError("BARRIER_CLOSURE_INVALID")
        if closure.capability_identity != cap.capability_identity:
            raise SessionBarrierError("BARRIER_CLOSURE_INVALID")
        if (
            closure.barrier_epoch != cap.barrier_epoch
            or closure.session_date != cap.session_date
            or closure.account_identity != cap.account_identity
            or closure.oms_store_identity != cap.oms_store_identity
            or closure.broker_store_identity != cap.broker_store_identity
            or closure.gateway_identity != cap.gateway_identity
            or closure.config_identity != cap.config_identity
            or closure.lock_root != cap.lock_root
        ):
            raise SessionBarrierError("BARRIER_CLOSURE_INVALID")
        expected_identity = _closure_identity_for(
            cap,
            close_token_identity=closure.close_token_identity,
            closing_row_identity=closure.closing_row_identity,
            lock_identity=closure.lock_identity,
        )
        if not hmac.compare_digest(closure.closure_identity, expected_identity):
            raise SessionBarrierError("BARRIER_CLOSURE_INVALID")
        expected_proof = _closure_proof(
            closure,
            seal=binding.seal,
            lock_object=binding.lock_object,
            terminal_policy=cap.terminal_policy,
        )
        if not hmac.compare_digest(binding.proof, expected_proof):
            raise SessionBarrierError("BARRIER_CLOSURE_INVALID")
        return closure
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_CLOSURE_INVALID") from None


def recover_session_barrier_closure_capability(
    *,
    capability: object,
    oms_handle: object,
    close_token_identity: str,
) -> SessionBarrierClosureCapability:
    """Recover the exact-token CLOSING closure after fresh row verify (no write)."""
    cap = unpack_session_barrier_capability(capability)
    handle = unpack_session_barrier_oms_handle(oms_handle, capability=cap)
    token = _hex64(close_token_identity)
    row = fresh_read_session_barrier(oms_handle=handle, capability=cap)
    _require_identity_match(row, cap)
    if row.state != "CLOSING":
        raise SessionBarrierError("BARRIER_TRANSITION_INVALID") from None
    if row.close_token_identity != token:
        raise SessionBarrierError("BARRIER_TOKEN_CONFLICT") from None
    key = (cap.capability_identity, token)
    with _REGISTRY_LOCK:
        existing = _CLOSURE_BY_TOKEN.get(key)
    if existing is not None:
        return unpack_session_barrier_closure_capability(existing, capability=cap)
    # Remint only under the anchored lock so lock_object identity is real.
    with hold_session_barrier_lock(cap) as held:
        row = fresh_read_session_barrier(oms_handle=handle, capability=cap)
        _require_identity_match(row, cap)
        if row.lock_identity != held.lock_identity:
            raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
        if row.state != "CLOSING" or row.close_token_identity != token:
            raise SessionBarrierError("BARRIER_TOKEN_CONFLICT") from None
        return _issue_or_recover_closure(
            cap,
            row=row,
            close_token_identity=token,
            lock_object=held,
            allow_fresh_mint=False,
        )


def transition_closing_to_closed(
    conn: sqlite3.Connection,
    capability: object,
    *,
    close_token_identity: str,
    now: dt.datetime,
) -> SessionBarrierRow:
    """CLOSING → CLOSED; exact token replay is idempotent.

    Order: anchored OS lock → BEGIN IMMEDIATE → work → COMMIT/ROLLBACK → unlock.
    ``FORMAL_CLOSURE_ONLY`` capabilities must not use this raw-token path.
    """
    cap = unpack_session_barrier_capability(capability)
    if cap.terminal_policy == "FORMAL_CLOSURE_ONLY":
        raise SessionBarrierError("BARRIER_CLOSURE_REQUIRED") from None
    token = _hex64(close_token_identity)
    transitioned = _utc_text(now)

    def _work(held: _HeldBarrierLock) -> SessionBarrierRow:
        current = read_session_barrier(conn)
        _require_identity_match(current, cap)
        if current.lock_identity != held.lock_identity:
            raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
        if current.state == "CLOSED":
            if current.close_token_identity == token:
                return current
            raise SessionBarrierError("BARRIER_TOKEN_CONFLICT") from None
        if current.state != "CLOSING":
            raise SessionBarrierError("BARRIER_TRANSITION_INVALID") from None
        if current.close_token_identity != token:
            raise SessionBarrierError("BARRIER_TOKEN_CONFLICT") from None
        updated = replace(
            current,
            state="CLOSED",
            close_token_identity=token,
            transitioned_at=transitioned,
            row_identity=_row_identity_for(
                current,
                state="CLOSED",
                close_token_identity=token,
                transitioned_at=transitioned,
                terminal_policy=cap.terminal_policy,
            ),
        )
        _replace_barrier_row(conn, previous=current, updated=updated)
        return read_session_barrier(conn)

    return _run_under_barrier_lock_transaction(cap, conn, _work)


_T = TypeVar("_T")


def _run_under_barrier_lock_transaction(
    cap: SessionBarrierCapability,
    conn: sqlite3.Connection,
    work: Callable[[_HeldBarrierLock], _T],
) -> _T:
    """OS lock → BEGIN IMMEDIATE → work → COMMIT/ROLLBACK → unlock (no nested lock)."""
    with hold_session_barrier_lock(cap) as held:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            if getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
                raise SessionBarrierError("BARRIER_WRITER_BUSY") from None
            raise SessionBarrierError("BARRIER_WRITE_FAILED") from None
        try:
            result = work(held)
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        try:
            conn.execute("COMMIT")
        except sqlite3.Error:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise SessionBarrierError("BARRIER_WRITE_FAILED") from None
        return result


@contextmanager
def hold_session_barrier_lock(capability: object) -> Iterator[_HeldBarrierLock]:
    """Hold the anchored exclusive OS lock for one capability root."""
    cap = unpack_session_barrier_capability(capability)
    held = _acquire_barrier_lock(cap.lock_root)
    try:
        yield held
    finally:
        _release_barrier_lock(held)


@contextmanager
def hold_open_operation_permit(
    capability: object,
    *,
    oms_handle: object,
) -> Iterator[SessionBarrierOperationPermit]:
    """Hold one OPEN operation fence under a single anchored OS lock.

    Child ``hold_open_write_lease`` calls reuse the held lock; the permit itself
    does not open an SQLite transaction.
    """
    cap = unpack_session_barrier_capability(capability)
    handle = unpack_session_barrier_oms_handle(oms_handle, capability=cap)
    existing = _ACTIVE_OPERATION_PERMIT.get()
    if existing is not None:
        with _REGISTRY_LOCK:
            existing_binding = _OPERATION_PERMIT_BINDINGS.get(existing)
        if existing_binding is not None and existing_binding.alive is True:
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_NESTED") from None
    with hold_session_barrier_lock(cap) as held:
        row = read_session_barrier(_oms_connection(handle))
        _require_identity_match(row, cap)
        if row.lock_identity != held.lock_identity:
            raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
        if row.state == "CLOSING":
            raise SessionBarrierError("BARRIER_STATE_CLOSING") from None
        if row.state == "CLOSED":
            raise SessionBarrierError("BARRIER_STATE_CLOSED") from None
        if row.state != "OPEN":
            raise SessionBarrierError("BARRIER_STATE_INVALID") from None
        permit = _mint_operation_permit(
            cap,
            handle=handle,
            lock_object=held,
            lock_identity=held.lock_identity,
        )
        token = _ACTIVE_OPERATION_PERMIT.set(permit)
        try:
            yield permit
        finally:
            _invalidate_operation_permit(permit)
            _ACTIVE_OPERATION_PERMIT.reset(token)


@contextmanager
def hold_open_write_lease(
    capability: object,
    *,
    oms_handle: object,
    store_kind: Literal["oms", "broker"],
) -> Iterator[SessionBarrierWriteLease]:
    """Acquire lock (or reuse active operation permit), mint one OPEN write lease."""
    cap = unpack_session_barrier_capability(capability)
    handle = unpack_session_barrier_oms_handle(oms_handle, capability=cap)
    if store_kind not in {"oms", "broker"}:
        raise SessionBarrierError("BARRIER_LEASE_INVALID") from None
    active = _ACTIVE_OPERATION_PERMIT.get()
    if active is not None:
        permit = unpack_session_barrier_operation_permit(
            active, capability=cap, oms_handle=handle
        )
        with _REGISTRY_LOCK:
            binding = _OPERATION_PERMIT_BINDINGS.get(permit)
            if binding is None or binding.alive is not True:
                raise SessionBarrierError("BARRIER_OPERATION_PERMIT_EXPIRED") from None
            if binding.active_child is not None:
                raise SessionBarrierError("BARRIER_OPERATION_CHILD_ACTIVE") from None
            held = binding.lock_object
        if not isinstance(held, _HeldBarrierLock):
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID") from None
        if held.lock_identity != permit.lock_identity:
            raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
        row = read_session_barrier(_oms_connection(handle))
        _require_identity_match(row, cap)
        if row.lock_identity != permit.lock_identity:
            raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
        if row.state == "CLOSING":
            raise SessionBarrierError("BARRIER_STATE_CLOSING") from None
        if row.state == "CLOSED":
            raise SessionBarrierError("BARRIER_STATE_CLOSED") from None
        if row.state != "OPEN":
            raise SessionBarrierError("BARRIER_STATE_INVALID") from None
        lease = _mint_write_lease(
            cap,
            lock_identity=permit.lock_identity,
            store_kind=store_kind,
        )
        with _REGISTRY_LOCK:
            binding = _OPERATION_PERMIT_BINDINGS.get(permit)
            if binding is None or binding.alive is not True:
                invalidate_write_lease(lease)
                raise SessionBarrierError("BARRIER_OPERATION_PERMIT_EXPIRED") from None
            if binding.active_child is not None:
                invalidate_write_lease(lease)
                raise SessionBarrierError("BARRIER_OPERATION_CHILD_ACTIVE") from None
            binding.active_child = lease
        try:
            yield lease
        finally:
            with _REGISTRY_LOCK:
                binding = _OPERATION_PERMIT_BINDINGS.get(permit)
                if binding is not None and binding.active_child is lease:
                    binding.active_child = None
            invalidate_write_lease(lease)
        return
    with hold_session_barrier_lock(cap) as held:
        row = read_session_barrier(_oms_connection(handle))
        _require_identity_match(row, cap)
        if row.lock_identity != held.lock_identity:
            raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
        if row.state == "CLOSING":
            raise SessionBarrierError("BARRIER_STATE_CLOSING") from None
        if row.state == "CLOSED":
            raise SessionBarrierError("BARRIER_STATE_CLOSED") from None
        if row.state != "OPEN":
            raise SessionBarrierError("BARRIER_STATE_INVALID") from None
        lease = _mint_write_lease(
            cap,
            lock_identity=held.lock_identity,
            store_kind=store_kind,
        )
        try:
            yield lease
        finally:
            invalidate_write_lease(lease)


def unpack_session_barrier_operation_permit(
    value: object,
    *,
    capability: object,
    oms_handle: object,
) -> SessionBarrierOperationPermit:
    """Validate one live OPEN operation permit against capability and OMS handle."""
    cap = unpack_session_barrier_capability(capability)
    handle = unpack_session_barrier_oms_handle(oms_handle, capability=cap)
    if type(value) is not SessionBarrierOperationPermit:
        raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID") from None
    permit = cast(SessionBarrierOperationPermit, value)
    try:
        with _REGISTRY_LOCK:
            binding = _OPERATION_PERMIT_BINDINGS.get(permit)
        if binding is None:
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID")
        if binding.alive is not True:
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_EXPIRED")
        if permit.capability_identity != cap.capability_identity:
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID")
        if permit.handle_identity != handle.handle_identity:
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID")
        if binding.oms_handle is not handle:
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID")
        if type(permit.lock_identity) is not str:
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID")
        if (
            permit.owner_pid != os.getpid()
            or permit.owner_thread_id != threading.get_ident()
        ):
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_OWNER_MISMATCH")
        held = binding.lock_object
        if (
            not isinstance(held, _HeldBarrierLock)
            or held.lock_identity != permit.lock_identity
        ):
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID")
        expected = _operation_permit_proof(permit, seal=binding.seal)
        if not hmac.compare_digest(binding.proof, expected):
            raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID")
        return permit
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_OPERATION_PERMIT_INVALID") from None


def unpack_open_write_lease(
    value: object,
    *,
    capability: object,
    store_kind: Literal["oms", "broker"],
) -> SessionBarrierWriteLease:
    """Validate a live OPEN write lease for the exact store kind."""
    cap = unpack_session_barrier_capability(capability)
    if type(value) is not SessionBarrierWriteLease:
        raise SessionBarrierError("BARRIER_LEASE_INVALID") from None
    lease = cast(SessionBarrierWriteLease, value)
    try:
        with _REGISTRY_LOCK:
            binding = _LEASE_BINDINGS.get(lease)
        if binding is None:
            raise SessionBarrierError("BARRIER_LEASE_INVALID")
        if binding.alive is not True:
            raise SessionBarrierError("BARRIER_LEASE_EXPIRED")
        if lease.capability_identity != cap.capability_identity:
            raise SessionBarrierError("BARRIER_LEASE_INVALID")
        if lease.barrier_epoch != cap.barrier_epoch or lease.session_date != cap.session_date:
            raise SessionBarrierError("BARRIER_LEASE_INVALID")
        if lease.state != "OPEN":
            raise SessionBarrierError("BARRIER_LEASE_INVALID")
        if lease.store_kind != store_kind:
            raise SessionBarrierError("BARRIER_LEASE_STORE_MISMATCH")
        if lease.owner_pid != os.getpid() or lease.owner_thread_id != threading.get_ident():
            raise SessionBarrierError("BARRIER_LEASE_OWNER_MISMATCH")
        expected = _lease_proof(lease, seal=binding.seal)
        if not hmac.compare_digest(binding.proof, expected):
            raise SessionBarrierError("BARRIER_LEASE_INVALID")
        return lease
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_LEASE_INVALID") from None


def verify_lease_against_row(
    lease: object,
    *,
    capability: object,
    row: SessionBarrierRow,
    store_kind: Literal["oms", "broker"],
) -> SessionBarrierWriteLease:
    """Re-verify lease under a freshly read barrier row (pre-commit)."""
    live = unpack_open_write_lease(lease, capability=capability, store_kind=store_kind)
    cap = unpack_session_barrier_capability(capability)
    _require_identity_match(row, cap)
    if row.state != "OPEN":
        if row.state == "CLOSING":
            raise SessionBarrierError("BARRIER_STATE_CLOSING") from None
        if row.state == "CLOSED":
            raise SessionBarrierError("BARRIER_STATE_CLOSED") from None
        raise SessionBarrierError("BARRIER_STATE_INVALID") from None
    if row.lock_identity != live.lock_identity:
        raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
    return live


def invalidate_write_lease(lease: object) -> None:
    """Drop the module-private lease binding after leave-context / commit / rollback."""
    if type(lease) is not SessionBarrierWriteLease:
        return
    with _REGISTRY_LOCK:
        _LEASE_BINDINGS.pop(lease, None)


def _oms_connection(handle: SessionBarrierOmsHandle) -> sqlite3.Connection:
    with _REGISTRY_LOCK:
        binding = _OMS_HANDLE_BINDINGS.get(handle)
    if binding is None or binding.alive is not True:
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID") from None
    if type(binding.conn) is not sqlite3.Connection:
        raise SessionBarrierError("BARRIER_OMS_HANDLE_INVALID") from None
    return binding.conn


def _compute_capability_identity(
    *,
    barrier_epoch: str,
    session_date: str,
    account_identity: str,
    oms_store_identity: str,
    broker_store_identity: str,
    gateway_identity: str,
    config_identity: str,
    lock_root: Path,
    terminal_policy: TerminalTransitionPolicy,
) -> str:
    return _digest(
        {
            "account_identity": account_identity,
            "barrier_epoch": barrier_epoch,
            "barrier_schema": _BARRIER_SCHEMA,
            "broker_store_identity": broker_store_identity,
            "config_identity": config_identity,
            "gateway_identity": gateway_identity,
            "lock_root_fingerprint": _lock_root_fingerprint(lock_root),
            "oms_store_identity": oms_store_identity,
            "session_date": session_date,
            "terminal_policy": terminal_policy,
            "type": "session-barrier-capability-v1",
        }
    )


def _capability_proof(
    *,
    barrier_epoch: str,
    session_date: str,
    account_identity: str,
    oms_store_identity: str,
    broker_store_identity: str,
    gateway_identity: str,
    config_identity: str,
    lock_root: Path,
    terminal_policy: TerminalTransitionPolicy,
    capability_identity: str,
    seal: bytes,
) -> bytes:
    return _hmac(
        _CAPABILITY_DOMAIN,
        canonical_json_bytes(
            {
                "account_identity": account_identity,
                "barrier_epoch": barrier_epoch,
                "barrier_schema": _BARRIER_SCHEMA,
                "broker_store_identity": broker_store_identity,
                "capability_identity": capability_identity,
                "config_identity": config_identity,
                "gateway_identity": gateway_identity,
                "lock_root_fingerprint": _lock_root_fingerprint(lock_root),
                "oms_store_identity": oms_store_identity,
                "seal": seal.hex(),
                "session_date": session_date,
                "terminal_policy": terminal_policy,
            }
        ),
    )


def _oms_handle_proof(
    *,
    capability_identity: str,
    handle_identity: str,
    seal: bytes,
) -> bytes:
    return _hmac(
        _OMS_HANDLE_DOMAIN,
        canonical_json_bytes(
            {
                "capability_identity": capability_identity,
                "handle_identity": handle_identity,
                "seal": seal.hex(),
            }
        ),
    )


def _mint_write_lease(
    cap: SessionBarrierCapability,
    *,
    lock_identity: str,
    store_kind: Literal["oms", "broker"],
) -> SessionBarrierWriteLease:
    nonce = secrets.token_hex(32)
    seal = secrets.token_bytes(32)
    lease = object.__new__(SessionBarrierWriteLease)
    object.__setattr__(lease, "capability_identity", cap.capability_identity)
    object.__setattr__(lease, "barrier_epoch", cap.barrier_epoch)
    object.__setattr__(lease, "session_date", cap.session_date)
    object.__setattr__(lease, "state", "OPEN")
    object.__setattr__(lease, "lock_identity", lock_identity)
    object.__setattr__(lease, "store_kind", store_kind)
    object.__setattr__(lease, "transaction_nonce", nonce)
    object.__setattr__(lease, "owner_pid", os.getpid())
    object.__setattr__(lease, "owner_thread_id", threading.get_ident())
    proof = _lease_proof(lease, seal=seal)
    with _REGISTRY_LOCK:
        _LEASE_BINDINGS[lease] = _LeaseBinding(seal=seal, proof=proof, alive=True)
    return lease


def _mint_operation_permit(
    cap: SessionBarrierCapability,
    *,
    handle: SessionBarrierOmsHandle,
    lock_object: object,
    lock_identity: str,
) -> SessionBarrierOperationPermit:
    seal = secrets.token_bytes(32)
    permit = object.__new__(SessionBarrierOperationPermit)
    object.__setattr__(permit, "capability_identity", cap.capability_identity)
    object.__setattr__(permit, "handle_identity", handle.handle_identity)
    object.__setattr__(permit, "lock_identity", lock_identity)
    object.__setattr__(permit, "owner_pid", os.getpid())
    object.__setattr__(permit, "owner_thread_id", threading.get_ident())
    proof = _operation_permit_proof(permit, seal=seal)
    with _REGISTRY_LOCK:
        _OPERATION_PERMIT_BINDINGS[permit] = _OperationPermitBinding(
            seal=seal,
            proof=proof,
            alive=True,
            lock_object=lock_object,
            oms_handle=handle,
            active_child=None,
        )
    return permit


def _invalidate_operation_permit(permit: object) -> None:
    """Drop the permit binding and any active child write lease."""
    if type(permit) is not SessionBarrierOperationPermit:
        return
    with _REGISTRY_LOCK:
        binding = _OPERATION_PERMIT_BINDINGS.pop(permit, None)
        child = None if binding is None else binding.active_child
        if binding is not None:
            binding.alive = False
            binding.active_child = None
    if child is not None:
        invalidate_write_lease(child)


def _operation_permit_proof(
    permit: SessionBarrierOperationPermit, *, seal: bytes
) -> bytes:
    return _hmac(
        _OPERATION_PERMIT_DOMAIN,
        canonical_json_bytes(
            {
                "capability_identity": permit.capability_identity,
                "handle_identity": permit.handle_identity,
                "lock_identity": permit.lock_identity,
                "owner_pid": permit.owner_pid,
                "owner_thread_id": permit.owner_thread_id,
                "seal": seal.hex(),
            }
        ),
    )


def _issue_or_recover_closure(
    cap: SessionBarrierCapability,
    *,
    row: SessionBarrierRow,
    close_token_identity: str,
    lock_object: object,
    allow_fresh_mint: bool,
) -> SessionBarrierClosureCapability:
    if row.state != "CLOSING" or row.close_token_identity != close_token_identity:
        raise SessionBarrierError("BARRIER_CLOSURE_INVALID") from None
    if row.lock_identity != getattr(lock_object, "lock_identity", None):
        raise SessionBarrierError("BARRIER_LOCK_IDENTITY_DRIFT") from None
    key = (cap.capability_identity, close_token_identity)
    with _REGISTRY_LOCK:
        existing = _CLOSURE_BY_TOKEN.get(key)
    if existing is not None:
        return unpack_session_barrier_closure_capability(existing, capability=cap)
    with _REGISTRY_LOCK:
        mint_count = _CLOSURE_MINT_COUNT.get(cap.capability_identity, 0)
        if allow_fresh_mint:
            if mint_count >= 1:
                # First OPEN→CLOSING mint already happened for this barrier.
                raise SessionBarrierError("BARRIER_CLOSURE_REISSUE_LIMIT") from None
            next_count = 1
        else:
            # Exact-token recover remint (incl. post-restart). Third mint refused.
            if mint_count >= 2:
                raise SessionBarrierError("BARRIER_CLOSURE_REISSUE_LIMIT") from None
            next_count = mint_count + 1
    closure_identity = _closure_identity_for(
        cap,
        close_token_identity=close_token_identity,
        closing_row_identity=row.row_identity,
        lock_identity=row.lock_identity,
    )
    seal = secrets.token_bytes(32)
    closure = object.__new__(SessionBarrierClosureCapability)
    object.__setattr__(closure, "capability_identity", cap.capability_identity)
    object.__setattr__(closure, "barrier_epoch", cap.barrier_epoch)
    object.__setattr__(closure, "session_date", cap.session_date)
    object.__setattr__(closure, "account_identity", cap.account_identity)
    object.__setattr__(closure, "oms_store_identity", cap.oms_store_identity)
    object.__setattr__(closure, "broker_store_identity", cap.broker_store_identity)
    object.__setattr__(closure, "gateway_identity", cap.gateway_identity)
    object.__setattr__(closure, "config_identity", cap.config_identity)
    object.__setattr__(closure, "close_token_identity", close_token_identity)
    object.__setattr__(closure, "closing_row_identity", row.row_identity)
    object.__setattr__(closure, "lock_identity", row.lock_identity)
    object.__setattr__(closure, "closure_identity", closure_identity)
    object.__setattr__(closure, "lock_root", cap.lock_root)
    proof = _closure_proof(
        closure,
        seal=seal,
        lock_object=lock_object,
        terminal_policy=cap.terminal_policy,
    )
    with _REGISTRY_LOCK:
        again = _CLOSURE_BY_TOKEN.get(key)
        if again is not None:
            return unpack_session_barrier_closure_capability(again, capability=cap)
        current = _CLOSURE_MINT_COUNT.get(cap.capability_identity, 0)
        if allow_fresh_mint and current >= 1:
            raise SessionBarrierError("BARRIER_CLOSURE_REISSUE_LIMIT") from None
        if not allow_fresh_mint and current >= 2:
            raise SessionBarrierError("BARRIER_CLOSURE_REISSUE_LIMIT") from None
        _CLOSURE_BINDINGS[closure] = _ClosureBinding(
            seal=seal,
            proof=proof,
            lock_object=lock_object,
            mint_generation=next_count,
        )
        _CLOSURE_BY_TOKEN[key] = closure
        _CLOSURE_MINT_COUNT[cap.capability_identity] = next_count
    return closure


def _invalidate_closure_capability(closure: object) -> None:
    """Drop a just-minted closure when the surrounding barrier transaction rolls back."""
    if type(closure) is not SessionBarrierClosureCapability:
        return
    item = cast(SessionBarrierClosureCapability, closure)
    key = (item.capability_identity, item.close_token_identity)
    with _REGISTRY_LOCK:
        binding = _CLOSURE_BINDINGS.pop(item, None)
        current = _CLOSURE_BY_TOKEN.get(key)
        if current is item:
            _CLOSURE_BY_TOKEN.pop(key, None)
        if binding is not None:
            count = _CLOSURE_MINT_COUNT.get(item.capability_identity, 0)
            if count <= 1:
                _CLOSURE_MINT_COUNT.pop(item.capability_identity, None)
            else:
                _CLOSURE_MINT_COUNT[item.capability_identity] = count - 1


def _closure_identity_for(
    cap: SessionBarrierCapability,
    *,
    close_token_identity: str,
    closing_row_identity: str,
    lock_identity: str,
) -> str:
    return _digest(
        {
            "account_identity": cap.account_identity,
            "barrier_epoch": cap.barrier_epoch,
            "barrier_schema": _BARRIER_SCHEMA,
            "broker_store_identity": cap.broker_store_identity,
            "capability_identity": cap.capability_identity,
            "close_token_identity": close_token_identity,
            "closing_row_identity": closing_row_identity,
            "config_identity": cap.config_identity,
            "gateway_identity": cap.gateway_identity,
            "lock_identity": lock_identity,
            "lock_root_fingerprint": _lock_root_fingerprint(cap.lock_root),
            "oms_store_identity": cap.oms_store_identity,
            "session_date": cap.session_date,
            "terminal_policy": cap.terminal_policy,
            "type": "session-barrier-closure-v1",
        }
    )


def _closure_proof(
    closure: SessionBarrierClosureCapability,
    *,
    seal: bytes,
    lock_object: object,
    terminal_policy: TerminalTransitionPolicy,
) -> bytes:
    return _hmac(
        _CLOSURE_DOMAIN,
        canonical_json_bytes(
            {
                "capability_identity": closure.capability_identity,
                "close_token_identity": closure.close_token_identity,
                "closing_row_identity": closure.closing_row_identity,
                "closure_identity": closure.closure_identity,
                "lock_identity": closure.lock_identity,
                "lock_object_id": id(lock_object),
                "seal": seal.hex(),
                "terminal_policy": terminal_policy,
            }
        ),
    )


def _lease_proof(lease: SessionBarrierWriteLease, *, seal: bytes) -> bytes:
    return _hmac(
        _LEASE_DOMAIN,
        canonical_json_bytes(
            {
                "barrier_epoch": lease.barrier_epoch,
                "capability_identity": lease.capability_identity,
                "lock_identity": lease.lock_identity,
                "owner_pid": lease.owner_pid,
                "owner_thread_id": lease.owner_thread_id,
                "seal": seal.hex(),
                "session_date": lease.session_date,
                "state": lease.state,
                "store_kind": lease.store_kind,
                "transaction_nonce": lease.transaction_nonce,
            }
        ),
    )


def _build_open_row(
    cap: SessionBarrierCapability,
    *,
    lock_identity: str,
    created_at: str,
) -> SessionBarrierRow:
    provisional = SessionBarrierRow(
        barrier_schema=_BARRIER_SCHEMA,
        barrier_epoch=cap.barrier_epoch,
        session_date=cap.session_date,
        account_identity=cap.account_identity,
        oms_store_identity=cap.oms_store_identity,
        broker_store_identity=cap.broker_store_identity,
        gateway_identity=cap.gateway_identity,
        config_identity=cap.config_identity,
        lock_identity=lock_identity,
        state="OPEN",
        close_token_identity=None,
        created_at=created_at,
        transitioned_at=created_at,
        row_identity="0" * 64,
    )
    return replace(
        provisional,
        row_identity=_row_identity_for(
            provisional,
            state="OPEN",
            close_token_identity=None,
            transitioned_at=created_at,
            terminal_policy=cap.terminal_policy,
        ),
    )


def _row_identity_for(
    row: SessionBarrierRow,
    *,
    state: BarrierState,
    close_token_identity: str | None,
    transitioned_at: str,
    terminal_policy: TerminalTransitionPolicy,
) -> str:
    # SUBSTRATE_RAW_TOKEN keeps the exact B1A digest payload (no new keys).
    payload: dict[str, object] = {
        "account_identity": row.account_identity,
        "barrier_epoch": row.barrier_epoch,
        "barrier_schema": row.barrier_schema,
        "broker_store_identity": row.broker_store_identity,
        "close_token_identity": close_token_identity,
        "config_identity": row.config_identity,
        "created_at": row.created_at,
        "gateway_identity": row.gateway_identity,
        "lock_identity": row.lock_identity,
        "oms_store_identity": row.oms_store_identity,
        "session_date": row.session_date,
        "state": state,
        "transitioned_at": transitioned_at,
    }
    if terminal_policy == "FORMAL_CLOSURE_ONLY":
        payload["terminal_policy_domain"] = _FORMAL_ROW_POLICY_DOMAIN
    elif terminal_policy != "SUBSTRATE_RAW_TOKEN":
        raise SessionBarrierError("BARRIER_CAPABILITY_INVALID") from None
    return _digest(payload)


def _require_identity_match(row: SessionBarrierRow, cap: SessionBarrierCapability) -> None:
    if (
        row.barrier_schema != _BARRIER_SCHEMA
        or row.barrier_epoch != cap.barrier_epoch
        or row.session_date != cap.session_date
        or row.account_identity != cap.account_identity
        or row.oms_store_identity != cap.oms_store_identity
        or row.broker_store_identity != cap.broker_store_identity
        or row.gateway_identity != cap.gateway_identity
        or row.config_identity != cap.config_identity
    ):
        raise SessionBarrierError("BARRIER_IDENTITY_DRIFT") from None
    expected = _row_identity_for(
        row,
        state=row.state,
        close_token_identity=row.close_token_identity,
        transitioned_at=row.transitioned_at,
        terminal_policy=cap.terminal_policy,
    )
    if hmac.compare_digest(row.row_identity, expected):
        return
    other_policy: TerminalTransitionPolicy = (
        "FORMAL_CLOSURE_ONLY"
        if cap.terminal_policy == "SUBSTRATE_RAW_TOKEN"
        else "SUBSTRATE_RAW_TOKEN"
    )
    other_expected = _row_identity_for(
        row,
        state=row.state,
        close_token_identity=row.close_token_identity,
        transitioned_at=row.transitioned_at,
        terminal_policy=other_policy,
    )
    if hmac.compare_digest(row.row_identity, other_expected):
        raise SessionBarrierError("BARRIER_IDENTITY_DRIFT") from None
    raise SessionBarrierError("BARRIER_ROW_CORRUPT") from None


def _insert_barrier_row(conn: sqlite3.Connection, row: SessionBarrierRow) -> None:
    conn.execute(
        """
        INSERT INTO session_barrier (
            singleton, barrier_schema, barrier_epoch, session_date,
            account_identity, oms_store_identity, broker_store_identity,
            gateway_identity, config_identity, lock_identity, state,
            close_token_identity, created_at, transitioned_at, row_identity
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.barrier_schema,
            row.barrier_epoch,
            row.session_date,
            row.account_identity,
            row.oms_store_identity,
            row.broker_store_identity,
            row.gateway_identity,
            row.config_identity,
            row.lock_identity,
            row.state,
            row.close_token_identity,
            row.created_at,
            row.transitioned_at,
            row.row_identity,
        ),
    )


def _replace_barrier_row(
    conn: sqlite3.Connection,
    *,
    previous: SessionBarrierRow,
    updated: SessionBarrierRow,
) -> None:
    try:
        cursor = conn.execute(
            """
            UPDATE session_barrier SET
                state = ?,
                close_token_identity = ?,
                transitioned_at = ?,
                row_identity = ?
            WHERE singleton = 1
              AND row_identity = ?
              AND state = ?
            """,
            (
                updated.state,
                updated.close_token_identity,
                updated.transitioned_at,
                updated.row_identity,
                previous.row_identity,
                previous.state,
            ),
        )
        if cursor.rowcount != 1:
            raise SessionBarrierError("BARRIER_STATE_STALE")
    except SessionBarrierError:
        raise
    except sqlite3.Error:
        raise SessionBarrierError("BARRIER_WRITE_FAILED") from None


def _load_barrier_rows(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    try:
        return list(
            conn.execute(
                """
                SELECT barrier_schema, barrier_epoch, session_date, account_identity,
                       oms_store_identity, broker_store_identity, gateway_identity,
                       config_identity, lock_identity, state, close_token_identity,
                       created_at, transitioned_at, row_identity
                FROM session_barrier
                ORDER BY singleton
                """
            ).fetchall()
        )
    except sqlite3.Error:
        raise SessionBarrierError("BARRIER_ROW_CORRUPT") from None


def _parse_barrier_row(row: tuple[object, ...]) -> SessionBarrierRow:
    try:
        if len(row) != 14:
            raise ValueError
        state = row[9]
        if state not in {"OPEN", "CLOSING", "CLOSED"}:
            raise SessionBarrierError("BARRIER_STATE_INVALID")
        close_token = row[10]
        if close_token is not None:
            close_token = _hex64(str(close_token))
        parsed = SessionBarrierRow(
            barrier_schema=str(row[0]),
            barrier_epoch=_hex64(str(row[1])),
            session_date=_session_date_text(str(row[2])),
            account_identity=_hex64(str(row[3])),
            oms_store_identity=_hex64(str(row[4])),
            broker_store_identity=_hex64(str(row[5])),
            gateway_identity=_hex64(str(row[6])),
            config_identity=_hex64(str(row[7])),
            lock_identity=_hex64(str(row[8])),
            state=cast(BarrierState, state),
            close_token_identity=close_token,
            created_at=_require_utc_text(str(row[11])),
            transitioned_at=_require_utc_text(str(row[12])),
            row_identity=_hex64(str(row[13])),
        )
        if parsed.barrier_schema != _BARRIER_SCHEMA:
            raise SessionBarrierError("BARRIER_SCHEMA_INVALID")
        substrate_identity = _row_identity_for(
            parsed,
            state=parsed.state,
            close_token_identity=parsed.close_token_identity,
            transitioned_at=parsed.transitioned_at,
            terminal_policy="SUBSTRATE_RAW_TOKEN",
        )
        formal_identity = _row_identity_for(
            parsed,
            state=parsed.state,
            close_token_identity=parsed.close_token_identity,
            transitioned_at=parsed.transitioned_at,
            terminal_policy="FORMAL_CLOSURE_ONLY",
        )
        if not (
            hmac.compare_digest(parsed.row_identity, substrate_identity)
            or hmac.compare_digest(parsed.row_identity, formal_identity)
        ):
            raise SessionBarrierError("BARRIER_ROW_CORRUPT")
        if parsed.state == "OPEN" and parsed.close_token_identity is not None:
            raise SessionBarrierError("BARRIER_ROW_CORRUPT")
        if parsed.state in {"CLOSING", "CLOSED"} and parsed.close_token_identity is None:
            raise SessionBarrierError("BARRIER_ROW_CORRUPT")
        return parsed
    except SessionBarrierError:
        raise
    except Exception:
        raise SessionBarrierError("BARRIER_ROW_CORRUPT") from None


def _oms_has_economic_rows(conn: sqlite3.Connection) -> bool:
    tables = (
        "commands",
        "events",
        "order_aggregates",
        "outbox",
        "ledger_entries",
        "cancel_commands",
        "approval_receipts",
    )
    for name in tables:
        try:
            row = conn.execute(f"SELECT 1 FROM {name} LIMIT 1").fetchone()
        except sqlite3.Error:
            continue
        if row is not None:
            return True
    return False


def _acquire_barrier_lock(root: Path) -> _HeldBarrierLock:
    # Direct sys.platform checks keep both arms mypy-reachable (no _IS_WIN32).
    if sys.platform == "win32":
        return _acquire_barrier_lock_win32(root)
    return _acquire_barrier_lock_posix(root)


def _acquire_barrier_lock_posix(root: Path) -> _HeldBarrierLock:
    ancestor_identities, root_identity = _snapshot_root_identities(root)
    dir_fd = -1
    lock_fd = -1
    try:
        try:
            dir_fd = os.open(
                root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY")
                | getattr(os, "O_CLOEXEC")
                | getattr(os, "O_NOFOLLOW"),
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.ENOENT}:
                raise SessionBarrierError("BARRIER_LOCK_ROOT_INVALID") from None
            raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
        _assert_fd_identity(dir_fd, root_identity, "BARRIER_LOCK_ROOT_INVALID")
        try:
            lock_fd = os.open(
                _LOCK_NAME,
                os.O_RDWR
                | os.O_CREAT
                | getattr(os, "O_CLOEXEC")
                | getattr(os, "O_NOFOLLOW"),
                0o600,
                dir_fd=dir_fd,
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR}:
                raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
            raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
        lock_path = root / _LOCK_NAME
        lock_identity_raw = _validate_lock_fd(
            dir_fd=dir_fd, lock_fd=lock_fd, lock_path=lock_path
        )
        _ensure_lock_byte(lock_fd)
        _apply_exclusive_lock(lock_fd)
        _revalidate_after_acquire(
            root=root,
            dir_fd=dir_fd,
            lock_fd=lock_fd,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity=lock_identity_raw,
        )
        held = _HeldBarrierLock(
            lock_fd=lock_fd,
            dir_fd=dir_fd,
            root=root,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity_raw=lock_identity_raw,
            lock_identity=_lock_object_identity(lock_identity_raw),
        )
        dir_fd = -1
        lock_fd = -1
        return held
    except SessionBarrierError:
        _best_effort_close(lock_fd)
        _best_effort_close(dir_fd)
        raise
    except Exception:
        _best_effort_close(lock_fd)
        _best_effort_close(dir_fd)
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None


def _acquire_barrier_lock_win32(root: Path) -> _HeldBarrierLock:
    ancestor_identities, root_identity = _snapshot_root_identities(root)
    lock_path = root / _LOCK_NAME
    lock_fd = -1
    try:
        _reject_reparse_path(lock_path, missing_ok=True, code="BARRIER_LOCK_FILE_INVALID")
        try:
            lock_fd = os.open(
                lock_path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except OSError as exc:
            if _path_is_plain_dir(lock_path) or exc.errno == errno.EISDIR:
                raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
            raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
        _ensure_lock_byte(lock_fd)
        lock_identity_raw = _validate_lock_fd(
            dir_fd=-1, lock_fd=lock_fd, lock_path=lock_path
        )
        _apply_exclusive_lock(lock_fd)
        _revalidate_after_acquire(
            root=root,
            dir_fd=-1,
            lock_fd=lock_fd,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity=lock_identity_raw,
        )
        held = _HeldBarrierLock(
            lock_fd=lock_fd,
            dir_fd=-1,
            root=root,
            lock_path=lock_path,
            root_identity=root_identity,
            ancestor_identities=ancestor_identities,
            lock_identity_raw=lock_identity_raw,
            lock_identity=_lock_object_identity(lock_identity_raw),
        )
        lock_fd = -1
        return held
    except SessionBarrierError:
        _best_effort_close(lock_fd)
        raise
    except Exception:
        _best_effort_close(lock_fd)
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None


def _release_barrier_lock(held: _HeldBarrierLock) -> None:
    release_error: SessionBarrierError | None = None
    try:
        _revalidate_for_release(held)
        try:
            _release_exclusive_lock(held.lock_fd)
        except OSError:
            release_error = SessionBarrierError("BARRIER_LOCK_RELEASE_FAILED")
    except SessionBarrierError as exc:
        release_error = exc
    except Exception:
        release_error = SessionBarrierError("BARRIER_LOCK_RELEASE_FAILED")
    if not _best_effort_close(held.lock_fd) and release_error is None:
        release_error = SessionBarrierError("BARRIER_LOCK_RELEASE_FAILED")
    held.lock_fd = -1
    if held.dir_fd >= 0:
        if not _best_effort_close(held.dir_fd) and release_error is None:
            release_error = SessionBarrierError("BARRIER_LOCK_RELEASE_FAILED")
        held.dir_fd = -1
    if release_error is not None:
        raise release_error from None


def _apply_exclusive_lock(lock_fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {
                errno.EACCES,
                errno.EAGAIN,
                getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
            }:
                raise SessionBarrierError("BARRIER_WRITER_BUSY") from None
            raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
        return
    import fcntl

    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {
            errno.EACCES,
            errno.EAGAIN,
            getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
        }:
            raise SessionBarrierError("BARRIER_WRITER_BUSY") from None
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None


def _release_exclusive_lock(lock_fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(lock_fd, 0, os.SEEK_SET)
        msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(lock_fd, fcntl.LOCK_UN)


def _ensure_lock_byte(lock_fd: int) -> None:
    try:
        size = os.fstat(lock_fd).st_size
    except OSError:
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
    if size >= 1:
        if size != 1:
            raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
        return
    try:
        os.lseek(lock_fd, 0, os.SEEK_SET)
        if os.write(lock_fd, b"\0") != 1:
            raise OSError
        os.fsync(lock_fd)
    except OSError:
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None


def _snapshot_root_identities(root: Path) -> tuple[dict[Path, _Identity], _Identity]:
    identities: dict[Path, _Identity] = {}
    try:
        root_stat = os.lstat(root)
    except FileNotFoundError:
        raise SessionBarrierError("BARRIER_LOCK_ROOT_INVALID") from None
    except OSError:
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
    if _is_reparse_stat(root, root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise SessionBarrierError("BARRIER_LOCK_ROOT_INVALID")
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    identities[root] = root_identity
    for path in root.parents:
        try:
            path_stat = os.lstat(path)
        except FileNotFoundError:
            raise SessionBarrierError("BARRIER_LOCK_ROOT_INVALID") from None
        except OSError:
            raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
        if _is_reparse_stat(path, path_stat) or not stat.S_ISDIR(path_stat.st_mode):
            raise SessionBarrierError("BARRIER_LOCK_ROOT_INVALID")
        identities[path] = (path_stat.st_dev, path_stat.st_ino)
    return identities, root_identity


def _is_reparse_stat(path: Path, path_stat: os.stat_result) -> bool:
    if stat.S_ISLNK(path_stat.st_mode):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if callable(isjunction) and isjunction(path):
        return True
    attrs = getattr(path_stat, "st_file_attributes", 0)
    return bool(attrs & _REPARSE)


def _reject_reparse_path(path: Path, *, missing_ok: bool, code: str) -> None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            return
        raise SessionBarrierError(code) from None
    except OSError:
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
    if _is_reparse_stat(path, path_stat):
        raise SessionBarrierError(code) from None


def _path_is_plain_dir(path: Path) -> bool:
    try:
        path_stat = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(path_stat.st_mode) and not _is_reparse_stat(path, path_stat)


def _validate_lock_fd(*, dir_fd: int, lock_fd: int, lock_path: Path) -> _Identity:
    try:
        fd_stat = os.fstat(lock_fd)
    except OSError:
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
    if not stat.S_ISREG(fd_stat.st_mode) or fd_stat.st_nlink != 1:
        raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
    try:
        if dir_fd >= 0:
            entry_stat = os.stat(_LOCK_NAME, dir_fd=dir_fd, follow_symlinks=False)
        else:
            entry_stat = os.lstat(lock_path)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ELOOP, errno.ENOTDIR}:
            raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
        raise SessionBarrierError("BARRIER_LOCK_IO_FAILED") from None
    if dir_fd < 0 and _is_reparse_stat(lock_path, entry_stat):
        raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
    if not stat.S_ISREG(entry_stat.st_mode) or entry_stat.st_nlink != 1:
        raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
    if (entry_stat.st_dev, entry_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino):
        raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None
    return (fd_stat.st_dev, fd_stat.st_ino)


def _revalidate_after_acquire(
    *,
    root: Path,
    dir_fd: int,
    lock_fd: int,
    lock_path: Path,
    root_identity: _Identity,
    ancestor_identities: dict[Path, _Identity],
    lock_identity: _Identity,
) -> None:
    current_ancestors, current_root = _snapshot_root_identities(root)
    if current_root != root_identity or current_ancestors != ancestor_identities:
        raise SessionBarrierError("BARRIER_LOCK_ROOT_INVALID") from None
    if dir_fd >= 0:
        _assert_fd_identity(dir_fd, root_identity, "BARRIER_LOCK_ROOT_INVALID")
    current_lock = _validate_lock_fd(dir_fd=dir_fd, lock_fd=lock_fd, lock_path=lock_path)
    if current_lock != lock_identity:
        raise SessionBarrierError("BARRIER_LOCK_FILE_INVALID") from None


def _revalidate_for_release(held: _HeldBarrierLock) -> None:
    try:
        current_ancestors, current_root = _snapshot_root_identities(held.root)
        if current_root != held.root_identity or current_ancestors != held.ancestor_identities:
            raise SessionBarrierError("BARRIER_LOCK_RELEASE_FAILED")
        if held.dir_fd >= 0:
            _assert_fd_identity(held.dir_fd, held.root_identity, "BARRIER_LOCK_RELEASE_FAILED")
        current_lock = _validate_lock_fd(
            dir_fd=held.dir_fd, lock_fd=held.lock_fd, lock_path=held.lock_path
        )
        if current_lock != held.lock_identity_raw:
            raise SessionBarrierError("BARRIER_LOCK_RELEASE_FAILED")
    except SessionBarrierError as exc:
        if exc.code == "BARRIER_LOCK_RELEASE_FAILED":
            raise
        raise SessionBarrierError("BARRIER_LOCK_RELEASE_FAILED") from None


def _assert_fd_identity(fd: int, expected: _Identity, code: str) -> None:
    try:
        current = os.fstat(fd)
    except OSError:
        raise SessionBarrierError(code) from None
    if (current.st_dev, current.st_ino) != expected:
        raise SessionBarrierError(code) from None


def _best_effort_close(fd: int) -> bool:
    if fd < 0:
        return True
    try:
        os.close(fd)
        return True
    except OSError:
        return False


def _lock_object_identity(raw: _Identity) -> str:
    return _digest({"st_dev": raw[0], "st_ino": raw[1], "type": "session-barrier-lock-v1"})


def _lock_root_fingerprint(root: Path) -> str:
    # Process-local fingerprint only; never persisted into the barrier row.
    return _digest(
        {
            "normcase": os.path.normcase(os.path.abspath(root)),
            "type": "session-barrier-lock-root-v1",
        }
    )


def _require_absolute_path(value: Path) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE or not value.is_absolute():
        raise SessionBarrierError("BARRIER_LOCK_ROOT_INVALID")
    return value


def _require_terminal_policy(value: object) -> TerminalTransitionPolicy:
    if type(value) is not str or value not in _TERMINAL_POLICIES:
        raise SessionBarrierError("BARRIER_CAPABILITY_INVALID")
    return cast(TerminalTransitionPolicy, value)


def _hex64(value: object) -> str:
    if type(value) is not str or len(value) != 64 or not set(value) <= _HEX:
        raise SessionBarrierError("BARRIER_IDENTITY_INVALID")
    return value


def _require_nonce(value: object) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise SessionBarrierError("BARRIER_TOKEN_INVALID")
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
        raise SessionBarrierError("BARRIER_TOKEN_INVALID")
    return value


def _session_date_text(value: object) -> str:
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is str and len(value) == 10 and value[4] == "-" and value[7] == "-":
        dt.date.fromisoformat(value)
        return value
    raise SessionBarrierError("BARRIER_IDENTITY_INVALID")


def _utc_text(value: dt.datetime) -> str:
    if type(value) is not dt.datetime or value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise SessionBarrierError("BARRIER_TIME_INVALID")
    text = utc_datetime_text(value)
    return _require_utc_text(text)


def _require_utc_text(value: str) -> str:
    if type(value) is not str or len(value) != 27 or not value.endswith("Z"):
        raise SessionBarrierError("BARRIER_TIME_INVALID")
    return value


def _digest(payload: Mapping[str, object]) -> str:
    """SHA-256 over canonical_json_bytes; Mapping contract matches wire SSOT."""
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _hmac(domain: bytes, body: bytes) -> bytes:
    return hmac.new(_PROCESS_PROOF_KEY, domain + body, hashlib.sha256).digest()


# SessionBarrierOperationPermit / hold_open_operation_permit stay module-private
# (not exported). ExecutionStore.open_operation_fence imports the holder narrowly.
__all__ = [
    "SessionBarrierCapability",
    "SessionBarrierClosureCapability",
    "SessionBarrierError",
    "SessionBarrierOmsHandle",
    "SessionBarrierRow",
    "SessionBarrierWriteLease",
    "TerminalTransitionPolicy",
    "build_session_barrier_capability",
    "compute_close_token_identity",
    "fresh_read_session_barrier",
    "hold_open_write_lease",
    "hold_session_barrier_lock",
    "initialize_open_barrier",
    "invalidate_session_barrier_oms_handle",
    "invalidate_write_lease",
    "issue_session_barrier_oms_handle",
    "read_session_barrier",
    "recover_session_barrier_closure_capability",
    "require_matching_barrier",
    "require_matching_barrier_handle",
    "transition_closing_to_closed",
    "transition_open_to_closing",
    "unpack_open_write_lease",
    "unpack_session_barrier_capability",
    "unpack_session_barrier_closure_capability",
    "unpack_session_barrier_oms_handle",
    "unpack_session_barrier_operation_permit",
    "verify_lease_against_row",
]
