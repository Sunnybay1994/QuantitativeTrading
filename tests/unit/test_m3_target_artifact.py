"""G7A development target artifact adversarial contract tests."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.research.m3.targets as target_module
from quant.domain import TargetWeightSchema
from quant.research.m3.contracts import TargetBuildSpec, TargetUpstreamPaths
from quant.research.m3.development_example import VerifiedDevelopmentExampleTargetArtifact
from quant.research.m3.run_state import publish_stage_receipt
from quant.research.m3.targets import (
    build_development_example_target_artifact,
    build_target_spec,
    read_target_manifest,
    verify_development_example_target_artifact,
)
from quant.strategies.ml_topk import MlTopkStrategy

_PREDICTION_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_prediction_test_support_for_target",
    Path(__file__).with_name("test_m3_prediction_artifact.py"),
)
assert _PREDICTION_SUPPORT_SPEC is not None
assert _PREDICTION_SUPPORT_SPEC.loader is not None
_PREDICTION_SUPPORT = importlib.util.module_from_spec(_PREDICTION_SUPPORT_SPEC)
_PREDICTION_SUPPORT_SPEC.loader.exec_module(_PREDICTION_SUPPORT)


def _parts(prediction_bundle: tuple[Any, ...]) -> dict[str, Any]:
    model_bundle = prediction_bundle[0]
    alignment_bundle = model_bundle[0]
    feature_bundle, feature, label, label_spec, alignment_spec, _, _, _, _ = (
        alignment_bundle
    )
    (
        common, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, fold_spec, folds, feature_spec,
        feature_upstream, _, feature_receipt, _,
    ) = feature_bundle
    return {
        "common": common,
        "roots": roots,
        "release": release,
        "snapshot": snapshot,
        "snapshot_spec": snapshot_spec,
        "provider": provider,
        "provider_spec": provider_spec,
        "config": config,
        "experiment_spec": experiment_spec,
        "experiment": experiment,
        "fold_spec": fold_spec,
        "folds": folds,
        "feature_spec": feature_spec,
        "feature_upstream": feature_upstream,
        "feature_receipt": feature_receipt,
        "feature": feature,
        "label": label,
        "label_spec": label_spec,
        "alignment": model_bundle[1],
        "alignment_spec": alignment_spec,
        "model": prediction_bundle[1],
        "model_spec": model_bundle[2],
        "prediction_upstream": prediction_bundle[3],
        "prediction_receipt": prediction_bundle[5],
    }


def _experiment_receipt(parts: dict[str, Any]) -> Path:
    return cast(
        Path,
        parts["feature_upstream"].fold_upstream_paths.experiment_receipt_path,
    )


def _fold_receipt(parts: dict[str, Any]) -> Path:
    return cast(Path, parts["feature_upstream"].fold_receipt_path)


def _target_inputs(
    prediction_bundle: tuple[Any, ...],
    prediction: Any,
) -> list[tuple[str, Path]]:
    parts = _parts(prediction_bundle)
    release = parts["release"]
    feature = parts["feature"]
    folds = parts["folds"]
    experiment = parts["experiment"]
    test = next(item for item in feature.manifest.segments if item.name == "test")
    return [
        ("root", release.release.manifest_path),
        ("root", release.release.root / "receipt.json"),
        ("root", dict(release.artifact_paths)["eligible_keys.parquet"]),
        ("root", feature.root / "feature_manifest.json"),
        ("root", cast(Path, parts["feature_receipt"])),
        ("root", feature.root / test.path),
        ("root", prediction.root / "prediction_manifest.json"),
        ("root", cast(Path, parts["prediction_receipt"])),
        ("root", prediction.root / "predictions.parquet"),
        ("root", folds.root / "folds.json"),
        ("root", _fold_receipt(parts)),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", _experiment_receipt(parts)),
    ]


def _target_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / "target_daily.parquet"),
        ("root", root / "target_manifest.json"),
        ("root", root / "target_weights.parquet"),
    ]


def _build_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    prediction_bundle = _PREDICTION_SUPPORT._build_bundle(tmp_path, monkeypatch)
    prediction = _PREDICTION_SUPPORT._verify(prediction_bundle)
    parts = _parts(prediction_bundle)
    spec = build_target_spec(
        release=parts["release"],
        feature=parts["feature"],
        prediction=prediction,
        folds=parts["folds"],
        experiment=parts["experiment"],
        config=parts["config"],
    )
    root = cast(Path, parts["common"]) / f"development-example-target-{spec.work_key}"
    root.mkdir()
    manifest = build_development_example_target_artifact(
        release=parts["release"],
        feature=parts["feature"],
        prediction=prediction,
        folds=parts["folds"],
        experiment=parts["experiment"],
        config=parts["config"],
        spec=spec,
        output_root=root,
    )
    receipt = (
        cast(Path, parts["common"])
        / "receipts"
        / "development-targets"
        / f"{spec.work_key}.json"
    )
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-targets",
        scope="WORK",
        scope_key=spec.work_key,
        artifact_roots=parts["roots"],
        inputs=_target_inputs(prediction_bundle, prediction),
        outputs=_target_outputs(root),
    )
    upstream_paths = TargetUpstreamPaths(
        feature_receipt_path=cast(Path, parts["feature_receipt"]),
        prediction_receipt_path=cast(Path, parts["prediction_receipt"]),
        prediction_upstream_paths=parts["prediction_upstream"],
        fold_receipt_path=_fold_receipt(parts),
        experiment_receipt_path=_experiment_receipt(parts),
    )
    return prediction_bundle, prediction, spec, upstream_paths, root, receipt, manifest


def _verify(
    bundle: tuple[Any, ...],
    *,
    prediction: Any = None,
    feature: Any = None,
    spec: Any = None,
    receipt: Path | None = None,
) -> VerifiedDevelopmentExampleTargetArtifact:
    prediction_bundle, default_prediction, default_spec, upstream_paths, root, default_receipt, _ = bundle
    parts = _parts(prediction_bundle)
    kwargs = {
        "root": root,
        "receipt_path": receipt or default_receipt,
        **parts,
        "prediction": prediction or default_prediction,
        "feature": feature or parts["feature"],
        "spec": spec or default_spec,
        "upstream_paths": upstream_paths,
        "artifact_roots": parts["roots"],
    }
    parameters = inspect.signature(verify_development_example_target_artifact).parameters
    return verify_development_example_target_artifact(
        **{name: value for name, value in kwargs.items() if name in parameters}
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@pytest.mark.parametrize("n_symbols", [299, 300, 301])
def test_topk_target_domain_preserves_every_eligible_key(n_symbols: int) -> None:
    symbols = [f"{index:06d}.SH" for index in range(1, n_symbols + 1)]
    frame = pl.DataFrame(
        {
            "as_of": ["2025-01-02"] * n_symbols,
            "symbol": symbols,
            "score": [float(n_symbols - index) for index in range(n_symbols)],
            "rank": list(range(1, n_symbols + 1)),
            "model": ["lightgbm"] * n_symbols,
            "model_version": ["v1"] * n_symbols,
            "dataset_snapshot_id": ["snapshot"] * n_symbols,
            "fold": ["fold_000"] * n_symbols,
            "horizon_sessions": [5] * n_symbols,
            "eligible": [True] * n_symbols,
        }
    ).with_columns(pl.col("as_of").str.to_date())
    strategy = MlTopkStrategy(top_k=30, cash_buffer=0.05, max_weight=0.05)
    targets = strategy.target_weights(frame.item(0, "as_of"), frame)
    assert targets.height == n_symbols
    assert set(targets.get_column("symbol")) == set(symbols)
    assert targets.filter(pl.col("weight") > 0).height == 30


def test_topk_keeps_unscorable_eligible_at_zero_and_never_reads_positions() -> None:
    frame = pl.DataFrame(
        {
            "as_of": ["2025-01-02"] * 3,
            "symbol": ["600000.SH", "600001.SH", "600002.SH"],
            "score": [1.0, None, 1.0],
            "rank": [1, None, 2],
            "model": ["lightgbm", None, "lightgbm"],
            "model_version": ["v1", None, "v1"],
            "dataset_snapshot_id": ["snapshot", None, "snapshot"],
            "fold": ["fold_000", None, "fold_000"],
            "horizon_sessions": [5, None, 5],
            "eligible": [True, True, True],
        }
    ).with_columns(pl.col("as_of").str.to_date())
    signature = inspect.signature(MlTopkStrategy.target_weights)
    assert "positions" not in signature.parameters
    targets = MlTopkStrategy(top_k=2, cash_buffer=0.1, max_weight=0.6).target_weights(
        frame.item(0, "as_of"), frame
    )
    assert targets.sort("symbol").get_column("weight").to_list() == [0.45, 0.0, 0.45]


def test_target_closed_loop_has_exact_domain_daily_counts_and_decimal_weights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    prediction_bundle, prediction, spec, _, root, receipt, manifest = bundle
    parts = _parts(prediction_bundle)
    release = parts["release"]
    folds = parts["folds"]
    planned = next(item for item in folds.manifest.folds if item.name == spec.fold)
    eligible = pl.read_parquet(dict(release.artifact_paths)["eligible_keys.parquet"]).filter(
        pl.col("as_of").is_in(
            pl.Series("test_dates", planned.test_dates, dtype=pl.Date)
        )
    ).sort("as_of", "symbol")
    targets = verified.targets.sort("as_of", "symbol")
    daily = verified.target_daily.sort("as_of")

    assert isinstance(verified, VerifiedDevelopmentExampleTargetArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.example_id == release.manifest.example_id
    assert targets.select("as_of", "symbol").equals(eligible.select("as_of", "symbol"))
    assert TargetWeightSchema.validate(targets).equals(targets)
    assert daily.columns == [
        "as_of", "n_eligible", "n_scorable", "n_predicted", "n_selected",
        "scorable_coverage", "total_target_weight",
    ]
    assert daily.get_column("as_of").is_sorted()
    assert daily.get_column("n_eligible").sum() == targets.height
    assert daily.get_column("n_predicted").sum() == prediction.predictions.height
    assert daily.get_column("n_selected").sum() == targets.filter(pl.col("weight") > 0).height
    for day in daily.iter_rows(named=True):
        n_eligible = eligible.filter(pl.col("as_of") == day["as_of"]).height
        n_predicted = prediction.predictions.filter(
            pl.col("as_of") == day["as_of"]
        ).height
        assert day["n_eligible"] == n_eligible
        assert day["n_scorable"] == day["n_predicted"] == n_predicted
        assert day["scorable_coverage"] == n_predicted / n_eligible
        n_selected = cast(int, day["n_selected"])
        expected = min(
            (Decimal("1") - Decimal(str(spec.cash_buffer))) / Decimal(n_selected),
            Decimal(str(spec.max_weight)),
        )
        selected = targets.filter(
            (pl.col("as_of") == day["as_of"]) & (pl.col("weight") > 0)
        )
        assert all(Decimal(str(value)) == expected for value in selected["weight"])
    assert manifest.n_selected == daily.get_column("n_selected").sum()
    assert manifest.targets_sha256 == hashlib.sha256(
        (root / "target_weights.parquet").read_bytes()
    ).hexdigest()
    assert manifest.target_daily_sha256 == hashlib.sha256(
        (root / "target_daily.parquet").read_bytes()
    ).hexdigest()
    assert verified.target_receipt_sha256 == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert read_target_manifest(root / "target_manifest.json") == manifest
    assert (root / "target_manifest.json").read_bytes() == _canonical(asdict(manifest))


def test_r2_development_target_reuses_fixed_decimal_allocation_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    prediction_bundle, prediction, spec = bundle[:3]
    parts = _parts(prediction_bundle)
    calls: list[int] = []
    real_allocation = target_module._target_allocation

    def counted_allocation(
        *, cash_buffer: float, max_weight: float, n_selected: int,
    ) -> tuple[Decimal, Decimal]:
        calls.append(n_selected)
        return real_allocation(
            cash_buffer=cash_buffer,
            max_weight=max_weight,
            n_selected=n_selected,
        )

    monkeypatch.setattr(target_module, "_target_allocation", counted_allocation)
    targets, daily = target_module._build_target_frames(
        parts["release"], parts["feature"], prediction, parts["folds"], spec
    )
    assert calls == daily.get_column("n_selected").to_list()
    assert targets.height == daily.get_column("n_eligible").sum()
    weight, total = real_allocation(
        cash_buffer=0.1, max_weight=0.2, n_selected=7
    )
    assert weight < Decimal("0.2") and total <= Decimal("0.9")


def test_target_spec_is_config_projection_not_caller_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    spec = cast(TargetBuildSpec, bundle[2])
    config = _parts(bundle[0])["config"]
    portfolio = config.section("portfolio")
    assert spec.strategy == "topk"
    assert spec.strategy_version == portfolio["strategy_version"]
    assert spec.top_k == portfolio["top_k"]
    assert spec.cash_buffer == portfolio["cash_buffer"]
    assert spec.max_weight == portfolio["max_weight"]
    assert spec.minimum_scorable_coverage == config.section("features")[
        "minimum_scorable_coverage"
    ]
    assert spec.minimum_scorable_coverage == 0.5
    forbidden = {
        "g1_release_id", "g1_release_manifest_sha256", "prediction_manifest_sha256",
        "feature_manifest_sha256", "eligible_keys_sha256", "signal_dates_sha256",
        "scientific_config_sha256",
    }
    assert forbidden.isdisjoint(inspect.signature(build_target_spec).parameters)


@pytest.mark.parametrize("kind", ["missing", "extra", "duplicate", "outside"])
def test_target_builder_rejects_prediction_key_drift_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    prediction_bundle = _PREDICTION_SUPPORT._build_bundle(tmp_path, monkeypatch)
    prediction = _PREDICTION_SUPPORT._verify(prediction_bundle)
    parts = _parts(prediction_bundle)
    frame = prediction.predictions
    if kind == "missing":
        drift = frame.slice(0, frame.height - 1)
    elif kind == "extra":
        drift = pl.concat([
            frame,
            frame.slice(-1, 1).with_columns(pl.lit("600999.SH").alias("symbol")),
        ])
    elif kind == "duplicate":
        drift = pl.concat([frame, frame.slice(0, 1)])
    else:
        drift = frame.with_columns(
            pl.when(pl.int_range(0, pl.len()) == 0)
            .then(pl.lit("600999.SH"))
            .otherwise(pl.col("symbol"))
            .alias("symbol")
        )
    drifted = replace(prediction, predictions=drift)
    spec = build_target_spec(
        release=parts["release"], feature=parts["feature"], prediction=prediction,
        folds=parts["folds"], experiment=parts["experiment"], config=parts["config"],
    )
    root = cast(Path, parts["common"]) / f"development-example-target-key-{kind}"
    root.mkdir()
    with pytest.raises(ValueError):
        build_development_example_target_artifact(
            release=parts["release"], feature=parts["feature"], prediction=drifted,
            folds=parts["folds"], experiment=parts["experiment"],
            config=parts["config"], spec=spec, output_root=root,
        )
    assert not any(root.iterdir())


def test_target_rejects_identity_mix_low_coverage_empty_prediction_and_no_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    prediction_bundle, prediction, spec, _, root, _, _ = bundle
    parts = _parts(prediction_bundle)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError):
        build_development_example_target_artifact(
            release=parts["release"], feature=parts["feature"], prediction=prediction,
            folds=parts["folds"], experiment=parts["experiment"],
            config=parts["config"], spec=spec, output_root=root,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    for invalid in (
        replace(spec, strategy_version="lineage-drift"),
        replace(spec, fold="fold_999"),
        replace(spec, horizon_sessions=10),
        replace(spec, minimum_scorable_coverage=1.0),
    ):
        with pytest.raises(ValueError):
            _verify(bundle, spec=invalid)
    with pytest.raises(ValueError):
        _verify(
            bundle,
            feature=replace(
                parts["feature"], example_id="development-example-" + "f" * 64
            ),
        )
    with pytest.raises(ValueError):
        _verify(bundle, prediction=replace(prediction, predictions=prediction.predictions.head(0)))


def test_target_receipt_has_exact_thirteen_inputs_and_three_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    _verify(bundle)
    payload = json.loads(cast(Path, bundle[5]).read_bytes())
    assert len(payload["inputs"]) == 13
    assert len(payload["outputs"]) == 3
    assert payload["stage"] == "development-targets"
    assert payload["scope"] == "WORK"
    assert payload["scope_key"] == bundle[2].work_key

    parts = _parts(bundle[0])
    decoy = cast(Path, parts["common"]) / "target-decoy.txt"
    decoy.write_text("not a target input", encoding="utf-8")
    receipt = cast(Path, parts["common"]) / "receipts" / "development-targets" / "extra.json"
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-targets",
        scope="WORK",
        scope_key=bundle[2].work_key,
        artifact_roots=parts["roots"],
        inputs=[*_target_inputs(bundle[0], bundle[1]), ("root", decoy)],
        outputs=_target_outputs(bundle[4]),
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=receipt)


def test_target_verifier_rejects_output_or_receipt_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_bundle(tmp_path, monkeypatch)
    root, receipt = cast(Path, bundle[4]), cast(Path, bundle[5])
    for path in (*[item[1] for item in _target_outputs(root)], receipt):
        raw = path.read_bytes()
        path.write_bytes(raw + b"drift")
        with pytest.raises(ValueError):
            _verify(bundle)
        path.write_bytes(raw)
        _verify(bundle)


def test_target_wholesale_bundle_from_foreign_work_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path, second_path = tmp_path / "first", tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first = _build_bundle(first_path, monkeypatch)
    second = _build_bundle(second_path, monkeypatch)
    foreign_root = cast(Path, second[4])
    foreign_manifest_path = foreign_root / "target_manifest.json"
    payload = json.loads(foreign_manifest_path.read_bytes())
    payload["work_key"] = "f" * 64
    foreign_manifest_path.write_bytes(_canonical(payload))
    foreign_receipt = cast(Path, second[5])
    foreign_receipt.unlink()
    foreign_parts = _parts(second[0])
    publish_stage_receipt(
        receipt_path=foreign_receipt,
        stage="development-targets",
        scope="WORK",
        scope_key="f" * 64,
        artifact_roots=foreign_parts["roots"],
        inputs=_target_inputs(second[0], second[1]),
        outputs=_target_outputs(foreign_root),
    )
    first_root = cast(Path, first[4])
    for _, source in _target_outputs(foreign_root):
        (first_root / source.name).write_bytes(source.read_bytes())
    cast(Path, first[5]).write_bytes(foreign_receipt.read_bytes())
    with pytest.raises(ValueError):
        _verify(first)


def test_target_package_import_is_lightgbm_free() -> None:
    # Subprocess only: in-process reload replaces targets and breaks later
    # formal/target consumers holding pre-reload types.
    script = """
import sys
for name in list(sys.modules):
    if name == "lightgbm" or name.startswith("lightgbm."):
        del sys.modules[name]
import quant.research.m3 as public
import quant.research.m3.targets as targets
assert public.TargetBuildSpec is not None
assert public.VerifiedDevelopmentExampleTargetArtifact is not None
assert targets is not None
assert not any(name == "lightgbm" or name.startswith("lightgbm.") for name in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert completed.returncode == 0, completed.stderr
