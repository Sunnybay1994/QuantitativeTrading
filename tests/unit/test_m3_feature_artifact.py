"""G4B development-only FeatureArtifact parent contract tests."""

from __future__ import annotations

import hashlib
import io
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import quant.research.m3 as m3_public
from quant.research.m3.contracts import FeatureBuildSpec, FeatureUpstreamPaths
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleFeatureArtifact,
)
from quant.research.m3.features import (
    build_feature_artifact,
    build_development_example_feature_artifact,
    verify_feature_artifact,
    verify_development_example_feature_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_fold_plan_test_support",
    Path(__file__).with_name("test_m3_fold_plan_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _feature_spec(
    *, provider: Any, experiment: Any, folds: Any, config: Any,
) -> FeatureBuildSpec:
    planned = folds.manifest.folds[0]
    return FeatureBuildSpec(
        experiment_key=experiment.manifest.experiment_key,
        experiment_manifest_sha256=experiment.manifest_sha256,
        fold=planned.name,
        planned_fold_sha256=planned.planned_fold_sha256,
        provider_key=provider.manifest.provider_key,
        provider_manifest_sha256=provider.manifest_sha256,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        feature_version=config.section("features")["feature_version"],
        expected_qlib_version="0.9.7",
        worker_protocol_version="m3-qlib-worker-v1",
    )


def _feature_inputs(
    *, release: Any, snapshot: Any, provider: Any, experiment: Any,
    folds: Any, upstream_paths: FeatureUpstreamPaths,
) -> list[tuple[str, Path]]:
    fold_paths = upstream_paths.fold_upstream_paths
    return [
        ("root", release.release.manifest_path),
        ("root", dict(release.artifact_paths)["eligible_keys.parquet"]),
        ("root", fold_paths.snapshot_request_path),
        ("root", snapshot.root / "manifest.json"),
        ("root", fold_paths.snapshot_receipt_path),
        ("root", snapshot.session_calendar_path),
        ("root", provider.root / "provider_manifest.json"),
        ("root", fold_paths.provider_receipt_path),
        ("root", experiment.root / "experiment_manifest.json"),
        ("root", fold_paths.experiment_receipt_path),
        ("root", folds.root / "folds.json"),
        ("root", upstream_paths.fold_receipt_path),
    ]


def _feature_outputs(root: Path) -> list[tuple[str, Path]]:
    return [
        ("root", root / name)
        for name in (
            "request.json",
            "worker-response.json",
            "train.parquet",
            "validation.parquet",
            "test.parquet",
            "coverage.parquet",
            "feature_manifest.json",
        )
    ]


def _build_feature_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    real_subprocess_run = subprocess.run
    (
        common, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, _, _, _, _, fold_spec,
        fold_upstream_paths, fold_root, fold_receipt, _, folds,
    ) = _SUPPORT._build_verified_bundle(tmp_path, monkeypatch)
    # G4A support materialises its provider through a narrow subprocess fake.
    # G4B itself must exercise the actual fresh Python worker boundary.
    monkeypatch.setattr(subprocess, "run", real_subprocess_run)
    spec = _feature_spec(
        provider=provider, experiment=experiment, folds=folds, config=config,
    )
    upstream_paths = FeatureUpstreamPaths(
        fold_receipt_path=fold_receipt,
        fold_upstream_paths=fold_upstream_paths,
    )
    root = common / f"development-example-features-{spec.fold}"
    root.mkdir()
    manifest = build_development_example_feature_artifact(
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        config=config,
        spec=spec,
        upstream_paths=upstream_paths,
        artifact_roots=roots,
        python_executable=Path(sys.executable),
        output_root=root,
        timeout_seconds=60.0,
    )
    receipt = (
        common / "receipts" / "development-features"
        / f"{experiment.manifest.experiment_key}-{spec.fold}.json"
    )
    receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-features",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots=roots,
        inputs=_feature_inputs(
            release=release,
            snapshot=snapshot,
            provider=provider,
            experiment=experiment,
            folds=folds,
            upstream_paths=upstream_paths,
        ),
        outputs=_feature_outputs(root),
    )
    return (
        common, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, fold_spec, folds, spec,
        upstream_paths, root, receipt, manifest,
    )


def _verify(bundle: tuple[Any, ...], *, receipt: Path | None = None) -> Any:
    (
        _, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, fold_spec, folds, spec,
        upstream_paths, root, default_receipt, _,
    ) = bundle
    return verify_development_example_feature_artifact(
        root=root,
        receipt_path=receipt or default_receipt,
        release=release,
        snapshot=snapshot,
        snapshot_spec=snapshot_spec,
        provider=provider,
        provider_spec=provider_spec,
        experiment=experiment,
        experiment_spec=experiment_spec,
        folds=folds,
        fold_spec=fold_spec,
        config=config,
        spec=spec,
        upstream_paths=upstream_paths,
        artifact_roots=roots,
    )


def test_package_root_exports_verified_feature_contract_without_qlib() -> None:
    assert m3_public.FeatureBuildSpec is FeatureBuildSpec
    assert m3_public.FeatureUpstreamPaths is FeatureUpstreamPaths
    assert m3_public.VerifiedFeatureArtifact is not None
    assert m3_public.VerifiedDevelopmentExampleFeatureArtifact is not None
    assert m3_public.build_feature_artifact is build_feature_artifact
    assert m3_public.verify_feature_artifact is verify_feature_artifact
    probe = (
        "import sys; import quant.research.m3 as m; "
        "assert m.FeatureBuildSpec is not None; "
        "assert not any(n == 'qlib' or n.startswith('qlib.') for n in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert completed.returncode == 0, completed.stderr


def test_development_feature_artifact_preserves_fold_shared_nan_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_feature_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    root = cast(Path, bundle[-3])
    built_manifest = bundle[-1]

    assert isinstance(verified, VerifiedDevelopmentExampleFeatureArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False
    assert verified.manifest == built_manifest
    schema = verified.manifest.schema
    assert len(schema.input_names) == 158
    assert len(schema.expressions) == 158
    assert len(schema.selected_names) == 157
    assert schema.dropped_all_nan_train == ("ALPHA158",)
    assert "ALPHA158" not in schema.selected_names
    assert tuple(segment.name for segment in verified.manifest.segments) == (
        "train", "validation", "test",
    )

    test_frame = pl.read_parquet(root / "test.parquet")
    assert test_frame.columns == ["as_of", "symbol", *schema.selected_names]
    assert "ALPHA158" not in test_frame.columns
    unscorable = test_frame.filter(
        pl.all_horizontal(pl.col(name).is_nan() | pl.col(name).is_null()
                          for name in schema.selected_names)
    )
    assert unscorable.height >= 1
    test_segment = next(
        segment for segment in verified.manifest.segments if segment.name == "test"
    )
    assert test_segment.n_feature_rows == test_frame.height
    assert test_segment.n_scorable < test_segment.n_feature_rows

    coverage = pl.read_parquet(root / "coverage.parquet")
    assert coverage.height == verified.manifest.coverage_row_count
    assert coverage.columns == [
        "segment", "as_of", "n_eligible", "n_feature_rows", "n_scorable",
        "reason",
    ]
    request = json.loads((root / "request.json").read_bytes())
    response = json.loads((root / "worker-response.json").read_bytes())
    assert request["release_kind"] == "development_example"
    assert request["formal_gate_eligible"] is False
    assert request["provider_uri_sha256"] == hashlib.sha256(
        _canonical([request["provider_key"], "provider"])
    ).hexdigest()
    for key, value in request.items():
        if key != "eligible_rows":
            assert response[key] == value
    request_text = (root / "request.json").read_text(encoding="utf-8")
    assert "provider_uri" not in request
    assert "pid" not in request
    assert str(bundle[5].root.resolve()) not in request_text


def test_feature_no_clobber_and_rejects_cross_kind_or_spec_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_feature_bundle(tmp_path, monkeypatch)
    (
        common, roots, release, snapshot, snapshot_spec, provider, provider_spec,
        config, experiment_spec, experiment, fold_spec, folds, spec,
        upstream_paths, root, _, _,
    ) = bundle
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError):
        build_development_example_feature_artifact(
            release=release,
            snapshot=snapshot,
            snapshot_spec=snapshot_spec,
            provider=provider,
            provider_spec=provider_spec,
            experiment=experiment,
            experiment_spec=experiment_spec,
            folds=folds,
            fold_spec=fold_spec,
            config=config,
            spec=spec,
            upstream_paths=upstream_paths,
            artifact_roots=roots,
            python_executable=Path(sys.executable),
            output_root=root,
            timeout_seconds=60.0,
        )
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before

    wrong_root = common / "development-example-features-wrong-spec"
    wrong_root.mkdir()
    with pytest.raises(ValueError):
        build_development_example_feature_artifact(
            release=release,
            snapshot=snapshot,
            snapshot_spec=snapshot_spec,
            provider=provider,
            provider_spec=provider_spec,
            experiment=experiment,
            experiment_spec=experiment_spec,
            folds=folds,
            fold_spec=fold_spec,
            config=config,
            spec=replace(spec, feature_version="alpha158-drift"),
            upstream_paths=upstream_paths,
            artifact_roots=roots,
            python_executable=Path(sys.executable),
            output_root=wrong_root,
            timeout_seconds=60.0,
        )
    assert not any(wrong_root.iterdir())

    cross_root = common / "development-example-features-cross-kind"
    cross_root.mkdir()
    with pytest.raises((TypeError, ValueError, AttributeError)):
        build_development_example_feature_artifact(
            release=cast(Any, release.release),
            snapshot=snapshot,
            snapshot_spec=snapshot_spec,
            provider=provider,
            provider_spec=provider_spec,
            experiment=experiment,
            experiment_spec=experiment_spec,
            folds=folds,
            fold_spec=fold_spec,
            config=config,
            spec=spec,
            upstream_paths=upstream_paths,
            artifact_roots=roots,
            python_executable=Path(sys.executable),
            output_root=cross_root,
            timeout_seconds=60.0,
        )
    assert not any(cross_root.iterdir())

    with pytest.raises(ValueError, match="formal feature build requires formal"):
        build_feature_artifact(
            release=cast(Any, release), snapshot=cast(Any, snapshot),
            snapshot_spec=snapshot_spec, provider=cast(Any, provider),
            provider_spec=provider_spec, experiment=cast(Any, experiment),
            experiment_spec=experiment_spec, folds=cast(Any, folds),
            fold_spec=fold_spec, config=config, spec=spec,
            upstream_paths=upstream_paths, artifact_roots=roots,
            python_executable=Path(sys.executable), output_root=cross_root,
            timeout_seconds=60.0,
        )
    with pytest.raises(ValueError, match="formal feature verify requires formal"):
        verify_feature_artifact(
            root=root, receipt_path=cast(Path, bundle[-2]),
            release=cast(Any, release), snapshot=cast(Any, snapshot),
            snapshot_spec=snapshot_spec, provider=cast(Any, provider),
            provider_spec=provider_spec, experiment=cast(Any, experiment),
            experiment_spec=experiment_spec, folds=cast(Any, folds),
            fold_spec=fold_spec, config=config, spec=spec,
            upstream_paths=upstream_paths, artifact_roots=roots,
        )


@pytest.mark.parametrize(
    ("relative_path", "mutator"),
    [
        (
            "worker-response.json",
            lambda raw: _canonical({**json.loads(raw), "fold": "fold_999"}),
        ),
        ("test.parquet", lambda raw: raw + b"drift"),
        ("coverage.parquet", lambda raw: _coverage_count_drift(raw)),
    ],
)
def test_feature_verifier_rejects_echo_bytes_and_coverage_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    mutator: Any,
) -> None:
    bundle = _build_feature_bundle(tmp_path, monkeypatch)
    root = cast(Path, bundle[-3])
    path = root / relative_path
    path.write_bytes(mutator(path.read_bytes()))
    with pytest.raises(ValueError):
        _verify(bundle)


def test_feature_receipt_requires_exact_input_and_output_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_feature_bundle(tmp_path, monkeypatch)
    (
        common, roots, release, snapshot, _, provider, _, _, _, experiment, _,
        folds, _, upstream_paths, root, _, _,
    ) = bundle
    decoy = common / "feature-decoy.txt"
    decoy.write_text("not a direct feature input", encoding="utf-8")
    bad_receipt = (
        common / "receipts" / "development-features" / "extra-input.json"
    )
    publish_stage_receipt(
        receipt_path=bad_receipt,
        stage="development-features",
        scope="EXPERIMENT",
        scope_key=experiment.manifest.experiment_key,
        artifact_roots=roots,
        inputs=[
            *_feature_inputs(
                release=release,
                snapshot=snapshot,
                provider=provider,
                experiment=experiment,
                folds=folds,
                upstream_paths=upstream_paths,
            ),
            ("root", decoy),
        ],
        outputs=_feature_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=bad_receipt)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _coverage_count_drift(raw: bytes) -> bytes:
    frame = pl.read_parquet(io.BytesIO(raw)).with_row_index("row_index")
    frame = frame.with_columns(
        pl.when(pl.col("row_index") == 0)
        .then(pl.col("n_feature_rows") + 1)
        .otherwise(pl.col("n_feature_rows"))
        .alias("n_feature_rows")
    ).drop("row_index")
    output = io.BytesIO()
    frame.write_parquet(
        output,
        compression="zstd",
        compression_level=3,
        statistics=True,
        row_group_size=65536,
        use_pyarrow=False,
    )
    return output.getvalue()


def test_feature_receipt_binds_all_declared_output_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _build_feature_bundle(tmp_path, monkeypatch)
    verified = _verify(bundle)
    root = cast(Path, bundle[-3])
    receipt = cast(Path, bundle[-2])
    receipt_payload = json.loads(receipt.read_bytes())
    expected = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for _, path in _feature_outputs(root)
    }
    observed = {
        Path(item["relative_path"]).name: item["sha256"]
        for item in receipt_payload["outputs"]
    }
    assert observed == expected
    assert verified.feature_receipt_sha256 == hashlib.sha256(
        receipt.read_bytes()
    ).hexdigest()


@pytest.mark.parametrize("mutation", ["unknown", "provider_uri"])
def test_artifact_verifier_rejects_request_response_schema_or_uri_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    bundle = _build_feature_bundle(tmp_path, monkeypatch)
    (
        common, roots, release, snapshot, _, provider, _, _, _, experiment,
        _, folds, _, upstream_paths, root, _, _,
    ) = bundle
    request_path = root / "request.json"
    response_path = root / "worker-response.json"
    request = json.loads(request_path.read_bytes())
    response = json.loads(response_path.read_bytes())
    if mutation == "unknown":
        request["injected_unknown"] = "x"
        response["injected_unknown"] = "x"
    else:
        request["provider_uri_sha256"] = "0" * 64
        response["provider_uri_sha256"] = "0" * 64
    request_path.write_bytes(_canonical(request))
    response_path.write_bytes(_canonical(response))
    receipt = common / "receipts" / "development-features" / f"drift-{mutation}.json"
    publish_stage_receipt(
        receipt_path=receipt, stage="development-features",
        scope="EXPERIMENT", scope_key=experiment.manifest.experiment_key,
        artifact_roots=roots,
        inputs=_feature_inputs(
            release=release, snapshot=snapshot, provider=provider,
            experiment=experiment, folds=folds, upstream_paths=upstream_paths,
        ),
        outputs=_feature_outputs(root),
    )
    with pytest.raises(ValueError):
        _verify(bundle, receipt=receipt)
