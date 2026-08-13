"""Focused formal G7E single-scenario A-share replay tests."""

from __future__ import annotations

import datetime as dt
import importlib.util
import inspect
from dataclasses import replace
from decimal import Context, Decimal, Inexact, localcontext
from pathlib import Path
from typing import Any, Callable, cast

import polars as pl
import pytest

import quant.backtest.a_share_simulator as simulator_module
import quant.data.m3_release as release_module
from quant.backtest.a_share_execution import AShareMarketFactsFreshVerificationContext
from quant.backtest.a_share_plan import BacktestPlanFreshVerificationContext
from quant.backtest.a_share_simulator import (
    AShareSimulationError,
    AShareSimulationFreshVerificationContext,
    simulate_formal_a_share_scenario,
)
from quant.data.m3_g1_candidate import (
    CNINFO_ENDPOINT,
    CNINFO_SOURCE,
    CNINFO_STOCK_ALLOTMENT_FIELDS,
)
from quant.research.m3.contracts import (
    AShareCostPeriod,
    BacktestPlanManifestV1,
    BacktestWindow,
    TargetManifestV1,
    VerifiedBacktestPlanArtifact,
    VerifiedTargetArtifact,
)


def _load_support(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_F0 = _load_support(
    "m3_g7e_f0_capability_support",
    Path(__file__).with_name("test_m3_formal_a_share_market_facts.py"),
)
_TARGET = _load_support(
    "m3_g7e_target_context_support",
    Path(__file__).with_name("test_m3_formal_target_artifact.py"),
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_D = "d" * 64
_H = "1" * 64
_FOLD = "fold_001"
_SYMBOLS = ("000001.SZ", "000002.SZ", "600000.SH")


def _five_session_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frame_mutator: Callable[
        [dict[str, pl.DataFrame], tuple[dt.date, ...]], dict[str, pl.DataFrame]
    ] | None = None,
) -> tuple[Any, tuple[dt.date, ...]]:
    original = _F0._frames_and_plan

    def source() -> tuple[dict[str, pl.DataFrame], Any]:
        frames, plan = original()
        sessions = tuple(plan.manifest.window.execution_dates[:5])
        plan.manifest.window = BacktestWindow(
            signal_dates=tuple(day - dt.timedelta(days=1) for day in sessions),
            execution_dates=sessions,
            first_execution_date=sessions[0],
            terminal_valuation_date=sessions[-1],
            force_liquidation=False,
        )
        plan.scheduled_targets = plan.scheduled_targets.filter(
            pl.col("execution_date").is_in(list(sessions))
        )
        if frame_mutator is not None:
            frames = frame_mutator(frames, sessions)
        return frames, plan

    monkeypatch.setattr(_F0, "_frames_and_plan", source)
    facts = _F0._issued_capability(tmp_path, monkeypatch)
    sessions = tuple(cast(list[dt.date], facts.calendar.sort("date")["date"].to_list()))
    return facts, sessions


def _target_plan(
    tmp_path: Path,
    sessions: tuple[dt.date, ...],
    weights: tuple[tuple[float, float, float], ...] | None = None,
) -> tuple[VerifiedTargetArtifact, VerifiedBacktestPlanArtifact]:
    daily = weights or ((0.2, 0.2, 0.2),) * len(sessions)
    rows = [
        {
            "as_of": day - dt.timedelta(days=1),
            "strategy": "topk",
            "strategy_version": "test",
            "symbol": symbol,
            "weight": weight,
        }
        for day, day_weights in zip(sessions, daily, strict=True)
        for symbol, weight in zip(_SYMBOLS, day_weights, strict=True)
    ]
    targets = pl.DataFrame(rows).with_columns(pl.col("as_of").cast(pl.Date)).sort(
        "as_of", "symbol"
    )
    target = VerifiedTargetArtifact(
        root=tmp_path / "target",
        targets=targets,
        target_daily=pl.DataFrame(
            {"as_of": list(sessions), "selected_count": [3] * len(sessions)}
        ).with_columns(pl.col("as_of").cast(pl.Date)),
        manifest=TargetManifestV1(
            schema_version="m3-target-artifact-v1",
            experiment_key=_H,
            experiment_manifest_sha256=_H,
            work_key=_H,
            g1_release_id=_A,
            g1_release_manifest_sha256=_B,
            scientific_config_sha256=_H,
            prediction_manifest_sha256=_H,
            feature_manifest_sha256=_H,
            fold_plan_manifest_sha256=_H,
            snapshot_id=_H,
            fold=_FOLD,
            horizon_sessions=5,
            model="lightgbm",
            model_version="test",
            strategy="topk",
            strategy_version="test",
            eligible_keys_sha256=_H,
            signal_dates_sha256=_H,
            n_dates=len(sessions),
            n_eligible=len(rows),
            n_scorable=len(rows),
            n_predicted=len(rows),
            n_selected=len(rows),
            target_keys_sha256=_H,
            targets_sha256=_H,
            target_daily_sha256=_H,
        ),
        manifest_sha256="2" * 64,
        target_receipt_sha256="3" * 64,
    )
    scheduled = targets.join(
        pl.DataFrame(
            {
                "as_of": [day - dt.timedelta(days=1) for day in sessions],
                "execution_date": list(sessions),
            },
            schema={"as_of": pl.Date, "execution_date": pl.Date},
        ),
        on="as_of",
    ).select(
        "as_of", "strategy", "strategy_version", "symbol", "weight",
        "execution_date",
    ).sort("execution_date", "as_of", "symbol")
    window = BacktestWindow(
        signal_dates=tuple(day - dt.timedelta(days=1) for day in sessions),
        execution_dates=sessions,
        first_execution_date=sessions[0],
        terminal_valuation_date=sessions[-1],
        force_liquidation=False,
    )
    plan = VerifiedBacktestPlanArtifact(
        root=tmp_path / "plan",
        scheduled_targets=scheduled,
        manifest=BacktestPlanManifestV1(
            schema_version="m3-a-share-backtest-plan-v1",
            experiment_key=_H,
            experiment_manifest_sha256=_H,
            work_key=_H,
            target_manifest_sha256=target.manifest_sha256,
            target_receipt_sha256=target.target_receipt_sha256,
            g1_release_id=_A,
            g1_release_manifest_sha256=_B,
            scientific_config_sha256=_H,
            fold_plan_manifest_sha256=_H,
            fold=_FOLD,
            horizon_sessions=5,
            window=window,
            session_calendar_sha256=_H,
            cost_schedule_sha256=_H,
            cost_schedule_version="test",
            order_quantity_rule_version="sse_szse_limit_order_quantity_v1",
            scheduled_targets_sha256=_H,
            schedule_diagnostics_sha256=_H,
        ),
        manifest_sha256=_C,
        plan_receipt_sha256=_D,
    )
    return target, plan


def _identity_release(tmp_path: Path) -> release_module.VerifiedG1Release:
    root = tmp_path / _A
    entries = tuple(
        release_module.G1ArtifactEntryV1(
            path=spec.path, sha256=_H, content_sha256=_H, size_bytes=1,
            row_count=1 if spec.kind in {"summary", "quality"} else 0,
            schema_name=spec.schema_name, table_schema_version="v3",
            key_columns=spec.key_columns, min_key=None, max_key=None,
        )
        for spec in release_module._ARTIFACT_REGISTRY
    )
    receipt = release_module.G1ReceiptProjectionV1(
        source=CNINFO_SOURCE, request_id=_H, endpoint=CNINFO_ENDPOINT,
        parameters_sha256=_H, stable_response_sha256=_H, row_count=1,
        columns=CNINFO_STOCK_ALLOTMENT_FIELDS,
    )
    manifest = release_module.G1ManifestV5(
        schema_version="m3-g1-manifest-v5", release_id=_A,
        primary_candidate_key=_H, config_version="test", g1_config_sha256=_H,
        signal_start=dt.date(2026, 1, 1), signal_end=dt.date(2026, 1, 1),
        history_start=dt.date(2026, 1, 1), history_end=dt.date(2026, 1, 1),
        request_plan_sha256=_H, build_code_version="test",
        dependency_fingerprint_sha256=_H, mapper_version="m3-g1-tushare-mapper-v5",
        clean_schema_version="test", membership_method_version="test",
        price_limit_method_version="test", corporate_action_selection_version="test",
        corporate_action_reconciliation_version="test",
        benchmark_mode="TRADEABLE_ETF_TOTAL_RETURN_PROXY",
        benchmark_method_version="tushare_510300_fund_daily_fund_adj_hfq_v1",
        benchmark_dividend_reconciliation_version=(
            "tushare_fund_div_implemented_cash_v1"
        ),
        input_receipts=(receipt,), price_limit_required_keys_sha256=_H,
        sample_plan_sha256=_H, cross_source_summary_sha256=_H,
        quality_sha256=_H, files=tuple(sorted(entries, key=lambda item: item.path)),
    )
    quality = release_module.G1QualityReportV1(
        schema_version="m3-g1-quality-v1", release_id=_A,
        primary_candidate_key=_H, plan_sha256=_H, error_count=0,
        warning_count=0, passed=True, issues=(),
    )
    release = release_module.G1Release(
        release_id=_A,
        root=root,
        manifest_path=root / "manifest.json",
        quality_path=root / "quality.json",
    )
    return release_module.VerifiedG1Release(
        release=release,
        manifest=manifest,
        manifest_sha256=_B,
        quality=quality,
        quality_sha256=_H,
        artifact_paths=tuple(
            (name, root / name) for name in sorted(release_module._ARTIFACT_PATHS)
        ),
    )


def _fresh_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: VerifiedTargetArtifact,
) -> AShareSimulationFreshVerificationContext:
    upstream_root = tmp_path / "upstream"
    upstream_root.mkdir()
    upstream = _TARGET._context(upstream_root, monkeypatch)
    kwargs = upstream["target_kwargs"]
    plan_context = BacktestPlanFreshVerificationContext(
        snapshot=kwargs["snapshot"],
        snapshot_spec=kwargs["snapshot_spec"],
        provider=kwargs["provider"],
        provider_spec=kwargs["provider_spec"],
        experiment_spec=kwargs["experiment_spec"],
        fold_spec=kwargs["fold_spec"],
        feature=kwargs["feature"],
        feature_spec=kwargs["feature_spec"],
        label=kwargs["label"],
        label_spec=kwargs["label_spec"],
        alignment=kwargs["alignment"],
        alignment_spec=kwargs["alignment_spec"],
        model=kwargs["model"],
        model_spec=kwargs["model_spec"],
        prediction=kwargs["prediction"],
        prediction_spec=kwargs["prediction_spec"],
        target_spec=kwargs["spec"],
        target_upstream_paths=kwargs["upstream_paths"],
        target_receipt_path=tmp_path / "target-receipt.json",
    )
    facts_context = AShareMarketFactsFreshVerificationContext(
        target=target,
        folds=kwargs["folds"],
        experiment=kwargs["experiment"],
        config=kwargs["config"],
        plan_fresh_context=plan_context,
        plan_receipt_path=tmp_path / "plan-receipt.json",
    )
    return AShareSimulationFreshVerificationContext(
        release=_identity_release(tmp_path),
        facts_fresh_context=facts_context,
    )


def _case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    weights: tuple[tuple[float, float, float], ...] | None = None,
    frame_mutator: Callable[
        [dict[str, pl.DataFrame], tuple[dt.date, ...]], dict[str, pl.DataFrame]
    ] | None = None,
) -> dict[str, Any]:
    facts, sessions = _five_session_facts(tmp_path, monkeypatch, frame_mutator)
    target, plan = _target_plan(tmp_path, sessions, weights)
    return {
        "target": target,
        "plan": plan,
        "facts": facts,
        "cost_periods": (
            AShareCostPeriod(
                effective_from=dt.date(2020, 1, 1),
                effective_to=None,
                commission_rate=Decimal("0.0003"),
                commission_min=Decimal("5"),
                stamp_tax_sell=Decimal("0.001"),
                transfer_fee=Decimal("0.00001"),
                slippage=Decimal("0.001"),
            ),
        ),
        "multiplier": Decimal("1"),
        "initial_cash": Decimal("100000"),
        "fresh_context": _fresh_context(tmp_path, monkeypatch, target),
        "artifact_roots": {"test": tmp_path},
    }


def _mock_fresh_plan(
    monkeypatch: pytest.MonkeyPatch,
    plan: VerifiedBacktestPlanArtifact,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def verified(**kwargs: Any) -> VerifiedBacktestPlanArtifact:
        calls.append(kwargs)
        return plan

    monkeypatch.setattr(simulator_module, "verify_backtest_plan_artifact", verified)
    return calls


@pytest.fixture(scope="module")
def formal_case(tmp_path_factory: pytest.TempPathFactory) -> Any:
    monkeypatch = pytest.MonkeyPatch()
    try:
        yield _case(tmp_path_factory.mktemp("m3-g7e-formal"), monkeypatch)
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="module")
def ex_date_first_buy_case(tmp_path_factory: pytest.TempPathFactory) -> Any:
    monkeypatch = pytest.MonkeyPatch()
    weights = (
        (0.2, 0.2, 0.0),
        (0.2, 0.2, 0.2),
        (0.2, 0.2, 0.2),
        (0.2, 0.2, 0.2),
        (0.2, 0.2, 0.2),
    )
    try:
        yield _case(
            tmp_path_factory.mktemp("m3-g7e-ex-date-first-buy"),
            monkeypatch,
            weights,
        )
    finally:
        monkeypatch.undo()


def test_formal_replay_uses_fresh_plan_exactly_once(
    formal_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = formal_case
    calls = _mock_fresh_plan(monkeypatch, case["plan"])
    result = simulate_formal_a_share_scenario(**case)
    assert len(calls) == 1
    assert calls[0]["target"] is case["target"]
    assert calls[0]["release"] is case["fresh_context"].release
    assert calls[0]["fresh_context"] is (
        case["fresh_context"].facts_fresh_context.plan_fresh_context
    )
    assert result.nav.height == result.daily_diagnostics.height == 5
    assert result.trades.height > 0
    assert result.multiplier == Decimal("1")


def test_ex_date_first_buy_has_no_retroactive_entitlement_and_float_nav_closes(
    ex_date_first_buy_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = ex_date_first_buy_case
    plan = cast(VerifiedBacktestPlanArtifact, case["plan"])
    _mock_fresh_plan(monkeypatch, plan)
    result = simulate_formal_a_share_scenario(**case)
    sessions = plan.manifest.window.execution_dates
    event = case["facts"].corporate_actions.row(0, named=True)
    assert event["record_date"] == sessions[0]
    assert event["ex_date"] == sessions[1]
    ex_date_buy = result.trades.filter(
        (pl.col("date") == sessions[1])
        & (pl.col("symbol") == event["symbol"])
        & (pl.col("side") == "BUY")
    )
    assert ex_date_buy.height == 1
    assert result.entitlements.filter(
        pl.col("event_id") == event["event_id"]
    ).is_empty()
    assert result.corporate_action_postings.filter(
        (pl.col("event_id") == event["event_id"])
        & (pl.col("posting_type") == "CAPTURE")
    ).is_empty()

    first_nav = result.nav.row(0, named=True)
    decimal_cash = Decimal("60129.64")
    decimal_market_value = Decimal("39800.0")
    decimal_equity = decimal_cash + decimal_market_value
    projected_component_sum = (
        first_nav["cash"]
        + first_nav["market_value"]
        + first_nav["cash_receivable"]
        + first_nav["stock_receivable_value"]
    )
    assert first_nav["cash"] == float(decimal_cash)
    assert first_nav["market_value"] == float(decimal_market_value)
    assert first_nav["equity"] == projected_component_sum
    assert first_nav["unit_nav"] == float(
        decimal_equity / Decimal("100000")
    )
    for name in (
        "nav", "trades", "positions", "rejections",
        "corporate_action_postings", "daily_diagnostics", "entitlements",
    ):
        assert type(getattr(result, name)) is pl.DataFrame


def test_nav_float_projection_uses_schema_left_associated_component_sum() -> None:
    cash = Decimal("0.1")
    market_value = Decimal("0.2")
    zero = Decimal("0")
    equity = cash + market_value
    independently_projected_equity = float(equity)
    projected_component_sum = (
        float(cash) + float(market_value) + float(zero) + float(zero)
    )
    assert independently_projected_equity != projected_component_sum

    row = simulator_module._formal_nav_row(
        date=dt.date(2024, 1, 2),
        pre_trade_equity=Decimal("1"),
        cash=cash,
        market_value=market_value,
        cash_receivable=zero,
        stock_receivable_value=zero,
        equity=equity,
        initial_cash=Decimal("1"),
        previous_equity=Decimal("1"),
        cumulative_commission=zero,
        cumulative_stamp=zero,
        cumulative_transfer=zero,
        cumulative_slippage=zero,
    )
    assert row["equity"] == projected_component_sum
    assert row["unit_nav"] == independently_projected_equity


def test_formal_replay_redacts_hostile_and_nonexact_fresh_plan(
    formal_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = formal_case

    def hostile(**_: Any) -> Any:
        raise RuntimeError("C:/PRIVATE/TOKEN_G7E")

    monkeypatch.setattr(simulator_module, "verify_backtest_plan_artifact", hostile)
    with pytest.raises(AShareSimulationError) as caught:
        simulate_formal_a_share_scenario(**case)
    assert str(caught.value) == "M3_A_SHARE_SIMULATION_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "TOKEN_G7E" not in repr(caught.value)

    other = replace(
        case["plan"],
        scheduled_targets=case["plan"].scheduled_targets.with_columns(
            pl.lit(0.1).alias("weight")
        ),
    )
    monkeypatch.setattr(
        simulator_module, "verify_backtest_plan_artifact", lambda **_: other
    )
    with pytest.raises(AShareSimulationError, match="^M3_A_SHARE_SIMULATION_INVALID$"):
        simulate_formal_a_share_scenario(**case)


def test_formal_replay_rejects_stale_outer_and_nonexact_inputs(
    formal_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = formal_case
    canonical = cast(VerifiedBacktestPlanArtifact, case["plan"])
    stale = replace(
        canonical,
        scheduled_targets=canonical.scheduled_targets.with_columns(
            pl.lit(0.1).alias("weight")
        ),
    )
    _mock_fresh_plan(monkeypatch, canonical)
    with pytest.raises(AShareSimulationError, match="^M3_A_SHARE_SIMULATION_INVALID$"):
        simulate_formal_a_share_scenario(**{**case, "plan": stale})

    for name, value in (
        ("multiplier", 1.0),
        ("initial_cash", 100000.0),
        ("facts", object()),
        ("cost_periods", list(case["cost_periods"])),
    ):
        with pytest.raises(
            AShareSimulationError, match="^M3_A_SHARE_SIMULATION_INVALID$"
        ):
            simulate_formal_a_share_scenario(**{**case, name: value})

    accesses: list[str] = []

    class FakeFacts:
        @property
        def identity(self) -> object:
            accesses.append("identity")
            return object()

    with pytest.raises(
        AShareSimulationError, match="^M3_A_SHARE_SIMULATION_INVALID$"
    ):
        simulate_formal_a_share_scenario(
            **{**case, "facts": cast(Any, FakeFacts())}
        )
    assert accesses == []
    assert set(inspect.signature(simulate_formal_a_share_scenario).parameters) == {
        "target", "plan", "facts", "cost_periods", "multiplier",
        "initial_cash", "fresh_context", "artifact_roots",
    }

    with pytest.raises(
        AShareSimulationError, match="^M3_A_SHARE_SIMULATION_INVALID$"
    ):
        AShareSimulationFreshVerificationContext(
            release=cast(Any, object()),
            facts_fresh_context=case["fresh_context"].facts_fresh_context,
        )


def test_formal_replay_account_identities_and_row_order_stability(
    formal_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = formal_case
    plan = cast(VerifiedBacktestPlanArtifact, case["plan"])
    _mock_fresh_plan(monkeypatch, plan)
    baseline = simulate_formal_a_share_scenario(**case)
    for row in baseline.nav.iter_rows(named=True):
        assert row["equity"] == pytest.approx(
            row["cash"] + row["market_value"] + row["cash_receivable"]
            + row["stock_receivable_value"]
        )
    for row in baseline.positions.iter_rows(named=True):
        assert row["quantity"] == (
            row["sellable_quantity"] + row["unsettled_quantity"]
        )
    for row in baseline.trades.iter_rows(named=True):
        assert row["total_fee"] == pytest.approx(
            row["commission"] + row["stamp_tax"] + row["transfer_fee"]
        )
    for row in baseline.daily_diagnostics.iter_rows(named=True):
        assert row["one_way_turnover"] == pytest.approx(
            row["gross_turnover"] / 2
        )

    shuffled = replace(plan, scheduled_targets=plan.scheduled_targets.reverse())
    _mock_fresh_plan(monkeypatch, shuffled)
    replayed = simulate_formal_a_share_scenario(
        **{**case, "plan": shuffled}
    )
    for name in (
        "nav", "trades", "positions", "rejections",
        "corporate_action_postings", "daily_diagnostics", "entitlements",
    ):
        assert getattr(replayed, name).equals(getattr(baseline, name))


def test_formal_replay_isolates_hostile_decimal_context(
    formal_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = formal_case
    _mock_fresh_plan(monkeypatch, case["plan"])
    baseline = simulate_formal_a_share_scenario(**case)
    hostile = Context(prec=4)
    hostile.traps[Inexact] = True
    with localcontext(hostile) as active:
        before = (
            active.prec,
            active.rounding,
            dict(active.traps),
            dict(active.flags),
        )
        replayed = simulate_formal_a_share_scenario(**case)
        after = (
            active.prec,
            active.rounding,
            dict(active.traps),
            dict(active.flags),
        )
    assert after == before
    for name in (
        "nav", "trades", "positions", "rejections",
        "corporate_action_postings", "daily_diagnostics", "entitlements",
    ):
        assert getattr(replayed, name).equals(getattr(baseline, name))
