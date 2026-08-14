"""G7B development A-share backtest-plan artifact adversarial tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import importlib.util
import inspect
import json
import shutil
import sys
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from quant.backtest.a_share_plan import (
    AShareCostPeriod,
    BacktestPlanManifestV1,
    BacktestPlanUpstreamPaths,
    build_development_example_backtest_plan_artifact,
    read_backtest_plan_manifest,
    verify_development_example_backtest_plan_artifact,
)
from quant.domain import TargetWeightSchema
from quant.research.m3.development_example import (
    DevelopmentExampleReleaseHandle,
    VerifiedDevelopmentExampleBacktestPlanArtifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_TARGET_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_target_test_support_for_plan",
    Path(__file__).with_name("test_m3_target_artifact.py"),
)
assert _TARGET_SUPPORT_SPEC is not None and _TARGET_SUPPORT_SPEC.loader is not None
_TARGET_SUPPORT = importlib.util.module_from_spec(_TARGET_SUPPORT_SPEC)
_TARGET_SUPPORT_SPEC.loader.exec_module(_TARGET_SUPPORT)


def _plan_inputs(target_bundle: tuple[Any, ...], target: Any) -> list[tuple[str, Path]]:
    parts = _TARGET_SUPPORT._parts(target_bundle[0])
    release = parts["release"]
    folds = parts["folds"]
    experiment = parts["experiment"]
    return [
        ("root", target.root / "target_manifest.json"),
        ("root", cast(Path, target_bundle[5])),
        ("root", target.root / "target_weights.parquet"),
        ("root", target.root / "target_daily.parquet"),
        ("root", release.release.manifest_path),
        ("root", release.release.root / "receipt.json"),
        ("root", dict(release.artifact_paths)["trade_calendar.parquet"]),
        ("root", folds.root / "folds.json"),
        ("root", _TARGET_SUPPORT._fold_receipt(parts)),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", _TARGET_SUPPORT._experiment_receipt(parts)),
    ]


def _plan_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / "cost_schedule.json"),
        ("root", root / "manifest.json"),
        ("root", root / "schedule_diagnostics.parquet"),
        ("root", root / "scheduled_targets.parquet"),
    ]


def _build_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    target_bundle = _TARGET_SUPPORT._build_bundle(tmp_path, monkeypatch)
    target = _TARGET_SUPPORT._verify(target_bundle)
    parts = _TARGET_SUPPORT._parts(target_bundle[0])
    root = cast(Path, parts["common"]) / f"development-example-plan-{target.manifest.work_key}"
    root.mkdir()
    manifest = build_development_example_backtest_plan_artifact(
        target=target,
        release=parts["release"],
        folds=parts["folds"],
        experiment=parts["experiment"],
        config=parts["config"],
        output_root=root,
    )
    receipt = (
        cast(Path, parts["common"])
        / "receipts"
        / "development-backtest-plan"
        / f"{target.manifest.work_key}.json"
    )
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-backtest-plan",
        scope="WORK",
        scope_key=target.manifest.work_key,
        artifact_roots=parts["roots"],
        inputs=_plan_inputs(target_bundle, target),
        outputs=_plan_outputs(root),
    )
    upstream_paths = BacktestPlanUpstreamPaths(
        target_receipt_path=cast(Path, target_bundle[5]),
        fold_receipt_path=_TARGET_SUPPORT._fold_receipt(parts),
        experiment_receipt_path=_TARGET_SUPPORT._experiment_receipt(parts),
    )
    return target_bundle, target, upstream_paths, root, receipt, manifest


def _verify(
    bundle: tuple[Any, ...],
    *,
    target: Any = None,
    release: Any = None,
    receipt: Path | None = None,
) -> VerifiedDevelopmentExampleBacktestPlanArtifact:
    target_bundle, default_target, upstream_paths, root, default_receipt, _ = bundle
    parts = _TARGET_SUPPORT._parts(target_bundle[0])
    kwargs = {
        "root": root,
        "receipt_path": receipt or default_receipt,
        "target": target or default_target,
        "release": release or parts["release"],
        "folds": parts["folds"],
        "experiment": parts["experiment"],
        "config": parts["config"],
        "upstream_paths": upstream_paths,
        "artifact_roots": parts["roots"],
    }
    parameters = inspect.signature(
        verify_development_example_backtest_plan_artifact
    ).parameters
    return verify_development_example_backtest_plan_artifact(
        **{name: value for name, value in kwargs.items() if name in parameters}
    )


def _canonical(value: object) -> bytes:
    def normalize(item: object) -> object:
        if type(item) is dt.date:
            return item.isoformat()
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sh_open_sessions(release: Any) -> tuple[dt.date, ...]:
    calendar = pl.read_parquet(dict(release.artifact_paths)["trade_calendar.parquet"])
    return tuple(
        calendar.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .sort("date")
        .get_column("date")
        .to_list()
    )


def _next_session(day: dt.date, sessions: tuple[dt.date, ...]) -> dt.date:
    return next(session for session in sessions if session > day)


def _copy_release_with_calendar(
    release: Any,
    root: Path,
    calendar: pl.DataFrame,
) -> Any:
    shutil.copytree(release.release.root, root)
    calendar.write_parquet(root / "contract" / "trade_calendar.parquet")
    return replace(
        release,
        release=DevelopmentExampleReleaseHandle(
            root=root,
            manifest_path=root / "manifest.json",
        ),
        artifact_paths=tuple(
            (name, root / "contract" / name) for name, _ in release.artifact_paths
        ),
    )


def test_plan_maps_each_complete_signal_batch_to_strict_next_sh_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    target_bundle, target, _, root, receipt, manifest = bundle
    parts = _TARGET_SUPPORT._parts(target_bundle[0])
    sessions = _sh_open_sessions(parts["release"])
    signal_dates = tuple(target.target_daily.sort("as_of").get_column("as_of"))
    execution_dates = tuple(_next_session(day, sessions) for day in signal_dates)
    scheduled = verified.scheduled_targets
    diagnostics = pl.read_parquet(root / "schedule_diagnostics.parquet")

    assert isinstance(verified, VerifiedDevelopmentExampleBacktestPlanArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.example_id == target.example_id
    assert manifest.window.signal_dates == signal_dates
    assert manifest.window.execution_dates == execution_dates
    assert manifest.window.first_execution_date == execution_dates[0]
    assert manifest.window.terminal_valuation_date == execution_dates[-1]
    assert manifest.window.force_liquidation is False
    mapping = dict(zip(signal_dates, execution_dates, strict=True))
    assert all(
        row["execution_date"] == mapping[row["as_of"]]
        and row["execution_date"] > row["as_of"]
        for row in scheduled.iter_rows(named=True)
    )
    assert scheduled.columns == [
        "as_of", "strategy", "strategy_version", "symbol", "weight",
        "execution_date",
    ]
    assert scheduled.equals(scheduled.sort("execution_date", "as_of", "symbol"))
    assert TargetWeightSchema.validate(scheduled.drop("execution_date")).height == scheduled.height
    assert diagnostics.columns == [
        "as_of", "execution_date", "n_targets", "total_target_weight", "session_lag",
    ]
    assert diagnostics.get_column("as_of").is_sorted()
    assert diagnostics.get_column("session_lag").to_list() == [1] * len(signal_dates)
    for row in diagnostics.iter_rows(named=True):
        day = target.targets.filter(pl.col("as_of") == row["as_of"])
        assert row["execution_date"] == mapping[row["as_of"]]
        assert row["n_targets"] == day.height
        assert row["total_target_weight"] == day.get_column("weight").sum()
    assert manifest.scheduled_targets_sha256 == hashlib.sha256(
        (root / "scheduled_targets.parquet").read_bytes()
    ).hexdigest()
    assert manifest.schedule_diagnostics_sha256 == hashlib.sha256(
        (root / "schedule_diagnostics.parquet").read_bytes()
    ).hexdigest()
    assert verified.plan_receipt_sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert read_backtest_plan_manifest(root / "manifest.json") == manifest
    assert (root / "manifest.json").read_bytes() == _canonical(asdict(manifest))


def test_cost_schedule_is_contiguous_canonical_and_scales_only_friction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    payload = json.loads((cast(Path, bundle[3]) / "cost_schedule.json").read_bytes())
    assert payload["multipliers"] == ["0.5", "1", "2"]
    assert payload["scaled_components"] == [
        "commission_rate", "commission_min", "slippage"
    ]
    schedules = payload["schedules"]
    assert [item["multiplier"] for item in schedules] == ["0.5", "1", "2"]
    for schedule in schedules:
        periods = schedule["periods"]
        assert periods[-1]["effective_to"] is None
        assert all(item["effective_to"] is not None for item in periods[:-1])
        for left, right in zip(periods, periods[1:]):
            assert dt.date.fromisoformat(left["effective_to"]) + dt.timedelta(days=1) == dt.date.fromisoformat(
                right["effective_from"]
            )
        multiplier = Decimal(schedule["multiplier"])
        for item, base in zip(periods, schedules[1]["periods"]):
            period = AShareCostPeriod(
                effective_from=dt.date.fromisoformat(item["effective_from"]),
                effective_to=None if item["effective_to"] is None else dt.date.fromisoformat(item["effective_to"]),
                commission_rate=Decimal(item["commission_rate"]),
                commission_min=Decimal(item["commission_min"]),
                stamp_tax_sell=Decimal(item["stamp_tax_sell"]),
                transfer_fee=Decimal(item["transfer_fee"]),
                slippage=Decimal(item["slippage"]),
            )
            assert period.commission_rate == Decimal(base["commission_rate"]) * multiplier
            assert period.commission_min == Decimal(base["commission_min"]) * multiplier
            assert period.slippage == Decimal(base["slippage"]) * multiplier
            assert period.stamp_tax_sell == Decimal(base["stamp_tax_sell"])
            assert period.transfer_fee == Decimal(base["transfer_fee"])
    raw = (cast(Path, bundle[3]) / "cost_schedule.json").read_text(encoding="utf-8")
    assert "e-" not in raw.lower()
    assert _canonical(payload) == raw.encode("utf-8")
    assert bundle[5].cost_schedule_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_plan_fails_closed_for_missing_tail_next_session_or_non_signal_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_bundle = _TARGET_SUPPORT._build_bundle(tmp_path, monkeypatch)
    target = _TARGET_SUPPORT._verify(target_bundle)
    parts = _TARGET_SUPPORT._parts(target_bundle[0])
    release = parts["release"]
    sessions = _sh_open_sessions(release)
    last_signal = max(target.target_daily.get_column("as_of"))
    truncated = pl.read_parquet(dict(release.artifact_paths)["trade_calendar.parquet"]).filter(
        pl.col("date") <= last_signal
    )
    drifted_release = _copy_release_with_calendar(
        release,
        cast(Path, parts["common"]) / "development-example-release-no-tail",
        truncated,
    )
    root = cast(Path, parts["common"]) / "development-example-plan-no-tail"
    root.mkdir()
    with pytest.raises(ValueError):
        build_development_example_backtest_plan_artifact(
            target=target, release=drifted_release, folds=parts["folds"],
            experiment=parts["experiment"], config=parts["config"], output_root=root,
        )
    assert not any(root.iterdir())

    non_signal = target.targets.with_columns(
        pl.when(pl.int_range(0, pl.len()) == 0)
        .then(pl.lit(sessions[0]))
        .otherwise(pl.col("as_of"))
        .alias("as_of")
    )
    drifted_target = replace(target, targets=non_signal)
    other = cast(Path, parts["common"]) / "development-example-plan-non-signal"
    other.mkdir()
    with pytest.raises(ValueError):
        build_development_example_backtest_plan_artifact(
            target=drifted_target, release=release, folds=parts["folds"],
            experiment=parts["experiment"], config=parts["config"], output_root=other,
        )
    assert not any(other.iterdir())


@pytest.mark.parametrize("kind", ["mixed_work", "mixed_strategy", "non_a_share"])
def test_plan_rejects_mixed_identity_or_non_a_share_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    target_bundle = _TARGET_SUPPORT._build_bundle(tmp_path, monkeypatch)
    target = _TARGET_SUPPORT._verify(target_bundle)
    parts = _TARGET_SUPPORT._parts(target_bundle[0])
    if kind == "mixed_work":
        drifted = replace(target, manifest=replace(target.manifest, work_key="f" * 64))
    elif kind == "mixed_strategy":
        drifted = replace(
            target,
            targets=target.targets.with_columns(
                pl.when(pl.int_range(0, pl.len()) == 0)
                .then(pl.lit("other"))
                .otherwise(pl.col("strategy"))
                .alias("strategy")
            ),
        )
    else:
        drifted = replace(
            target,
            targets=target.targets.with_columns(
                pl.when(pl.int_range(0, pl.len()) == 0)
                .then(pl.lit("00700.HK"))
                .otherwise(pl.col("symbol"))
                .alias("symbol")
            ),
        )
    root = cast(Path, parts["common"]) / f"development-example-plan-{kind}"
    root.mkdir()
    with pytest.raises(ValueError):
        build_development_example_backtest_plan_artifact(
            target=drifted, release=parts["release"], folds=parts["folds"],
            experiment=parts["experiment"], config=parts["config"], output_root=root,
        )
    assert not any(root.iterdir())


def test_plan_no_clobber_and_rejects_development_identity_mix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    target_bundle, target, _, root, _, _ = bundle
    parts = _TARGET_SUPPORT._parts(target_bundle[0])
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError):
        build_development_example_backtest_plan_artifact(
            target=target, release=parts["release"], folds=parts["folds"],
            experiment=parts["experiment"], config=parts["config"], output_root=root,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    with pytest.raises(ValueError):
        _verify(
            bundle,
            target=replace(target, example_id="development-example-" + "f" * 64),
        )


def test_plan_receipt_exact_closure_and_output_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    _verify(bundle)
    root, receipt = cast(Path, bundle[3]), cast(Path, bundle[4])
    assert {path.name for path in root.iterdir()} == {
        "scheduled_targets.parquet", "schedule_diagnostics.parquet",
        "cost_schedule.json", "manifest.json",
    }
    payload = json.loads(receipt.read_bytes())
    assert len(payload["inputs"]) == 11
    assert len(payload["outputs"]) == 4
    assert payload["stage"] == "development-backtest-plan"
    assert payload["scope"] == "WORK"
    assert payload["scope_key"] == bundle[1].manifest.work_key

    parts = _TARGET_SUPPORT._parts(bundle[0][0])
    decoy = cast(Path, parts["common"]) / "plan-decoy.txt"
    decoy.write_text("not a plan input", encoding="utf-8")
    extra = cast(Path, parts["common"]) / "receipts" / "development-backtest-plan" / "extra.json"
    publish_stage_receipt(
        receipt_path=extra,
        stage="development-backtest-plan",
        scope="WORK",
        scope_key=bundle[1].manifest.work_key,
        artifact_roots=parts["roots"],
        inputs=[*_plan_inputs(bundle[0], bundle[1]), ("root", decoy)],
        outputs=_plan_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=extra)


def test_plan_verifier_rejects_each_output_or_receipt_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    root, receipt = cast(Path, bundle[3]), cast(Path, bundle[4])
    for path in (*[item[1] for item in _plan_outputs(root)], receipt):
        raw = path.read_bytes()
        path.write_bytes(raw + b"drift")
        with pytest.raises(ValueError):
            _verify(bundle)
        path.write_bytes(raw)
        _verify(bundle)


def test_plan_package_import_does_not_load_qlib(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(sys.modules):
        if name == "qlib" or name.startswith("qlib."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.reload(importlib.import_module("quant.backtest.a_share_plan"))
    assert module.BacktestPlanManifestV1 is BacktestPlanManifestV1
    assert not any(name == "qlib" or name.startswith("qlib.") for name in sys.modules)
