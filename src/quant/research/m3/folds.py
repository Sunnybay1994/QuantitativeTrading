"""交易日滚动切分与训练标签可知时点过滤。"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import polars as pl

from quant.research.m3.contracts import DateSegment, TemporalFold


def make_temporal_folds(
    *,
    open_dates: Sequence[dt.date],
    train_sessions: int,
    validation_sessions: int,
    test_sessions: int,
    step_sessions: int,
    embargo_sessions: int,
) -> list[TemporalFold]:
    """按交易日计数生成互不重叠且带 embargo 的 walk-forward 折。

    窗口布局::

        [train][embargo][validation][embargo][test]

    尾部不足以容纳完整 test 段时不生成该折。
    """
    if min(
        train_sessions,
        validation_sessions,
        test_sessions,
        step_sessions,
    ) <= 0:
        raise ValueError("train/validation/test/step 会话数必须为正")
    if embargo_sessions < 0:
        raise ValueError("embargo_sessions 不得为负")

    dates = list(open_dates)
    block = (
        train_sessions
        + embargo_sessions
        + validation_sessions
        + embargo_sessions
        + test_sessions
    )
    folds: list[TemporalFold] = []
    start = 0
    fold_idx = 1
    while start + block <= len(dates):
        train_start = start
        train_end = train_start + train_sessions - 1
        valid_start = train_end + 1 + embargo_sessions
        valid_end = valid_start + validation_sessions - 1
        test_start = valid_end + 1 + embargo_sessions
        test_end = test_start + test_sessions - 1
        folds.append(
            TemporalFold(
                name=f"fold_{fold_idx:03d}",
                train=DateSegment(dates[train_start], dates[train_end]),
                validation=DateSegment(dates[valid_start], dates[valid_end]),
                test=DateSegment(dates[test_start], dates[test_end]),
            )
        )
        fold_idx += 1
        start += step_sessions
    return folds


def eligible_training_labels(
    labels: pl.DataFrame, *, fold: TemporalFold
) -> pl.DataFrame:
    """仅保留 as_of 落在训练段且 available_as_of <= train_end 的标签行。"""
    required = {"as_of", "available_as_of"}
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(f"labels 缺少字段: {sorted(missing)}")
    return labels.filter(
        (pl.col("as_of") >= fold.train.start)
        & (pl.col("as_of") <= fold.train.end)
        & (pl.col("available_as_of") <= fold.train.end)
    )
