"""Safe, read-only projections of immutable lightweight research runs."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import stat
from dataclasses import dataclass, fields
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Sequence, cast

import polars as pl

from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    ResearchOutputDigestV1,
    canonical_json_bytes,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_INTEGRITY_BYTES = 128 * 1024 * 1024
_MAX_NAV_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_NAV_ROWS = 250_000
_MIN_COMPARISON_RUNS = 2
_MAX_COMPARISON_RUNS = 4
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)

_Conclusion = Literal["REJECTED", "RESEARCH_ONLY", "PAPER_CANDIDATE"]
_SignalTiming = Literal["close"]
_ExecutionTiming = Literal["next_session_open"]
_ValuationTiming = Literal["close"]


@dataclass(frozen=True)
class CatalogIssue:
    """One safe-to-display problem found while projecting a research run."""

    code: str
    entry: str
    detail: str


@dataclass(frozen=True)
class ResearchRunSummary:
    """A manifest-backed run that passed canonical and identity validation."""

    run_root: Path
    manifest: LightweightResearchRunV1


@dataclass(frozen=True)
class ResearchRunCatalog:
    """Valid run summaries plus isolated issues for unreadable entries."""

    runs_root: Path
    runs: tuple[ResearchRunSummary, ...]
    issues: tuple[CatalogIssue, ...]


@dataclass(frozen=True)
class ResearchRunIntegrity:
    """Result of checking the exact immutable output tree for one run."""

    status: Literal["VERIFIED", "BLOCKED"]
    run: ResearchRunSummary
    checked_files: int
    nav_path: Path | None
    issue: CatalogIssue | None


@dataclass(frozen=True)
class ResearchNavProjection:
    """A bounded, validated 1.0x-cost NAV projection for display only."""

    status: Literal["AVAILABLE", "NOT_AVAILABLE", "BLOCKED"]
    frame: pl.DataFrame | None
    issue: CatalogIssue | None


@dataclass(frozen=True)
class ResearchRunComparison:
    """All-or-nothing evidence for one strict 2-4 run comparison."""

    status: Literal["VERIFIED", "BLOCKED"]
    runs: tuple[ResearchRunSummary, ...]
    integrities: tuple[ResearchRunIntegrity, ...]
    issue: CatalogIssue | None


@dataclass(frozen=True)
class ResearchRunComparisonNav:
    """A display-only NAV projection for a fully verified comparison."""

    status: Literal["AVAILABLE", "BLOCKED"]
    frame: pl.DataFrame | None
    issue: CatalogIssue | None


class _ReadProblem(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def discover_research_runs(artifact_root: Path) -> ResearchRunCatalog:
    """Discover canonical V1 runs from the one fixed lightweight-runs directory."""
    root = artifact_root.absolute()
    research_root = root / "research"
    runs_root = research_root / "runs"
    for directory in (root, research_root, runs_root):
        state = _directory_state(directory)
        if state == "MISSING":
            return ResearchRunCatalog(
                runs_root=runs_root,
                runs=(),
                issues=(
                    CatalogIssue(
                        "RUNS_ROOT_MISSING",
                        "research/runs",
                        "The fixed lightweight research-runs directory is missing.",
                    ),
                ),
            )
        if state == "UNSAFE":
            return ResearchRunCatalog(
                runs_root=runs_root,
                runs=(),
                issues=(
                    CatalogIssue(
                        "RUNS_ROOT_UNSAFE",
                        "research/runs",
                        "The research-runs path is not a safe readable directory.",
                    ),
                ),
            )

    try:
        entries = sorted(runs_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return ResearchRunCatalog(
            runs_root=runs_root,
            runs=(),
            issues=(
                CatalogIssue(
                    "RUNS_ROOT_UNSAFE",
                    "research/runs",
                    "The research-runs directory cannot be enumerated safely.",
                ),
            ),
        )

    runs: list[ResearchRunSummary] = []
    issues: list[CatalogIssue] = []
    for entry in entries:
        entry_name = _display_entry(entry.name)
        if _HEX64.fullmatch(entry.name) is None or _directory_state(entry) != "SAFE":
            issues.append(
                CatalogIssue(
                    "RUN_ENTRY_UNSAFE",
                    entry_name,
                    "The direct runs entry is not a safe canonical run directory.",
                )
            )
            continue
        summary, issue = _load_summary(entry)
        if issue is not None:
            issues.append(issue)
        elif summary is not None:
            runs.append(summary)

    runs.sort(
        key=lambda item: (
            -item.manifest.data_end.toordinal(),
            item.manifest.hypothesis_id,
            item.manifest.run_id,
        )
    )
    return ResearchRunCatalog(runs_root, tuple(runs), tuple(issues))


def verify_research_run(run: ResearchRunSummary) -> ResearchRunIntegrity:
    """Verify the exact output tree, sizes and SHA-256 values for one run."""
    refreshed, issue = _load_summary(run.run_root)
    if issue is not None or refreshed is None:
        return _blocked_integrity(
            run,
            issue
            or CatalogIssue(
                "RUN_MANIFEST_INVALID",
                run.manifest.run_id,
                "The manifest could not be revalidated.",
            ),
        )
    if refreshed.manifest != run.manifest:
        return _blocked_integrity(
            run,
            CatalogIssue(
                "RUN_MANIFEST_INVALID",
                run.manifest.run_id,
                "The manifest changed after catalog discovery.",
            ),
        )

    try:
        actual_files, actual_directories = _collect_tree(run.run_root)
    except _ReadProblem as problem:
        return _blocked_integrity(
            run,
            CatalogIssue(problem.code, run.manifest.run_id, problem.detail),
        )

    expected_files = {"run.json", *(item.relative_path for item in run.manifest.outputs)}
    expected_directories = _parent_directories(expected_files)
    if actual_files != expected_files or actual_directories != expected_directories:
        return _blocked_integrity(
            run,
            CatalogIssue(
                "RUN_TREE_MISMATCH",
                run.manifest.run_id,
                "The output tree does not exactly match the immutable manifest.",
            ),
        )

    checked_files = 0
    nav_path: Path | None = None
    remaining_bytes = _MAX_INTEGRITY_BYTES
    for output in run.manifest.outputs:
        if output.size_bytes > remaining_bytes:
            return _blocked_integrity(
                run,
                CatalogIssue(
                    "RUN_OUTPUT_INVALID",
                    run.manifest.run_id,
                    "The output set exceeds the bounded G0 integrity-check limit.",
                ),
                checked_files=checked_files,
            )
        output_path = run.run_root.joinpath(*PurePosixPath(output.relative_path).parts)
        try:
            size_bytes, digest = _hash_regular_file(
                output_path,
                max_bytes=remaining_bytes,
            )
        except _ReadProblem as problem:
            return _blocked_integrity(
                run,
                CatalogIssue(problem.code, run.manifest.run_id, problem.detail),
                checked_files=checked_files,
            )
        if size_bytes != output.size_bytes or digest != output.sha256:
            return _blocked_integrity(
                run,
                CatalogIssue(
                    "RUN_OUTPUT_DIGEST_MISMATCH",
                    run.manifest.run_id,
                    "An output size or SHA-256 value does not match the manifest.",
                ),
                checked_files=checked_files,
            )
        checked_files += 1
        remaining_bytes -= size_bytes
        if output.relative_path == "test_nav.parquet":
            nav_path = output_path

    return ResearchRunIntegrity(
        status="VERIFIED",
        run=run,
        checked_files=checked_files,
        nav_path=nav_path,
        issue=None,
    )


def load_nav_projection(
    source: ResearchRunIntegrity | ResearchRunSummary,
    *,
    max_rows: int = _DEFAULT_MAX_NAV_ROWS,
) -> ResearchNavProjection:
    """Load a bounded 1.0x-cost NAV only after exact output verification."""
    if type(max_rows) is not int or max_rows <= 0:
        raise ValueError("max_rows must be a positive integer")
    if isinstance(source, ResearchRunSummary):
        return _nav_problem(
            "BLOCKED",
            source.manifest.run_id,
            "NAV_NOT_AVAILABLE",
            "Output integrity must be verified before NAV is read.",
        )
    if source.status != "VERIFIED" or source.issue is not None:
        return _nav_problem(
            "BLOCKED",
            source.run.manifest.run_id,
            "NAV_NOT_AVAILABLE",
            "Output integrity did not pass; NAV remains blocked.",
        )
    if source.nav_path is None:
        return _nav_problem(
            "NOT_AVAILABLE",
            source.run.manifest.run_id,
            "NAV_NOT_AVAILABLE",
            "The immutable manifest does not list test_nav.parquet.",
        )

    expected = next(
        (
            output
            for output in source.run.manifest.outputs
            if output.relative_path == "test_nav.parquet"
        ),
        None,
    )
    if expected is None or expected.size_bytes > _MAX_NAV_BYTES:
        return _nav_problem(
            "BLOCKED",
            source.run.manifest.run_id,
            "NAV_SCHEMA_INVALID",
            "The NAV output exceeds the bounded G0 projection contract.",
        )
    try:
        payload = _read_regular_bytes(
            source.nav_path,
            max_bytes=_MAX_NAV_BYTES,
            code="NAV_SCHEMA_INVALID",
            invalid_detail="The NAV output is no longer a safe regular file.",
            oversized_detail="The NAV output exceeds the bounded G0 projection contract.",
        )
    except _ReadProblem as problem:
        return _nav_problem(
            "BLOCKED",
            source.run.manifest.run_id,
            problem.code,
            problem.detail,
        )
    if len(payload) != expected.size_bytes or hashlib.sha256(payload).hexdigest() != expected.sha256:
        return _nav_problem(
            "BLOCKED",
            source.run.manifest.run_id,
            "NAV_NOT_AVAILABLE",
            "The NAV output changed after integrity verification.",
        )

    required = ("strategy", "date", "unit_nav", "fold", "cost_multiplier")
    try:
        frame = pl.read_parquet(
            io.BytesIO(payload),
            columns=list(required),
            n_rows=max_rows + 1,
        )
    except (OSError, ValueError, pl.exceptions.PolarsError):
        return _invalid_nav(source.run.manifest.run_id)
    if frame.is_empty() or frame.height > max_rows or not _valid_nav_schema(frame):
        return _invalid_nav(source.run.manifest.run_id)

    strategies = frame.get_column("strategy").to_list()
    dates = frame.get_column("date").to_list()
    nav_values = frame.get_column("unit_nav").to_list()
    folds = frame.get_column("fold").to_list()
    costs = frame.get_column("cost_multiplier").to_list()
    allowed_folds = {fold.fold for fold in source.run.manifest.folds}
    if (
        any(not value for value in strategies)
        or any(
            type(value) is not dt.date
            or value < source.run.manifest.data_start
            or value > source.run.manifest.data_end
            for value in dates
        )
        or any(not math.isfinite(value) or value <= 0 for value in nav_values)
        or any(value not in allowed_folds for value in folds)
        or any(not math.isfinite(value) or value <= 0 for value in costs)
    ):
        return _invalid_nav(source.run.manifest.run_id)

    projected = frame.filter((pl.col("cost_multiplier") - 1.0).abs() <= 1e-12)
    if projected.is_empty():
        return _invalid_nav(source.run.manifest.run_id)
    if projected.unique(subset=["strategy", "fold", "date"]).height != projected.height:
        return _invalid_nav(source.run.manifest.run_id)
    series = [
        f"{strategy} / fold {fold}"
        for strategy, fold in zip(
            projected.get_column("strategy").to_list(),
            projected.get_column("fold").to_list(),
            strict=True,
        )
    ]
    projected = projected.with_columns(pl.Series("series", series)).sort(
        ["strategy", "fold", "date"]
    )
    return ResearchNavProjection("AVAILABLE", projected, None)


def verify_research_run_comparison(
    runs: Sequence[ResearchRunSummary],
) -> ResearchRunComparison:
    """Verify one strict comparison without ranking or recomputing its evidence."""
    selected = tuple(runs)
    run_ids = tuple(run.manifest.run_id for run in selected)
    if not _MIN_COMPARISON_RUNS <= len(selected) <= _MAX_COMPARISON_RUNS:
        return _comparison_problem(
            selected,
            "COMPARISON_SELECTION_INVALID",
            "comparison",
            "A comparison requires between two and four runs.",
        )
    if len(set(run_ids)) != len(run_ids):
        return _comparison_problem(
            selected,
            "COMPARISON_SELECTION_INVALID",
            "comparison",
            "Every selected comparison run must have a unique run id.",
        )

    reference = _comparison_contract(selected[0])
    mismatched_fields = {
        field
        for run in selected[1:]
        for field, value in _comparison_contract(run).items()
        if value != reference[field]
    }
    if mismatched_fields:
        return _comparison_problem(
            selected,
            "COMPARISON_CONTRACT_MISMATCH",
            "comparison",
            "Selected runs have incompatible comparison fields: "
            + ", ".join(sorted(mismatched_fields))
            + ".",
        )

    declared_output_bytes = sum(
        output.size_bytes
        for run in selected
        for output in run.manifest.outputs
    )
    if declared_output_bytes > _MAX_INTEGRITY_BYTES:
        return _comparison_problem(
            selected,
            "COMPARISON_OUTPUT_LIMIT",
            "comparison",
            "The selected output set exceeds the bounded comparison limit.",
        )

    verified: list[ResearchRunIntegrity] = []
    for run in selected:
        integrity = verify_research_run(run)
        if integrity.status != "VERIFIED" or integrity.issue is not None:
            underlying = integrity.issue
            detail = (
                f"{underlying.code}: {underlying.detail}"
                if underlying is not None
                else "The run did not provide complete output-integrity evidence."
            )
            return _comparison_problem(
                selected,
                "COMPARISON_RUN_UNVERIFIED",
                run.manifest.run_id,
                detail,
            )
        verified.append(integrity)
    return ResearchRunComparison("VERIFIED", selected, tuple(verified), None)


def load_comparison_nav_projection(
    comparison: ResearchRunComparison,
    *,
    max_rows: int = _DEFAULT_MAX_NAV_ROWS,
) -> ResearchRunComparisonNav:
    """Join labels onto verified NAV rows without computing business metrics."""
    if type(max_rows) is not int or max_rows <= 0:
        raise ValueError("max_rows must be a positive integer")
    if (
        comparison.status != "VERIFIED"
        or comparison.issue is not None
        or len(comparison.integrities) != len(comparison.runs)
    ):
        return _comparison_nav_problem(
            "comparison",
            "COMPARISON_NAV_UNAVAILABLE",
            "Every selected run must pass the comparison and output checks first.",
        )

    frames: list[pl.DataFrame] = []
    remaining_rows = max_rows
    for selection_order, (run, integrity) in enumerate(
        zip(comparison.runs, comparison.integrities, strict=True),
        start=1,
    ):
        if (
            integrity.status != "VERIFIED"
            or integrity.issue is not None
            or integrity.run != run
        ):
            return _comparison_nav_problem(
                run.manifest.run_id,
                "COMPARISON_NAV_UNAVAILABLE",
                "Comparison integrity evidence no longer matches the selected run.",
            )
        if remaining_rows <= 0:
            return _comparison_nav_problem(
                run.manifest.run_id,
                "COMPARISON_NAV_LIMIT",
                "The combined NAV projection exceeds the bounded row limit.",
            )
        nav = load_nav_projection(integrity, max_rows=max_rows)
        if nav.status != "AVAILABLE" or nav.frame is None or nav.issue is not None:
            underlying = nav.issue
            detail = (
                f"{underlying.code}: {underlying.detail}"
                if underlying is not None
                else "The run has no complete bounded NAV evidence."
            )
            return _comparison_nav_problem(
                run.manifest.run_id,
                "COMPARISON_NAV_UNAVAILABLE",
                detail,
            )
        if nav.frame.height > remaining_rows:
            return _comparison_nav_problem(
                run.manifest.run_id,
                "COMPARISON_NAV_LIMIT",
                "The combined NAV projection exceeds the bounded row limit.",
            )
        if frames and nav.frame.schema != frames[0].select(nav.frame.columns).schema:
            return _comparison_nav_problem(
                run.manifest.run_id,
                "COMPARISON_NAV_UNAVAILABLE",
                "Selected NAV projections do not share one exact display schema.",
            )
        comparison_series = [
            f"{run.manifest.strategy_name} · {run.manifest.run_id[:12]} · {series}"
            for series in nav.frame.get_column("series").to_list()
        ]
        frames.append(
            nav.frame.with_columns(
                pl.lit(selection_order).alias("selection_order"),
                pl.lit(run.manifest.run_id).alias("run_id"),
                pl.Series("comparison_series", comparison_series),
            )
        )
        remaining_rows -= nav.frame.height

    if not frames:
        return _comparison_nav_problem(
            "comparison",
            "COMPARISON_NAV_UNAVAILABLE",
            "The comparison did not produce any bounded NAV evidence.",
        )
    return ResearchRunComparisonNav(
        status="AVAILABLE",
        frame=pl.concat(frames, how="vertical"),
        issue=None,
    )


def _comparison_contract(run: ResearchRunSummary) -> dict[str, object]:
    manifest = run.manifest
    return {
        "schema_version": manifest.schema_version,
        "data_start": manifest.data_start,
        "data_end": manifest.data_end,
        "universe_name": manifest.universe_name,
        "universe_frozen_as_of": manifest.universe_frozen_as_of,
        "candidate_symbols": manifest.candidate_symbols,
        "signal_timing": manifest.signal_timing,
        "execution_timing": manifest.execution_timing,
        "valuation_timing": manifest.valuation_timing,
        "folds": manifest.folds,
        "cost_multipliers": manifest.cost_multipliers,
        "selection_metric": manifest.selection_metric,
        "aggregate_metric_names": tuple(
            name for name, _ in manifest.aggregate_metrics
        ),
        "inputs": manifest.inputs,
    }


def _comparison_problem(
    runs: tuple[ResearchRunSummary, ...],
    code: str,
    entry: str,
    detail: str,
) -> ResearchRunComparison:
    return ResearchRunComparison(
        status="BLOCKED",
        runs=runs,
        integrities=(),
        issue=CatalogIssue(code, entry, detail),
    )


def _comparison_nav_problem(
    entry: str,
    code: str,
    detail: str,
) -> ResearchRunComparisonNav:
    return ResearchRunComparisonNav(
        status="BLOCKED",
        frame=None,
        issue=CatalogIssue(code, entry, detail),
    )


def _load_summary(run_root: Path) -> tuple[ResearchRunSummary | None, CatalogIssue | None]:
    entry = _display_entry(run_root.name)
    if _directory_state(run_root) != "SAFE":
        return None, CatalogIssue(
            "RUN_ENTRY_UNSAFE",
            entry,
            "The run directory is not a safe regular directory.",
        )
    try:
        raw = _read_regular_bytes(
            run_root / "run.json",
            max_bytes=_MAX_MANIFEST_BYTES,
            code="RUN_MANIFEST_INVALID",
            invalid_detail="run.json is missing or is not a safe regular file.",
            oversized_detail="run.json exceeds the bounded manifest size.",
        )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _ReadProblem(
                "RUN_MANIFEST_INVALID", "run.json is not strict UTF-8 JSON."
            ) from error
        if canonical_json_bytes(payload) != raw:
            raise _ReadProblem(
                "RUN_MANIFEST_NONCANONICAL",
                "run.json does not use the canonical lightweight-run encoding.",
            )
        mapping = _exact_mapping(payload, LightweightResearchRunV1)
        run_id = _json_str(mapping["run_id"])
        if _HEX64.fullmatch(run_id) is None:
            raise _ReadProblem("RUN_MANIFEST_INVALID", "run.json has an invalid run id.")
        identity_payload = dict(mapping)
        identity_payload.pop("run_id")
        expected_id = hashlib.sha256(
            canonical_json_bytes(
                ["lightweight-research-run-id-v1", identity_payload]
            )
        ).hexdigest()
        if run_id != expected_id or run_root.name != run_id:
            raise _ReadProblem(
                "RUN_ID_MISMATCH",
                "The directory, manifest and canonical content identity do not match.",
            )
        manifest = _manifest_from_mapping(mapping)
    except _ReadProblem as problem:
        return None, CatalogIssue(problem.code, entry, problem.detail)
    except (KeyError, OSError, TypeError, ValueError, OverflowError):
        return None, CatalogIssue(
            "RUN_MANIFEST_INVALID",
            entry,
            "run.json does not satisfy the complete lightweight-run V1 contract.",
        )
    return ResearchRunSummary(run_root=run_root, manifest=manifest), None


def _manifest_from_mapping(mapping: dict[str, object]) -> LightweightResearchRunV1:
    schema_version = _json_str(mapping["schema_version"])
    conclusion = _json_str(mapping["conclusion"])
    signal_timing = _json_str(mapping["signal_timing"])
    execution_timing = _json_str(mapping["execution_timing"])
    valuation_timing = _json_str(mapping["valuation_timing"])
    if schema_version != "lightweight-research-run-v1":
        raise ValueError("invalid schema version")
    if conclusion not in {"REJECTED", "RESEARCH_ONLY", "PAPER_CANDIDATE"}:
        raise ValueError("invalid conclusion")
    if signal_timing != "close":
        raise ValueError("invalid signal timing")
    if execution_timing != "next_session_open":
        raise ValueError("invalid execution timing")
    if valuation_timing != "close":
        raise ValueError("invalid valuation timing")

    folds = tuple(_fold_from_json(value) for value in _json_list(mapping["folds"]))
    inputs = tuple(_input_from_json(value) for value in _json_list(mapping["inputs"]))
    outputs = tuple(_output_from_json(value) for value in _json_list(mapping["outputs"]))
    aggregate_metrics = tuple(
        _metric_from_json(value) for value in _json_list(mapping["aggregate_metrics"])
    )
    return LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id=_json_str(mapping["run_id"]),
        hypothesis_id=_json_str(mapping["hypothesis_id"]),
        hypothesis=_json_str(mapping["hypothesis"]),
        strategy_name=_json_str(mapping["strategy_name"]),
        strategy_version=_json_str(mapping["strategy_version"]),
        conclusion=cast(_Conclusion, conclusion),
        random_seed=_json_int(mapping["random_seed"]),
        config_relative_path=_json_str(mapping["config_relative_path"]),
        config_sha256=_json_str(mapping["config_sha256"]),
        code_sha256=_json_str(mapping["code_sha256"]),
        universe_name=_json_str(mapping["universe_name"]),
        universe_frozen_as_of=_json_date(mapping["universe_frozen_as_of"]),
        candidate_symbols=tuple(
            _json_str(value) for value in _json_list(mapping["candidate_symbols"])
        ),
        data_start=_json_date(mapping["data_start"]),
        data_end=_json_date(mapping["data_end"]),
        signal_timing=cast(_SignalTiming, signal_timing),
        execution_timing=cast(_ExecutionTiming, execution_timing),
        valuation_timing=cast(_ValuationTiming, valuation_timing),
        folds=folds,
        cost_multipliers=tuple(
            _json_float(value) for value in _json_list(mapping["cost_multipliers"])
        ),
        selection_metric=_json_str(mapping["selection_metric"]),
        inputs=inputs,
        outputs=outputs,
        aggregate_metrics=aggregate_metrics,
        caveats=tuple(_json_str(value) for value in _json_list(mapping["caveats"])),
    )


def _fold_from_json(value: object) -> ResearchFoldV1:
    mapping = _exact_mapping(value, ResearchFoldV1)
    return ResearchFoldV1(
        fold=_json_int(mapping["fold"]),
        train_start=_json_date(mapping["train_start"]),
        train_end=_json_date(mapping["train_end"]),
        validation_start=_json_date(mapping["validation_start"]),
        validation_end=_json_date(mapping["validation_end"]),
        test_start=_json_date(mapping["test_start"]),
        test_end=_json_date(mapping["test_end"]),
    )


def _input_from_json(value: object) -> ResearchInputDigestV1:
    mapping = _exact_mapping(value, ResearchInputDigestV1)
    return ResearchInputDigestV1(
        name=_json_str(mapping["name"]),
        rows=_json_int(mapping["rows"]),
        min_date=_json_optional_date(mapping["min_date"]),
        max_date=_json_optional_date(mapping["max_date"]),
        content_sha256=_json_str(mapping["content_sha256"]),
    )


def _output_from_json(value: object) -> ResearchOutputDigestV1:
    mapping = _exact_mapping(value, ResearchOutputDigestV1)
    return ResearchOutputDigestV1(
        relative_path=_json_str(mapping["relative_path"]),
        size_bytes=_json_int(mapping["size_bytes"]),
        sha256=_json_str(mapping["sha256"]),
    )


def _metric_from_json(value: object) -> tuple[str, int | float]:
    values = _json_list(value)
    if len(values) != 2:
        raise ValueError("invalid aggregate metric")
    metric_value = values[1]
    if type(metric_value) not in {int, float}:
        raise ValueError("invalid aggregate metric")
    return _json_str(values[0]), cast(int | float, metric_value)


def _valid_nav_schema(frame: pl.DataFrame) -> bool:
    integer_types = {
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    }
    float_types = {pl.Float32, pl.Float64}
    schema = frame.schema
    if (
        schema.get("strategy") != pl.String
        or schema.get("date") != pl.Date
        or schema.get("unit_nav") not in float_types
        or schema.get("fold") not in integer_types
        or schema.get("cost_multiplier") not in float_types
    ):
        return False
    return all(nulls == 0 for nulls in frame.null_count().row(0))


def _collect_tree(root: Path) -> tuple[set[str], set[str]]:
    if _directory_state(root) != "SAFE":
        raise _ReadProblem(
            "RUN_OUTPUT_INVALID", "The run root is no longer a safe directory."
        )
    files_found: set[str] = set()
    directories_found: set[str] = set()
    stack: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath("."))]
    while stack:
        directory, relative_root = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError as error:
            raise _ReadProblem(
                "RUN_OUTPUT_INVALID", "The output tree cannot be enumerated safely."
            ) from error
        for entry in entries:
            relative = (
                PurePosixPath(entry.name)
                if str(relative_root) == "."
                else relative_root / entry.name
            )
            try:
                metadata = entry.lstat()
            except OSError as error:
                raise _ReadProblem(
                    "RUN_OUTPUT_INVALID", "An output entry cannot be inspected safely."
                ) from error
            if _is_link_or_reparse(metadata):
                raise _ReadProblem(
                    "RUN_OUTPUT_INVALID", "The output tree contains a link or reparse point."
                )
            if stat.S_ISDIR(metadata.st_mode):
                directories_found.add(relative.as_posix())
                stack.append((entry, relative))
            elif stat.S_ISREG(metadata.st_mode):
                files_found.add(relative.as_posix())
            else:
                raise _ReadProblem(
                    "RUN_OUTPUT_INVALID", "The output tree contains a non-regular entry."
                )
    return files_found, directories_found


def _parent_directories(relative_files: set[str]) -> set[str]:
    directories: set[str] = set()
    for relative_file in relative_files:
        parent = PurePosixPath(relative_file).parent
        while str(parent) != ".":
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _directory_state(path: Path) -> Literal["SAFE", "MISSING", "UNSAFE"]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return "MISSING"
    except OSError:
        return "UNSAFE"
    if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        return "UNSAFE"
    return "SAFE"


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & _REPARSE_POINT)


def _read_regular_bytes(
    path: Path,
    *,
    max_bytes: int,
    code: str,
    invalid_detail: str,
    oversized_detail: str,
) -> bytes:
    try:
        before = path.lstat()
    except OSError as error:
        raise _ReadProblem(code, invalid_detail) from error
    if (
        _is_link_or_reparse(before)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size > max_bytes
    ):
        detail = oversized_detail if before.st_size > max_bytes else invalid_detail
        raise _ReadProblem(code, detail)
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not _same_file(before, opened) or not stat.S_ISREG(opened.st_mode):
                raise _ReadProblem(code, invalid_detail)
            payload = stream.read(max_bytes + 1)
        after = path.lstat()
    except _ReadProblem:
        raise
    except OSError as error:
        raise _ReadProblem(code, invalid_detail) from error
    if len(payload) > max_bytes:
        raise _ReadProblem(code, oversized_detail)
    if not _same_file(before, after) or _is_link_or_reparse(after):
        raise _ReadProblem(code, invalid_detail)
    return payload


def _hash_regular_file(path: Path, *, max_bytes: int) -> tuple[int, str]:
    try:
        before = path.lstat()
    except OSError as error:
        raise _ReadProblem(
            "RUN_OUTPUT_INVALID", "An output is missing or cannot be inspected safely."
        ) from error
    if (
        _is_link_or_reparse(before)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size > max_bytes
    ):
        raise _ReadProblem(
            "RUN_OUTPUT_INVALID",
            "An output is unsafe or exceeds the bounded G0 integrity-check limit.",
        )
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not _same_file(before, opened) or not stat.S_ISREG(opened.st_mode):
                raise _ReadProblem(
                    "RUN_OUTPUT_INVALID", "An output changed while it was opened."
                )
            while chunk := stream.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise _ReadProblem(
                        "RUN_OUTPUT_INVALID",
                        "The output set exceeds the bounded G0 integrity-check limit.",
                    )
                digest.update(chunk)
        after = path.lstat()
    except _ReadProblem:
        raise
    except OSError as error:
        raise _ReadProblem(
            "RUN_OUTPUT_INVALID", "An output could not be read safely."
        ) from error
    if not _same_file(before, after) or _is_link_or_reparse(after):
        raise _ReadProblem(
            "RUN_OUTPUT_INVALID", "An output changed during integrity verification."
        )
    return size_bytes, digest.hexdigest()


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _exact_mapping(value: object, data_class: type[Any]) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("expected a JSON object")
    mapping = cast(dict[str, object], value)
    expected = {field.name for field in fields(data_class)}
    if set(mapping) != expected:
        raise ValueError("JSON object fields do not match the contract")
    return mapping


def _json_list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError("expected a JSON array")
    return cast(list[object], value)


def _json_str(value: object) -> str:
    if type(value) is not str:
        raise ValueError("expected a JSON string")
    return cast(str, value)


def _json_int(value: object) -> int:
    if type(value) is not int:
        raise ValueError("expected a JSON integer")
    return cast(int, value)


def _json_float(value: object) -> float:
    if type(value) is not float:
        raise ValueError("expected a JSON float")
    return cast(float, value)


def _json_date(value: object) -> dt.date:
    encoded = _json_str(value)
    parsed = dt.date.fromisoformat(encoded)
    if parsed.isoformat() != encoded:
        raise ValueError("date is not canonical")
    return parsed


def _json_optional_date(value: object) -> dt.date | None:
    return None if value is None else _json_date(value)


def _display_entry(value: str) -> str:
    return value[:128]


def _blocked_integrity(
    run: ResearchRunSummary,
    issue: CatalogIssue,
    *,
    checked_files: int = 0,
) -> ResearchRunIntegrity:
    return ResearchRunIntegrity("BLOCKED", run, checked_files, None, issue)


def _invalid_nav(run_id: str) -> ResearchNavProjection:
    return _nav_problem(
        "BLOCKED",
        run_id,
        "NAV_SCHEMA_INVALID",
        "test_nav.parquet does not satisfy the bounded G0 NAV projection contract.",
    )


def _nav_problem(
    status: Literal["NOT_AVAILABLE", "BLOCKED"],
    run_id: str,
    code: str,
    detail: str,
) -> ResearchNavProjection:
    return ResearchNavProjection(status, None, CatalogIssue(code, run_id, detail))


def conclusion_counts(runs: Sequence[ResearchRunSummary]) -> dict[str, int]:
    """Return stable conclusion counts for summary cards."""
    counts = {"REJECTED": 0, "RESEARCH_ONLY": 0, "PAPER_CANDIDATE": 0}
    for run in runs:
        counts[run.manifest.conclusion] += 1
    return counts


__all__ = [
    "CatalogIssue",
    "ResearchNavProjection",
    "ResearchRunCatalog",
    "ResearchRunComparison",
    "ResearchRunComparisonNav",
    "ResearchRunIntegrity",
    "ResearchRunSummary",
    "conclusion_counts",
    "discover_research_runs",
    "load_comparison_nav_projection",
    "load_nav_projection",
    "verify_research_run",
    "verify_research_run_comparison",
]
