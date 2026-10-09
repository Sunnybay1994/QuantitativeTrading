import datetime as dt

from quant.reporting.sample_scope import first_oos_month, months_between, q10_oos_defaults


def test_q10_oos_start_is_2026_10():
    defaults = q10_oos_defaults()
    assert defaults["oos_start"] == "2026-10"
    assert first_oos_month(dt.date(2026, 9, 12)) == "2026-10"


def test_oos_months_grow():
    assert months_between("2026-10", dt.date(2026, 10, 9)) == 1
    assert months_between("2026-10", dt.date(2026, 12, 1)) == 3
