"""A-share corporate-action entitlement state machine for account replay."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import cast

import polars as pl

from quant.domain import CorporateActionLedgerSchema
from quant.domain.enums import EntitlementLegState, EntitlementPostingType

_CENT = Decimal("0.01")


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
            or (self.cash_per_share_gross == 0)
            != (self.cash_state is EntitlementLegState.NOT_APPLICABLE)
            or (self.stock_ratio == 0)
            != (self.stock_state is EntitlementLegState.NOT_APPLICABLE)
        ):
            raise ValueError("entitlement position invalid")


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


__all__ = [
    "EntitlementPosition",
    "EntitlementPosting",
    "EntitlementTransition",
    "capture_record_close_entitlements",
    "mark_full_day_event_from_factor",
    "recognize_ex_date_entitlements",
    "settle_due_entitlements",
]
