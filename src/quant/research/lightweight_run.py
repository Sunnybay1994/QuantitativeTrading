"""Lightweight, reproducible research-run records.

This module deliberately does not implement the formal M3 receipt protocol.  It
captures enough information to reproduce and compare an early research run while
keeping hypothesis iteration inexpensive.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Callable, Literal, Mapping, Sequence, TypeVar

import polars as pl

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ResearchFoldV1:
    fold: int
    train_start: dt.date
    train_end: dt.date
    validation_start: dt.date
    validation_end: dt.date
    test_start: dt.date
    test_end: dt.date

    def __post_init__(self) -> None:
        dates = (
            self.train_start,
            self.train_end,
            self.validation_start,
            self.validation_end,
            self.test_start,
            self.test_end,
        )
        if type(self.fold) is not int or self.fold <= 0:
            raise ValueError("invalid research fold")
        if any(type(value) is not dt.date for value in dates):
            raise ValueError("invalid research fold dates")
        if not (
            self.train_start <= self.train_end
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise ValueError("invalid research fold ordering")


@dataclass(frozen=True)
class ResearchInputDigestV1:
    name: str
    rows: int
    min_date: dt.date | None
    max_date: dt.date | None
    content_sha256: str

    def __post_init__(self) -> None:
        _require_token(self.name)
        if type(self.rows) is not int or self.rows < 0:
            raise ValueError("invalid research input rows")
        if (self.min_date is None) != (self.max_date is None):
            raise ValueError("invalid research input date range")
        if self.min_date is not None:
            if (
                type(self.min_date) is not dt.date
                or type(self.max_date) is not dt.date
                or self.max_date < self.min_date
            ):
                raise ValueError("invalid research input date range")
        _require_hex(self.content_sha256)


@dataclass(frozen=True)
class ResearchOutputDigestV1:
    relative_path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _require_relative(self.relative_path)
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("invalid research output size")
        _require_hex(self.sha256)


@dataclass(frozen=True)
class LightweightResearchRunV1:
    schema_version: Literal["lightweight-research-run-v1"]
    run_id: str
    hypothesis_id: str
    hypothesis: str
    strategy_name: str
    strategy_version: str
    conclusion: Literal["REJECTED", "RESEARCH_ONLY", "PAPER_CANDIDATE"]
    random_seed: int
    config_relative_path: str
    config_sha256: str
    code_sha256: str
    universe_name: str
    universe_frozen_as_of: dt.date
    candidate_symbols: tuple[str, ...]
    data_start: dt.date
    data_end: dt.date
    signal_timing: Literal["close"]
    execution_timing: Literal["next_session_open"]
    valuation_timing: Literal["close"]
    folds: tuple[ResearchFoldV1, ...]
    cost_multipliers: tuple[float, ...]
    selection_metric: str
    inputs: tuple[ResearchInputDigestV1, ...]
    outputs: tuple[ResearchOutputDigestV1, ...]
    aggregate_metrics: tuple[tuple[str, float | int], ...]
    caveats: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "lightweight-research-run-v1":
            raise ValueError("invalid lightweight research schema")
        if self.run_id:
            _require_hex(self.run_id)
        _require_token(self.hypothesis_id)
        _require_text(self.hypothesis)
        _require_token(self.strategy_name)
        _require_token(self.strategy_version)
        if self.conclusion not in {"REJECTED", "RESEARCH_ONLY", "PAPER_CANDIDATE"}:
            raise ValueError("invalid research conclusion")
        if type(self.random_seed) is not int or self.random_seed < 0:
            raise ValueError("invalid research seed")
        _require_relative(self.config_relative_path)
        _require_hex(self.config_sha256)
        _require_hex(self.code_sha256)
        _require_token(self.universe_name.lower())
        if type(self.universe_frozen_as_of) is not dt.date:
            raise ValueError("invalid universe date")
        if (
            type(self.candidate_symbols) is not tuple
            or not self.candidate_symbols
            or self.candidate_symbols != tuple(sorted(self.candidate_symbols))
            or len(self.candidate_symbols) != len(set(self.candidate_symbols))
        ):
            raise ValueError("candidate symbols are not canonical")
        if type(self.data_start) is not dt.date or type(self.data_end) is not dt.date:
            raise ValueError("invalid research data window")
        if self.data_end < self.data_start:
            raise ValueError("invalid research data window")
        if (
            self.signal_timing != "close"
            or self.execution_timing != "next_session_open"
            or self.valuation_timing != "close"
        ):
            raise ValueError("invalid research timing")
        if (
            type(self.folds) is not tuple
            or not self.folds
            or any(type(item) is not ResearchFoldV1 for item in self.folds)
            or tuple(item.fold for item in self.folds) != tuple(range(1, len(self.folds) + 1))
        ):
            raise ValueError("invalid research folds")
        if (
            type(self.cost_multipliers) is not tuple
            or 1.0 not in self.cost_multipliers
            or tuple(sorted(set(self.cost_multipliers))) != self.cost_multipliers
            or any(type(value) is not float or not math.isfinite(value) or value <= 0 for value in self.cost_multipliers)
        ):
            raise ValueError("invalid research cost multipliers")
        _require_token(self.selection_metric)
        _require_ordered_unique(self.inputs, lambda item: item.name)
        _require_ordered_unique(self.outputs, lambda item: item.relative_path)
        if type(self.aggregate_metrics) is not tuple:
            raise ValueError("invalid aggregate metrics")
        metric_names = tuple(name for name, _ in self.aggregate_metrics)
        if metric_names != tuple(sorted(metric_names)) or len(metric_names) != len(set(metric_names)):
            raise ValueError("aggregate metrics are not canonical")
        for name, value in self.aggregate_metrics:
            _require_token(name)
            if type(value) not in {int, float} or not math.isfinite(float(value)):
                raise ValueError("invalid aggregate metric")
        if type(self.caveats) is not tuple or any(type(value) is not str or not value for value in self.caveats):
            raise ValueError("invalid research caveats")
        expected = _run_id(self)
        if self.run_id and self.run_id != expected:
            raise ValueError("research run identity mismatch")


def compute_code_sha256(*, project_root: Path, relative_paths: Sequence[str]) -> str:
    """Hash the exact source files that implement one lightweight run."""
    root = project_root.resolve(strict=True)
    canonical = tuple(sorted(relative_paths))
    if not canonical or len(canonical) != len(set(canonical)):
        raise ValueError("source paths are not canonical")
    entries: list[list[str]] = []
    for relative in canonical:
        _require_relative(relative)
        path = (root / Path(relative)).resolve(strict=True)
        if path.parent != root and root not in path.parents:
            raise ValueError("source path escapes project root")
        payload = path.read_bytes()
        entries.append([relative, hashlib.sha256(payload).hexdigest()])
    return _sha256(entries)


def dataframe_input_digest(
    *, name: str, frame: pl.DataFrame, sort_by: Sequence[str], date_column: str
) -> ResearchInputDigestV1:
    """Build a content digest for the selected in-memory research input."""
    _require_token(name)
    if not isinstance(frame, pl.DataFrame) or frame.is_empty():
        raise ValueError("research input must be a non-empty DataFrame")
    if not sort_by or any(column not in frame.columns for column in sort_by):
        raise ValueError("invalid research input sort key")
    if date_column not in frame.columns:
        raise ValueError("research input date column is missing")
    ordered = frame.sort(list(sort_by))
    dates = ordered.get_column(date_column)
    min_date = dates.min()
    max_date = dates.max()
    if type(min_date) is not dt.date or type(max_date) is not dt.date:
        raise ValueError("research input date column must contain dates")
    rows = [
        [_json_scalar(value) for value in row]
        for row in ordered.iter_rows()
    ]
    digest = _sha256([ordered.columns, [str(dtype) for dtype in ordered.dtypes], rows])
    return ResearchInputDigestV1(name, ordered.height, min_date, max_date, digest)


def publish_lightweight_research_run(
    *, artifact_root: Path, run: LightweightResearchRunV1,
    output_payloads: Mapping[str, bytes],
) -> tuple[Path, LightweightResearchRunV1, bool]:
    """Publish one no-clobber lightweight run, or reuse identical bytes."""
    if run.run_id:
        raise ValueError("run_id must be empty before publication")
    payload_keys = tuple(sorted(output_payloads))
    if (
        not payload_keys
        or "run.json" in payload_keys
        or any(type(output_payloads[key]) is not bytes for key in payload_keys)
    ):
        raise ValueError("invalid research outputs")
    for key in payload_keys:
        _require_relative(key)
    outputs = tuple(
        ResearchOutputDigestV1(key, len(output_payloads[key]), hashlib.sha256(output_payloads[key]).hexdigest())
        for key in payload_keys
    )
    complete = replace(run, outputs=outputs)
    complete = replace(complete, run_id=_run_id(complete))
    root = artifact_root / "research" / "runs" / complete.run_id
    manifest_payload = _canonical_bytes(_run_mapping(complete))
    if root.exists():
        _verify_existing(root, complete, manifest_payload, output_payloads)
        return root, complete, True
    parent = root.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = parent / f".{complete.run_id}.tmp-{os.getpid()}"
    if temp.exists():
        raise ValueError("research temporary directory already exists")
    temp.mkdir()
    try:
        for relative, payload in sorted(output_payloads.items()):
            _write_exclusive(temp, relative, payload)
        _write_exclusive(temp, "run.json", manifest_payload)
        temp.rename(root)
    except FileExistsError:
        shutil.rmtree(temp, ignore_errors=True)
        _verify_existing(root, complete, manifest_payload, output_payloads)
        return root, complete, True
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return root, complete, False


def canonical_json_bytes(value: object) -> bytes:
    """Return the lightweight research canonical JSON encoding."""
    return _canonical_bytes(value)


def _run_id(run: LightweightResearchRunV1) -> str:
    return _sha256(["lightweight-research-run-id-v1", _run_mapping(run, include_run_id=False)])


def _run_mapping(run: LightweightResearchRunV1, *, include_run_id: bool = True) -> dict[str, object]:
    value = asdict(run)
    if not include_run_id:
        value.pop("run_id")
    return value


def _verify_existing(
    root: Path, run: LightweightResearchRunV1, manifest_payload: bytes,
    outputs: Mapping[str, bytes],
) -> None:
    expected = {"run.json", *outputs}
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual != expected or (root / "run.json").read_bytes() != manifest_payload:
        raise ValueError("existing research run does not match")
    for relative, payload in outputs.items():
        if (root / Path(relative)).read_bytes() != payload:
            raise ValueError("existing research output does not match")
    if _run_id(run) != run.run_id:
        raise ValueError("existing research identity does not match")


def _write_exclusive(root: Path, relative: str, payload: bytes) -> None:
    _require_relative(relative)
    path = root / Path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _json_scalar(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite research input")
        return value
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is dt.datetime:
        if value.tzinfo is None:
            raise ValueError("naive research input timestamp")
        return value.isoformat()
    raise ValueError("unsupported research input scalar")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if type(value) is dt.date:
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_token(value: object) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ValueError("invalid research token")


def _require_text(value: object) -> None:
    if type(value) is not str or not value.strip() or len(value) > 1000:
        raise ValueError("invalid research text")


def _require_hex(value: object) -> None:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError("invalid sha256")


def _require_relative(value: object) -> None:
    if type(value) is not str or "\\" in value:
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid relative path")


_T = TypeVar("_T")


def _require_ordered_unique(
    values: tuple[_T, ...], key: Callable[[_T], str]
) -> None:
    if type(values) is not tuple:
        raise ValueError("values are not canonical")
    keys = tuple(key(value) for value in values)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("values are not canonical")


__all__ = [
    "LightweightResearchRunV1",
    "ResearchFoldV1",
    "ResearchInputDigestV1",
    "ResearchOutputDigestV1",
    "canonical_json_bytes",
    "compute_code_sha256",
    "dataframe_input_digest",
    "publish_lightweight_research_run",
]
