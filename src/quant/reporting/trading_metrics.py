"""Deterministic execution and ledger-book metrics for M4 B6 results.

This module deliberately does not reconstruct fills, fees, settlement, FX, or
market valuation.  It consumes the public ``VerifiedSimulationResult`` shape
and reports only evidence present in that result.  Consequently the value
curve is a per-currency ledger book curve, not a mark-to-market NAV curve.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import NoReturn, cast

from quant.backtest.event_simulator import (
    VerifiedScenarioResult,
    VerifiedSimulationResult,
    verify_simulation_result_identity,
)
from quant.backtest.ledger import LedgerState
from quant.domain.enums import Currency, ExecutionEventType

_ERROR = "TRADING_METRICS_INPUT_INVALID"
_HEX = frozenset("0123456789abcdef")
_FILL_TYPES = frozenset({ExecutionEventType.PARTIAL_FILL, ExecutionEventType.FILL})


class TradingMetricsError(ValueError):
    """Stable failure raised for an invalid or insufficient B6 result."""


def _fail() -> NoReturn:
    raise TradingMetricsError(_ERROR)


def _is_hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX


def _finite(value: Decimal | None) -> bool:
    return value is None or (type(value) is Decimal and value.is_finite())


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        _fail()
    if value == 0:
        return "0"
    sign, raw_digits, raw_exponent = value.as_tuple()
    exponent = cast(int, raw_exponent)
    digits = list(raw_digits)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    point = len(coefficient) + exponent
    if point <= 0:
        text = "0." + "0" * (-point) + coefficient
    elif point < len(coefficient):
        text = coefficient[:point] + "." + coefficient[point:]
    else:
        text = coefficient + "0" * exponent
    return "-" + text if sign else text


@dataclass(frozen=True, slots=True)
class CurrencyTradingMetrics:
    """Metrics whose arithmetic is valid only within one currency."""

    currency: Currency
    opening_book_value: Decimal
    closing_book_value: Decimal
    book_return: Decimal | None
    maximum_book_drawdown: Decimal | None
    annualized_book_volatility: Decimal | None
    gross_traded_notional: Decimal
    total_fees: Decimal

    def __post_init__(self) -> None:
        values = (
            self.opening_book_value,
            self.closing_book_value,
            self.book_return,
            self.maximum_book_drawdown,
            self.annualized_book_volatility,
            self.gross_traded_notional,
            self.total_fees,
        )
        if (
            type(self.currency) is not Currency
            or any(not _finite(value) for value in values)
            or self.maximum_book_drawdown is not None
            and self.maximum_book_drawdown < 0
            or self.annualized_book_volatility is not None
            and self.annualized_book_volatility < 0
            or self.gross_traded_notional < 0
            or self.total_fees < 0
        ):
            _fail()


@dataclass(frozen=True, slots=True)
class ScenarioTradingMetrics:
    """Execution quality and per-currency ledger metrics for one scenario."""

    scenario_id: str
    scenario_result_id: str
    command_count: int
    fill_event_count: int
    partial_fill_event_count: int
    requested_quantity: int
    filled_quantity: int
    fill_ratio: Decimal | None
    currencies: tuple[CurrencyTradingMetrics, ...]

    def __post_init__(self) -> None:
        counts = (
            self.command_count,
            self.fill_event_count,
            self.partial_fill_event_count,
            self.requested_quantity,
            self.filled_quantity,
        )
        if (
            type(self.scenario_id) is not str
            or not self.scenario_id
            or not _is_hex64(self.scenario_result_id)
            or any(type(value) is not int or value < 0 for value in counts)
            or self.partial_fill_event_count > self.fill_event_count
            or self.filled_quantity > self.requested_quantity
            or not _finite(self.fill_ratio)
            or self.fill_ratio is not None
            and not Decimal(0) <= self.fill_ratio <= Decimal(1)
            or type(self.currencies) is not tuple
            or any(type(item) is not CurrencyTradingMetrics for item in self.currencies)
            or self.currencies
            != tuple(sorted(self.currencies, key=lambda item: item.currency.value))
            or len({item.currency for item in self.currencies}) != len(self.currencies)
        ):
            _fail()


@dataclass(frozen=True, slots=True)
class TradingMetrics:
    """Identity-bound B7 metrics for an entire B6 simulation result."""

    metrics_id: str
    simulation_result_id: str
    annualization_sessions: int
    scenarios: tuple[ScenarioTradingMetrics, ...]

    def __post_init__(self) -> None:
        if (
            not _is_hex64(self.metrics_id)
            or not _is_hex64(self.simulation_result_id)
            or type(self.annualization_sessions) is not int
            or self.annualization_sessions <= 0
            or type(self.scenarios) is not tuple
            or not self.scenarios
            or any(type(item) is not ScenarioTradingMetrics for item in self.scenarios)
            or self.scenarios != tuple(sorted(self.scenarios, key=lambda item: item.scenario_id))
            or len({item.scenario_id for item in self.scenarios}) != len(self.scenarios)
            or self.metrics_id != _metrics_identity(
                self.simulation_result_id, self.annualization_sessions, self.scenarios
            )
        ):
            _fail()


def _currency_payload(item: CurrencyTradingMetrics) -> dict[str, object]:
    return {
        "currency": item.currency.value,
        "opening_book_value": _decimal_text(item.opening_book_value),
        "closing_book_value": _decimal_text(item.closing_book_value),
        "book_return": _decimal_text(item.book_return),
        "maximum_book_drawdown": _decimal_text(item.maximum_book_drawdown),
        "annualized_book_volatility": _decimal_text(item.annualized_book_volatility),
        "gross_traded_notional": _decimal_text(item.gross_traded_notional),
        "total_fees": _decimal_text(item.total_fees),
    }


def _scenario_payload(item: ScenarioTradingMetrics) -> dict[str, object]:
    return {
        "scenario_id": item.scenario_id,
        "scenario_result_id": item.scenario_result_id,
        "command_count": item.command_count,
        "fill_event_count": item.fill_event_count,
        "partial_fill_event_count": item.partial_fill_event_count,
        "requested_quantity": item.requested_quantity,
        "filled_quantity": item.filled_quantity,
        "fill_ratio": _decimal_text(item.fill_ratio),
        "currencies": [_currency_payload(value) for value in item.currencies],
    }


def _metrics_identity(
    result_id: str,
    annualization_sessions: int,
    scenarios: tuple[ScenarioTradingMetrics, ...],
) -> str:
    payload = {
        "type": "TradingMetrics",
        "version": 1,
        "simulation_result_id": result_id,
        "annualization_sessions": annualization_sessions,
        "scenarios": [_scenario_payload(item) for item in scenarios],
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _book_values(state: LedgerState) -> dict[Currency, Decimal]:
    values: dict[Currency, Decimal] = {}
    for cash in state.cash:
        value = cash.settled + cash.receivable - cash.payable
        if not value.is_finite():
            _fail()
        values[cash.currency] = values.get(cash.currency, Decimal(0)) + value
    for position in state.positions:
        value = position.avg_cost.amount * position.quantity
        if not value.is_finite():
            _fail()
        currency = position.avg_cost.currency
        values[currency] = values.get(currency, Decimal(0)) + value
    return values


def _curve_states(scenario: VerifiedScenarioResult) -> tuple[LedgerState, ...]:
    state_by_id: dict[str, LedgerState] = {}
    previous_id = scenario.initial_ledger_state_id
    for transition in scenario.transitions:
        if transition.previous_state_id != previous_id:
            _fail()
        existing = state_by_id.get(transition.state.state_id)
        if existing is not None and existing != transition.state:
            _fail()
        state_by_id[transition.state.state_id] = transition.state
        previous_id = transition.state.state_id
    if previous_id != scenario.final_state.state_id:
        _fail()

    states: list[LedgerState] = []
    for checkpoint in scenario.checkpoints:
        state = state_by_id.get(checkpoint.ledger_state_id)
        if state is None or state.as_of_date != checkpoint.session_date:
            _fail()
        if states and state.as_of_date <= states[-1].as_of_date:
            _fail()
        states.append(state)
    if not states:
        _fail()
    if scenario.final_state.state_id != states[-1].state_id:
        if scenario.final_state.as_of_date < states[-1].as_of_date:
            _fail()
        states.append(scenario.final_state)
    return tuple(states)


def _returns(values: tuple[Decimal, ...]) -> tuple[Decimal, ...] | None:
    output: list[Decimal] = []
    for previous, current in zip(values, values[1:]):
        if previous <= 0:
            return None
        output.append(current / previous - Decimal(1))
    return tuple(output)


def _maximum_drawdown(values: tuple[Decimal, ...]) -> Decimal | None:
    peak: Decimal | None = None
    maximum = Decimal(0)
    for value in values:
        if not value.is_finite():
            _fail()
        if peak is None or value > peak:
            peak = value
        if peak > 0:
            maximum = max(maximum, (peak - value) / peak)
    return None if peak is None or peak <= 0 else maximum


def _annualized_volatility(
    returns: tuple[Decimal, ...] | None, annualization_sessions: int
) -> Decimal | None:
    if returns is None or len(returns) < 2:
        return None
    with localcontext() as context:
        context.prec = 28
        mean = sum(returns, Decimal(0)) / Decimal(len(returns))
        variance = sum(((item - mean) ** 2 for item in returns), Decimal(0)) / Decimal(
            len(returns)
        )
        return variance.sqrt() * Decimal(annualization_sessions).sqrt()


def _build_scenario(
    scenario: VerifiedScenarioResult, annualization_sessions: int
) -> ScenarioTradingMetrics:
    states = _curve_states(scenario)
    values_by_state = tuple(_book_values(state) for state in states)
    requested = sum((item.intent.quantity for item in scenario.commands), 0)
    fills = tuple(item for item in scenario.events if item.event_type in _FILL_TYPES)
    filled = sum((item.last_quantity for item in fills), 0)
    if filled > requested:
        _fail()

    notionals: dict[Currency, Decimal] = {}
    fees: dict[Currency, Decimal] = {}
    for event in fills:
        if event.last_price is None or not event.last_price.is_finite():
            _fail()
        command = next(
            (item for item in scenario.commands if item.command_id == event.command_id), None
        )
        if command is None:
            _fail()
        currency = command.intent.quote_currency
        notionals[currency] = notionals.get(currency, Decimal(0)) + (
            event.last_price * event.last_quantity
        )
        for fee in event.fees:
            amount = fee.amount.amount
            if not amount.is_finite():
                _fail()
            fee_currency = fee.amount.currency
            fees[fee_currency] = fees.get(fee_currency, Decimal(0)) + amount

    currencies = sorted(
        set().union(*(values.keys() for values in values_by_state), notionals, fees),
        key=lambda item: item.value,
    )
    currency_metrics: list[CurrencyTradingMetrics] = []
    for currency in currencies:
        curve = tuple(values.get(currency, Decimal(0)) for values in values_by_state)
        returns = _returns(curve)
        book_return = None if curve[0] <= 0 else curve[-1] / curve[0] - Decimal(1)
        currency_metrics.append(
            CurrencyTradingMetrics(
                currency=currency,
                opening_book_value=curve[0],
                closing_book_value=curve[-1],
                book_return=book_return,
                maximum_book_drawdown=_maximum_drawdown(curve),
                annualized_book_volatility=_annualized_volatility(
                    returns, annualization_sessions
                ),
                gross_traded_notional=notionals.get(currency, Decimal(0)),
                total_fees=fees.get(currency, Decimal(0)),
            )
        )
    ratio = None if requested == 0 else Decimal(filled) / Decimal(requested)
    return ScenarioTradingMetrics(
        scenario_id=scenario.scenario_id,
        scenario_result_id=scenario.scenario_result_id,
        command_count=len(scenario.commands),
        fill_event_count=len(fills),
        partial_fill_event_count=sum(
            item.event_type is ExecutionEventType.PARTIAL_FILL for item in fills
        ),
        requested_quantity=requested,
        filled_quantity=filled,
        fill_ratio=ratio,
        currencies=tuple(currency_metrics),
    )


def build_trading_metrics(
    result: VerifiedSimulationResult, annualization_sessions: int
) -> TradingMetrics:
    """Build deterministic metrics without replaying B6 or inventing market NAV."""
    try:
        if (
            type(result) is not VerifiedSimulationResult
            or not _is_hex64(result.result_id)
            or type(annualization_sessions) is not int
            or annualization_sessions <= 0
            or type(result.scenarios) is not tuple
            or not result.scenarios
            or any(type(item) is not VerifiedScenarioResult for item in result.scenarios)
        ):
            _fail()
        with localcontext() as context:
            context.prec = 28
            context.rounding = ROUND_HALF_EVEN
            proven_result = verify_simulation_result_identity(result)
            scenarios = tuple(
                sorted(
                    (
                        _build_scenario(item, annualization_sessions)
                        for item in proven_result.scenarios
                    ),
                    key=lambda item: item.scenario_id,
                )
            )
            return TradingMetrics(
                metrics_id=_metrics_identity(
                    proven_result.result_id, annualization_sessions, scenarios
                ),
                simulation_result_id=proven_result.result_id,
                annualization_sessions=annualization_sessions,
                scenarios=scenarios,
            )
    except TradingMetricsError:
        raise
    except Exception:
        pass
    # Raise outside the active exception handler so hostile verifier details
    # cannot survive in ``__context__`` or a rendered traceback.
    _fail()


__all__ = [
    "CurrencyTradingMetrics",
    "ScenarioTradingMetrics",
    "TradingMetrics",
    "TradingMetricsError",
    "build_trading_metrics",
]
