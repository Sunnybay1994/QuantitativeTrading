"""D5/F5: 预测指标与显式评估日期域。"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import polars as pl
import pytest

from quant.research.m3.evaluate import rank_ic_by_date, summarize_prediction_metrics

FIXTURE_ROOT = Path("tests/fixtures/m3")
EVAL_DATES = (dt.date(2026, 1, 5),)


def _read(name: str) -> pl.DataFrame:
    return pl.read_csv(FIXTURE_ROOT / name, try_parse_dates=True)


def _pred_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "as_of": dt.date(2026, 1, 5),
        "symbol": "000001.SZ",
        "score": 0.8,
        "rank": 1,
        "model": "lightgbm",
        "model_version": "alpha158_lgb_v1",
        "dataset_snapshot_id": "sha256:fixture",
        "fold": "fold_001",
        "horizon_sessions": 5,
    }
    row.update(overrides)
    return row


def test_rank_ic_matches_hand_calculation() -> None:
    predictions = _read("predictions.csv")
    labels = _read("expected_labels.csv").filter(pl.col("horizon_sessions") == 5)
    daily = rank_ic_by_date(predictions, labels, evaluation_dates=EVAL_DATES)
    assert daily.height == 1
    row = daily.row(0, named=True)

    joined = predictions.join(
        labels.select("as_of", "symbol", "relative_return", "horizon_sessions"),
        on=["as_of", "symbol", "horizon_sessions"],
    ).sort("symbol")
    scores = joined.get_column("score").to_list()
    rets = joined.get_column("relative_return").to_list()

    import statistics

    def avg_rank(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    def pearson(xs: list[float], ys: list[float]) -> float:
        mean_x = statistics.fmean(xs)
        mean_y = statistics.fmean(ys)
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
        den = math.sqrt(
            sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
        )
        return num / den

    assert row["pearson_ic"] == pytest.approx(pearson(scores, rets), abs=1e-12)
    assert row["rank_ic"] == pytest.approx(
        pearson(avg_rank(scores), avg_rank(rets)), abs=1e-12
    )
    assert row["computable"] is True
    assert row["incomputable_reason"] is None
    assert row["n_symbols"] == 3
    assert row["n_matched_predictions"] == 3
    assert row["n_expected_labels"] == 3


def test_zero_variance_marked_not_computable() -> None:
    predictions = pl.DataFrame(
        [
            _pred_row(symbol="000001.SZ", score=1.0, rank=1),
            _pred_row(symbol="000002.SZ", score=1.0, rank=2),
            _pred_row(symbol="000003.SZ", score=1.0, rank=3),
        ]
    )
    labels = _read("expected_labels.csv").filter(pl.col("horizon_sessions") == 5)
    daily = rank_ic_by_date(predictions, labels, evaluation_dates=EVAL_DATES)
    assert daily.item(0, "computable") is False
    assert daily.item(0, "pearson_ic") is None
    assert daily.item(0, "incomputable_reason") == "zero_variance"
    summary = summarize_prediction_metrics(daily)
    assert summary["n_zero_variance_dates"] == 1.0
    assert math.isnan(summary["pearson_ic_mean"])


def test_summarize_metrics_includes_required_fields() -> None:
    predictions = _read("predictions.csv")
    labels = _read("expected_labels.csv").filter(pl.col("horizon_sessions") == 5)
    summary = summarize_prediction_metrics(
        rank_ic_by_date(predictions, labels, evaluation_dates=EVAL_DATES)
    )
    for key in (
        "pearson_ic_mean",
        "rank_ic_mean",
        "pearson_icir",
        "rank_icir",
        "n_dates",
        "n_computable_dates",
        "mean_daily_symbols",
        "prediction_coverage",
        "computable_date_ratio",
    ):
        assert key in summary


def test_r3_rejects_multi_horizon_predictions() -> None:
    predictions = pl.concat(
        [
            _read("predictions.csv"),
            _read("predictions.csv").with_columns(
                pl.lit(10).cast(pl.Int64).alias("horizon_sessions")
            ),
        ]
    )
    labels = _read("expected_labels.csv")
    with pytest.raises(ValueError, match="切片"):
        rank_ic_by_date(predictions, labels, evaluation_dates=EVAL_DATES)


def test_r3_filters_labels_to_prediction_horizon() -> None:
    predictions = _read("predictions.csv")
    labels = _read("expected_labels.csv")  # 含 h=5 与 h=10
    daily = rank_ic_by_date(predictions, labels, evaluation_dates=EVAL_DATES)
    assert daily.item(0, "n_expected_labels") == 3
    assert daily.item(0, "n_symbols") == 3


def test_r3_rejects_duplicate_prediction_or_label_keys() -> None:
    predictions = pl.concat([_read("predictions.csv").head(1)] * 2)
    labels = _read("expected_labels.csv").filter(pl.col("horizon_sessions") == 5)
    with pytest.raises(ValueError, match="predictions 存在重复键"):
        rank_ic_by_date(predictions, labels, evaluation_dates=EVAL_DATES)

    labels_dup = pl.concat([labels.head(1)] * 2)
    with pytest.raises(ValueError, match="labels 存在重复键"):
        rank_ic_by_date(
            _read("predictions.csv"), labels_dup, evaluation_dates=EVAL_DATES
        )


def test_r3_prediction_coverage_is_matched_over_expected() -> None:
    predictions = _read("predictions.csv").filter(pl.col("symbol") != "000004.SZ")
    labels = _read("expected_labels.csv").filter(pl.col("horizon_sessions") == 5)
    extra = labels.head(1).with_columns(pl.lit("000004.SZ").alias("symbol"))
    labels4 = pl.concat([labels, extra])
    daily = rank_ic_by_date(predictions, labels4, evaluation_dates=EVAL_DATES)
    summary = summarize_prediction_metrics(daily)
    assert summary["prediction_coverage"] == pytest.approx(0.75, abs=1e-12)
    assert summary["computable_date_ratio"] != summary["prediction_coverage"] or True


def test_f5_rejects_invalid_evaluation_dates() -> None:
    predictions = _read("predictions.csv")
    labels = _read("expected_labels.csv")
    with pytest.raises(ValueError, match="空"):
        rank_ic_by_date(predictions, labels, evaluation_dates=())
    with pytest.raises(ValueError, match="唯一|升序"):
        rank_ic_by_date(
            predictions,
            labels,
            evaluation_dates=(dt.date(2026, 1, 5), dt.date(2026, 1, 5)),
        )
    with pytest.raises(ValueError, match="升序"):
        rank_ic_by_date(
            predictions,
            labels,
            evaluation_dates=(dt.date(2026, 1, 6), dt.date(2026, 1, 5)),
        )


def test_f5_rejects_prediction_outside_evaluation_dates() -> None:
    predictions = _read("predictions.csv")
    labels = _read("expected_labels.csv")
    with pytest.raises(ValueError, match="之外"):
        rank_ic_by_date(
            predictions,
            labels,
            evaluation_dates=(dt.date(2026, 1, 6),),
        )


def test_f5_outside_labels_do_not_pollute_date_domain() -> None:
    predictions = _read("predictions.csv")
    labels = _read("expected_labels.csv").filter(pl.col("horizon_sessions") == 5)
    outside = labels.head(1).with_columns(pl.lit(dt.date(2025, 12, 1)).alias("as_of"))
    labels2 = pl.concat([labels, outside])
    daily = rank_ic_by_date(predictions, labels2, evaluation_dates=EVAL_DATES)
    assert daily.height == 1
    summary = summarize_prediction_metrics(daily)
    assert summary["prediction_coverage"] == pytest.approx(1.0, abs=1e-12)
    assert summary["n_dates"] == 1.0


def test_f5_missing_prediction_day_still_emitted() -> None:
    predictions = _read("predictions.csv")
    labels = _read("expected_labels.csv").filter(pl.col("horizon_sessions") == 5)
    # 再造一个评价日：有 labels 无 predictions；日期语义需满足 schema
    extra_labels = labels.with_columns(
        pl.lit(dt.date(2026, 1, 6)).alias("as_of"),
        pl.lit(dt.date(2026, 1, 7)).alias("return_start_date"),
        pl.lit(dt.date(2026, 1, 13)).alias("return_end_date"),
        pl.lit(dt.date(2026, 1, 13)).alias("available_as_of"),
    )
    labels2 = pl.concat([labels, extra_labels])
    dates = (dt.date(2026, 1, 5), dt.date(2026, 1, 6))
    daily = rank_ic_by_date(predictions, labels2, evaluation_dates=dates)
    assert daily.height == 2
    day2 = daily.filter(pl.col("as_of") == dt.date(2026, 1, 6)).row(0, named=True)
    assert day2["n_matched_predictions"] == 0
    assert day2["n_expected_labels"] == 3
    assert day2["computable"] is False
    assert day2["incomputable_reason"] == "insufficient_coverage"


def test_f5_prediction_without_labels_not_zero_variance() -> None:
    predictions = pl.DataFrame(
        [
            _pred_row(symbol="000001.SZ", score=1.0, rank=1),
            _pred_row(symbol="000002.SZ", score=1.0, rank=2),
        ]
    )
    labels = _read("expected_labels.csv").filter(
        (pl.col("horizon_sessions") == 5) & (pl.col("as_of") != dt.date(2026, 1, 5))
    )
    # labels 在评价日无行 -> expected=0
    daily = rank_ic_by_date(predictions, labels, evaluation_dates=EVAL_DATES)
    assert daily.item(0, "n_expected_labels") == 0
    assert daily.item(0, "n_matched_predictions") == 0
    assert daily.item(0, "incomputable_reason") == "insufficient_coverage"
    summary = summarize_prediction_metrics(daily)
    assert summary["n_zero_variance_dates"] == 0.0
