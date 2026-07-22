import datetime as dt

import polars as pl
import pytest

from quant.data.eligibility import (
    EligibilityHistoryError,
    VerifiedReverseEligibilityAudit,
    build_membership_intervals,
    build_membership_intervals_from_reverse_audit,
    eligible_symbols_on,
    verify_reverse_eligibility_history,
)


BASELINE = dt.date(2026, 1, 1)


def snapshot() -> pl.DataFrame:
    return pl.DataFrame({
        "route": ["SH_CONNECT", "SH_CONNECT"],
        "snapshot_date": [BASELINE, BASELINE],
        "symbol": ["00001.HK", "00002.HK"],
        "name_cn": ["甲", "乙"], "name_en": ["A", "B"],
        "security_type": ["STOCK", "STOCK"],
        "buy_eligible": [True, True], "source": ["sse", "sse"],
    })


def events(rows: list[tuple[dt.date, str, str]]) -> pl.DataFrame:
    return pl.DataFrame({
        "route": ["SH_CONNECT"] * len(rows),
        "effective_date": [row[0] for row in rows],
        "symbol": [row[1] for row in rows],
        "action": [row[2] for row in rows],
        "name_cn": [""] * len(rows), "name_en": [""] * len(rows),
        "security_type": ["STOCK"] * len(rows),
        "published_date": [None] * len(rows), "source": ["sse"] * len(rows),
    }).with_columns(pl.col("published_date").cast(pl.Date))


def test_reconstructs_removal_reentry_and_point_in_time_query() -> None:
    history = events([
        (dt.date(2026, 1, 2), "00003.HK", "ADD"),
        (dt.date(2026, 1, 3), "00002.HK", "REMOVE"),
        (dt.date(2026, 1, 5), "00003.HK", "REMOVE"),
        (dt.date(2026, 1, 6), "00002.HK", "ADD"),
    ])
    intervals = build_membership_intervals(snapshot(), history, route="SH_CONNECT")
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2026, 1, 4)
    ) == ["00001.HK", "00003.HK"]
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2026, 1, 6)
    ) == ["00001.HK", "00002.HK"]


def test_rejects_query_before_baseline() -> None:
    intervals = build_membership_intervals(snapshot(), events([]), route="SH_CONNECT")
    with pytest.raises(EligibilityHistoryError, match="早于可证明覆盖起点"):
        eligible_symbols_on(
            intervals, route="SH_CONNECT", as_of=dt.date(2025, 12, 31)
        )


def test_rejects_remove_for_unknown_symbol() -> None:
    history = events([(dt.date(2026, 1, 2), "00003.HK", "REMOVE")])
    with pytest.raises(EligibilityHistoryError, match="调出不在"):
        build_membership_intervals(snapshot(), history, route="SH_CONNECT")


def test_ignores_events_already_reflected_by_baseline() -> None:
    history = events([(BASELINE, "00002.HK", "ADD")])
    intervals = build_membership_intervals(snapshot(), history, route="SH_CONNECT")
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=BASELINE
    ) == ["00001.HK", "00002.HK"]


def _rev_snap(symbols: list[str], day: dt.date = dt.date(2021, 1, 1)) -> pl.DataFrame:
    n = len(symbols)
    return pl.DataFrame({
        "route": ["SH_CONNECT"] * n,
        "snapshot_date": [day] * n,
        "symbol": symbols,
        "name_cn": ["n"] * n,
        "name_en": ["e"] * n,
        "security_type": ["STOCK"] * n,
        "buy_eligible": [True] * n,
        "source": ["sse"] * n,
    })


def _rev_events(rows: list[tuple[dt.date, str, str]]) -> pl.DataFrame:
    n = len(rows)
    return pl.DataFrame(
        {
            "route": ["SH_CONNECT"] * n,
            "effective_date": [r[0] for r in rows],
            "symbol": [r[1] for r in rows],
            "action": [r[2] for r in rows],
            "name_cn": [""] * n,
            "name_en": [""] * n,
            "security_type": ["STOCK"] * n,
            "published_date": [None] * n,
            "source": ["sse"] * n,
        },
        schema={
            "route": pl.String,
            "effective_date": pl.Date,
            "symbol": pl.String,
            "action": pl.String,
            "name_cn": pl.String,
            "name_en": pl.String,
            "security_type": pl.String,
            "published_date": pl.Date,
            "source": pl.String,
        },
    )


def test_reverse_audit_happy_path_and_value_object_invariants() -> None:
    snap = _rev_snap(["00002.HK", "00003.HK"])
    history = _rev_events([
        (dt.date(2020, 6, 1), "00003.HK", "ADD"),
        (dt.date(2020, 7, 1), "00001.HK", "REMOVE"),
    ])
    audit = verify_reverse_eligibility_history(
        snap,
        history,
        route="SH_CONNECT",
        baseline_date=dt.date(2020, 1, 1),
        expected_baseline_count=2,
    )
    assert isinstance(audit, VerifiedReverseEligibilityAudit)
    assert audit.baseline_symbols == ("00001.HK", "00002.HK")
    assert audit.reverse_count == 2
    assert audit.current_count == 2
    assert audit.event_count == 2


def test_reverse_audit_rejects_event_after_snapshot() -> None:
    snap = _rev_snap(["00001.HK"])
    history = _rev_events([(dt.date(2021, 2, 1), "00002.HK", "ADD")])
    with pytest.raises(EligibilityHistoryError, match="REVERSE_AUDIT_COVERAGE_INVALID"):
        verify_reverse_eligibility_history(
            snap,
            history,
            route="SH_CONNECT",
            baseline_date=dt.date(2020, 1, 1),
            expected_baseline_count=1,
        )


def _membership_preview_fixture(
    *,
    route: str = "SH_CONNECT",
) -> tuple[VerifiedReverseEligibilityAudit, pl.DataFrame, pl.DataFrame]:
    """baseline {1,2} → ADD 3, REMOVE 2, ADD 2 → snapshot {1,2,3}."""
    baseline_date = dt.date(2020, 1, 1)
    snapshot_date = dt.date(2021, 1, 1)
    history = _rev_events(
        [
            (dt.date(2020, 3, 1), "00003.HK", "ADD"),
            (dt.date(2020, 6, 1), "00002.HK", "REMOVE"),
            (dt.date(2020, 9, 1), "00002.HK", "ADD"),
        ]
    )
    if route == "SZ_CONNECT":
        history = history.with_columns(
            pl.lit("SZ_CONNECT").alias("route"),
            pl.lit("szse").alias("source"),
        )
    snap = _rev_snap(["00001.HK", "00002.HK", "00003.HK"], day=snapshot_date)
    if route == "SZ_CONNECT":
        snap = snap.with_columns(
            pl.lit("SZ_CONNECT").alias("route"),
            pl.lit("szse").alias("source"),
        )
    audit = verify_reverse_eligibility_history(
        snap,
        history,
        route=route,
        baseline_date=baseline_date,
        expected_baseline_count=2,
    )
    return audit, snap, history


def test_membership_preview_remove_readd_multi_segment_and_final_set() -> None:
    audit, snap, history = _membership_preview_fixture(route="SH_CONNECT")
    intervals = build_membership_intervals_from_reverse_audit(
        audit=audit, snapshot=snap, events=history
    )
    assert set(intervals.get_column("universe").to_list()) == {"SH_CONNECT"}
    assert audit.baseline_symbols == ("00001.HK", "00002.HK")

    rows = {
        (r["symbol"], r["effective_from"], r["effective_to"])
        for r in intervals.to_dicts()
    }
    assert rows == {
        ("00001.HK", dt.date(2020, 1, 1), None),
        ("00002.HK", dt.date(2020, 1, 1), dt.date(2020, 5, 31)),
        ("00002.HK", dt.date(2020, 9, 1), None),
        ("00003.HK", dt.date(2020, 3, 1), None),
    }
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2020, 1, 1)
    ) == ["00001.HK", "00002.HK"]
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2020, 5, 31)
    ) == ["00001.HK", "00002.HK", "00003.HK"]
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2020, 6, 1)
    ) == ["00001.HK", "00003.HK"]
    assert eligible_symbols_on(
        intervals, route="SH_CONNECT", as_of=dt.date(2021, 1, 1)
    ) == ["00001.HK", "00002.HK", "00003.HK"]

    final_active = set(
        eligible_symbols_on(intervals, route="SH_CONNECT", as_of=snap["snapshot_date"][0])
    )
    assert final_active == set(snap.get_column("symbol").to_list())


def test_membership_preview_sz_route() -> None:
    audit, snap, history = _membership_preview_fixture(route="SZ_CONNECT")
    intervals = build_membership_intervals_from_reverse_audit(
        audit=audit, snapshot=snap, events=history
    )
    assert set(intervals.get_column("universe").to_list()) == {"SZ_CONNECT"}
    assert set(
        eligible_symbols_on(intervals, route="SZ_CONNECT", as_of=dt.date(2021, 1, 1))
    ) == set(snap.get_column("symbol").to_list())


def test_membership_preview_row_order_deterministic() -> None:
    audit, snap, history = _membership_preview_fixture()
    a = build_membership_intervals_from_reverse_audit(
        audit=audit, snapshot=snap, events=history
    )
    b = build_membership_intervals_from_reverse_audit(
        audit=audit, snapshot=snap.reverse(), events=history.reverse()
    )
    assert a.to_dicts() == b.to_dicts()


def test_membership_preview_baseline_first_segment_and_pre_baseline_fail_closed() -> None:
    audit, snap, history = _membership_preview_fixture()
    intervals = build_membership_intervals_from_reverse_audit(
        audit=audit, snapshot=snap, events=history
    )
    for symbol in audit.baseline_symbols:
        first = (
            intervals.filter(pl.col("symbol") == symbol)
            .sort("effective_from")
            .row(0, named=True)
        )
        assert first["effective_from"] == audit.baseline_date
    with pytest.raises(EligibilityHistoryError, match="早于可证明覆盖起点"):
        eligible_symbols_on(
            intervals,
            route="SH_CONNECT",
            as_of=audit.baseline_date - dt.timedelta(days=1),
        )


def test_membership_rejects_forged_and_cross_batch_audit() -> None:
    audit, snap, history = _membership_preview_fixture()
    forged = VerifiedReverseEligibilityAudit(
        route=audit.route,
        baseline_date=audit.baseline_date,
        snapshot_date=audit.snapshot_date,
        expected_baseline_count=audit.expected_baseline_count,
        baseline_symbols=audit.baseline_symbols,
        current_count=audit.current_count,
        event_count=audit.event_count,
        reverse_count=audit.reverse_count,
        event_min_date=audit.event_min_date,
        event_max_date=audit.event_max_date,
    )
    object.__setattr__(forged, "baseline_symbols", ("00009.HK", "00010.HK"))
    with pytest.raises(EligibilityHistoryError, match="REVERSE_MEMBERSHIP_AUDIT_MISMATCH"):
        build_membership_intervals_from_reverse_audit(
            audit=forged, snapshot=snap, events=history
        )

    other_snap = _rev_snap(["00001.HK", "00004.HK"], day=dt.date(2021, 1, 1))
    other_events = _rev_events(
        [
            (dt.date(2020, 3, 1), "00004.HK", "ADD"),
            (dt.date(2020, 6, 1), "00002.HK", "REMOVE"),
        ]
    )
    other_audit = verify_reverse_eligibility_history(
        other_snap,
        other_events,
        route="SH_CONNECT",
        baseline_date=dt.date(2020, 1, 1),
        expected_baseline_count=2,
    )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_MEMBERSHIP_AUDIT_MISMATCH"):
        build_membership_intervals_from_reverse_audit(
            audit=other_audit, snapshot=snap, events=history
        )


def test_membership_rejects_event_row_count_drift() -> None:
    audit, snap, history = _membership_preview_fixture()
    fewer = history.head(history.height - 1)
    with pytest.raises(EligibilityHistoryError, match="REVERSE_MEMBERSHIP_AUDIT_MISMATCH"):
        build_membership_intervals_from_reverse_audit(
            audit=audit, snapshot=snap, events=fewer
        )
    extra = pl.concat(
        [
            history,
            _rev_events([(dt.date(2020, 10, 1), "00004.HK", "ADD")]),
        ]
    )
    with pytest.raises(EligibilityHistoryError, match="REVERSE_MEMBERSHIP_AUDIT_MISMATCH"):
        build_membership_intervals_from_reverse_audit(
            audit=audit, snapshot=snap, events=extra
        )


def test_membership_rejects_same_count_different_symbol_set() -> None:
    audit, snap, history = _membership_preview_fixture()
    swapped = snap.with_columns(
        pl.when(pl.col("symbol") == "00003.HK")
        .then(pl.lit("00099.HK"))
        .otherwise(pl.col("symbol"))
        .alias("symbol")
    )
    assert swapped.height == snap.height
    with pytest.raises(
        EligibilityHistoryError,
        match="REVERSE_MEMBERSHIP_(AUDIT_MISMATCH|FINAL_STATE_MISMATCH)",
    ) as caught:
        build_membership_intervals_from_reverse_audit(
            audit=audit, snapshot=swapped, events=history
        )
    text = str(caught.value)
    assert "00099" not in text
    assert "00003" not in text
    assert "/" not in text


def test_membership_error_has_no_symbol_or_path() -> None:
    audit, snap, history = _membership_preview_fixture()
    with pytest.raises(EligibilityHistoryError) as caught:
        build_membership_intervals_from_reverse_audit(
            audit=audit, snapshot=snap, events=history.head(0)
        )
    text = str(caught.value)
    assert text == "REVERSE_MEMBERSHIP_AUDIT_MISMATCH"
    assert "0000" not in text
    assert "/" not in text
    assert "\\" not in text


def test_membership_rejects_non_exact_audit_type() -> None:
    audit, snap, history = _membership_preview_fixture()
    with pytest.raises(EligibilityHistoryError, match="REVERSE_MEMBERSHIP_INPUT_INVALID"):
        build_membership_intervals_from_reverse_audit(
            audit={"route": audit.route},  # type: ignore[arg-type]
            snapshot=snap,
            events=history,
        )
