from __future__ import annotations

import datetime as dt

import polars as pl
import pytest
from pandera.errors import SchemaError

from quant.factors.classic import (
    CLASSIC_FACTOR_NAMES,
    CLASSIC_FACTOR_SPECS,
    compute_classic_daily_factors,
)
from quant.research.factor_labels import build_next_open_factor_labels


def _bars(*, split: bool = False, zero_last_volume: bool = False) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = dt.date(2025, 1, 1)
    for index in range(25):
        adjusted_close = 10.0 + index
        factor = 2.0 if split and index >= 10 else 1.0
        raw_close = adjusted_close / factor
        volume = 0.0 if zero_last_volume and index == 24 else 1_000.0 + index
        rows.append(
            {
                "symbol": "600001.SH",
                "trade_date": start + dt.timedelta(days=index),
                "open": (adjusted_close - 0.5) / factor,
                "high": (adjusted_close + 1.0) / factor,
                "low": (adjusted_close - 1.0) / factor,
                "close": raw_close,
                "volume": volume,
                "amount": volume * raw_close,
                "adj_factor": factor,
                "source": "fixture",
            }
        )
    return pl.DataFrame(rows)


def test_catalog_is_de_duplicated_and_formulas_match_hand_values() -> None:
    assert tuple(spec.name for spec in CLASSIC_FACTOR_SPECS) == CLASSIC_FACTOR_NAMES
    assert len(CLASSIC_FACTOR_NAMES) == len(set(CLASSIC_FACTOR_NAMES)) == 6
    factors = compute_classic_daily_factors(_bars())
    last = factors.tail(1)
    assert last.get_column("history_rows").item() == 25
    assert last.get_column("alpha101_033").item() == pytest.approx(1.0 - 33.5 / 34.0)
    assert last.get_column("alpha101_101").item() == pytest.approx(0.5 / 2.001)
    assert last.get_column("alpha158_roc20").item() == pytest.approx(14.0 / 34.0)
    assert last.get_column("alpha158_rsv20").item() == pytest.approx(20.0 / 21.0)
    assert last.get_column("alpha158_vma20").item() == pytest.approx(1014.5 / 1024.0)


def test_cross_session_price_factors_are_split_adjustment_invariant() -> None:
    plain = compute_classic_daily_factors(_bars())
    split = compute_classic_daily_factors(_bars(split=True))
    columns = ["alpha158_roc20", "alpha158_std20", "alpha158_rsv20"]
    assert plain.select(columns).equals(split.select(columns), null_equal=True)


def test_zero_current_volume_is_null_and_duplicate_key_is_rejected() -> None:
    result = compute_classic_daily_factors(_bars(zero_last_volume=True))
    assert result.tail(1).get_column("alpha158_vma20").item() is None
    duplicate = pl.concat([_bars(), _bars().tail(1)])
    with pytest.raises(SchemaError, match="symbol_date_source_unique"):
        compute_classic_daily_factors(duplicate)


def test_next_open_labels_use_exact_exchange_sessions_without_skipping() -> None:
    sessions = tuple(dt.date(2025, 1, 1) + dt.timedelta(days=index) for index in range(5))
    bars = pl.DataFrame(
        {
            "symbol": ["600001.SH"] * 4,
            "trade_date": [sessions[0], sessions[2], sessions[3], sessions[4]],
            "open": [10.0, 12.0, 13.0, 14.0],
            "high": [11.0, 13.0, 14.0, 15.0],
            "low": [9.0, 11.0, 12.0, 13.0],
            "close": [10.5, 12.5, 13.5, 14.5],
            "volume": [100.0] * 4,
            "amount": [1_000.0, 1_200.0, 1_300.0, 1_400.0],
            "adj_factor": [1.0] * 4,
            "source": ["fixture"] * 4,
        }
    )
    factor_values = pl.DataFrame(
        {"symbol": ["600001.SH", "600001.SH"], "trade_date": sessions[:2], "score": [1.0, 2.0]}
    )
    labels = build_next_open_factor_labels(
        factor_values=factor_values,
        bars=bars,
        sessions=sessions,
        horizons=(1, 2),
    )
    first = labels.filter(pl.col("trade_date") == sessions[0])
    assert first.get_column("execution_date_1").item() == sessions[1]
    assert first.get_column("entry_open_1").item() is None
    assert first.get_column("label_1").item() is None
    second = labels.filter(pl.col("trade_date") == sessions[1])
    assert second.get_column("label_1").item() == pytest.approx(13.0 / 12.0 - 1.0)
    assert second.get_column("label_2").item() == pytest.approx(14.0 / 12.0 - 1.0)


def test_label_does_not_depend_on_same_day_close_or_factor_value() -> None:
    bars = _bars().head(4)
    sessions = tuple(bars.get_column("trade_date").to_list())
    base = pl.DataFrame(
        {"symbol": ["600001.SH"], "trade_date": [sessions[0]], "score": [1.0]}
    )
    changed = base.with_columns(pl.lit(-999.0).alias("score"))
    first = build_next_open_factor_labels(
        factor_values=base, bars=bars, sessions=sessions, horizons=(1,)
    )
    second = build_next_open_factor_labels(
        factor_values=changed, bars=bars, sessions=sessions, horizons=(1,)
    )
    assert first.get_column("label_1").item() == second.get_column("label_1").item()
