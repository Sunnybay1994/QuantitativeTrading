import datetime as dt

from quant.research.run_s1_walk_forward import make_folds


def test_walk_forward_builds_only_complete_folds() -> None:
    folds = make_folds(
        start=dt.date(2023, 1, 1),
        end=dt.date(2026, 7, 10),
        train_months=24,
        validation_months=6,
        test_months=6,
        step_months=6,
    )
    assert len(folds) == 2
    assert folds[0].validation_start == dt.date(2025, 1, 1)
    assert folds[0].test_end == dt.date(2025, 12, 31)
    assert folds[1].train_start == dt.date(2023, 7, 1)
    assert folds[1].test_end == dt.date(2026, 6, 30)
