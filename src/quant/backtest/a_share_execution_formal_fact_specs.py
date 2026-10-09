"""Frozen formal G1 table specs for verified market facts."""

from __future__ import annotations

from typing import Any

from quant.domain import (
    Bar1dSchema,
    BenchmarkBar1dSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    InstrumentSchema,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TradeCalendarSchema,
)

_FACT_FILES = (
    "bar_1d.parquet",
    "benchmark_bar_1d.parquet",
    "corporate_action_ledger.parquet",
    "corporate_action_reconciliation.parquet",
    "instrument.parquet",
    "price_limit_1d.parquet",
    "suspension_1d.parquet",
    "trade_calendar.parquet",
)

_FORMAL_FACT_SPECS: dict[
    str, tuple[str, Any, tuple[str, ...], tuple[str, ...]]
] = {
    "instrument.parquet": (
        "instrument", InstrumentSchema, ("symbol",), ("symbol",)
    ),
    "trade_calendar.parquet": (
        "trade_calendar", TradeCalendarSchema,
        ("market", "date"), ("market", "date"),
    ),
    "bar_1d.parquet": (
        "bar_1d", Bar1dSchema,
        ("symbol", "trade_date", "source"),
        ("symbol", "trade_date", "source"),
    ),
    "price_limit_1d.parquet": (
        "price_limit_1d", PriceLimit1dSchema,
        ("symbol", "trade_date", "source"),
        ("symbol", "trade_date", "source"),
    ),
    "suspension_1d.parquet": (
        "suspension_1d", Suspension1dSchema,
        ("symbol", "trade_date", "source"),
        ("symbol", "trade_date", "source"),
    ),
    "corporate_action_ledger.parquet": (
        "corporate_action_ledger", CorporateActionLedgerSchema,
        ("event_id",), ("symbol", "ex_date", "event_id"),
    ),
    "corporate_action_reconciliation.parquet": (
        "corporate_action_reconciliation", CorporateActionReconciliationSchema,
        ("symbol", "previous_factor_date", "effective_date"),
        ("symbol", "previous_factor_date", "effective_date"),
    ),
    "benchmark_bar_1d.parquet": (
        "benchmark_bar_1d", BenchmarkBar1dSchema,
        ("benchmark", "trade_date", "source"),
        ("benchmark", "trade_date", "source"),
    ),
}

_FORMAL_CAPABILITY_FRAME_BINDINGS = (
    ("_instruments", "instrument.parquet"),
    ("_calendar", "trade_calendar.parquet"),
    ("_bars", "bar_1d.parquet"),
    ("_limits", "price_limit_1d.parquet"),
    ("_suspensions", "suspension_1d.parquet"),
    ("_corporate_actions", "corporate_action_ledger.parquet"),
    (
        "_corporate_action_reconciliation",
        "corporate_action_reconciliation.parquet",
    ),
    ("_benchmark_bars", "benchmark_bar_1d.parquet"),
)

_FORMAL_CAPABILITY_FRAME_SLOTS = tuple(
    slot for slot, _ in _FORMAL_CAPABILITY_FRAME_BINDINGS
)
