import datetime as dt

import polars as pl
import pytest

from quant.research import pead_event_signals as events
from quant.research.monthly_sue_context_v2 import NAME, build_monthly_sue_context_v2
from tests.unit.test_earnings_surprise import income

SYMBOL = "000001.SZ"


def history():
    return income([float(i * i + 5 * (i % 4)) for i in range(16)])


def announce(frame, date):
    return frame.with_columns(*[pl.lit(date).alias(column) for column in
                               ("ann_date", "f_ann_date", "available_date")])


def build(frame, start=dt.date(2020, 1, 1), end=dt.date(2025, 12, 31), **kwargs):
    return events.build_financial_events(frame, start, end, **kwargs)


def test_first_disclosures_keep_missing_rows_and_match_existing_pit_formula():
    frame = history()
    actual = build(frame)
    assert actual.schema == events.EVENT_SCHEMA
    assert actual.height == 16
    assert set(actual["status"][:12]) == {"MISSING"}
    assert actual["sue"][:12].null_count() == 12
    date = frame["available_date"][-1]
    expected = build_monthly_sue_context_v2(
        income_history=frame, signal_dates=(date + dt.timedelta(days=1),),
        candidate_symbols=(SYMBOL,),
    )
    row = actual.row(-1, named=True)
    assert row["status"] == "VALID"
    assert row["end_date"] == row["latest_report_end"] == row["financial_period_end"]
    assert row["sue"] == pytest.approx(expected.factors[NAME][0])
    assert row["context_as_of"] == date + dt.timedelta(days=1)


def test_future_revision_does_not_change_first_scores_or_open_another_event():
    frame = history()
    revision_date = frame["available_date"][-1] + dt.timedelta(days=10)
    revision = announce(frame.tail(1), revision_date).with_columns(
        pl.lit(999999.).alias("n_income_attr_p"), pl.lit("1").alias("update_flag"),
        pl.lit("4").alias("comp_type"),
    )
    combined = pl.concat([frame, revision])
    assert build(combined).equals(build(frame))
    # A report first disclosed before start is not revived by an in-window revision.
    assert build(combined, start=revision_date).is_empty()
    assert build(combined.reverse()).equals(build(frame))


def test_new_financial_company_type_does_not_fall_back_to_old_industrial_score():
    frame = history()
    new = announce(frame.tail(1), dt.date(2024, 4, 20)).with_columns(
        pl.lit(dt.date(2024, 3, 31)).alias("end_date"), pl.lit("4").alias("comp_type"),
    )
    row = build(pl.concat([frame, new])).row(-1, named=True)
    assert row["status"] == "NOT_APPLICABLE" and row["sue"] is None
    assert row["context_status"] == "CONTEXT_NON_INDUSTRIAL"
    assert row["latest_report_end"] == dt.date(2024, 3, 31)
    assert row["financial_period_end"] == dt.date(2023, 12, 31)


def test_late_first_announcement_for_old_period_does_not_emit_newer_period_score():
    frame = history()
    old_period = dt.date(2023, 9, 30)
    late = announce(frame.filter(pl.col("end_date") == old_period), dt.date(2024, 2, 1))
    frame = pl.concat([frame.filter(pl.col("end_date") != old_period), late])
    row = build(frame).row(-1, named=True)
    assert row["end_date"] == old_period
    assert row["latest_report_end"] == dt.date(2023, 12, 31)
    assert row["status"] == "NOT_APPLICABLE" and row["sue"] is None
    assert row["reason"] == "EVENT_PERIOD_NOT_LATEST_DISCLOSED_REPORT"


def test_simultaneous_periods_keep_only_latest_and_batch_all_symbols(monkeypatch):
    frame = history()
    date = frame["available_date"][-1]
    frame = pl.concat([frame.head(14), announce(frame.tail(2), date)])
    another = frame.with_columns(pl.lit("000002.SZ").alias("symbol"))
    calls, receipts = [], []
    original = events.build_monthly_sue_context_v2

    def record(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(events, "build_monthly_sue_context_v2", record)
    actual = build(pl.concat([frame, another]), start=date, end=date, progress=receipts.append)
    assert actual.height == 2
    assert actual["end_date"].to_list() == [dt.date(2023, 12, 31)] * 2
    assert len(calls) == len(receipts) == 1
    assert calls[0]["candidate_symbols"] == (SYMBOL, "000002.SZ")
    assert receipts[0]["events"] == 2 and receipts[0]["total_dates"] == 1


def test_first_day_economic_conflict_remains_quarantined_instead_of_row_order_choice():
    frame = history()
    # n_income is not the SUE numerator but is still an economic revision field.
    conflict = frame.tail(1).with_columns((pl.col("n_income") + 100).alias("n_income"))
    combined = pl.concat([frame, conflict])
    actual = build(combined)
    row = actual.row(-1, named=True)
    assert row["status"] == "QUARANTINED" and row["sue"] is None
    assert row["reason"] == "ORIGINAL_REVISION_CONFLICT"
    assert build(combined.reverse()).equals(actual)
    assert build(pl.concat([frame, frame.tail(1)])).equals(build(frame))


@pytest.mark.parametrize("company_type,expected", [(None, "MISSING"), ("9", "MISSING")])
def test_unknown_company_type_has_missing_context(company_type, expected):
    frame = history()
    latest = frame.tail(1).with_columns(pl.lit(company_type, dtype=pl.String).alias("comp_type"))
    row = build(pl.concat([frame.head(15), latest])).row(-1, named=True)
    assert row["status"] == expected and row["sue"] is None
    assert row["context_status"] == "CONTEXT_UNKNOWN"


def test_ambiguous_first_day_company_types_are_quarantined():
    frame = history()
    ambiguous = frame.tail(1).with_columns(pl.lit("4").alias("comp_type"))
    row = build(pl.concat([frame, ambiguous])).row(-1, named=True)
    assert row["status"] == "QUARANTINED" and row["sue"] is None
    assert row["context_status"] == "CONTEXT_AMBIGUOUS"


@pytest.mark.parametrize("delay,expected", [(-1, "NOT_APPLICABLE"), (0, "VALID"),
                                           (180, "VALID"), (181, "NOT_APPLICABLE")])
def test_disclosure_delay_boundaries_retain_ineligible_rows(delay, expected):
    frame = history()
    last = announce(frame.tail(1), frame["end_date"][-1] + dt.timedelta(days=delay))
    actual = build(pl.concat([frame.head(15), last]))
    row = actual.filter(pl.col("end_date") == frame["end_date"][-1]).row(0, named=True)
    assert row["status"] == expected and row["disclosure_delay_days"] == delay
    if expected == "NOT_APPLICABLE":
        assert row["sue"] is None
        assert row["reason"] == "DISCLOSURE_DELAY_OUTSIDE_0_180"


def test_stock_with_no_later_reports_is_retained_and_other_report_types_are_not_events():
    frame = history()
    departed = frame.head(14).with_columns(pl.lit("000018.SZ").alias("symbol"))
    other_type = announce(frame.tail(1), dt.date(2024, 2, 15)).with_columns(
        pl.lit("2").alias("report_type"),
    )
    actual = build(pl.concat([frame, departed, other_type]))
    old = actual.filter(pl.col("symbol") == "000018.SZ")
    assert old.height == 14 and old["status"][-1] == "VALID"
    assert actual.height == 30


def test_zero_variance_remains_missing():
    row = build(income([float(i) for i in range(16)])).row(-1, named=True)
    assert row["status"] == "MISSING" and row["sue"] is None
    assert row["reason"] == "ORIGINAL_SUE_MISSING_OR_ZERO_VARIANCE"


def test_empty_window_and_empty_input_have_stable_schema():
    frame = history()
    for value in (build(frame.head(0)), build(frame, start=dt.date(2025, 1, 1)),
                  build(frame.with_columns(pl.lit("2").alias("report_type")))):
        assert value.is_empty() and value.schema == events.EVENT_SCHEMA


def test_invalid_contract_fails_before_silently_losing_undatable_events():
    frame = history()
    with pytest.raises(ValueError, match="start <= end"):
        build(frame, start=dt.date(2025, 1, 1), end=dt.date(2024, 1, 1))
    with pytest.raises(ValueError, match="schema"):
        build(frame.with_columns(pl.col("available_date").cast(pl.String)))
    with pytest.raises(ValueError, match="require symbol"):
        build(frame.with_columns(pl.lit(None, dtype=pl.Date).alias("available_date")))
