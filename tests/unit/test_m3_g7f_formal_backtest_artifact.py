"""Focused formal G7F three-scenario A-share artifact tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_reporting as reporting_module
import quant.backtest.a_share_simulator as simulator_module
import quant.data.m3_release as release_module
from quant.backtest.a_share_reporting import (
    AShareBacktestArtifactError,
    BacktestArtifactFreshVerificationContext,
    BacktestArtifactUpstreamPaths,
    FormalBacktestArtifactUpstreamPaths,
    build_backtest_artifact,
    verify_backtest_artifact,
    verify_backtest_build_output,
)
from quant.data.m3_release import G1Release, VerifiedG1Release
from quant.research.m3.contracts import VerifiedBacktestArtifact
from quant.research.m3.run_state import (
    publish_stage_receipt,
    select_artifact_root,
    verify_stage_receipt,
)

_G7E_SPEC = importlib.util.spec_from_file_location(
    "m3_formal_g7e_support_for_g7f",
    Path(__file__).with_name("test_m3_g7e_formal_a_share_simulator.py"),
)
assert _G7E_SPEC is not None and _G7E_SPEC.loader is not None
_G7E_SUPPORT = importlib.util.module_from_spec(_G7E_SPEC)
_G7E_SPEC.loader.exec_module(_G7E_SUPPORT)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aliased(
    paths: tuple[Path, ...], roots: dict[str, Path]
) -> list[tuple[str, Path]]:
    return [
        (select_artifact_root(path, artifact_roots=roots)[0], path)
        for path in paths
    ]


def _formal_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    g7e = _G7E_SUPPORT._case(tmp_path, monkeypatch)
    target = g7e["target"]
    plan = g7e["plan"]
    facts = g7e["facts"]
    simulation_context = g7e["fresh_context"]
    release = simulation_context.release
    facts_context = simulation_context.facts_fresh_context
    config = replace(
        facts_context.config,
        scientific_config_sha256=target.manifest.scientific_config_sha256,
    )
    experiment = replace(
        facts_context.experiment,
        manifest=replace(
            facts_context.experiment.manifest,
            experiment_key=target.manifest.experiment_key,
            scientific_config_sha256=config.scientific_config_sha256,
        ),
        manifest_sha256=target.manifest.experiment_manifest_sha256,
    )
    facts_context = replace(
        facts_context,
        experiment=experiment,
        config=config,
    )
    roots = cast(dict[str, Path], g7e["artifact_roots"])
    upstream_paths = FormalBacktestArtifactUpstreamPaths(
        target_receipt_path=facts_context.plan_fresh_context.target_receipt_path,
        plan_receipt_path=facts_context.plan_receipt_path,
        experiment_receipt_path=(
            facts_context.plan_fresh_context
            .target_upstream_paths.experiment_receipt_path
        ),
    )
    g1_root = release.release.root
    assert release.release.quality_path == g1_root / "quality.json"
    assert not (g1_root / "receipt.json").exists()
    market_files = (
        "bar_1d.parquet",
        "benchmark_bar_1d.parquet",
        "corporate_action_ledger.parquet",
        "corporate_action_reconciliation.parquet",
        "instrument.parquet",
        "price_limit_1d.parquet",
        "suspension_1d.parquet",
        "trade_calendar.parquet",
    )
    source = dict(release.artifact_paths)
    provisional_inputs = (
        target.root / "target_manifest.json",
        upstream_paths.target_receipt_path,
        target.root / "target_weights.parquet",
        target.root / "target_daily.parquet",
        plan.root / "manifest.json",
        upstream_paths.plan_receipt_path,
        plan.root / "scheduled_targets.parquet",
        plan.root / "schedule_diagnostics.parquet",
        plan.root / "cost_schedule.json",
        experiment.root / "experiment_manifest.json",
        upstream_paths.experiment_receipt_path,
        release.release.manifest_path,
        release.release.quality_path,
        *(source[name] for name in market_files),
    )
    assert provisional_inputs[11].name == "manifest.json"
    assert provisional_inputs[12].name == "quality.json"
    for index, path in enumerate(provisional_inputs):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(f"g7f-input-{index}".encode())
    assert not (g1_root / "receipt.json").exists()
    object.__setattr__(release, "quality_sha256", _sha(release.release.quality_path))
    fresh_context = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=facts_context,
        upstream_paths=upstream_paths,
        release=release,
    )
    input_paths = reporting_module._formal_receipt_inputs(
        target, plan, release, experiment, upstream_paths
    )
    assert input_paths[11] == release.release.manifest_path
    assert input_paths[12] == release.release.quality_path
    assert all(path.name != "receipt.json" for path in input_paths)
    calls: list[tuple[str, object]] = []

    def fresh_plan(**kwargs: Any) -> Any:
        calls.append(("g7f-plan", kwargs))
        return plan

    def fresh_facts(**kwargs: Any) -> Any:
        calls.append(("g7f-facts", kwargs))
        return facts

    def g7e_plan(**kwargs: Any) -> Any:
        calls.append(("g7e-plan", kwargs))
        return plan

    monkeypatch.setattr(
        reporting_module, "verify_backtest_plan_artifact", fresh_plan
    )
    monkeypatch.setattr(
        reporting_module, "load_verified_a_share_market_facts", fresh_facts
    )
    monkeypatch.setattr(simulator_module, "verify_backtest_plan_artifact", g7e_plan)
    root = tmp_path / "formal-backtest"
    root.mkdir()
    kwargs = {
        "target": target,
        "plan": plan,
        "release": release,
        "experiment": experiment,
        "config": config,
        "fresh_context": fresh_context,
        "artifact_roots": roots,
    }
    return {
        "context": {"common": tmp_path},
        "kwargs": kwargs,
        "root": root,
        "roots": roots,
        "upstream_paths": upstream_paths,
        "calls": calls,
        "g7e": g7e,
    }


def _publish_receipt(case: dict[str, Any], suffix: str = "base") -> Path:
    kwargs = case["kwargs"]
    root = case["root"]
    roots = case["roots"]
    receipt = (
        cast(Path, case["context"]["common"])
        / "receipts" / "backtest" / f"{suffix}.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    inputs = reporting_module._formal_receipt_inputs(
        kwargs["target"], kwargs["plan"], kwargs["release"],
        kwargs["experiment"], case["upstream_paths"],
    )
    outputs = reporting_module._formal_output_paths(root)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="backtest",
        scope="WORK",
        scope_key=kwargs["target"].manifest.work_key,
        artifact_roots=roots,
        inputs=_aliased(inputs, roots),
        outputs=_aliased(outputs, roots),
    )
    return receipt


def _assert_public_invalid(callback: Any, message: str) -> None:
    with pytest.raises(AShareBacktestArtifactError) as caught:
        callback()
    assert str(caught.value) == message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_formal_build_verify_actual_chain_exact_three_and_21_29(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _formal_case(tmp_path, monkeypatch)
    simulation_calls: list[Decimal] = []
    real_simulation = reporting_module.simulate_formal_a_share_scenario

    def counted_simulation(**kwargs: Any) -> Any:
        simulation_calls.append(kwargs["multiplier"])
        return real_simulation(**kwargs)

    monkeypatch.setattr(
        reporting_module, "simulate_formal_a_share_scenario", counted_simulation
    )
    inputs = reporting_module.backtest_artifact_input_paths(
        target=case["kwargs"]["target"],
        plan=case["kwargs"]["plan"],
        release=case["kwargs"]["release"],
        experiment=case["kwargs"]["experiment"],
        fresh_context=case["kwargs"]["fresh_context"],
    )
    assert len(inputs) == 21
    assert inputs[11].name == "manifest.json"
    assert inputs[12].name == "quality.json"
    assert inputs[12] == case["kwargs"]["release"].release.quality_path
    assert all(path.name != "receipt.json" for path in inputs)
    assert not (
        case["kwargs"]["release"].release.root / "receipt.json"
    ).exists()
    manifest = build_backtest_artifact(
        **case["kwargs"], output_root=case["root"]
    )
    assert [name for name, _ in case["calls"]] == [
        "g7f-plan", "g7f-facts", "g7e-plan", "g7e-plan", "g7e-plan"
    ]
    assert simulation_calls == [
        Decimal("0.5"), Decimal("1"), Decimal("2")
    ]
    expected = reporting_module._FORMAL_EXPECTED_NAMES
    actual = {
        path.relative_to(case["root"]).as_posix()
        for path in case["root"].rglob("*")
        if path.is_file()
    }
    assert actual == expected
    assert len(actual) == 29
    assert tuple(name for name, _ in manifest.scenario_manifest_sha256s) == (
        "0p5x", "1p0x", "2p0x"
    )
    receipt = _publish_receipt(case)
    parsed = verify_stage_receipt(
        receipt_path=receipt, artifact_roots=case["roots"]
    )
    assert parsed is not None
    assert len(parsed.inputs) == 21
    assert len(parsed.outputs) == 29
    assert sum(
        1 for item in parsed.inputs if item.relative_path.endswith("quality.json")
    ) == 1
    verified = verify_backtest_artifact(
        root=case["root"], receipt_path=receipt, **case["kwargs"]
    )
    assert type(verified) is VerifiedBacktestArtifact
    assert verified.manifest == manifest
    assert [name for name, _ in case["calls"]] == [
        "g7f-plan", "g7f-facts", "g7e-plan", "g7e-plan", "g7e-plan",
        "g7f-plan", "g7f-facts", "g7e-plan", "g7e-plan", "g7e-plan",
    ]
    assert simulation_calls == [
        Decimal("0.5"), Decimal("1"), Decimal("2"),
        Decimal("0.5"), Decimal("1"), Decimal("2"),
    ]


def test_formal_surface_has_no_caller_result_or_execution_state() -> None:
    for function in (build_backtest_artifact, verify_backtest_artifact):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {
            "result", "results", "fills", "transition", "schedule",
            "market_facts", "frames", "multiplier", "metrics",
        }


def test_fresh_context_is_exact_nonserializable() -> None:
    fields = BacktestArtifactFreshVerificationContext.__dataclass_fields__
    assert {name for name, item in fields.items() if item.init} == {
        "facts_fresh_context", "upstream_paths", "release",
    }
    assert "_source_snapshot" in fields
    assert fields["_source_snapshot"].init is False
    assert fields["_source_snapshot"].repr is False
    assert fields["_source_snapshot"].compare is False
    assert set(FormalBacktestArtifactUpstreamPaths.__dataclass_fields__) == {
        "target_receipt_path", "plan_receipt_path", "experiment_receipt_path",
    }
    assert "g1_receipt_path" not in FormalBacktestArtifactUpstreamPaths.__dataclass_fields__
    _assert_public_invalid(
        lambda: BacktestArtifactFreshVerificationContext(
            facts_fresh_context=cast(Any, object()),
            upstream_paths=cast(Any, object()),
            release=cast(Any, object()),
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )


def test_fresh_boundaries_reject_hostile_nonexact_and_stale_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _formal_case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]

    def rejected(root: Path) -> None:
        _assert_public_invalid(
            lambda: build_backtest_artifact(**kwargs, output_root=root),
            "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
        )
        assert root.is_dir() and not tuple(root.iterdir())

    hostile_root = tmp_path / "hostile-plan"
    hostile_root.mkdir()

    def hostile_plan(**_: Any) -> Any:
        raise RuntimeError("TOKEN=private SQL=/secret pid=123")

    monkeypatch.setattr(
        reporting_module, "verify_backtest_plan_artifact", hostile_plan
    )
    rejected(hostile_root)

    nonexact_root = tmp_path / "nonexact-plan"
    nonexact_root.mkdir()
    monkeypatch.setattr(
        reporting_module,
        "verify_backtest_plan_artifact",
        lambda **_: object(),
    )
    rejected(nonexact_root)

    hostile_facts_root = tmp_path / "hostile-facts"
    hostile_facts_root.mkdir()
    monkeypatch.setattr(
        reporting_module,
        "verify_backtest_plan_artifact",
        lambda **_: kwargs["plan"],
    )

    def hostile_facts(**_: Any) -> Any:
        raise RuntimeError("TOKEN=private SQL=/secret pid=456")

    monkeypatch.setattr(
        reporting_module, "load_verified_a_share_market_facts", hostile_facts
    )
    rejected(hostile_facts_root)

    nonexact_facts_root = tmp_path / "nonexact-facts"
    nonexact_facts_root.mkdir()
    monkeypatch.setattr(
        reporting_module,
        "load_verified_a_share_market_facts",
        lambda **_: object(),
    )
    rejected(nonexact_facts_root)

    stale_root = tmp_path / "stale-outer"
    stale_root.mkdir()
    stale = replace(
        kwargs["plan"],
        manifest=replace(
            kwargs["plan"].manifest,
            target_manifest_sha256="f" * 64,
        ),
    )
    _assert_public_invalid(
        lambda: build_backtest_artifact(
            **{**kwargs, "plan": stale}, output_root=stale_root
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    assert stale_root.is_dir() and not tuple(stale_root.iterdir())


def test_p0_no_clobber_rejects_nonempty_root_before_fresh_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _formal_case(tmp_path, monkeypatch)
    root = case["root"]
    (root / "foreign.txt").write_text("owned elsewhere", encoding="utf-8")
    _assert_public_invalid(
        lambda: build_backtest_artifact(**case["kwargs"], output_root=root),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    assert (root / "foreign.txt").read_text(encoding="utf-8") == "owned elsewhere"
    assert case["calls"] == []


def test_scaled_cost_schedule_changes_only_negotiable_friction() -> None:
    base = reporting_module.AShareCostPeriod(
        effective_from=reporting_module.dt.date(2020, 1, 1),
        effective_to=None,
        commission_rate=Decimal("0.0003"),
        commission_min=Decimal("5"),
        stamp_tax_sell=Decimal("0.001"),
        transfer_fee=Decimal("0.00001"),
        slippage=Decimal("0.001"),
    )
    half, one, double = (
        reporting_module._scaled_periods((base,), multiplier)[0]
        for multiplier in (Decimal("0.5"), Decimal("1"), Decimal("2"))
    )
    assert (half.commission_rate, one.commission_rate, double.commission_rate) == (
        Decimal("0.00015"), Decimal("0.0003"), Decimal("0.0006")
    )
    assert (half.commission_min, one.commission_min, double.commission_min) == (
        Decimal("2.5"), Decimal("5"), Decimal("10")
    )
    assert (half.slippage, one.slippage, double.slippage) == (
        Decimal("0.0005"), Decimal("0.001"), Decimal("0.002")
    )
    assert {item.stamp_tax_sell for item in (half, one, double)} == {
        base.stamp_tax_sell
    }
    assert {item.transfer_fee for item in (half, one, double)} == {
        base.transfer_fee
    }


def test_whole_bundle_metrics_or_receipt_drift_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _formal_case(tmp_path, monkeypatch)
    build_backtest_artifact(**case["kwargs"], output_root=case["root"])
    receipt = _publish_receipt(case)
    metrics_path = case["root"] / "1p0x" / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["rejection_count"] += 1
    metrics_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _assert_public_invalid(
        lambda: verify_backtest_artifact(
            root=case["root"], receipt_path=receipt, **case["kwargs"]
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )


def test_formal_metrics_count_residual_intents_not_reason_rows() -> None:
    rejections = pl.DataFrame(
        [
            {
                "date": "2024-01-02", "symbol": "600000.SH", "side": "SELL",
                "reason": "T_PLUS_ONE", "requested_quantity": 200,
                "filled_quantity": 0, "rejected_quantity": 100,
                "rejected_notional": 1000.0,
            },
            {
                "date": "2024-01-02", "symbol": "600000.SH", "side": "SELL",
                "reason": "LOT_SIZE", "requested_quantity": 200,
                "filled_quantity": 0, "rejected_quantity": 100,
                "rejected_notional": 1000.0,
            },
        ]
    ).with_columns(pl.col("date").str.to_date())
    keys = {
        (row["date"], row["symbol"], row["side"])
        for row in rejections.iter_rows(named=True)
        if (
            row["rejected_quantity"] > 0
            or Decimal(str(row["rejected_notional"])) > 0
        )
    }
    assert rejections.height == 2
    assert len(keys) == 1


def test_terminal_exit_uses_sell_floor_tick_and_execution_notional() -> None:
    positions = pl.DataFrame(
        [{
            "quantity": 101,
            "mark_price": 10.01,
        }]
    )
    period = reporting_module.AShareCostPeriod(
        effective_from=reporting_module.dt.date(2020, 1, 1),
        effective_to=None,
        commission_rate=Decimal("0.00025"),
        commission_min=Decimal("5"),
        stamp_tax_sell=Decimal("0.0005"),
        transfer_fee=Decimal("0.00001"),
        slippage=Decimal("0.001"),
    )
    actual = reporting_module._formal_terminal_exit_cost(positions, period)
    execution_notional = Decimal("9.99") * 101
    expected = Decimal("5") + Decimal("0.50") + Decimal("0.01") + Decimal("2.02")
    assert execution_notional == Decimal("1008.99")
    assert actual == expected
    assert actual != (
        Decimal("10.01") * 101 * period.slippage
        + Decimal("5") + Decimal("0.51") + Decimal("0.01")
    )


def test_r3_formal_g1_quality_closure_rejects_drift_alias_and_legacy_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _formal_case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    release = kwargs["release"]
    quality = release.release.quality_path
    quality_backup = quality.read_bytes()
    original_root = release.release.root
    original_manifest = release.release.manifest_path
    original_quality = release.release.quality_path
    original_artifacts = release.artifact_paths
    original_quality_sha = release.quality_sha256
    assert quality.is_file() and not (release.release.root / "receipt.json").exists()

    def _restore_release() -> None:
        object.__setattr__(
            release,
            "release",
            G1Release(
                release_id=original_root.name,
                root=original_root,
                manifest_path=original_manifest,
                quality_path=original_quality,
            ),
        )
        object.__setattr__(release, "artifact_paths", original_artifacts)
        if not original_quality.exists():
            original_quality.write_bytes(quality_backup)
        elif original_quality.read_bytes() != quality_backup:
            original_quality.write_bytes(quality_backup)
        object.__setattr__(release, "quality_sha256", _sha(original_quality))
        kwargs["fresh_context"] = BacktestArtifactFreshVerificationContext(
            facts_fresh_context=kwargs["fresh_context"].facts_fresh_context,
            upstream_paths=case["upstream_paths"],
            release=release,
        )

    decoy = release.release.root / "receipt.json"
    decoy.write_bytes(b'{"stage":"backtest"}')
    inputs = reporting_module._formal_receipt_inputs(
        kwargs["target"], kwargs["plan"], release,
        kwargs["experiment"], case["upstream_paths"],
    )
    assert inputs[12] == quality and decoy not in inputs
    assert inputs[12].name == "quality.json"
    decoy.unlink()

    missing_root = tmp_path / "quality-missing"
    missing_root.mkdir()
    quality.unlink()
    _assert_public_invalid(
        lambda: build_backtest_artifact(**kwargs, output_root=missing_root),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    assert not tuple(missing_root.iterdir())
    _restore_release()

    build_backtest_artifact(**kwargs, output_root=case["root"])
    receipt = _publish_receipt(case, suffix="quality-ok")
    quality.write_bytes(b'{"schema_version":"hostile-quality","passed":false}\n')
    _assert_public_invalid(
        lambda: verify_backtest_artifact(
            root=case["root"], receipt_path=receipt, **kwargs
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    _restore_release()

    target_receipt = case["upstream_paths"].target_receipt_path
    target_backup = target_receipt.read_bytes()
    target_receipt.unlink()
    try:
        os.link(quality, target_receipt)
    except OSError:
        target_receipt.write_bytes(target_backup)
        pytest.skip("hardlink unavailable for quality receipt alias probe")
    with pytest.raises(Exception):
        reporting_module._formal_receipt_inputs(
            kwargs["target"], kwargs["plan"], release,
            kwargs["experiment"], case["upstream_paths"],
        )
    target_receipt.unlink()
    target_receipt.write_bytes(target_backup)

    market = dict(release.artifact_paths)["bar_1d.parquet"]
    market_backup = market.read_bytes()
    market.unlink()
    try:
        os.link(quality, market)
    except OSError:
        market.write_bytes(market_backup)
        pytest.skip("hardlink unavailable for quality market alias probe")
    with pytest.raises(Exception):
        reporting_module._formal_receipt_inputs(
            kwargs["target"], kwargs["plan"], release,
            kwargs["experiment"], case["upstream_paths"],
        )
    market.unlink()
    market.write_bytes(market_backup)
    kwargs["fresh_context"] = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=kwargs["fresh_context"].facts_fresh_context,
        upstream_paths=case["upstream_paths"],
        release=release,
    )

    object.__setattr__(
        release,
        "release",
        SimpleNamespace(
            root=release.release.root,
            manifest_path=release.release.manifest_path,
            quality_path=release.release.root / "receipt.json",
        ),
    )
    pseudo_root = tmp_path / "pseudo-receipt-quality"
    pseudo_root.mkdir()
    (release.release.root / "receipt.json").write_bytes(quality_backup)
    object.__setattr__(
        release, "quality_sha256", _sha(release.release.root / "receipt.json")
    )
    _assert_public_invalid(
        lambda: build_backtest_artifact(**kwargs, output_root=pseudo_root),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    assert not tuple(pseudo_root.iterdir())
    (release.release.root / "receipt.json").unlink(missing_ok=True)
    _restore_release()

    outside = tmp_path / "outside-quality.json"
    outside.write_bytes(quality_backup)
    object.__setattr__(
        release,
        "release",
        SimpleNamespace(
            root=release.release.root,
            manifest_path=release.release.manifest_path,
            quality_path=outside,
        ),
    )
    object.__setattr__(release, "quality_sha256", _sha(outside))
    outside_root = tmp_path / "outside-quality-root"
    outside_root.mkdir()
    _assert_public_invalid(
        lambda: build_backtest_artifact(**kwargs, output_root=outside_root),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    assert not tuple(outside_root.iterdir())
    _restore_release()

    development_paths = BacktestArtifactUpstreamPaths(
        target_receipt_path=case["upstream_paths"].target_receipt_path,
        plan_receipt_path=case["upstream_paths"].plan_receipt_path,
        experiment_receipt_path=case["upstream_paths"].experiment_receipt_path,
        g1_receipt_path=release.release.root / "receipt.json",
    )
    _assert_public_invalid(
        lambda: BacktestArtifactFreshVerificationContext(
            facts_fresh_context=kwargs["fresh_context"].facts_fresh_context,
            upstream_paths=cast(Any, development_paths),
            release=release,
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    with pytest.raises(Exception):
        reporting_module._formal_receipt_inputs(
            kwargs["target"], kwargs["plan"], release,
            kwargs["experiment"], cast(Any, development_paths),
        )
    with pytest.raises(Exception):
        reporting_module._formal_receipt_inputs(
            kwargs["target"], kwargs["plan"], release,
            kwargs["experiment"], cast(Any, {"target_receipt_path": quality}),
        )

    replaced = tmp_path / "replaced-g1"
    shutil.copytree(original_root, replaced)
    object.__setattr__(
        release,
        "release",
        SimpleNamespace(
            root=replaced,
            manifest_path=replaced / "manifest.json",
            quality_path=replaced / "quality.json",
        ),
    )
    remapped = tuple((name, replaced / name) for name, _ in original_artifacts)
    object.__setattr__(release, "artifact_paths", remapped)
    object.__setattr__(release, "quality_sha256", original_quality_sha)
    _assert_public_invalid(
        lambda: verify_backtest_artifact(
            root=case["root"], receipt_path=receipt, **kwargs
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    legacy_root = tmp_path / "legacy-pseudo-receipt-resign"
    legacy_root.mkdir()
    fake_receipt = original_root / "receipt.json"
    fake_receipt.write_bytes(b'{"stage":"backtest","pseudo":true}')
    _restore_release()
    current = list(
        reporting_module._formal_receipt_inputs(
            kwargs["target"], kwargs["plan"], release,
            kwargs["experiment"], case["upstream_paths"],
        )
    )
    legacy_inputs = [*current[:12], fake_receipt, *current[13:]]
    assert legacy_inputs[12].name == "receipt.json"
    assert len(legacy_inputs) == 21
    legacy_receipt = (
        cast(Path, case["context"]["common"])
        / "receipts" / "backtest" / "legacy-pseudo.json"
    )
    publish_stage_receipt(
        receipt_path=legacy_receipt,
        stage="backtest",
        scope="WORK",
        scope_key=kwargs["target"].manifest.work_key,
        artifact_roots=case["roots"],
        inputs=_aliased(tuple(legacy_inputs), case["roots"]),
        outputs=_aliased(
            reporting_module._formal_output_paths(case["root"]), case["roots"]
        ),
    )
    _assert_public_invalid(
        lambda: verify_backtest_artifact(
            root=case["root"], receipt_path=legacy_receipt, **kwargs
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    fake_receipt.unlink(missing_ok=True)
    assert legacy_root.is_dir()


def test_r4_prefinal_release_context_entity_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _formal_case(tmp_path, monkeypatch)
    kwargs = case["kwargs"]
    release = kwargs["release"]
    assert type(release) is VerifiedG1Release
    assert type(release.release) is G1Release
    original = release.release
    original_root = original.root
    quality_sha = release.quality_sha256
    rid = original.release_id

    build_backtest_artifact(**kwargs, output_root=case["root"])
    verify_backtest_build_output(root=case["root"], **kwargs)
    receipt = _publish_receipt(case, suffix="r4-legit")
    verified = verify_backtest_artifact(
        root=case["root"], receipt_path=receipt, **kwargs
    )
    assert type(verified) is VerifiedBacktestArtifact

    forged_ns = SimpleNamespace(
        root=original_root,
        manifest_path=original.manifest_path,
        quality_path=original.quality_path,
    )
    object.__setattr__(release, "release", forged_ns)
    assert type(release.release) is not G1Release
    _assert_public_invalid(
        lambda: verify_backtest_build_output(root=case["root"], **kwargs),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    object.__setattr__(release, "release", original)

    copied_root = tmp_path / "copied" / rid
    copied_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(original_root, copied_root)
    assert _sha(copied_root / "quality.json") == quality_sha
    exact_inner = G1Release(
        release_id=rid,
        root=copied_root,
        manifest_path=copied_root / "manifest.json",
        quality_path=copied_root / "quality.json",
    )
    remapped = tuple(
        (name, copied_root / name)
        for name in sorted(release_module._ARTIFACT_PATHS)
    )
    exact_verified = replace(
        release,
        release=exact_inner,
        artifact_paths=remapped,
        quality_sha256=quality_sha,
    )
    assert type(exact_verified) is VerifiedG1Release
    assert type(exact_verified.release) is G1Release
    _assert_public_invalid(
        lambda: verify_backtest_build_output(
            root=case["root"], **{**kwargs, "release": exact_verified}
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )

    quality = original.quality_path
    before_entity = reporting_module._formal_entity(quality, directory=False)
    payload = quality.read_bytes()
    quality.unlink()
    quality.write_bytes(payload)
    after_entity = reporting_module._formal_entity(quality, directory=False)
    if (before_entity.device, before_entity.inode) == (
        after_entity.device,
        after_entity.inode,
    ):
        pytest.skip("same-path rewrite reused inode")
    assert _sha(quality) == quality_sha
    _assert_public_invalid(
        lambda: verify_backtest_build_output(root=case["root"], **kwargs),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    kwargs["fresh_context"] = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=kwargs["fresh_context"].facts_fresh_context,
        upstream_paths=case["upstream_paths"],
        release=release,
    )
    verify_backtest_build_output(root=case["root"], **kwargs)

    drifted_release = replace(
        release,
        release=exact_inner,
        artifact_paths=remapped,
        quality_sha256=quality_sha,
    )
    object.__setattr__(kwargs["fresh_context"], "release", drifted_release)
    _assert_public_invalid(
        lambda: verify_backtest_build_output(root=case["root"], **{
            **kwargs, "release": drifted_release
        }),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    # replace() rebuilds a *new* context via __post_init__ (new request); the
    # original context object must still reject a drifted caller release.
    replaced_ctx = replace(kwargs["fresh_context"], release=release)
    assert replaced_ctx is not kwargs["fresh_context"]
    _assert_public_invalid(
        lambda: verify_backtest_build_output(
            root=case["root"],
            **{**kwargs, "release": drifted_release},
        ),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    kwargs["fresh_context"] = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=kwargs["fresh_context"].facts_fresh_context,
        upstream_paths=case["upstream_paths"],
        release=release,
    )

    object.__setattr__(
        kwargs["fresh_context"],
        "_source_snapshot",
        cast(Any, None),
    )
    _assert_public_invalid(
        lambda: verify_backtest_build_output(root=case["root"], **kwargs),
        "M3_A_SHARE_BACKTEST_ARTIFACT_INVALID",
    )
    kwargs["fresh_context"] = BacktestArtifactFreshVerificationContext(
        facts_fresh_context=kwargs["fresh_context"].facts_fresh_context,
        upstream_paths=case["upstream_paths"],
        release=release,
    )
    verify_backtest_build_output(root=case["root"], **kwargs)
    assert case["root"].is_dir()