import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import quant.research.m3.labels as labels_module
from quant.research.m3.contracts import (
    LabelReconciliationReceiptPaths,
    LabelReconciliationSpec,
)
from quant.research.m3.development_example import (
    compute_development_label_reconciliation_key,
)
from quant.research.m3.labels import (
    M3LabelReconciliationError,
    reconcile_development_example_labels_with_qlib,
    reconcile_labels_with_qlib,
    verify_development_example_label_artifact,
    verify_development_example_label_reconciliation_artifact,
)
from quant.research.m3.provider_validation import (
    plan_development_example_provider_probe,
    validate_development_example_provider_public_api,
    verify_development_example_provider_validation_artifact,
)
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_label_artifact_test_support",
    Path(__file__).with_name("test_m3_label_artifact.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    (
        common, release, snapshot, provider, config, experiment_spec, experiment,
        label_spec, label_root, label_receipt, _,
    ) = _SUPPORT._build_and_receipt(tmp_path, monkeypatch, horizon=5)
    labels = verify_development_example_label_artifact(
        label_root=label_root, label_receipt_path=label_receipt,
        release=release, snapshot=snapshot, experiment=experiment, config=config,
        experiment_spec=experiment_spec, spec=label_spec,
        artifact_roots={"root": common},
    )
    # Rebuild the deterministic validation identity for the provider already in use.
    from quant.research.m3.contracts import ProviderValidationSpec
    from quant.research.m3.development_example import (
        compute_development_provider_validation_key,
    )

    validation_code = "development-example/g3b-validation-v1"
    validation_key = compute_development_provider_validation_key(
        example_id=snapshot.example_id,
        provider_key=provider.manifest.provider_key,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256=(
            provider.manifest.provider_runtime_fingerprint_sha256
        ),
        code_version=validation_code,
    )
    provider_spec = ProviderValidationSpec(
        provider_validation_key=validation_key,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        code_version=validation_code, qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=provider_spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _SUPPORT._SUPPORT._fake_worker(snapshot),
    )
    validation_root = common / "development-example-provider-validation-g3b"
    validation_root.mkdir()
    validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=provider_spec, python_executable=Path(sys.executable),
        output_root=validation_root, timeout_seconds=30.0,
    )
    snapshot_receipt = (
        common / "receipts" / "development-snapshot"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    provider_receipt = (
        common / "receipts" / "development-provider"
        / f"{provider.manifest.provider_key}.json"
    )
    validation_receipt = common / "development-provider-validation-g3b-receipt.json"
    publish_stage_receipt(
        receipt_path=validation_receipt, stage="development-provider-validation",
        scope="PROVIDER", scope_key=validation_key,
        artifact_roots={"root": common},
        inputs=_SUPPORT._SUPPORT._validation_inputs(
            common, snapshot, provider, provider_receipt
        ),
        outputs=[
            ("root", validation_root / "provider_validation.parquet"),
            ("root", validation_root / "provider_validation.json"),
        ],
    )
    provider_validation = verify_development_example_provider_validation_artifact(
        validation_root=validation_root, validation_receipt_path=validation_receipt,
        snapshot=snapshot, provider=provider, config=config, spec=provider_spec,
        artifact_roots={"root": common},
    )
    experiment_receipt = (
        common / "receipts" / "development-experiment-identity"
        / f"{experiment.manifest.experiment_key}.json"
    )
    receipts = LabelReconciliationReceiptPaths(
        snapshot_receipt_path=snapshot_receipt,
        provider_receipt_path=provider_receipt,
        provider_validation_receipt_path=validation_receipt,
        experiment_receipt_path=experiment_receipt,
        label_receipt_path=label_receipt,
    )
    validation = config.section("validation")["labels"]
    code_version = "development-example/g3b-reconciliation-v1"
    key = compute_development_label_reconciliation_key(
        example_id=snapshot.example_id,
        experiment_key=experiment.manifest.experiment_key,
        horizon=5,
        provider_validation_receipt_sha256=(
            provider_validation.validation_receipt_sha256
        ),
        label_manifest_sha256=labels.manifest_sha256,
        label_reconciliation_config_sha256=(
            config.label_reconciliation_config_sha256
        ),
        dependency_fingerprint_sha256=(
            experiment.manifest.dependency_fingerprint_sha256
        ),
        code_version=code_version,
    )
    spec = LabelReconciliationSpec(
        reconciliation_key=key,
        experiment_key=experiment.manifest.experiment_key,
        horizon_sessions=5,
        provider_validation_receipt_sha256=(
            provider_validation.validation_receipt_sha256
        ),
        label_manifest_sha256=labels.manifest_sha256,
        label_reconciliation_config_sha256=(
            config.label_reconciliation_config_sha256
        ),
        dependency_fingerprint_sha256=(
            experiment.manifest.dependency_fingerprint_sha256
        ),
        code_version=code_version, worker_protocol_version="m3-qlib-worker-v1",
        qlib_version="0.9.7",
        qlib_expression_atol=float(validation["qlib_expression_atol"]),
        benchmark_return_atol=float(validation["benchmark_return_atol"]),
        label_return_atol=float(validation["label_return_atol"]),
    )
    return (
        common, release, snapshot, provider, provider_validation, experiment,
        labels, config, receipts, spec,
    )


def _fake_reconciliation_worker(labels: Any, *, raw_delta: float = 0.0):
    values = {
        tuple(row[name] for name in labels_module._RECONCILIATION_KEY_COLUMNS): row
        for row in labels.labels.to_dicts()
    }

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["shell"] is False
        request_path = Path(argv[argv.index("--request") + 1])
        response_path = Path(argv[argv.index("--response") + 1])
        details_path = Path(argv[argv.index("--details") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        rows: list[dict[str, object]] = []
        for item in request["label_rows"]:
            key = (
                __import__("datetime").date.fromisoformat(item[0]),
                item[1], item[2], item[3], item[4],
            )
            label = values[key]
            rows.append({
                "as_of": key[0], "symbol": key[1], "benchmark": key[2],
                "horizon_sessions": key[3], "label_version": key[4],
                "return_start_date": label["return_start_date"],
                "return_end_date": label["return_end_date"],
                "qlib_expression_raw": float(label["raw_return"]) + raw_delta,
                "provider_direct_raw": float(label["raw_return"]) + raw_delta,
            })
        frame = pl.DataFrame(
            rows,
            schema=dict(zip(
                labels_module._RECONCILIATION_RAW_COLUMNS,
                labels_module._RECONCILIATION_RAW_DTYPES,
                strict=True,
            )),
        )
        frame.write_parquet(details_path)
        echo = {
            key: value for key, value in request.items()
            if key not in {"provider_uri", "label_rows"}
        }
        response = {
            **echo,
            "response_schema_version": "m3-label-reconciliation-worker-response-v1",
            "response_rows_sha256": hashlib.sha256(_canonical(
                labels_module._reconciliation_json_rows(rows)
            )).hexdigest(),
        }
        response_path.write_bytes(_canonical(response))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    return run


def test_development_reconciliation_closed_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, release, snapshot, provider, provider_validation, experiment,
        labels, config, receipts, spec,
    ) = _bundle(tmp_path, monkeypatch)
    calls = 0

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(labels_module.subprocess, "run", forbidden)
    bad_receipts = LabelReconciliationReceiptPaths(
        snapshot_receipt_path=receipts.snapshot_receipt_path,
        provider_receipt_path=receipts.provider_receipt_path,
        provider_validation_receipt_path=(
            receipts.provider_validation_receipt_path
        ),
        experiment_receipt_path=receipts.experiment_receipt_path,
        label_receipt_path=receipts.experiment_receipt_path,
    )
    rejected = common / "development-example-label-reconciliation-rejected"
    rejected.mkdir()
    artifact_roots = {
        "root": common, "EXTERNAL_QLIB": common.parent / "external_qlib",
    }
    with pytest.raises(M3LabelReconciliationError) as caught:
        reconcile_development_example_labels_with_qlib(
            release=release, snapshot=snapshot, experiment=experiment,
            provider=provider, provider_validation=provider_validation,
            labels=labels, config=config, spec=spec, receipt_paths=bad_receipts,
            artifact_roots=artifact_roots,
            python_executable=Path(sys.executable), output_root=rejected,
            timeout_seconds=30.0,
        )
    assert caught.value.code == "LABEL_RECONCILIATION_INPUT_INVALID"
    weak_label_receipt = common / "development-label-receipt-weak.json"
    release_paths = dict(release.artifact_paths)
    publish_stage_receipt(
        receipt_path=weak_label_receipt, stage="development-labels",
        scope="EXPERIMENT", scope_key=experiment.manifest.experiment_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", receipts.experiment_receipt_path),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", release.release.manifest_path),
            # Deliberately omit bar_1d.parquet while keeping all identities valid.
            ("root", release_paths["benchmark_bar_1d.parquet"]),
            ("root", release_paths["eligible_keys.parquet"]),
            ("root", receipts.snapshot_receipt_path),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
        ],
        outputs=[
            ("root", labels.root / "labels.parquet"),
            ("root", labels.root / "diagnostics.parquet"),
            ("root", labels.root / "label_manifest.json"),
        ],
    )
    weak_labels = replace(
        labels,
        label_receipt_sha256=hashlib.sha256(
            weak_label_receipt.read_bytes()
        ).hexdigest(),
    )
    weak_receipts = replace(receipts, label_receipt_path=weak_label_receipt)
    with pytest.raises(M3LabelReconciliationError):
        reconcile_development_example_labels_with_qlib(
            release=release, snapshot=snapshot, experiment=experiment,
            provider=provider, provider_validation=provider_validation,
            labels=weak_labels, config=config, spec=spec,
            receipt_paths=weak_receipts, artifact_roots=artifact_roots,
            python_executable=Path(sys.executable), output_root=rejected,
            timeout_seconds=30.0,
        )
    request_source = (
        common / "snapshot-requests"
        / f"{snapshot.request.snapshot_request_key}.json"
    )
    decoy_request = common / "decoy" / request_source.name
    decoy_request.parent.mkdir()
    decoy_request.write_bytes(request_source.read_bytes())
    weak_validation_receipt = common / "development-validation-receipt-weak.json"
    publish_stage_receipt(
        receipt_path=weak_validation_receipt,
        stage="development-provider-validation", scope="PROVIDER",
        scope_key=provider_validation.summary.provider_validation_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("root", provider.root / "provider_manifest.json"),
            *(("root", provider.root / item.relative_path) for item in provider.manifest.files),
            ("root", receipts.snapshot_receipt_path),
            ("root", receipts.provider_receipt_path),
            ("root", decoy_request),
        ],
        outputs=[
            ("root", provider_validation.root / "provider_validation.parquet"),
            ("root", provider_validation.root / "provider_validation.json"),
        ],
    )
    weak_validation_sha = hashlib.sha256(
        weak_validation_receipt.read_bytes()
    ).hexdigest()
    weak_provider_validation = replace(
        provider_validation, validation_receipt_sha256=weak_validation_sha
    )
    weak_validation_spec = replace(
        spec,
        provider_validation_receipt_sha256=weak_validation_sha,
        reconciliation_key=compute_development_label_reconciliation_key(
            example_id=snapshot.example_id,
            experiment_key=experiment.manifest.experiment_key, horizon=5,
            provider_validation_receipt_sha256=weak_validation_sha,
            label_manifest_sha256=labels.manifest_sha256,
            label_reconciliation_config_sha256=(
                config.label_reconciliation_config_sha256
            ),
            dependency_fingerprint_sha256=(
                experiment.manifest.dependency_fingerprint_sha256
            ),
            code_version=spec.code_version,
        ),
    )
    weak_validation_paths = replace(
        receipts,
        provider_validation_receipt_path=weak_validation_receipt,
    )
    with pytest.raises(M3LabelReconciliationError):
        reconcile_development_example_labels_with_qlib(
            release=release, snapshot=snapshot, experiment=experiment,
            provider=provider, provider_validation=weak_provider_validation,
            labels=labels, config=config, spec=weak_validation_spec,
            receipt_paths=weak_validation_paths, artifact_roots=artifact_roots,
            python_executable=Path(sys.executable), output_root=rejected,
            timeout_seconds=30.0,
        )
    with pytest.raises(M3LabelReconciliationError):
        reconcile_labels_with_qlib(
            release=release, snapshot=snapshot, experiment=experiment,
            provider=provider, provider_validation=provider_validation,
            labels=labels, config=config, spec=spec, receipt_paths=receipts,
            artifact_roots=artifact_roots,
            python_executable=Path(sys.executable), output_root=rejected,
            timeout_seconds=30.0,
        )
    for mixed_spec, mixed_validation in (
        (replace(spec, horizon_sessions=10), provider_validation),
        (replace(spec, experiment_key="0" * 64), provider_validation),
        (
            spec,
            replace(provider_validation, validation_receipt_sha256="0" * 64),
        ),
    ):
        with pytest.raises(M3LabelReconciliationError) as mixed:
            reconcile_development_example_labels_with_qlib(
                release=release, snapshot=snapshot, experiment=experiment,
                provider=provider, provider_validation=mixed_validation,
                labels=labels, config=config, spec=mixed_spec,
                receipt_paths=receipts, artifact_roots=artifact_roots,
                python_executable=Path(sys.executable), output_root=rejected,
                timeout_seconds=30.0,
            )
        assert mixed.value.code == "LABEL_RECONCILIATION_INPUT_INVALID"
    for field in (
        "provider_manifest_sha256",
        "provider_validation_config_sha256",
        "provider_runtime_fingerprint_sha256",
    ):
        drifted_validation = replace(
            provider_validation,
            summary=replace(provider_validation.summary, **{field: "0" * 64}),
        )
        with pytest.raises(M3LabelReconciliationError) as drifted:
            reconcile_development_example_labels_with_qlib(
                release=release, snapshot=snapshot, experiment=experiment,
                provider=provider, provider_validation=drifted_validation,
                labels=labels, config=config, spec=spec,
                receipt_paths=receipts, artifact_roots=artifact_roots,
                python_executable=Path(sys.executable), output_root=rejected,
                timeout_seconds=30.0,
            )
        assert drifted.value.code == "LABEL_RECONCILIATION_INPUT_INVALID"
    sys.modules["qlib.preloaded"] = types.ModuleType("qlib.preloaded")
    try:
        with pytest.raises(M3LabelReconciliationError) as preloaded:
            reconcile_development_example_labels_with_qlib(
                release=release, snapshot=snapshot, experiment=experiment,
                provider=provider, provider_validation=provider_validation,
                labels=labels, config=config, spec=spec, receipt_paths=receipts,
                artifact_roots=artifact_roots,
                python_executable=Path(sys.executable), output_root=rejected,
                timeout_seconds=30.0,
            )
        assert preloaded.value.code == "LABEL_RECONCILIATION_INPUT_INVALID"
    finally:
        sys.modules.pop("qlib.preloaded", None)
    assert calls == 0
    base_worker = _fake_reconciliation_worker(labels)
    b_worker = _fake_reconciliation_worker(labels, raw_delta=0.1)
    worker_paths: list[tuple[Path, Path, Path]] = []

    def tracked_worker(
        argv: list[str], **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        paths = tuple(
            Path(argv[argv.index(option) + 1])
            for option in ("--request", "--response", "--details")
        )
        worker_paths.append(paths)
        worker = base_worker if len(worker_paths) == 1 else b_worker
        return worker(argv, **kwargs)

    def exercise_worker_failure(name: str, worker: object) -> None:
        failure_root = common / f"development-example-label-{name}"
        failure_root.mkdir()
        monkeypatch.setattr(labels_module.subprocess, "run", worker)
        with pytest.raises(M3LabelReconciliationError) as failed:
            reconcile_development_example_labels_with_qlib(
                release=release, snapshot=snapshot, experiment=experiment,
                provider=provider, provider_validation=provider_validation,
                labels=labels, config=config, spec=spec, receipt_paths=receipts,
                artifact_roots=artifact_roots,
                python_executable=Path(sys.executable), output_root=failure_root,
                timeout_seconds=30.0,
            )
        assert failed.value.code == "LABEL_WORKER_FAILED"
        assert list(failure_root.iterdir()) == []

    def timeout_worker(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=30.0)

    def bad_json_worker(
        argv: list[str], **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        completed = base_worker(argv, **kwargs)
        Path(argv[argv.index("--response") + 1]).write_bytes(b"{")
        return completed

    def bad_parquet_worker(
        argv: list[str], **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        completed = base_worker(argv, **kwargs)
        Path(argv[argv.index("--details") + 1]).write_bytes(b"not parquet")
        return completed

    def echo_drift_worker(
        argv: list[str], **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        completed = base_worker(argv, **kwargs)
        path = Path(argv[argv.index("--response") + 1])
        response = json.loads(path.read_text(encoding="utf-8"))
        response["reconciliation_key"] = "0" * 64
        path.write_bytes(_canonical(response))
        return completed

    exercise_worker_failure("timeout", timeout_worker)
    exercise_worker_failure("bad-json", bad_json_worker)
    exercise_worker_failure("bad-parquet", bad_parquet_worker)
    exercise_worker_failure("echo-drift", echo_drift_worker)

    polluted_root = common / "development-example-label-parent-pollution"
    polluted_root.mkdir()

    def parent_polluting_worker(
        argv: list[str], **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        completed = base_worker(argv, **kwargs)
        sys.modules["qlib.polluted"] = types.ModuleType("qlib.polluted")
        return completed

    monkeypatch.setattr(
        labels_module.subprocess, "run", parent_polluting_worker
    )
    try:
        with pytest.raises(M3LabelReconciliationError) as polluted:
            reconcile_development_example_labels_with_qlib(
                release=release, snapshot=snapshot, experiment=experiment,
                provider=provider, provider_validation=provider_validation,
                labels=labels, config=config, spec=spec, receipt_paths=receipts,
                artifact_roots=artifact_roots,
                python_executable=Path(sys.executable), output_root=polluted_root,
                timeout_seconds=30.0,
            )
        assert polluted.value.code == "LABEL_RECONCILIATION_INPUT_INVALID"
        assert list(polluted_root.iterdir()) == []
    finally:
        sys.modules.pop("qlib.polluted", None)

    monkeypatch.setattr(labels_module.subprocess, "run", tracked_worker)
    output = common / "development-example-label-reconciliation"
    output.mkdir()
    labels_module._validate_reconciliation_inputs(
        release=release, snapshot=snapshot, experiment=experiment,
        provider=provider, provider_validation=provider_validation,
        labels=labels, config=config, spec=spec, receipt_paths=receipts,
        artifact_roots=artifact_roots, example_id=snapshot.example_id,
    )
    labels_module._label_worker_request(
        snapshot=snapshot, provider=provider, labels=labels, spec=spec
    )
    qlib_before = {
        name for name in sys.modules if name == "qlib" or name.startswith("qlib.")
    }
    result = reconcile_development_example_labels_with_qlib(
        release=release, snapshot=snapshot, experiment=experiment,
        provider=provider, provider_validation=provider_validation,
        labels=labels, config=config, spec=spec, receipt_paths=receipts,
        artifact_roots=artifact_roots, python_executable=Path(sys.executable),
        output_root=output, timeout_seconds=30.0,
    )
    second_output = common / "development-example-label-reconciliation-second"
    second_output.mkdir()
    second_result = reconcile_development_example_labels_with_qlib(
        release=release, snapshot=snapshot, experiment=experiment,
        provider=provider, provider_validation=provider_validation,
        labels=labels, config=config, spec=spec, receipt_paths=receipts,
        artifact_roots=artifact_roots, python_executable=Path(sys.executable),
        output_root=second_output, timeout_seconds=30.0,
    )
    # A then B uses new request/response/details paths, so worker-local caches
    # cannot be reused across reconciliation invocations.
    assert len(worker_paths) == 2
    assert set(worker_paths[0]).isdisjoint(worker_paths[1])
    assert result.summary.passed is True
    assert second_result.summary.passed is False
    assert second_result.summary.raw_label_max_abs_error > 0.09
    qlib_after = {
        name for name in sys.modules if name == "qlib" or name.startswith("qlib.")
    }
    assert qlib_after == qlib_before
    assert result.summary.row_count == labels.labels.height
    raw = result.details.select(*labels_module._RECONCILIATION_RAW_COLUMNS)
    expression_bad = raw.with_row_index().with_columns(
        pl.when(pl.col("index") == 0)
        .then(pl.col("qlib_expression_raw") + 0.1)
        .otherwise(pl.col("qlib_expression_raw"))
        .alias("qlib_expression_raw")
    ).drop("index")
    expression_result = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot, labels=labels, spec=spec,
        raw_details=expression_bad,
    )
    assert expression_result.summary.passed is False
    assert expression_result.summary.expression_direct_max_abs_error > 0.09
    direct_bad = raw.with_row_index().with_columns(
        pl.when(pl.col("index") == 0)
        .then(pl.col("provider_direct_raw") + 0.1)
        .otherwise(pl.col("provider_direct_raw"))
        .alias("provider_direct_raw")
    ).drop("index")
    direct_result = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot, labels=labels, spec=spec,
        raw_details=direct_bad,
    )
    assert direct_result.summary.passed is False
    assert direct_result.summary.expression_direct_max_abs_error > 0.09
    assert direct_result.summary.raw_label_max_abs_error > 0.09
    calendar = pl.read_parquet(snapshot.session_calendar_path).get_column(
        "date"
    ).to_list()
    benchmark_rows = pl.read_parquet(
        release_paths["benchmark_bar_1d.parquet"]
    ).select("trade_date", "open", "close").iter_rows()
    benchmark_prices = {
        day: (float(opened), float(closed))
        for day, opened, closed in benchmark_rows
    }
    calendar_index = {day: index for index, day in enumerate(calendar)}
    forged_rows = labels.labels.to_dicts()
    for row in forged_rows:
        as_of_index = calendar_index[row["as_of"]]
        wrong_entry = calendar[as_of_index + 2]
        exit_day = calendar[as_of_index + int(row["horizon_sessions"])]
        wrong_benchmark_return = (
            benchmark_prices[exit_day][1] / benchmark_prices[wrong_entry][1] - 1.0
        )
        # The minimal fixture intentionally has flat benchmark prices. Keep the
        # t+2 convention bug observable instead of letting that degeneracy hide it.
        if math.isclose(
            wrong_benchmark_return, float(row["benchmark_return"]),
            rel_tol=0.0, abs_tol=0.0,
        ):
            wrong_benchmark_return += 0.1
        row["benchmark_return"] = wrong_benchmark_return
        row["relative_return"] = (
            float(row["raw_return"]) - float(row["benchmark_return"])
        )
    forged_label_frame = pl.DataFrame(
        forged_rows, schema=labels.labels.schema
    ).select(labels.labels.columns)
    benchmark_result = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot,
        labels=replace(labels, labels=forged_label_frame), spec=spec,
        raw_details=raw,
    )
    assert benchmark_result.summary.passed is False
    assert benchmark_result.summary.benchmark_max_abs_error > 0.0
    quantized = raw.with_columns(
        pl.col("qlib_expression_raw").cast(pl.Float32).cast(pl.Float64),
        pl.col("provider_direct_raw").cast(pl.Float32).cast(pl.Float64),
    )
    quantized_result = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot, labels=labels, spec=spec,
        raw_details=quantized,
    )
    assert quantized_result.summary.passed is True
    missing = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot, labels=labels, spec=spec,
        raw_details=raw.slice(1),
    )
    duplicate = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot, labels=labels, spec=spec,
        raw_details=pl.concat([raw, raw.head(1)]),
    )
    assert missing.summary.missing_key_count == 1
    assert duplicate.summary.duplicate_key_count == 1
    extra_row = raw.head(1).with_columns(pl.lit("999999.SH").alias("symbol"))
    extra = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot, labels=labels, spec=spec,
        raw_details=pl.concat([raw, extra_row]),
    )
    assert extra.summary.extra_key_count == 1
    for non_finite in (math.nan, math.inf, -math.inf):
        polluted = raw.with_row_index().with_columns(
            pl.when(pl.col("index") == 0)
            .then(pl.lit(non_finite))
            .otherwise(pl.col("qlib_expression_raw"))
            .alias("qlib_expression_raw")
        ).drop("index")
        polluted_result = labels_module._result_from_raw_details(
            release=release, snapshot=snapshot, labels=labels, spec=spec,
            raw_details=polluted,
        )
        assert polluted_result.summary.passed is False
        assert polluted_result.summary.non_finite_count >= 1
    signed_zero = raw.with_row_index().with_columns(
        pl.when(pl.col("index") == 0)
        .then(pl.lit(-0.0))
        .otherwise(pl.col("qlib_expression_raw"))
        .alias("qlib_expression_raw")
    ).drop("index")
    signed_zero_result = labels_module._result_from_raw_details(
        release=release, snapshot=snapshot, labels=labels, spec=spec,
        raw_details=signed_zero,
    )
    assert signed_zero_result.summary.non_finite_count == 0
    assert labels_module._reconciliation_json_rows(
        signed_zero_result.details.to_dicts()
    )[0]["qlib_expression_raw"] == 0.0
    assert labels_module._reconciliation_json_rows([
        {"value": -0.0},
    ]) == [{"value": 0.0}]
    swapped = raw.with_row_index().with_columns(
        pl.when(pl.col("index") == 0)
        .then(pl.col("return_end_date"))
        .otherwise(pl.col("return_start_date"))
        .alias("return_start_date")
    ).drop("index")
    with pytest.raises(ValueError, match="return dates"):
        labels_module._result_from_raw_details(
            release=release, snapshot=snapshot, labels=labels, spec=spec,
            raw_details=swapped,
        )
    reconciliation_receipt = common / "development-label-reconciliation.json"
    paths = dict(release.artifact_paths)
    publish_stage_receipt(
        receipt_path=reconciliation_receipt,
        stage="development-label-reconciliation", scope="EXPERIMENT",
        scope_key=spec.reconciliation_key, artifact_roots={"root": common},
        inputs=[
            ("root", release.release.manifest_path),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
            ("root", provider.root / "provider_manifest.json"),
            *(("root", provider.root / item.relative_path) for item in provider.manifest.files),
            ("root", provider_validation.root / "provider_validation.parquet"),
            ("root", provider_validation.root / "provider_validation.json"),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", labels.root / "labels.parquet"),
            ("root", labels.root / "diagnostics.parquet"),
            ("root", labels.root / "label_manifest.json"),
            *(("root", path) for path in receipts.__dict__.values()),
        ],
        outputs=[
            ("root", output / "reconciliation.parquet"),
            ("root", output / "reconciliation.json"),
        ],
    )
    verified = verify_development_example_label_reconciliation_artifact(
        reconciliation_root=output,
        reconciliation_receipt_path=reconciliation_receipt,
        release=release, snapshot=snapshot, experiment=experiment,
        provider=provider, provider_validation=provider_validation, labels=labels,
        config=config, spec=spec, receipt_paths=receipts,
        artifact_roots=artifact_roots,
    )
    assert verified.formal_gate_eligible is False
    assert verified.summary == result.summary
    summary_path = output / "reconciliation.json"
    forged_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    forged_summary["benchmark_max_abs_error"] = 0.5
    summary_path.write_bytes(_canonical(forged_summary))
    resigned = common / "development-label-reconciliation-resigned.json"
    publish_stage_receipt(
        receipt_path=resigned, stage="development-label-reconciliation",
        scope="EXPERIMENT", scope_key=spec.reconciliation_key,
        artifact_roots={"root": common},
        inputs=[
            ("root", release.release.manifest_path),
            ("root", paths["benchmark_bar_1d.parquet"]),
            ("root", snapshot.root / "manifest.json"),
            ("root", snapshot.session_calendar_path),
            ("root", provider.root / "provider_manifest.json"),
            *(("root", provider.root / item.relative_path) for item in provider.manifest.files),
            ("root", provider_validation.root / "provider_validation.parquet"),
            ("root", provider_validation.root / "provider_validation.json"),
            ("root", experiment.root / "experiment_manifest.json"),
            ("root", labels.root / "labels.parquet"),
            ("root", labels.root / "diagnostics.parquet"),
            ("root", labels.root / "label_manifest.json"),
            *(("root", path) for path in receipts.__dict__.values()),
        ],
        outputs=[
            ("root", output / "reconciliation.parquet"),
            ("root", summary_path),
        ],
    )
    with pytest.raises(M3LabelReconciliationError) as forged:
        verify_development_example_label_reconciliation_artifact(
            reconciliation_root=output, reconciliation_receipt_path=resigned,
            release=release, snapshot=snapshot, experiment=experiment,
            provider=provider, provider_validation=provider_validation,
            labels=labels, config=config, spec=spec, receipt_paths=receipts,
            artifact_roots=artifact_roots,
        )
    assert forged.value.code == "LABEL_RECONCILIATION_MISMATCH"


@pytest.mark.parametrize("value", [True, 1, math.nan, math.inf, -1.0])
def test_reconciliation_spec_rejects_invalid_tolerances(value: object) -> None:
    kwargs = {
        "reconciliation_key": "1" * 64,
        "experiment_key": "2" * 64,
        "horizon_sessions": 5,
        "provider_validation_receipt_sha256": "3" * 64,
        "label_manifest_sha256": "4" * 64,
        "label_reconciliation_config_sha256": "5" * 64,
        "dependency_fingerprint_sha256": "6" * 64,
        "code_version": "v1", "worker_protocol_version": "m3-qlib-worker-v1",
        "qlib_version": "0.9.7", "qlib_expression_atol": value,
        "benchmark_return_atol": 0.0, "label_return_atol": 1.0,
    }
    with pytest.raises(ValueError):
        LabelReconciliationSpec(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("size,index", [(1, 0), (100, 98), (101, 99)])
def test_nearest_rank_p99(size: int, index: int) -> None:
    values = [float(value) for value in range(size)]
    assert labels_module._nearest_rank_p99(values) == values[index]


def test_public_error_observations_are_redacted(tmp_path: Path) -> None:
    secret = "TOKEN_SHOULD_NOT_ESCAPE"
    path = tmp_path / secret / "missing.json"
    try:
        labels_module.read_label_reconciliation_summary(path)
    except M3LabelReconciliationError as error:
        observations = (str(error), repr(error), error.args, error.__cause__, error.__context__)
        assert all(secret not in str(value) for value in observations)
        assert error.__cause__ is None
        assert error.__context__ is None
    else:
        raise AssertionError("invalid summary unexpectedly accepted")
