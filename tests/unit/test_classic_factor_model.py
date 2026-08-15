from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.research.classic_factor_model import (
    MODEL_FEATURES,
    MODEL_SCORE,
    ClassicFactorLightgbmSpec,
    build_cross_sectional_rank_features,
    fit_predict_lightgbm_fold,
)
from quant.research.lightweight_run import ResearchFoldV1


def test_cross_sectional_rank_features_are_row_order_invariant() -> None:
    panel = _panel()
    expected = build_cross_sectional_rank_features(panel)
    shuffled = build_cross_sectional_rank_features(
        panel.sample(fraction=1.0, shuffle=True, seed=17)
    )

    assert expected.equals(shuffled)
    rank_columns = [f"{name}_rank" for name in MODEL_FEATURES]
    assert expected.select(rank_columns).null_count().sum_horizontal().item() == 0
    assert expected.select(
        pl.all_horizontal(
            *[pl.col(name).is_between(-0.5, 0.5) for name in rank_columns]
        ).all()
    ).item()


def test_lightgbm_fold_never_reads_test_labels_during_fit() -> None:
    pytest.importorskip("lightgbm")
    panel = _panel()
    fold = _fold()
    spec = _spec()

    first, metadata, model = fit_predict_lightgbm_fold(
        panel, fold=fold, spec=spec, minimum_symbols=10
    )
    poisoned = panel.with_columns(
        pl.when(pl.col("trade_date") >= fold.test_start)
        .then(pl.col("label_20") * -1000.0 + 7.0)
        .otherwise(pl.col("label_20"))
        .alias("label_20")
    )
    second, second_metadata, second_model = fit_predict_lightgbm_fold(
        poisoned, fold=fold, spec=spec, minimum_symbols=10
    )

    first_scores = first.filter(pl.col("period") == "test").select(
        "trade_date", "symbol", MODEL_SCORE
    )
    second_scores = second.filter(pl.col("period") == "test").select(
        "trade_date", "symbol", MODEL_SCORE
    )
    assert first_scores.equals(second_scores)
    assert metadata == second_metadata
    assert model == second_model
    assert 1 <= int(metadata["best_iteration"]) <= spec.num_boost_round
    assert model.startswith(b"tree\n")


def _spec() -> ClassicFactorLightgbmSpec:
    return ClassicFactorLightgbmSpec(
        objective="regression",
        metric="l2",
        device_type="cpu",
        learning_rate=0.05,
        num_leaves=7,
        max_depth=-1,
        feature_fraction=0.9,
        bagging_fraction=0.9,
        bagging_freq=1,
        num_boost_round=30,
        early_stopping_rounds=5,
        seed=20260815,
        num_threads=1,
    )


def _fold() -> ResearchFoldV1:
    return ResearchFoldV1(
        fold=1,
        train_start=dt.date(2020, 1, 1),
        train_end=dt.date(2020, 1, 4),
        validation_start=dt.date(2020, 1, 5),
        validation_end=dt.date(2020, 1, 8),
        test_start=dt.date(2020, 1, 9),
        test_end=dt.date(2020, 1, 12),
    )


def _panel() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for day in range(1, 13):
        date = dt.date(2020, 1, day)
        for index in range(10):
            centered = index - 4.5
            std = centered / 10.0 + day / 1000.0
            roc = -centered / 12.0 + (day % 3) / 100.0
            rsv = index / 10.0
            corr = ((index * day) % 7 - 3) / 5.0
            wvma = ((index + day) % 5) / 4.0
            label = 0.03 * std - 0.02 * roc + 0.01 * corr * wvma
            rows.append(
                {
                    "trade_date": date,
                    "symbol": f"{index:06d}.SH",
                    "alpha158_std20": std,
                    "alpha158_roc20": roc,
                    "alpha158_rsv20": rsv,
                    "alpha158_corr20": corr,
                    "alpha158_wvma20": wvma,
                    "execution_date_20": date,
                    "exit_date_20": date,
                    "label_1": label / 4,
                    "label_5": label / 2,
                    "label_20": label,
                }
            )
    return pl.DataFrame(rows).sort("trade_date", "symbol")
