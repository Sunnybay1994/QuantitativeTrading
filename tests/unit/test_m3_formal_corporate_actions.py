"""Focused adversarial tests for the formal G7C entitlement replay."""

from __future__ import annotations

import datetime as dt
import inspect
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal, ROUND_DOWN, getcontext
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_execution as facts_module
from quant.backtest.corporate_actions import (
    AShareEntitlementError,
    AShareEntitlementReplayState,
    AShareEntitlementReplayTransition,
    EntitlementReplayPhase,
    advance_formal_a_share_entitlements_pre_open,
    capture_formal_a_share_entitlements_record_close,
    initialize_formal_a_share_entitlement_replay,
)
from quant.domain.enums import EntitlementLegState, EntitlementPostingType
from quant.research.m3.development_example import _fixture_frames


def _event(
    event_id: str,
    *,
    symbol: str,
    record: dt.date,
    ex: dt.date,
    action: str = "DIVIDEND_DISTRIBUTION",
    cash: float = 0.0,
    stock: float = 0.0,
    pay: dt.date | None = None,
    stock_list: dt.date | None = None,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "symbol": symbol,
        "ex_date": ex,
        "action_type": action,
        "cash_per_share_gross": cash,
        "stock_ratio": stock,
        "rights_price": 8.0 if action == "RIGHTS" else None,
        "rights_ratio": 0.1 if action == "RIGHTS" else 0.0,
        "rights_actual_shares": 1000.0 if action == "RIGHTS" else None,
        "rights_pre_shares": 10000.0 if action == "RIGHTS" else None,
        "rights_post_shares": 11000.0 if action == "RIGHTS" else None,
        "rights_pre_circulating_shares": None,
        "rights_post_circulating_shares": None,
        "rights_mixed_change_proof_sha256": None,
        "record_date": record,
        "pay_date": pay,
        "stock_list_date": ex if action == "RIGHTS" else stock_list,
        "vendor_record_id": "fixture",
        "source": "fixture",
        "source_snapshot_id": "fixture",
    }


def _issued_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    events: tuple[dict[str, object], ...],
    *,
    identity_char: str = "f",
) -> Any:
    frames = _fixture_frames()
    frames["instrument.parquet"] = frames["instrument.parquet"].with_columns(
        pl.lit(None, dtype=pl.Date).alias("delist_date"),
        pl.lit("LISTED").alias("status"),
    )
    frames["benchmark_bar_1d.parquet"] = frames[
        "benchmark_bar_1d.parquet"
    ].with_columns(pl.lit("H00300.CSI").alias("benchmark"))
    frames["corporate_action_ledger.parquet"] = pl.DataFrame(events).with_columns(
        pl.col("record_date", "ex_date", "pay_date", "stock_list_date").cast(pl.Date)
    )
    selected = {
        name: spec[1].validate(frames[name]).sort(list(spec[3]))
        for name, spec in facts_module._FORMAL_FACT_SPECS.items()
    }
    digests = tuple(
        facts_module.FormalAShareMarketFactArtifactDigestV1(
            root_alias="formal",
            relative_path=f"release/{index}.parquet",
            size_bytes=1,
            sha256=f"{index + 1:x}" * 64,
            table_name=spec[0],
            row_count=selected[name].height,
            content_sha256=f"{index + 9:x}"[-1] * 64,
        )
        for index, (name, spec) in enumerate(facts_module._FORMAL_FACT_SPECS.items())
    )
    identity = facts_module.FormalAShareMarketFactsIdentityV1(
        schema_version="m3-formal-a-share-market-facts-v1",
        g1_release_id="a" * 64,
        g1_release_manifest_sha256="b" * 64,
        backtest_plan_manifest_sha256="c" * 64,
        backtest_plan_receipt_sha256="d" * 64,
        window_sha256="e" * 64,
        artifact_digests=digests,
        input_market_facts_sha256=identity_char * 64,
    )
    release_entity = facts_module._PathEntity(tmp_path / "release", 1, 1, 1, 1, 1, 1)
    plan_entity = facts_module._PathEntity(tmp_path / "plan", 1, 2, 1, 1, 1, 1)
    fact_entities = tuple(
        facts_module._PathEntity(tmp_path / f"fact-{index}", 1, index + 3, 1, 1, 1, 1)
        for index in range(8)
    )
    monkeypatch.setattr(
        facts_module,
        "_prepare_verified_a_share_market_facts",
        lambda **kwargs: (
            identity, selected, (release_entity, plan_entity, fact_entities)
        ),
    )
    return facts_module.load_verified_a_share_market_facts(
        release=cast(Any, object()),
        plan=cast(Any, object()),
        fresh_context=cast(Any, object()),
        artifact_roots={"formal": tmp_path},
    )


def _sessions(facts: Any) -> tuple[dt.date, ...]:
    return tuple(facts.benchmark_bars.get_column("trade_date").to_list())


def _assert_invalid(callback: Any) -> None:
    with pytest.raises(AShareEntitlementError) as caught:
        callback()
    assert str(caught.value) == "M3_A_SHARE_ENTITLEMENT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_release_replay_mixed_share_consideration_rights_and_receivable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _fixture_frames()["benchmark_bar_1d.parquet"]["trade_date"].to_list()
    events = (
        _event(
            "a" * 64, symbol="600000.SH", record=base[0], ex=base[1],
            cash=0.01005, stock=0.1, pay=base[2], stock_list=base[1],
        ),
        _event(
            "b" * 64, symbol="000001.SZ", record=base[2], ex=base[3],
            action="RIGHTS",
        ),
        _event(
            "c" * 64, symbol="000002.SZ", record=base[4], ex=base[5],
            action="SHARE_CONSIDERATION", stock=0.2, stock_list=base[5],
        ),
        _event(
            "d" * 64, symbol="600000.SH", record=base[6], ex=base[7],
            cash=0.02, pay=base[-1] + dt.timedelta(days=30),
        ),
    )
    facts = _issued_facts(tmp_path, monkeypatch, events)
    replay = initialize_formal_a_share_entitlement_replay(facts=facts)
    postings = []
    cash = Decimal(0)
    stock = []
    for date in _sessions(facts):
        opened = advance_formal_a_share_entitlements_pre_open(
            date=date, replay=replay, facts=facts
        )
        postings.extend(opened.postings)
        cash += opened.cash_delta
        stock.extend(opened.settled_stock)
        quantities = {"600000.SH": 100, "000001.SZ": 0, "000002.SZ": 10}
        closed = capture_formal_a_share_entitlements_record_close(
            date=date,
            replay=opened.replay,
            total_quantities=quantities,
            facts=facts,
        )
        postings.extend(closed.postings)
        replay = closed.replay
    assert replay.phase is EntitlementReplayPhase.COMPLETE
    assert replay.processed_record_event_ids == tuple("abcd"[i] * 64 for i in range(4))
    assert replay.record_quantities == (
        ("a" * 64, 100), ("b" * 64, 0), ("c" * 64, 10), ("d" * 64, 100)
    )
    assert cash == Decimal("1.01")
    assert stock == [("600000.SH", 10), ("000002.SZ", 2)]
    assert all(item.event_id != "b" * 64 for item in replay.positions)
    assert replay.positions[-1].cash_state is EntitlementLegState.RECOGNIZED
    assert replay.positions[-1].cash_settlement_session is None
    assert len({(item.date, item.event_id, item.posting_type) for item in postings}) == len(postings)
    capture = next(item for item in postings if item.posting_type is EntitlementPostingType.CAPTURE)
    assert capture.cash_amount == 0 and capture.stock_quantity == 0


def test_rights_positive_holding_fails_but_zero_is_canonical_processed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = _fixture_frames()["benchmark_bar_1d.parquet"]["trade_date"].to_list()
    facts = _issued_facts(
        tmp_path, monkeypatch,
        (_event("a" * 64, symbol="600000.SH", record=dates[0], ex=dates[1], action="RIGHTS"),),
    )
    opened = advance_formal_a_share_entitlements_pre_open(
        date=dates[0], replay=initialize_formal_a_share_entitlement_replay(facts=facts), facts=facts
    )
    _assert_invalid(
        lambda: capture_formal_a_share_entitlements_record_close(
            date=dates[0], replay=opened.replay,
            total_quantities={"600000.SH": 1}, facts=facts,
        )
    )
    zero = capture_formal_a_share_entitlements_record_close(
        date=dates[0], replay=opened.replay,
        total_quantities={"600000.SH": 0}, facts=facts,
    )
    assert zero.postings == () and zero.replay.positions == ()
    assert zero.replay.record_quantities == (("a" * 64, 0),)


def test_half_up_is_ambient_context_independent_and_old_state_replay_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = _fixture_frames()["benchmark_bar_1d.parquet"]["trade_date"].to_list()
    facts = _issued_facts(
        tmp_path, monkeypatch,
        (_event(
            "a" * 64, symbol="600000.SH", record=dates[0], ex=dates[1],
            cash=0.01005, pay=dates[1],
        ),),
    )
    state = initialize_formal_a_share_entitlement_replay(facts=facts)
    opened = advance_formal_a_share_entitlements_pre_open(date=dates[0], replay=state, facts=facts)
    captured = capture_formal_a_share_entitlements_record_close(
        date=dates[0], replay=opened.replay,
        total_quantities={"600000.SH": 100}, facts=facts,
    )
    context = getcontext()
    old = (context.prec, context.rounding)
    context.prec, context.rounding = 3, ROUND_DOWN
    try:
        settled = advance_formal_a_share_entitlements_pre_open(
            date=dates[1], replay=captured.replay, facts=facts
        )
    finally:
        context.prec, context.rounding = old
    assert settled.cash_delta == Decimal("1.01")
    assert settled.postings[-1].cash_rounding_delta == Decimal("0.00500")
    _assert_invalid(
        lambda: advance_formal_a_share_entitlements_pre_open(
            date=dates[0], replay=captured.replay, facts=facts
        )
    )


def test_forged_position_or_quantity_closure_and_nonformal_facts_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = _fixture_frames()["benchmark_bar_1d.parquet"]["trade_date"].to_list()
    facts = _issued_facts(
        tmp_path, monkeypatch,
        (_event(
            "a" * 64, symbol="600000.SH", record=dates[0], ex=dates[1],
            cash=0.01, pay=dates[2],
        ),),
    )
    initial = initialize_formal_a_share_entitlement_replay(facts=facts)
    opened = advance_formal_a_share_entitlements_pre_open(date=dates[0], replay=initial, facts=facts)
    captured = capture_formal_a_share_entitlements_record_close(
        date=dates[0], replay=opened.replay,
        total_quantities={"600000.SH": 100}, facts=facts,
    )
    with pytest.raises(TypeError):
        replace(captured, postings=())
    with pytest.raises(TypeError):
        replace(captured.replay, positions=())
    for public_type in (AShareEntitlementReplayState, AShareEntitlementReplayTransition):
        _assert_invalid(lambda public_type=public_type: public_type())
    state_clone = object.__new__(AShareEntitlementReplayState)
    for slot in AShareEntitlementReplayState.__slots__:
        if slot != "__weakref__":
            object.__setattr__(
                state_clone, slot, object.__getattribute__(captured.replay, slot)
            )
    transition_clone = object.__new__(AShareEntitlementReplayTransition)
    for slot in AShareEntitlementReplayTransition.__slots__:
        if slot != "__weakref__":
            object.__setattr__(
                transition_clone, slot, object.__getattribute__(captured, slot)
            )
    object.__setattr__(transition_clone, "_postings", ())
    _assert_invalid(lambda: state_clone.phase)
    _assert_invalid(lambda: transition_clone.postings)
    _assert_invalid(
        lambda: initialize_formal_a_share_entitlement_replay(facts=cast(Any, object()))
    )


def test_r2_global_event_id_merge_and_same_day_order_are_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = _fixture_frames()["benchmark_bar_1d.parquet"]["trade_date"].to_list()
    facts = _issued_facts(
        tmp_path,
        monkeypatch,
        (
            _event(
                "b" * 64, symbol="600000.SH", record=dates[0], ex=dates[1],
                cash=0.01, pay=dates[1],
            ),
            _event(
                "a" * 64, symbol="000001.SZ", record=dates[2], ex=dates[3],
                cash=0.02, pay=dates[3],
            ),
        ),
    )
    replay = initialize_formal_a_share_entitlement_replay(facts=facts)
    for date in dates[:3]:
        opened = advance_formal_a_share_entitlements_pre_open(
            date=date, replay=replay, facts=facts
        )
        closed = capture_formal_a_share_entitlements_record_close(
            date=date,
            replay=opened.replay,
            total_quantities={"600000.SH": 100, "000001.SZ": 100},
            facts=facts,
        )
        replay = closed.replay
    assert replay.processed_record_event_ids == ("a" * 64, "b" * 64)
    assert replay.record_quantities == (("a" * 64, 100), ("b" * 64, 100))
    assert tuple(item.event_id for item in replay.positions) == ("a" * 64, "b" * 64)

    same_day = _issued_facts(
        tmp_path / "same-day",
        monkeypatch,
        tuple(
            _event(
                event_id,
                symbol=symbol,
                record=dates[0],
                ex=dates[1],
                cash=0.01005,
                stock=0.1,
                pay=dates[1],
                stock_list=dates[1],
            )
            for event_id, symbol in (("b" * 64, "600000.SH"), ("a" * 64, "000001.SZ"))
        ),
    )
    initial = initialize_formal_a_share_entitlement_replay(facts=same_day)
    day0 = advance_formal_a_share_entitlements_pre_open(
        date=dates[0], replay=initial, facts=same_day
    )
    captured = capture_formal_a_share_entitlements_record_close(
        date=dates[0], replay=day0.replay,
        total_quantities={"600000.SH": 100, "000001.SZ": 100}, facts=same_day,
    )
    assert tuple(item.event_id for item in captured.postings) == ("a" * 64, "b" * 64)
    opened = advance_formal_a_share_entitlements_pre_open(
        date=dates[1], replay=captured.replay, facts=same_day
    )
    assert tuple(item.posting_type for item in opened.postings) == (
        EntitlementPostingType.CASH_RECOGNIZE,
        EntitlementPostingType.STOCK_RECOGNIZE,
        EntitlementPostingType.CASH_RECOGNIZE,
        EntitlementPostingType.STOCK_RECOGNIZE,
        EntitlementPostingType.CASH_SETTLE,
        EntitlementPostingType.STOCK_SETTLE,
        EntitlementPostingType.CASH_SETTLE,
        EntitlementPostingType.STOCK_SETTLE,
    )
    assert tuple(item.event_id for item in opened.postings) == (
        "a" * 64, "a" * 64, "b" * 64, "b" * 64,
        "a" * 64, "a" * 64, "b" * 64, "b" * 64,
    )


def _reachable_callables(*roots: Any) -> tuple[Any, ...]:
    pending = list(roots)
    seen: set[int] = set()
    found: list[Any] = []
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if callable(value):
            found.append(value)
        closure = getattr(value, "__closure__", None)
        if closure is None:
            continue
        for cell in closure:
            try:
                nested = cell.cell_contents
            except ValueError:
                continue
            if callable(nested):
                pending.append(nested)
    return tuple(found)


def test_r2_public_graph_has_no_raw_issuer_and_clone_registry_attack_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant.backtest.corporate_actions as module

    assert "_initialize_formal_entitlement_capability" not in vars(module)
    assert not any(
        callable(value)
        and any(token in name.lower() for token in ("register", "sign", "mint", "factory"))
        for name, value in vars(module).items()
    )
    roots = (
        initialize_formal_a_share_entitlement_replay,
        advance_formal_a_share_entitlements_pre_open,
        capture_formal_a_share_entitlements_record_close,
        AShareEntitlementReplayState.__repr__,
        AShareEntitlementReplayTransition.__repr__,
    )
    reachable = _reachable_callables(*roots)
    assert not any(
        any(token in callback.__name__.lower() for token in ("register", "sign", "mint", "factory"))
        for callback in reachable
    )
    assert not any(
        {"values", "positions", "record_quantities"}
        <= set(inspect.signature(callback).parameters)
        for callback in reachable
    )

    dates = _fixture_frames()["benchmark_bar_1d.parquet"]["trade_date"].to_list()
    facts = _issued_facts(
        tmp_path, monkeypatch,
        (_event(
            "a" * 64, symbol="600000.SH", record=dates[0], ex=dates[1],
            cash=0.01, pay=dates[1],
        ),),
    )
    state = initialize_formal_a_share_entitlement_replay(facts=facts)
    opened = advance_formal_a_share_entitlements_pre_open(
        date=dates[0], replay=state, facts=facts
    )
    transition = capture_formal_a_share_entitlements_record_close(
        date=dates[0], replay=opened.replay,
        total_quantities={"600000.SH": 100}, facts=facts,
    )
    clone = object.__new__(AShareEntitlementReplayState)
    for slot in AShareEntitlementReplayState.__slots__:
        if slot != "__weakref__":
            object.__setattr__(clone, slot, object.__getattribute__(state, slot))
    # Even adding the clone to the closure registry cannot bypass the
    # attestation's exact-instance binding.
    for callback in reachable:
        closure = getattr(callback, "__closure__", None) or ()
        for cell in closure:
            try:
                nested = cell.cell_contents
            except ValueError:
                continue
            if isinstance(nested, __import__("weakref").WeakSet):
                nested.add(clone)
    _assert_invalid(lambda: clone.phase)
    transition_clone = object.__new__(AShareEntitlementReplayTransition)
    for slot in AShareEntitlementReplayTransition.__slots__:
        if slot != "__weakref__":
            object.__setattr__(
                transition_clone, slot, object.__getattribute__(transition, slot)
            )
    for callback in reachable:
        closure = getattr(callback, "__closure__", None) or ()
        for cell in closure:
            try:
                nested = cell.cell_contents
            except ValueError:
                continue
            if isinstance(nested, __import__("weakref").WeakSet):
                nested.add(transition_clone)
    _assert_invalid(lambda: transition_clone.postings)
    object.__setattr__(transition, "_postings", ())
    _assert_invalid(lambda: transition.postings)
    object.__setattr__(state, "_next_session_index", 1)
    _assert_invalid(lambda: state.next_session_index)


def test_r2_reload_rejects_old_values_in_fresh_subprocess() -> None:
    script = f"""
import importlib
import pathlib
import runpy
import tempfile
from pytest import MonkeyPatch

support = runpy.run_path({str(Path(__file__).resolve())!r})
frames = support['_fixture_frames']()
dates = frames['benchmark_bar_1d.parquet']['trade_date'].to_list()
mp = MonkeyPatch()
facts = support['_issued_facts'](
    pathlib.Path(tempfile.mkdtemp()), mp,
    (support['_event']('a' * 64, symbol='600000.SH', record=dates[0],
                       ex=dates[1], cash=0.01, pay=dates[1]),),
)
import quant.backtest.corporate_actions as module
old_state = module.initialize_formal_a_share_entitlement_replay(facts=facts)
old_transition = module.advance_formal_a_share_entitlements_pre_open(
    date=dates[0], replay=old_state, facts=facts)
module = importlib.reload(module)
for callback in (lambda: old_state.phase, lambda: old_transition.postings):
    try:
        callback()
    except ValueError as exc:
        assert str(exc) == 'M3_A_SHARE_ENTITLEMENT_INVALID'
    else:
        raise AssertionError('old formal value survived reload')
new_state = module.initialize_formal_a_share_entitlement_replay(facts=facts)
assert new_state.phase.value == 'PRE_OPEN'
assert module.mark_full_day_event_from_factor(
    previous_mark=support['Decimal']('10'),
    actual_factor_ratio=support['Decimal']('2')) == support['Decimal']('5')
mp.undo()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr


def test_r3_transition_attestation_rejects_every_ordered_output_and_input_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = _fixture_frames()["benchmark_bar_1d.parquet"]["trade_date"].to_list()
    event = _event(
        "a" * 64,
        symbol="600000.SH",
        record=dates[0],
        ex=dates[1],
        cash=0.01005,
        stock=0.1,
        pay=dates[1],
        stock_list=dates[1],
    )
    facts = _issued_facts(tmp_path / "facts-a", monkeypatch, (event,))
    initial = initialize_formal_a_share_entitlement_replay(facts=facts)
    day0 = advance_formal_a_share_entitlements_pre_open(
        date=dates[0], replay=initial, facts=facts
    )
    captured = capture_formal_a_share_entitlements_record_close(
        date=dates[0],
        replay=day0.replay,
        total_quantities={"600000.SH": 100},
        facts=facts,
    )
    assert len(captured.postings) == 1
    assert captured.replay.record_quantities == (("a" * 64, 100),)
    captured_replay = captured.replay

    def fresh_advance() -> Any:
        value = advance_formal_a_share_entitlements_pre_open(
            date=dates[1], replay=captured_replay, facts=facts
        )
        assert tuple(item.posting_type for item in value.postings) == (
            EntitlementPostingType.CASH_RECOGNIZE,
            EntitlementPostingType.STOCK_RECOGNIZE,
            EntitlementPostingType.CASH_SETTLE,
            EntitlementPostingType.STOCK_SETTLE,
        )
        assert value.cash_delta == Decimal("1.01")
        assert value.settled_stock == (("600000.SH", 10),)
        assert "operation='ADVANCE'" in repr(value)
        return value

    def reject_drift(value: Any, slot: str, attacked: object) -> None:
        # The exact issued object is consumable before the single-field attack.
        assert value.postings
        object.__setattr__(value, slot, attacked)
        _assert_invalid(lambda: value.postings)
        _assert_invalid(lambda: repr(value))

    value = fresh_advance()
    reject_drift(value, "_postings", value.postings[:-1])

    value = fresh_advance()
    reject_drift(value, "_postings", (*value.postings, value.postings[0]))

    value = fresh_advance()
    reordered = (value.postings[1], value.postings[0], *value.postings[2:])
    reject_drift(value, "_postings", reordered)

    value = fresh_advance()
    reject_drift(value, "_cash_delta", Decimal("0"))

    value = fresh_advance()
    reject_drift(value, "_settled_stock", ())

    value = fresh_advance()
    reject_drift(value, "_operation", "CAPTURE")

    other_facts = _issued_facts(
        tmp_path / "facts-b",
        monkeypatch,
        (event,),
        identity_char="0",
    )
    value = fresh_advance()
    reject_drift(
        value,
        "_facts_identity",
        other_facts.identity.input_market_facts_sha256,
    )
    _assert_invalid(
        lambda: advance_formal_a_share_entitlements_pre_open(
            date=dates[1], replay=captured_replay, facts=other_facts
        )
    )

    assert captured.postings
    object.__setattr__(captured, "_quantity_inputs", (("600000.SH", 99),))
    _assert_invalid(lambda: captured.postings)
    _assert_invalid(lambda: repr(captured))

    capture_control = capture_formal_a_share_entitlements_record_close(
        date=dates[0],
        replay=day0.replay,
        total_quantities={"600000.SH": 100},
        facts=facts,
    )
    assert capture_control.replay.record_quantities == (("a" * 64, 100),)

    # Fresh originals from the same immutable inputs remain valid after every
    # adversarial variant; attacks never mutate either input replay.
    control = fresh_advance()
    assert len(control.postings) == 4
    assert control.replay.phase is EntitlementReplayPhase.RECORD_CLOSE
