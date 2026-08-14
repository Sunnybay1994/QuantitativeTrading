"""Focused formal G7D-F2 session execution tests."""

from __future__ import annotations

import datetime as dt
import inspect
from dataclasses import fields, replace
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_execution as execution
import tests.unit.test_m3_formal_a_share_market_facts as facts_support
import tests.unit.test_m3_formal_a_share_open_execution as open_support
from quant.domain import ExecutionRejectReason, OrderSide
from quant.research.m3.contracts import AShareCostPeriod


_DAY = dt.date(2026, 1, 5)
_FULL_DAY = dt.date(2026, 1, 6)


def _issued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    return facts_support._issued_capability(tmp_path, monkeypatch)


def _period(**updates: Decimal) -> AShareCostPeriod:
    values = {
        "commission_rate": Decimal("0.00025"),
        "commission_min": Decimal("5"),
        "stamp_tax_sell": Decimal("0.0005"),
        "transfer_fee": Decimal("0.00001"),
        "slippage": Decimal("0.001"),
    }
    values.update(updates)
    return AShareCostPeriod(
        effective_from=dt.date(2023, 8, 28),
        effective_to=None,
        **values,
    )


def _targets(
    *rows: tuple[str, float], as_of: dt.date = dt.date(2026, 1, 4)
) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "as_of": as_of,
                "strategy": "formal",
                "strategy_version": "v1",
                "symbol": symbol,
                "weight": weight,
            }
            for symbol, weight in rows
        ],
        schema={
            "as_of": pl.Date,
            "strategy": pl.Utf8,
            "strategy_version": pl.Utf8,
            "symbol": pl.Utf8,
            "weight": pl.Float64,
        },
    )


def _position(
    symbol: str,
    quantity: int,
    *,
    sellable: int | None = None,
    mark: Decimal = Decimal("10"),
) -> execution.AccountPosition:
    available = quantity if sellable is None else sellable
    return execution.AccountPosition(
        symbol=symbol,
        quantity=quantity,
        sellable_quantity=available,
        unsettled_quantity=quantity - available,
        mark_price=mark,
    )


def _run(
    *,
    facts: Any,
    targets: pl.DataFrame,
    positions: execution.PositionBook = (),
    cash: Decimal = Decimal("10000"),
    equity: Decimal = Decimal("10000"),
    day: dt.date = _DAY,
    period: AShareCostPeriod | None = None,
    multiplier: Decimal = Decimal(1),
) -> execution.AShareSessionExecutionTransition:
    return execution.execute_formal_a_share_session(
        facts=facts,
        date=day,
        targets=targets,
        positions=positions,
        cash=cash,
        pre_trade_equity=equity,
        base_cost_period=period or _period(),
        friction_multiplier=multiplier,
    )


def _assert_invalid(callback: Any) -> None:
    with pytest.raises(execution.AShareExecutionError) as caught:
        callback()
    assert type(caught.value) is execution.AShareExecutionError
    assert str(caught.value) == "M3_A_SHARE_EXECUTION_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def _as_star(facts: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    old, new = "600000.SH", "688001.SH"
    updates: dict[str, pl.DataFrame] = {}
    for artifact, frame in open_support._selected(facts).items():
        if artifact in {
            "instrument.parquet",
            "bar_1d.parquet",
            "price_limit_1d.parquet",
            "suspension_1d.parquet",
        }:
            frame = frame.with_columns(
                pl.when(pl.col("symbol") == old)
                .then(pl.lit(new))
                .otherwise(pl.col("symbol"))
                .alias("symbol")
            ).sort(*(
                ["symbol"]
                if artifact == "instrument.parquet"
                else ["symbol", "trade_date", "source"]
            ))
        updates[artifact] = frame
    return open_support._reissue(facts, monkeypatch, **updates)


def test_happy_path_calls_public_f1_exact_once_and_exports_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    original = execution.build_formal_a_share_open_execution_states
    calls: list[tuple[str, ...]] = []

    def spy(**kwargs: object) -> pl.DataFrame:
        calls.append(cast(tuple[str, ...], kwargs["symbols"]))
        return original(**cast(Any, kwargs))

    monkeypatch.setattr(
        execution, "build_formal_a_share_open_execution_states", spy
    )
    result = _run(facts=facts, targets=_targets(("000001.SZ", 0.1)))
    assert calls == [("000001.SZ",)]
    assert result.input_market_facts_sha256 == "f" * 64
    assert [(item.symbol, item.side, item.requested_quantity) for item in result.intents] == [
        ("000001.SZ", OrderSide.BUY, 125)
    ]
    assert [(item.symbol, item.quantity) for item in result.fills] == [
        ("000001.SZ", 100)
    ]
    assert result.fills[0].execution_price == Decimal("8.01")
    assert result.post_trade_cash == Decimal("9193.99")
    assert result.post_trade_positions[0].unsettled_quantity == 100
    assert result.buy_allocation_lambda == Fraction(1)
    assert "open_states" not in inspect.signature(
        execution.execute_formal_a_share_session
    ).parameters


@pytest.mark.parametrize(
    ("symbol", "weight", "raw"),
    [
        ("600000.SH", 0.00001, 0),
        ("600000.SH", 0.099, 99),
        ("688001.SH", 0.00001, 0),
        ("688001.SH", 0.199, 199),
    ],
)
def test_zero_position_tiny_positive_target_keeps_one_buy_lot_diagnostic(
    symbol: str,
    weight: float,
    raw: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    if symbol.startswith("688"):
        facts = _as_star(facts, monkeypatch)
    result = _run(facts=facts, targets=_targets((symbol, weight)))
    assert len(result.intents) == 1
    intent = result.intents[0]
    assert intent.side is OrderSide.BUY
    assert intent.raw_target_quantity == raw
    assert intent.target_position_quantity == 0
    assert intent.requested_quantity == raw
    assert result.fills == ()
    assert len(result.rejections) == 1
    rejection = result.rejections[0]
    assert (
        rejection.side,
        rejection.reason,
        rejection.requested_quantity,
        rejection.rejected_quantity,
    ) == (OrderSide.BUY, ExecutionRejectReason.LOT_CONSTRAINT, raw, raw)
    assert rejection.rejected_notional == intent.target_notional
    assert result.reference_opens == ((symbol, Decimal("10.0")),)
    with pytest.raises(ValueError):
        replace(
            result,
            reference_opens=((symbol, Decimal("10.01")),),
        )


@pytest.mark.parametrize(
    ("symbol", "weight", "raw", "quantity"),
    [
        ("600000.SH", 0.099, 99, 100),
        ("688001.SH", 0.199, 199, 250),
    ],
)
def test_held_tiny_target_has_one_sell_intent_and_separate_buy_diagnostic(
    symbol: str,
    weight: float,
    raw: int,
    quantity: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    if symbol.startswith("688"):
        facts = _as_star(facts, monkeypatch)
    result = _run(
        facts=facts,
        targets=_targets((symbol, weight)),
        positions=(_position(symbol, quantity),),
        cash=Decimal("7000"),
        equity=Decimal("10000"),
    )
    assert len(result.intents) == 1
    assert result.intents[0].side is OrderSide.SELL
    assert result.intents[0].requested_quantity == quantity
    assert [(item.side, item.quantity) for item in result.fills] == [
        (OrderSide.SELL, quantity)
    ]
    assert result.post_trade_positions == ()
    assert [(item.side, item.reason, item.rejected_quantity) for item in result.rejections] == [
        (OrderSide.BUY, ExecutionRejectReason.LOT_CONSTRAINT, raw)
    ]
    with pytest.raises(ValueError):
        replace(
            result,
            reference_opens=((symbol, Decimal("10.01")),),
        )


def test_blocked_sell_keeps_target_attainability_lot_and_cash_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = open_support._limit_facts(
        _issued(tmp_path, monkeypatch),
        monkeypatch,
        open_value=10.0,
        upper=11.0,
        lower=9.995,
    )
    result = _run(
        facts=facts,
        targets=_targets(("000001.SZ", 0.079)),
        positions=(_position("000001.SZ", 100, mark=Decimal("8")),),
        cash=Decimal("1000"),
        equity=Decimal("10000"),
    )
    assert result.fills == ()
    assert result.post_trade_cash == Decimal("1000")
    assert result.post_trade_positions == (_position("000001.SZ", 100, mark=Decimal("8")),)
    assert [(item.side, item.reason) for item in result.rejections] == [
        (OrderSide.SELL, ExecutionRejectReason.SELL_AT_LOWER_LIMIT),
        (OrderSide.BUY, ExecutionRejectReason.LOT_CONSTRAINT),
    ]


def test_tiny_zero_position_target_reports_lot_before_upper_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = open_support._limit_facts(
        _issued(tmp_path, monkeypatch),
        monkeypatch,
        open_value=10.0,
        upper=10.005,
        lower=9.0,
    )
    result = _run(
        facts=facts, targets=_targets(("000001.SZ", 0.079))
    )
    assert result.fills == ()
    assert [(item.reason, item.rejected_quantity) for item in result.rejections] == [
        (ExecutionRejectReason.LOT_CONSTRAINT, 79)
    ]


def test_t1_partial_sell_and_target_lot_are_separate_conservation_domains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    result = _run(
        facts=facts,
        targets=_targets(("600000.SH", 0.099)),
        positions=(_position("600000.SH", 200, sellable=100),),
        cash=Decimal("0"),
        equity=Decimal("10000"),
    )
    assert [(item.side, item.quantity) for item in result.fills] == [
        (OrderSide.SELL, 100)
    ]
    assert [(item.side, item.reason, item.rejected_quantity) for item in result.rejections] == [
        (OrderSide.SELL, ExecutionRejectReason.T_PLUS_ONE, 100),
        (OrderSide.BUY, ExecutionRejectReason.LOT_CONSTRAINT, 99),
    ]
    assert result.post_trade_positions == (
        _position("600000.SH", 100, sellable=0),
    )


def test_missing_target_null_gap_and_r2_transition_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    result = _run(
        facts=facts,
        day=_FULL_DAY,
        targets=_targets(
            ("000002.SZ", 0.0), as_of=dt.date(2026, 1, 5)
        ),
        positions=(_position("000001.SZ", 100, mark=Decimal("8")),),
        cash=Decimal("200"),
        equity=Decimal("1000"),
    )
    assert [(item.symbol, item.side, item.requested_quantity) for item in result.intents] == [
        ("000001.SZ", OrderSide.SELL, None)
    ]
    assert result.rejections[0].reason is ExecutionRejectReason.SUSPENDED
    assert result.rejections[0].rejected_notional == Decimal("800")
    assert result.post_trade_cash == Decimal("200")
    assert result.post_trade_positions == result.pre_trade_positions
    with pytest.raises(ValueError):
        replace(result, rejections=())

    ordinary_cases = (
        (ExecutionRejectReason.T_PLUS_ONE, OrderSide.SELL),
        (ExecutionRejectReason.LOT_CONSTRAINT, OrderSide.SELL),
        (ExecutionRejectReason.LOT_CONSTRAINT, OrderSide.BUY),
        (ExecutionRejectReason.CASH_CONSTRAINT, OrderSide.BUY),
        (ExecutionRejectReason.SELL_AT_LOWER_LIMIT, OrderSide.SELL),
    )
    for reason, side in ordinary_cases:
        if reason is ExecutionRejectReason.LOT_CONSTRAINT and side is OrderSide.BUY:
            ordinary = _run(
                facts=facts, targets=_targets(("600000.SH", 0.15))
            )
        else:
            ordinary = _transition_for_rejection(
                reason=reason, tmp_path=tmp_path, monkeypatch=monkeypatch
            )
        index, rejection = next(
            (index, item)
            for index, item in enumerate(ordinary.rejections)
            if item.reason is reason and item.side is side
        )
        changed = list(ordinary.rejections)
        changed[index] = replace(
            rejection,
            rejected_notional=rejection.rejected_notional + Decimal("0.01"),
        )
        with pytest.raises(ValueError):
            replace(ordinary, rejections=tuple(changed))

    two_symbols = _run(
        facts=facts,
        targets=_targets(("000001.SZ", 0.05), ("600000.SH", 0.05)),
    )
    assert two_symbols.reference_opens == (
        ("000001.SZ", Decimal("8.0")),
        ("600000.SH", Decimal("10.0")),
    )
    invalid_references = (
        two_symbols.reference_opens[1:],
        two_symbols.reference_opens + (("600001.SH", Decimal("10")),),
        tuple(reversed(two_symbols.reference_opens)),
        two_symbols.reference_opens + (two_symbols.reference_opens[-1],),
        (("000001.SZ", Decimal("8.01")), two_symbols.reference_opens[1]),
        cast(Any, (
            ["000001.SZ", Decimal("8.0")],
            two_symbols.reference_opens[1],
        )),
    )
    for reference_opens in invalid_references:
        with pytest.raises(ValueError):
            replace(two_symbols, reference_opens=reference_opens)
    with pytest.raises(ValueError):
        replace(two_symbols, reference_opens_sha256="0" * 64)
    rehashed_references = (
        ("000001.SZ", Decimal("8.01")),
        two_symbols.reference_opens[1],
    )
    rehashed = replace(
        two_symbols,
        reference_opens=rehashed_references,
        reference_opens_sha256=execution._formal_reference_opens_sha256(
            rehashed_references
        ),
    )
    assert rehashed.reference_opens == rehashed_references

    fill_result = _run(
        facts=facts, targets=_targets(("000001.SZ", 0.1))
    )
    bad_fill = replace(
        fill_result.fills[0],
        reference_open=fill_result.fills[0].reference_open + Decimal("0.01"),
    )
    with pytest.raises(ValueError):
        replace(fill_result, fills=(bad_fill,))

    special = _run(
        facts=facts,
        targets=_targets(("600000.SH", 0.0999)),
        positions=(_position("600000.SH", 100),),
        cash=Decimal("7000"),
        equity=Decimal("10000"),
    )
    target_lot = next(
        item for item in special.rejections
        if item.side is OrderSide.BUY
        and item.reason is ExecutionRejectReason.LOT_CONSTRAINT
    )
    assert target_lot.rejected_notional == Decimal("999.0000")
    assert target_lot.rejected_notional != Decimal("10.0") * 99
    with pytest.raises(ValueError):
        replace(
            special,
            rejections=(replace(
                target_lot,
                rejected_notional=target_lot.rejected_notional + Decimal("0.01"),
            ),),
        )

    null_gap = _run(
        facts=facts,
        day=_FULL_DAY,
        targets=_targets(
            ("000002.SZ", 0.0), as_of=dt.date(2026, 1, 5)
        ),
        positions=(_position("000001.SZ", 100, mark=Decimal("8")),),
        cash=Decimal("200"),
        equity=Decimal("1000"),
    )
    assert null_gap.reference_opens == ()
    assert null_gap.reference_opens_sha256 == (
        execution._formal_reference_opens_sha256(())
    )
    with pytest.raises(ValueError):
        replace(null_gap, reference_opens_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(
            null_gap,
            reference_opens=(("000001.SZ", Decimal("8")),),
        )
    with pytest.raises(ValueError):
        replace(
            null_gap,
            rejections=(replace(
                null_gap.rejections[0],
                rejected_notional=Decimal("800.01"),
            ),),
        )


def test_null_gap_is_exact_and_ambient_decimal_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    mark = Decimal(
        "7.1818181818181818181818181818181818181818181818181818181818181818181818181818182"
    )
    transitions: list[execution.AShareSessionExecutionTransition] = []
    contexts = (
        (28, None, None, None, False),
        (50, None, None, None, False),
        (4, ROUND_DOWN, 9, -9, True),
    )
    for precision, rounding, emax, emin, trap_inexact in contexts:
        with localcontext() as ambient:
            ambient.prec = precision
            if rounding is not None:
                ambient.rounding = rounding
            if emax is not None and emin is not None:
                ambient.Emax = emax
                ambient.Emin = emin
            ambient.traps[Inexact] = trap_inexact
            ambient.clear_flags()
            before = (
                ambient.prec,
                ambient.rounding,
                ambient.Emax,
                ambient.Emin,
                dict(ambient.traps),
                dict(ambient.flags),
            )
            transitions.append(_run(
                facts=facts,
                day=_FULL_DAY,
                targets=_targets(
                    ("000001.SZ", 0.0), as_of=dt.date(2026, 1, 5)
                ),
                positions=(_position("000001.SZ", 100, mark=mark),),
                cash=Decimal("200"),
                equity=Decimal("1000"),
            ))
            after = (
                ambient.prec,
                ambient.rounding,
                ambient.Emax,
                ambient.Emin,
                dict(ambient.traps),
                dict(ambient.flags),
            )
        assert after == before

    baseline = transitions[0]
    for transition in transitions[1:]:
        for field in fields(baseline):
            assert getattr(transition, field.name) == getattr(baseline, field.name)
    rejection = baseline.rejections[0]
    assert rejection.requested_quantity is None
    assert rejection.rejected_notional == execution._formal_multiply(
        mark, 100
    ).copy_abs()
    with pytest.raises(ValueError):
        replace(
            baseline,
            rejections=(replace(
                rejection,
                rejected_notional=rejection.rejected_notional + Decimal("0.01"),
            ),),
        )


def test_sell_then_fraction_buy_uses_actual_cash_and_component_fees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    period = _period(
        commission_rate=Decimal(0),
        commission_min=Decimal("5"),
        stamp_tax_sell=Decimal(0),
        transfer_fee=Decimal("0.00001"),
        slippage=Decimal(0),
    )
    result = _run(
        facts=facts,
        targets=_targets(("000001.SZ", 0.24), ("600000.SH", 0.0)),
        positions=(_position("600000.SH", 200),),
        cash=Decimal("15.02"),
        equity=Decimal("10000"),
        period=period,
    )
    assert [item.side for item in result.fills] == [OrderSide.SELL, OrderSide.BUY]
    assert result.fills[1].quantity == 200
    assert result.post_trade_cash >= 0
    assert result.buy_allocation_lambda == Fraction(2, 3)


def test_multiplier_decimal_context_and_transition_local_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    with localcontext() as ambient:
        ambient.prec = 4
        ambient.rounding = ROUND_DOWN
        ambient.Emax = 9
        ambient.Emin = -9
        ambient.traps[Inexact] = True
        before = (
            ambient.prec,
            ambient.rounding,
            ambient.Emax,
            ambient.Emin,
            dict(ambient.traps),
            dict(ambient.flags),
        )
        result = _run(
            facts=facts,
            targets=_targets(("000001.SZ", 0.1)),
            multiplier=Decimal("0.5"),
        )
        assert (
            ambient.prec,
            ambient.rounding,
            ambient.Emax,
            ambient.Emin,
            dict(ambient.traps),
            dict(ambient.flags),
        ) == before
    assert result.effective_cost_period.commission_rate == Decimal("0.000125")
    assert result.effective_cost_period.commission_min == Decimal("2.5")
    assert result.effective_cost_period.stamp_tax_sell == Decimal("0.0005")
    assert result.effective_cost_period.transfer_fee == Decimal("0.00001")
    assert result.effective_cost_period.slippage == Decimal("0.0005")
    with pytest.raises(ValueError):
        replace(result, post_trade_cash=result.post_trade_cash + Decimal("0.01"))
    with pytest.raises(ValueError):
        replace(result, rejections=())


@pytest.mark.parametrize(
    "targets",
    [
        _targets(("600000.SH", 0.1), ("000001.SZ", 0.1)),
        _targets(("000001.SZ", 0.6), ("000002.SZ", 0.4000000001)),
        _targets(("000001.SZ", float("nan"))),
        _targets(("999999.SZ", 0.1)),
    ],
)
def test_invalid_target_domains_fail_closed_without_repair(
    targets: pl.DataFrame,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_invalid(lambda: _run(
        facts=_issued(tmp_path, monkeypatch), targets=targets
    ))


def test_fake_facts_fail_before_property_access_and_error_is_redacted() -> None:
    accesses: list[str] = []

    class Fake:
        @property
        def identity(self) -> object:
            accesses.append("identity")
            return object()

    _assert_invalid(lambda: _run(
        facts=cast(Any, Fake()), targets=_targets(("000001.SZ", 0.1))
    ))
    assert accesses == []


def test_large_star_desired_avoids_linear_valid_quantity_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _as_star(_issued(tmp_path, monkeypatch), monkeypatch)
    monkeypatch.setattr(
        execution,
        "_valid_buy_quantities",
        lambda *args, **kwargs: pytest.fail("linear materialization"),
    )
    result = _run(
        facts=facts,
        targets=_targets(("688001.SH", 1.0)),
        cash=Decimal("100000000"),
        equity=Decimal("100000000"),
        period=_period(
            commission_rate=Decimal(0),
            commission_min=Decimal(0),
            stamp_tax_sell=Decimal(0),
            transfer_fee=Decimal(0),
            slippage=Decimal(0),
        ),
    )
    assert result.fills[0].quantity == 10_000_000
    assert result.buy_allocation_lambda == Fraction(1)


def test_unaffordable_first_star_breakpoint_terminates_at_exact_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _as_star(_issued(tmp_path, monkeypatch), monkeypatch)
    result = _run(
        facts=facts,
        targets=_targets(("688001.SH", 0.201)),
        cash=Decimal(0),
        equity=Decimal("10000"),
    )
    assert result.fills == ()
    assert result.buy_allocation_lambda == Fraction(0)
    assert [(item.reason, item.rejected_quantity) for item in result.rejections] == [
        (ExecutionRejectReason.CASH_CONSTRAINT, 201)
    ]


def _transition_for_rejection(
    *,
    reason: ExecutionRejectReason,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> execution.AShareSessionExecutionTransition:
    facts = _issued(tmp_path, monkeypatch)
    if reason in {
        ExecutionRejectReason.T_PLUS_ONE,
        ExecutionRejectReason.LOT_CONSTRAINT,
    }:
        result = _run(
            facts=facts,
            targets=_targets(("600000.SH", 0.1)),
            positions=(
                _position("600000.SH", 257, sellable=120),
            ),
            cash=Decimal("7000"),
            equity=Decimal("10000"),
        )
        if reason is ExecutionRejectReason.LOT_CONSTRAINT:
            assert any(
                item.side is OrderSide.SELL and item.reason is reason
                for item in result.rejections
            )
        return result
    if reason is ExecutionRejectReason.CASH_CONSTRAINT:
        return _run(
            facts=facts,
            targets=_targets(("600000.SH", 0.2)),
            cash=Decimal("1005"),
            equity=Decimal("10000"),
            period=_period(
                commission_rate=Decimal(0),
                commission_min=Decimal("5"),
                stamp_tax_sell=Decimal(0),
                transfer_fee=Decimal(0),
                slippage=Decimal(0),
            ),
        )
    if reason is ExecutionRejectReason.SELL_AT_LOWER_LIMIT:
        blocked = open_support._limit_facts(
            facts,
            monkeypatch,
            open_value=10.0,
            upper=11.0,
            lower=9.995,
        )
        return _run(
            facts=blocked,
            targets=_targets(("000001.SZ", 0.0)),
            positions=(
                _position("000001.SZ", 100, mark=Decimal("8")),
            ),
            cash=Decimal("1000"),
            equity=Decimal("10000"),
        )
    if reason is ExecutionRejectReason.BUY_AT_UPPER_LIMIT:
        blocked = open_support._limit_facts(
            facts,
            monkeypatch,
            open_value=10.0,
            upper=10.005,
            lower=9.0,
        )
        return _run(
            facts=blocked,
            targets=_targets(("000001.SZ", 0.1)),
        )
    raise AssertionError(reason)
