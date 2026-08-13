"""Five-session hand-checkable golden replay for formal G7E."""

from __future__ import annotations

import datetime as dt
import importlib.util
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_simulator as simulator_module
from quant.research.m3.contracts import VerifiedBacktestPlanArtifact

_UNIT_SPEC = importlib.util.spec_from_file_location(
    "m3_g7e_unit_support",
    Path(__file__).parents[1] / "unit" / "test_m3_g7e_formal_a_share_simulator.py",
)
assert _UNIT_SPEC is not None and _UNIT_SPEC.loader is not None
_UNIT = importlib.util.module_from_spec(_UNIT_SPEC)
_UNIT_SPEC.loader.exec_module(_UNIT)


def _golden_frames(
    frames: dict[str, pl.DataFrame],
    sessions: tuple[dt.date, ...],
) -> dict[str, pl.DataFrame]:
    result = dict(frames)
    result["corporate_action_ledger.parquet"] = frames[
        "corporate_action_ledger.parquet"
    ].with_columns(
        pl.lit("000001.SZ").alias("symbol"),
        pl.lit(0.1).alias("stock_ratio"),
        pl.lit(sessions[4], dtype=pl.Date).alias("pay_date"),
        pl.lit(sessions[3], dtype=pl.Date).alias("stock_list_date"),
    )
    ratio = 8.0 / ((8.0 - 0.1) / 1.1)
    result["corporate_action_reconciliation.parquet"] = frames[
        "corporate_action_reconciliation.parquet"
    ].with_columns(
        pl.lit("000001.SZ").alias("symbol"),
        pl.lit(8.0).alias("previous_close"),
        pl.lit((8.0 - 0.1) / 1.1).alias("ex_reference_price"),
        pl.lit("[0.1]").alias("stock_ratio_terms_json"),
        pl.lit("1" * 64).alias("stock_ratio_terms_sha256"),
        pl.lit(0.1).alias("stock_ratio"),
        pl.lit(ratio).alias("declared_dividend_factor_ratio"),
        pl.lit(ratio).alias("market_reference_factor_ratio"),
        pl.lit(ratio).alias("actual_factor_ratio"),
    )
    day = sessions[1]
    result["bar_1d.parquet"] = frames["bar_1d.parquet"].with_columns(
        *(
            pl.when((pl.col("symbol") == "600000.SH") & (pl.col("trade_date") == day))
            .then(pl.lit(11.0))
            .otherwise(pl.col(field))
            .alias(field)
            for field in ("open", "high", "low", "close")
        )
    )
    result["price_limit_1d.parquet"] = frames[
        "price_limit_1d.parquet"
    ].with_columns(
        pl.when(
            (pl.col("symbol") == "000002.SZ")
            & (pl.col("trade_date") == sessions[4])
        )
        .then(pl.lit(5.995))
        .otherwise(pl.col("down_limit"))
        .alias("down_limit")
    )
    return result


@pytest.fixture(scope="module")
def golden_case(tmp_path_factory: pytest.TempPathFactory) -> Any:
    monkeypatch = pytest.MonkeyPatch()
    weights = (
        (0.4, 0.3, 0.2),
        (0.1, 0.3, 0.5),
        (0.0, 0.1, 0.6),
        (0.0, 0.1, 0.0),
        (0.0, 0.0, 0.0),
    )
    try:
        yield _UNIT._case(
            tmp_path_factory.mktemp("m3-g7e-golden"),
            monkeypatch,
            weights,
            _golden_frames,
        )
    finally:
        monkeypatch.undo()


def test_five_session_three_security_golden(
    golden_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = cast(VerifiedBacktestPlanArtifact, golden_case["plan"])
    monkeypatch.setattr(
        simulator_module, "verify_backtest_plan_artifact", lambda **_: plan
    )
    result = simulator_module.simulate_formal_a_share_scenario(**golden_case)
    sessions = plan.manifest.window.execution_dates
    assert result.multiplier == Decimal("1")
    assert result.nav.height == result.daily_diagnostics.height == 5
    assert result.nav["date"].to_list() == list(sessions)
    assert result.nav["cash"].to_list() == pytest.approx(
        [9852.05, 9852.05, 27435.78, 93278.6, 93778.6]
    )
    assert result.nav["market_value"].to_list() == pytest.approx(
        [90000.0, 87909.09090909091, 72200.0, 10200.0, 10200.0]
    )
    assert result.nav["cash_receivable"].to_list() == pytest.approx(
        [0.0, 500.0, 500.0, 500.0, 0.0]
    )
    assert result.nav["stock_receivable_value"].to_list() == pytest.approx(
        [0.0, 3590.909090909091, 4000.0, 0.0, 0.0]
    )
    assert result.nav["equity"].to_list() == pytest.approx(
        [99852.05, 101852.05, 104135.78, 103978.6, 103978.6]
    )

    assert result.trades.select("date", "symbol", "side", "quantity").rows() == [
        (sessions[0], "000001.SZ", "BUY", 5000),
        (sessions[0], "000002.SZ", "BUY", 5000),
        (sessions[0], "600000.SH", "BUY", 2000),
        (sessions[2], "000001.SZ", "SELL", 5000),
        (sessions[2], "000002.SZ", "SELL", 3300),
        (sessions[2], "600000.SH", "BUY", 4200),
        (sessions[3], "000001.SZ", "SELL", 500),
        (sessions[3], "600000.SH", "SELL", 6200),
    ]
    minimum_commission = result.trades.filter(
        (pl.col("date") == sessions[3]) & (pl.col("symbol") == "000001.SZ")
    )
    assert minimum_commission.item(0, "commission") == 5.0

    assert result.positions.select(
        "date", "symbol", "quantity", "sellable_quantity",
        "unsettled_quantity", "pending_exit",
    ).rows() == [
        (sessions[0], "000001.SZ", 5000, 0, 5000, False),
        (sessions[0], "000002.SZ", 5000, 0, 5000, False),
        (sessions[0], "600000.SH", 2000, 0, 2000, False),
        (sessions[1], "000001.SZ", 5000, 5000, 0, False),
        (sessions[1], "000002.SZ", 5000, 5000, 0, False),
        (sessions[1], "600000.SH", 2000, 2000, 0, False),
        (sessions[2], "000002.SZ", 1700, 1700, 0, False),
        (sessions[2], "600000.SH", 6200, 2000, 4200, False),
        (sessions[3], "000002.SZ", 1700, 1700, 0, False),
        (sessions[4], "000002.SZ", 1700, 1700, 0, True),
    ]
    adjusted = result.positions.filter(
        (pl.col("date") == sessions[1]) & (pl.col("symbol") == "000001.SZ")
    )
    assert adjusted.item(0, "mark_price") == pytest.approx((8.0 - 0.1) / 1.1)
    assert adjusted.item(0, "target_quantity") is None

    assert result.rejections.select(
        "date", "symbol", "side", "reason", "requested_quantity",
        "rejected_quantity",
    ).rows() == [
        (sessions[1], "000001.SZ", "SELL", "SUSPENDED", None, None),
        (sessions[1], "600000.SH", "BUY", "BUY_AT_UPPER_LIMIT", 2629, 2629),
        (sessions[2], "600000.SH", "BUY", "LOT_CONSTRAINT", 61, 61),
        (
            sessions[4], "000002.SZ", "SELL", "SELL_AT_LOWER_LIMIT", 1700, 1700
        ),
    ]

    assert result.corporate_action_postings.select(
        "date", "posting_type", "cash_amount", "stock_quantity",
    ).rows() == [
        (sessions[0], "CAPTURE", 0.0, 0),
        (sessions[1], "CASH_RECOGNIZE", 0.0, 0),
        (sessions[1], "STOCK_RECOGNIZE", 0.0, 0),
        (sessions[3], "STOCK_SETTLE", 0.0, 500),
        (sessions[4], "CASH_SETTLE", 500.0, 0),
    ]
    assert result.entitlements.select(
        "date", "record_quantity", "cash_state", "stock_state",
        "cash_receivable", "stock_receivable",
    ).rows() == [
        (sessions[0], 5000, "CAPTURED", "CAPTURED", 0.0, 0),
        (sessions[1], 5000, "RECOGNIZED", "RECOGNIZED", 500.0, 500),
        (sessions[2], 5000, "RECOGNIZED", "RECOGNIZED", 500.0, 500),
        (sessions[3], 5000, "RECOGNIZED", "SETTLED", 500.0, 0),
    ]

    diagnostics = result.daily_diagnostics
    assert diagnostics.select(
        "date", "n_order_intents", "n_trades", "n_rejections",
    ).rows() == [
        (sessions[0], 3, 3, 0),
        (sessions[1], 2, 0, 2),
        (sessions[2], 3, 3, 1),
        (sessions[3], 2, 2, 0),
        (sessions[4], 1, 0, 1),
    ]
    assert diagnostics["one_way_turnover"].to_list() == pytest.approx(
        [value / 2 for value in diagnostics["gross_turnover"].to_list()]
    )
    asymmetric = diagnostics.row(2, named=True)
    max_side_turnover = max(39950.0 + 19767.0, 42042.0) / cast(
        float, asymmetric["pre_trade_equity"]
    )
    assert asymmetric["one_way_turnover"] != pytest.approx(max_side_turnover)
