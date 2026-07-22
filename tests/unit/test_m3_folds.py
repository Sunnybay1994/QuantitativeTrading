"""D2: 交易日 fold 与 embargo。"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

from quant.research.m3.contracts import DateSegment, TemporalFold
from quant.research.m3.folds import eligible_training_labels, make_temporal_folds

FIXTURE_ROOT = Path("tests/fixtures/m3")


def _open_dates() -> list[dt.date]:
    return (
        pl.read_csv(FIXTURE_ROOT / "calendar.csv", try_parse_dates=True)
        .get_column("date")
        .to_list()
    )


def test_expected_folds_match_golden_fixture() -> None:
    folds = make_temporal_folds(
        open_dates=_open_dates(),
        train_sessions=4,
        validation_sessions=2,
        test_sessions=2,
        step_sessions=2,
        embargo_sessions=1,
    )
    expected = pl.read_csv(FIXTURE_ROOT / "expected_folds.csv", try_parse_dates=True)
    assert len(folds) == expected.height
    for fold, row in zip(folds, expected.iter_rows(named=True), strict=True):
        assert fold.name == row["fold"]
        assert fold.train.start == row["train_start"]
        assert fold.train.end == row["train_end"]
        assert fold.validation.start == row["validation_start"]
        assert fold.validation.end == row["validation_end"]
        assert fold.test.start == row["test_start"]
        assert fold.test.end == row["test_end"]


def test_weekends_and_holidays_are_not_counted() -> None:
    # calendar fixture 已跳过周末；若错误按自然日计数则无法匹配 golden
    dates = _open_dates()
    assert dt.date(2026, 1, 10) not in dates  # Saturday
    assert dt.date(2026, 1, 11) not in dates  # Sunday
    folds = make_temporal_folds(
        open_dates=dates,
        train_sessions=4,
        validation_sessions=2,
        test_sessions=2,
        step_sessions=2,
        embargo_sessions=1,
    )
    assert folds[0].validation.start == dt.date(2026, 1, 12)


def test_segments_do_not_overlap() -> None:
    folds = make_temporal_folds(
        open_dates=_open_dates(),
        train_sessions=4,
        validation_sessions=2,
        test_sessions=2,
        step_sessions=2,
        embargo_sessions=1,
    )
    for fold in folds:
        assert fold.train.end < fold.validation.start
        assert fold.validation.end < fold.test.start


def test_incomplete_tail_does_not_create_fold() -> None:
    dates = _open_dates()[:9]  # 需要 10 个交易日才能生成一折
    folds = make_temporal_folds(
        open_dates=dates,
        train_sessions=4,
        validation_sessions=2,
        test_sessions=2,
        step_sessions=2,
        embargo_sessions=1,
    )
    assert folds == []


def test_eligible_training_labels_filter_by_available_as_of() -> None:
    fold = TemporalFold(
        name="fold_001",
        train=DateSegment(dt.date(2026, 1, 5), dt.date(2026, 1, 8)),
        validation=DateSegment(dt.date(2026, 1, 12), dt.date(2026, 1, 13)),
        test=DateSegment(dt.date(2026, 1, 15), dt.date(2026, 1, 16)),
    )
    labels = pl.DataFrame(
        {
            "as_of": [
                dt.date(2026, 1, 5),
                dt.date(2026, 1, 6),
                dt.date(2026, 1, 7),
            ],
            "available_as_of": [
                dt.date(2026, 1, 8),
                dt.date(2026, 1, 12),  # 晚于 train_end，应剔除
                dt.date(2026, 1, 8),
            ],
            "symbol": ["000001.SZ", "000001.SZ", "000002.SZ"],
        }
    )
    eligible = eligible_training_labels(labels, fold=fold)
    assert eligible.get_column("as_of").to_list() == [
        dt.date(2026, 1, 5),
        dt.date(2026, 1, 7),
    ]


def test_reuses_temporal_fold_dataclass() -> None:
    folds = make_temporal_folds(
        open_dates=_open_dates(),
        train_sessions=4,
        validation_sessions=2,
        test_sessions=2,
        step_sessions=2,
        embargo_sessions=1,
    )
    assert isinstance(folds[0], TemporalFold)
    with pytest.raises(ValueError, match="训练段必须早于验证段"):
        TemporalFold(
            name="bad",
            train=DateSegment(dt.date(2026, 1, 5), dt.date(2026, 1, 12)),
            validation=DateSegment(dt.date(2026, 1, 12), dt.date(2026, 1, 13)),
            test=DateSegment(dt.date(2026, 1, 15), dt.date(2026, 1, 16)),
        )
