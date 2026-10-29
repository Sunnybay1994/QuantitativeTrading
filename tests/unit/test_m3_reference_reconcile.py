"""Reference contract regressions with shared verified synthetic inputs."""
from __future__ import annotations

from tests.unit.test_m3_reference import (
    Any,
    CrossSourceFieldStatsV1,
    CrossSourceReconciliationBundle,
    CrossSourceSamplePlan,
    G1Candidate,
    G1CrossSourcePolicy,
    G1QualityIssue,
    G1_CORPORATE_ACTION_RECONCILIATION_VERSION,
    G1_CORPORATE_ACTION_SELECTION_VERSION,
    M3ReferenceError,
    RawStore,
    ReferenceRawCandidateV1,
    ReferenceRequestIntentV1,
    ReferenceRequestPlanV1,
    ReferenceRequestReceipt,
    ReferenceRequestSpec,
    VerifiedReferenceResponse,
    _D0,
    _build_spec,
    _bundle_with_n_mismatches,
    _detail_from_rows,
    _detail_rows,
    _first_key_for_side,
    _lying_green_summary_from_mismatch_bundle,
    _make_verified_reference,
    _missing_reference_bundle,
    _mutate_key_rows,
    _num,
    _perfect_reference_responses,
    _policy,
    _rebind_identity,
    _rebuild_bundle_from_valid_detail,
    _rebundle_with_mutated_detail,
    _reference_frame,
    _reference_rows_for_symbol,
    _sample_dates_by_symbol,
    asdict,
    audit_g1_candidate,
    clean_table_content_sha256,
    dt,
    execute_baostock_reference_plan,
    happy_candidate,
    happy_inputs,
    patch,
    pl,
    plan_baostock_reference_requests,
    plan_cross_source_reconciliation,
    pytest,
    reconcile_cross_source,
    ref,
    replace,
    request_plan,
    sample_plan,
    socket,
    verify_reference_receipt,
)


def test_reconcile_tradestatus_zero_is_reference_missing_not_error(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    target_spec = request_plan.requests[0]
    dates = by_symbol[target_spec.symbol]
    zero_day = dates[0]
    rows = _reference_rows_for_symbol(
        happy_candidate, target_spec.symbol, dates, zero_dates=frozenset({zero_day})
    )
    responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=_policy(max_mismatch_rate=0.01),
    )
    assert {issue.code for issue in bundle.issues} == {"CROSS_SOURCE_INCOMPLETE"}
    assert bundle.summary.missing_reference_rows == 1


@pytest.mark.parametrize(
    "mutator",
    [
        "wrong_code",
        "date_before_start",
        "date_after_end",
        "duplicate_date",
        "bad_adjustflag",
        "bad_tradestatus",
        "nonpositive_price",
        "negative_volume",
        "nonnumeric_value",
        "nan_value",
    ],
)
def test_reconcile_rejects_invalid_reference_rows(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
    mutator: str,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
    target_spec = request_plan.requests[0]
    dates = by_symbol[target_spec.symbol]
    rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, dates)
    params = dict(target_spec.parameters)
    start = dt.date.fromisoformat(params["start_date"])
    end = dt.date.fromisoformat(params["end_date"])

    if mutator == "wrong_code":
        rows[0]["code"] = "sz.999999"
    elif mutator == "date_before_start":
        rows[0]["date"] = (start - dt.timedelta(days=1)).isoformat()
    elif mutator == "date_after_end":
        rows[0]["date"] = (end + dt.timedelta(days=1)).isoformat()
    elif mutator == "duplicate_date":
        rows.append(dict(rows[0]))
    elif mutator == "bad_adjustflag":
        rows[0]["adjustflag"] = "1"
    elif mutator == "bad_tradestatus":
        rows[0]["tradestatus"] = "2"
    elif mutator == "nonpositive_price":
        rows[0]["open"] = "0.0"
    elif mutator == "negative_volume":
        rows[0]["volume"] = "-1.0"
    elif mutator == "nonnumeric_value":
        rows[0]["close"] = "abc"
    elif mutator == "nan_value":
        rows[0]["close"] = "nan"

    responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))
    with pytest.raises(M3ReferenceError) as excinfo:
        reconcile_cross_source(
            candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
            policy=_policy(),
        )
    assert excinfo.value.code == "G1_CROSS_SOURCE_RECONCILIATION_INVALID"


def test_reconcile_price_tolerance_atol_and_rtol_boundaries(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    target_spec = request_plan.requests[0]
    by_symbol = _sample_dates_by_symbol(sample_plan)
    dates = by_symbol[target_spec.symbol]
    bars_index = {
        row["trade_date"]: row
        for row in happy_candidate.bars.filter(pl.col("symbol") == target_spec.symbol).iter_rows(
            named=True
        )
    }
    base_close = bars_index[dates[0]]["close"]
    policy = _policy(price_atol=0.02, price_rtol=0.0, max_mismatch_rate=0.5)

    def _bundle_with_close(delta: float) -> Any:
        rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, dates)
        rows[0]["close"] = _num(base_close + delta)
        responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
        responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))
        return reconcile_cross_source(
            candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
            policy=policy,
        )

    assert _bundle_with_close(-(0.02 - 1e-6)).summary.mismatch_cells == 0
    assert _bundle_with_close(-(0.02 + 1e-6)).summary.mismatch_cells == 1


def test_reconcile_volume_tolerance_uses_relative_denominator(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    target_spec = request_plan.requests[0]
    by_symbol = _sample_dates_by_symbol(sample_plan)
    dates = by_symbol[target_spec.symbol]
    bars_index = {
        row["trade_date"]: row
        for row in happy_candidate.bars.filter(pl.col("symbol") == target_spec.symbol).iter_rows(
            named=True
        )
    }
    primary_volume = bars_index[dates[0]]["volume"]
    rtol = 0.1
    policy = _policy(volume_rtol=rtol, max_mismatch_rate=0.5)
    boundary = primary_volume / (1.0 + rtol)

    def _bundle_with_volume(value: float) -> Any:
        rows = _reference_rows_for_symbol(happy_candidate, target_spec.symbol, dates)
        rows[0]["volume"] = _num(value)
        responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))
        responses[0] = _make_verified_reference(target_spec, _reference_frame(rows))
        return reconcile_cross_source(
            candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
            policy=policy,
        )

    assert _bundle_with_volume(boundary + 1e-3).summary.mismatch_cells == 0
    assert _bundle_with_volume(boundary - 1e-3).summary.mismatch_cells == 1


def test_reconcile_mismatch_rate_exact_threshold_vs_exceeding(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(price_atol=0.0, price_rtol=0.0, volume_rtol=0.0, max_mismatch_rate=0.01)
    at_threshold = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 30)
    assert at_threshold.summary.mismatch_cells == 30
    assert at_threshold.summary.mismatch_rate == pytest.approx(0.01)
    assert {issue.code for issue in at_threshold.issues} == set()
    assert at_threshold.passed is True

    over_threshold = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 31)
    assert over_threshold.summary.mismatch_cells == 31
    assert {issue.code for issue in over_threshold.issues} == {"CROSS_SOURCE_MISMATCH"}
    assert over_threshold.passed is False


def test_reconcile_both_issue_types_can_coexist(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    by_symbol = _sample_dates_by_symbol(sample_plan)
    policy = _policy(price_atol=0.0, price_rtol=0.0, volume_rtol=0.0, max_mismatch_rate=0.001)
    responses = list(_perfect_reference_responses(happy_candidate, sample_plan, request_plan))

    spec0 = request_plan.requests[0]
    dates0 = by_symbol[spec0.symbol]
    rows0 = _reference_rows_for_symbol(happy_candidate, spec0.symbol, dates0[1:])
    responses[0] = _make_verified_reference(spec0, _reference_frame(rows0))

    spec1 = request_plan.requests[1]
    dates1 = by_symbol[spec1.symbol]
    rows1 = _reference_rows_for_symbol(happy_candidate, spec1.symbol, dates1)
    rows1[0]["close"] = _num(float(rows1[0]["close"]) + 1.0)
    responses[1] = _make_verified_reference(spec1, _reference_frame(rows1))

    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses),
        policy=policy,
    )
    assert {issue.code for issue in bundle.issues} == {
        "CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH",
    }
    assert bundle.passed is False


def test_bundle_constructor_rejects_wholesale_and_field_drift(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    with pytest.raises(ValueError):
        replace(bundle, detail_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(bundle, detail=bundle.detail.with_columns(pl.lit(999.0).alias("abs_diff")))
    with pytest.raises(ValueError):
        replace(bundle, summary_sha256="0" * 64)
    with pytest.raises(ValueError):
        replace(bundle, passed=not bundle.passed)
    with pytest.raises(ValueError):
        replace(
            bundle,
            issues=(
                G1QualityIssue(
                    code="CROSS_SOURCE_MISMATCH", severity="ERROR", message="forged",
                    count=1, evidence=(),
                ),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=replace(bundle.summary, mismatch_cells=bundle.summary.mismatch_cells + 1),
        )
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=bundle.reference_receipts[:-1])


def test_bundle_wholesale_summary_drift_only_caught_by_recomputing_reconcile(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses_a = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle_a = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses_a,
        policy=_policy(),
    )
    by_symbol = _sample_dates_by_symbol(sample_plan)
    spec0 = request_plan.requests[0]
    rows = _reference_rows_for_symbol(happy_candidate, spec0.symbol, by_symbol[spec0.symbol])
    rows[0]["close"] = _num(float(rows[0]["close"]) + 5.0)
    responses_b = list(responses_a)
    responses_b[0] = _make_verified_reference(spec0, _reference_frame(rows))
    bundle_b = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=tuple(responses_b),
        policy=_policy(),
    )
    assert bundle_b.summary_sha256 != bundle_a.summary_sha256
    assert bundle_b.detail_sha256 != bundle_a.detail_sha256
    assert bundle_b.summary.mismatch_cells != bundle_a.summary.mismatch_cells


def test_adv5_bundle_rejects_lying_green_summary_on_mismatch_detail(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(max_mismatch_rate=0.0)
    bundle = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 1)
    assert bundle.summary.mismatch_cells > 0
    assert bundle.passed is False
    green, green_hash = _lying_green_summary_from_mismatch_bundle(bundle)
    with pytest.raises(ValueError):
        CrossSourceReconciliationBundle(
            sample_plan=bundle.sample_plan,
            reference_receipts=bundle.reference_receipts,
            detail=bundle.detail,
            detail_sha256=bundle.detail_sha256,
            summary=green,
            summary_sha256=green_hash,
            issues=(),
            passed=True,
        )


def test_adv5_variants_reject_forged_stats_missing_rate_issues_passed(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(max_mismatch_rate=0.0)
    bundle = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 5)
    # Forge max diffs to zero while keeping mismatch counts consistent with summary totals.
    forged_stats = replace(
        bundle.summary.field_stats[3],  # close — mismatches are injected on close
        max_abs_diff=0.0,
        max_relative_diff=0.0,
    )
    assert bundle.summary.field_stats[3].max_abs_diff > 0.0
    stats_summary = replace(
        bundle.summary,
        field_stats=(
            *bundle.summary.field_stats[:3],
            forged_stats,
            bundle.summary.field_stats[4],
        ),
    )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=stats_summary,
            summary_sha256=ref._sha256_json(asdict(stats_summary)),
        )

    missing_summary = replace(bundle.summary, missing_reference_rows=bundle.summary.missing_reference_rows + 1)
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=missing_summary,
            summary_sha256=ref._sha256_json(asdict(missing_summary)),
        )

    zero_stats = tuple(
        CrossSourceFieldStatsV1(
            field=stats.field,
            comparison_count=stats.comparison_count,
            mismatch_count=0,
            max_abs_diff=0.0,
            max_relative_diff=0.0,
        )
        for stats in bundle.summary.field_stats
    )
    cells_summary = replace(
        bundle.summary,
        mismatch_cells=0,
        mismatch_rate=0.0,
        field_stats=zero_stats,
        passed=False,
    )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=cells_summary,
            summary_sha256=ref._sha256_json(asdict(cells_summary)),
        )

    with pytest.raises(ValueError):
        replace(
            bundle,
            issues=(
                G1QualityIssue(
                    code="CROSS_SOURCE_MISMATCH",
                    severity="ERROR",
                    message="cross-source mismatch rate exceeds policy threshold",
                    count=bundle.summary.mismatch_cells + 1,
                    evidence=(),
                ),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            bundle,
            issues=(
                G1QualityIssue(
                    code="CROSS_SOURCE_MISMATCH",
                    severity="ERROR",
                    message="forged message",
                    count=bundle.summary.mismatch_cells,
                    evidence=(),
                ),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            bundle,
            passed=True,
            summary=replace(bundle.summary, passed=True),
            summary_sha256=ref._sha256_json(asdict(replace(bundle.summary, passed=True))),
        )


def test_adv5_detail_schema_and_key_drifts_reject_with_stable_valueerror(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    cases = [
        bundle.detail.with_row_index().filter(pl.col("index") > 0).drop("index"),  # missing row
        pl.concat([bundle.detail, bundle.detail.head(1)]),  # duplicate/extra
        bundle.detail.with_columns(pl.col("field").cast(pl.Categorical)),
        bundle.detail.with_columns(pl.lit("WRONG").alias("missing_side")),
        bundle.detail.with_columns(pl.lit(False).alias("matched")),
        bundle.detail.with_columns(pl.lit(None, dtype=pl.Float64).alias("tolerance")),
    ]
    for detail in cases:
        digest = clean_table_content_sha256(table_name="cross_source_detail", frame=detail)
        summary = replace(bundle.summary, detail_sha256=digest)
        with pytest.raises(ValueError) as excinfo:
            CrossSourceReconciliationBundle(
                sample_plan=bundle.sample_plan,
                reference_receipts=bundle.reference_receipts,
                detail=detail,
                detail_sha256=digest,
                summary=summary,
                summary_sha256=ref._sha256_json(asdict(summary)),
                issues=bundle.issues,
                passed=bundle.passed,
            )
        text = f"{excinfo.value}{excinfo.value!s}{excinfo.value!r}"
        assert "/home/" not in text
        assert "polars" not in text.lower()
        assert "ComputeError" not in text


def test_adv9_bundle_rejects_warning_severity_for_both_cross_source_codes(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    policy = _policy(max_mismatch_rate=0.0)
    bundle = _bundle_with_n_mismatches(happy_candidate, sample_plan, request_plan, policy, 1)
    for code in ("CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"):
        # Force a WARNING issue while keeping passed/summary consistent enough to isolate severity.
        if code == "CROSS_SOURCE_MISMATCH":
            warn_issue = G1QualityIssue(
                code=code,
                severity="WARNING",
                message="cross-source mismatch rate exceeds policy threshold",
                count=bundle.summary.mismatch_cells,
                evidence=(),
            )
            with pytest.raises(ValueError):
                replace(bundle, issues=(warn_issue,), passed=False)
        else:
            # Build an incomplete bundle then swap ERROR→WARNING on the incomplete issue.
            incomplete = reconcile_cross_source(
                candidate=happy_candidate,
                sample_plan=sample_plan,
                reference_responses=_perfect_reference_responses(
                    happy_candidate, sample_plan, request_plan
                )[:-1] + (
                    _make_verified_reference(
                        request_plan.requests[-1],
                        _reference_frame([]),
                    ),
                ),
                policy=_policy(max_mismatch_rate=1.0),
            )
            assert any(i.code == "CROSS_SOURCE_INCOMPLETE" for i in incomplete.issues)
            base = incomplete.issues[0]
            warn_issue = G1QualityIssue(
                code="CROSS_SOURCE_INCOMPLETE",
                severity="WARNING",
                message=base.message,
                count=base.count,
                evidence=base.evidence,
            )
            with pytest.raises(ValueError):
                replace(incomplete, issues=(warn_issue,))


def test_f3_bundle_rejects_sample_plan_and_reference_receipt_closure_drifts(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    # primary_candidate_key drift
    key_summary = replace(bundle.summary, primary_candidate_key="a" * 64)
    with pytest.raises(ValueError):
        replace(bundle, summary=key_summary, summary_sha256=ref._sha256_json(asdict(key_summary)))
    # sample_plan_sha256 drift
    plan_summary = replace(bundle.summary, sample_plan_sha256="b" * 64)
    with pytest.raises(ValueError):
        replace(bundle, summary=plan_summary, summary_sha256=ref._sha256_json(asdict(plan_summary)))
    # delete one reference receipt
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=bundle.reference_receipts[:-1])
    # change summary digests without changing receipts
    digests_only = replace(
        bundle.summary,
        reference_receipt_digests=tuple(
            sorted({*bundle.summary.reference_receipt_digests[:-1], "c" * 64})
        ),
    )
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=digests_only,
            summary_sha256=ref._sha256_json(asdict(digests_only)),
        )
    # change one receipt digest without updating summary digests
    forged_receipt = replace(
        bundle.reference_receipts[0], stable_response_sha256="c" * 64
    )
    forged_receipts = tuple(
        sorted(
            (forged_receipt, *bundle.reference_receipts[1:]),
            key=lambda item: (item.source, item.endpoint, item.request_id),
        )
    )
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=forged_receipts)
    # summary.detail_sha256 drift vs bundle.detail_sha256
    detail_summary = replace(bundle.summary, detail_sha256="d" * 64)
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=detail_summary,
            summary_sha256=ref._sha256_json(asdict(detail_summary)),
        )


def test_f3_summary_reference_digests_must_match_receipt_projections(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    wrong_digests = tuple(sorted({*bundle.summary.reference_receipt_digests, "e" * 64}))
    # Keep length uniqueness rules of summary validator in mind: digests must be sorted unique.
    # Adding an extra digest changes the tuple and must be rejected by F3 closure.
    with pytest.raises(ValueError):
        summary = replace(bundle.summary, reference_receipt_digests=wrong_digests)
        replace(bundle, summary=summary, summary_sha256=ref._sha256_json(asdict(summary)))


def test_h1_missing_rows_require_exact_zero_tolerance(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    incomplete = _missing_reference_bundle(happy_candidate, sample_plan, request_plan)
    symbol, day = _first_key_for_side(incomplete.detail, "REFERENCE")

    bad_tol = _mutate_key_rows(
        incomplete.detail, symbol, day, missing_side="REFERENCE", tolerance=123.0
    )
    with pytest.raises(ValueError):
        _rebundle_with_mutated_detail(incomplete, bad_tol)

    for bad in (float("nan"), float("inf"), float("-inf"), None, 1, True):
        rows = _detail_rows(incomplete.detail)
        for row in rows:
            if row["symbol"] == symbol and row["trade_date"] == day:
                row["tolerance"] = bad
        detail = _detail_from_rows(incomplete.detail, rows)
        with pytest.raises(ValueError):
            _rebundle_with_mutated_detail(incomplete, detail)

    neg_zero = _mutate_key_rows(
        incomplete.detail, symbol, day, missing_side="REFERENCE", tolerance=-0.0
    )
    rebuilt = _rebundle_with_mutated_detail(incomplete, neg_zero)
    assert rebuilt.summary.missing_reference_rows == 1

    happy = reconcile_cross_source(
        candidate=happy_candidate,
        sample_plan=sample_plan,
        reference_responses=_perfect_reference_responses(
            happy_candidate, sample_plan, request_plan
        ),
        policy=_policy(),
    )
    first_symbol, first_day = happy.detail.row(0, named=True)["symbol"], happy.detail.row(
        0, named=True
    )["trade_date"]
    for side in ("PRIMARY", "BOTH"):
        forged = _mutate_key_rows(
            happy.detail,
            first_symbol,
            first_day,
            missing_side=side,
            tolerance=123.0,
            primary_value=None,
            reference_value=None if side == "BOTH" else 1.0,
        )
        # Hash-rebinding attack: craft summary counts as if tolerance were accepted.
        overrides = {
            "missing_primary_rows": 1 if side in {"PRIMARY", "BOTH"} else 0,
            "missing_reference_rows": 1 if side in {"REFERENCE", "BOTH"} else 0,
            "mismatch_cells": 5,
            "mismatch_rate": 5 / 3000,
            "field_stats": tuple(
                CrossSourceFieldStatsV1(
                    field=stats.field,
                    comparison_count=stats.comparison_count,
                    mismatch_count=1,
                    max_abs_diff=0.0,
                    max_relative_diff=0.0,
                )
                for stats in happy.summary.field_stats
            ),
            "passed": False,
        }
        evidence = (f"{first_symbol}|{first_day.isoformat()}",)
        issues = (
            G1QualityIssue(
                code="CROSS_SOURCE_INCOMPLETE",
                severity="ERROR",
                message="cross-source sample row missing primary or reference bar",
                count=overrides["missing_primary_rows"] + overrides["missing_reference_rows"],
                evidence=evidence,
            ),
        )
        with pytest.raises(ValueError):
            _rebundle_with_mutated_detail(
                happy, forged, summary_overrides=overrides, issues=issues, passed=False
            )

        ok = _mutate_key_rows(
            happy.detail,
            first_symbol,
            first_day,
            missing_side=side,
            tolerance=0.0,
            primary_value=None,
            reference_value=None if side == "BOTH" else 1.0,
        )
        rebuilt_ok = _rebuild_bundle_from_valid_detail(happy, ok)
        assert rebuilt_ok.summary.missing_primary_rows == overrides["missing_primary_rows"]
        assert rebuilt_ok.summary.missing_reference_rows == overrides["missing_reference_rows"]


@pytest.mark.parametrize(
    ("missing_side", "field", "bad_value"),
    [
        ("REFERENCE", "open", 0.0),
        ("REFERENCE", "open", -1.0),
        ("REFERENCE", "open", float("nan")),
        ("REFERENCE", "open", float("inf")),
        ("REFERENCE", "high", 0.0),
        ("REFERENCE", "low", -1.0),
        ("REFERENCE", "close", float("nan")),
        ("REFERENCE", "volume", -1.0),
        ("REFERENCE", "volume", float("nan")),
        ("REFERENCE", "volume", float("inf")),
        ("PRIMARY", "open", 0.0),
        ("PRIMARY", "close", -1.0),
        ("PRIMARY", "volume", -1.0),
        ("PRIMARY", "volume", float("nan")),
    ],
)
def test_h2_missing_rows_reject_invalid_present_side_domain(
    happy_candidate: G1Candidate,
    sample_plan: CrossSourceSamplePlan,
    request_plan: ReferenceRequestPlanV1,
    missing_side: str,
    field: str,
    bad_value: float,
) -> None:
    happy = reconcile_cross_source(
        candidate=happy_candidate,
        sample_plan=sample_plan,
        reference_responses=_perfect_reference_responses(
            happy_candidate, sample_plan, request_plan
        ),
        policy=_policy(max_mismatch_rate=0.01),
    )
    first_symbol = happy.detail.row(0, named=True)["symbol"]
    first_day = happy.detail.row(0, named=True)["trade_date"]
    base = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side=missing_side,
        tolerance=0.0,
        primary_value=None if missing_side == "PRIMARY" else 1.0,
        reference_value=None if missing_side == "REFERENCE" else 1.0,
    )
    rows = _detail_rows(base)
    for row in rows:
        if row["symbol"] == first_symbol and row["trade_date"] == first_day and row["field"] == field:
            if missing_side == "REFERENCE":
                row["primary_value"] = bad_value
            else:
                row["reference_value"] = bad_value
    detail = _detail_from_rows(base, rows)
    with pytest.raises(ValueError) as excinfo:
        _rebuild_bundle_from_valid_detail(happy, detail)
    text = f"{excinfo.value}{excinfo.value!s}{excinfo.value!r}"
    assert "/home/" not in text
    assert "polars" not in text.lower()
    assert "ComputeError" not in text


def test_h2_missing_rows_accept_valid_present_side_and_both_nulls(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    incomplete = _missing_reference_bundle(happy_candidate, sample_plan, request_plan)
    symbol, day = _first_key_for_side(incomplete.detail, "REFERENCE")
    rows = _detail_rows(incomplete.detail)
    for row in rows:
        if row["symbol"] == symbol and row["trade_date"] == day and row["field"] == "volume":
            row["primary_value"] = 0.0
    detail = _detail_from_rows(incomplete.detail, rows)
    rebuilt = _rebundle_with_mutated_detail(incomplete, detail)
    assert rebuilt.summary.missing_reference_rows == 1

    happy = reconcile_cross_source(
        candidate=happy_candidate,
        sample_plan=sample_plan,
        reference_responses=_perfect_reference_responses(
            happy_candidate, sample_plan, request_plan
        ),
        policy=_policy(),
    )
    first_symbol = happy.detail.row(0, named=True)["symbol"]
    first_day = happy.detail.row(0, named=True)["trade_date"]

    primary_ok = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side="PRIMARY",
        tolerance=0.0,
        primary_value=None,
        reference_value=2.5,
    )
    rebuilt_primary = _rebuild_bundle_from_valid_detail(happy, primary_ok)
    assert rebuilt_primary.summary.missing_primary_rows == 1

    both_ok = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side="BOTH",
        tolerance=0.0,
        primary_value=None,
        reference_value=None,
    )
    rebuilt_both = _rebuild_bundle_from_valid_detail(happy, both_ok)
    assert rebuilt_both.summary.missing_primary_rows == 1
    assert rebuilt_both.summary.missing_reference_rows == 1

    both_bad = _mutate_key_rows(
        happy.detail,
        first_symbol,
        first_day,
        missing_side="BOTH",
        tolerance=0.0,
        primary_value=1.0,
        reference_value=None,
    )
    with pytest.raises(ValueError):
        _rebuild_bundle_from_valid_detail(happy, both_bad)


def test_h3_stable_response_digests_remain_one_per_request(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    bundle = reconcile_cross_source(
        candidate=happy_candidate, sample_plan=sample_plan, reference_responses=responses,
        policy=_policy(),
    )
    assert len(bundle.reference_receipts) == 30
    assert len(set(item.stable_response_sha256 for item in bundle.reference_receipts)) == 30
    assert len(bundle.summary.reference_receipt_digests) == 30

    r0 = bundle.reference_receipts[0]
    r1 = bundle.reference_receipts[1]
    dup_receipt = replace(r1, stable_response_sha256=r0.stable_response_sha256)
    forged_receipts = tuple(
        sorted(
            (dup_receipt if item.request_id == r1.request_id else item for item in bundle.reference_receipts),
            key=lambda item: (item.source, item.endpoint, item.request_id),
        )
    )
    assert len(set(item.stable_response_sha256 for item in forged_receipts)) == 29

    # Receipt-only drift (summary still lists 30).
    with pytest.raises(ValueError):
        replace(bundle, reference_receipts=forged_receipts)

    # Summary-only drift to 29 while receipts remain 30 unique.
    digests_29 = tuple(sorted(set(bundle.summary.reference_receipt_digests[:-1])))
    assert len(digests_29) == 29
    summary_29 = replace(bundle.summary, reference_receipt_digests=digests_29)
    with pytest.raises(ValueError):
        replace(
            bundle,
            summary=summary_29,
            summary_sha256=ref._sha256_json(asdict(summary_29)),
        )

    # Self-consistent collapse: receipts + summary both rebound to 29 unique digests.
    collapsed = tuple(sorted({item.stable_response_sha256 for item in forged_receipts}))
    assert len(collapsed) == 29
    summary_collapsed = replace(bundle.summary, reference_receipt_digests=collapsed)
    with pytest.raises(ValueError):
        CrossSourceReconciliationBundle(
            sample_plan=bundle.sample_plan,
            reference_receipts=forged_receipts,
            detail=bundle.detail,
            detail_sha256=bundle.detail_sha256,
            summary=summary_collapsed,
            summary_sha256=ref._sha256_json(asdict(summary_collapsed)),
            issues=bundle.issues,
            passed=bundle.passed,
        )


def test_pure_functions_perform_zero_io_or_network(
    happy_candidate: G1Candidate, sample_plan: CrossSourceSamplePlan, request_plan: ReferenceRequestPlanV1,
) -> None:
    import builtins

    real_open = builtins.open

    def guarded_open(file: object, *args: object, **kwargs: object) -> object:
        text = str(file).replace("\\", "/").lower()
        forbidden = ("/raw/", "/journal/", ".parquet", "receipt.json", "candidate.json", "intent.json")
        if any(token in text for token in forbidden):
            raise AssertionError("open called on data/journal path")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    responses = _perfect_reference_responses(happy_candidate, sample_plan, request_plan)
    with (
        patch("builtins.open", side_effect=guarded_open),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket")),
        patch.object(RawStore, "write", side_effect=AssertionError("raw write")),
        patch.object(RawStore, "write_request", side_effect=AssertionError("raw write_request")),
    ):
        plan_a = plan_cross_source_reconciliation(candidate=happy_candidate, policy=_policy())
        plan_b = plan_baostock_reference_requests(sample_plan=plan_a)
        bundle = reconcile_cross_source(
            candidate=happy_candidate, sample_plan=plan_a, reference_responses=responses,
            policy=_policy(),
        )
    assert plan_a == sample_plan
    assert plan_b == request_plan
    assert bundle.passed is True


def test_cross_source_issue_codes_constructible_and_enter_bundle() -> None:
    for code in ("CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"):
        issue = G1QualityIssue(code=code, severity="ERROR", message="m", count=1, evidence=())
        assert issue.code == code


def test_unfrozen_cross_source_codes_are_rejected() -> None:
    with pytest.raises(ValueError):
        G1QualityIssue(code="CROSS_SOURCE_UNKNOWN", severity="ERROR", message="m", count=1, evidence=())


def test_audit_g1_candidate_only_uses_primary_codes_on_happy_and_damaged_candidates(
    happy_candidate: G1Candidate,
) -> None:
    audit = audit_g1_candidate(candidate=happy_candidate)
    assert audit.passed is True
    codes = {issue.code for issue in audit.issues}
    assert codes.isdisjoint({"CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"})

    symbol = happy_candidate.eligible_keys["symbol"][0]
    bars = happy_candidate.bars.filter(
        ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D0))
    )
    damaged = _rebind_identity(happy_candidate, bars=bars)
    audit2 = audit_g1_candidate(candidate=damaged)
    assert audit2.passed is False
    codes2 = {issue.code for issue in audit2.issues}
    assert codes2.isdisjoint({"CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"})
    assert "BAR_OR_SUSPENSION_MISSING" in codes2


def test_m3_reference_error_str_repr_is_sanitized() -> None:
    err = M3ReferenceError("G1_REFERENCE_IO_FAILED")
    text = f"{err}{err!s}{err!r}"
    assert "/home/" not in text
    assert "token" not in text.lower()
    assert err.__cause__ is None


def test_m3_reference_error_rejects_unknown_code() -> None:
    with pytest.raises(ValueError):
        M3ReferenceError("NOT_A_REAL_CODE")


def test_package_exports_frozen_public_names() -> None:
    import quant.data as qd

    assert qd.G1CrossSourcePolicy is G1CrossSourcePolicy
    assert qd.CrossSourceSamplePlan is CrossSourceSamplePlan
    assert qd.ReferenceRequestSpec is ReferenceRequestSpec
    assert qd.ReferenceRequestPlanV1 is ReferenceRequestPlanV1
    assert qd.ReferenceRequestIntentV1 is ReferenceRequestIntentV1
    assert qd.ReferenceRawCandidateV1 is ReferenceRawCandidateV1
    assert qd.ReferenceRequestReceipt is ReferenceRequestReceipt
    assert qd.VerifiedReferenceResponse is VerifiedReferenceResponse
    assert qd.plan_cross_source_reconciliation is plan_cross_source_reconciliation
    assert qd.plan_baostock_reference_requests is plan_baostock_reference_requests
    assert qd.execute_baostock_reference_plan is execute_baostock_reference_plan
    assert qd.verify_reference_receipt is verify_reference_receipt
    assert qd.reconcile_cross_source is reconcile_cross_source
    assert qd.M3ReferenceError is M3ReferenceError


def test_p0e_reconciliation_version_propagates_in_build_spec() -> None:
    assert G1_CORPORATE_ACTION_SELECTION_VERSION == (
        "tushare_dividend_cninfo_rights_share_consideration_basis_v8"
    )
    assert G1_CORPORATE_ACTION_RECONCILIATION_VERSION == (
        "tushare_factor_daily_preclose_suspension_resume_basis_terms_v9"
    )
    spec = _build_spec()
    assert spec.corporate_action_selection_version == (
        G1_CORPORATE_ACTION_SELECTION_VERSION
    )
    assert spec.corporate_action_reconciliation_version == (
        G1_CORPORATE_ACTION_RECONCILIATION_VERSION
    )
    with pytest.raises(ValueError, match="corporate_action_reconciliation_version"):
        replace(
            spec,
            corporate_action_reconciliation_version="tushare_factor_daily_preclose_v3",
        )
