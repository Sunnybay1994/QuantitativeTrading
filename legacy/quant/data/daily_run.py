"""M1 单日更新的单写者编排、不可变收据与完成幂等。"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import polars as pl

from quant.data._journal_lock import M3JournalLockError, hold_journal_writer_lock
from quant.data.calendar import expected_open_dates
from quant.data.pipeline import BarUpdateResult
from quant.data.storage import RawSnapshot
from quant.domain import AdjustmentFactorSchema, Bar1dSchema, TradeCalendarSchema

_SPEC_VERSION = "m1-daily-spec-v1"
_MANIFEST_VERSION = "m1-daily-manifest-v1"
_RECEIPT_VERSION = "m1-daily-receipt-v1"
_PROJECTION_VERSION = "m1-clean-projection-v1"
_DATA_LAYOUT_VERSION = "m1-data-layout-v1"
_QUALITY_CONTRACT_VERSION = "m1-bar-quality-v1"
_SOURCES = frozenset({"tushare", "akshare", "baostock"})
_SYMBOL = re.compile(r"^\d{5,6}\.(?:SH|SZ|HK)$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_ErrorCode = Literal[
    "M1_DAILY_INPUT_INVALID",
    "M1_DAILY_CALENDAR_INVALID",
    "M1_DAILY_WRITER_ACTIVE",
    "M1_DAILY_JOURNAL_INVALID",
    "M1_DAILY_IO_FAILED",
    "M1_DAILY_UPDATE_FAILED",
    "M1_DAILY_RECEIPT_INVALID",
    "M1_DAILY_CLEAN_DRIFT",
]


class M1DailyRunError(ValueError):
    """Stable, sanitized daily-run failure; ``str(error)`` equals ``code``."""

    def __init__(self, code: _ErrorCode) -> None:
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M1DailyRunError({self.code!r})"


@dataclass(frozen=True, kw_only=True)
class CalendarSessionV1:
    """One market's exact clean-calendar row bound into a daily identity."""

    market: str
    date: dt.date
    is_open: bool
    is_connect_open: bool
    is_half_day: bool

    def __post_init__(self) -> None:
        if self.market not in {"SH", "SZ", "HK"}:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if type(self.date) is not dt.date:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        for value in (self.is_open, self.is_connect_open, self.is_half_day):
            if type(value) is not bool:
                raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if not self.is_open:
            raise M1DailyRunError("M1_DAILY_CALENDAR_INVALID")


@dataclass(frozen=True, kw_only=True)
class DailyRunSpecV1:
    """Strict, path-independent identity for one requested daily update."""

    session_date: dt.date
    source: str
    symbols: tuple[str, ...]
    use_adjustment_factors: bool
    calendar_sessions: tuple[CalendarSessionV1, ...]
    schema_version: str = _SPEC_VERSION
    data_layout_version: str = _DATA_LAYOUT_VERSION
    quality_contract_version: str = _QUALITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _SPEC_VERSION:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if self.data_layout_version != _DATA_LAYOUT_VERSION:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if self.quality_contract_version != _QUALITY_CONTRACT_VERSION:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if type(self.session_date) is not dt.date or self.source not in _SOURCES:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if type(self.use_adjustment_factors) is not bool:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if not self.symbols or self.symbols != tuple(sorted(set(self.symbols))):
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if any(type(symbol) is not str or not _SYMBOL.fullmatch(symbol) for symbol in self.symbols):
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        markets = tuple(sorted({symbol.rsplit(".", maxsplit=1)[1] for symbol in self.symbols}))
        calendar_markets = tuple(item.market for item in self.calendar_sessions)
        if calendar_markets != markets or len(set(calendar_markets)) != len(calendar_markets):
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if any(item.date != self.session_date for item in self.calendar_sessions):
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")

    @property
    def run_id(self) -> str:
        """Return the bare SHA-256 of the canonical spec bytes."""
        return hashlib.sha256(_canonical_json_bytes(_spec_mapping(self))).hexdigest()


@dataclass(frozen=True, kw_only=True)
class DailyRunResult:
    """A newly completed or strictly replayed M1 daily run."""

    status: Literal["SUCCESS", "ALREADY_COMPLETE"]
    run_id: str
    receipt_selector: str


def build_daily_run_spec(
    *,
    data_root: Path,
    session_date: dt.date,
    source: str,
    symbols: Sequence[str],
    use_adjustment_factors: bool,
) -> DailyRunSpecV1:
    """Build a canonical spec after exact clean-calendar validation."""
    try:
        if not isinstance(data_root, Path) or type(session_date) is not dt.date:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if type(source) is not str or source not in _SOURCES:
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        if type(use_adjustment_factors) is not bool or isinstance(symbols, (str, bytes)):
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        values = tuple(symbols)
        if not values or any(
            type(value) is not str or not _SYMBOL.fullmatch(value) for value in values
        ):
            raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
        canonical_symbols = tuple(sorted(set(values)))
        if session_date not in expected_open_dates(
            data_root, list(canonical_symbols), session_date, session_date
        ):
            raise M1DailyRunError("M1_DAILY_CALENDAR_INVALID")
        sessions = tuple(
            _read_calendar_session(data_root, market, session_date)
            for market in sorted(
                {symbol.rsplit(".", maxsplit=1)[-1] for symbol in canonical_symbols}
            )
        )
        return DailyRunSpecV1(
            session_date=session_date,
            source=source,
            symbols=canonical_symbols,
            use_adjustment_factors=use_adjustment_factors,
            calendar_sessions=sessions,
        )
    except M1DailyRunError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, pl.exceptions.PolarsError):
        raise M1DailyRunError("M1_DAILY_CALENDAR_INVALID") from None


def execute_daily_run(
    *,
    spec: DailyRunSpecV1,
    data_root: Path,
    artifact_root: Path,
    update: Callable[[], BarUpdateResult],
) -> DailyRunResult:
    """Execute once under the global writer lock or verify a completed receipt."""
    if not isinstance(spec, DailyRunSpecV1):
        raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
    if not isinstance(data_root, Path) or not isinstance(artifact_root, Path):
        raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
    if not callable(update):
        raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
    data_root = Path(os.path.abspath(data_root))
    artifact_root = Path(os.path.abspath(artifact_root))
    journal_root = data_root / "run_state" / "m1_daily"
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise M1DailyRunError("M1_DAILY_IO_FAILED") from None
    try:
        with hold_journal_writer_lock(journal_root=journal_root):
            return _execute_locked(
                spec=spec,
                data_root=data_root,
                artifact_root=artifact_root,
                journal_root=journal_root,
                update=update,
            )
    except M3JournalLockError as exc:
        raise _map_lock_error(exc) from None


def verify_daily_receipt(
    *, spec: DailyRunSpecV1, data_root: Path, artifact_root: Path
) -> DailyRunResult:
    """Strictly verify immutable run evidence plus current clean projections."""
    if not isinstance(spec, DailyRunSpecV1):
        raise M1DailyRunError("M1_DAILY_INPUT_INVALID")
    data_root = Path(os.path.abspath(data_root))
    artifact_root = Path(os.path.abspath(artifact_root))
    _verify_current_calendar(spec, data_root)
    run_dir = data_root / "run_state" / "m1_daily" / spec.run_id
    _require_plain_dir(run_dir, "M1_DAILY_RECEIPT_INVALID")
    intent_path = run_dir / "intent.json"
    manifest_path = run_dir / "manifest.json"
    receipt_path = run_dir / "receipt.json"
    if _read_regular_bytes(intent_path) != _canonical_json_bytes(_spec_mapping(spec)):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    manifest_raw = _read_regular_bytes(manifest_path)
    manifest = _strict_canonical_object(manifest_raw)
    _validate_manifest(manifest, spec)
    receipt = _strict_canonical_object(_read_regular_bytes(receipt_path))
    _validate_receipt(receipt, spec)

    expected_artifacts = _manifest_artifact_selectors(spec, manifest)
    actual_artifacts = receipt["artifacts"]
    if type(actual_artifacts) is not list or len(actual_artifacts) != len(expected_artifacts):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    seen: set[tuple[str, str]] = set()
    observed_order: list[tuple[str, str]] = []
    for item in actual_artifacts:
        if type(item) is not dict or set(item) != {
            "alias", "selector", "sha256", "size_bytes"
        }:
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
        alias = item["alias"]
        selector = item["selector"]
        if (
            type(alias) is not str
            or type(selector) is not str
            or type(item["sha256"]) is not str
            or not _HEX64.fullmatch(item["sha256"])
            or type(item["size_bytes"]) is not int
            or isinstance(item["size_bytes"], bool)
            or item["size_bytes"] < 0
        ):
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
        key = (alias, selector)
        if key in seen or key not in expected_artifacts:
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
        seen.add(key)
        observed_order.append(key)
        path = _resolve_selector(
            alias=alias,
            selector=selector,
            data_root=data_root,
            artifact_root=artifact_root,
        )
        raw = _read_regular_bytes(path)
        if item["size_bytes"] != len(raw) or item["sha256"] != _sha256_bytes(raw):
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if seen != expected_artifacts or observed_order != sorted(observed_order):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")

    _verify_manifest_closure(
        spec=spec,
        manifest=manifest,
        data_root=data_root,
        artifact_root=artifact_root,
    )
    return DailyRunResult(
        status="ALREADY_COMPLETE",
        run_id=spec.run_id,
        receipt_selector=f"run_state/m1_daily/{spec.run_id}/receipt.json",
    )


def _execute_locked(
    *,
    spec: DailyRunSpecV1,
    data_root: Path,
    artifact_root: Path,
    journal_root: Path,
    update: Callable[[], BarUpdateResult],
) -> DailyRunResult:
    _verify_current_calendar(spec, data_root)
    run_dir = journal_root / spec.run_id
    try:
        run_dir.mkdir(exist_ok=True)
    except OSError:
        raise M1DailyRunError("M1_DAILY_IO_FAILED") from None
    _require_plain_dir(run_dir, "M1_DAILY_JOURNAL_INVALID")
    intent_path = run_dir / "intent.json"
    manifest_path = run_dir / "manifest.json"
    receipt_path = run_dir / "receipt.json"
    _publish_once(intent_path, _canonical_json_bytes(_spec_mapping(spec)))

    if _path_exists(receipt_path):
        return verify_daily_receipt(
            spec=spec, data_root=data_root, artifact_root=artifact_root
        )
    if _path_exists(manifest_path):
        manifest = _strict_canonical_object(_read_regular_bytes(manifest_path))
        _validate_manifest(manifest, spec)
        _verify_manifest_closure(
            spec=spec,
            manifest=manifest,
            data_root=data_root,
            artifact_root=artifact_root,
        )
        _publish_receipt(
            spec=spec,
            manifest=manifest,
            data_root=data_root,
            artifact_root=artifact_root,
            receipt_path=receipt_path,
        )
        return _as_success(
            verify_daily_receipt(
                spec=spec, data_root=data_root, artifact_root=artifact_root
            )
        )

    try:
        result = update()
    except M1DailyRunError:
        raise
    except Exception:
        raise M1DailyRunError("M1_DAILY_UPDATE_FAILED") from None
    if not isinstance(result, BarUpdateResult):
        raise M1DailyRunError("M1_DAILY_UPDATE_FAILED")
    manifest = _build_manifest(
        spec=spec,
        result=result,
        data_root=data_root,
        artifact_root=artifact_root,
    )
    _publish_once(manifest_path, _canonical_json_bytes(manifest))
    _verify_manifest_closure(
        spec=spec,
        manifest=manifest,
        data_root=data_root,
        artifact_root=artifact_root,
    )
    _publish_receipt(
        spec=spec,
        manifest=manifest,
        data_root=data_root,
        artifact_root=artifact_root,
        receipt_path=receipt_path,
    )
    return _as_success(
        verify_daily_receipt(spec=spec, data_root=data_root, artifact_root=artifact_root)
    )


def _build_manifest(
    *, spec: DailyRunSpecV1, result: BarUpdateResult, data_root: Path, artifact_root: Path
) -> dict[str, Any]:
    if not result.quality_report.passed:
        raise M1DailyRunError("M1_DAILY_UPDATE_FAILED")
    bar_raw = _raw_manifest_entry(result.raw_snapshot, data_root)
    quality_path = (
        artifact_root / "data_quality" / "bar_1d" / f"{result.raw_snapshot.snapshot_id}.json"
    )
    _require_relative(quality_path, artifact_root)
    factor_raw: dict[str, Any] | None = None
    if spec.use_adjustment_factors:
        if result.factor_snapshot is None:
            raise M1DailyRunError("M1_DAILY_UPDATE_FAILED")
        factor_raw = _raw_manifest_entry(result.factor_snapshot, data_root)
    elif result.factor_snapshot is not None:
        raise M1DailyRunError("M1_DAILY_UPDATE_FAILED")
    return {
        "schema_version": _MANIFEST_VERSION,
        "run_id": spec.run_id,
        "bar_raw": bar_raw,
        "factor_raw": factor_raw,
        "quality_selector": _relative_selector(quality_path, artifact_root),
        "bar_clean": _bar_projection(spec, data_root),
        "factor_clean": _factor_projection(spec, data_root)
        if spec.use_adjustment_factors
        else None,
    }


def _publish_receipt(
    *,
    spec: DailyRunSpecV1,
    manifest: Mapping[str, Any],
    data_root: Path,
    artifact_root: Path,
    receipt_path: Path,
) -> None:
    artifacts: list[dict[str, Any]] = []
    for alias, selector in sorted(_manifest_artifact_selectors(spec, manifest)):
        path = _resolve_selector(
            alias=alias,
            selector=selector,
            data_root=data_root,
            artifact_root=artifact_root,
        )
        raw = _read_regular_bytes(path)
        artifacts.append(
            {
                "alias": alias,
                "selector": selector,
                "sha256": _sha256_bytes(raw),
                "size_bytes": len(raw),
            }
        )
    receipt = {
        "schema_version": _RECEIPT_VERSION,
        "run_id": spec.run_id,
        "artifacts": artifacts,
    }
    _publish_once(receipt_path, _canonical_json_bytes(receipt))


def _verify_manifest_closure(
    *,
    spec: DailyRunSpecV1,
    manifest: Mapping[str, Any],
    data_root: Path,
    artifact_root: Path,
) -> None:
    _verify_raw_entry(
        spec=spec,
        entry=manifest["bar_raw"],
        table="bar_1d",
        data_root=data_root,
    )
    factor_raw = manifest["factor_raw"]
    if spec.use_adjustment_factors:
        if type(factor_raw) is not dict:
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
        _verify_raw_entry(
            spec=spec,
            entry=factor_raw,
            table="adjust_factor",
            data_root=data_root,
        )
    elif factor_raw is not None:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")

    quality_path = _resolve_selector(
        alias="artifacts",
        selector=manifest["quality_selector"],
        data_root=data_root,
        artifact_root=artifact_root,
    )
    expected_quality = f"data_quality/bar_1d/{manifest['bar_raw']['snapshot_id']}.json"
    if manifest["quality_selector"] != expected_quality:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    quality = _strict_json_object(_read_regular_bytes(quality_path), canonical=False)
    if quality.get("passed") is not True or quality.get("rows") != len(spec.symbols):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if _bar_projection(spec, data_root) != manifest["bar_clean"]:
        raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT")
    if spec.use_adjustment_factors:
        if _factor_projection(spec, data_root) != manifest["factor_clean"]:
            raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT")
    elif manifest["factor_clean"] is not None:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")


def _verify_raw_entry(
    *, spec: DailyRunSpecV1, entry: object, table: str, data_root: Path
) -> None:
    if type(entry) is not dict or set(entry) != {
        "snapshot_id", "checksum_sha256", "data_selector", "metadata_selector"
    }:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    snapshot_id = entry["snapshot_id"]
    checksum = entry["checksum_sha256"]
    if type(snapshot_id) is not str or type(checksum) is not str or not _HEX64.fullmatch(checksum):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    data_selector = entry["data_selector"]
    metadata_selector = entry["metadata_selector"]
    if type(data_selector) is not str or type(metadata_selector) is not str:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    expected_suffix = f"/{snapshot_id}.parquet"
    if (
        not data_selector.startswith(f"raw/{spec.source}/{table}/date=")
        or not data_selector.endswith(expected_suffix)
        or metadata_selector != data_selector.removesuffix(".parquet") + ".json"
    ):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    data_path = _resolve_selector(
        alias="data", selector=data_selector, data_root=data_root, artifact_root=data_root
    )
    metadata_path = _resolve_selector(
        alias="data", selector=metadata_selector, data_root=data_root, artifact_root=data_root
    )
    data_raw = _read_regular_bytes(data_path)
    if _sha256_bytes(data_raw) != checksum:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    metadata = _strict_json_object(_read_regular_bytes(metadata_path), canonical=False)
    if (
        metadata.get("snapshot_id") != snapshot_id
        or metadata.get("source") != spec.source
        or metadata.get("table") != table
        or metadata.get("checksum_sha256") != checksum
    ):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    parameters = metadata.get("parameters")
    if type(parameters) is not dict:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if parameters.get("symbols") != list(spec.symbols):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if parameters.get("end") != spec.session_date.isoformat():
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    expected_start = "1990-01-01" if table == "adjust_factor" else spec.session_date.isoformat()
    if parameters.get("start") != expected_start:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if table == "adjust_factor" and parameters.get("factor_type") != "cumulative_backward":
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    try:
        frame = pl.read_parquet(io.BytesIO(data_raw))
    except Exception:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID") from None
    if metadata.get("rows") != frame.height or metadata.get("columns") != frame.columns:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")


def _raw_manifest_entry(snapshot: RawSnapshot, data_root: Path) -> dict[str, str]:
    snapshot_id = snapshot.snapshot_id
    data_path = snapshot.data_path
    metadata_path = snapshot.metadata_path
    checksum = snapshot.checksum_sha256
    if (
        type(snapshot_id) is not str
        or not isinstance(data_path, Path)
        or not isinstance(metadata_path, Path)
        or type(checksum) is not str
        or not _HEX64.fullmatch(checksum)
    ):
        raise M1DailyRunError("M1_DAILY_UPDATE_FAILED")
    return {
        "snapshot_id": snapshot_id,
        "checksum_sha256": checksum,
        "data_selector": _relative_selector(data_path, data_root),
        "metadata_selector": _relative_selector(metadata_path, data_root),
    }


def _bar_projection(spec: DailyRunSpecV1, data_root: Path) -> dict[str, Any]:
    selector = f"clean/bar_1d/date={spec.session_date.isoformat()}/data.parquet"
    path = _resolve_selector(
        alias="data", selector=selector, data_root=data_root, artifact_root=data_root
    )
    try:
        validated = Bar1dSchema.validate(pl.read_parquet(path))
        frame = validated.filter(
            (pl.col("trade_date") == spec.session_date)
            & (pl.col("source") == spec.source)
            & pl.col("symbol").is_in(spec.symbols)
        ).sort(["symbol", "trade_date", "source"])
    except Exception:
        raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT") from None
    if (
        frame.height != len(spec.symbols)
        or frame.unique(subset=["symbol", "trade_date", "source"]).height != frame.height
        or tuple(frame.get_column("symbol").to_list()) != spec.symbols
    ):
        raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT")
    return _projection_mapping("bar_1d", selector, frame)


def _factor_projection(spec: DailyRunSpecV1, data_root: Path) -> dict[str, Any]:
    selector = f"clean/adjust_factor/source={spec.source}/data.parquet"
    path = _resolve_selector(
        alias="data", selector=selector, data_root=data_root, artifact_root=data_root
    )
    try:
        validated = AdjustmentFactorSchema.validate(pl.read_parquet(path))
        frame = validated.filter(
            (pl.col("source") == spec.source)
            & pl.col("symbol").is_in(spec.symbols)
            & (pl.col("effective_date") <= spec.session_date)
        ).sort(["symbol", "effective_date", "source"])
    except Exception:
        raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT") from None
    if frame.height == 0 or set(frame.get_column("symbol").to_list()) != set(spec.symbols):
        raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT")
    if frame.unique(subset=["symbol", "effective_date", "source"]).height != frame.height:
        raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT")
    return _projection_mapping("adjust_factor", selector, frame)


def _projection_mapping(table: str, selector: str, frame: pl.DataFrame) -> dict[str, Any]:
    rows: list[str] = []
    for row in frame.iter_rows(named=True):
        rows.append(_canonical_json_bytes({key: _scalar_tag(value) for key, value in row.items()}).decode())
    rows.sort()
    digest = _sha256_bytes(
        _canonical_json_bytes(
            {
                "schema_version": _PROJECTION_VERSION,
                "table": table,
                "columns": [
                    {"name": name, "dtype": str(dtype)}
                    for name, dtype in zip(frame.columns, frame.dtypes, strict=True)
                ],
                "rows": rows,
            }
        )
    )
    return {"selector": selector, "row_count": frame.height, "content_sha256": digest}


def _read_calendar_session(
    data_root: Path, market: str, session_date: dt.date
) -> CalendarSessionV1:
    path = data_root / "clean" / "trade_calendar" / f"market={market}" / "data.parquet"
    try:
        frame = TradeCalendarSchema.validate(pl.read_parquet(path)).filter(
            pl.col("date") == session_date
        )
    except Exception:
        raise M1DailyRunError("M1_DAILY_CALENDAR_INVALID") from None
    if frame.height != 1:
        raise M1DailyRunError("M1_DAILY_CALENDAR_INVALID")
    row = frame.row(0, named=True)
    return CalendarSessionV1(
        market=row["market"],
        date=row["date"],
        is_open=row["is_open"],
        is_connect_open=row["is_connect_open"],
        is_half_day=row["is_half_day"],
    )


def _verify_current_calendar(spec: DailyRunSpecV1, data_root: Path) -> None:
    current = tuple(
        _read_calendar_session(data_root, item.market, spec.session_date)
        for item in spec.calendar_sessions
    )
    if current != spec.calendar_sessions:
        raise M1DailyRunError("M1_DAILY_CALENDAR_INVALID")


def _spec_mapping(spec: DailyRunSpecV1) -> dict[str, Any]:
    return {
        "schema_version": spec.schema_version,
        "session_date": spec.session_date.isoformat(),
        "source": spec.source,
        "symbols": list(spec.symbols),
        "use_adjustment_factors": spec.use_adjustment_factors,
        "calendar_sessions": [
            {
                "market": item.market,
                "date": item.date.isoformat(),
                "is_open": item.is_open,
                "is_connect_open": item.is_connect_open,
                "is_half_day": item.is_half_day,
            }
            for item in spec.calendar_sessions
        ],
        "data_layout_version": spec.data_layout_version,
        "quality_contract_version": spec.quality_contract_version,
    }


def _validate_manifest(manifest: Mapping[str, Any], spec: DailyRunSpecV1) -> None:
    if set(manifest) != {
        "schema_version", "run_id", "bar_raw", "factor_raw", "quality_selector",
        "bar_clean", "factor_clean"
    }:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if manifest["schema_version"] != _MANIFEST_VERSION or manifest["run_id"] != spec.run_id:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if type(manifest["quality_selector"]) is not str:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    raw_keys = {
        "snapshot_id", "checksum_sha256", "data_selector", "metadata_selector"
    }
    if type(manifest["bar_raw"]) is not dict or set(manifest["bar_raw"]) != raw_keys:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if spec.use_adjustment_factors:
        if type(manifest["factor_raw"]) is not dict or set(manifest["factor_raw"]) != raw_keys:
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    elif manifest["factor_raw"] is not None:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    for key in ("bar_clean", "factor_clean"):
        value = manifest[key]
        if key == "factor_clean" and not spec.use_adjustment_factors and value is None:
            continue
        if type(value) is not dict or set(value) != {"selector", "row_count", "content_sha256"}:
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
        if (
            type(value["selector"]) is not str
            or type(value["row_count"]) is not int
            or isinstance(value["row_count"], bool)
            or value["row_count"] < 1
            or type(value["content_sha256"]) is not str
            or not _HEX64.fullmatch(value["content_sha256"])
        ):
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")


def _validate_receipt(receipt: Mapping[str, Any], spec: DailyRunSpecV1) -> None:
    if set(receipt) != {"schema_version", "run_id", "artifacts"}:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    if receipt["schema_version"] != _RECEIPT_VERSION or receipt["run_id"] != spec.run_id:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")


def _manifest_artifact_selectors(
    spec: DailyRunSpecV1, manifest: Mapping[str, Any]
) -> set[tuple[str, str]]:
    run_prefix = f"run_state/m1_daily/{spec.run_id}"
    selectors = {
        ("data", f"{run_prefix}/intent.json"),
        ("data", f"{run_prefix}/manifest.json"),
        ("data", manifest["bar_raw"]["data_selector"]),
        ("data", manifest["bar_raw"]["metadata_selector"]),
        ("artifacts", manifest["quality_selector"]),
    }
    factor = manifest["factor_raw"]
    if spec.use_adjustment_factors:
        if type(factor) is not dict:
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
        selectors.add(("data", factor["data_selector"]))
        selectors.add(("data", factor["metadata_selector"]))
    return selectors


def _publish_once(path: Path, payload: bytes) -> None:
    if _path_exists(path):
        if _read_regular_bytes(path) != payload:
            raise M1DailyRunError("M1_DAILY_JOURNAL_INVALID")
        return
    fd = -1
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read_regular_bytes(path) != payload:
                raise M1DailyRunError("M1_DAILY_JOURNAL_INVALID") from None
        _fsync_directory(path.parent)
    except M1DailyRunError:
        raise
    except OSError:
        raise M1DailyRunError("M1_DAILY_IO_FAILED") from None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _strict_canonical_object(payload: bytes) -> dict[str, Any]:
    value = _strict_json_object(payload, canonical=True)
    if _canonical_json_bytes(value) != payload:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    return value


def _strict_json_object(payload: bytes, *, canonical: bool) -> dict[str, Any]:
    if payload.startswith(b"\xef\xbb\xbf") or (canonical and b"\r" in payload):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    try:
        text = payload.decode("utf-8")

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID") from None
    if type(value) is not dict:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise M1DailyRunError("M1_DAILY_INPUT_INVALID") from None


def _scalar_tag(value: object) -> list[Any]:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT")
        return ["float", format(0.0 if value == 0.0 else value, ".17g")]
    if type(value) is dt.date and type(value) is not dt.datetime:
        return ["date", value.isoformat()]
    if type(value) is str:
        return ["string", value]
    raise M1DailyRunError("M1_DAILY_CLEAN_DRIFT")


def _read_regular_bytes(path: Path) -> bytes:
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
        return path.read_bytes()
    except M1DailyRunError:
        raise
    except OSError:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID") from None


def _require_plain_dir(path: Path, code: _ErrorCode) -> None:
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            raise M1DailyRunError(code)
    except M1DailyRunError:
        raise
    except OSError:
        raise M1DailyRunError(code) from None


def _resolve_selector(
    *, alias: object, selector: object, data_root: Path, artifact_root: Path
) -> Path:
    if type(alias) is not str or alias not in {"data", "artifacts"} or type(selector) is not str:
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    pure = PurePosixPath(selector)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID")
    root = data_root if alias == "data" else artifact_root
    path = root.joinpath(*pure.parts)
    _require_relative(path, root)
    return path


def _relative_selector(path: Path, root: Path) -> str:
    path = Path(os.path.abspath(path))
    root = Path(os.path.abspath(root))
    _require_relative(path, root)
    return PurePosixPath(path.relative_to(root)).as_posix()


def _require_relative(path: Path, root: Path) -> None:
    try:
        Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(root)))
    except (TypeError, ValueError):
        raise M1DailyRunError("M1_DAILY_RECEIPT_INVALID") from None


def _path_exists(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise M1DailyRunError("M1_DAILY_IO_FAILED") from None


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _map_lock_error(error: M3JournalLockError) -> M1DailyRunError:
    if error.code == "JOURNAL_WRITER_ACTIVE":
        return M1DailyRunError("M1_DAILY_WRITER_ACTIVE")
    if error.code in {
        "JOURNAL_LOCK_INPUT_INVALID",
        "JOURNAL_LOCK_ROOT_INVALID",
        "JOURNAL_LOCK_FILE_INVALID",
    }:
        return M1DailyRunError("M1_DAILY_JOURNAL_INVALID")
    return M1DailyRunError("M1_DAILY_IO_FAILED")


def _as_success(result: DailyRunResult) -> DailyRunResult:
    return DailyRunResult(
        status="SUCCESS", run_id=result.run_id, receipt_selector=result.receipt_selector
    )
