"""Fresh-process Qlib public-API validation for an immutable M3 provider."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal, ParamSpec, TypeVar, cast

import numpy as np
import polars as pl

from quant.research.m3.config import LoadedM3Config
from quant.research.m3.contracts import (
    ProviderProbePlan,
    ProviderValidationResult,
    ProviderValidationSpec,
    ProviderValidationSummaryV1,
    VerifiedProviderArtifact,
    VerifiedProviderValidationArtifact,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleProviderArtifact,
    VerifiedDevelopmentExampleProviderValidationArtifact,
    VerifiedDevelopmentExampleSnapshotArtifact,
    compute_development_provider_validation_key,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    compute_provider_validation_key,
    verify_stage_receipt,
)

_FIELDS = ("open", "high", "low", "close", "vwap", "volume", "factor")
_POLICY: Literal["provider_market_stratified_hash_first_last_v1"] = (
    "provider_market_stratified_hash_first_last_v1"
)
_PROTOCOL = "m3-qlib-worker-v1"
_PLAN_SCHEMA: Literal["m3-provider-probe-v1"] = "m3-provider-probe-v1"
_SUMMARY_SCHEMA: Literal["m3-provider-validation-v1"] = (
    "m3-provider-validation-v1"
)
_DETAIL_COLUMNS = (
    "sample_kind", "symbol", "date", "field", "api_row_present", "expected",
    "actual", "expected_f32_bits", "actual_f32_bits", "status",
)
_RAW_COLUMNS = ("sample_kind", "symbol", "date", "field", "api_row_present", "actual")
_RAW_DTYPES = (pl.Utf8, pl.Utf8, pl.Date, pl.Utf8, pl.Boolean, pl.Float64)
_DETAIL_DTYPES = (
    pl.Utf8, pl.Utf8, pl.Date, pl.Utf8, pl.Boolean, pl.Float64, pl.Float64,
    pl.UInt32, pl.UInt32, pl.Utf8,
)
_P = ParamSpec("_P")
_R = TypeVar("_R")


class M3ProviderValidationError(ValueError):
    """Sanitized stable failure at the G2C boundary."""

    _CODES = {
        "PROVIDER_VALIDATION_INPUT_INVALID",
        "PROVIDER_WORKER_FAILED",
        "PROVIDER_VALIDATION_MISMATCH",
    }

    def __init__(self, code: str) -> None:
        if code not in self._CODES:
            raise ValueError("unknown provider validation error")
        self.code = code
        super().__init__(code)


def _boundary(code: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            try:
                return function(*args, **kwargs)
            except M3ProviderValidationError:
                raise
            except (
                TypeError, ValueError, OSError, subprocess.SubprocessError,
                pl.exceptions.PolarsError,
            ):
                raise M3ProviderValidationError(code) from None

        return wrapped

    return decorate


@_boundary("PROVIDER_VALIDATION_INPUT_INVALID")
def plan_provider_probe(
    *, snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
) -> ProviderProbePlan:
    """Build the fixed 3-symbol by 20-date formal probe plan."""
    if type(snapshot) is not VerifiedSnapshotArtifact or type(provider) is not VerifiedProviderArtifact:
        raise ValueError("formal validation requires formal artifacts")
    return _plan_probe(snapshot=snapshot, provider=provider, config=config, spec=spec, example_id=None)


@_boundary("PROVIDER_VALIDATION_INPUT_INVALID")
def plan_development_example_provider_probe(
    *, snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
) -> ProviderProbePlan:
    """Build the same probe in the isolated development-example domain."""
    if (
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(provider) is not VerifiedDevelopmentExampleProviderArtifact
        or snapshot.example_id != provider.example_id
    ):
        raise ValueError("development validation requires matching development artifacts")
    return _plan_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec,
        example_id=snapshot.example_id,
    )


def _plan_probe(
    *, snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec, example_id: str | None,
) -> ProviderProbePlan:
    _validate_identities(snapshot, provider, config, spec, example_id)
    rows_by_symbol = _read_staging_rows(snapshot)
    candidates = tuple(sorted(
        symbol for symbol, rows in rows_by_symbol.items() if len(rows) >= 20
    ))
    sh = tuple(symbol for symbol in candidates if symbol.endswith(".SH"))
    sz = tuple(symbol for symbol in candidates if symbol.endswith(".SZ"))
    if not sh or not sz or len(candidates) < 3:
        raise ValueError("provider probe market/candidate closure invalid")
    def rank(symbol: str) -> tuple[str, str]:
        return (
            _hash_array([
                "provider-symbol-v1", snapshot.manifest.snapshot_id,
                provider.manifest.provider_key, symbol,
            ]),
            symbol,
        )
    first_sh = min(sh, key=rank)
    first_sz = min(sz, key=rank)
    remaining = tuple(symbol for symbol in candidates if symbol not in {first_sh, first_sz})
    selected_symbols = tuple(sorted((first_sh, first_sz, min(remaining, key=rank))))
    selected: list[tuple[str, dt.date]] = []
    gaps: list[tuple[str, dt.date]] = []
    calendar = tuple(
        pl.read_parquet(snapshot.session_calendar_path).get_column("date").to_list()
    )
    for symbol in selected_symbols:
        dates = tuple(row[0] for row in rows_by_symbol[symbol])
        internal = dates[1:-1]
        ranked_internal = sorted(internal, key=lambda day: (
            _hash_array(["provider-date-v1", provider.manifest.provider_key, symbol, day.isoformat()]),
            day,
        ))
        chosen = tuple(sorted((dates[0], dates[-1], *ranked_internal[:18])))
        if len(chosen) != 20:
            raise ValueError("provider probe emitted count invalid")
        selected.extend((symbol, day) for day in chosen)
        emitted = set(dates)
        span = tuple(day for day in calendar if dates[0] <= day <= dates[-1])
        ranked_gaps = sorted((day for day in span if day not in emitted), key=lambda day: (
            _hash_array(["provider-gap-date-v1", provider.manifest.provider_key, symbol, day.isoformat()]),
            day,
        ))
        gaps.extend((symbol, day) for day in ranked_gaps[:5])
    selected_rows = tuple(sorted(selected))
    selected_gap_rows = tuple(sorted(gaps))
    candidate_keys = tuple(
        (symbol, day.isoformat())
        for symbol in candidates for day, _ in rows_by_symbol[symbol]
    )
    return ProviderProbePlan(
        schema_version=_PLAN_SCHEMA,
        provider_validation_key=spec.provider_validation_key,
        provider_key=provider.manifest.provider_key,
        snapshot_id=snapshot.manifest.snapshot_id,
        sampling_policy_version=_POLICY,
        candidate_keys_sha256=_hash_array(candidate_keys),
        selected_rows=selected_rows,
        selected_gap_rows=selected_gap_rows,
        emitted_keys_sha256=_hash_array(tuple((symbol, day.isoformat()) for symbol, day in selected_rows)),
        gap_keys_sha256=_hash_array(tuple((symbol, day.isoformat()) for symbol, day in selected_gap_rows)),
    )


@_boundary("PROVIDER_VALIDATION_INPUT_INVALID")
def validate_provider_public_api(
    *, snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    probe_plan: ProviderProbePlan, config: LoadedM3Config,
    spec: ProviderValidationSpec, python_executable: Path, output_root: Path,
    timeout_seconds: float,
) -> ProviderValidationResult:
    if type(snapshot) is not VerifiedSnapshotArtifact or type(provider) is not VerifiedProviderArtifact:
        raise ValueError("formal validation requires formal artifacts")
    return _validate_public_api(
        snapshot=snapshot, provider=provider, probe_plan=probe_plan, config=config,
        spec=spec, python_executable=python_executable, output_root=output_root,
        timeout_seconds=timeout_seconds, example_id=None,
    )


@_boundary("PROVIDER_VALIDATION_INPUT_INVALID")
def validate_development_example_provider_public_api(
    *, snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    probe_plan: ProviderProbePlan, config: LoadedM3Config,
    spec: ProviderValidationSpec, python_executable: Path, output_root: Path,
    timeout_seconds: float,
) -> ProviderValidationResult:
    if (
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(provider) is not VerifiedDevelopmentExampleProviderArtifact
        or snapshot.example_id != provider.example_id
    ):
        raise ValueError("development validation requires matching artifacts")
    name = output_root.name.lower()
    if "development" not in name or "example" not in name:
        raise ValueError("development validation root must be labelled")
    return _validate_public_api(
        snapshot=snapshot, provider=provider, probe_plan=probe_plan, config=config,
        spec=spec, python_executable=python_executable, output_root=output_root,
        timeout_seconds=timeout_seconds, example_id=snapshot.example_id,
    )


def _validate_public_api(
    *, snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    probe_plan: ProviderProbePlan, config: LoadedM3Config,
    spec: ProviderValidationSpec, python_executable: Path, output_root: Path,
    timeout_seconds: float, example_id: str | None,
) -> ProviderValidationResult:
    _validate_identities(snapshot, provider, config, spec, example_id)
    if probe_plan != _plan_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec,
        example_id=example_id,
    ):
        raise ValueError("provider probe plan drift")
    if any(name == "qlib" or name.startswith("qlib.") for name in sys.modules):
        raise ValueError("parent imported qlib")
    if not python_executable.is_file() or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("provider worker runtime invalid")
    _require_real_directory(output_root)
    if any(output_root.iterdir()):
        raise ValueError("provider validation output must be an empty directory")
    request = _worker_request(snapshot, provider, probe_plan, spec)
    with tempfile.TemporaryDirectory(prefix="m3-provider-validation-") as temp_name:
        temp = Path(temp_name)
        request_path = temp / "request.json"
        response_path = temp / "response.json"
        raw_details_path = temp / "details.parquet"
        request_path.write_bytes(_canonical_bytes(request))
        argv = [
            str(python_executable), "-m", "quant.research.m3.qlib_adapter",
            "validate-provider", "--request", str(request_path),
            "--response", str(response_path), "--details", str(raw_details_path),
        ]
        try:
            completed = subprocess.run(
                argv, shell=False, check=False, capture_output=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise M3ProviderValidationError("PROVIDER_WORKER_FAILED") from None
        if completed.returncode != 0 or not response_path.is_file() or not raw_details_path.is_file():
            raise M3ProviderValidationError("PROVIDER_WORKER_FAILED")
        try:
            response = _strict_json(_read_regular(response_path))
            raw_details = pl.read_parquet(_read_regular_bytes_path(raw_details_path))
            result = _rebuild_result(
                snapshot=snapshot, provider=provider, plan=probe_plan, spec=spec,
                request=request, response=response, raw_details=raw_details,
            )
        except (TypeError, ValueError, OSError, pl.exceptions.PolarsError):
            raise M3ProviderValidationError("PROVIDER_WORKER_FAILED") from None
    if any(name == "qlib" or name.startswith("qlib.") for name in sys.modules):
        raise ValueError("worker polluted parent imports")
    _write_exclusive(output_root / "provider_validation.parquet", _details_bytes(result.details))
    _write_exclusive(output_root / "provider_validation.json", _canonical_bytes(asdict(result.summary)))
    return result


def _rebuild_result(
    *, snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    plan: ProviderProbePlan, spec: ProviderValidationSpec,
    request: dict[str, object], response: dict[str, object], raw_details: pl.DataFrame,
) -> ProviderValidationResult:
    expected_echo = {
        key: request[key] for key in (
            "schema_version", "worker_protocol_version", "provider_validation_key",
            "provider_key", "snapshot_id", "qlib_version", "provider_uri_sha256",
            "fields", "selected_rows", "selected_gap_rows",
        )
    }
    expected_response_keys = {
        *expected_echo, "response_schema_version", "api_calendar",
        "api_instrument_ranges", "response_rows_sha256",
    }
    if set(response) != expected_response_keys or response.get("response_schema_version") != "m3-qlib-worker-response-v1":
        raise ValueError("worker response schema invalid")
    if any(response.get(key) != value for key, value in expected_echo.items()):
        raise ValueError("worker identity echo mismatch")
    if raw_details.columns != list(_RAW_COLUMNS) or tuple(raw_details.dtypes) != _RAW_DTYPES:
        raise ValueError("worker details schema invalid")
    raw_rows = raw_details.to_dicts()
    if response["response_rows_sha256"] != _hash_array(_json_rows(raw_rows)):
        raise ValueError("worker row digest mismatch")
    planned = {
        (kind, symbol, day.isoformat(), field)
        for kind, rows in (("EMITTED", plan.selected_rows), ("GAP", plan.selected_gap_rows))
        for symbol, day in rows for field in _FIELDS
    }
    counts = Counter(
        (row["sample_kind"], row["symbol"], _date_iso(row["date"]), row["field"])
        for row in raw_rows
    )
    duplicate_count = sum(value - 1 for value in counts.values() if value > 1)
    extra_count = sum(value for key, value in counts.items() if key not in planned)
    first_rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw_row in raw_rows:
        key = (
            raw_row["sample_kind"], raw_row["symbol"],
            _date_iso(raw_row["date"]), raw_row["field"],
        )
        first_rows.setdefault(key, raw_row)
    staging = _read_staging_rows(snapshot)
    staging_values = {
        (symbol, day): values for symbol, rows in staging.items() for day, values in rows
    }
    detail_rows: list[dict[str, object]] = []
    errors = Counter[str]()
    for kind, symbol, date_iso, field in sorted(planned):
        day = dt.date.fromisoformat(date_iso)
        matched_row = first_rows.get((kind, symbol, date_iso, field))
        present = (
            bool(matched_row["api_row_present"])
            if matched_row is not None else False
        )
        actual_obj = matched_row["actual"] if matched_row is not None else None
        actual = float(actual_obj) if actual_obj is not None else None
        expected: float | None = None
        expected_bits: int | None = None
        actual_bits: int | None = None
        if kind == "EMITTED":
            expected_value = np.float32(staging_values[(symbol, day)][_FIELDS.index(field)])
            expected = float(expected_value)
            expected_bits = int(expected_value.view(np.uint32))
            if matched_row is None or not present or actual is None:
                status = "MISSING_EMITTED"
                errors["missing"] += 1
            elif not math.isfinite(actual):
                status = "NON_FINITE_EMITTED"
                errors["non_finite"] += 1
            else:
                actual_value = np.float32(actual)
                actual_bits = int(actual_value.view(np.uint32))
                if actual_bits != expected_bits:
                    status = "EMITTED_MISMATCH"
                    errors["mismatch"] += 1
                else:
                    status = "MATCHED"
        elif actual is not None and not math.isnan(actual):
            actual_bits = (
                int(np.float32(actual).view(np.uint32))
                if math.isfinite(actual) else None
            )
            status = "GAP_FILLED" if math.isfinite(actual) else "GAP_NON_NAN"
            errors["gap"] += 1
        elif present:
            status = "GAP_NAN"
        else:
            status = "GAP_ABSENT"
        detail_rows.append({
            "sample_kind": kind, "symbol": symbol, "date": day, "field": field,
            "api_row_present": present, "expected": expected,
            "actual": actual if actual is not None and math.isfinite(actual) else None,
            "expected_f32_bits": expected_bits, "actual_f32_bits": actual_bits,
            "status": status,
        })
    details = pl.DataFrame(detail_rows).select(*_DETAIL_COLUMNS).cast(dict(
        zip(_DETAIL_COLUMNS, _DETAIL_DTYPES, strict=True)
    )).sort("sample_kind", "symbol", "date", "field")
    api_calendar = _parse_api_calendar(response["api_calendar"])
    expected_calendar = tuple(
        day.isoformat() for day in
        pl.read_parquet(snapshot.session_calendar_path).get_column("date").to_list()
    )
    api_ranges = _parse_api_ranges(response["api_instrument_ranges"])
    expected_ranges = tuple(sorted(
        (_to_qlib_symbol(symbol).upper(), rows[0][0].isoformat(), rows[-1][0].isoformat())
        for symbol, rows in sorted(staging.items())
    ))
    calendar_mismatch = 0 if api_calendar == expected_calendar else 1
    instrument_mismatch = 0 if api_ranges == expected_ranges else 1
    details_sha = _hash_array(_json_rows(details.to_dicts()))
    plan_sha = _hash_array(_plan_payload(plan))
    provider_uri_sha = cast(str, request["provider_uri_sha256"])
    read_audit_sha = _hash_array({
        "request_keys": tuple(sorted(request)), "fields": _FIELDS,
        "api_calendar_sha256": _hash_array(api_calendar),
        "api_instrument_ranges_sha256": _hash_array(api_ranges),
        "response_rows_sha256": response["response_rows_sha256"],
    })
    passed = (
        errors.total() == 0 and extra_count == 0 and duplicate_count == 0
        and calendar_mismatch == 0 and instrument_mismatch == 0
        and len(plan.selected_rows) == 60 and len(plan.selected_rows) * 7 == 420
        and details.height == len(planned)
    )
    summary = ProviderValidationSummaryV1(
        schema_version=_SUMMARY_SCHEMA,
        provider_validation_key=spec.provider_validation_key,
        provider_key=provider.manifest.provider_key,
        provider_receipt_sha256=provider.provider_receipt_sha256,
        provider_manifest_sha256=provider.manifest_sha256,
        snapshot_id=snapshot.manifest.snapshot_id,
        provider_validation_config_sha256=spec.provider_validation_config_sha256,
        provider_runtime_fingerprint_sha256=provider.manifest.provider_runtime_fingerprint_sha256,
        qlib_version=spec.qlib_version,
        sampling_policy_version=spec.sampling_policy_version,
        worker_protocol_version=spec.worker_protocol_version,
        probe_plan_sha256=plan_sha,
        candidate_keys_sha256=plan.candidate_keys_sha256,
        emitted_keys_sha256=plan.emitted_keys_sha256,
        gap_keys_sha256=plan.gap_keys_sha256,
        emitted_key_count=len(plan.selected_rows),
        gap_key_count=len(plan.selected_gap_rows),
        emitted_comparison_count=len(plan.selected_rows) * len(_FIELDS),
        gap_comparison_count=len(plan.selected_gap_rows) * len(_FIELDS),
        details_sha256=details_sha,
        details_row_count=details.height,
        api_calendar_sha256=_hash_array(api_calendar),
        api_instrument_ranges_sha256=_hash_array(api_ranges),
        missing_emitted_cell_count=errors["missing"],
        extra_cell_count=extra_count,
        duplicate_cell_count=duplicate_count,
        non_finite_emitted_cell_count=errors["non_finite"],
        emitted_mismatch_cell_count=errors["mismatch"],
        gap_finite_cell_count=errors["gap"],
        calendar_mismatch_count=calendar_mismatch,
        instrument_mismatch_count=instrument_mismatch,
        provider_uri_sha256=provider_uri_sha,
        parent_import_audit_sha256=_hash_array(()),
        read_audit_sha256=read_audit_sha,
        passed=passed,
    )
    return ProviderValidationResult(details=details, summary=summary)


@_boundary("PROVIDER_VALIDATION_MISMATCH")
def read_provider_validation_summary(path: Path) -> ProviderValidationSummaryV1:
    """Strictly reconstruct a canonical G2C summary."""
    return _read_provider_validation_summary(path)


def _read_provider_validation_summary(path: Path) -> ProviderValidationSummaryV1:
    raw = _read_regular(path)
    value = _strict_json(raw)
    names = tuple(ProviderValidationSummaryV1.__dataclass_fields__)
    if set(value) != set(names):
        raise M3ProviderValidationError("PROVIDER_VALIDATION_MISMATCH")
    try:
        summary = ProviderValidationSummaryV1(**value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise M3ProviderValidationError("PROVIDER_VALIDATION_MISMATCH") from None
    if _canonical_bytes(asdict(summary)) != raw:
        raise ValueError("provider validation summary noncanonical")
    return summary


@_boundary("PROVIDER_VALIDATION_MISMATCH")
def verify_provider_validation_artifact(
    *, validation_root: Path, validation_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact, provider: VerifiedProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedProviderValidationArtifact:
    if type(snapshot) is not VerifiedSnapshotArtifact or type(provider) is not VerifiedProviderArtifact:
        raise ValueError("formal verifier requires formal artifacts")
    details, summary, summary_sha, receipt_sha = _verify_validation(
        validation_root=validation_root, validation_receipt_path=validation_receipt_path,
        snapshot=snapshot, provider=provider, config=config,
        spec=spec, artifact_roots=artifact_roots,
        expected_stage="provider-validation",
    )
    return VerifiedProviderValidationArtifact(
        root=validation_root.resolve(strict=True), details=details, summary=summary,
        summary_sha256=summary_sha, validation_receipt_sha256=receipt_sha,
    )


@_boundary("PROVIDER_VALIDATION_MISMATCH")
def verify_development_example_provider_validation_artifact(
    *, validation_root: Path, validation_receipt_path: Path,
    snapshot: VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleProviderValidationArtifact:
    if (
        type(snapshot) is not VerifiedDevelopmentExampleSnapshotArtifact
        or type(provider) is not VerifiedDevelopmentExampleProviderArtifact
        or snapshot.example_id != provider.example_id
    ):
        raise ValueError("development verifier requires matching artifacts")
    name = validation_root.name.lower()
    if "development" not in name or "example" not in name:
        raise ValueError("development validation root must be labelled")
    details, summary, summary_sha, receipt_sha = _verify_validation(
        validation_root=validation_root, validation_receipt_path=validation_receipt_path,
        snapshot=snapshot, provider=provider, config=config,
        spec=spec, artifact_roots=artifact_roots,
        expected_stage="development-provider-validation",
    )
    return VerifiedDevelopmentExampleProviderValidationArtifact(
        release_kind="development_example", formal_gate_eligible=False,
        example_id=snapshot.example_id, root=validation_root.resolve(strict=True),
        details=details, summary=summary, summary_sha256=summary_sha,
        validation_receipt_sha256=receipt_sha,
    )


def _verify_validation(
    *, validation_root: Path, validation_receipt_path: Path,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec,
    artifact_roots: Mapping[str, Path], expected_stage: str,
) -> tuple[pl.DataFrame, ProviderValidationSummaryV1, str, str]:
    example_id = (
        snapshot.example_id
        if type(snapshot) is VerifiedDevelopmentExampleSnapshotArtifact else None
    )
    _validate_identities(snapshot, provider, config, spec, example_id)
    _require_real_directory(validation_root)
    if set(path.name for path in validation_root.iterdir()) != {
        "provider_validation.parquet", "provider_validation.json",
    }:
        raise ValueError("provider validation tree closure invalid")
    summary_path = validation_root / "provider_validation.json"
    details_path = validation_root / "provider_validation.parquet"
    summary = _read_provider_validation_summary(summary_path)
    details = pl.read_parquet(_read_regular_bytes_path(details_path))
    _verify_passing_summary(
        details=details, summary=summary, snapshot=snapshot, provider=provider,
        config=config, spec=spec, example_id=example_id,
    )
    receipt = verify_stage_receipt(
        receipt_path=validation_receipt_path, artifact_roots=artifact_roots
    )
    if receipt is None or receipt.stage != expected_stage or receipt.scope != "PROVIDER" or receipt.scope_key != summary.provider_validation_key:
        raise ValueError("provider validation receipt mismatch")
    expected_outputs = tuple(sorted((
        _digest_for_path(details_path, artifact_roots),
        _digest_for_path(summary_path, artifact_roots),
    ), key=lambda item: (item.root_alias, item.relative_path)))
    if receipt.outputs != expected_outputs:
        raise ValueError("provider validation receipt outputs mismatch")
    direct_paths = (
        snapshot.root / "manifest.json", snapshot.session_calendar_path,
        *snapshot.staging_paths, provider.root / "provider_manifest.json",
        *(provider.root / item.relative_path for item in provider.manifest.files),
    )
    direct_digests = tuple(_digest_for_path(path, artifact_roots) for path in direct_paths)
    required = Counter((
        *(item.sha256 for item in direct_digests), snapshot.request_sha256,
        snapshot.snapshot_receipt_sha256, provider.provider_receipt_sha256,
    ))
    if Counter(item.sha256 for item in receipt.inputs) != required or not set(direct_digests).issubset(set(receipt.inputs)):
        raise ValueError("provider validation receipt inputs mismatch")
    snapshot_manifest_digest = _digest_for_path(
        snapshot.root / "manifest.json", artifact_roots
    )
    provider_manifest_digest = _digest_for_path(
        provider.root / "provider_manifest.json", artifact_roots
    )
    snapshot_prefix = _snapshot_stage_prefix(
        snapshot_manifest_digest.relative_path
    )
    provider_prefix = _provider_stage_prefix(provider_manifest_digest.relative_path)
    snapshot_stage = (
        "development-snapshot"
        if type(snapshot) is VerifiedDevelopmentExampleSnapshotArtifact else "snapshot"
    )
    provider_stage = (
        "development-provider"
        if type(provider) is VerifiedDevelopmentExampleProviderArtifact else "provider"
    )
    _require_receipt_input(
        receipt.inputs, sha256=snapshot.request_sha256,
        root_alias=snapshot_manifest_digest.root_alias,
        relative_path=PurePosixPath(
            *snapshot_prefix, "snapshot-requests",
            f"{snapshot.request.snapshot_request_key}.json",
        ).as_posix(),
    )
    _require_receipt_input(
        receipt.inputs, sha256=snapshot.snapshot_receipt_sha256,
        root_alias=snapshot_manifest_digest.root_alias,
        relative_path=PurePosixPath(
            *snapshot_prefix, "receipts", snapshot_stage,
            f"{snapshot.request.snapshot_request_key}.json",
        ).as_posix(),
    )
    _require_receipt_input(
        receipt.inputs, sha256=provider.provider_receipt_sha256,
        root_alias=provider_manifest_digest.root_alias,
        relative_path=PurePosixPath(
            *provider_prefix, "receipts", provider_stage,
            f"{provider.manifest.provider_key}.json",
        ).as_posix(),
    )
    return (
        details, summary, hashlib.sha256(_read_regular(summary_path)).hexdigest(),
        hashlib.sha256(_read_regular(validation_receipt_path)).hexdigest(),
    )


def _verify_passing_summary(
    *, details: pl.DataFrame, summary: ProviderValidationSummaryV1,
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec, example_id: str | None,
) -> None:
    if details.columns != list(_DETAIL_COLUMNS) or tuple(details.dtypes) != _DETAIL_DTYPES:
        raise ValueError("provider validation details schema invalid")
    if not details.equals(details.sort("sample_kind", "symbol", "date", "field")):
        raise ValueError("provider validation details order invalid")
    expected_identity = {
        "provider_key": provider.manifest.provider_key,
        "provider_validation_key": spec.provider_validation_key,
        "provider_receipt_sha256": provider.provider_receipt_sha256,
        "provider_manifest_sha256": provider.manifest_sha256,
        "snapshot_id": snapshot.manifest.snapshot_id,
        "provider_validation_config_sha256": config.provider_validation_config_sha256,
        "provider_runtime_fingerprint_sha256": provider.manifest.provider_runtime_fingerprint_sha256,
        "qlib_version": provider.manifest.qlib_version,
        "sampling_policy_version": _POLICY,
        "worker_protocol_version": _PROTOCOL,
        "provider_uri_sha256": _hash_array((provider.manifest.provider_key, "provider")),
        "parent_import_audit_sha256": _hash_array(()),
    }
    if any(getattr(summary, name) != value for name, value in expected_identity.items()):
        raise ValueError("provider validation summary identity drift")
    if not summary.passed:
        raise ValueError("provider validation did not pass")
    staging = _read_staging_rows(snapshot)
    authoritative_plan = _plan_probe(
        snapshot=snapshot, provider=provider, config=config, spec=spec,
        example_id=example_id,
    )
    staging_values = {
        (symbol, day): values
        for symbol, rows in staging.items() for day, values in rows
    }
    seen_cells: set[tuple[str, str, dt.date, str]] = set()
    emitted_keys: set[tuple[str, dt.date]] = set()
    gap_keys: set[tuple[str, dt.date]] = set()
    raw_rows: list[dict[str, object]] = []
    for row in details.to_dicts():
        kind = row["sample_kind"]
        symbol = row["symbol"]
        day = row["date"]
        field = row["field"]
        if (
            type(kind) is not str or type(symbol) is not str
            or type(day) is not dt.date or field not in _FIELDS
        ):
            raise ValueError("provider validation detail key invalid")
        key = (kind, symbol, day, cast(str, field))
        if key in seen_cells:
            raise ValueError("provider validation duplicate detail")
        seen_cells.add(key)
        present = row["api_row_present"]
        expected = row["expected"]
        actual = row["actual"]
        expected_bits = row["expected_f32_bits"]
        actual_bits = row["actual_f32_bits"]
        status = row["status"]
        if kind == "EMITTED":
            emitted_keys.add((symbol, day))
            values = staging_values.get((symbol, day))
            if values is None:
                raise ValueError("provider validation emitted key absent from staging")
            expected_value = np.float32(values[_FIELDS.index(cast(str, field))])
            bits = int(expected_value.view(np.uint32))
            if (
                present is not True or status != "MATCHED"
                or expected is None or actual is None
                or not math.isfinite(cast(float, expected))
                or not math.isfinite(cast(float, actual))
                or expected_bits != bits or actual_bits != bits
                or int(np.float32(expected).view(np.uint32)) != bits
                or int(np.float32(actual).view(np.uint32)) != bits
            ):
                raise ValueError("provider validation emitted detail mismatch")
            raw_actual: object = actual
        elif kind == "GAP":
            gap_keys.add((symbol, day))
            if (symbol, day) in staging_values or (
                expected is not None or actual is not None
                or expected_bits is not None or actual_bits is not None
                or status not in {"GAP_ABSENT", "GAP_NAN"}
                or present is not (status == "GAP_NAN")
            ):
                raise ValueError("provider validation gap detail mismatch")
            raw_actual = math.nan if status == "GAP_NAN" else None
        else:
            raise ValueError("provider validation sample kind invalid")
        raw_rows.append({
            "sample_kind": kind, "symbol": symbol, "date": day,
            "field": field, "api_row_present": present, "actual": raw_actual,
        })
    for kind, keys in (("EMITTED", emitted_keys), ("GAP", gap_keys)):
        for symbol, day in keys:
            fields = {
                field for row_kind, row_symbol, row_day, field in seen_cells
                if row_kind == kind and row_symbol == symbol and row_day == day
            }
            if fields != set(_FIELDS):
                raise ValueError("provider validation field closure invalid")
    emitted_rows = tuple(sorted(emitted_keys))
    gap_rows = tuple(sorted(gap_keys))
    if (
        emitted_rows != authoritative_plan.selected_rows
        or gap_rows != authoritative_plan.selected_gap_rows
    ):
        raise ValueError("provider validation sampling policy drift")
    calendar = tuple(
        day.isoformat() for day in
        pl.read_parquet(snapshot.session_calendar_path).get_column("date").to_list()
    )
    ranges = tuple(sorted(
        (_to_qlib_symbol(symbol).upper(), rows[0][0].isoformat(), rows[-1][0].isoformat())
        for symbol, rows in staging.items()
    ))
    response_rows_sha = _hash_array(_json_rows(raw_rows))
    read_audit_sha = _hash_array({
        "request_keys": tuple(sorted({
            "schema_version", "worker_protocol_version", "provider_validation_key",
            "provider_key", "snapshot_id", "qlib_version", "provider_uri",
            "provider_uri_sha256", "fields", "selected_rows",
            "selected_gap_rows",
        })),
        "fields": _FIELDS,
        "api_calendar_sha256": _hash_array(calendar),
        "api_instrument_ranges_sha256": _hash_array(ranges),
        "response_rows_sha256": response_rows_sha,
    })
    expected_summary = {
        "probe_plan_sha256": _hash_array(_plan_payload(authoritative_plan)),
        "candidate_keys_sha256": authoritative_plan.candidate_keys_sha256,
        "emitted_keys_sha256": authoritative_plan.emitted_keys_sha256,
        "gap_keys_sha256": authoritative_plan.gap_keys_sha256,
        "emitted_key_count": 60,
        "gap_key_count": len(gap_rows),
        "emitted_comparison_count": 420,
        "gap_comparison_count": len(gap_rows) * 7,
        "details_sha256": _hash_array(_json_rows(details.to_dicts())),
        "details_row_count": details.height,
        "api_calendar_sha256": _hash_array(calendar),
        "api_instrument_ranges_sha256": _hash_array(ranges),
        "missing_emitted_cell_count": 0,
        "extra_cell_count": 0,
        "duplicate_cell_count": 0,
        "non_finite_emitted_cell_count": 0,
        "emitted_mismatch_cell_count": 0,
        "gap_finite_cell_count": 0,
        "calendar_mismatch_count": 0,
        "instrument_mismatch_count": 0,
        "read_audit_sha256": read_audit_sha,
    }
    if any(getattr(summary, name) != value for name, value in expected_summary.items()):
        raise ValueError("provider validation summary recomputation mismatch")


def _validate_identities(
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    config: LoadedM3Config, spec: ProviderValidationSpec, example_id: str | None,
) -> None:
    _verify_physical_inputs(snapshot, provider)
    if spec.provider_validation_config_sha256 != config.provider_validation_config_sha256:
        raise ValueError("provider validation config drift")
    if provider.manifest.snapshot_id != snapshot.manifest.snapshot_id or provider.manifest.snapshot_manifest_sha256 != snapshot.manifest_sha256:
        raise ValueError("provider/snapshot identity drift")
    if provider.manifest.qlib_version != spec.qlib_version:
        raise ValueError("provider validation qlib drift")
    if example_id is None:
        expected = compute_provider_validation_key(
            provider_key=provider.manifest.provider_key,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            provider_validation_config_sha256=spec.provider_validation_config_sha256,
            provider_runtime_fingerprint_sha256=provider.manifest.provider_runtime_fingerprint_sha256,
            code_version=spec.code_version,
        )
    else:
        expected = compute_development_provider_validation_key(
            example_id=example_id, provider_key=provider.manifest.provider_key,
            provider_receipt_sha256=provider.provider_receipt_sha256,
            provider_validation_config_sha256=spec.provider_validation_config_sha256,
            provider_runtime_fingerprint_sha256=provider.manifest.provider_runtime_fingerprint_sha256,
            code_version=spec.code_version,
        )
    if spec.provider_validation_key != expected:
        raise ValueError("provider validation key drift")


def _verify_physical_inputs(
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
) -> None:
    _require_real_directory(snapshot.root)
    expected_snapshot_root_names = {
        "manifest.json", "session_calendar.parquet", "staging",
    }
    actual_snapshot_root_names = {path.name for path in snapshot.root.iterdir()}
    if actual_snapshot_root_names != expected_snapshot_root_names:
        raise ValueError("snapshot root closure drift")
    staging_root = snapshot.root / "staging"
    _require_real_directory(staging_root)
    expected_staging_paths = {
        path.relative_to(staging_root).as_posix() for path in snapshot.staging_paths
    }
    actual_staging_paths = {
        path.relative_to(staging_root).as_posix() for path in staging_root.rglob("*")
    }
    if actual_staging_paths != expected_staging_paths:
        raise ValueError("snapshot staging closure drift")
    snapshot_manifest_raw = _read_regular(snapshot.root / "manifest.json")
    if hashlib.sha256(snapshot_manifest_raw).hexdigest() != snapshot.manifest_sha256:
        raise ValueError("snapshot manifest bytes drift")
    snapshot_paths = (
        snapshot.session_calendar_path, *snapshot.staging_paths,
    )
    relative_snapshot_paths = tuple(
        path.relative_to(snapshot.root).as_posix() for path in snapshot_paths
    )
    if relative_snapshot_paths != tuple(item.path for item in snapshot.manifest.files):
        raise ValueError("snapshot file closure drift")
    for entry, path in zip(snapshot.manifest.files, snapshot_paths, strict=True):
        raw = _read_regular(path)
        if len(raw) != entry.size_bytes or hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise ValueError("snapshot file bytes drift")
    provider_manifest_raw = _read_regular(provider.root / "provider_manifest.json")
    if hashlib.sha256(provider_manifest_raw).hexdigest() != provider.manifest_sha256:
        raise ValueError("provider manifest bytes drift")
    expected_paths = tuple(item.relative_path for item in provider.manifest.files)
    _require_real_directory(provider.qlib_dir)
    actual_paths = tuple(sorted(
        path.relative_to(provider.root).as_posix()
        for path in provider.qlib_dir.rglob("*") if path.is_file() or path.is_symlink()
    ))
    if actual_paths != expected_paths:
        raise ValueError("provider file closure drift")
    expected_directories = {
        parent.as_posix()
        for relative_path in expected_paths
        for parent in PurePosixPath(relative_path).parents
        if parent.as_posix() not in {".", "provider"}
    }
    actual_directories = {
        path.relative_to(provider.root).as_posix()
        for path in provider.qlib_dir.rglob("*") if path.is_dir()
    }
    if actual_directories != expected_directories:
        raise ValueError("provider directory closure drift")
    for relative_path in actual_directories:
        _require_real_directory(provider.root / relative_path)
    for provider_entry in provider.manifest.files:
        raw = _read_regular(provider.root / provider_entry.relative_path)
        if (
            len(raw) != provider_entry.size_bytes
            or hashlib.sha256(raw).hexdigest() != provider_entry.sha256
        ):
            raise ValueError("provider file bytes drift")


def _worker_request(
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
    provider: VerifiedProviderArtifact | VerifiedDevelopmentExampleProviderArtifact,
    plan: ProviderProbePlan, spec: ProviderValidationSpec,
) -> dict[str, object]:
    uri_identity = (provider.manifest.provider_key, "provider")
    return {
        "schema_version": "m3-qlib-worker-request-v1",
        "worker_protocol_version": spec.worker_protocol_version,
        "provider_validation_key": spec.provider_validation_key,
        "provider_key": provider.manifest.provider_key,
        "snapshot_id": snapshot.manifest.snapshot_id,
        "qlib_version": spec.qlib_version,
        "provider_uri": str(provider.qlib_dir.resolve(strict=True)),
        "provider_uri_sha256": _hash_array(uri_identity),
        "fields": list(_FIELDS),
        "selected_rows": [[symbol, day.isoformat()] for symbol, day in plan.selected_rows],
        "selected_gap_rows": [[symbol, day.isoformat()] for symbol, day in plan.selected_gap_rows],
    }


def _read_staging_rows(
    snapshot: VerifiedSnapshotArtifact | VerifiedDevelopmentExampleSnapshotArtifact,
) -> dict[str, tuple[tuple[dt.date, tuple[float, ...]], ...]]:
    result: dict[str, tuple[tuple[dt.date, tuple[float, ...]], ...]] = {}
    for path in snapshot.staging_paths:
        frame = pl.read_parquet(path).select("symbol", "date", *_FIELDS).sort("date")
        symbols = frame.get_column("symbol").unique().to_list()
        if len(symbols) != 1:
            raise ValueError("staging symbol closure invalid")
        symbol = cast(str, symbols[0])
        rows = tuple(
            (cast(dt.date, row[0]), tuple(float(value) for value in row[1:]))
            for row in frame.select("date", *_FIELDS).iter_rows()
        )
        if symbol in result or len({day for day, _ in rows}) != len(rows):
            raise ValueError("staging keys invalid")
        result[symbol] = rows
    return result


def _plan_payload(plan: ProviderProbePlan) -> dict[str, object]:
    value = asdict(plan)
    value["selected_rows"] = [[s, d.isoformat()] for s, d in plan.selected_rows]
    value["selected_gap_rows"] = [[s, d.isoformat()] for s, d in plan.selected_gap_rows]
    return value


def _parse_api_calendar(value: object) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ValueError("worker calendar invalid")
    result = tuple(cast(list[str], value))
    if result != tuple(sorted(set(result))):
        raise ValueError("worker calendar order invalid")
    for item in result:
        dt.date.fromisoformat(item)
    return result


def _parse_api_ranges(value: object) -> tuple[tuple[str, str, str], ...]:
    if type(value) is not list:
        raise ValueError("worker instrument ranges invalid")
    result: list[tuple[str, str, str]] = []
    for row in value:
        if type(row) is not list or len(row) != 3 or any(type(item) is not str for item in row):
            raise ValueError("worker instrument range invalid")
        symbol, start, end = cast(list[str], row)
        dt.date.fromisoformat(start)
        dt.date.fromisoformat(end)
        result.append((symbol, start, end))
    output = tuple(result)
    if output != tuple(sorted(set(output))):
        raise ValueError("worker instrument ranges order invalid")
    return output


def _date_iso(value: object) -> str:
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is str:
        return dt.date.fromisoformat(value).isoformat()
    raise ValueError("worker date invalid")


def _json_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for row in rows:
        clean: dict[str, object] = {}
        for key, value in row.items():
            if type(value) is dt.date:
                clean[key] = value.isoformat()
            elif isinstance(value, float) and math.isnan(value):
                clean[key] = {"__float__": "nan"}
            elif value == math.inf:
                clean[key] = {"__float__": "+inf"}
            elif value == -math.inf:
                clean[key] = {"__float__": "-inf"}
            else:
                clean[key] = value
        output.append(clean)
    return tuple(output)


def _details_bytes(frame: pl.DataFrame) -> bytes:
    import io
    buffer = io.BytesIO()
    frame.write_parquet(
        buffer, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
    return buffer.getvalue()


def _digest_for_path(path: Path, roots: Mapping[str, Path]) -> ArtifactDigest:
    raw = _read_regular(path)
    resolved = path.resolve(strict=True)
    matches = [
        (alias, root.resolve(strict=True)) for alias, root in roots.items()
        if resolved == root.resolve(strict=True) or root.resolve(strict=True) in resolved.parents
    ]
    if len(matches) != 1:
        raise ValueError("artifact root alias ambiguous")
    alias, root = matches[0]
    relative = resolved.relative_to(root).as_posix()
    return ArtifactDigest(
        root_alias=alias, relative_path=relative,
        sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
    )


def _require_receipt_input(
    inputs: tuple[ArtifactDigest, ...], *, sha256: str, root_alias: str,
    relative_path: str,
) -> None:
    matches = tuple(item for item in inputs if item.sha256 == sha256)
    if len(matches) != 1 or matches[0].root_alias != root_alias or matches[0].relative_path != relative_path:
        raise ValueError("provider validation receipt identity input invalid")


def _snapshot_stage_prefix(manifest_relative_path: str) -> tuple[str, ...]:
    parts = PurePosixPath(manifest_relative_path).parts
    if len(parts) >= 3 and parts[-3] == "snapshots" and parts[-1] == "manifest.json":
        return parts[:-3]
    if len(parts) >= 2 and parts[-1] == "manifest.json":
        return ()
    raise ValueError("snapshot manifest path invalid")


def _provider_stage_prefix(manifest_relative_path: str) -> tuple[str, ...]:
    parts = PurePosixPath(manifest_relative_path).parts
    if len(parts) >= 3 and parts[-3] == "providers" and parts[-1] == "provider_manifest.json":
        return parts[:-3]
    if len(parts) >= 2 and parts[-1] == "provider_manifest.json":
        return ()
    raise ValueError("provider manifest path invalid")


def _to_qlib_symbol(symbol: str) -> str:
    code, market = symbol.split(".")
    return f"{market}{code}"


def _hash_array(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_json(raw: bytes) -> dict[str, object]:
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=hook,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )
    if type(value) is not dict:
        raise ValueError("JSON object required")
    return value


def _write_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)


def _read_regular(path: Path) -> bytes:
    _require_no_reparse_chain(path)
    status = os.lstat(path)
    attributes = getattr(status, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
        or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    ):
        raise ValueError("regular unlinked validation file required")
    return path.read_bytes()


def _read_regular_bytes_path(path: Path) -> Any:
    import io

    return io.BytesIO(_read_regular(path))


def _require_real_directory(path: Path) -> None:
    _require_no_reparse_chain(path)
    status = os.lstat(path)
    attributes = getattr(status, "st_file_attributes", 0)
    if not stat.S_ISDIR(status.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError("real validation directory required")


def _require_no_reparse_chain(path: Path) -> None:
    current = path.absolute()
    while True:
        if current.exists() or current.is_symlink():
            status = os.lstat(current)
            attributes = getattr(status, "st_file_attributes", 0)
            if stat.S_ISLNK(status.st_mode) or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError("validation path link/reparse invalid")
        if current.parent == current:
            break
        current = current.parent
