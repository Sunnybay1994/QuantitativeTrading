"""D6: 分数标准化与无状态 Top-k（含返工 R4）。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.domain import TargetWeightSchema
from quant.strategies.ml_topk import MlTopkStrategy, normalize_prediction_scores

FIXTURE_ROOT = Path("tests/fixtures/m3")


def _read(name: str) -> pl.DataFrame:
    return pl.read_csv(FIXTURE_ROOT / name, try_parse_dates=True)


def _strategy_input() -> pl.DataFrame:
    predictions = _read("predictions.csv")
    eligibility = _read("eligibility_2026-01-05.csv")
    return predictions.join(eligibility, on="symbol")


def test_golden_targets_match_top2_with_cash_buffer() -> None:
    strategy = MlTopkStrategy(top_k=2, cash_buffer=0.1)
    targets = strategy.target_weights(dt.date(2026, 1, 5), _strategy_input())
    expected = _read("expected_targets.csv")
    TargetWeightSchema.validate(targets)
    got = targets.sort("symbol")
    exp = expected.sort("symbol")
    assert got.select(["as_of", "strategy", "strategy_version", "symbol"]).equals(
        exp.select(["as_of", "strategy", "strategy_version", "symbol"])
    )
    for left, right in zip(
        got.get_column("weight").to_list(),
        exp.get_column("weight").to_list(),
        strict=True,
    ):
        assert left == pytest.approx(right, abs=1e-12)


def test_score_tie_broken_by_symbol_asc() -> None:
    frame = pl.DataFrame(
        {
            "as_of": [dt.date(2026, 1, 5)] * 2,
            "symbol": ["000002.SZ", "000001.SZ"],
            "score": [0.5, 0.5],
            "model": ["lightgbm"] * 2,
            "model_version": ["v1"] * 2,
            "dataset_snapshot_id": ["sha256:x"] * 2,
            "fold": ["fold_001"] * 2,
            "horizon_sessions": [5] * 2,
        }
    )
    ranked = normalize_prediction_scores(frame)
    assert ranked.sort("symbol").get_column("rank").to_list() == [1, 2]


def test_empty_cross_section_returns_empty_targets() -> None:
    strategy = MlTopkStrategy(top_k=2, cash_buffer=0.1)
    data = _strategy_input().head(0)
    targets = strategy.target_weights(dt.date(2026, 1, 5), data)
    assert targets.is_empty()


def test_eligibility_filters_before_topk() -> None:
    strategy = MlTopkStrategy(top_k=2, cash_buffer=0.1)
    targets = strategy.target_weights(dt.date(2026, 1, 5), _strategy_input())
    assert targets.filter(pl.col("symbol") == "000003.SZ").item(0, "weight") == 0.0
    positive = targets.filter(pl.col("weight") > 0).get_column("symbol").to_list()
    assert set(positive) == {"000001.SZ", "000004.SZ"}


def test_max_weight_caps_position() -> None:
    strategy = MlTopkStrategy(top_k=2, cash_buffer=0.0, max_weight=0.3)
    targets = strategy.target_weights(dt.date(2026, 1, 5), _strategy_input())
    positive = targets.filter(pl.col("weight") > 0)
    assert positive.get_column("weight").max() == pytest.approx(0.3)
    assert positive.get_column("weight").sum() == pytest.approx(0.6)


def test_explicit_zero_targets_for_non_selected() -> None:
    strategy = MlTopkStrategy(top_k=2, cash_buffer=0.1)
    targets = strategy.target_weights(dt.date(2026, 1, 5), _strategy_input())
    zeros = targets.filter(pl.col("weight") == 0).get_column("symbol").to_list()
    assert "000002.SZ" in zeros
    assert "000003.SZ" in zeros


def test_r4_rejects_multi_horizon_same_day() -> None:
    data = pl.concat(
        [
            _strategy_input(),
            _strategy_input().with_columns(
                pl.lit(10).cast(pl.Int64).alias("horizon_sessions")
            ),
        ]
    )
    strategy = MlTopkStrategy(top_k=2, cash_buffer=0.1)
    with pytest.raises(ValueError, match="切片"):
        strategy.target_weights(dt.date(2026, 1, 5), data)


def test_r4_rejects_multi_model_fold_snapshot() -> None:
    strategy = MlTopkStrategy(top_k=2, cash_buffer=0.1)
    for col, value in (
        ("model_version", "other_v1"),
        ("fold", "fold_002"),
        ("dataset_snapshot_id", "sha256:other"),
    ):
        data = pl.concat(
            [
                _strategy_input(),
                _strategy_input().with_columns(pl.lit(value).alias(col)),
            ]
        )
        with pytest.raises(ValueError, match="切片"):
            strategy.target_weights(dt.date(2026, 1, 5), data)


def test_r4_rejects_conflicting_eligibility() -> None:
    data = _strategy_input()
    conflict = data.filter(pl.col("symbol") == "000001.SZ").with_columns(
        pl.lit(False).alias("eligible")
    )
    with pytest.raises(ValueError, match="冲突"):
        MlTopkStrategy(top_k=2, cash_buffer=0.1).target_weights(
            dt.date(2026, 1, 5), pl.concat([data, conflict])
        )


def test_r4_total_weight_respects_cash_buffer_and_max_weight() -> None:
    no_cap = MlTopkStrategy(top_k=2, cash_buffer=0.1).target_weights(
        dt.date(2026, 1, 5), _strategy_input()
    )
    assert no_cap.get_column("weight").sum() == pytest.approx(0.9, abs=1e-12)

    capped = MlTopkStrategy(top_k=2, cash_buffer=0.1, max_weight=0.3).target_weights(
        dt.date(2026, 1, 5), _strategy_input()
    )
    assert capped.get_column("weight").max() <= 0.3 + 1e-12
    assert capped.get_column("weight").sum() <= 0.9 + 1e-12
    assert capped.get_column("weight").sum() == pytest.approx(0.6, abs=1e-12)
