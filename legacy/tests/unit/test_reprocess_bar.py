import datetime as dt

import pytest

from quant.data.reprocess_bar import _resolve_range


def test_reprocess_range_accepts_single_date_or_explicit_interval() -> None:
    date = dt.date(2026, 7, 10)
    assert _resolve_range(date, None, None) == (date, date)
    assert _resolve_range(None, dt.date(2026, 7, 1), date) == (
        dt.date(2026, 7, 1),
        date,
    )


def test_reprocess_range_rejects_ambiguous_or_incomplete_arguments() -> None:
    with pytest.raises(ValueError, match="同时使用"):
        _resolve_range(
            dt.date(2026, 7, 10), dt.date(2026, 7, 1), dt.date(2026, 7, 10)
        )
    with pytest.raises(ValueError, match="必须提供"):
        _resolve_range(None, dt.date(2026, 7, 1), None)
