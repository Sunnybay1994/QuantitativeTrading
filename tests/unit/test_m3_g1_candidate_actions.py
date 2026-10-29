"""G1 action/closure regressions split from the constructor module."""
from __future__ import annotations

from tests.unit.test_m3_g1_candidate import (
    Any,
    CNINFO_DIVIDEND_ENDPOINT,
    CNINFO_SHARE_CHANGE_ENDPOINT,
    CNINFO_STOCK_ALLOTMENT_FIELDS,
    CNINFO_STOCK_DIVIDEND_FIELDS,
    CNINFO_STOCK_SHARE_CHANGE_FIELDS,
    Decimal,
    G1BuildInputs,
    G1BuildSpec,
    G1Candidate,
    G1_CORPORATE_ACTION_RECONCILIATION_VERSION,
    G1_CORPORATE_ACTION_SELECTION_VERSION,
    G1_MEMBERSHIP_METHOD_VERSION,
    G1_PRICE_LIMIT_METHOD_VERSION,
    HistoryWindow,
    M3G1CandidateError,
    M3G1ExecutionFactError,
    RawStore,
    TUSHARE_FIELDS,
    TushareRequestSpec,
    VerifiedRawResponse,
    _D0,
    _D1,
    _HEX,
    _build_inputs,
    _daily_frame,
    _empty_suspend,
    _full_day_suspend,
    _limit_frame,
    _make_cninfo_ca_verified,
    _make_cninfo_verified,
    _make_verified,
    _rebind_identity,
    _symbols,
    apply_adjustment_factors_strict,
    audit_g1_candidate,
    backfill,
    build_g1_candidate,
    dt,
    happy_candidate,
    happy_inputs,
    patch,
    pl,
    project_scoped_adjustment_factors,
    pytest,
    replace,
    select_g1_cninfo_share_consideration_actions,
    socket,
    verify_g1_candidate,
)

def test_wholesale_candidate_replacement_fails_verify(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    other = build_g1_candidate(inputs=_build_inputs(mutate_daily_close=11.0))
    # Pretend attacker synced all digests/identity of another valid candidate.
    with pytest.raises(M3G1CandidateError) as excinfo:
        verify_g1_candidate(inputs=happy_inputs, candidate=other)
    assert excinfo.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_exception_surfaces_are_sanitized() -> None:
    err = M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    text = f"{err}{err!s}{err!r}{err.__cause__}"
    assert "/home/" not in text
    assert "token" not in text.lower()
    assert "Tushare" not in text
    assert err.__cause__ is None


def test_no_file_or_network_io_during_build(happy_inputs: G1BuildInputs) -> None:
    import builtins

    real_open = builtins.open

    def guarded_open(file: object, *args: object, **kwargs: object) -> object:
        path = str(file).replace("\\", "/").lower()
        forbidden = (
            "/data/raw/",
            "/data/clean/",
            "/journal/",
            ".parquet",
            "releases/",
        )
        if any(token in path for token in forbidden):
            raise AssertionError("open called on data path")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    with (
        patch("builtins.open", side_effect=guarded_open),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket")),
        patch.object(RawStore, "write", side_effect=AssertionError("raw write")),
        patch.object(
            RawStore, "write_request", side_effect=AssertionError("raw write_request")
        ),
    ):
        candidate = build_g1_candidate(inputs=happy_inputs)
        verify_g1_candidate(inputs=happy_inputs, candidate=candidate)
        audit = audit_g1_candidate(candidate=candidate)
        assert audit.passed is True


def _rebuild_inputs_with_suspend_specs(
    inputs: G1BuildInputs,
    suspend_specs: list[TushareRequestSpec],
) -> G1BuildInputs:
    """Rebuild plan/responses so only suspend_d specs differ; multiset stays closed."""
    history_requests = [
        spec
        for spec in inputs.request_plan.history_batch.requests
        if spec.endpoint != "suspend_d"
    ] + list(suspend_specs)
    history_batch = backfill._make_batch("HISTORY", history_requests)
    plan = backfill.G1RequestPlan(
        "m3-g1-request-plan-v3",
        inputs.request_plan.index_weight_batch,
        history_batch,
        inputs.request_plan.cninfo_rights_batch,
        inputs.request_plan.cninfo_dividend_batch,
        inputs.request_plan.cninfo_share_change_batch,
        backfill._plan_hash(
            inputs.request_plan.index_weight_batch,
            history_batch,
            inputs.request_plan.cninfo_rights_batch,
            inputs.request_plan.cninfo_dividend_batch,
            inputs.request_plan.cninfo_share_change_batch,
        ),
    )
    non_suspend = [
        item for item in inputs.responses if item.spec.endpoint != "suspend_d"
    ]
    suspend_responses = [
        _make_verified(
            "suspend_d",
            _empty_suspend(),
            parameters={
                "ts_code": dict(spec.parameters)["ts_code"],
                "start_date": dict(spec.parameters)["start_date"],
                "end_date": dict(spec.parameters)["end_date"],
                "suspend_type": dict(spec.parameters)["suspend_type"],
            },
        )
        for spec in suspend_specs
    ]
    by_id = {item.spec.request_id: item for item in non_suspend + suspend_responses}
    ordered = [by_id[spec.request_id] for spec in plan.index_weight_batch.requests] + [
        by_id[spec.request_id] for spec in plan.history_batch.requests
    ]
    return G1BuildInputs(
        build_spec=inputs.build_spec,
        request_plan=plan,
        responses=tuple(ordered),
        cninfo_responses=inputs.cninfo_responses,
        cninfo_dividend_responses=inputs.cninfo_dividend_responses,
        cninfo_share_change_responses=inputs.cninfo_share_change_responses,
        calendars=inputs.calendars,
        instruments=inputs.instruments,
        universe=inputs.universe,
        signal_start=inputs.signal_start,
        signal_end=inputs.signal_end,
        history=inputs.history,
        expected_constituent_count=inputs.expected_constituent_count,
        factor_ratio_rtol=inputs.factor_ratio_rtol,
    )


def test_suspend_d_natural_month_window_rejected(
    happy_inputs: G1BuildInputs,
) -> None:
    """旧自然月 end 窗口不得被 candidate 接受。"""
    month_start = happy_inputs.history.start.replace(day=1)
    month_end = (month_start.replace(day=28) + dt.timedelta(days=4)).replace(
        day=1
    ) - dt.timedelta(days=1)
    assert month_end != happy_inputs.history.end
    monthly: list[TushareRequestSpec] = []
    for spec in happy_inputs.request_plan.history_batch.requests:
        if spec.endpoint != "suspend_d":
            continue
        params = dict(spec.parameters)
        monthly.append(
            TushareRequestSpec.create(
                endpoint="suspend_d",
                parameters={
                    "fields": TUSHARE_FIELDS["suspend_d"],
                    "ts_code": params["ts_code"],
                    "start_date": month_start.strftime("%Y%m%d"),
                    "end_date": month_end.strftime("%Y%m%d"),
                    "suspend_type": "S",
                },
            )
        )
    poisoned = _rebuild_inputs_with_suspend_specs(happy_inputs, monthly)
    with pytest.raises(M3G1CandidateError) as excinfo:
        build_g1_candidate(inputs=poisoned)
    assert excinfo.value.code == "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"
    assert excinfo.value.__cause__ is None


def test_suspend_d_missing_symbol_rejected(happy_inputs: G1BuildInputs) -> None:
    """缺任一 history_symbol 的 suspend_d 不得被 candidate 接受。"""
    suspend_specs = [
        spec
        for spec in happy_inputs.request_plan.history_batch.requests
        if spec.endpoint == "suspend_d"
    ]
    assert len(suspend_specs) >= 2
    poisoned = _rebuild_inputs_with_suspend_specs(happy_inputs, suspend_specs[1:])
    with pytest.raises(M3G1CandidateError) as excinfo:
        build_g1_candidate(inputs=poisoned)
    assert excinfo.value.code == "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH"
    assert excinfo.value.__cause__ is None


def test_package_exports() -> None:
    import quant.data as qd

    assert qd.build_g1_candidate is build_g1_candidate
    assert qd.audit_g1_candidate is audit_g1_candidate
    assert qd.G1_MEMBERSHIP_METHOD_VERSION == G1_MEMBERSHIP_METHOD_VERSION


def test_p0d_versions_and_scoped_projection_bounds() -> None:
    assert G1_CORPORATE_ACTION_SELECTION_VERSION == (
        "tushare_dividend_cninfo_rights_share_consideration_basis_v8"
    )
    assert G1_CORPORATE_ACTION_RECONCILIATION_VERSION == (
        "tushare_factor_daily_preclose_suspension_resume_basis_terms_v9"
    )
    with pytest.raises(ValueError, match="corporate_action_reconciliation_version"):
        G1BuildSpec(
            config_version="m3-g1-test-v1",
            g1_config_sha256=_HEX,
            mapper_version="m3-g1-tushare-mapper-v5",
            schema_version="m3-g1-schema-v3",
            membership_method_version=G1_MEMBERSHIP_METHOD_VERSION,
            price_limit_method_version=G1_PRICE_LIMIT_METHOD_VERSION,
            corporate_action_selection_version=G1_CORPORATE_ACTION_SELECTION_VERSION,
            corporate_action_reconciliation_version="tushare_factor_daily_preclose_v3",
            benchmark_mode="TRADEABLE_ETF_TOTAL_RETURN_PROXY",
            benchmark_method_version="tushare_510300_fund_daily_fund_adj_hfq_v1",
            benchmark_dividend_reconciliation_version=(
                "tushare_fund_div_implemented_cash_v1"
            ),
            build_code_version="m3-g1-candidate-v1",
            dependency_fingerprint_sha256=_HEX,
        )
    d0 = dt.date(2016, 2, 1)
    d1 = dt.date(2016, 2, 2)
    d_halt = dt.date(2016, 2, 3)
    d2 = dt.date(2016, 2, 4)
    d3 = dt.date(2016, 2, 5)
    symbol = "000001.SZ"
    bars = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": day,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 1.0,
                "amount": 1.0,
                "source": "tushare",
            }
            for day in (d1, d2)
        ]
    )
    factors = pl.DataFrame(
        [
            {
                "symbol": symbol,
                "effective_date": day,
                "adj_factor": 1.0 if day != d0 else 0.5,
                "source": "tushare",
            }
            for day in (d0, d1, d_halt, d2, d3)
        ]
    )
    # Input shuffle must not change scoped projection.
    scoped = project_scoped_adjustment_factors(
        bars=bars, adjustment_factors=factors.reverse()
    )
    # Inclusive bounds + keep mid-span suspension factor without a bar.
    assert scoped.get_column("effective_date").to_list() == [d1, d_halt, d2]
    assert scoped.get_column("adj_factor").to_list() == [1.0, 1.0, 1.0]
    assert d0 not in scoped.get_column("effective_date").to_list()
    assert d3 not in scoped.get_column("effective_date").to_list()


def test_p0d_build_excludes_pre_first_bar_factor_jump(
    happy_inputs: G1BuildInputs,
) -> None:
    """Structural 000553: pre-first-bar jump + ledger event must not fail build."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "adj_factor":
            # D0 factor 1.0 -> D1 factor 1.2 (~20% jump) plus ledger event on D0.
            frame = pl.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "trade_date": _D0.strftime("%Y%m%d"),
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": symbol,
                        "trade_date": _D1.strftime("%Y%m%d"),
                        "adj_factor": 1.2,
                    },
                ]
            ).select(TUSHARE_FIELDS["adj_factor"].split(","))
            replacement = _make_verified(
                "adj_factor", frame, parameters=request_params
            )
        elif endpoint == "dividend":
            frame = pl.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "end_date": _D0.strftime("%Y%m%d"),
                        "ann_date": _D0.strftime("%Y%m%d"),
                        "div_proc": "实施",
                        "stk_div": 0.0,
                        "stk_bo_rate": None,
                        "stk_co_rate": None,
                        "cash_div": 0.1,
                        "cash_div_tax": 0.1,
                        "record_date": _D0.strftime("%Y%m%d"),
                        "ex_date": _D0.strftime("%Y%m%d"),
                        "pay_date": _D0.strftime("%Y%m%d"),
                        "div_listdate": None,
                        "imp_ann_date": _D0.strftime("%Y%m%d"),
                        "base_date": None,
                        "base_share": None,
                    }
                ]
            ).select(TUSHARE_FIELDS["dividend"].split(","))
            replacement = _make_verified(
                "dividend", frame, parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)

    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    verify_g1_candidate(inputs=inputs, candidate=candidate)
    audit = audit_g1_candidate(candidate=candidate)
    assert audit.passed is True
    assert candidate.build_spec.mapper_version == "m3-g1-tushare-mapper-v5"
    assert (
        candidate.build_spec.corporate_action_selection_version
        == "tushare_dividend_cninfo_rights_share_consideration_basis_v8"
    )
    assert (
        candidate.build_spec.corporate_action_reconciliation_version
        == "tushare_factor_daily_preclose_suspension_resume_basis_terms_v9"
    )
    scoped = candidate.adjustment_factors.filter(pl.col("symbol") == symbol)
    assert scoped.get_column("effective_date").to_list() == [_D1]
    assert scoped.get_column("adj_factor").to_list() == [1.2]
    # Ledger may retain the pre-bar event; reconciliation must not include it.
    ledger = candidate.corporate_actions.filter(pl.col("symbol") == symbol)
    assert ledger.height >= 1
    assert ledger.filter(pl.col("ex_date") == _D0).height == 1
    recon = candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") == symbol
    )
    assert recon.height == 0


def test_p0d_audit_rejects_restored_out_of_scope_factors(
    happy_inputs: G1BuildInputs,
) -> None:
    """Audit: self-contained bar-span check. Verify: rebuild from frozen inputs."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)
    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    assert candidate.adjustment_factors.filter(pl.col("symbol") == symbol).height == 1

    restored = pl.concat(
        [
            candidate.adjustment_factors,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "effective_date": _D0,
                        "adj_factor": 0.5,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])
    attacked = _rebind_identity(candidate, adjustment_factors=restored)
    # audit_g1_candidate only sees candidate tables: reject out-of-span factors.
    audit = audit_g1_candidate(candidate=attacked)
    assert audit.passed is False
    assert any(
        issue.code == "FACTOR_INVALID"
        and "outside publish bar scope" in issue.message
        for issue in audit.issues
    )
    # verify_g1_candidate rebuilds scoped factors from frozen inputs and mismatches.
    with pytest.raises(M3G1CandidateError) as caught:
        verify_g1_candidate(inputs=inputs, candidate=attacked)
    assert caught.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_p0d_bar_missing_factor_and_lineage_still_fail(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    symbol = _symbols()[0]
    factors = happy_candidate.adjustment_factors.filter(pl.col("symbol") == symbol)
    bars = happy_candidate.bars.filter(pl.col("symbol") == symbol).drop("adj_factor")
    daily = [
        item
        for item in happy_inputs.responses
        if item.spec.endpoint == "daily"
        and dict(item.spec.parameters).get("ts_code") == symbol
    ]
    factor_resps = [
        item
        for item in happy_inputs.responses
        if item.spec.endpoint == "adj_factor"
        and dict(item.spec.parameters).get("ts_code") == symbol
    ]
    with pytest.raises(M3G1CandidateError):
        apply_adjustment_factors_strict(
            bars=bars,
            adjustment_factors=factors.head(factors.height - 1),
            daily_responses=daily,
            factor_responses=factor_resps,
        )
    bad_factor = factors.with_columns(pl.lit(-1.0).alias("adj_factor"))
    with pytest.raises(M3G1CandidateError):
        apply_adjustment_factors_strict(
            bars=bars,
            adjustment_factors=bad_factor,
            daily_responses=daily,
            factor_responses=factor_resps,
        )


_D2 = dt.date(2016, 2, 3)  # Wed; mid-span halt day between D0 and D2 bars


def _assert_topology_mismatch(audit: Any) -> None:
    assert audit.passed is False
    assert any(
        issue.code == "CORPORATE_ACTION_FACTOR_MISMATCH"
        and "scoped factor transition topology mismatch" in issue.message
        for issue in audit.issues
    )


def _clone_no_event_recon_row(
    template: dict[str, Any],
    *,
    previous_factor_date: dt.date,
    effective_date: dt.date,
    actual_factor_ratio: float,
) -> dict[str, Any]:
    row = dict(template)
    row["previous_factor_date"] = previous_factor_date
    row["effective_date"] = effective_date
    row["actual_factor_ratio"] = actual_factor_ratio
    row["declared_dividend_relative_error"] = abs(actual_factor_ratio - 1.0)
    row["declared_dividend_factor_ratio"] = 1.0
    row["event_count"] = 0
    row["cash_per_share_gross"] = 0.0
    row["stock_ratio"] = 0.0
    row["previous_close_date"] = None
    row["previous_close"] = None
    row["ex_reference_price"] = None
    row["market_reference_factor_ratio"] = None
    row["market_reference_relative_error"] = None
    row["status"] = "NO_EVENT_STABLE_FACTOR"
    return row


def test_p0d_r1_audit_rejects_deleted_transition_evidence(
    happy_candidate: G1Candidate, happy_inputs: G1BuildInputs
) -> None:
    """Matrix 1: delete one scoped transition evidence → topology fail."""
    target = (
        happy_candidate.corporate_action_reconciliation.filter(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
    )
    assert target.height == 1
    trimmed = happy_candidate.corporate_action_reconciliation.filter(
        ~(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
    )
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=trimmed
    )
    _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))
    with pytest.raises(M3G1CandidateError) as caught:
        verify_g1_candidate(inputs=happy_inputs, candidate=attacked)
    assert caught.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_p0d_r1_audit_rejects_non_adjacent_previous_date(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 2: previous_factor_date not the immediate prior factor day."""
    earlier = dt.date(2016, 1, 29)
    mutated = happy_candidate.corporate_action_reconciliation.with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
        .then(pl.lit(earlier))
        .otherwise(pl.col("previous_factor_date"))
        .alias("previous_factor_date")
    )
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=mutated
    )
    _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))


def test_p0d_r1_audit_rejects_extra_topology_evidence(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 3: schema-legal extra evidence outside expected topology."""
    template = happy_candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") == "000001.SZ"
    ).to_dicts()[0]
    extra = _clone_no_event_recon_row(
        template,
        previous_factor_date=_D0,
        effective_date=dt.date(2016, 2, 5),
        actual_factor_ratio=1.0,
    )
    expanded = pl.concat(
        [
            happy_candidate.corporate_action_reconciliation,
            pl.DataFrame([extra]),
        ]
    ).sort(["symbol", "effective_date", "source"])
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=expanded
    )
    _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))


def test_p0d_r1_audit_rejects_rewritten_actual_factor_ratio(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 4: sync formula fields; exact factor ratio bind still fails."""
    # Stay within NO_EVENT rtol so row-formula verify passes; topology exactness fails.
    rewritten = 1.0005
    mutated = happy_candidate.corporate_action_reconciliation.with_columns(
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
        .then(pl.lit(rewritten))
        .otherwise(pl.col("actual_factor_ratio"))
        .alias("actual_factor_ratio"),
        pl.when(
            (pl.col("symbol") == "000001.SZ")
            & (pl.col("previous_factor_date") == _D0)
            & (pl.col("effective_date") == _D1)
        )
        .then(pl.lit(abs(rewritten - 1.0)))
        .otherwise(pl.col("declared_dividend_relative_error"))
        .alias("declared_dividend_relative_error"),
    )
    attacked = _rebind_identity(
        happy_candidate, corporate_action_reconciliation=mutated
    )
    audit = audit_g1_candidate(candidate=attacked)
    _assert_topology_mismatch(audit)
    # Row-formula verify must not be the only failure mode for this attack.
    assert not any(
        issue.message == "reconciliation result failed verification"
        for issue in audit.issues
    )


def test_p0d_r1_single_scoped_factor_allows_empty_evidence(
    happy_inputs: G1BuildInputs,
) -> None:
    """Matrix 5: one scoped factor → zero transitions; empty evidence legal."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)
    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    scoped = candidate.adjustment_factors.filter(pl.col("symbol") == symbol)
    assert scoped.height == 1
    recon = candidate.corporate_action_reconciliation.filter(pl.col("symbol") == symbol)
    assert recon.height == 0
    audit = audit_g1_candidate(candidate=candidate)
    assert audit.passed is True
    assert audit.issues == ()


def _mid_halt_scoped_candidate(happy_candidate: G1Candidate) -> G1Candidate:
    """Bars on D0/D2 with mid-span D1 factor → two adjacent transitions."""
    symbol = "000001.SZ"
    d1_bar = happy_candidate.bars.filter(
        (pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1)
    ).to_dicts()[0]
    d2_bar = dict(d1_bar)
    d2_bar["trade_date"] = _D2
    bars = pl.concat(
        [
            happy_candidate.bars.filter(
                ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1))
            ),
            pl.DataFrame([d2_bar]),
        ]
    ).sort(["symbol", "trade_date", "source"])

    factors = pl.concat(
        [
            happy_candidate.adjustment_factors,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "effective_date": _D2,
                        "adj_factor": 1.0,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])

    d1_match = happy_candidate.factor_match_evidence.filter(
        (pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1)
    ).to_dicts()[0]
    d2_match = dict(d1_match)
    d2_match["trade_date"] = _D2
    matches = pl.concat(
        [
            happy_candidate.factor_match_evidence.filter(
                ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1))
            ),
            pl.DataFrame([d2_match]),
        ]
    ).sort(["symbol", "trade_date", "source"])

    d1_limit = happy_candidate.price_limits.filter(
        (pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1)
    ).to_dicts()[0]
    d2_limit = dict(d1_limit)
    d2_limit["trade_date"] = _D2
    limits = pl.concat(
        [
            happy_candidate.price_limits.filter(
                ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == _D1))
            ),
            pl.DataFrame([d2_limit]),
        ]
    ).sort(["symbol", "trade_date", "source"])

    suspensions = pl.concat(
        [
            happy_candidate.suspensions,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "trade_date": _D1,
                        "suspension_scope": "FULL_DAY",
                        "suspension_detail": None,
                        "source": "tushare",
                        "source_snapshot_id": _HEX,
                    }
                ]
            ),
        ]
    ).sort(["symbol", "trade_date", "source"])

    bench_d1 = happy_candidate.benchmark_bars.filter(
        pl.col("trade_date") == _D1
    ).to_dicts()[0]
    bench_d2 = dict(bench_d1)
    bench_d2["trade_date"] = _D2
    benchmarks = pl.concat(
        [happy_candidate.benchmark_bars, pl.DataFrame([bench_d2])]
    ).sort(["benchmark", "trade_date", "source"])

    template = happy_candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") == symbol
    ).to_dicts()[0]
    other_recon = happy_candidate.corporate_action_reconciliation.filter(
        pl.col("symbol") != symbol
    )
    recon = pl.concat(
        [
            other_recon,
            pl.DataFrame(
                [
                    _clone_no_event_recon_row(
                        template,
                        previous_factor_date=_D0,
                        effective_date=_D1,
                        actual_factor_ratio=1.0,
                    ),
                    _clone_no_event_recon_row(
                        template,
                        previous_factor_date=_D1,
                        effective_date=_D2,
                        actual_factor_ratio=1.0,
                    ),
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])

    return _rebind_identity(
        happy_candidate,
        history_end=_D2,
        bars=bars,
        adjustment_factors=factors,
        factor_match_evidence=matches,
        price_limits=limits,
        suspensions=suspensions,
        benchmark_bars=benchmarks,
        corporate_action_reconciliation=recon,
    )


def test_p0d_r1_mid_halt_transitions_delete_either_fails(
    happy_candidate: G1Candidate,
) -> None:
    """Matrix 6: mid-span halt factor → two transitions; delete either fails."""
    base = _mid_halt_scoped_candidate(happy_candidate)
    audit_ok = audit_g1_candidate(candidate=base)
    assert audit_ok.passed is True
    assert audit_ok.issues == ()
    scoped = base.adjustment_factors.filter(pl.col("symbol") == "000001.SZ")
    assert scoped.get_column("effective_date").to_list() == [_D0, _D1, _D2]
    recon = base.corporate_action_reconciliation.filter(pl.col("symbol") == "000001.SZ")
    assert recon.height == 2

    for previous, effective in ((_D0, _D1), (_D1, _D2)):
        trimmed = base.corporate_action_reconciliation.filter(
            ~(
                (pl.col("symbol") == "000001.SZ")
                & (pl.col("previous_factor_date") == previous)
                & (pl.col("effective_date") == effective)
            )
        )
        attacked = _rebind_identity(base, corporate_action_reconciliation=trimmed)
        _assert_topology_mismatch(audit_g1_candidate(candidate=attacked))


def test_p0d_r1_adv3a_out_of_scope_factor_still_rejected(
    happy_inputs: G1BuildInputs,
) -> None:
    """Matrix 7: ADV3a bar-span reject kept; verify still inputs-rebuild only."""
    symbol = _symbols()[0]
    replacements: list[VerifiedRawResponse] = []
    for item in happy_inputs.responses:
        params = dict(item.spec.parameters)
        endpoint = item.spec.endpoint
        if params.get("ts_code") != symbol:
            replacements.append(item)
            continue
        request_params = {key: value for key, value in params.items() if key != "fields"}
        if endpoint == "daily":
            replacement = _make_verified(
                "daily", _daily_frame(symbol, [_D1]), parameters=request_params
            )
        elif endpoint == "suspend_d":
            replacement = _make_verified(
                "suspend_d",
                _full_day_suspend(symbol, _D0),
                parameters=request_params,
            )
        else:
            replacements.append(item)
            continue
        assert replacement.spec == item.spec
        replacements.append(replacement)
    inputs = replace(happy_inputs, responses=tuple(replacements))
    candidate = build_g1_candidate(inputs=inputs)
    restored = pl.concat(
        [
            candidate.adjustment_factors,
            pl.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "effective_date": _D0,
                        "adj_factor": 0.5,
                        "source": "tushare",
                    }
                ]
            ),
        ]
    ).sort(["symbol", "effective_date", "source"])
    attacked = _rebind_identity(candidate, adjustment_factors=restored)
    audit = audit_g1_candidate(candidate=attacked)
    assert audit.passed is False
    assert any(
        issue.code == "FACTOR_INVALID"
        and "outside publish bar scope" in issue.message
        for issue in audit.issues
    )
    with pytest.raises(M3G1CandidateError) as caught:
        verify_g1_candidate(inputs=inputs, candidate=attacked)
    assert caught.value.code == "G1_CANDIDATE_IDENTITY_MISMATCH"


def test_p0d_r1_happy_and_no_event_jump_still_pass(
    happy_candidate: G1Candidate, happy_inputs: G1BuildInputs
) -> None:
    """Matrix 8: legal happy audit continues to pass after topology bind."""
    audit = audit_g1_candidate(candidate=happy_candidate)
    assert audit.passed is True
    assert audit.issues == ()
    verify_g1_candidate(inputs=happy_inputs, candidate=happy_candidate)
    assert happy_candidate.corporate_action_reconciliation.height == 300
def test_p0k_a_cninfo_ca_raw_changes_identity_without_ledger(
    happy_inputs: G1BuildInputs, happy_candidate: G1Candidate
) -> None:
    """Mutating F010N/VARYDATE changes candidate key; CA frames stay out of ledger."""
    from quant.data.connectors.cninfo import (
        CNINFO_DIVIDEND_ENDPOINT,
        CNINFO_STOCK_DIVIDEND_FIELDS,
        CNINFO_STOCK_SHARE_CHANGE_FIELDS,
    )

    base_actions = happy_candidate.corporate_actions.height
    base_evidence = happy_candidate.corporate_action_selection_evidence.height
    div_spec = happy_inputs.request_plan.cninfo_dividend_batch.requests[0]
    share_spec = happy_inputs.request_plan.cninfo_share_change_batch.requests[0]

    div_row = {name: None for name in CNINFO_STOCK_DIVIDEND_FIELDS}
    div_row.update({"F001V": "股权分置", "F010N": "5", "F044V": "10送5"})
    div_frame = pl.DataFrame(
        [div_row], schema={name: pl.Utf8 for name in CNINFO_STOCK_DIVIDEND_FIELDS}
    )
    share_row = {name: None for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    share_row.update(
        {
            "SECCODE": dict(share_spec.parameters)["symbol"],
            "VARYDATE": "2018-08-23",
            "F001V": "股权分置",
        }
    )
    share_frame = pl.DataFrame(
        [share_row], schema={name: pl.Utf8 for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    )

    mutated_div = []
    for item in happy_inputs.cninfo_dividend_responses:
        if item.spec.request_id == div_spec.request_id:
            mutated_div.append(_make_cninfo_ca_verified(item.spec, frame=div_frame))
        else:
            mutated_div.append(item)
    mutated_share = []
    for item in happy_inputs.cninfo_share_change_responses:
        if item.spec.request_id == share_spec.request_id:
            mutated_share.append(_make_cninfo_ca_verified(item.spec, frame=share_frame))
        else:
            mutated_share.append(item)

    altered = G1BuildInputs(
        build_spec=happy_inputs.build_spec,
        request_plan=happy_inputs.request_plan,
        responses=happy_inputs.responses,
        cninfo_responses=happy_inputs.cninfo_responses,
        cninfo_dividend_responses=tuple(mutated_div),
        cninfo_share_change_responses=tuple(mutated_share),
        calendars=happy_inputs.calendars,
        instruments=happy_inputs.instruments,
        universe=happy_inputs.universe,
        signal_start=happy_inputs.signal_start,
        signal_end=happy_inputs.signal_end,
        history=happy_inputs.history,
        expected_constituent_count=happy_inputs.expected_constituent_count,
        factor_ratio_rtol=happy_inputs.factor_ratio_rtol,
    )
    other = build_g1_candidate(inputs=altered)
    assert other.primary_candidate_key != happy_candidate.primary_candidate_key
    assert other.request_plan.plan_sha256 == happy_candidate.request_plan.plan_sha256
    # receipt projection digest must move with CA content
    assert other.input_receipts != happy_candidate.input_receipts
    assert other.corporate_actions.height == base_actions
    assert other.corporate_action_selection_evidence.height == base_evidence
    # endpoints are projected but not selected into ledger in P0K-A
    assert any(item.endpoint == CNINFO_DIVIDEND_ENDPOINT for item in other.input_receipts)
    assert any(item.endpoint == "stock_share_change" for item in other.input_receipts)

    physical_only = list(happy_inputs.cninfo_dividend_responses)
    original = physical_only[0]
    physical_only[0] = _make_cninfo_ca_verified(
        original.spec,
        frame=original.frame,
        raw_metadata_sha256="b" * 64,
    )
    physical_candidate = build_g1_candidate(
        inputs=replace(
            happy_inputs,
            cninfo_dividend_responses=tuple(physical_only),
        )
    )
    assert (
        physical_candidate.primary_candidate_key
        != happy_candidate.primary_candidate_key
    )
    assert physical_candidate.corporate_actions.equals(
        happy_candidate.corporate_actions
    )


def _p0kc_candidate_inputs(
    inputs: G1BuildInputs,
    *,
    share_row_overrides: dict[str, Any] | None = None,
) -> G1BuildInputs:
    symbol = "000001.SZ"
    code = "000001"
    declared_factor = 10.0 * 1.3 / (10.0 + 2.0 * 0.3)
    ex_reference = 10.0 / declared_factor

    responses: list[VerifiedRawResponse] = []
    for item in inputs.responses:
        parameters = dict(item.spec.parameters)
        is_target = parameters.get("ts_code") == symbol
        if item.spec.endpoint == "daily" and is_target:
            frame = _daily_frame(symbol, [_D0, _D1]).with_columns(
                pl.when(pl.col("trade_date") == _D1.strftime("%Y%m%d"))
                .then(pl.lit(ex_reference))
                .otherwise(pl.col(name))
                .alias(name)
                for name in ("open", "high", "low", "close", "pre_close")
            )
            responses.append(_make_verified("daily", frame, parameters=parameters))
        elif item.spec.endpoint == "adj_factor" and is_target:
            frame = pl.DataFrame(
                [
                    {
                        "ts_code": symbol,
                        "trade_date": _D0.strftime("%Y%m%d"),
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": symbol,
                        "trade_date": _D1.strftime("%Y%m%d"),
                        "adj_factor": declared_factor,
                    },
                ]
            ).select(TUSHARE_FIELDS["adj_factor"].split(","))
            responses.append(
                _make_verified("adj_factor", frame, parameters=parameters)
            )
        elif item.spec.endpoint == "stk_limit" and is_target:
            frame = _limit_frame(symbol, [_D0, _D1]).with_columns(
                pl.when(pl.col("trade_date") == _D1.strftime("%Y%m%d"))
                .then(pl.lit(ex_reference))
                .otherwise(pl.col("pre_close"))
                .alias("pre_close"),
                pl.when(pl.col("trade_date") == _D1.strftime("%Y%m%d"))
                .then(pl.lit(ex_reference * 1.1))
                .otherwise(pl.col("up_limit"))
                .alias("up_limit"),
                pl.when(pl.col("trade_date") == _D1.strftime("%Y%m%d"))
                .then(pl.lit(ex_reference * 0.9))
                .otherwise(pl.col("down_limit"))
                .alias("down_limit"),
            )
            responses.append(
                _make_verified("stk_limit", frame, parameters=parameters)
            )
        else:
            responses.append(item)

    rights_row = {name: None for name in CNINFO_STOCK_ALLOTMENT_FIELDS}
    rights_row.update(
        {
            "DECLAREDATE": _D0.isoformat(),
            "F001V": "001001",
            "F002V": "A股",
            "F004N": "3",
            "F005N": "2",
            "F011D": _D0.isoformat(),
            "F012D": _D1.isoformat(),
            "F013D": "2016-01-31",
            "F014D": "2016-01-31",
            "F017N": "300",
            "F024N": "1000",
            "F025N": "1300.5",
            "F038D": _D1.isoformat(),
            "F041N": "800",
            "F042N": "1100.5",
            "F052D": _D1.isoformat(),
            "ORGNAME": "P0KC测试公司",
            "SECCODE": code,
            "SECNAME": "P0KC测试",
            "SUBID": "p0kc-1",
        }
    )
    rights_frame = pl.DataFrame(
        [rights_row],
        schema={name: pl.Utf8 for name in CNINFO_STOCK_ALLOTMENT_FIELDS},
    )
    rights_responses = []
    for item in inputs.cninfo_responses:
        symbols = dict(item.spec.parameters)["symbols"].split(",")
        rights_responses.append(
            _make_cninfo_verified(
                item.spec,
                frame=rights_frame if code in symbols else None,
            )
        )

    share_row = {name: None for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    share_row.update(
        {
            "DECLAREDATE": _D1.isoformat(),
            "VARYDATE": _D1.isoformat(),
            "F001V": "015012,015005",
            "F002V": "可转债转股,配股上市",
            "F003N": "1300.5",
            "F021N": "1100.5",
            "F022N": "1100.5",
            "SECCODE": code,
        }
    )
    if share_row_overrides:
        share_row.update(share_row_overrides)
    share_frame = pl.DataFrame(
        [share_row],
        schema={name: pl.Utf8 for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS},
    )
    share_responses = []
    for item in inputs.cninfo_share_change_responses:
        item_code = dict(item.spec.parameters)["symbol"]
        share_responses.append(
            _make_cninfo_ca_verified(
                item.spec,
                frame=share_frame if item_code == code else None,
            )
        )

    return replace(
        inputs,
        responses=tuple(responses),
        cninfo_responses=tuple(rights_responses),
        cninfo_share_change_responses=tuple(share_responses),
    )


def test_p0kc_candidate_build_audit_and_formal_receipt_closure(
    happy_inputs: G1BuildInputs,
) -> None:
    official = build_g1_candidate(
        inputs=_p0kc_candidate_inputs(happy_inputs)
    )
    rights = official.corporate_actions.filter(pl.col("action_type") == "RIGHTS")
    assert rights.height == 1
    assert rights["rights_mixed_change_proof_sha256"][0] is not None
    assert audit_g1_candidate(candidate=official).passed is True

    forged = build_g1_candidate(
        inputs=_p0kc_candidate_inputs(
            happy_inputs,
            share_row_overrides={"F004N": "1"},
        )
    )
    assert audit_g1_candidate(candidate=forged).passed is True
    assert not forged.corporate_actions.equals(official.corporate_actions)

    attacked = _rebind_identity(
        official,
        corporate_actions=forged.corporate_actions,
        corporate_action_selection_evidence=(
            forged.corporate_action_selection_evidence
        ),
        corporate_action_reconciliation=forged.corporate_action_reconciliation,
    )
    audit = audit_g1_candidate(candidate=attacked)
    assert audit.passed is False
    assert any(
        issue.code == "CORPORATE_ACTION_FACTOR_MISMATCH"
        and issue.message == "reconciliation result failed verification"
        for issue in audit.issues
    )


def _p0kb_dividend_frame(**overrides: Any) -> pl.DataFrame:
    row = {name: None for name in CNINFO_STOCK_DIVIDEND_FIELDS}
    row.update(
        {
            "F006D": "2018-08-20",
            "F007V": "10送5股",
            "F010N": "5",
            "F018D": "2018-02-01",
            "F044V": "承诺补偿",
        }
    )
    row.update(overrides)
    return pl.DataFrame(
        [row], schema={name: pl.Utf8 for name in CNINFO_STOCK_DIVIDEND_FIELDS}
    )


def _p0kb_share_frame(
    *, circulating_after: str = "39690", duplicate_reform: bool = False
) -> pl.DataFrame:
    before = {name: None for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    before.update(
        {
            "DECLAREDATE": "2018-08-25",
            "F001V": "015004,015020",
            "F002V": "增发新股上市,股权分置",
            "F003N": "95867.1182",
            "F021N": "11340",
            "SECCODE": "600733",
            "VARYDATE": "2018-08-23",
        }
    )
    after = {name: None for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    after.update(
        {
            "DECLAREDATE": "2018-09-13",
            "F001V": "015011",
            "F002V": "转增",
            "F003N": "335534.9137",
            "F021N": circulating_after,
            "SECCODE": "600733",
            "VARYDATE": "2018-09-19",
        }
    )
    rows = [before, after]
    if duplicate_reform:
        duplicate = dict(before)
        duplicate["DECLAREDATE"] = "2018-08-26"
        rows.insert(1, duplicate)
    return pl.DataFrame(
        rows, schema={name: pl.Utf8 for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS}
    )


def _p0kb_tushare_actions() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "event_id": "1" * 64,
                "symbol": "600733.SH",
                "ex_date": dt.date(2018, 9, 19),
                "action_type": "DIVIDEND_DISTRIBUTION",
                "cash_per_share_gross": 0.0,
                "stock_ratio": 2.5,
                "rights_price": None,
                "rights_ratio": 0.0,
                "rights_actual_shares": None,
                "rights_pre_shares": None,
                "rights_post_shares": None,
                "rights_pre_circulating_shares": None,
                "rights_post_circulating_shares": None,
                "rights_mixed_change_proof_sha256": None,
                "record_date": dt.date(2018, 9, 18),
                "pay_date": None,
                "stock_list_date": dt.date(2018, 9, 19),
                "vendor_record_id": None,
                "source": "tushare",
                "source_snapshot_id": "2" * 64,
            }
        ]
    )


def _p0kb_select(
    *,
    dividend_frame: pl.DataFrame | None = None,
    share_frame: pl.DataFrame | None = None,
    existing_actions: pl.DataFrame | None = None,
):
    dividend_spec = backfill.CninfoCorporateActionRequestSpec.create(
        endpoint=CNINFO_DIVIDEND_ENDPOINT,
        parameters={"symbol": "600733"},
    )
    share_spec = backfill.CninfoCorporateActionRequestSpec.create(
        endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
        parameters={
            "symbol": "600733",
            "start_date": "20151009",
            "end_date": "20260710",
        },
    )
    return select_g1_cninfo_share_consideration_actions(
        dividend_response=_make_cninfo_ca_verified(
            dividend_spec,
            frame=(
                _p0kb_dividend_frame()
                if dividend_frame is None
                else dividend_frame
            ),
        ),
        share_change_response=_make_cninfo_ca_verified(
            share_spec,
            frame=_p0kb_share_frame() if share_frame is None else share_frame,
        ),
        history=HistoryWindow(dt.date(2015, 10, 9), dt.date(2026, 7, 10)),
        symbols=("600733.SH",),
        existing_actions=(
            _p0kb_tushare_actions()
            if existing_actions is None
            else existing_actions
        ),
    )


def test_p0kb_selects_raw_consideration_and_proves_basis() -> None:
    result, facts = _p0kb_select()
    assert result.ledger.height == 1
    row = result.ledger.row(0, named=True)
    assert row["action_type"] == "SHARE_CONSIDERATION"
    assert row["record_date"] == dt.date(2018, 2, 1)
    assert row["ex_date"] == dt.date(2018, 8, 23)
    assert row["stock_list_date"] == dt.date(2018, 8, 23)
    assert row["stock_ratio"] == 0.5
    assert len(facts) == 1
    assert facts[0].basis_multiplier == Decimal("3.5")
    assert facts[0].effective_stock_ratio == Decimal("0.5") / Decimal("3.5")


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"F007V": "承诺补偿", "F044V": "10送5股"}, "G1_CORPORATE_ACTION_EVENT_INVALID"),
        ({"F007V": "10送4股"}, "G1_CORPORATE_ACTION_EVENT_INVALID"),
    ],
)
def test_p0kb_rejects_swapped_or_mismatched_dividend_fields(
    overrides: dict[str, Any], code: str
) -> None:
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _p0kb_select(dividend_frame=_p0kb_dividend_frame(**overrides))
    assert caught.value.code == code


def test_p0kb_ordinary_cninfo_dividend_does_not_enter_ledger() -> None:
    result, facts = _p0kb_select(
        dividend_frame=_p0kb_dividend_frame(
            F044V="股改分红", F007V="10转增25股", F010N=None, F011N="25"
        )
    )
    assert result.ledger.is_empty()
    assert result.selection_evidence.is_empty()
    assert facts == ()


def test_p0kb_dated_ordinary_compensation_does_not_enter_special_path() -> None:
    result, facts = _p0kb_select(
        dividend_frame=_p0kb_dividend_frame(
            F001V="2017三季报",
            F006D="2017-12-08",
            F007V="10送0.03985947股",
            F010N="0.039859470000000001",
            F018D="2017-12-13",
            F025D="2017-12-15",
        )
    )
    assert result.ledger.is_empty()
    assert facts == ()


def test_p0kb_exact_tushare_consideration_is_not_duplicated() -> None:
    exact = _p0kb_tushare_actions().with_columns(pl.lit(0).alias("_order"))
    same = pl.DataFrame(
        [
            {
                "event_id": "3" * 64,
                "symbol": "600733.SH",
                "ex_date": dt.date(2018, 8, 23),
                "action_type": "DIVIDEND_DISTRIBUTION",
                "cash_per_share_gross": 0.0,
                "stock_ratio": 0.5,
                "rights_price": None,
                "rights_ratio": 0.0,
                "rights_actual_shares": None,
                "rights_pre_shares": None,
                "rights_post_shares": None,
                "rights_pre_circulating_shares": None,
                "rights_post_circulating_shares": None,
                "rights_mixed_change_proof_sha256": None,
                "record_date": dt.date(2018, 2, 1),
                "pay_date": None,
                "stock_list_date": dt.date(2018, 8, 23),
                "vendor_record_id": None,
                "source": "tushare",
                "source_snapshot_id": "4" * 64,
                "_order": 1,
            }
        ]
    )
    existing = (
        pl.concat([exact, same], how="vertical_relaxed")
        .sort("_order")
        .drop("_order")
    )
    result, facts = _p0kb_select(existing_actions=existing)
    assert result.ledger.is_empty()
    assert result.selection_evidence.is_empty()
    assert len(facts) == 1
    assert facts[0].event_id == "3" * 64


def test_p0kb_conflicting_tushare_consideration_fails_closed() -> None:
    existing = _p0kb_tushare_actions()
    conflict = existing.row(0, named=True)
    conflict.update(
        {
            "event_id": "3" * 64,
            "ex_date": dt.date(2018, 8, 23),
            "record_date": dt.date(2018, 2, 1),
            "stock_list_date": dt.date(2018, 8, 23),
            "stock_ratio": 0.4,
        }
    )
    existing = pl.concat([existing, pl.DataFrame([conflict])], how="vertical_relaxed")
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _p0kb_select(existing_actions=existing)
    assert caught.value.code == "G1_CORPORATE_ACTION_VERSION_CONFLICT"


def test_p0kb_conflicting_tushare_record_date_fails_closed() -> None:
    existing = _p0kb_tushare_actions()
    conflict = existing.row(0, named=True)
    conflict.update(
        {
            "event_id": "3" * 64,
            "ex_date": dt.date(2018, 8, 23),
            "record_date": dt.date(2018, 2, 2),
            "stock_list_date": dt.date(2018, 8, 23),
            "stock_ratio": 0.5,
        }
    )
    existing = pl.concat([existing, pl.DataFrame([conflict])], how="vertical_relaxed")
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _p0kb_select(existing_actions=existing)
    assert caught.value.code == "G1_CORPORATE_ACTION_VERSION_CONFLICT"


def test_p0kb_unexplained_issuance_cannot_prove_stock_basis() -> None:
    attacked = _p0kb_share_frame().with_columns(
        pl.when(pl.col("VARYDATE") == "2018-09-19")
        .then(pl.lit("015004"))
        .otherwise(pl.col("F001V"))
        .alias("F001V"),
        pl.when(pl.col("VARYDATE") == "2018-09-19")
        .then(pl.lit("增发新股上市"))
        .otherwise(pl.col("F002V"))
        .alias("F002V"),
    )
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _p0kb_select(share_frame=attacked)
    assert caught.value.code == "G1_CORPORATE_ACTION_BASIS_UNPROVEN"


@pytest.mark.parametrize(
    "share_frame",
    [
        _p0kb_share_frame(circulating_after="39000"),
        _p0kb_share_frame(duplicate_reform=True),
    ],
)
def test_p0kb_requires_unique_dual_share_basis(share_frame: pl.DataFrame) -> None:
    with pytest.raises(M3G1ExecutionFactError) as caught:
        _p0kb_select(share_frame=share_frame)
    assert caught.value.code == "G1_CORPORATE_ACTION_BASIS_UNPROVEN"
