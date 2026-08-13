"""A-share corporate-action entitlement state machine for account replay."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import (
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Rounded,
)
from enum import Enum
import re
from typing import TYPE_CHECKING, Any, NoReturn, cast, final
import weakref

import polars as pl

from quant.domain import CorporateActionLedgerSchema
from quant.domain.enums import EntitlementLegState, EntitlementPostingType
from quant.backtest.a_share_execution import VerifiedAShareMarketFacts

_CENT = Decimal("0.01")
_FORMAL_ERROR = "M3_A_SHARE_ENTITLEMENT_INVALID"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_EXACT_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_EXACT_CONTEXT.traps[InvalidOperation] = True
_EXACT_CONTEXT.traps[Inexact] = True
_EXACT_CONTEXT.traps[Rounded] = True
_SETTLE_CONTEXT = Context(prec=50, rounding=ROUND_HALF_UP)
_SETTLE_CONTEXT.traps[InvalidOperation] = True
_PRE_RELOAD_STABLE_TYPES = tuple(
    globals().get(name)
    for name in (
        "AShareEntitlementError",
        "EntitlementReplayPhase",
        "EntitlementPosition",
        "EntitlementPosting",
        "EntitlementTransition",
    )
)


@dataclass(frozen=True)
class EntitlementPosition:
    event_id: str
    symbol: str
    record_date: dt.date
    ex_date: dt.date
    pay_date: dt.date | None
    stock_list_date: dt.date | None
    cash_settlement_session: dt.date | None
    stock_settlement_session: dt.date | None
    record_quantity: int
    cash_per_share_gross: Decimal
    stock_ratio: Decimal
    cash_entitlement_gross: Decimal
    stock_entitlement: int
    cash_state: EntitlementLegState
    stock_state: EntitlementLegState
    action_type: str = "DIVIDEND_DISTRIBUTION"

    def __post_init__(self) -> None:
        if (
            type(self.event_id) is not str
            or not self.event_id
            or type(self.symbol) is not str
            or not self.symbol.endswith((".SH", ".SZ"))
            or type(self.record_date) is not dt.date
            or type(self.ex_date) is not dt.date
            or self.record_date >= self.ex_date
            or type(self.record_quantity) is not int
            or self.record_quantity <= 0
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (
                    self.cash_per_share_gross,
                    self.stock_ratio,
                    self.cash_entitlement_gross,
                )
            )
            or type(self.stock_entitlement) is not int
            or self.stock_entitlement < 0
            or self.cash_state is EntitlementLegState.ABSENT
            or self.stock_state is EntitlementLegState.ABSENT
            or type(self.action_type) is not str
            or self.action_type not in {
                "DIVIDEND_DISTRIBUTION",
                "SHARE_CONSIDERATION",
            }
            or (self.cash_per_share_gross == 0)
            != (self.cash_state is EntitlementLegState.NOT_APPLICABLE)
            or (self.stock_ratio == 0)
            != (self.stock_state is EntitlementLegState.NOT_APPLICABLE)
        ):
            raise ValueError("entitlement position invalid")


class AShareEntitlementError(ValueError):
    """Stable formal A-share entitlement replay contract error."""


class EntitlementReplayPhase(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    RECORD_CLOSE = "RECORD_CLOSE"
    COMPLETE = "COMPLETE"


if TYPE_CHECKING:
    @final
    class AShareEntitlementReplayState:
        @property
        def input_market_facts_sha256(self) -> str: ...
        @property
        def next_session_index(self) -> int: ...
        @property
        def phase(self) -> EntitlementReplayPhase: ...
        @property
        def positions(self) -> tuple[EntitlementPosition, ...]: ...
        @property
        def processed_record_event_ids(self) -> tuple[str, ...]: ...
        @property
        def record_quantities(self) -> tuple[tuple[str, int], ...]: ...


    @final
    class AShareEntitlementReplayTransition:
        @property
        def replay(self) -> AShareEntitlementReplayState: ...
        @property
        def postings(self) -> tuple[EntitlementPosting, ...]: ...
        @property
        def cash_delta(self) -> Decimal: ...
        @property
        def settled_stock(self) -> tuple[tuple[str, int], ...]: ...


    def initialize_formal_a_share_entitlement_replay(
        *, facts: VerifiedAShareMarketFacts
    ) -> AShareEntitlementReplayState: ...


    def advance_formal_a_share_entitlements_pre_open(
        *, date: dt.date, replay: AShareEntitlementReplayState,
        facts: VerifiedAShareMarketFacts,
    ) -> AShareEntitlementReplayTransition: ...


    def capture_formal_a_share_entitlements_record_close(
        *, date: dt.date, replay: AShareEntitlementReplayState,
        total_quantities: Mapping[str, int], facts: VerifiedAShareMarketFacts,
    ) -> AShareEntitlementReplayTransition: ...


@dataclass(frozen=True)
class EntitlementPosting:
    date: dt.date
    event_id: str
    symbol: str
    posting_type: EntitlementPostingType
    cash_amount: Decimal
    stock_quantity: int
    cash_rounding_delta: Decimal
    cash_state_before: EntitlementLegState
    cash_state_after: EntitlementLegState
    stock_state_before: EntitlementLegState
    stock_state_after: EntitlementLegState

    def __post_init__(self) -> None:
        if (
            type(self.date) is not dt.date
            or type(self.event_id) is not str
            or not self.event_id
            or type(self.symbol) is not str
            or type(self.posting_type) is not EntitlementPostingType
            or any(
                type(value) is not Decimal or not value.is_finite()
                for value in (self.cash_amount, self.cash_rounding_delta)
            )
            or type(self.stock_quantity) is not int
            or self.stock_quantity < 0
        ):
            raise ValueError("entitlement posting invalid")


@dataclass(frozen=True)
class EntitlementTransition:
    positions: tuple[EntitlementPosition, ...]
    postings: tuple[EntitlementPosting, ...]
    cash_delta: Decimal
    settled_stock: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if (
            any(type(item) is not EntitlementPosition for item in self.positions)
            or any(type(item) is not EntitlementPosting for item in self.postings)
            or type(self.cash_delta) is not Decimal
            or not self.cash_delta.is_finite()
            or any(
                type(symbol) is not str or type(quantity) is not int or quantity <= 0
                for symbol, quantity in self.settled_stock
            )
        ):
            raise ValueError("entitlement transition invalid")


if all(item is not None for item in _PRE_RELOAD_STABLE_TYPES):
    for _stable_name, _stable_type in zip(
        (
            "AShareEntitlementError",
            "EntitlementReplayPhase",
            "EntitlementPosition",
            "EntitlementPosting",
            "EntitlementTransition",
        ),
        _PRE_RELOAD_STABLE_TYPES,
        strict=True,
    ):
        globals()[_stable_name] = _stable_type
del _PRE_RELOAD_STABLE_TYPES


def capture_record_close_entitlements(
    *,
    date: dt.date,
    positions: tuple[EntitlementPosition, ...],
    total_quantities: Mapping[str, int],
    corporate_actions: pl.DataFrame,
    sh_sessions: tuple[dt.date, ...],
    terminal_valuation_date: dt.date,
) -> tuple[EntitlementPosition, ...]:
    """Capture implemented events using record-close total quantities."""
    _validate_sessions(sh_sessions, terminal_valuation_date)
    _validate_positions(positions)
    try:
        ledger = CorporateActionLedgerSchema.validate(corporate_actions)
    except Exception:
        raise ValueError("corporate-action ledger invalid") from None
    for record_date, ex_date in ledger.select("record_date", "ex_date").iter_rows():
        if (
            record_date >= ex_date
            or record_date not in sh_sessions
            or ex_date not in sh_sessions
        ):
            raise ValueError("corporate-action event/date invalid")
    existing = {item.event_id for item in positions}
    captured = list(positions)
    rows = ledger.filter(pl.col("record_date") == date).sort("event_id")
    for row in rows.iter_rows(named=True):
        event_id = cast(str, row["event_id"])
        symbol = cast(str, row["symbol"])
        record_date = cast(dt.date, row["record_date"])
        ex_date = cast(dt.date, row["ex_date"])
        if (
            event_id in existing
        ):
            raise ValueError("corporate-action event/date invalid")
        quantity = total_quantities.get(symbol, 0)
        if type(quantity) is not int or quantity < 0:
            raise ValueError("record-close quantity invalid")
        if quantity == 0:
            continue
        cash = Decimal(str(row["cash_per_share_gross"]))
        stock = Decimal(str(row["stock_ratio"]))
        pay_date = cast(dt.date | None, row["pay_date"])
        stock_list_date = cast(dt.date | None, row["stock_list_date"])
        if (cash > 0 and pay_date is None) or (stock > 0 and stock_list_date is None):
            raise ValueError("entitlement due date missing")
        stock_exact = Decimal(quantity) * stock
        if stock_exact != stock_exact.to_integral_value():
            raise ValueError("stock entitlement is fractional")
        captured.append(
            EntitlementPosition(
                event_id=event_id,
                symbol=symbol,
                record_date=record_date,
                ex_date=ex_date,
                pay_date=pay_date,
                stock_list_date=stock_list_date,
                cash_settlement_session=_settlement_session(
                    pay_date, sh_sessions, terminal_valuation_date
                ),
                stock_settlement_session=_settlement_session(
                    stock_list_date, sh_sessions, terminal_valuation_date
                ),
                record_quantity=quantity,
                cash_per_share_gross=cash,
                stock_ratio=stock,
                cash_entitlement_gross=Decimal(quantity) * cash,
                stock_entitlement=int(stock_exact),
                cash_state=(
                    EntitlementLegState.CAPTURED
                    if cash > 0
                    else EntitlementLegState.NOT_APPLICABLE
                ),
                stock_state=(
                    EntitlementLegState.CAPTURED
                    if stock > 0
                    else EntitlementLegState.NOT_APPLICABLE
                ),
            )
        )
        existing.add(event_id)
    return tuple(sorted(captured, key=lambda item: item.event_id))


def recognize_ex_date_entitlements(
    *, date: dt.date, positions: tuple[EntitlementPosition, ...]
) -> EntitlementTransition:
    """Recognize each non-zero entitlement leg on its ex-date."""
    _validate_positions(positions)
    updated: list[EntitlementPosition] = []
    postings: list[EntitlementPosting] = []
    for original in sorted(positions, key=lambda item: item.event_id):
        position = original
        _reject_impossible_state_for_date(position, date)
        if position.ex_date == date and position.cash_state is EntitlementLegState.CAPTURED:
            after = replace(position, cash_state=EntitlementLegState.RECOGNIZED)
            postings.append(
                _posting(
                    date, position, after, EntitlementPostingType.CASH_RECOGNIZE
                )
            )
            position = after
        if position.ex_date == date and position.stock_state is EntitlementLegState.CAPTURED:
            after = replace(position, stock_state=EntitlementLegState.RECOGNIZED)
            postings.append(
                _posting(
                    date, position, after, EntitlementPostingType.STOCK_RECOGNIZE
                )
            )
            position = after
        updated.append(position)
    return EntitlementTransition(
        positions=tuple(updated),
        postings=tuple(postings),
        cash_delta=Decimal("0"),
        settled_stock=(),
    )


def settle_due_entitlements(
    *, date: dt.date, positions: tuple[EntitlementPosition, ...]
) -> EntitlementTransition:
    """Settle recognized cash and stock legs whose observed session is due."""
    _validate_positions(positions)
    updated: list[EntitlementPosition] = []
    postings: list[EntitlementPosting] = []
    cash_delta = Decimal("0")
    settled_stock: list[tuple[str, int]] = []
    for original in sorted(positions, key=lambda item: item.event_id):
        position = original
        for leg in ("cash", "stock"):
            state = position.cash_state if leg == "cash" else position.stock_state
            due = (
                position.cash_settlement_session
                if leg == "cash"
                else position.stock_settlement_session
            )
            if due is None or due > date or state is EntitlementLegState.NOT_APPLICABLE:
                continue
            if state is EntitlementLegState.CAPTURED:
                raise ValueError("entitlement settlement before recognition")
            if state is EntitlementLegState.SETTLED:
                continue
            if state is not EntitlementLegState.RECOGNIZED:
                raise ValueError("entitlement settlement state invalid")
            if leg == "cash":
                amount = position.cash_entitlement_gross.quantize(
                    _CENT, rounding=ROUND_HALF_UP
                )
                after = replace(position, cash_state=EntitlementLegState.SETTLED)
                postings.append(
                    _posting(
                        date,
                        position,
                        after,
                        EntitlementPostingType.CASH_SETTLE,
                        cash_amount=amount,
                        cash_rounding_delta=amount - position.cash_entitlement_gross,
                    )
                )
                cash_delta += amount
            else:
                after = replace(position, stock_state=EntitlementLegState.SETTLED)
                postings.append(
                    _posting(
                        date,
                        position,
                        after,
                        EntitlementPostingType.STOCK_SETTLE,
                        stock_quantity=position.stock_entitlement,
                    )
                )
                settled_stock.append((position.symbol, position.stock_entitlement))
            position = after
        updated.append(position)
    return EntitlementTransition(
        positions=tuple(updated),
        postings=tuple(postings),
        cash_delta=cash_delta,
        settled_stock=tuple(settled_stock),
    )


def mark_full_day_event_from_factor(
    *, previous_mark: Decimal, actual_factor_ratio: Decimal
) -> Decimal:
    """Adjust a FULL_DAY event mark from verified positive factor evidence."""
    if (
        type(previous_mark) is not Decimal
        or type(actual_factor_ratio) is not Decimal
        or not previous_mark.is_finite()
        or not actual_factor_ratio.is_finite()
        or previous_mark <= 0
        or actual_factor_ratio <= 0
    ):
        raise ValueError("factor mark inputs invalid")
    return previous_mark / actual_factor_ratio


def _posting(
    date: dt.date,
    before: EntitlementPosition,
    after: EntitlementPosition,
    kind: EntitlementPostingType,
    *,
    cash_amount: Decimal = Decimal("0"),
    stock_quantity: int = 0,
    cash_rounding_delta: Decimal = Decimal("0"),
) -> EntitlementPosting:
    return EntitlementPosting(
        date=date,
        event_id=before.event_id,
        symbol=before.symbol,
        posting_type=kind,
        cash_amount=cash_amount,
        stock_quantity=stock_quantity,
        cash_rounding_delta=cash_rounding_delta,
        cash_state_before=before.cash_state,
        cash_state_after=after.cash_state,
        stock_state_before=before.stock_state,
        stock_state_after=after.stock_state,
    )


def _validate_sessions(
    sessions: tuple[dt.date, ...], terminal_valuation_date: dt.date
) -> None:
    if (
        not sessions
        or any(type(day) is not dt.date for day in sessions)
        or tuple(sorted(set(sessions))) != sessions
        or terminal_valuation_date not in sessions
    ):
        raise ValueError("SH session domain invalid")


def _settlement_session(
    due_date: dt.date | None,
    sessions: tuple[dt.date, ...],
    terminal_valuation_date: dt.date,
) -> dt.date | None:
    if due_date is None:
        return None
    return next(
        (
            session
            for session in sessions
            if session >= due_date and session <= terminal_valuation_date
        ),
        None,
    )


def _validate_positions(positions: tuple[EntitlementPosition, ...]) -> None:
    if (
        type(positions) is not tuple
        or any(type(item) is not EntitlementPosition for item in positions)
        or len({item.event_id for item in positions}) != len(positions)
    ):
        raise ValueError("entitlement positions invalid")


def _reject_impossible_state_for_date(
    position: EntitlementPosition, date: dt.date
) -> None:
    for state, due in (
        (position.cash_state, position.cash_settlement_session),
        (position.stock_state, position.stock_settlement_session),
    ):
        if state is EntitlementLegState.SETTLED and (due is None or due > date):
            raise ValueError("entitlement state skipped")


@dataclass(frozen=True)
class _FormalDomain:
    identity: str
    sessions: tuple[dt.date, ...]
    open_sessions: tuple[dt.date, ...]
    terminal: dt.date
    symbols: frozenset[str]
    rows: tuple[dict[str, object], ...]


def _initialize_formal_entitlement_capability() -> tuple[type[Any], type[Any], Any, Any, Any]:
    signing_key = secrets.token_bytes(32)
    issued_states: weakref.WeakSet[Any] = weakref.WeakSet()
    issued_transitions: weakref.WeakSet[Any] = weakref.WeakSet()

    def reject() -> NoReturn:
        raise AShareEntitlementError(_FORMAL_ERROR) from None

    def state_payload(instance: Any) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(instance, slot)
            for slot in (
                "_input_market_facts_sha256", "_next_session_index", "_phase",
                "_positions", "_processed_record_event_ids", "_record_quantities",
            )
        )

    def verify_state(instance: Any) -> bytes:
        try:
            module = sys.modules.get(__name__)
            if (
                module is None
                or getattr(module, "AShareEntitlementReplayState", None) is not _State
                or type(instance) is not _State
                or instance not in issued_states
            ):
                raise ValueError
            payload = state_payload(instance)
            nonce = object.__getattribute__(instance, "_nonce")
            attestation = object.__getattribute__(instance, "_attestation")
            if (
                type(nonce) is not bytes or len(nonce) != 16
                or type(attestation) is not bytes
                or len(attestation) != hashlib.sha256().digest_size
            ):
                raise ValueError
            expected = hmac.digest(
                signing_key,
                repr((payload, nonce, id(instance))).encode("utf-8"),
                "sha256",
            )
            if not hmac.compare_digest(attestation, expected):
                raise ValueError
            return attestation
        except Exception:
            pass
        reject()

    def consume_state(instance: Any, slot: str) -> Any:
        try:
            verify_state(instance)
            return object.__getattribute__(instance, slot)
        except Exception:
            pass
        reject()

    @final
    class _State:
        __slots__ = (
            "_input_market_facts_sha256", "_next_session_index", "_phase",
            "_positions", "_processed_record_event_ids", "_record_quantities",
            "_nonce", "_attestation", "__weakref__",
        )

        def __new__(cls, *args: object, **kwargs: object) -> Any:
            reject()

        def __init__(self, *args: object, **kwargs: object) -> None:
            reject()

        @property
        def input_market_facts_sha256(self) -> str:
            return cast(str, consume_state(self, "_input_market_facts_sha256"))

        @property
        def next_session_index(self) -> int:
            return cast(int, consume_state(self, "_next_session_index"))

        @property
        def phase(self) -> EntitlementReplayPhase:
            return cast(EntitlementReplayPhase, consume_state(self, "_phase"))

        @property
        def positions(self) -> tuple[EntitlementPosition, ...]:
            return cast(tuple[EntitlementPosition, ...], consume_state(self, "_positions"))

        @property
        def processed_record_event_ids(self) -> tuple[str, ...]:
            return cast(tuple[str, ...], consume_state(self, "_processed_record_event_ids"))

        @property
        def record_quantities(self) -> tuple[tuple[str, int], ...]:
            return cast(tuple[tuple[str, int], ...], consume_state(self, "_record_quantities"))

        def __reduce__(self) -> Any:
            reject()

        def __repr__(self) -> str:
            try:
                values = state_payload(self)
                verify_state(self)
                return (
                    "AShareEntitlementReplayState(phase="
                    f"{cast(EntitlementReplayPhase, values[2]).value!r}, "
                    f"next_session_index={values[1]!r})"
                )
            except Exception:
                pass
            reject()

    def transition_payload(instance: Any) -> tuple[object, ...]:
        return tuple(
            object.__getattribute__(instance, slot)
            for slot in (
                "_input_state_attestation", "_operation", "_date", "_facts_identity",
                "_quantity_inputs", "_replay", "_postings", "_cash_delta",
                "_settled_stock",
            )
        )

    def verify_transition(instance: Any) -> None:
        try:
            module = sys.modules.get(__name__)
            if (
                module is None
                or getattr(module, "AShareEntitlementReplayTransition", None)
                is not _Transition
                or type(instance) is not _Transition
                or instance not in issued_transitions
            ):
                raise ValueError
            payload = transition_payload(instance)
            replay = payload[5]
            input_proof = payload[0]
            if (
                type(input_proof) is not bytes
                or len(input_proof) != hashlib.sha256().digest_size
                or type(payload[1]) is not str
                or payload[1] not in {"INITIALIZE", "ADVANCE", "CAPTURE"}
                or type(payload[2]) is not dt.date
                or type(payload[3]) is not str
                or type(payload[4]) is not tuple
                or type(replay) is not _State
                or type(payload[6]) is not tuple
                or any(type(item) is not EntitlementPosting for item in cast(tuple[Any, ...], payload[6]))
                or type(payload[7]) is not Decimal
                or type(payload[8]) is not tuple
            ):
                raise ValueError
            verify_state(replay)
            nonce = object.__getattribute__(instance, "_nonce")
            attestation = object.__getattribute__(instance, "_attestation")
            expected = hmac.digest(
                signing_key,
                repr((payload, nonce, id(instance))).encode("utf-8"),
                "sha256",
            )
            if (
                type(nonce) is not bytes or len(nonce) != 16
                or type(attestation) is not bytes
                or not hmac.compare_digest(attestation, expected)
            ):
                raise ValueError
        except Exception:
            pass
        else:
            return
        reject()

    def consume_transition(instance: Any, slot: str) -> Any:
        try:
            verify_transition(instance)
            return object.__getattribute__(instance, slot)
        except Exception:
            pass
        reject()

    @final
    class _Transition:
        __slots__ = (
            "_input_state_attestation", "_operation", "_date", "_facts_identity",
            "_quantity_inputs", "_replay", "_postings", "_cash_delta",
            "_settled_stock", "_nonce", "_attestation", "__weakref__",
        )

        def __new__(cls, *args: object, **kwargs: object) -> Any:
            reject()

        def __init__(self, *args: object, **kwargs: object) -> None:
            reject()

        @property
        def replay(self) -> Any:
            return consume_transition(self, "_replay")

        @property
        def postings(self) -> tuple[EntitlementPosting, ...]:
            return cast(tuple[EntitlementPosting, ...], consume_transition(self, "_postings"))

        @property
        def cash_delta(self) -> Decimal:
            return cast(Decimal, consume_transition(self, "_cash_delta"))

        @property
        def settled_stock(self) -> tuple[tuple[str, int], ...]:
            return cast(tuple[tuple[str, int], ...], consume_transition(self, "_settled_stock"))

        def __reduce__(self) -> Any:
            reject()

        def __repr__(self) -> str:
            try:
                payload = transition_payload(self)
                verify_transition(self)
                return (
                    "AShareEntitlementReplayTransition(operation="
                    f"{payload[1]!r}, postings={len(cast(tuple[Any, ...], payload[6]))})"
                )
            except Exception:
                pass
            reject()

    def initialize(*, facts: VerifiedAShareMarketFacts) -> Any:
        try:
            domain = _formal_domain(facts)
            prior = tuple(sorted(
                (cast(str, row["event_id"]), 0)
                for row in domain.rows
                if cast(dt.date, row["record_date"]) < domain.sessions[0]
            ))
            values: tuple[object, ...] = (
                domain.identity, 0, EntitlementReplayPhase.PRE_OPEN, (),
                tuple(event_id for event_id, _ in prior), prior,
            )
            _validate_formal_replay_values(values, domain)
            instance = object.__new__(_State)
            nonce = secrets.token_bytes(16)
            attestation = hmac.digest(
                signing_key,
                repr((values, nonce, id(instance))).encode("utf-8"),
                "sha256",
            )
            for slot, value in zip(
                (
                    "_input_market_facts_sha256", "_next_session_index", "_phase",
                    "_positions", "_processed_record_event_ids", "_record_quantities",
                ),
                values,
                strict=True,
            ):
                object.__setattr__(instance, slot, value)
            object.__setattr__(instance, "_nonce", nonce)
            object.__setattr__(instance, "_attestation", attestation)
            issued_states.add(instance)
            verify_state(instance)
            return instance
        except Exception:
            pass
        reject()

    def advance(*, date: dt.date, replay: Any, facts: VerifiedAShareMarketFacts) -> Any:
        try:
            input_values = state_payload(replay)
            verify_state(replay)
            domain = _formal_domain(facts)
            _validate_formal_replay_values(input_values, domain)
            index = cast(int, input_values[1])
            if (
                type(date) is not dt.date
                or input_values[2] is not EntitlementReplayPhase.PRE_OPEN
                or index >= len(domain.sessions)
                or date != domain.sessions[index]
            ):
                raise ValueError
            positions = list(cast(tuple[EntitlementPosition, ...], input_values[3]))
            postings: list[EntitlementPosting] = []
            for offset, original in enumerate(tuple(positions)):
                position = original
                if position.ex_date == date:
                    if position.cash_state is EntitlementLegState.CAPTURED:
                        after = replace(position, cash_state=EntitlementLegState.RECOGNIZED)
                        postings.append(_posting(date, position, after, EntitlementPostingType.CASH_RECOGNIZE))
                        position = after
                    if position.stock_state is EntitlementLegState.CAPTURED:
                        after = replace(position, stock_state=EntitlementLegState.RECOGNIZED)
                        postings.append(_posting(date, position, after, EntitlementPostingType.STOCK_RECOGNIZE))
                        position = after
                positions[offset] = position
            cash_delta = Decimal(0)
            settled_stock: list[tuple[str, int]] = []
            for offset, original in enumerate(tuple(positions)):
                position = original
                if position.cash_state is EntitlementLegState.RECOGNIZED and position.cash_settlement_session == date:
                    amount = _SETTLE_CONTEXT.quantize(position.cash_entitlement_gross, _CENT)
                    after = replace(position, cash_state=EntitlementLegState.SETTLED)
                    postings.append(_posting(
                        date, position, after, EntitlementPostingType.CASH_SETTLE,
                        cash_amount=amount,
                        cash_rounding_delta=_EXACT_CONTEXT.subtract(amount, position.cash_entitlement_gross),
                    ))
                    cash_delta = _EXACT_CONTEXT.add(cash_delta, amount)
                    position = after
                if position.stock_state is EntitlementLegState.RECOGNIZED and position.stock_settlement_session == date:
                    after = replace(position, stock_state=EntitlementLegState.SETTLED)
                    postings.append(_posting(
                        date, position, after, EntitlementPostingType.STOCK_SETTLE,
                        stock_quantity=position.stock_entitlement,
                    ))
                    settled_stock.append((position.symbol, position.stock_entitlement))
                    position = after
                positions[offset] = position
            output_values: tuple[object, ...] = (
                input_values[0], index, EntitlementReplayPhase.RECORD_CLOSE,
                tuple(positions), input_values[4], input_values[5],
            )
            _validate_formal_replay_values(output_values, domain)
            output = object.__new__(_State)
            state_nonce = secrets.token_bytes(16)
            state_attestation = hmac.digest(
                signing_key,
                repr((output_values, state_nonce, id(output))).encode("utf-8"),
                "sha256",
            )
            for slot, value in zip(
                (
                    "_input_market_facts_sha256", "_next_session_index", "_phase",
                    "_positions", "_processed_record_event_ids", "_record_quantities",
                ),
                output_values,
                strict=True,
            ):
                object.__setattr__(output, slot, value)
            object.__setattr__(output, "_nonce", state_nonce)
            object.__setattr__(output, "_attestation", state_attestation)
            issued_states.add(output)
            verify_state(output)
            payload: tuple[object, ...] = (
                verify_state(replay), "ADVANCE", date, domain.identity, (), output,
                tuple(postings), cash_delta, tuple(settled_stock),
            )
            transition = object.__new__(_Transition)
            transition_nonce = secrets.token_bytes(16)
            transition_attestation = hmac.digest(
                signing_key,
                repr((payload, transition_nonce, id(transition))).encode("utf-8"),
                "sha256",
            )
            for slot, value in zip(
                (
                    "_input_state_attestation", "_operation", "_date",
                    "_facts_identity", "_quantity_inputs", "_replay", "_postings",
                    "_cash_delta", "_settled_stock",
                ),
                payload,
                strict=True,
            ):
                object.__setattr__(transition, slot, value)
            object.__setattr__(transition, "_nonce", transition_nonce)
            object.__setattr__(transition, "_attestation", transition_attestation)
            issued_transitions.add(transition)
            verify_transition(transition)
            return transition
        except Exception:
            pass
        reject()

    def capture(
        *, date: dt.date, replay: Any, total_quantities: Mapping[str, int],
        facts: VerifiedAShareMarketFacts,
    ) -> Any:
        try:
            input_values = state_payload(replay)
            verify_state(replay)
            domain = _formal_domain(facts)
            _validate_formal_replay_values(input_values, domain)
            index = cast(int, input_values[1])
            if (
                type(date) is not dt.date
                or input_values[2] is not EntitlementReplayPhase.RECORD_CLOSE
                or index >= len(domain.sessions)
                or date != domain.sessions[index]
                or not isinstance(total_quantities, Mapping)
            ):
                raise ValueError
            supplied: dict[str, int] = {}
            for symbol, quantity in total_quantities.items():
                if (
                    type(symbol) is not str or symbol not in domain.symbols
                    or type(quantity) is not int or quantity < 0 or symbol in supplied
                ):
                    raise ValueError
                supplied[symbol] = quantity
            quantity_inputs = tuple(sorted(supplied.items()))
            today = tuple(
                row for row in domain.rows
                if cast(dt.date, row["record_date"]) == date
            )
            additions = tuple(
                (cast(str, row["event_id"]), supplied.get(cast(str, row["symbol"]), 0))
                for row in today
            )
            if any(
                cast(str, row["action_type"]) == "RIGHTS" and quantity > 0
                for row, (_, quantity) in zip(today, additions, strict=True)
            ):
                raise ValueError
            quantities = tuple(sorted(cast(tuple[tuple[str, int], ...], input_values[5]) + additions))
            next_index = index + 1
            phase = (
                EntitlementReplayPhase.COMPLETE
                if next_index == len(domain.sessions)
                else EntitlementReplayPhase.PRE_OPEN
            )
            positions = _expected_positions(
                quantities, domain, next_index=next_index, phase=phase
            )
            output_values: tuple[object, ...] = (
                input_values[0], next_index, phase, positions,
                tuple(event_id for event_id, _ in quantities), quantities,
            )
            _validate_formal_replay_values(output_values, domain)
            old_ids = set(cast(tuple[str, ...], input_values[4]))
            postings = tuple(
                EntitlementPosting(
                    date=date, event_id=position.event_id, symbol=position.symbol,
                    posting_type=EntitlementPostingType.CAPTURE,
                    cash_amount=Decimal(0), stock_quantity=0,
                    cash_rounding_delta=Decimal(0),
                    cash_state_before=(EntitlementLegState.ABSENT if position.cash_per_share_gross > 0 else EntitlementLegState.NOT_APPLICABLE),
                    cash_state_after=position.cash_state,
                    stock_state_before=(EntitlementLegState.ABSENT if position.stock_ratio > 0 else EntitlementLegState.NOT_APPLICABLE),
                    stock_state_after=position.stock_state,
                )
                for position in positions if position.event_id not in old_ids
            )
            output = object.__new__(_State)
            state_nonce = secrets.token_bytes(16)
            state_attestation = hmac.digest(
                signing_key,
                repr((output_values, state_nonce, id(output))).encode("utf-8"),
                "sha256",
            )
            for slot, value in zip(
                (
                    "_input_market_facts_sha256", "_next_session_index", "_phase",
                    "_positions", "_processed_record_event_ids", "_record_quantities",
                ),
                output_values,
                strict=True,
            ):
                object.__setattr__(output, slot, value)
            object.__setattr__(output, "_nonce", state_nonce)
            object.__setattr__(output, "_attestation", state_attestation)
            issued_states.add(output)
            verify_state(output)
            payload: tuple[object, ...] = (
                verify_state(replay), "CAPTURE", date, domain.identity,
                quantity_inputs, output, postings, Decimal(0), (),
            )
            transition = object.__new__(_Transition)
            transition_nonce = secrets.token_bytes(16)
            transition_attestation = hmac.digest(
                signing_key,
                repr((payload, transition_nonce, id(transition))).encode("utf-8"),
                "sha256",
            )
            for slot, value in zip(
                (
                    "_input_state_attestation", "_operation", "_date",
                    "_facts_identity", "_quantity_inputs", "_replay", "_postings",
                    "_cash_delta", "_settled_stock",
                ),
                payload,
                strict=True,
            ):
                object.__setattr__(transition, slot, value)
            object.__setattr__(transition, "_nonce", transition_nonce)
            object.__setattr__(transition, "_attestation", transition_attestation)
            issued_transitions.add(transition)
            verify_transition(transition)
            return transition
        except Exception:
            pass
        reject()

    _State.__name__ = "AShareEntitlementReplayState"
    _State.__qualname__ = "AShareEntitlementReplayState"
    _State.__module__ = __name__
    _Transition.__name__ = "AShareEntitlementReplayTransition"
    _Transition.__qualname__ = "AShareEntitlementReplayTransition"
    _Transition.__module__ = __name__
    initialize.__name__ = "initialize_formal_a_share_entitlement_replay"
    advance.__name__ = "advance_formal_a_share_entitlements_pre_open"
    capture.__name__ = "capture_formal_a_share_entitlements_record_close"
    return _State, _Transition, initialize, advance, capture


if not TYPE_CHECKING:
    (
        AShareEntitlementReplayState,
        AShareEntitlementReplayTransition,
        initialize_formal_a_share_entitlement_replay,
        advance_formal_a_share_entitlements_pre_open,
        capture_formal_a_share_entitlements_record_close,
    ) = _initialize_formal_entitlement_capability()
    del _initialize_formal_entitlement_capability


def _formal_domain(facts: VerifiedAShareMarketFacts) -> _FormalDomain:
    if type(facts) is not VerifiedAShareMarketFacts:
        raise ValueError
    identity = facts.identity
    calendar = facts.calendar
    ledger = facts.corporate_actions
    benchmark = facts.benchmark_bars
    instruments = facts.instruments
    digest = identity.input_market_facts_sha256
    if type(digest) is not str or _HEX64.fullmatch(digest) is None:
        raise ValueError
    sessions = tuple(benchmark.get_column("trade_date").to_list())
    if (
        not sessions
        or any(type(day) is not dt.date for day in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise ValueError
    open_sessions = tuple(
        calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .get_column("date")
        .to_list()
    )
    if (
        any(type(day) is not dt.date for day in open_sessions)
        or open_sessions != tuple(sorted(set(open_sessions)))
        or not set(sessions) <= set(open_sessions)
    ):
        raise ValueError
    symbols = frozenset(instruments.get_column("symbol").to_list())
    if not symbols or any(type(symbol) is not str for symbol in symbols):
        raise ValueError
    rows = tuple(ledger.iter_rows(named=True))
    event_ids = tuple(cast(str, row["event_id"]) for row in rows)
    if (
        any(_HEX64.fullmatch(event_id) is None for event_id in event_ids)
        or len(set(event_ids)) != len(event_ids)
    ):
        raise ValueError
    rows = tuple(sorted(rows, key=lambda row: cast(str, row["event_id"])))
    domain = _FormalDomain(
        identity=digest,
        sessions=sessions,
        open_sessions=open_sessions,
        terminal=sessions[-1],
        symbols=symbols,
        rows=rows,
    )
    for row in rows:
        _validated_event_values(row, domain)
    return domain


def _validated_event_values(
    row: dict[str, object], domain: _FormalDomain
) -> tuple[str, str, str, dt.date, dt.date, Decimal, Decimal, dt.date | None, dt.date | None]:
    event_id = cast(str, row["event_id"])
    symbol = cast(str, row["symbol"])
    action = cast(str, row["action_type"])
    record_date = cast(dt.date, row["record_date"])
    ex_date = cast(dt.date, row["ex_date"])
    pay_date = cast(dt.date | None, row["pay_date"])
    stock_list_date = cast(dt.date | None, row["stock_list_date"])
    cash = Decimal(str(row["cash_per_share_gross"]))
    stock = Decimal(str(row["stock_ratio"]))
    open_set = set(domain.open_sessions)
    if (
        type(event_id) is not str
        or _HEX64.fullmatch(event_id) is None
        or type(symbol) is not str
        or symbol not in domain.symbols
        or action not in {"DIVIDEND_DISTRIBUTION", "RIGHTS", "SHARE_CONSIDERATION"}
        or type(record_date) is not dt.date
        or type(ex_date) is not dt.date
        or record_date >= ex_date
        or record_date not in open_set
        or ex_date not in open_set
        or not cash.is_finite()
        or not stock.is_finite()
        or cash < 0
        or stock < 0
        or (
            action == "DIVIDEND_DISTRIBUTION"
            and (
                (cash > 0) != (type(pay_date) is dt.date)
                or (stock > 0) != (type(stock_list_date) is dt.date)
                or (type(pay_date) is dt.date and pay_date < ex_date)
                or (
                    type(stock_list_date) is dt.date
                    and stock_list_date < ex_date
                )
            )
        )
        or (
            action == "RIGHTS"
            and (
                cash != 0
                or stock != 0
                or pay_date is not None
                or type(stock_list_date) is not dt.date
                or stock_list_date < ex_date
            )
        )
        or (action == "SHARE_CONSIDERATION" and (cash != 0 or stock <= 0 or stock_list_date != ex_date))
        or (action == "DIVIDEND_DISTRIBUTION" and cash == 0 and stock == 0)
    ):
        raise ValueError
    return (
        event_id, symbol, action, record_date, ex_date, cash, stock,
        pay_date, stock_list_date,
    )


def _expected_positions(
    quantities: tuple[tuple[str, int], ...],
    domain: _FormalDomain,
    *,
    next_index: int,
    phase: EntitlementReplayPhase,
) -> tuple[EntitlementPosition, ...]:
    rows = {cast(str, row["event_id"]): row for row in domain.rows}
    pre_open_through: dt.date | None
    if phase is EntitlementReplayPhase.COMPLETE:
        pre_open_through = domain.terminal
    elif phase is EntitlementReplayPhase.RECORD_CLOSE:
        pre_open_through = domain.sessions[next_index]
    else:
        pre_open_through = (
            domain.sessions[next_index - 1] if next_index > 0 else None
        )
    positions: list[EntitlementPosition] = []
    for event_id, quantity in quantities:
        row = rows[event_id]
        (
            _, symbol, action, record_date, ex_date, cash, stock,
            pay_date, stock_list_date,
        ) = _validated_event_values(row, domain)
        if quantity == 0 or action == "RIGHTS":
            continue
        cash_product = _EXACT_CONTEXT.multiply(Decimal(quantity), cash)
        stock_product = _EXACT_CONTEXT.multiply(Decimal(quantity), stock)
        if stock_product != stock_product.to_integral_value():
            raise ValueError
        cash_due = _formal_settlement_session(pay_date, domain)
        stock_due = _formal_settlement_session(stock_list_date, domain)
        positions.append(
            EntitlementPosition(
                event_id=event_id,
                symbol=symbol,
                record_date=record_date,
                ex_date=ex_date,
                pay_date=pay_date,
                stock_list_date=stock_list_date,
                cash_settlement_session=cash_due,
                stock_settlement_session=stock_due,
                record_quantity=quantity,
                cash_per_share_gross=cash,
                stock_ratio=stock,
                cash_entitlement_gross=cash_product,
                stock_entitlement=int(stock_product),
                cash_state=_expected_leg_state(cash, ex_date, cash_due, pre_open_through),
                stock_state=_expected_leg_state(stock, ex_date, stock_due, pre_open_through),
                action_type=action,
            )
        )
    return tuple(positions)


def _expected_leg_state(
    value: Decimal,
    ex_date: dt.date,
    settlement: dt.date | None,
    pre_open_through: dt.date | None,
) -> EntitlementLegState:
    if value == 0:
        return EntitlementLegState.NOT_APPLICABLE
    if pre_open_through is None or ex_date > pre_open_through:
        return EntitlementLegState.CAPTURED
    if settlement is not None and settlement <= pre_open_through:
        return EntitlementLegState.SETTLED
    return EntitlementLegState.RECOGNIZED


def _formal_settlement_session(
    due_date: dt.date | None, domain: _FormalDomain
) -> dt.date | None:
    if due_date is None:
        return None
    return next(
        (day for day in domain.open_sessions if due_date <= day <= domain.terminal),
        None,
    )


def _validate_formal_replay_values(
    values: tuple[object, ...], domain: _FormalDomain
) -> None:
    if (
        type(values) is not tuple
        or len(values) != 6
        or values[0] != domain.identity
        or type(values[1]) is not int
        or cast(int, values[1]) < 0
        or cast(int, values[1]) > len(domain.sessions)
        or type(values[2]) is not EntitlementReplayPhase
        or type(values[3]) is not tuple
        or any(type(item) is not EntitlementPosition for item in cast(tuple[Any, ...], values[3]))
        or type(values[4]) is not tuple
        or type(values[5]) is not tuple
    ):
        raise ValueError
    index = cast(int, values[1])
    phase = cast(EntitlementReplayPhase, values[2])
    positions = cast(tuple[EntitlementPosition, ...], values[3])
    processed = cast(tuple[str, ...], values[4])
    quantities = cast(tuple[tuple[str, int], ...], values[5])
    if phase is EntitlementReplayPhase.COMPLETE:
        if index != len(domain.sessions):
            raise ValueError
        record_cutoff = domain.terminal
    else:
        if index >= len(domain.sessions):
            raise ValueError
        record_cutoff = domain.sessions[index]
    expected_ids = tuple(
        cast(str, row["event_id"])
        for row in domain.rows
        if cast(dt.date, row["record_date"]) < record_cutoff
        or (
            phase is EntitlementReplayPhase.COMPLETE
            and cast(dt.date, row["record_date"]) == record_cutoff
        )
    )
    if (
        processed != expected_ids
        or tuple(event_id for event_id, _ in quantities) != expected_ids
        or quantities != tuple(sorted(quantities))
        or any(
            type(event_id) is not str
            or type(quantity) is not int
            or quantity < 0
            for event_id, quantity in quantities
        )
        or positions
        != _expected_positions(
            quantities, domain, next_index=index, phase=phase,
        )
    ):
        raise ValueError


__all__ = [
    "AShareEntitlementError",
    "AShareEntitlementReplayState",
    "AShareEntitlementReplayTransition",
    "EntitlementPosition",
    "EntitlementPosting",
    "EntitlementReplayPhase",
    "EntitlementTransition",
    "advance_formal_a_share_entitlements_pre_open",
    "capture_formal_a_share_entitlements_record_close",
    "capture_record_close_entitlements",
    "initialize_formal_a_share_entitlement_replay",
    "mark_full_day_event_from_factor",
    "recognize_ex_date_entitlements",
    "settle_due_entitlements",
]
