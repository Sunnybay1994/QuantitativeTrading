"""预测指标：按日 Rank IC / Pearson IC 与汇总。不 import Qlib/MLflow。"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence

import polars as pl

from quant.domain import ForwardReturnLabelSchema, PredictionScoreSchema

_IDENTITY_COLS = (
    "model",
    "model_version",
    "dataset_snapshot_id",
    "fold",
    "horizon_sessions",
)


def rank_ic_by_date(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    evaluation_dates: Sequence[dt.date],
) -> pl.DataFrame:
    """按 evaluation_dates 计算截面 Pearson IC 与 Spearman Rank IC。

    每次只接受一个预测身份切片；零方差截面记为不可计算，不得静默填 0。
    日期域由 ``evaluation_dates`` 冻结：区间外预测拒绝；区间外 labels 不影响输出。
    """
    _assert_evaluation_dates(evaluation_dates)
    eval_set = set(evaluation_dates)

    _assert_unique_prediction_keys(predictions)
    _assert_unique_label_keys(labels)
    predictions = PredictionScoreSchema.validate(predictions)
    labels = ForwardReturnLabelSchema.validate(labels)
    _assert_single_prediction_slice(predictions)

    pred_dates = set(predictions.get_column("as_of").unique().to_list())
    outside = sorted(pred_dates - eval_set)
    if outside:
        raise ValueError(
            "predictions 存在 evaluation_dates 之外的日期: "
            + ", ".join(d.isoformat() for d in outside)
        )

    horizon = int(predictions.get_column("horizon_sessions").unique().to_list()[0])
    labels_h = labels.filter(
        (pl.col("horizon_sessions") == horizon)
        & pl.col("as_of").is_in(list(evaluation_dates))
    )
    expected_by_date = (
        labels_h.group_by("as_of")
        .agg(pl.len().alias("n_expected_labels"))
        .sort("as_of")
    )

    joined = (
        predictions.select("as_of", "symbol", "score", "horizon_sessions")
        .join(
            labels_h.select("as_of", "symbol", "relative_return", "horizon_sessions"),
            on=["as_of", "symbol", "horizon_sessions"],
            how="inner",
        )
        .sort(["as_of", "symbol"])
    )

    expected_map = {
        row["as_of"]: int(row["n_expected_labels"])
        for row in expected_by_date.iter_rows(named=True)
    }

    rows: list[dict[str, object]] = []
    for as_of in evaluation_dates:
        group = joined.filter(pl.col("as_of") == as_of)
        scores = group.get_column("score").to_list() if not group.is_empty() else []
        rets = (
            group.get_column("relative_return").to_list() if not group.is_empty() else []
        )
        n_matched = len(scores)
        n_expected = expected_map.get(as_of, 0)
        pearson = _pearson(scores, rets) if n_matched else None
        spearman = _spearman(scores, rets) if n_matched else None
        computable = pearson is not None and spearman is not None
        reason = _incomputable_reason(
            computable=computable,
            n_expected=n_expected,
            n_matched=n_matched,
            pearson=pearson,
            spearman=spearman,
        )
        rows.append(
            {
                "as_of": as_of,
                "n_expected_labels": n_expected,
                "n_matched_predictions": n_matched,
                "n_symbols": n_matched,
                "pearson_ic": pearson,
                "rank_ic": spearman,
                "computable": computable,
                "incomputable_reason": reason,
            }
        )

    return pl.DataFrame(rows).sort("as_of")


def summarize_prediction_metrics(daily_ic: pl.DataFrame) -> dict[str, float]:
    """汇总 IC/ICIR、覆盖率与可计算日比例。"""
    if daily_ic.is_empty():
        return {
            "pearson_ic_mean": float("nan"),
            "rank_ic_mean": float("nan"),
            "pearson_icir": float("nan"),
            "rank_icir": float("nan"),
            "n_dates": 0.0,
            "n_computable_dates": 0.0,
            "n_zero_variance_dates": 0.0,
            "mean_daily_symbols": float("nan"),
            "prediction_coverage": float("nan"),
            "computable_date_ratio": float("nan"),
        }

    computable = daily_ic.filter(pl.col("computable"))
    n_dates = float(daily_ic.height)
    n_computable = float(computable.height)
    if "incomputable_reason" in daily_ic.columns:
        n_zero_var = float(
            daily_ic.filter(pl.col("incomputable_reason") == "zero_variance").height
        )
    else:
        n_zero_var = float(daily_ic.filter(~pl.col("computable")).height)
    matched = float(daily_ic.get_column("n_matched_predictions").sum())
    expected = float(daily_ic.get_column("n_expected_labels").sum())

    pearson_vals = [
        v for v in computable.get_column("pearson_ic").to_list() if v is not None
    ]
    rank_vals = [
        v for v in computable.get_column("rank_ic").to_list() if v is not None
    ]

    return {
        "pearson_ic_mean": _mean(pearson_vals),
        "rank_ic_mean": _mean(rank_vals),
        "pearson_icir": _icir(pearson_vals),
        "rank_icir": _icir(rank_vals),
        "n_dates": n_dates,
        "n_computable_dates": n_computable,
        "n_zero_variance_dates": n_zero_var,
        "mean_daily_symbols": _as_float(daily_ic.get_column("n_symbols").mean()),
        "prediction_coverage": matched / expected if expected else float("nan"),
        "computable_date_ratio": n_computable / n_dates if n_dates else float("nan"),
    }


def _assert_evaluation_dates(evaluation_dates: Sequence[dt.date]) -> None:
    if not evaluation_dates:
        raise ValueError("evaluation_dates 不得为空")
    if len(evaluation_dates) != len(set(evaluation_dates)):
        raise ValueError("evaluation_dates 必须唯一")
    if list(evaluation_dates) != sorted(evaluation_dates):
        raise ValueError("evaluation_dates 必须严格升序")
    for i in range(1, len(evaluation_dates)):
        if evaluation_dates[i] <= evaluation_dates[i - 1]:
            raise ValueError("evaluation_dates 必须严格升序")


def _incomputable_reason(
    *,
    computable: bool,
    n_expected: int,
    n_matched: int,
    pearson: float | None,
    spearman: float | None,
) -> str | None:
    if computable:
        return None
    # 无标签日不得记为零方差，即使 matched>0
    if n_expected == 0:
        return "insufficient_coverage"
    if n_matched < 2:
        return "insufficient_coverage"
    if pearson is None or spearman is None:
        return "zero_variance"
    return "insufficient_coverage"


def _assert_single_prediction_slice(predictions: pl.DataFrame) -> None:
    keys = predictions.select(list(_IDENTITY_COLS)).unique()
    if keys.height != 1:
        raise ValueError(
            "predictions 必须只包含一个 "
            "(model,model_version,dataset_snapshot_id,fold,horizon_sessions) 切片"
        )


def _assert_unique_prediction_keys(predictions: pl.DataFrame) -> None:
    key_cols = ["as_of", "symbol", *_IDENTITY_COLS]
    dup = predictions.group_by(key_cols).len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise ValueError("predictions 存在重复键")


def _assert_unique_label_keys(labels: pl.DataFrame) -> None:
    dup = (
        labels.group_by("as_of", "symbol", "horizon_sessions")
        .len()
        .filter(pl.col("len") > 1)
    )
    if not dup.is_empty():
        raise ValueError("labels 存在重复键")


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float("nan")


def _mean(values: list[float]) -> float:
    if not values:
        return float("nan")
    return sum(values) / len(values)


def _icir(values: list[float]) -> float:
    if len(values) < 2:
        return float("nan")
    mean = _mean(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    std = math.sqrt(var)
    if std == 0.0:
        return float("nan")
    return mean / std


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return None
    return num / (den_x * den_y)


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    return _pearson(_average_ranks(xs), _average_ranks(ys))


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks
