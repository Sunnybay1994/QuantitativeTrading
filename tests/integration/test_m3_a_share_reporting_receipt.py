"""G7F development backtest StageReceipt closure integration tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from quant.backtest.a_share_reporting import (
    BacktestArtifactUpstreamPaths,
    build_development_example_backtest_artifact,
    verify_development_example_backtest_artifact,
)
from quant.research.m3.contracts import VerifiedTargetArtifact
from quant.research.m3.run_state import publish_stage_receipt

_PLAN_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_plan_test_support_for_reporting_receipt",
    Path(__file__).parents[1] / "unit" / "test_m3_backtest_plan_artifact.py",
)
assert _PLAN_SUPPORT_SPEC is not None and _PLAN_SUPPORT_SPEC.loader is not None
_PLAN_SUPPORT = importlib.util.module_from_spec(_PLAN_SUPPORT_SPEC)
_PLAN_SUPPORT_SPEC.loader.exec_module(_PLAN_SUPPORT)

_MARKET_FACT_FILES = (
    "bar_1d.parquet",
    "benchmark_bar_1d.parquet",
    "corporate_action_ledger.parquet",
    "corporate_action_reconciliation.parquet",
    "instrument.parquet",
    "price_limit_1d.parquet",
    "suspension_1d.parquet",
    "trade_calendar.parquet",
)


def _inputs(plan_bundle: tuple[Any, ...]) -> list[tuple[str, Path]]:
    target_bundle, target, _, plan_root, plan_receipt, _ = plan_bundle
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(target_bundle[0])
    release = parts["release"]
    experiment = parts["experiment"]
    paths = dict(release.artifact_paths)
    result = [
        ("root", target.root / "target_weights.parquet"),
        ("root", target.root / "target_daily.parquet"),
        ("root", target.root / "target_manifest.json"),
        ("root", cast(Path, target_bundle[5])),
        ("root", cast(Path, plan_root) / "scheduled_targets.parquet"),
        ("root", cast(Path, plan_root) / "schedule_diagnostics.parquet"),
        ("root", cast(Path, plan_root) / "cost_schedule.json"),
        ("root", cast(Path, plan_root) / "manifest.json"),
        ("root", cast(Path, plan_receipt)),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", _PLAN_SUPPORT._TARGET_SUPPORT._experiment_receipt(parts)),
        ("root", release.release.manifest_path),
        ("root", release.release.root / "receipt.json"),
        *(("root", paths[name]) for name in _MARKET_FACT_FILES),
    ]
    assert len(result) == 21
    return result


def _outputs(root: Path) -> list[tuple[str, Path]]:
    return [("root", path) for path in sorted(root.rglob("*")) if path.is_file()]


def _build_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    plan_bundle = _PLAN_SUPPORT._build_bundle(tmp_path, monkeypatch)
    plan = _PLAN_SUPPORT._verify(plan_bundle)
    target_bundle, target, _, _, plan_receipt, _ = plan_bundle
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(target_bundle[0])
    common = cast(Path, parts["common"])
    root = common / f"development-example-backtest-{target.manifest.work_key}"
    root.mkdir()
    manifest = build_development_example_backtest_artifact(
        target=target,
        plan=plan,
        release=parts["release"],
        experiment=parts["experiment"],
        config=parts["config"],
        output_root=root,
    )
    receipt = (
        common
        / "receipts"
        / "development-backtest"
        / f"{target.manifest.work_key}.json"
    )
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-backtest",
        scope="WORK",
        scope_key=target.manifest.work_key,
        artifact_roots=parts["roots"],
        inputs=_inputs(plan_bundle),
        outputs=_outputs(root),
    )
    upstream = BacktestArtifactUpstreamPaths(
        target_receipt_path=cast(Path, target_bundle[5]),
        plan_receipt_path=cast(Path, plan_receipt),
        experiment_receipt_path=(
            _PLAN_SUPPORT._TARGET_SUPPORT._experiment_receipt(parts)
        ),
        g1_receipt_path=release_receipt(parts),
    )
    return plan_bundle, target, plan, upstream, root, receipt, manifest


def release_receipt(parts: dict[str, Any]) -> Path:
    return cast(Path, parts["release"].release.root / "receipt.json")


def _verify(
    bundle: tuple[Any, ...],
    *,
    receipt: Path | None = None,
    target: Any = None,
    artifact_roots: dict[str, Path] | None = None,
) -> Any:
    plan_bundle, default_target, plan, upstream, root, default_receipt, _ = bundle
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(plan_bundle[0][0])
    return verify_development_example_backtest_artifact(
        root=root,
        receipt_path=receipt or default_receipt,
        target=target or default_target,
        plan=plan,
        release=parts["release"],
        experiment=parts["experiment"],
        config=parts["config"],
        upstream_paths=upstream,
        artifact_roots=artifact_roots or parts["roots"],
    )


def _publish_variant(
    bundle: tuple[Any, ...],
    *,
    name: str,
    inputs: list[tuple[str, Path]] | None = None,
    outputs: list[tuple[str, Path]] | None = None,
    artifact_roots: dict[str, Path] | None = None,
) -> Path:
    plan_bundle, target, _, _, root, receipt, _ = bundle
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(plan_bundle[0][0])
    path = cast(Path, receipt).with_name(f"{name}.json")
    publish_stage_receipt(
        receipt_path=path,
        stage="development-backtest",
        scope="WORK",
        scope_key=target.manifest.work_key,
        artifact_roots=artifact_roots or parts["roots"],
        inputs=inputs or _inputs(plan_bundle),
        outputs=outputs or _outputs(cast(Path, root)),
    )
    return path


def test_backtest_receipt_covers_every_input_and_recursive_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    root, receipt = cast(Path, bundle[4]), cast(Path, bundle[5])
    payload = json.loads(receipt.read_bytes())

    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert payload["stage"] == "development-backtest"
    assert payload["scope"] == "WORK"
    assert payload["scope_key"] == bundle[1].manifest.work_key
    assert len(payload["inputs"]) == 21
    assert len(payload["outputs"]) == 29
    assert len(_outputs(root)) == 29
    assert {path.name for path in root.iterdir() if path.is_file()} == {
        "backtest_metrics.json",
        "backtest_manifest.json",
    }
    scenario_dirs = tuple(sorted(path for path in root.iterdir() if path.is_dir()))
    assert tuple(path.name for path in scenario_dirs) == ("0p5x", "1p0x", "2p0x")
    for scenario in scenario_dirs:
        files = tuple(path for path in scenario.iterdir() if path.is_file())
        assert len(files) == 9
        manifest_payload = json.loads((scenario / "manifest.json").read_bytes())
        assert len(manifest_payload["output_files"]) == 8
        assert "manifest.json" not in {
            item["path"] for item in manifest_payload["output_files"]
        }


def test_backtest_receipt_rejects_missing_empty_table_extra_and_digest_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    root = cast(Path, bundle[4])
    outputs = _outputs(root)
    empty_table = next(
        path
        for _, path in outputs
        if path.suffix == ".parquet" and pl.read_parquet(path).is_empty()
    )
    missing = _publish_variant(
        bundle,
        name="missing-empty-table",
        outputs=[item for item in outputs if item[1] != empty_table],
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=missing)

    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(bundle[0][0][0])
    decoy = cast(Path, parts["common"]) / "backtest-receipt-decoy.txt"
    decoy.write_text("not a backtest output", encoding="utf-8")
    extra = _publish_variant(
        bundle,
        name="extra-output",
        outputs=[*outputs, ("root", decoy)],
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=extra)

    raw = empty_table.read_bytes()
    empty_table.write_bytes(raw + b"digest-drift")
    with pytest.raises(ValueError):
        _verify(bundle)
    empty_table.write_bytes(raw)
    _verify(bundle)


def test_backtest_receipt_rejects_root_alias_and_formal_identity_mix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    plan_bundle, target, _, _, root, _, _ = bundle
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(plan_bundle[0][0])
    roots = {**parts["roots"], "same_files_wrong_alias": cast(Path, parts["common"])}
    with pytest.raises(ValueError):
        _publish_variant(
            bundle,
            name="wrong-root-alias",
            inputs=[("same_files_wrong_alias", path) for _, path in _inputs(plan_bundle)],
            outputs=[("same_files_wrong_alias", path) for _, path in _outputs(root)],
            artifact_roots=roots,
        )

    formal_target = VerifiedTargetArtifact(
        root=target.root,
        targets=target.targets,
        target_daily=target.target_daily,
        manifest=target.manifest,
        manifest_sha256=target.manifest_sha256,
        target_receipt_sha256=target.target_receipt_sha256,
    )
    with pytest.raises((TypeError, ValueError)):
        _verify(bundle, target=formal_target)
