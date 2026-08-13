"""G7C corporate-action entitlement state-machine adversarial tests."""

from __future__ import annotations

import datetime as dt
import inspect
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.corporate_actions as corporate_actions_module
import quant.domain as domain_public
from quant.backtest.corporate_actions import (
    EntitlementPosition,
    EntitlementPosting,
    EntitlementTransition,
    capture_record_close_entitlements,
    mark_full_day_event_from_factor,
    recognize_ex_date_entitlements,
    settle_due_entitlements,
)
from quant.domain.enums import EntitlementLegState, EntitlementPostingType

_D0 = dt.date(2025, 1, 2)
_D1 = dt.date(2025, 1, 3)
_D2 = dt.date(2025, 1, 6)
_D3 = dt.date(2025, 1, 7)
_D4 = dt.date(2025, 1, 8)
_SESSIONS = (_D0, _D1, _D2, _D3, _D4)


def _event(
    *,
    event_id: str = "a" * 64,
    symbol: str = "600000.SH",
    record_date: dt.date = _D0,
    ex_date: dt.date = _D1,
    cash: float = 0.01005,
    stock: float = 0.1,
    pay_date: dt.date | None = dt.date(2025, 1, 4),
    stock_list_date: dt.date | None = _D1,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "symbol": symbol,
        "ex_date": ex_date,
        "action_type": "DIVIDEND_DISTRIBUTION",
        "cash_per_share_gross": cash,
        "stock_ratio": stock,
        "rights_price": None,
        "rights_ratio": 0.0,
        "rights_actual_shares": None,
        "rights_pre_shares": None,
        "rights_post_shares": None,
        "rights_pre_circulating_shares": None,
        "rights_post_circulating_shares": None,
        "rights_mixed_change_proof_sha256": None,
        "record_date": record_date,
        "pay_date": pay_date,
        "stock_list_date": stock_list_date,
        "vendor_record_id": "fixture-event",
        "source": "tushare+cninfo",
        "source_snapshot_id": "fixture-snapshot",
    }


def _ledger(*rows: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(rows).with_columns(
        pl.col("ex_date", "record_date", "pay_date", "stock_list_date").cast(pl.Date)
    )


def _capture(
    *rows: dict[str, object],
    quantities: dict[str, int] | None = None,
    positions: tuple[EntitlementPosition, ...] = (),
    date: dt.date = _D0,
    terminal: dt.date = _D4,
) -> tuple[EntitlementPosition, ...]:
    return capture_record_close_entitlements(
        date=date,
        positions=positions,
        total_quantities=quantities or {"600000.SH": 100},
        corporate_actions=_ledger(*rows),
        sh_sessions=_SESSIONS,
        terminal_valuation_date=terminal,
    )


def test_public_enums_and_frozen_value_objects_are_exact() -> None:
    assert domain_public.EntitlementLegState is EntitlementLegState
    assert domain_public.EntitlementPostingType is EntitlementPostingType
    assert tuple(item.value for item in EntitlementLegState) == (
        "ABSENT",
        "NOT_APPLICABLE",
        "CAPTURED",
        "RECOGNIZED",
        "SETTLED",
    )
    assert tuple(item.value for item in EntitlementPostingType) == (
        "CAPTURE",
        "CASH_RECOGNIZE",
        "STOCK_RECOGNIZE",
        "CASH_SETTLE",
        "STOCK_SETTLE",
    )
    position = _capture(_event())[0]
    assert isinstance(position, EntitlementPosition)
    with pytest.raises(FrozenInstanceError):
        position.record_quantity = 1  # type: ignore[misc]
    recognized = recognize_ex_date_entitlements(date=_D1, positions=(position,))
    assert isinstance(recognized, EntitlementTransition)
    assert all(isinstance(posting, EntitlementPosting) for posting in recognized.postings)


def test_capture_uses_record_close_total_quantity_maps_due_sessions_and_states() -> None:
    position = _capture(_event(), quantities={"600000.SH": 100})[0]
    assert position.record_quantity == 100
    assert position.cash_per_share_gross == Decimal("0.01005")
    assert position.stock_ratio == Decimal("0.1")
    assert position.cash_entitlement_gross == Decimal("1.00500")
    assert position.stock_entitlement == 10
    assert position.cash_state is EntitlementLegState.CAPTURED
    assert position.stock_state is EntitlementLegState.CAPTURED
    # Saturday pay date maps to the first authoritative SH session >= due date.
    assert position.cash_settlement_session == _D2
    assert position.stock_settlement_session == _D1

    # Zero close quantity means no entitlement; later sales do not alter an
    # already captured position because transition APIs do not accept holdings.
    assert _capture(_event(), quantities={"600000.SH": 0}) == ()
    assert recognize_ex_date_entitlements(date=_D1, positions=(position,)).positions[0].record_quantity == 100


def test_cash_and_stock_legs_are_independent_and_zero_leg_is_not_applicable() -> None:
    cash_only = _event(event_id="a" * 64, stock=0.0, stock_list_date=None)
    stock_only = _event(
        event_id="b" * 64,
        cash=0.0,
        pay_date=None,
        stock=0.25,
        stock_list_date=_D3,
    )
    positions = _capture(cash_only, stock_only)
    by_id = {item.event_id: item for item in positions}
    assert by_id["a" * 64].cash_state is EntitlementLegState.CAPTURED
    assert by_id["a" * 64].stock_state is EntitlementLegState.NOT_APPLICABLE
    assert by_id["b" * 64].cash_state is EntitlementLegState.NOT_APPLICABLE
    assert by_id["b" * 64].stock_state is EntitlementLegState.CAPTURED
    assert all(
        state is not EntitlementLegState.ABSENT
        for item in positions
        for state in (item.cash_state, item.stock_state)
    )

    with pytest.raises(ValueError):
        replace(by_id["a" * 64], cash_state=EntitlementLegState.ABSENT)


@pytest.mark.parametrize(
    "mutation",
    ["same_date", "record_not_session", "ex_not_session", "duplicate"],
)
def test_capture_rejects_invalid_dates_and_duplicate_event(mutation: str) -> None:
    event = _event()
    positions: tuple[EntitlementPosition, ...] = ()
    if mutation == "same_date":
        event["record_date"] = _D1
    elif mutation == "record_not_session":
        event["record_date"] = dt.date(2025, 1, 1)
    elif mutation == "ex_not_session":
        event["ex_date"] = dt.date(2025, 1, 4)
        event["pay_date"] = _D2
        event["stock_list_date"] = _D2
    else:
        positions = _capture(event)
    with pytest.raises(ValueError):
        _capture(event, positions=positions)


def test_due_date_after_terminal_remains_receivable_without_settlement_session() -> None:
    event = _event(pay_date=dt.date(2025, 2, 1), stock_list_date=dt.date(2025, 2, 2))
    captured = _capture(event, terminal=_D4)
    position = captured[0]
    assert position.cash_settlement_session is None
    assert position.stock_settlement_session is None
    recognized = recognize_ex_date_entitlements(date=_D1, positions=captured)
    assert recognized.positions[0].cash_state is EntitlementLegState.RECOGNIZED
    assert recognized.positions[0].stock_state is EntitlementLegState.RECOGNIZED
    settled = settle_due_entitlements(date=_D4, positions=recognized.positions)
    assert settled.positions == recognized.positions
    assert settled.postings == ()
    assert settled.cash_delta == Decimal("0")
    assert settled.settled_stock == ()


@pytest.mark.parametrize(
    "sessions",
    [(_D0, _D1, _D1, _D2), (_D0, _D2, _D1, _D3), (_D1, _D2, _D3)],
)
def test_capture_rejects_non_authoritative_session_domains(
    sessions: tuple[dt.date, ...],
) -> None:
    with pytest.raises(ValueError):
        capture_record_close_entitlements(
            date=_D0,
            positions=(),
            total_quantities={"600000.SH": 100},
            corporate_actions=_ledger(_event()),
            sh_sessions=sessions,
            terminal_valuation_date=_D4,
        )


def test_recognize_then_same_day_stock_settle_and_later_cash_half_up_settle() -> None:
    captured = _capture(_event())
    before_ex = recognize_ex_date_entitlements(date=_D0, positions=captured)
    assert before_ex.positions == captured and before_ex.postings == ()
    with pytest.raises(ValueError):
        settle_due_entitlements(date=_D1, positions=captured)

    recognized = recognize_ex_date_entitlements(date=_D1, positions=captured)
    assert [item.posting_type for item in recognized.postings] == [
        EntitlementPostingType.CASH_RECOGNIZE,
        EntitlementPostingType.STOCK_RECOGNIZE,
    ]
    assert recognized.cash_delta == Decimal("0")
    assert recognized.settled_stock == ()
    cash_recognize, stock_recognize = recognized.postings
    assert (
        cash_recognize.cash_state_before,
        cash_recognize.cash_state_after,
        cash_recognize.stock_state_before,
        cash_recognize.stock_state_after,
    ) == (
        EntitlementLegState.CAPTURED,
        EntitlementLegState.RECOGNIZED,
        EntitlementLegState.CAPTURED,
        EntitlementLegState.CAPTURED,
    )
    assert (
        stock_recognize.cash_state_before,
        stock_recognize.cash_state_after,
        stock_recognize.stock_state_before,
        stock_recognize.stock_state_after,
    ) == (
        EntitlementLegState.RECOGNIZED,
        EntitlementLegState.RECOGNIZED,
        EntitlementLegState.CAPTURED,
        EntitlementLegState.RECOGNIZED,
    )
    assert all(
        state is EntitlementLegState.RECOGNIZED
        for state in (
            recognized.positions[0].cash_state,
            recognized.positions[0].stock_state,
        )
    )

    stock_settled = settle_due_entitlements(date=_D1, positions=recognized.positions)
    assert [item.posting_type for item in stock_settled.postings] == [
        EntitlementPostingType.STOCK_SETTLE
    ]
    assert stock_settled.settled_stock == (("600000.SH", 10),)
    assert stock_settled.postings[0].stock_state_before is EntitlementLegState.RECOGNIZED
    assert stock_settled.postings[0].stock_state_after is EntitlementLegState.SETTLED
    assert stock_settled.positions[0].stock_state is EntitlementLegState.SETTLED
    assert stock_settled.positions[0].cash_state is EntitlementLegState.RECOGNIZED

    cash_settled = settle_due_entitlements(date=_D2, positions=stock_settled.positions)
    assert [item.posting_type for item in cash_settled.postings] == [
        EntitlementPostingType.CASH_SETTLE
    ]
    posting = cash_settled.postings[0]
    assert cash_settled.cash_delta == Decimal("1.01")
    assert posting.cash_amount == Decimal("1.01")
    assert posting.cash_rounding_delta == Decimal("0.00500")
    assert posting.cash_state_before is EntitlementLegState.RECOGNIZED
    assert posting.cash_state_after is EntitlementLegState.SETTLED
    assert posting.stock_state_before is EntitlementLegState.SETTLED
    assert posting.stock_state_after is EntitlementLegState.SETTLED
    assert cash_settled.positions[0].cash_state is EntitlementLegState.SETTLED


def test_transitions_are_idempotent_after_posting_and_reject_state_skips() -> None:
    captured = _capture(_event())
    recognized = recognize_ex_date_entitlements(date=_D1, positions=captured)
    repeated_recognition = recognize_ex_date_entitlements(
        date=_D1, positions=recognized.positions
    )
    assert repeated_recognition.positions == recognized.positions
    assert repeated_recognition.postings == ()

    settled = settle_due_entitlements(date=_D1, positions=recognized.positions)
    repeated_settlement = settle_due_entitlements(date=_D1, positions=settled.positions)
    assert repeated_settlement.positions == settled.positions
    assert repeated_settlement.postings == ()

    skipped = replace(
        captured[0],
        cash_state=EntitlementLegState.SETTLED,
        stock_state=EntitlementLegState.SETTLED,
    )
    with pytest.raises(ValueError):
        recognize_ex_date_entitlements(date=_D1, positions=(skipped,))


def test_postings_sort_by_event_then_cash_before_stock() -> None:
    positions = _capture(
        _event(event_id="b" * 64),
        _event(event_id="a" * 64, symbol="600001.SH"),
        quantities={"600000.SH": 100, "600001.SH": 100},
    )
    transition = recognize_ex_date_entitlements(date=_D1, positions=positions)
    assert [(item.event_id, item.posting_type) for item in transition.postings] == [
        ("a" * 64, EntitlementPostingType.CASH_RECOGNIZE),
        ("a" * 64, EntitlementPostingType.STOCK_RECOGNIZE),
        ("b" * 64, EntitlementPostingType.CASH_RECOGNIZE),
        ("b" * 64, EntitlementPostingType.STOCK_RECOGNIZE),
    ]


@pytest.mark.parametrize("ratio", [0.125, 0.333, -0.1, float("nan")])
def test_stock_entitlement_must_be_exact_integer(ratio: float) -> None:
    with pytest.raises(ValueError):
        _capture(_event(cash=0.0, pay_date=None, stock=ratio), quantities={"600000.SH": 10})


def test_full_day_factor_mark_is_strict_decimal_and_has_no_theoretical_api() -> None:
    assert mark_full_day_event_from_factor(
        previous_mark=Decimal("10.00"), actual_factor_ratio=Decimal("1.25")
    ) == Decimal("8")
    assert tuple(inspect.signature(mark_full_day_event_from_factor).parameters) == (
        "previous_mark",
        "actual_factor_ratio",
    )
    assert not hasattr(corporate_actions_module, "theoretical_ex_mark")
    for previous, ratio in (
        (Decimal("0"), Decimal("1")),
        (Decimal("10"), Decimal("0")),
        (Decimal("10"), Decimal("-1")),
        (Decimal("NaN"), Decimal("1")),
        (Decimal("10"), Decimal("Infinity")),
        (10, Decimal("1")),
        (Decimal("10"), 1),
    ):
        with pytest.raises(ValueError):
            mark_full_day_event_from_factor(
                previous_mark=cast(Any, previous),
                actual_factor_ratio=cast(Any, ratio),
            )


def test_corporate_action_core_import_does_not_load_qlib() -> None:
    formal_support = Path(__file__).with_name(
        "test_m3_formal_corporate_actions.py"
    ).resolve()
    source_root = Path(__file__).resolve().parents[2] / "src"
    expected_public = (
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
    )
    script = f"""
import importlib
import pathlib
import runpy
import sys
import tempfile
from decimal import Decimal
from pytest import MonkeyPatch

sys.path.insert(0, {str(source_root)!r})
heavy = ('qlib', 'lightgbm', 'mlflow')
def heavy_loaded():
    return tuple(
        name for name in sys.modules
        if any(name == root or name.startswith(root + '.') for root in heavy)
    )

assert heavy_loaded() == ()
module = importlib.import_module('quant.backtest.corporate_actions')
assert heavy_loaded() == ()
assert tuple(module.__all__) == {expected_public!r}
assert '_initialize_formal_entitlement_capability' not in vars(module)

support = runpy.run_path({str(formal_support)!r})
frames = support['_fixture_frames']()
dates = frames['benchmark_bar_1d.parquet']['trade_date'].to_list()
mp = MonkeyPatch()
facts = support['_issued_facts'](
    pathlib.Path(tempfile.mkdtemp()), mp,
    (support['_event'](
        'a' * 64, symbol='600000.SH', record=dates[0], ex=dates[1],
        cash=0.01, pay=dates[1],
    ),),
)
old_state = module.initialize_formal_a_share_entitlement_replay(facts=facts)
old_transition = module.advance_formal_a_share_entitlements_pre_open(
    date=dates[0], replay=old_state, facts=facts,
)
module = importlib.reload(module)
assert heavy_loaded() == ()
assert tuple(module.__all__) == {expected_public!r}
assert '_initialize_formal_entitlement_capability' not in vars(module)
for callback in (lambda: old_state.phase, lambda: old_transition.postings):
    try:
        callback()
    except ValueError as exc:
        assert str(exc) == 'M3_A_SHARE_ENTITLEMENT_INVALID'
        assert exc.__cause__ is None and exc.__context__ is None
    else:
        raise AssertionError('old formal capability survived reload')
new_state = module.initialize_formal_a_share_entitlement_replay(facts=facts)
assert type(new_state) is module.AShareEntitlementReplayState
assert new_state.phase is module.EntitlementReplayPhase.PRE_OPEN
new_transition = module.advance_formal_a_share_entitlements_pre_open(
    date=dates[0], replay=new_state, facts=facts,
)
assert type(new_transition) is module.AShareEntitlementReplayTransition
assert new_transition.replay.phase is module.EntitlementReplayPhase.RECORD_CLOSE
assert module.mark_full_day_event_from_factor(
    previous_mark=Decimal('10'), actual_factor_ratio=Decimal('2'),
) == Decimal('5')
assert heavy_loaded() == ()
mp.undo()
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
