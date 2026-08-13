"""Focused formal G7D-F1 opening-fact projection tests."""

from __future__ import annotations

import datetime as dt
import inspect
import logging
import socket
from dataclasses import fields
from decimal import Inexact, ROUND_DOWN, localcontext
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_execution as execution
import tests.unit.test_m3_formal_a_share_market_facts as facts_support
from quant.domain import AShareBoard, OpenExecutionStateSchema
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleAShareMarketFacts,
)


_DAY = dt.date(2026, 1, 5)
_FULL_DAY = dt.date(2026, 1, 6)
_SYMBOL = "000001.SZ"
_COLUMNS = [
    "date", "symbol", "open", "has_open", "full_day_suspended",
    "partial_open_status", "has_price_limit", "up_limit", "down_limit",
    "buy_allowed", "sell_allowed", "reason",
]
_DTYPES = [
    pl.Date, pl.Utf8, pl.Float64, pl.Boolean, pl.Boolean, pl.Utf8,
    pl.Boolean, pl.Float64, pl.Float64, pl.Boolean, pl.Boolean, pl.Utf8,
]


def _assert_invalid(callback: Any) -> None:
    with pytest.raises(execution.AShareExecutionError) as caught:
        callback()
    assert type(caught.value) is execution.AShareExecutionError
    assert str(caught.value) == "M3_A_SHARE_EXECUTION_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def _selected(facts: Any) -> dict[str, pl.DataFrame]:
    return {
        "instrument.parquet": facts.instruments,
        "trade_calendar.parquet": facts.calendar,
        "bar_1d.parquet": facts.bars,
        "price_limit_1d.parquet": facts.limits,
        "suspension_1d.parquet": facts.suspensions,
        "corporate_action_ledger.parquet": facts.corporate_actions,
        "corporate_action_reconciliation.parquet": (
            facts.corporate_action_reconciliation
        ),
        "benchmark_bar_1d.parquet": facts.benchmark_bars,
    }


def _reissue(
    facts: Any,
    monkeypatch: pytest.MonkeyPatch,
    **updates: pl.DataFrame,
) -> Any:
    selected = _selected(facts)
    selected.update(updates)
    identity = facts.identity
    provenance = object.__getattribute__(facts, "_provenance")
    monkeypatch.setattr(
        execution,
        "_prepare_verified_a_share_market_facts",
        lambda **kwargs: (identity, selected, provenance),
    )
    return execution.load_verified_a_share_market_facts(
        release=cast(Any, object()),
        plan=cast(Any, object()),
        fresh_context=cast(Any, object()),
        artifact_roots={"formal": Path.cwd()},
    )


def _issued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    return facts_support._issued_capability(tmp_path, monkeypatch)


def _partial_facts(
    facts: Any,
    monkeypatch: pytest.MonkeyPatch,
    detail: object,
) -> Any:
    suspensions = facts.suspensions
    template = suspensions.row(0, named=True)
    partial = pl.DataFrame(
        [{
            **template,
            "symbol": _SYMBOL,
            "trade_date": _DAY,
            "suspension_scope": "PARTIAL",
            "suspension_detail": detail,
        }],
        schema=suspensions.schema,
    )
    return _reissue(
        facts,
        monkeypatch,
        **{"suspension_1d.parquet": partial},
    )


def _limit_facts(
    facts: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    open_value: float,
    upper: float,
    lower: float,
) -> Any:
    bars = facts.bars.with_columns(
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(open_value)).otherwise(pl.col("open")).alias("open"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(open_value + 0.2)).otherwise(pl.col("high")).alias("high"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(open_value - 0.2)).otherwise(pl.col("low")).alias("low"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(open_value)).otherwise(pl.col("close")).alias("close"),
    )
    limits = facts.limits.with_columns(
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(open_value)).otherwise(pl.col("pre_close")).alias("pre_close"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(upper)).otherwise(pl.col("up_limit")).alias("up_limit"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(lower)).otherwise(pl.col("down_limit")).alias("down_limit"),
    )
    return _reissue(
        facts,
        monkeypatch,
        **{"bar_1d.parquet": bars, "price_limit_1d.parquet": limits},
    )


def test_formal_happy_empty_schema_rule_and_return_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    states = execution.build_formal_a_share_open_execution_states(
        facts=facts,
        date=_DAY,
        symbols=("000001.SZ", "000002.SZ", "600000.SH"),
    )
    assert states.columns == _COLUMNS
    assert states.dtypes == _DTYPES
    assert states.equals(states.sort("date", "symbol"))
    assert OpenExecutionStateSchema.validate(states).equals(states)
    assert states.get_column("reason").null_count() == states.height

    empty = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=()
    )
    assert empty.is_empty()
    assert empty.columns == _COLUMNS
    assert empty.dtypes == _DTYPES

    rule = execution.resolve_formal_a_share_order_quantity_rule(
        facts=facts, date=_DAY, symbol="600000.SH"
    )
    assert rule.board is AShareBoard.SSE_MAIN
    assert rule.rule_version == "sse_szse_limit_order_quantity_v1"

    changed = states.with_columns(pl.lit(999.0).alias("open"))
    assert not changed.equals(states)
    again = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    )
    assert again.row(0, named=True)["open"] == 8.0

    for name in ("instruments", "bars", "limits", "suspensions"):
        monkeypatch.setattr(
            execution.VerifiedAShareMarketFacts,
            name,
            property(lambda self, name=name: pytest.fail(name)),
        )
    minimal_empty = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=()
    )
    assert minimal_empty.equals(empty)


def test_exact_input_checks_precede_every_facts_property_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    accesses: list[str] = []
    monkeypatch.setattr(
        execution.VerifiedAShareMarketFacts,
        "identity",
        property(lambda self: accesses.append("identity")),
    )

    invalid_builds = (
        lambda: execution.build_formal_a_share_open_execution_states(
            facts=cast(Any, object()), date=_DAY, symbols=()
        ),
        lambda: execution.build_formal_a_share_open_execution_states(
            facts=facts, date=cast(Any, True), symbols=()
        ),
        lambda: execution.build_formal_a_share_open_execution_states(
            facts=facts, date=_DAY, symbols=cast(Any, [_SYMBOL])
        ),
        lambda: execution.build_formal_a_share_open_execution_states(
            facts=facts, date=_DAY, symbols=(_SYMBOL, _SYMBOL)
        ),
        lambda: execution.build_formal_a_share_open_execution_states(
            facts=facts, date=_DAY, symbols=("600000.SH", _SYMBOL)
        ),
        lambda: execution.build_formal_a_share_open_execution_states(
            facts=facts, date=_DAY, symbols=(cast(Any, 1),)
        ),
    )
    for callback in invalid_builds:
        _assert_invalid(callback)
    _assert_invalid(lambda: execution.resolve_formal_a_share_order_quantity_rule(
        facts=facts, date=cast(Any, True), symbol=_SYMBOL
    ))
    _assert_invalid(lambda: execution.resolve_formal_a_share_order_quantity_rule(
        facts=facts, date=_DAY, symbol=cast(Any, 1)
    ))
    assert accesses == []


def test_fake_and_subclass_fail_before_property_access() -> None:
    accesses: list[str] = []

    class Fake:
        @property
        def identity(self) -> object:
            accesses.append("fake")
            return object()

    class Subclass(execution.VerifiedAShareMarketFacts):
        @property
        def identity(self) -> object:
            accesses.append("subclass")
            return object()

    subclass = object.__new__(Subclass)
    development = object.__new__(VerifiedDevelopmentExampleAShareMarketFacts)
    for value in (Fake(), subclass, development, pl.DataFrame()):
        _assert_invalid(lambda value=value: (
            execution.build_formal_a_share_open_execution_states(
                facts=cast(Any, value), date=_DAY, symbols=()
            )
        ))
        _assert_invalid(lambda value=value: (
            execution.resolve_formal_a_share_order_quantity_rule(
                facts=cast(Any, value), date=_DAY, symbol=_SYMBOL
            )
        ))
    assert accesses == []


def test_date_symbol_instrument_lifecycle_and_potential_domain_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    for day, symbol in (
        (dt.date(2026, 1, 4), _SYMBOL),
        (_DAY, "999999.SZ"),
    ):
        _assert_invalid(lambda day=day, symbol=symbol: (
            execution.build_formal_a_share_open_execution_states(
                facts=facts, date=day, symbols=(symbol,)
            )
        ))
        _assert_invalid(lambda day=day, symbol=symbol: (
            execution.resolve_formal_a_share_order_quantity_rule(
                facts=facts, date=day, symbol=symbol
            )
        ))

    _assert_invalid(lambda: execution.build_formal_a_share_open_execution_states(
        facts=facts, date=dt.date(2026, 1, 4), symbols=()
    ))

    instruments = facts.instruments.with_columns(
        pl.when(pl.col("symbol") == _SYMBOL)
        .then(pl.lit("ETF"))
        .otherwise(pl.col("instrument_type"))
        .alias("instrument_type")
    )
    attacked = _reissue(
        facts, monkeypatch, **{"instrument.parquet": instruments}
    )
    _assert_invalid(lambda: execution.resolve_formal_a_share_order_quantity_rule(
        facts=attacked, date=_DAY, symbol=_SYMBOL
    ))

    missing_bars = facts.bars.filter(
        ~((pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY))
    )
    attacked = _reissue(
        facts, monkeypatch, **{"bar_1d.parquet": missing_bars}
    )
    _assert_invalid(lambda: execution.build_formal_a_share_open_execution_states(
        facts=attacked, date=_DAY, symbols=(_SYMBOL,)
    ))


def test_full_day_without_bar_projects_optional_limit_but_never_trades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    missing_limit = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_FULL_DAY, symbols=(_SYMBOL,)
    ).row(0, named=True)
    assert missing_limit == {
        "date": _FULL_DAY,
        "symbol": _SYMBOL,
        "open": None,
        "has_open": False,
        "full_day_suspended": True,
        "partial_open_status": "NOT_APPLICABLE",
        "has_price_limit": False,
        "up_limit": None,
        "down_limit": None,
        "buy_allowed": False,
        "sell_allowed": False,
        "reason": "SUSPENDED",
    }

    template = facts.limits.row(0, named=True)
    extra = pl.DataFrame(
        [{**template, "symbol": _SYMBOL, "trade_date": _FULL_DAY}],
        schema=facts.limits.schema,
    )
    attacked = _reissue(
        facts,
        monkeypatch,
        **{
            "price_limit_1d.parquet": pl.concat([facts.limits, extra]).sort(
                "symbol", "trade_date", "source"
            )
        },
    )
    row = execution.build_formal_a_share_open_execution_states(
        facts=attacked, date=_FULL_DAY, symbols=(_SYMBOL,)
    ).row(0, named=True)
    assert row["has_price_limit"] is True
    assert (row["up_limit"], row["down_limit"]) == (8.8, 7.2)
    assert row["buy_allowed"] is False and row["sell_allowed"] is False

    extra_bar = facts.bars.row(0, named=True)
    bars = pl.concat([
        facts.bars,
        pl.DataFrame(
            [{**extra_bar, "symbol": _SYMBOL, "trade_date": _FULL_DAY}],
            schema=facts.bars.schema,
        ),
    ]).sort("symbol", "trade_date", "source")
    attacked = _reissue(facts, monkeypatch, **{"bar_1d.parquet": bars})
    _assert_invalid(lambda: execution.build_formal_a_share_open_execution_states(
        facts=attacked, date=_FULL_DAY, symbols=(_SYMBOL,)
    ))


@pytest.mark.parametrize(
    ("detail", "status", "allowed", "reason"),
    [
        ("09:30-10:00", "SUSPENDED_AT_OPEN", False, "SUSPENDED"),
        ("09:00-09:30", "PROVEN_OPEN_TRADABLE", True, None),
        ("09:00-10:00 | 13:00-14:00", "SUSPENDED_AT_OPEN", False, "SUSPENDED"),
        ("09:00-09:29 | 13:00-14:00", "PROVEN_OPEN_TRADABLE", True, None),
        ("09:00-09:29|13:00-14:00", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
        ("24:00-24:30", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
        (" ", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
        ("UNKNOWN", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
    ],
)
def test_partial_interval_boundaries_are_exact_and_conservative(
    detail: object,
    status: str,
    allowed: bool,
    reason: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _partial_facts(_issued(tmp_path, monkeypatch), monkeypatch, detail)
    row = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    ).row(0, named=True)
    assert row["partial_open_status"] == status
    assert row["buy_allowed"] is allowed
    assert row["sell_allowed"] is allowed
    assert row["reason"] == reason


@pytest.mark.parametrize("detail", ["", None])
def test_unreachable_empty_partial_detail_remains_defensively_conservative(
    detail: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    template = facts.suspensions.row(0, named=True)
    hostile = pl.DataFrame(
        [{
            **template,
            "symbol": _SYMBOL,
            "trade_date": _DAY,
            "suspension_scope": "PARTIAL",
            "suspension_detail": detail,
        }],
        schema=facts.suspensions.schema,
    )
    monkeypatch.setattr(
        execution.VerifiedAShareMarketFacts,
        "suspensions",
        property(lambda self: hostile.clone()),
    )
    row = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    ).row(0, named=True)
    assert row["partial_open_status"] == "OPEN_UNKNOWN"
    assert row["buy_allowed"] is False and row["sell_allowed"] is False
    assert row["reason"] == "OPEN_UNKNOWN"


@pytest.mark.parametrize(
    ("upper", "lower", "buy_allowed", "sell_allowed"),
    [
        (10.0049, 9.0, False, True),
        (10.005, 9.0, False, True),
        (10.0051, 9.0, True, True),
        (11.0, 9.9951, True, False),
        (11.0, 9.995, True, False),
        (11.0, 9.9949, True, True),
    ],
)
def test_half_tick_uses_exact_decimal_inclusive_boundary(
    upper: float,
    lower: float,
    buy_allowed: bool,
    sell_allowed: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _limit_facts(
        _issued(tmp_path, monkeypatch),
        monkeypatch,
        open_value=10.0,
        upper=upper,
        lower=lower,
    )
    row = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    ).row(0, named=True)
    assert row["buy_allowed"] is buy_allowed
    assert row["sell_allowed"] is sell_allowed


def test_formal_public_apis_are_ambient_decimal_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _limit_facts(
        _issued(tmp_path, monkeypatch),
        monkeypatch,
        open_value=10.0,
        upper=10.005,
        lower=9.9949,
    )
    states: list[pl.DataFrame] = []
    rules: list[execution.AShareOrderQuantityRule] = []
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
            states.append(execution.build_formal_a_share_open_execution_states(
                facts=facts, date=_DAY, symbols=(_SYMBOL,)
            ))
            rules.append(execution.resolve_formal_a_share_order_quantity_rule(
                facts=facts, date=_DAY, symbol=_SYMBOL
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

    assert states[0].row(0, named=True)["buy_allowed"] is False
    assert states[0].row(0, named=True)["sell_allowed"] is True
    for state in states[1:]:
        assert state.schema == states[0].schema
        assert state.to_dicts() == states[0].to_dicts()
    for rule in rules[1:]:
        for field in fields(rules[0]):
            assert getattr(rule, field.name) == getattr(rules[0], field.name)


def test_future_bar_fields_and_forbidden_properties_are_not_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    baseline = execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    )
    changed_bars = facts.bars.with_columns(
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(888.0)).otherwise(pl.col("high")).alias("high"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(0.1)).otherwise(pl.col("low")).alias("low"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(777.0)).otherwise(pl.col("close")).alias("close"),
        pl.when(
            (pl.col("symbol") == _SYMBOL) & (pl.col("trade_date") == _DAY)
        ).then(pl.lit(999999.0)).otherwise(pl.col("volume")).alias("volume"),
    )
    changed = _reissue(
        facts, monkeypatch, **{"bar_1d.parquet": changed_bars}
    )
    forbidden: list[str] = []
    for name in (
        "calendar", "corporate_actions", "corporate_action_reconciliation",
    ):
        monkeypatch.setattr(
            execution.VerifiedAShareMarketFacts,
            name,
            property(lambda self, name=name: forbidden.append(name)),
        )
    actual = execution.build_formal_a_share_open_execution_states(
        facts=changed, date=_DAY, symbols=(_SYMBOL,)
    )
    assert actual.equals(baseline)
    assert forbidden == []


def test_hostile_property_and_parser_errors_are_stably_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)

    def hostile_property(self: object) -> object:
        raise RuntimeError("C:/PRIVATE/TOKEN_SQL_PID_12345/600000.SH")

    monkeypatch.setattr(
        execution.VerifiedAShareMarketFacts,
        "bars",
        property(hostile_property),
    )
    _assert_invalid(lambda: execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    ))

    monkeypatch.undo()
    facts = _partial_facts(
        _issued(tmp_path, monkeypatch), monkeypatch, "09:00-10:00"
    )
    monkeypatch.setattr(
        execution,
        "_partial_open_status",
        lambda detail: (_ for _ in ()).throw(RuntimeError("TOKEN_DETAIL")),
    )
    _assert_invalid(lambda: execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    ))


def test_formal_projection_and_rule_have_no_io_network_or_log_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _issued(tmp_path, monkeypatch)
    calls: list[str] = []

    def unexpected(*args: object, **kwargs: object) -> None:
        calls.append("side-effect")
        raise AssertionError

    monkeypatch.setattr(Path, "open", unexpected)
    monkeypatch.setattr(Path, "mkdir", unexpected)
    monkeypatch.setattr(socket, "socket", unexpected)
    monkeypatch.setattr(logging.Logger, "_log", unexpected)
    execution.build_formal_a_share_open_execution_states(
        facts=facts, date=_DAY, symbols=(_SYMBOL,)
    )
    execution.resolve_formal_a_share_order_quantity_rule(
        facts=facts, date=_DAY, symbol=_SYMBOL
    )
    assert calls == []


def test_no_formal_downstream_accepts_bare_open_state_frame() -> None:
    public_formal = (
        execution.build_formal_a_share_open_execution_states,
        execution.resolve_formal_a_share_order_quantity_rule,
    )
    for callback in public_formal:
        assert "open_states" not in inspect.signature(callback).parameters
