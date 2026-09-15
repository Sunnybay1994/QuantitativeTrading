"""M4-D1 production repositories: compose strict readers, fail closed.

Based on pending-main-acceptance M4-D0 contracts. Callers never pass arbitrary
directory parameters on load methods. Wiring may supply configured paths only for
legacy-path rejection audits; no filesystem scanning is performed here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypeVar

from quant.domain.enums import ConnectRoute, Market
from quant.execution.contracts import (
    AccountSnapshot,
    CashBalance,
    ContractError,
    PositionBalance,
    SymbolMarketState,
    VerifiedConnectMarketContext,
    VerifiedMarketSnapshot,
    build_account_snapshot,
    build_account_snapshot_identity,
    build_verified_connect_market_context_identity,
    build_verified_market_snapshot,
    build_verified_market_snapshot_identity,
)
from quant.execution.ports import ConnectMarketContextRepository

_LEGACY_MARKERS = ("data/legacy", "data\\legacy")
_HEX64 = frozenset("0123456789abcdef")
_T = TypeVar("_T")


class RepositoryContractError(ValueError):
    """Stable typed repository contract violation (no partial payloads)."""

    def __init__(self, code: str, message: str = "") -> None:
        if type(code) is not str or not code:
            raise ValueError("RepositoryContractError code must be non-empty str")
        self.code = code
        detail = message or code
        super().__init__(f"{code}: {detail}" if message else code)


def _require_hex64_identity(name: str, value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX64 for char in value):
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            f"{name} must be bare 64-char lowercase hex",
        )
    return value


def _require_exact_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            f"{name} must be bool",
        )
    return value


@dataclass(frozen=True, slots=True)
class CleanMarketFactsBundle:
    """Strict-reader output before port-level assembly/validation."""

    known_as_of: dt.datetime
    states: tuple[SymbolMarketState, ...]
    calendar_identity: str
    source_identity: str
    quality_passed: bool

    def __post_init__(self) -> None:
        _validate_clean_market_facts_bundle(self)


@dataclass(frozen=True, slots=True)
class CleanAccountFactsBundle:
    """Strict-reader output for account snapshot assembly."""

    known_as_of: dt.datetime
    positions: tuple[PositionBalance, ...]
    cash: tuple[CashBalance, ...]
    quality_passed: bool

    def __post_init__(self) -> None:
        _validate_clean_account_facts_bundle(self)


MarketFactsReader = Callable[
    ...,
    CleanMarketFactsBundle,
]
AccountFactsReader = Callable[..., CleanAccountFactsBundle]


def reject_data_legacy_path(path: Path | str) -> None:
    """Reject any wiring path that targets data/legacy (fail closed)."""
    text = str(path).replace("\\", "/").lower()
    posix = PurePosixPath(text)
    parts = tuple(part.lower() for part in posix.parts)
    if "legacy" in parts and "data" in parts:
        data_idx = parts.index("data")
        if data_idx + 1 < len(parts) and parts[data_idx + 1] == "legacy":
            raise RepositoryContractError(
                "LEGACY_PATH_REJECTED",
                "data/legacy paths are not allowed",
            )
    for marker in _LEGACY_MARKERS:
        if marker in text:
            raise RepositoryContractError(
                "LEGACY_PATH_REJECTED",
                "data/legacy paths are not allowed",
            )


def _require_utc_datetime(name: str, value: object) -> dt.datetime:
    if type(value) is not dt.datetime:
        raise RepositoryContractError("INVALID_AS_OF", f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryContractError("INVALID_AS_OF", f"{name} must be timezone-aware UTC")
    if value.utcoffset() != dt.timedelta(0):
        raise RepositoryContractError("INVALID_AS_OF", f"{name} must be timezone-aware UTC")
    return value


def _require_date(name: str, value: object) -> dt.date:
    if type(value) is not dt.date or isinstance(value, dt.datetime):
        raise RepositoryContractError("INVALID_SESSION_DATE", f"{name} must be date")
    return value


def _require_exact_connect_routes(value: object) -> tuple[ConnectRoute, ...]:
    """Require exact tuple[ConnectRoute, ...] unique and sorted by .value ascending."""
    if type(value) is not tuple:
        raise RepositoryContractError(
            "INVALID_CONNECT_ROUTES",
            "connect_routes must be exact tuple[ConnectRoute, ...]",
        )
    routes: list[ConnectRoute] = []
    for item in value:
        if type(item) is not ConnectRoute:
            raise RepositoryContractError(
                "INVALID_CONNECT_ROUTES",
                "connect_routes elements must be exact ConnectRoute",
            )
        routes.append(item)
    route_values = tuple(item.value for item in routes)
    if len(route_values) != len(set(route_values)):
        raise RepositoryContractError(
            "INVALID_CONNECT_ROUTES",
            "connect_routes must be unique",
        )
    if route_values != tuple(sorted(route_values)):
        raise RepositoryContractError(
            "INVALID_CONNECT_ROUTES",
            "connect_routes must be sorted by value ascending",
        )
    return tuple(routes)


def _audit_configured_paths(paths: Sequence[Path | str]) -> None:
    for path in paths:
        reject_data_legacy_path(path)


def _validate_clean_market_facts_bundle(bundle: object) -> CleanMarketFactsBundle:
    if type(bundle) is not CleanMarketFactsBundle:
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            "reader must return CleanMarketFactsBundle",
        )
    _require_utc_datetime("known_as_of", bundle.known_as_of)
    if type(bundle.states) is not tuple:
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            "states must be tuple[SymbolMarketState, ...]",
        )
    for state in bundle.states:
        if type(state) is not SymbolMarketState:
            raise RepositoryContractError(
                "INVALID_READER_RESULT",
                "states must be tuple[SymbolMarketState, ...]",
            )
    _require_hex64_identity("calendar_identity", bundle.calendar_identity)
    _require_hex64_identity("source_identity", bundle.source_identity)
    _require_exact_bool("quality_passed", bundle.quality_passed)
    return bundle


def _validate_clean_account_facts_bundle(bundle: object) -> CleanAccountFactsBundle:
    if type(bundle) is not CleanAccountFactsBundle:
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            "reader must return CleanAccountFactsBundle",
        )
    _require_utc_datetime("known_as_of", bundle.known_as_of)
    if type(bundle.positions) is not tuple:
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            "positions must be tuple[PositionBalance, ...]",
        )
    for position in bundle.positions:
        if type(position) is not PositionBalance:
            raise RepositoryContractError(
                "INVALID_READER_RESULT",
                "positions must be tuple[PositionBalance, ...]",
            )
    if type(bundle.cash) is not tuple:
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            "cash must be tuple[CashBalance, ...]",
        )
    for item in bundle.cash:
        if type(item) is not CashBalance:
            raise RepositoryContractError(
                "INVALID_READER_RESULT",
                "cash must be tuple[CashBalance, ...]",
            )
    _require_exact_bool("quality_passed", bundle.quality_passed)
    return bundle


def _check_symbol_coverage(
    *,
    requested: tuple[str, ...],
    observed: Sequence[str],
) -> None:
    req = set(requested)
    obs = set(observed)
    missing = req - obs
    extra = obs - req
    if missing:
        raise RepositoryContractError(
            "MISSING_SYMBOL",
            f"missing symbols: {len(missing)}",
        )
    if extra:
        raise RepositoryContractError(
            "SYMBOL_SUPERSET",
            f"unexpected symbols: {len(extra)}",
        )
    if len(observed) != len(set(observed)):
        raise RepositoryContractError("DUPLICATE_KEY", "duplicate symbols in states")


def _check_state_keys(states: Sequence[SymbolMarketState]) -> None:
    seen: set[tuple[Market, str]] = set()
    for state in states:
        key = (state.market, state.symbol)
        if key in seen:
            raise RepositoryContractError("DUPLICATE_KEY", "duplicate market/symbol")
        seen.add(key)


def _assert_session_dates(
    states: Sequence[SymbolMarketState], session_date: dt.date
) -> None:
    for state in states:
        if state.session_date != session_date:
            raise RepositoryContractError(
                "SESSION_DATE_MISMATCH",
                "state session_date must match request",
            )


def _pit_check(*, known_as_of: dt.datetime, as_of: dt.datetime) -> None:
    if known_as_of > as_of:
        raise RepositoryContractError(
            "PIT_VIOLATION",
            "snapshot known_as_of is after requested as_of",
        )


def _map_domain_contract_error() -> RepositoryContractError:
    return RepositoryContractError(
        "DOMAIN_CONTRACT",
        "domain contract rejected payload",
    )


def _invoke_domain(action: Callable[[], _T]) -> _T:
    """Run domain builder/verifier; map ContractError without exception chaining."""
    failure: RepositoryContractError | None = None
    try:
        return action()
    except ContractError:
        failure = _map_domain_contract_error()
    if failure is None:
        raise RuntimeError("unreachable")
    raise failure


def _states_have_hk(states: Sequence[SymbolMarketState]) -> bool:
    return any(state.market is Market.HK for state in states)


def _validate_loaded_connect_context(
    raw: object,
    *,
    route: ConnectRoute,
    session_date: dt.date,
    as_of: dt.datetime,
) -> VerifiedConnectMarketContext:
    """Exact-type, identity, route/session, and PIT checks for a loaded context."""
    if type(raw) is not VerifiedConnectMarketContext:
        raise RepositoryContractError(
            "CONNECT_CONTEXT_CONTRACT_INVALID",
            "connect context must be exact VerifiedConnectMarketContext",
        )
    identity_failure: RepositoryContractError | None = None
    try:
        build_verified_connect_market_context_identity(raw)
    except Exception:
        identity_failure = RepositoryContractError(
            "CONNECT_CONTEXT_CONTRACT_INVALID",
            "connect context identity invalid",
        )
    if identity_failure is not None:
        raise identity_failure from None
    if raw.route is not route:
        raise RepositoryContractError(
            "CONNECT_CONTEXT_CONTRACT_INVALID",
            "connect context route must match request",
        )
    if raw.session_date != session_date:
        raise RepositoryContractError(
            "CONNECT_CONTEXT_CONTRACT_INVALID",
            "connect context session_date must match request",
        )
    if raw.as_of > as_of:
        raise RepositoryContractError(
            "CONNECT_CONTEXT_CONTRACT_INVALID",
            "connect context as_of must be <= query as_of",
        )
    return raw


def _load_connect_contexts_for_routes(
    *,
    connect_context_repository: ConnectMarketContextRepository,
    connect_routes: tuple[ConnectRoute, ...],
    session_date: dt.date,
    as_of: dt.datetime,
) -> tuple[VerifiedConnectMarketContext, ...]:
    loaded: list[VerifiedConnectMarketContext] = []
    for route in connect_routes:
        reader_failure: RepositoryContractError | None = None
        raw: object | None = None
        try:
            raw = connect_context_repository.load_verified_connect_market_context(
                route=route,
                session_date=session_date,
                as_of=as_of,
            )
        except RepositoryContractError:
            raise
        except Exception:
            reader_failure = RepositoryContractError(
                "CONNECT_CONTEXT_READER_FAILURE",
                "connect context reader failed",
            )
        if reader_failure is not None:
            raise reader_failure from None
        loaded.append(
            _validate_loaded_connect_context(
                raw,
                route=route,
                session_date=session_date,
                as_of=as_of,
            )
        )
    return tuple(loaded)


def _assemble_connect_contexts(
    *,
    states: Sequence[SymbolMarketState],
    connect_routes: tuple[ConnectRoute, ...],
    connect_context_repository: ConnectMarketContextRepository | None,
    session_date: dt.date,
    known_as_of: dt.datetime,
) -> tuple[VerifiedConnectMarketContext, ...]:
    has_hk = _states_have_hk(states)
    if has_hk:
        if not connect_routes:
            raise RepositoryContractError(
                "CONNECT_CONTEXT_REQUIRED",
                "HK market state requires connect_routes",
            )
        if connect_context_repository is None:
            raise RepositoryContractError(
                "CONNECT_CONTEXT_REPOSITORY_REQUIRED",
                "HK market state requires connect_context_repository",
            )
        return _load_connect_contexts_for_routes(
            connect_context_repository=connect_context_repository,
            connect_routes=connect_routes,
            session_date=session_date,
            as_of=known_as_of,
        )
    if connect_routes:
        raise RepositoryContractError(
            "CONNECT_CONTEXT_UNEXPECTED",
            "connect_routes must be empty when snapshot has no HK state",
        )
    return ()


def _validate_market_mapping_entry(
    key: object,
    snapshot: object,
) -> tuple[tuple[dt.date, frozenset[str]], VerifiedMarketSnapshot]:
    if type(key) is not tuple or len(key) != 2:
        raise RepositoryContractError(
            "INVALID_MAPPING_KEY",
            "market key must be (date, frozenset[str])",
        )
    session_date, symbols = key
    if type(session_date) is not dt.date or isinstance(session_date, dt.datetime):
        raise RepositoryContractError(
            "INVALID_MAPPING_KEY",
            "market key session_date must be date",
        )
    if type(symbols) is not frozenset or any(type(item) is not str for item in symbols):
        raise RepositoryContractError(
            "INVALID_MAPPING_KEY",
            "market key symbols must be frozenset[str]",
        )
    if type(snapshot) is not VerifiedMarketSnapshot:
        raise RepositoryContractError(
            "INVALID_SNAPSHOT",
            "market mapping value must be VerifiedMarketSnapshot",
        )
    if session_date != snapshot.session_date:
        raise RepositoryContractError(
            "KEY_CONTENT_MISMATCH",
            "market key session_date must match snapshot.session_date",
        )
    observed = frozenset(item.symbol for item in snapshot.states)
    if symbols != observed:
        raise RepositoryContractError(
            "KEY_CONTENT_MISMATCH",
            "market key symbol set must match snapshot states",
        )
    _invoke_domain(lambda: build_verified_market_snapshot_identity(snapshot))
    return (session_date, symbols), snapshot


def _validate_account_mapping_entry(
    key: object,
    snapshot: object,
) -> tuple[dt.datetime, AccountSnapshot]:
    as_of = _require_utc_datetime("mapping key", key)
    if type(snapshot) is not AccountSnapshot:
        raise RepositoryContractError(
            "INVALID_SNAPSHOT",
            "account mapping value must be AccountSnapshot",
        )
    if as_of != snapshot.as_of:
        raise RepositoryContractError(
            "KEY_CONTENT_MISMATCH",
            "account key must equal snapshot.as_of",
        )
    _invoke_domain(lambda: build_account_snapshot_identity(snapshot))
    return as_of, snapshot


def _require_symbol_market_states(states: Sequence[SymbolMarketState]) -> tuple[SymbolMarketState, ...]:
    if isinstance(states, (str, bytes)) or not isinstance(states, Sequence):
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            "states must be a sequence of SymbolMarketState",
        )
    items = tuple(states)
    for state in items:
        if type(state) is not SymbolMarketState:
            raise RepositoryContractError(
                "INVALID_READER_RESULT",
                "states must be a sequence of SymbolMarketState",
            )
    return items


def _require_connect_contexts(
    contexts: Sequence[VerifiedConnectMarketContext],
) -> tuple[VerifiedConnectMarketContext, ...]:
    if isinstance(contexts, (str, bytes)) or not isinstance(contexts, Sequence):
        raise RepositoryContractError(
            "INVALID_READER_RESULT",
            "connect_contexts must be a sequence of VerifiedConnectMarketContext",
        )
    items = tuple(contexts)
    for item in items:
        if type(item) is not VerifiedConnectMarketContext:
            raise RepositoryContractError(
                "INVALID_READER_RESULT",
                "connect_contexts must be a sequence of VerifiedConnectMarketContext",
            )
    return items


class ValidatedCleanMarketDataRepository:
    """Production MarketDataRepository: compose injected strict readers only."""

    def __init__(
        self,
        *,
        read_market_facts: Callable[
            ...,
            CleanMarketFactsBundle,
        ],
        connect_context_repository: ConnectMarketContextRepository | None = None,
        configured_paths: Sequence[Path | str] = (),
    ) -> None:
        _audit_configured_paths(configured_paths)
        self._read_market_facts = read_market_facts
        self._connect_context_repository = connect_context_repository

    def load_verified_market_snapshot(
        self,
        *,
        symbols: tuple[str, ...],
        session_date: dt.date,
        as_of: dt.datetime,
        connect_routes: tuple[ConnectRoute, ...],
    ) -> VerifiedMarketSnapshot:
        as_of_utc = _require_utc_datetime("as_of", as_of)
        session = _require_date("session_date", session_date)
        routes = _require_exact_connect_routes(connect_routes)
        if type(symbols) is not tuple or any(type(item) is not str or not item for item in symbols):
            raise RepositoryContractError("INVALID_SYMBOLS", "symbols must be tuple[str, ...]")
        if len(symbols) != len(set(symbols)):
            raise RepositoryContractError("DUPLICATE_KEY", "requested symbols not unique")

        reader_failure: RepositoryContractError | None = None
        raw_bundle: CleanMarketFactsBundle | None = None
        try:
            raw_bundle = self._read_market_facts(
                symbols=symbols,
                session_date=session,
                as_of=as_of_utc,
            )
        except RepositoryContractError:
            raise
        except Exception:
            reader_failure = RepositoryContractError(
                "READER_FAILURE",
                "market facts reader failed",
            )
        if reader_failure is not None:
            raise reader_failure
        if raw_bundle is None:
            raise RepositoryContractError(
                "INVALID_READER_RESULT",
                "reader must return CleanMarketFactsBundle",
            )

        bundle = _validate_clean_market_facts_bundle(raw_bundle)
        if bundle.quality_passed is not True:
            raise RepositoryContractError(
                "QUALITY_GATE_FAILED",
                "clean market quality gate failed",
            )
        known = bundle.known_as_of
        _pit_check(known_as_of=known, as_of=as_of_utc)
        states = bundle.states
        _check_state_keys(states)
        _check_symbol_coverage(
            requested=symbols,
            observed=tuple(item.symbol for item in states),
        )
        _assert_session_dates(states, session)
        contexts = _assemble_connect_contexts(
            states=states,
            connect_routes=routes,
            connect_context_repository=self._connect_context_repository,
            session_date=session,
            known_as_of=known,
        )
        return _invoke_domain(
            lambda: build_verified_market_snapshot(
                as_of=known,
                session_date=session,
                states=states,
                connect_contexts=contexts,
                calendar_identity=bundle.calendar_identity,
                source_identity=bundle.source_identity,
            )
        )


class ValidatedCleanAccountSnapshotRepository:
    """Production AccountSnapshotRepository: compose injected strict readers only."""

    def __init__(
        self,
        *,
        read_account_facts: Callable[..., CleanAccountFactsBundle],
        configured_paths: Sequence[Path | str] = (),
    ) -> None:
        _audit_configured_paths(configured_paths)
        self._read_account_facts = read_account_facts

    def load_account_snapshot(self, *, as_of: dt.datetime) -> AccountSnapshot:
        as_of_utc = _require_utc_datetime("as_of", as_of)
        reader_failure: RepositoryContractError | None = None
        raw_bundle: CleanAccountFactsBundle | None = None
        try:
            raw_bundle = self._read_account_facts(as_of=as_of_utc)
        except RepositoryContractError:
            raise
        except Exception:
            reader_failure = RepositoryContractError(
                "READER_FAILURE",
                "account facts reader failed",
            )
        if reader_failure is not None:
            raise reader_failure
        if raw_bundle is None:
            raise RepositoryContractError(
                "INVALID_READER_RESULT",
                "reader must return CleanAccountFactsBundle",
            )

        bundle = _validate_clean_account_facts_bundle(raw_bundle)
        if bundle.quality_passed is not True:
            raise RepositoryContractError(
                "QUALITY_GATE_FAILED",
                "account quality gate failed",
            )
        known = bundle.known_as_of
        _pit_check(known_as_of=known, as_of=as_of_utc)
        return _invoke_domain(
            lambda: build_account_snapshot(
                as_of=known,
                positions=bundle.positions,
                cash=bundle.cash,
            )
        )


class InMemoryMarketDataRepository:
    """Contract fake: keyed by (session_date, frozenset(symbols))."""

    def __init__(
        self,
        snapshots: Mapping[
            tuple[dt.date, frozenset[str]],
            VerifiedMarketSnapshot,
        ],
        *,
        configured_paths: Sequence[Path | str] = (),
    ) -> None:
        _audit_configured_paths(configured_paths)
        validated: dict[tuple[dt.date, frozenset[str]], VerifiedMarketSnapshot] = {}
        for key, snapshot in snapshots.items():
            bound_key, bound_snap = _validate_market_mapping_entry(key, snapshot)
            validated[bound_key] = bound_snap
        self._snapshots = validated

    @classmethod
    def from_states(
        cls,
        *,
        session_date: dt.date,
        as_of: dt.datetime,
        states: Sequence[SymbolMarketState],
        connect_contexts: Sequence[VerifiedConnectMarketContext],
        calendar_identity: str,
        source_identity: str,
        configured_paths: Sequence[Path | str] = (),
    ) -> InMemoryMarketDataRepository:
        state_items = _require_symbol_market_states(states)
        context_items = _require_connect_contexts(connect_contexts)
        _check_state_keys(state_items)
        snap = _invoke_domain(
            lambda: build_verified_market_snapshot(
                as_of=as_of,
                session_date=session_date,
                states=state_items,
                connect_contexts=context_items,
                calendar_identity=calendar_identity,
                source_identity=source_identity,
            )
        )
        key = (session_date, frozenset(item.symbol for item in snap.states))
        return cls({key: snap}, configured_paths=configured_paths)

    def load_verified_market_snapshot(
        self,
        *,
        symbols: tuple[str, ...],
        session_date: dt.date,
        as_of: dt.datetime,
        connect_routes: tuple[ConnectRoute, ...],
    ) -> VerifiedMarketSnapshot:
        as_of_utc = _require_utc_datetime("as_of", as_of)
        session = _require_date("session_date", session_date)
        routes = _require_exact_connect_routes(connect_routes)
        if type(symbols) is not tuple or any(type(item) is not str or not item for item in symbols):
            raise RepositoryContractError("INVALID_SYMBOLS", "symbols must be tuple[str, ...]")
        if len(symbols) != len(set(symbols)):
            raise RepositoryContractError("DUPLICATE_KEY", "requested symbols not unique")

        key = (session, frozenset(symbols))
        exact = self._snapshots.get(key)
        if exact is not None:
            _pit_check(known_as_of=exact.as_of, as_of=as_of_utc)
            snap_routes = frozenset(item.route for item in exact.connect_contexts)
            if snap_routes != frozenset(routes):
                raise RepositoryContractError(
                    "SNAPSHOT_CONNECT_ROUTES_MISMATCH",
                    "request connect_routes must equal snapshot route set",
                )
            return exact

        # Scan same session for coverage diagnostics (still fail closed, no partial).
        session_snaps = [
            snap for (snap_session, _), snap in self._snapshots.items() if snap_session == session
        ]
        if not session_snaps:
            raise RepositoryContractError("MISSING_SNAPSHOT", "no snapshot for session_date")

        # Prefer the unique snapshot whose symbol set relates for clearer codes.
        for snap in session_snaps:
            observed = {item.symbol for item in snap.states}
            requested = set(symbols)
            if requested < observed:
                raise RepositoryContractError(
                    "SYMBOL_SUPERSET",
                    "requested symbols are a proper subset of stored snapshot",
                )
            if observed < requested:
                raise RepositoryContractError(
                    "MISSING_SYMBOL",
                    "stored snapshot missing requested symbols",
                )
        raise RepositoryContractError("MISSING_SNAPSHOT", "no exact symbol-key snapshot")


class InMemoryAccountSnapshotRepository:
    """Contract fake: exact as_of keys; PIT requires known_as_of <= request as_of."""

    def __init__(
        self,
        snapshots: Mapping[dt.datetime, AccountSnapshot],
        *,
        configured_paths: Sequence[Path | str] = (),
    ) -> None:
        _audit_configured_paths(configured_paths)
        validated: dict[dt.datetime, AccountSnapshot] = {}
        for key, snapshot in snapshots.items():
            bound_key, bound_snap = _validate_account_mapping_entry(key, snapshot)
            validated[bound_key] = bound_snap
        self._snapshots = validated

    def load_account_snapshot(self, *, as_of: dt.datetime) -> AccountSnapshot:
        as_of_utc = _require_utc_datetime("as_of", as_of)
        # PIT and ranking both use snapshot.as_of (bound equal to mapping key at construct).
        candidates = [snap for snap in self._snapshots.values() if snap.as_of <= as_of_utc]
        if not candidates:
            if self._snapshots:
                raise RepositoryContractError(
                    "PIT_VIOLATION",
                    "all account snapshots are after requested as_of",
                )
            raise RepositoryContractError("MISSING_SNAPSHOT", "no account snapshot")
        chosen = max(candidates, key=lambda item: item.as_of)
        _pit_check(known_as_of=chosen.as_of, as_of=as_of_utc)
        return chosen


__all__ = [
    "AccountFactsReader",
    "CleanAccountFactsBundle",
    "CleanMarketFactsBundle",
    "InMemoryAccountSnapshotRepository",
    "InMemoryMarketDataRepository",
    "MarketFactsReader",
    "RepositoryContractError",
    "ValidatedCleanAccountSnapshotRepository",
    "ValidatedCleanMarketDataRepository",
    "reject_data_legacy_path",
]
