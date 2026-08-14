from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
import quant.research.m3.provider_validation as provider_validation_module

from quant.research.m3.contracts import ProviderBuildSpec, ProviderValidationSpec
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleProviderValidationArtifact,
    compute_development_provider_key,
    compute_development_provider_validation_key,
)
from quant.research.m3.fetch_qlib_tool import build_qlib_dump_tool_spec
from quant.research.m3.provider import (
    build_provider_runtime_fingerprint,
    materialize_development_example_qlib_provider,
    verify_development_example_provider_artifact,
)
from quant.research.m3.provider_validation import (
    M3ProviderValidationError,
    plan_development_example_provider_probe,
    plan_provider_probe,
    read_provider_validation_summary,
    validate_development_example_provider_public_api,
    verify_development_example_provider_validation_artifact,
    _verify_passing_summary,
)
from quant.research.m3.qlib_adapter import (
    _date_only,
    _normalise_ranges,
    _require_feature_frame_contract,
)
from quant.research.m3.run_state import publish_stage_receipt

_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_provider_materialization_test_support",
    Path(__file__).with_name("test_m3_provider_materialization.py"),
)
assert _SUPPORT_SPEC is not None and _SUPPORT_SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SUPPORT_SPEC)
_SUPPORT_SPEC.loader.exec_module(_SUPPORT)
_materialized = _SUPPORT._materialized
_snapshot = _SUPPORT._snapshot

_FIELDS = ("open", "high", "low", "close", "vwap", "volume", "factor")


def _verified_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    common, snapshot, config, provider_spec, tool, result = _materialized(
        tmp_path, monkeypatch
    )
    receipt_path = (
        common / "receipts" / "development-provider" / f"{provider_spec.provider_key}.json"
    )
    receipt_path.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=receipt_path,
        stage="development-provider",
        scope="PROVIDER",
        scope_key=provider_spec.provider_key,
        artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            (
                "root",
                common / "snapshot-requests"
                / f"{snapshot.request.snapshot_request_key}.json",
            ),
            (
                "root",
                common / "receipts" / "development-snapshot"
                / f"{snapshot.request.snapshot_request_key}.json",
            ),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            ("EXTERNAL_QLIB", tool),
        ],
        outputs=[
            ("root", result.root / "provider_manifest.json"),
            *(("root", result.root / item.relative_path) for item in result.manifest.files),
        ],
    )
    provider = verify_development_example_provider_artifact(
        provider_root=result.root,
        provider_receipt_path=receipt_path,
        snapshot=snapshot,
        config=config,
        artifact_roots={"root": common, "EXTERNAL_QLIB": tool.parent},
    )
    code_version = "development-example/g2c-v1"
    validation_key = compute_development_provider_validation_key(
        example_id=snapshot.example_id,
        provider_key=provider.manifest.provider_key,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256=provider.manifest.provider_runtime_fingerprint_sha256,
        code_version=code_version,
    )
    spec = ProviderValidationSpec(
        provider_validation_key=validation_key,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        code_version=code_version,
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    return common, snapshot, provider, config, spec, receipt_path


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _worker_rows_sha(rows: list[dict[str, object]]) -> str:
    json_rows = []
    for row in rows:
        clean: dict[str, object] = {}
        for key, value in row.items():
            if type(value) is dt.date:
                clean[key] = value.isoformat()
            elif isinstance(value, float) and np.isnan(value):
                clean[key] = {"__float__": "nan"}
            elif value == np.inf:
                clean[key] = {"__float__": "+inf"}
            elif value == -np.inf:
                clean[key] = {"__float__": "-inf"}
            else:
                clean[key] = value
        json_rows.append(clean)
    return hashlib.sha256(_canonical(tuple(json_rows))).hexdigest()


def _fake_worker(
    snapshot: Any, *, gap_value: float | None = None,
    emitted_non_finite: float | None = None, bad_dtype: bool = False,
):
    staging: dict[tuple[str, dt.date], tuple[float, ...]] = {}
    ranges: list[list[str]] = []
    for path in snapshot.staging_paths:
        frame = pl.read_parquet(path).sort("date")
        symbol = frame.item(0, "symbol")
        code, market = symbol.split(".")
        dates = frame.get_column("date").to_list()
        ranges.append([f"{market}{code}", dates[0].isoformat(), dates[-1].isoformat()])
        for row in frame.select("date", *_FIELDS).iter_rows():
            staging[(symbol, row[0])] = tuple(float(value) for value in row[1:])
    calendar = [
        day.isoformat() for day in
        pl.read_parquet(snapshot.session_calendar_path).get_column("date").to_list()
    ]

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["shell"] is False
        request_path = Path(argv[argv.index("--request") + 1])
        response_path = Path(argv[argv.index("--response") + 1])
        details_path = Path(argv[argv.index("--details") + 1])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        rows: list[dict[str, object]] = []
        for kind, name in (("EMITTED", "selected_rows"), ("GAP", "selected_gap_rows")):
            for symbol, date_text in request[name]:
                day = dt.date.fromisoformat(date_text)
                values = staging.get((symbol, day))
                for index, field in enumerate(_FIELDS):
                    actual: float | None
                    if values is not None:
                        actual = (
                            emitted_non_finite
                            if emitted_non_finite is not None and not rows
                            else float(np.float32(values[index]))
                        )
                    elif gap_value is not None:
                        actual = gap_value
                    else:
                        actual = None
                    rows.append({
                        "sample_kind": kind, "symbol": symbol, "date": day,
                        "field": field,
                        "api_row_present": values is not None or gap_value is not None,
                        "actual": actual,
                    })
        rows.sort(key=lambda row: (
            row["sample_kind"], row["symbol"], row["date"], row["field"]
        ))
        details = pl.DataFrame(rows).select(
            "sample_kind", "symbol", pl.col("date").cast(pl.Date), "field",
            "api_row_present", pl.col("actual").cast(pl.Float64),
        )
        if bad_dtype:
            details = details.with_columns(pl.col("api_row_present").cast(pl.Int64))
        details.write_parquet(details_path)
        echo = {
            key: request[key] for key in (
                "schema_version", "worker_protocol_version",
                "provider_validation_key", "provider_key", "snapshot_id",
                "qlib_version", "provider_uri_sha256", "fields",
                "selected_rows", "selected_gap_rows",
            )
        }
        response = {
            **echo,
            "response_schema_version": "m3-qlib-worker-response-v1",
            "api_calendar": calendar,
            "api_instrument_ranges": sorted(ranges),
            "response_rows_sha256": _worker_rows_sha(rows),
        }
        response_path.write_bytes(_canonical(response))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    return run


def _validation_inputs(
    common: Path, snapshot: Any, provider: Any, provider_receipt: Path,
) -> list[tuple[str, Path]]:
    return [
        ("root", snapshot.root / "manifest.json"),
        (
            "root", common / "snapshot-requests"
            / f"{snapshot.request.snapshot_request_key}.json",
        ),
        (
            "root", common / "receipts" / "development-snapshot"
            / f"{snapshot.request.snapshot_request_key}.json",
        ),
        ("root", snapshot.session_calendar_path),
        *(("root", path) for path in snapshot.staging_paths),
        ("root", provider.root / "provider_manifest.json"),
        *(("root", provider.root / item.relative_path) for item in provider.manifest.files),
        ("root", provider_receipt),
    ]


def _mutating_worker(snapshot: Any, mutation: str):
    base = _fake_worker(snapshot)

    def run(argv: list[str], **kwargs: object) -> Any:
        result = base(argv, **kwargs)
        response_path = Path(argv[argv.index("--response") + 1])
        details_path = Path(argv[argv.index("--details") + 1])
        response = json.loads(response_path.read_text(encoding="utf-8"))
        details = pl.read_parquet(details_path)
        rows = details.to_dicts()
        if mutation == "missing":
            rows = rows[1:]
        elif mutation == "duplicate":
            rows.append(dict(rows[0]))
        elif mutation == "extra":
            extra = dict(rows[0])
            extra["field"] = "unexpected"
            rows.append(extra)
        elif mutation == "calendar":
            response["api_calendar"] = response["api_calendar"][:-1]
        elif mutation == "instrument":
            response["api_instrument_ranges"] = response[
                "api_instrument_ranges"
            ][:-1]
        else:
            raise AssertionError(mutation)
        if mutation in {"missing", "duplicate", "extra"}:
            rows.sort(key=lambda row: (
                row["sample_kind"], row["symbol"], row["date"], row["field"]
            ))
            pl.DataFrame(rows, schema=details.schema).write_parquet(details_path)
            response["response_rows_sha256"] = _worker_rows_sha(rows)
        response_path.write_bytes(_canonical(response))
        return result

    return run


def _built_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    *, worker: Any | None = None,
):
    common, snapshot, provider, config, spec, provider_receipt = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        worker or _fake_worker(snapshot),
    )
    output = common / "development-example-provider-validation-built"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(sys.executable), output_root=output,
        timeout_seconds=30.0,
    )
    return common, snapshot, provider, config, spec, provider_receipt, output, result


def test_development_probe_is_deterministic_3x20_with_separate_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, snapshot, provider, config, spec, _ = _verified_provider(tmp_path, monkeypatch)
    first = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    second = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    assert first == second
    assert len(first.selected_rows) == 60
    assert len(first.selected_gap_rows) == 1
    assert {symbol for symbol, _ in first.selected_rows} == {
        "000001.SZ", "000002.SZ", "600000.SH",
    }
    by_symbol = {
        symbol: [day for selected, day in first.selected_rows if selected == symbol]
        for symbol in {selected for selected, _ in first.selected_rows}
    }
    assert all(len(days) == 20 for days in by_symbol.values())


def test_development_public_api_closed_loop_and_nominal_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, provider_receipt = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run", _fake_worker(snapshot)
    )
    output = common / "development-example-provider-validation"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(__import__("sys").executable),
        output_root=output, timeout_seconds=30.0,
    )
    assert result.summary.passed is True, ",".join(
        f"{name}={getattr(result.summary, name)}"
        for name in (
            "missing_emitted_cell_count", "extra_cell_count",
            "duplicate_cell_count", "non_finite_emitted_cell_count",
            "emitted_mismatch_cell_count", "gap_finite_cell_count",
            "calendar_mismatch_count", "instrument_mismatch_count",
        )
    )
    assert result.summary.emitted_key_count == 60
    assert result.summary.emitted_comparison_count == 420
    assert result.summary.gap_key_count == 1
    assert result.summary.gap_comparison_count == 7
    assert set(path.name for path in output.iterdir()) == {
        "provider_validation.json", "provider_validation.parquet",
    }
    assert read_provider_validation_summary(
        output / "provider_validation.json"
    ) == result.summary
    receipt = common / "development-provider-validation-receipt.json"
    publish_stage_receipt(
        receipt_path=receipt,
        stage="development-provider-validation",
        scope="PROVIDER",
        scope_key=spec.provider_validation_key,
        artifact_roots={"root": common},
        inputs=_validation_inputs(common, snapshot, provider, provider_receipt),
        outputs=[
            ("root", output / "provider_validation.parquet"),
            ("root", output / "provider_validation.json"),
        ],
    )
    verified = verify_development_example_provider_validation_artifact(
        validation_root=output, validation_receipt_path=receipt,
        snapshot=snapshot, provider=provider, config=config, spec=spec,
        artifact_roots={"root": common},
    )
    assert isinstance(verified, VerifiedDevelopmentExampleProviderValidationArtifact)
    assert verified.release_kind == "development_example"
    assert verified.formal_gate_eligible is False

    with pytest.raises(M3ProviderValidationError) as exc:
        plan_provider_probe(
            snapshot=snapshot,  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            config=config, spec=spec,
        )
    assert exc.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"


def test_finite_gap_is_persisted_as_failed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _fake_worker(snapshot, gap_value=123.0),
    )
    output = common / "development-example-provider-validation-failed"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(__import__("sys").executable),
        output_root=output, timeout_seconds=30.0,
    )
    assert result.summary.passed is False
    assert result.summary.gap_finite_cell_count == 7


@pytest.mark.parametrize("gap_value", [np.inf, -np.inf])
def test_infinite_gap_is_not_treated_as_nan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gap_value: float,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _fake_worker(snapshot, gap_value=gap_value),
    )
    output = common / "development-example-provider-validation-infinite-gap"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(sys.executable), output_root=output,
        timeout_seconds=30.0,
    )
    assert result.summary.passed is False
    assert result.summary.gap_finite_cell_count == 7
    assert set(result.details.filter(pl.col("sample_kind") == "GAP").get_column("status")) == {
        "GAP_NON_NAN"
    }


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_emitted_non_finite_is_counted_separately_from_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: float,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _fake_worker(snapshot, emitted_non_finite=value),
    )
    output = common / "development-example-provider-validation-non-finite"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(sys.executable), output_root=output,
        timeout_seconds=30.0,
    )
    assert result.summary.passed is False
    assert result.summary.missing_emitted_cell_count == 0
    assert result.summary.non_finite_emitted_cell_count == 1


def test_worker_details_dtype_drift_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _fake_worker(snapshot, bad_dtype=True),
    )
    output = common / "development-example-provider-validation-bad-dtype"
    output.mkdir()
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_WORKER_FAILED"
    assert not any(output.iterdir())


def test_explicit_nan_gap_is_legal_and_distinct_from_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _fake_worker(snapshot, gap_value=np.nan),
    )
    output = common / "development-example-provider-validation-gap-nan"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(sys.executable), output_root=output,
        timeout_seconds=30.0,
    )
    assert result.summary.passed is True
    assert set(result.details.filter(pl.col("sample_kind") == "GAP").get_column("status")) == {
        "GAP_NAN"
    }


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra"])
def test_worker_cell_closure_drift_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _mutating_worker(snapshot, mutation),
    )
    output = common / f"development-example-provider-validation-{mutation}"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(sys.executable), output_root=output,
        timeout_seconds=30.0,
    )
    assert result.summary.passed is False
    field = {
        "missing": "missing_emitted_cell_count",
        "duplicate": "duplicate_cell_count",
        "extra": "extra_cell_count",
    }[mutation]
    assert getattr(result.summary, field) == 1


@pytest.mark.parametrize("mutation", ["calendar", "instrument"])
def test_worker_api_summary_drift_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        _mutating_worker(snapshot, mutation),
    )
    output = common / f"development-example-provider-validation-{mutation}-drift"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(sys.executable), output_root=output,
        timeout_seconds=30.0,
    )
    assert result.summary.passed is False
    assert getattr(result.summary, f"{mutation}_mismatch_count") == 1


def test_summary_reader_sanitizes_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_bytes(b"{")
    with pytest.raises(M3ProviderValidationError) as exc:
        read_provider_validation_summary(path)
    assert exc.value.code == "PROVIDER_VALIDATION_MISMATCH"


def test_hash_tie_uses_symbol_as_deterministic_tiebreaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, snapshot, provider, config, spec, _ = _verified_provider(tmp_path, monkeypatch)
    original_rows = provider_validation_module._read_staging_rows(snapshot)
    extended = dict(original_rows)
    extended["000003.SZ"] = original_rows["000002.SZ"]
    original_hash = provider_validation_module._hash_array

    def tied_hash(value: object) -> str:
        if isinstance(value, list) and value and value[0] == "provider-symbol-v1":
            return "0" * 64
        return original_hash(value)

    monkeypatch.setattr(
        provider_validation_module, "_read_staging_rows", lambda _: extended
    )
    monkeypatch.setattr(provider_validation_module, "_hash_array", tied_hash)
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    assert {symbol for symbol, _ in plan.selected_rows} == {
        "000001.SZ", "000002.SZ", "600000.SH",
    }


def test_probe_rejects_missing_market_and_underfilled_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, snapshot, provider, config, spec, _ = _verified_provider(tmp_path, monkeypatch)
    original_rows = provider_validation_module._read_staging_rows(snapshot)
    invalid = {
        "000001.SZ": original_rows["000001.SZ"][:19],
        "000002.SZ": original_rows["000002.SZ"],
    }
    monkeypatch.setattr(
        provider_validation_module, "_read_staging_rows", lambda _: invalid
    )
    with pytest.raises(M3ProviderValidationError) as exc:
        plan_development_example_provider_probe(
            snapshot=snapshot, provider=provider, config=config, spec=spec
        )
    assert exc.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"


def test_worker_nonzero_and_bad_parquet_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    output = common / "development-example-provider-validation-worker-failure"
    output.mkdir()
    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run",
        lambda argv, **_: subprocess.CompletedProcess(argv, 9, b"", b"secret"),
    )
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_WORKER_FAILED"
    assert "secret" not in str(exc.value)

    base = _fake_worker(snapshot)

    def bad_parquet(argv: list[str], **kwargs: object) -> Any:
        result = base(argv, **kwargs)
        Path(argv[argv.index("--details") + 1]).write_bytes(b"not parquet")
        return result

    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run", bad_parquet
    )
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_WORKER_FAILED"


def test_worker_date_contract_rejects_timezone_and_non_midnight() -> None:
    pandas = pytest.importorskip("pandas")
    with pytest.raises(ValueError, match="naive midnight"):
        _date_only(pandas.Timestamp("2026-01-05", tz="Asia/Shanghai"))
    with pytest.raises(ValueError, match="naive midnight"):
        _date_only(pandas.Timestamp("2026-01-05 12:00:00"))


def test_verifier_recomputes_summary_and_rejects_wholesale_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, snapshot, provider, config, spec, provider_receipt, output, _,
    ) = _built_validation(tmp_path, monkeypatch)
    summary_path = output / "provider_validation.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["emitted_key_count"] = 999
    payload["probe_plan_sha256"] = "f" * 64
    payload["read_audit_sha256"] = "e" * 64
    summary_path.write_bytes(_canonical(payload))
    receipt = common / "development-provider-validation-wholesale-receipt.json"
    publish_stage_receipt(
        receipt_path=receipt, stage="development-provider-validation",
        scope="PROVIDER", scope_key=spec.provider_validation_key,
        artifact_roots={"root": common},
        inputs=_validation_inputs(common, snapshot, provider, provider_receipt),
        outputs=[
            ("root", output / "provider_validation.parquet"),
            ("root", summary_path),
        ],
    )
    with pytest.raises(M3ProviderValidationError) as exc:
        verify_development_example_provider_validation_artifact(
            validation_root=output, validation_receipt_path=receipt,
            snapshot=snapshot, provider=provider, config=config, spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "PROVIDER_VALIDATION_MISMATCH"


def test_verifier_rejects_same_input_bytes_from_decoy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, snapshot, provider, config, spec, provider_receipt, output, _,
    ) = _built_validation(tmp_path, monkeypatch)
    decoy = common / "decoy-provider-manifest.json"
    shutil.copyfile(provider.root / "provider_manifest.json", decoy)
    inputs = _validation_inputs(common, snapshot, provider, provider_receipt)
    inputs[inputs.index(("root", provider.root / "provider_manifest.json"))] = (
        "root", decoy,
    )
    receipt = common / "development-provider-validation-decoy-receipt.json"
    publish_stage_receipt(
        receipt_path=receipt, stage="development-provider-validation",
        scope="PROVIDER", scope_key=spec.provider_validation_key,
        artifact_roots={"root": common}, inputs=inputs,
        outputs=[
            ("root", output / "provider_validation.parquet"),
            ("root", output / "provider_validation.json"),
        ],
    )
    with pytest.raises(M3ProviderValidationError):
        verify_development_example_provider_validation_artifact(
            validation_root=output, validation_receipt_path=receipt,
            snapshot=snapshot, provider=provider, config=config, spec=spec,
            artifact_roots={"root": common},
        )


def test_verifier_recomputes_sampling_instead_of_trusting_detail_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _, snapshot, provider, config, spec, _, _, result,
    ) = _built_validation(tmp_path, monkeypatch)
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    symbol = "000002.SZ"
    selected = {day for selected_symbol, day in plan.selected_rows if selected_symbol == symbol}
    staging_path = next(path for path in snapshot.staging_paths if path.name == "sz000002.parquet")
    staging = pl.read_parquet(staging_path).sort("date")
    replacement_day = next(day for day in staging.get_column("date") if day not in selected)
    replaced_day = next(day for day in sorted(selected)[1:-1])
    replacement = staging.filter(pl.col("date") == replacement_day).row(0, named=True)
    changed_rows = result.details.to_dicts()
    for row in changed_rows:
        if (
            row["sample_kind"] == "EMITTED"
            and row["symbol"] == symbol
            and row["date"] == replaced_day
        ):
            field = row["field"]
            value = np.float32(replacement[field])
            bits = int(value.view(np.uint32))
            row["date"] = replacement_day
            row["expected"] = float(value)
            row["actual"] = float(value)
            row["expected_f32_bits"] = bits
            row["actual_f32_bits"] = bits
    details = pl.DataFrame(
        changed_rows, schema=result.details.schema
    ).sort("sample_kind", "symbol", "date", "field")
    with pytest.raises(ValueError, match="sampling policy drift"):
        _verify_passing_summary(
            details=details, summary=result.summary, snapshot=snapshot,
            provider=provider, config=config, spec=spec,
            example_id=snapshot.example_id,
        )


def test_verifier_recomputes_validation_key_from_trusted_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, snapshot, provider, config, spec, provider_receipt, output, _,
    ) = _built_validation(tmp_path, monkeypatch)
    summary_path = output / "provider_validation.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    forged_key = "d" * 64
    payload["provider_validation_key"] = forged_key
    summary_path.write_bytes(_canonical(payload))
    receipt = common / "development-provider-validation-forged-key-receipt.json"
    publish_stage_receipt(
        receipt_path=receipt, stage="development-provider-validation",
        scope="PROVIDER", scope_key=forged_key,
        artifact_roots={"root": common},
        inputs=_validation_inputs(common, snapshot, provider, provider_receipt),
        outputs=[
            ("root", output / "provider_validation.parquet"),
            ("root", summary_path),
        ],
    )
    with pytest.raises(M3ProviderValidationError) as exc:
        verify_development_example_provider_validation_artifact(
            validation_root=output, validation_receipt_path=receipt,
            snapshot=snapshot, provider=provider, config=config, spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "PROVIDER_VALIDATION_MISMATCH"


def test_instrument_api_rejects_multiple_segments() -> None:
    with pytest.raises(ValueError, match="exactly one segment"):
        _normalise_ranges({
            "SH600000": [
                (dt.date(2026, 1, 5), dt.date(2026, 1, 9)),
                (dt.date(2026, 1, 12), dt.date(2026, 2, 2)),
            ]
        })


def test_worker_timeout_uses_frozen_sanitized_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )

    def timeout(argv: list[str], **_: object) -> Any:
        raise subprocess.TimeoutExpired(argv, 30.0)

    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run", timeout
    )
    output = common / "development-example-provider-validation-timeout"
    output.mkdir()
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_WORKER_FAILED"
    assert not any(output.iterdir())


def test_worker_identity_echo_drift_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    base = _fake_worker(snapshot)

    def drift(argv: list[str], **kwargs: object) -> Any:
        result = base(argv, **kwargs)
        response_path = Path(argv[argv.index("--response") + 1])
        response = json.loads(response_path.read_text(encoding="utf-8"))
        response["provider_key"] = "0" * 64
        response_path.write_bytes(_canonical(response))
        return result

    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run", drift
    )
    output = common / "development-example-provider-validation-echo-drift"
    output.mkdir()
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_WORKER_FAILED"
    assert not any(output.iterdir())


def test_parent_preloaded_qlib_fails_before_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    monkeypatch.setitem(sys.modules, "qlib", object())
    called = False

    def forbidden(*_: object, **__: object) -> Any:
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run", forbidden
    )
    output = common / "development-example-provider-validation-parent-import"
    output.mkdir()
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"
    assert called is False
    assert not any(output.iterdir())


def test_validation_artifact_rejects_hardlinked_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        common, snapshot, provider, config, spec, _, output, _,
    ) = _built_validation(tmp_path, monkeypatch)
    summary = output / "provider_validation.json"
    backing = common / "summary-backing.json"
    summary.rename(backing)
    os.link(backing, summary)
    with pytest.raises(M3ProviderValidationError) as exc:
        verify_development_example_provider_validation_artifact(
            validation_root=output,
            validation_receipt_path=common / "unused-receipt.json",
            snapshot=snapshot, provider=provider, config=config, spec=spec,
            artifact_roots={"root": common},
        )
    assert exc.value.code == "PROVIDER_VALIDATION_MISMATCH"


def test_validation_output_rejects_symlinked_parent_before_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    real_parent = tmp_path / "real-validation-parent"
    real_parent.mkdir()
    real_output = real_parent / "development-example-validation"
    real_output.mkdir()
    alias = tmp_path / "development-example-validation-alias"
    try:
        alias.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit directory symlink creation")
    called = False

    def forbidden(*_: object, **__: object) -> Any:
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(
        "quant.research.m3.provider_validation.subprocess.run", forbidden
    )
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable),
            output_root=alias / real_output.name, timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"
    assert called is False
    assert not any(real_output.iterdir())


def test_wrong_development_key_fails_before_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    bad = replace(spec, provider_validation_key="0" * 64)
    output = common / "development-example-provider-validation-bad"
    output.mkdir()
    with pytest.raises(M3ProviderValidationError) as exc:
        plan_development_example_provider_probe(
            snapshot=snapshot, provider=provider, config=config, spec=bad
        )
    assert exc.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"
    assert not any(output.iterdir())


def test_signed_zero_uses_float32_bits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    original = provider_validation_module._read_staging_rows(snapshot)
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    target_symbol, target_day = plan.selected_rows[0]
    patched: dict[str, tuple[tuple[dt.date, tuple[float, ...]], ...]] = {}
    for symbol, rows in original.items():
        patched[symbol] = tuple(
            (
                day,
                (0.0, *values[1:])
                if symbol == target_symbol and day == target_day else values,
            )
            for day, values in rows
        )
    monkeypatch.setattr(
        provider_validation_module, "_read_staging_rows", lambda _: patched
    )
    monkeypatch.setattr(
        provider_validation_module.subprocess, "run",
        _fake_worker(snapshot, emitted_non_finite=-0.0),
    )
    output = common / "development-example-provider-validation-signed-zero"
    output.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=spec, python_executable=Path(sys.executable), output_root=output,
        timeout_seconds=30.0,
    )
    assert result.summary.emitted_mismatch_cell_count == 1
    assert result.summary.passed is False


@pytest.mark.parametrize("mutation", ["bad-json", "field-order"])
def test_worker_response_json_and_field_order_are_strict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    common, snapshot, provider, config, spec, _ = _verified_provider(
        tmp_path, monkeypatch
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec
    )
    nominal = _fake_worker(snapshot)

    def mutated(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        completed = nominal(argv, **kwargs)
        response_path = Path(argv[argv.index("--response") + 1])
        if mutation == "bad-json":
            response_path.write_bytes(b"{")
        else:
            payload = json.loads(response_path.read_text(encoding="utf-8"))
            payload["fields"] = list(reversed(payload["fields"]))
            response_path.write_bytes(_canonical(payload))
        return completed

    monkeypatch.setattr(provider_validation_module.subprocess, "run", mutated)
    output = common / f"development-example-provider-validation-{mutation}"
    output.mkdir()
    with pytest.raises(M3ProviderValidationError) as exc:
        validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
    assert exc.value.code == "PROVIDER_WORKER_FAILED"
    assert not any(output.iterdir())


@pytest.mark.parametrize(
    "names", [("datetime", "instrument"), ("symbol", "datetime")],
)
def test_qlib_feature_multiindex_names_and_order_are_exact(names: tuple[str, str]) -> None:
    pandas = pytest.importorskip("pandas")
    index = pandas.MultiIndex.from_tuples(
        [("SZ000001", pandas.Timestamp("2026-01-05"))], names=names
    )
    fields = [f"${field}" for field in _FIELDS]
    frame = pandas.DataFrame([[1.0] * len(fields)], index=index, columns=fields)
    with pytest.raises(ValueError, match="Qlib feature MultiIndex invalid"):
        _require_feature_frame_contract(frame, fields)


def test_two_validation_identities_use_fresh_worker_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_a = tmp_path / "provider-a"
    root_b = tmp_path / "provider-b"
    root_a.mkdir()
    root_b.mkdir()
    a = _verified_provider(root_a, monkeypatch)
    original_provider_spec = _SUPPORT._provider_spec

    def provider_spec_b(snapshot: Any, config: Any) -> ProviderBuildSpec:
        base = original_provider_spec(snapshot, config)
        code_version = "development-example/g2b-provider-b"
        provider_key = compute_development_provider_key(
            example_id=snapshot.example_id,
            snapshot_id=snapshot.manifest.snapshot_id,
            snapshot_manifest_sha256=snapshot.manifest_sha256,
            provider_config_sha256=config.provider_config_sha256,
            dump_tool_sha256=base.dump_tool.sha256,
            qlib_version=base.qlib_version,
            provider_runtime_fingerprint_sha256=base.runtime_fingerprint.sha256,
            code_version=code_version,
        )
        return replace(base, provider_key=provider_key, code_version=code_version)

    monkeypatch.setattr(_SUPPORT, "_provider_spec", provider_spec_b)
    b = _verified_provider(root_b, monkeypatch)
    assert a[2].manifest.provider_key != b[2].manifest.provider_key
    assert a[2].qlib_dir.resolve() != b[2].qlib_dir.resolve()
    assert not any(name == "qlib" or name.startswith("qlib.") for name in sys.modules)
    seen: list[tuple[str, str, Path, Path, Path]] = []
    for suffix, bundle in (("a", a), ("b", b)):
        common, snapshot, provider, config, spec, _ = bundle
        nominal = _fake_worker(snapshot)

        def capture(
            argv: list[str], *, _nominal: Any = nominal, **kwargs: object,
        ) -> subprocess.CompletedProcess[bytes]:
            assert argv[1:3] == ["-m", "quant.research.m3.qlib_adapter"]
            request_path = Path(argv[argv.index("--request") + 1])
            response_path = Path(argv[argv.index("--response") + 1])
            details_path = Path(argv[argv.index("--details") + 1])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            seen.append((
                request["provider_validation_key"], request["provider_uri"],
                request_path, response_path, details_path,
            ))
            return _nominal(argv, **kwargs)

        monkeypatch.setattr(provider_validation_module.subprocess, "run", capture)
        plan = plan_development_example_provider_probe(
            snapshot=snapshot, provider=provider, config=config, spec=spec
        )
        output = common / f"development-example-provider-validation-fresh-{suffix}"
        output.mkdir()
        result = validate_development_example_provider_public_api(
            snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
            spec=spec, python_executable=Path(sys.executable), output_root=output,
            timeout_seconds=30.0,
        )
        assert result.summary.passed is True
    assert [item[0] for item in seen] == [a[4].provider_validation_key, b[4].provider_validation_key]
    assert [Path(item[1]) for item in seen] == [
        a[2].qlib_dir.resolve(), b[2].qlib_dir.resolve(),
    ]
    assert set(seen[0][2:]).isdisjoint(seen[1][2:])
    assert not any(name == "qlib" or name.startswith("qlib.") for name in sys.modules)


@pytest.mark.parametrize("target", ["snapshot", "provider"])
def test_input_tree_rejects_unlisted_empty_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    _, snapshot, provider, config, spec, _ = _verified_provider(tmp_path, monkeypatch)
    root = snapshot.root if target == "snapshot" else provider.qlib_dir
    (root / "UNDECLARED_EMPTY").mkdir()
    with pytest.raises(M3ProviderValidationError) as exc:
        plan_development_example_provider_probe(
            snapshot=snapshot, provider=provider, config=config, spec=spec
        )
    assert exc.value.code == "PROVIDER_VALIDATION_INPUT_INVALID"


@pytest.mark.skipif(
    os.environ.get("M3_RUN_REAL_QLIB") != "1",
    reason="explicit py312 real-Qlib public-API smoke only",
)
def test_real_pinned_qlib_public_api_validation(tmp_path: Path) -> None:
    common = tmp_path / "artifacts"
    common.mkdir()
    snapshot, config, _ = _snapshot(common)
    runtime = build_provider_runtime_fingerprint()
    tool_spec = build_qlib_dump_tool_spec(config)
    provider_code = "development-example/g2c-real-provider-v1"
    provider_key = compute_development_provider_key(
        example_id=snapshot.example_id,
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool_sha256=tool_spec.sha256,
        qlib_version=tool_spec.qlib_version,
        provider_runtime_fingerprint_sha256=runtime.sha256,
        code_version=provider_code,
    )
    provider_spec = ProviderBuildSpec(
        snapshot_id=snapshot.manifest.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        provider_key=provider_key,
        provider_config_sha256=config.provider_config_sha256,
        dump_tool=tool_spec,
        qlib_version="0.9.7",
        code_version=provider_code,
        runtime_fingerprint=runtime,
        fields=_FIELDS,
        frequency="day",
        dump_contract_version="m3-qlib-dump-all-v1",
    )
    provider_root = common / "development-example-provider-real"
    provider_root.mkdir()
    provider_result = materialize_development_example_qlib_provider(
        snapshot=snapshot,
        qlib_dump_script=Path("data/external/qlib/v0.9.7/dump_bin.py").resolve(),
        python_executable=Path(sys.executable).resolve(),
        config=config,
        spec=provider_spec,
        output_root=provider_root,
        timeout_seconds=120.0,
    )
    provider_receipt = (
        common / "receipts" / "development-provider" / f"{provider_key}.json"
    )
    provider_receipt.parent.mkdir(parents=True)
    publish_stage_receipt(
        receipt_path=provider_receipt,
        stage="development-provider",
        scope="PROVIDER",
        scope_key=provider_key,
        artifact_roots={
            "root": common,
            "EXTERNAL_QLIB": Path("data/external/qlib/v0.9.7").resolve(),
        },
        inputs=[
            ("root", snapshot.root / "manifest.json"),
            (
                "root", common / "snapshot-requests"
                / f"{snapshot.request.snapshot_request_key}.json",
            ),
            (
                "root", common / "receipts" / "development-snapshot"
                / f"{snapshot.request.snapshot_request_key}.json",
            ),
            ("root", snapshot.session_calendar_path),
            *(("root", path) for path in snapshot.staging_paths),
            (
                "EXTERNAL_QLIB",
                Path("data/external/qlib/v0.9.7/dump_bin.py").resolve(),
            ),
        ],
        outputs=[
            ("root", provider_root / "provider_manifest.json"),
            *(("root", provider_root / item.relative_path) for item in provider_result.manifest.files),
        ],
    )
    provider = verify_development_example_provider_artifact(
        provider_root=provider_root,
        provider_receipt_path=provider_receipt,
        snapshot=snapshot,
        config=config,
        artifact_roots={
            "root": common,
            "EXTERNAL_QLIB": Path("data/external/qlib/v0.9.7").resolve(),
        },
    )
    validation_code = "development-example/g2c-real-validation-v1"
    validation_key = compute_development_provider_validation_key(
        example_id=snapshot.example_id,
        provider_key=provider.manifest.provider_key,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256=provider.manifest.provider_runtime_fingerprint_sha256,
        code_version=validation_code,
    )
    validation_spec = ProviderValidationSpec(
        provider_validation_key=validation_key,
        provider_validation_config_sha256=config.provider_validation_config_sha256,
        code_version=validation_code,
        qlib_version="0.9.7",
        sampling_policy_version="provider_market_stratified_hash_first_last_v1",
        worker_protocol_version="m3-qlib-worker-v1",
    )
    plan = plan_development_example_provider_probe(
        snapshot=snapshot, provider=provider, config=config, spec=validation_spec
    )
    validation_root = common / "development-example-provider-validation-real"
    validation_root.mkdir()
    result = validate_development_example_provider_public_api(
        snapshot=snapshot, provider=provider, probe_plan=plan, config=config,
        spec=validation_spec, python_executable=Path(sys.executable).resolve(),
        output_root=validation_root, timeout_seconds=120.0,
    )
    assert result.summary.passed is True
    assert result.summary.emitted_comparison_count == 420
    assert result.summary.gap_comparison_count == 7
