"""clean -> Qlib staging Parquet 与不可变 snapshot manifest。

复权公式（SSOT 2.3）::

    normalization_base = first_valid_raw_close * first_valid_adj_factor
    qlib_factor        = adj_factor / normalization_base
    qlib_ohlc          = raw_ohlc * qlib_factor
    raw_vwap           = amount / volume
    qlib_vwap          = raw_vwap * qlib_factor
    qlib_volume        = raw_volume / qlib_factor

恒等式：``qlib_vwap / qlib_factor == amount / volume``。

``materialize_qlib_provider`` 仍留待真实 Qlib 环境；``validate_provider`` fail-closed。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import wraps
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, ParamSpec, TypeVar, cast

import polars as pl

from quant.data.m3_release import VerifiedG1Release, verify_g1_release
from quant.domain.schemas import SnapshotSessionCalendarSchema
from quant.research.m3.config import LoadedM3Config, canonical_config_sha256
from quant.research.m3.contracts import (
    DatasetSnapshot,
    SnapshotArtifactEntryV1,
    SnapshotBuildResult,
    SnapshotBuildSpec,
    SnapshotManifestV1,
    SnapshotRequestRecordV1,
    VerifiedSnapshotArtifact,
)
from quant.research.m3.development_example import (
    VerifiedDevelopmentExampleG1Release,
    VerifiedDevelopmentExampleSnapshotArtifact,
    compute_development_snapshot_request_key_from_parts,
    verify_development_example_g1_release,
)
from quant.research.m3.run_state import (
    ArtifactDigest,
    compute_snapshot_request_key,
    verify_stage_receipt,
)

STAGING_COLUMNS = (
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "vwap",
    "volume",
    "factor",
)

ADJUSTMENT_SPEC: Mapping[str, object] = MappingProxyType({
    "formula_version": "qlib_yahoo_like_v1",
    "clean_units": {
        "ohlc": "raw_unadjusted",
        "amount": "CNY",
        "volume": "shares",
        "adj_factor": "cumulative_backward",
        "vwap": "amount_per_share_unadjusted",
    },
    "normalization_base": "first_valid_raw_close * first_valid_adj_factor",
    "qlib_factor": "adj_factor / normalization_base",
    "qlib_ohlc": "raw_ohlc * qlib_factor",
    "raw_vwap": "amount / volume",
    "qlib_vwap": "(amount / volume) * qlib_factor",
    "qlib_volume": "raw_volume / qlib_factor",
    "identity": "qlib_vwap / qlib_factor == amount / volume",
})

_SOURCE = "tushare"
_UNIVERSE = "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
_MANIFEST_NAME = "manifest.json"
_CALENDAR_NAME = "session_calendar.parquet"
_STAGING_DIR = "staging"
_P = ParamSpec("_P")
_R = TypeVar("_R")


class M3SnapshotError(ValueError):
    """Sanitized stable failure at the G2A boundary."""

    def __init__(self, code: str) -> None:
        if code not in {
            "SNAPSHOT_INPUT_INVALID",
            "SNAPSHOT_OUTPUT_INVALID",
            "SNAPSHOT_IDENTITY_MISMATCH",
        }:
            raise ValueError("unknown M3 snapshot error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3SnapshotError({self.code!r})"


@dataclass(frozen=True)
class _SnapshotSourceView:
    trust_domain: Literal["FORMAL_G1", "DEVELOPMENT_EXAMPLE_G1"]
    source_id: str
    development_example_id: str | None
    development_request_key: str | None
    manifest_sha256: str
    manifest_path: Path
    history_start: dt.date
    history_end: dt.date
    signal_start: dt.date
    signal_end: dt.date
    files: tuple[Any, ...]
    artifact_paths: tuple[tuple[str, Path], ...]


@dataclass(frozen=True)
class _VerifiedSnapshotParts:
    root: Path
    request: SnapshotRequestRecordV1
    request_sha256: str
    manifest: SnapshotManifestV1
    manifest_sha256: str
    snapshot_receipt_sha256: str
    session_calendar_path: Path
    staging_paths: tuple[Path, ...]


def _snapshot_boundary(
    code: str,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            try:
                return function(*args, **kwargs)
            except M3SnapshotError:
                raise
            except (TypeError, ValueError, OSError, pl.exceptions.PolarsError):
                raise M3SnapshotError(code) from None
        return wrapped
    return decorate


def to_qlib_symbol(symbol: str) -> str:
    """将项目证券代码映射为 Qlib dump 使用的小写代码。"""
    if "." not in symbol:
        raise ValueError(f"非法证券代码: {symbol}")
    code, market = symbol.rsplit(".", 1)
    market = market.upper()
    if market not in {"SH", "SZ"}:
        raise ValueError(f"Qlib staging 暂仅支持 SH/SZ，收到: {symbol}")
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法证券代码: {symbol}")
    return f"{market.lower()}{code}"


def from_qlib_symbol(instrument: str) -> str:
    """将 Qlib instrument（大小写均可）还原为项目证券代码。"""
    text = instrument.strip()
    if len(text) < 8:
        raise ValueError(f"非法 Qlib instrument: {instrument}")
    prefix = text[:2].lower()
    code = text[2:]
    if prefix == "sh":
        market = "SH"
    elif prefix == "sz":
        market = "SZ"
    else:
        raise ValueError(f"未知或不支持的 Qlib 市场前缀: {instrument}")
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法 Qlib instrument: {instrument}")
    return f"{code}.{market}"


def _prepare_qlib_staging(
    *,
    release: VerifiedG1Release | None = None,
    history_start: dt.date | None = None,
    history_end: dt.date | None = None,
    bars: pl.DataFrame | None = None,
    membership: pl.DataFrame | None = None,
    calendars: pl.DataFrame | None = None,
    source: str | None = None,
    universe: str | None = None,
) -> pl.DataFrame:
    """Build deterministic staging from a reverified G1 release.

    The frame arguments remain as a compatibility seam for the already-published
    deterministic unit fixtures; production callers must pass ``release``.
    """
    if release is not None:
        if any(value is not None for value in (bars, membership, calendars, source, universe)):
            raise ValueError("release 模式不得混用裸 DataFrame")
        if type(history_start) is not dt.date or type(history_end) is not dt.date:
            raise ValueError("release 模式必须提供精确 history 日期")
        source_view = _formal_snapshot_source(release)
        bars = _read_snapshot_source_parquet(source_view, "bar_1d.parquet")
        membership = _read_snapshot_source_parquet(
            source_view, "universe_membership.parquet"
        )
        calendars = _read_snapshot_source_parquet(
            source_view, "trade_calendar.parquet"
        )
        source = _SOURCE
        universe = _UNIVERSE
    elif any(value is not None for value in (history_start, history_end)):
        raise ValueError("裸 DataFrame 兼容模式不得单独传 history 日期")

    if not all(isinstance(value, pl.DataFrame) for value in (bars, membership, calendars)):
        raise ValueError("bars/membership/calendars 必须成套提供")
    if type(source) is not str or type(universe) is not str:
        raise ValueError("source/universe 必须为字符串")
    assert bars is not None and membership is not None and calendars is not None
    staging = _prepare_qlib_staging_frames(
        bars=bars,
        membership=membership,
        calendars=calendars,
        source=source,
        universe=universe,
    )
    if release is not None:
        assert history_start is not None and history_end is not None
        staging = staging.filter(pl.col("date").is_between(history_start, history_end))
        if staging.is_empty():
            raise ValueError("history window 过滤后 staging 为空")
    return staging


def prepare_qlib_staging(
    *, release: VerifiedG1Release | None = None,
    history_start: dt.date | None = None, history_end: dt.date | None = None,
    bars: pl.DataFrame | None = None, membership: pl.DataFrame | None = None,
    calendars: pl.DataFrame | None = None, source: str | None = None,
    universe: str | None = None,
) -> pl.DataFrame:
    """Public G2A staging boundary with a legacy fixture-only frame seam."""
    try:
        return _prepare_qlib_staging(
            release=release, history_start=history_start, history_end=history_end,
            bars=bars, membership=membership, calendars=calendars, source=source,
            universe=universe,
        )
    except M3SnapshotError:
        raise
    except (TypeError, ValueError, OSError, pl.exceptions.PolarsError):
        if release is not None:
            raise M3SnapshotError("SNAPSHOT_INPUT_INVALID") from None
        raise


def _prepare_qlib_staging_frames(
    *, bars: pl.DataFrame, membership: pl.DataFrame, calendars: pl.DataFrame,
    source: str, universe: str,
) -> pl.DataFrame:
    """按 source → 合法性 → universe 并集/SH 日历 → 逐证券归一化。"""
    required = {
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
        "source",
    }
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ValueError(f"bars 缺少选源所需字段: {missing}")

    if not universe:
        raise ValueError("universe 不得为空")
    if "universe" not in membership.columns or "symbol" not in membership.columns:
        raise ValueError("membership 缺少 universe/symbol")

    selected = bars.filter(pl.col("source") == source)
    if selected.is_empty():
        raise ValueError(f"source={source} 无行情行")
    if selected.get_column("source").n_unique() != 1:
        raise ValueError("禁止混合数据源写入 staging")

    _reject_duplicates(selected)
    _reject_invalid_rows(selected)

    members = membership.filter(pl.col("universe") == universe)
    if members.is_empty():
        raise ValueError(f"universe={universe} 无 membership 行")
    symbol_union = set(members.get_column("symbol").unique().to_list())
    if not symbol_union:
        raise ValueError(f"universe={universe} symbol 并集为空")

    # 交易日域统一使用 SH session calendar，不得把 SH/SZ 开市日做并集。
    open_dates = set(
        calendars.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .get_column("date")
        .to_list()
    )
    if not open_dates:
        raise ValueError("SH 开市日历为空")

    # 仅按 symbol 并集与 SH 开市日过滤；不得按 effective_from/to 删除行情。
    filtered = selected.filter(
        pl.col("symbol").is_in(sorted(symbol_union))
        & pl.col("trade_date").is_in(sorted(open_dates))
    )
    if filtered.is_empty():
        raise ValueError("universe/日历过滤后 staging 为空")

    filtered = filtered.select(
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
    ).unique(subset=["symbol", "trade_date"], keep="first")

    parts: list[pl.DataFrame] = []
    for symbol in filtered.get_column("symbol").unique().sort().to_list():
        part = filtered.filter(pl.col("symbol") == symbol).sort("trade_date")
        first = part.row(0, named=True)
        base = float(first["close"]) * float(first["adj_factor"])
        if not math.isfinite(base) or base <= 0:
            raise ValueError(f"{symbol} normalization_base 非正或非 finite")
        adjusted = part.with_columns(
            (pl.col("adj_factor") / base).alias("factor"),
            (pl.col("amount") / pl.col("volume")).alias("_raw_vwap"),
        ).with_columns(
            (pl.col("open") * pl.col("factor")).alias("open"),
            (pl.col("high") * pl.col("factor")).alias("high"),
            (pl.col("low") * pl.col("factor")).alias("low"),
            (pl.col("close") * pl.col("factor")).alias("close"),
            (pl.col("_raw_vwap") * pl.col("factor")).alias("vwap"),
            (pl.col("volume") / pl.col("factor")).alias("volume"),
            pl.col("trade_date").alias("date"),
        )
        # 验证 qlib_vwap / factor == amount / volume（用未覆写前的 raw_vwap）
        bad = adjusted.filter(
            (pl.col("vwap") / pl.col("factor") - pl.col("_raw_vwap")).abs() > 1e-9
        )
        if not bad.is_empty():
            raise ValueError(f"{symbol} vwap/factor != amount/volume")
        parts.append(adjusted.select(list(STAGING_COLUMNS)))

    return (
        pl.concat(parts)
        .with_columns(
            pl.col("symbol").cast(pl.String),
            pl.col("date").cast(pl.Date),
            *(pl.col(name).cast(pl.Float64) for name in STAGING_COLUMNS[2:]),
        )
        .sort(["symbol", "date"])
    )


@_snapshot_boundary("SNAPSHOT_INPUT_INVALID")
def build_snapshot_session_calendar(
    *, release: VerifiedG1Release, history_start: dt.date, history_end: dt.date,
) -> pl.DataFrame:
    """Project the strict SH open-session calendar from a reverified G1 release."""
    return _build_snapshot_session_calendar(
        source=_formal_snapshot_source(release),
        history_start=history_start,
        history_end=history_end,
    )


@_snapshot_boundary("SNAPSHOT_INPUT_INVALID")
def build_development_example_snapshot_session_calendar(
    *, release: VerifiedDevelopmentExampleG1Release,
    history_start: dt.date,
    history_end: dt.date,
) -> pl.DataFrame:
    return _build_snapshot_session_calendar(
        source=_development_snapshot_source(release),
        history_start=history_start,
        history_end=history_end,
    )


def _build_snapshot_session_calendar(
    *, source: _SnapshotSourceView,
    history_start: dt.date,
    history_end: dt.date,
) -> pl.DataFrame:
    if type(history_start) is not dt.date or type(history_end) is not dt.date:
        raise ValueError("history 日期必须为精确 date")
    if history_end < history_start:
        raise ValueError("history_end 不得早于 history_start")
    calendars = _read_snapshot_source_parquet(source, "trade_calendar.parquet")
    result = (
        calendars.filter(
            (pl.col("market") == "SH")
            & pl.col("is_open")
            & pl.col("date").is_between(history_start, history_end)
        )
        .select("date")
        .sort("date")
    )
    _validate_snapshot_calendar(result)
    return result


@_snapshot_boundary("SNAPSHOT_OUTPUT_INVALID")
def write_staging_by_symbol(frame: pl.DataFrame, output_dir: Path) -> tuple[Path, ...]:
    """每证券写入一个按日期升序的 Parquet；文件名为 Qlib 小写代码。"""
    if output_dir.exists():
        _require_empty_real_directory(output_dir, label="staging output")
    else:
        parent = output_dir.parent
        _require_real_directory(parent, label="staging parent")
        output_dir.mkdir()
    paths: list[Path] = []
    for symbol in frame.get_column("symbol").unique().sort().to_list():
        part = frame.filter(pl.col("symbol") == symbol).sort("date")
        path = output_dir / f"{to_qlib_symbol(symbol)}.parquet"
        _write_parquet(part, path)
        paths.append(path)
    return tuple(paths)


@_snapshot_boundary("SNAPSHOT_OUTPUT_INVALID")
def build_snapshot_artifact(
    *, release: VerifiedG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec, output_root: Path,
) -> SnapshotBuildResult:
    """Materialize one complete G2A snapshot inside an already-empty temp root."""
    source = _formal_snapshot_source(release)
    return _build_snapshot_artifact(
        source=source, config=config, spec=spec, output_root=output_root
    )


@_snapshot_boundary("SNAPSHOT_OUTPUT_INVALID")
def build_development_example_snapshot_artifact(
    *, release: VerifiedDevelopmentExampleG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec, output_root: Path,
) -> SnapshotBuildResult:
    """Build a G2A-shaped artifact in the isolated development trust domain."""
    source = _development_snapshot_source(release)
    return _build_snapshot_artifact(
        source=source, config=config, spec=spec, output_root=output_root
    )


def _build_snapshot_artifact(
    *, source: _SnapshotSourceView, config: LoadedM3Config,
    spec: SnapshotBuildSpec, output_root: Path,
) -> SnapshotBuildResult:
    try:
        _validate_build_inputs(source=source, config=config, spec=spec)
    except (TypeError, ValueError, OSError, pl.exceptions.PolarsError):
        raise M3SnapshotError("SNAPSHOT_INPUT_INVALID") from None
    _require_empty_real_directory(output_root, label="snapshot output_root")

    bars = _read_snapshot_source_parquet(source, "bar_1d.parquet")
    membership = _read_snapshot_source_parquet(
        source, "universe_membership.parquet"
    )
    calendars = _read_snapshot_source_parquet(source, "trade_calendar.parquet")
    calendar = _calendar_from_frame(
        calendars=calendars,
        history_start=spec.history_start,
        history_end=spec.history_end,
    )
    staging = _prepare_qlib_staging_frames(
        bars=bars,
        membership=membership,
        calendars=calendars,
        source=_SOURCE,
        universe=_UNIVERSE,
    ).filter(pl.col("date").is_between(spec.history_start, spec.history_end))
    if staging.is_empty():
        raise ValueError("snapshot staging 为空")
    staging_dates = set(staging.get_column("date").to_list())
    session_dates = set(calendar.get_column("date").to_list())
    if staging_dates != session_dates:
        raise ValueError("staging 日期并集必须精确等于 SH session calendar")

    calendar_path = output_root / _CALENDAR_NAME
    _write_parquet(calendar, calendar_path)
    staging_paths = write_staging_by_symbol(staging, output_root / _STAGING_DIR)
    entries = _artifact_entries(
        root=output_root,
        calendar_path=calendar_path,
        staging_paths=staging_paths,
    )
    manifest = _make_manifest(
        source=source,
        config=config,
        spec=spec,
        calendar=calendar,
        staging=staging,
        entries=entries,
    )
    manifest_bytes = _canonical_json_bytes(asdict(manifest))
    manifest_path = output_root / _MANIFEST_NAME
    _exclusive_write_bytes(manifest_path, manifest_bytes)
    return SnapshotBuildResult(
        root=output_root.resolve(strict=True),
        manifest=manifest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


@_snapshot_boundary("SNAPSHOT_IDENTITY_MISMATCH")
def build_snapshot_request_record(
    *, release: VerifiedG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec, result: SnapshotBuildResult,
) -> SnapshotRequestRecordV1:
    """Build the immutable request-key to content-id mapping without publishing it."""
    return _build_snapshot_request_record(
        source=_formal_snapshot_source(release), config=config, spec=spec,
        result=result,
    )


@_snapshot_boundary("SNAPSHOT_IDENTITY_MISMATCH")
def build_development_example_snapshot_request_record(
    *, release: VerifiedDevelopmentExampleG1Release, config: LoadedM3Config,
    spec: SnapshotBuildSpec, result: SnapshotBuildResult,
) -> SnapshotRequestRecordV1:
    return _build_snapshot_request_record(
        source=_development_snapshot_source(release), config=config, spec=spec,
        result=result,
    )


def _build_snapshot_request_record(
    *, source: _SnapshotSourceView, config: LoadedM3Config,
    spec: SnapshotBuildSpec, result: SnapshotBuildResult,
) -> SnapshotRequestRecordV1:
    _validate_build_inputs(source=source, config=config, spec=spec)
    rebuilt = read_snapshot_manifest(result.root / _MANIFEST_NAME)
    raw = (result.root / _MANIFEST_NAME).read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    if rebuilt != result.manifest or manifest_sha != result.manifest_sha256:
        raise ValueError("snapshot build result 与磁盘 manifest 不一致")
    return SnapshotRequestRecordV1(
        schema_version="m3-snapshot-request-v1",
        snapshot_request_key=spec.snapshot_request_key,
        snapshot_id=rebuilt.snapshot_id,
        snapshot_manifest_sha256=manifest_sha,
        g1_release_id=source.source_id,
        g1_release_manifest_sha256=source.manifest_sha256,
        snapshot_config_sha256=spec.snapshot_config_sha256,
        code_version=spec.code_version,
        history_start=rebuilt.history_start,
        history_end=rebuilt.history_end,
        signal_start=rebuilt.signal_start,
        signal_end=rebuilt.signal_end,
    )


def snapshot_request_record_bytes(record: SnapshotRequestRecordV1) -> bytes:
    """Return the only canonical byte representation accepted for publication."""
    if type(record) is not SnapshotRequestRecordV1:
        raise M3SnapshotError("SNAPSHOT_INPUT_INVALID")
    return _canonical_json_bytes(asdict(record))


@_snapshot_boundary("SNAPSHOT_IDENTITY_MISMATCH")
def verify_snapshot_build_result(
    *, snapshot_root: Path, release: VerifiedG1Release,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
) -> SnapshotBuildResult:
    """Verify a complete temp/final snapshot before request/receipt publication."""
    return _verify_snapshot_build_result(
        snapshot_root=snapshot_root, source=_formal_snapshot_source(release),
        config=config, spec=spec,
    )


@_snapshot_boundary("SNAPSHOT_IDENTITY_MISMATCH")
def verify_development_example_snapshot_build_result(
    *, snapshot_root: Path, release: VerifiedDevelopmentExampleG1Release,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
) -> SnapshotBuildResult:
    return _verify_snapshot_build_result(
        snapshot_root=snapshot_root, source=_development_snapshot_source(release),
        config=config, spec=spec,
    )


def _verify_snapshot_build_result(
    *, snapshot_root: Path, source: _SnapshotSourceView,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
) -> SnapshotBuildResult:
    _validate_build_inputs(source=source, config=config, spec=spec)
    _require_real_directory(snapshot_root, label="snapshot root")
    root_entries = {entry.name for entry in os.scandir(snapshot_root)}
    if root_entries != {_MANIFEST_NAME, _CALENDAR_NAME, _STAGING_DIR}:
        raise ValueError("snapshot root 文件树非法")
    _require_real_directory(snapshot_root / _STAGING_DIR, label="snapshot staging")
    manifest_path = snapshot_root / _MANIFEST_NAME
    manifest = read_snapshot_manifest(manifest_path)
    manifest_raw = _read_regular_file(manifest_path, label="snapshot manifest")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    _verify_manifest_identity(
        manifest=manifest, source=source, config=config, spec=spec
    )
    _verify_manifest_files(snapshot_root, manifest)
    return SnapshotBuildResult(
        root=snapshot_root.resolve(strict=True), manifest=manifest,
        manifest_sha256=manifest_sha,
    )


@_snapshot_boundary("SNAPSHOT_OUTPUT_INVALID")
def read_snapshot_manifest(path: Path) -> SnapshotManifestV1:
    """Read one canonical, strict G2A manifest."""
    raw = _read_regular_file(path, label="snapshot manifest")
    payload = _strict_json_object(raw, label="snapshot manifest")
    expected = {
        "schema_version", "snapshot_id", "config_version", "snapshot_config_sha256",
        "g1_release_id", "g1_release_manifest_sha256", "source", "universe",
        "history_start", "history_end", "signal_start", "signal_end", "row_count",
        "symbol_count", "min_date", "max_date", "session_calendar_sha256",
        "session_count", "session_start", "session_end", "staging_format",
        "staging_schema_version", "adjustment_formula_version",
        "adjustment_spec_sha256", "files",
    }
    _require_exact_keys(payload, expected, label="snapshot manifest")
    raw_files = payload["files"]
    if type(raw_files) is not list:
        raise ValueError("snapshot manifest files 必须为数组")
    file_keys = {
        "path", "sha256", "size_bytes", "row_count", "schema_name", "symbol",
        "min_date", "max_date",
    }
    files: list[SnapshotArtifactEntryV1] = []
    for item in raw_files:
        if type(item) is not dict:
            raise ValueError("snapshot manifest file entry 非法")
        _require_exact_keys(item, file_keys, label="snapshot file entry")
        files.append(SnapshotArtifactEntryV1(
            path=item["path"], sha256=item["sha256"], size_bytes=item["size_bytes"],
            row_count=item["row_count"], schema_name=item["schema_name"],
            symbol=item["symbol"], min_date=_parse_date(item["min_date"]),
            max_date=_parse_date(item["max_date"]),
        ))
    values = dict(payload)
    values["files"] = tuple(files)
    for name in (
        "history_start", "history_end", "signal_start", "signal_end", "min_date",
        "max_date", "session_start", "session_end",
    ):
        values[name] = _parse_date(values[name])
    manifest = SnapshotManifestV1(**cast(Any, values))
    if _canonical_json_bytes(asdict(manifest)) != raw:
        raise ValueError("snapshot manifest 不是 canonical JSON")
    if _snapshot_id(manifest) != manifest.snapshot_id:
        raise ValueError("snapshot_id 与 manifest 内容不一致")
    return manifest


@_snapshot_boundary("SNAPSHOT_OUTPUT_INVALID")
def read_snapshot_request_record(path: Path) -> SnapshotRequestRecordV1:
    """Read one canonical, strict request mapping."""
    raw = _read_regular_file(path, label="snapshot request")
    payload = _strict_json_object(raw, label="snapshot request")
    expected = {
        "schema_version", "snapshot_request_key", "snapshot_id",
        "snapshot_manifest_sha256", "g1_release_id", "g1_release_manifest_sha256",
        "snapshot_config_sha256", "code_version", "history_start", "history_end",
        "signal_start", "signal_end",
    }
    _require_exact_keys(payload, expected, label="snapshot request")
    values = dict(payload)
    for name in ("history_start", "history_end", "signal_start", "signal_end"):
        values[name] = _parse_date(values[name])
    record = SnapshotRequestRecordV1(**cast(Any, values))
    if _canonical_json_bytes(asdict(record)) != raw:
        raise ValueError("snapshot request 不是 canonical JSON")
    return record


@_snapshot_boundary("SNAPSHOT_IDENTITY_MISMATCH")
def verify_snapshot_artifact(
    *, snapshot_root: Path, snapshot_request_path: Path,
    snapshot_receipt_path: Path, release: VerifiedG1Release,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedSnapshotArtifact:
    """Rebuild physical, logical, identity and exact StageReceipt closure."""
    parts = _verify_snapshot_artifact(
        snapshot_root=snapshot_root,
        snapshot_request_path=snapshot_request_path,
        snapshot_receipt_path=snapshot_receipt_path,
        source=_formal_snapshot_source(release),
        config=config,
        spec=spec,
        artifact_roots=artifact_roots,
        expected_stage="snapshot",
    )
    return VerifiedSnapshotArtifact(
        root=parts.root, request=parts.request,
        request_sha256=parts.request_sha256, manifest=parts.manifest,
        manifest_sha256=parts.manifest_sha256,
        snapshot_receipt_sha256=parts.snapshot_receipt_sha256,
        session_calendar_path=parts.session_calendar_path,
        staging_paths=parts.staging_paths,
    )


@_snapshot_boundary("SNAPSHOT_IDENTITY_MISMATCH")
def verify_development_example_snapshot_artifact(
    *, snapshot_root: Path, snapshot_request_path: Path,
    snapshot_receipt_path: Path, release: VerifiedDevelopmentExampleG1Release,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
    artifact_roots: Mapping[str, Path],
) -> VerifiedDevelopmentExampleSnapshotArtifact:
    source = _development_snapshot_source(release)
    parts = _verify_snapshot_artifact(
        snapshot_root=snapshot_root,
        snapshot_request_path=snapshot_request_path,
        snapshot_receipt_path=snapshot_receipt_path,
        source=source,
        config=config,
        spec=spec,
        artifact_roots=artifact_roots,
        expected_stage="development-snapshot",
    )
    assert source.development_example_id is not None
    return VerifiedDevelopmentExampleSnapshotArtifact(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=source.development_example_id,
        root=parts.root, request=parts.request,
        request_sha256=parts.request_sha256, manifest=parts.manifest,
        manifest_sha256=parts.manifest_sha256,
        snapshot_receipt_sha256=parts.snapshot_receipt_sha256,
        session_calendar_path=parts.session_calendar_path,
        staging_paths=parts.staging_paths,
    )


def _verify_snapshot_artifact(
    *, snapshot_root: Path, snapshot_request_path: Path,
    snapshot_receipt_path: Path, source: _SnapshotSourceView,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
    artifact_roots: Mapping[str, Path], expected_stage: str,
) -> _VerifiedSnapshotParts:
    _validate_build_inputs(source=source, config=config, spec=spec)
    _require_real_directory(snapshot_root, label="snapshot root")
    root_entries = {entry.name for entry in os.scandir(snapshot_root)}
    if root_entries != {_MANIFEST_NAME, _CALENDAR_NAME, _STAGING_DIR}:
        raise ValueError("snapshot root 文件树非法")
    _require_real_directory(snapshot_root / _STAGING_DIR, label="snapshot staging")

    manifest_path = snapshot_root / _MANIFEST_NAME
    manifest = read_snapshot_manifest(manifest_path)
    manifest_raw = _read_regular_file(manifest_path, label="snapshot manifest")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    request = read_snapshot_request_record(snapshot_request_path)
    request_raw = _read_regular_file(snapshot_request_path, label="snapshot request")
    request_sha = hashlib.sha256(request_raw).hexdigest()
    _verify_request_and_manifest(
        request=request, manifest=manifest, manifest_sha=manifest_sha,
        source=source, config=config, spec=spec,
    )
    calendar_path, staging_paths = _verify_manifest_files(snapshot_root, manifest)

    receipt = verify_stage_receipt(
        receipt_path=snapshot_receipt_path, artifact_roots=artifact_roots
    )
    if receipt is None:
        raise ValueError("snapshot receipt 缺失")
    if receipt.stage != expected_stage or receipt.scope != "SNAPSHOT":
        raise ValueError("snapshot receipt stage/scope 非法")
    if receipt.scope_key != spec.snapshot_request_key:
        raise ValueError("snapshot receipt scope_key 非法")
    expected_inputs = {
        source.manifest_path.resolve(strict=True),
        *(dict(source.artifact_paths)[name].resolve(strict=True) for name in (
            "bar_1d.parquet", "universe_membership.parquet", "trade_calendar.parquet"
        )),
    }
    expected_outputs = {
        snapshot_request_path.resolve(strict=True), manifest_path.resolve(strict=True),
        calendar_path.resolve(strict=True),
        *(path.resolve(strict=True) for path in staging_paths),
    }
    if _receipt_paths(receipt.inputs, artifact_roots) != expected_inputs:
        raise ValueError("snapshot receipt inputs 闭包非法")
    if _receipt_paths(receipt.outputs, artifact_roots) != expected_outputs:
        raise ValueError("snapshot receipt outputs 闭包非法")
    receipt_raw = _read_regular_file(snapshot_receipt_path, label="snapshot receipt")
    return _VerifiedSnapshotParts(
        root=snapshot_root.resolve(strict=True), request=request,
        request_sha256=request_sha, manifest=manifest, manifest_sha256=manifest_sha,
        snapshot_receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
        session_calendar_path=calendar_path.resolve(strict=True),
        staging_paths=tuple(path.resolve(strict=True) for path in staging_paths),
    )


def build_snapshot_manifest(
    *,
    files: Sequence[Path],
    source: str,
    universe: str,
    g1_release_id: str,
    g1_release_manifest_sha256: str,
    schema_version: str,
    snapshot_config_sha256: str,
    config_version: str,
) -> dict[str, object]:
    """构建可复现 manifest；元数据从 staging 文件计算，不可由调用者伪造。"""
    if not files:
        raise ValueError("files 不得为空")

    file_entries: list[dict[str, object]] = []
    total_rows = 0
    symbols: set[str] = set()
    min_dates: list[str] = []
    max_dates: list[str] = []
    seen_paths: set[str] = set()
    seen_rel: set[str] = set()
    seen_symbols: set[str] = set()

    for path in sorted(files, key=lambda item: item.name):
        resolved = str(path.resolve())
        if resolved in seen_paths:
            raise ValueError(f"重复文件路径: {path}")
        seen_paths.add(resolved)

        relative_path = path.name
        if relative_path in seen_rel:
            raise ValueError(f"重复 relative_path: {relative_path}")
        seen_rel.add(relative_path)

        payload = path.read_bytes()
        frame = pl.read_parquet(path)
        if frame.is_empty():
            raise ValueError(f"staging Parquet 为空: {relative_path}")
        if list(frame.columns) != list(STAGING_COLUMNS):
            raise ValueError(
                f"staging 列必须精确等于 STAGING_COLUMNS: {relative_path}"
            )

        symbol_vals = frame.get_column("symbol").unique().to_list()
        if len(symbol_vals) != 1:
            raise ValueError(f"staging 文件必须单证券: {relative_path}")
        symbol = str(symbol_vals[0])
        if symbol in seen_symbols:
            raise ValueError(f"重复 symbol: {symbol}")
        seen_symbols.add(symbol)

        expected_name = f"{to_qlib_symbol(symbol)}.parquet"
        if relative_path != expected_name:
            raise ValueError(
                f"文件名必须等于 to_qlib_symbol(symbol)+'.parquet'："
                f"期望 {expected_name}，收到 {relative_path}"
            )

        dates = frame.get_column("date").to_list()
        if len(dates) != len(set(dates)):
            raise ValueError(f"日期不唯一: {relative_path}")
        if dates != sorted(dates):
            raise ValueError(f"日期必须严格升序: {relative_path}")

        _reject_non_finite_staging(frame, relative_path)

        row_count = frame.height
        min_date = frame.get_column("date").min()
        max_date = frame.get_column("date").max()
        min_iso = _iso_date(min_date)
        max_iso = _iso_date(max_date)
        file_entries.append(
            {
                "relative_path": relative_path,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "symbol": symbol,
                "row_count": row_count,
                "min_date": min_iso,
                "max_date": max_iso,
            }
        )
        total_rows += row_count
        symbols.add(symbol)
        min_dates.append(min_iso)
        max_dates.append(max_iso)

    manifest: dict[str, object] = {
        "source": source,
        "universe": universe,
        "g1_release_id": g1_release_id,
        "g1_release_manifest_sha256": g1_release_manifest_sha256,
        "row_count": total_rows,
        "symbol_count": len(symbols),
        "min_date": min(min_dates),
        "max_date": max(max_dates),
        "schema_version": schema_version,
        "config_version": config_version,
        "snapshot_config_sha256": snapshot_config_sha256,
        "adjustment": dict(ADJUSTMENT_SPEC),
        "files": file_entries,
    }
    manifest["snapshot_id"] = _stable_hash(
        {key: value for key, value in manifest.items() if key != "snapshot_id"}
    )
    return manifest


def snapshot_id_from_manifest(manifest: Mapping[str, Any]) -> str:
    body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    return _stable_hash(body)


def validate_provider(*, provider_dir: Path, expected: DatasetSnapshot) -> None:
    """Legacy fail-closed seam; real provider validation belongs to G2B/G2C."""
    if not provider_dir.exists():
        raise FileNotFoundError(f"provider 目录不存在: {provider_dir}")
    if expected.symbol_count <= 0:
        raise ValueError("expected.symbol_count 必须为正")

    feature_dir = provider_dir / "features"
    if not feature_dir.exists() or not any(feature_dir.iterdir()):
        raise RuntimeError(
            "provider 未 materialize（features 为空），G2 逐字段回读未验证"
        )
    raise RuntimeError(
        "当前环境未实现 3 证券 × 20 日期逐字段回读；G2 未验证"
    )


def _reverify_release(release: VerifiedG1Release) -> VerifiedG1Release:
    if type(release) is not VerifiedG1Release:
        raise ValueError("release 必须为 VerifiedG1Release")
    return verify_g1_release(release=release.release)


def _formal_snapshot_source(release: VerifiedG1Release) -> _SnapshotSourceView:
    verified = _reverify_release(release)
    return _SnapshotSourceView(
        trust_domain="FORMAL_G1",
        source_id=verified.manifest.release_id,
        development_example_id=None,
        development_request_key=None,
        manifest_sha256=verified.manifest_sha256,
        manifest_path=verified.release.manifest_path,
        history_start=verified.manifest.history_start,
        history_end=verified.manifest.history_end,
        signal_start=verified.manifest.signal_start,
        signal_end=verified.manifest.signal_end,
        files=verified.manifest.files,
        artifact_paths=verified.artifact_paths,
    )


def _development_snapshot_source(
    release: VerifiedDevelopmentExampleG1Release,
) -> _SnapshotSourceView:
    if type(release) is not VerifiedDevelopmentExampleG1Release:
        raise ValueError("release 必须为 VerifiedDevelopmentExampleG1Release")
    verified = verify_development_example_g1_release(root=release.release.root)
    return _SnapshotSourceView(
        trust_domain="DEVELOPMENT_EXAMPLE_G1",
        source_id=verified.manifest.contract_release_id,
        development_example_id=verified.manifest.example_id,
        development_request_key=verified.request.example_request_key,
        manifest_sha256=verified.manifest_sha256,
        manifest_path=verified.release.manifest_path,
        history_start=verified.manifest.history_start,
        history_end=verified.manifest.history_end,
        signal_start=verified.manifest.signal_start,
        signal_end=verified.manifest.signal_end,
        files=verified.manifest.files,
        artifact_paths=verified.artifact_paths,
    )


def _read_snapshot_source_parquet(
    source: _SnapshotSourceView, name: str,
) -> pl.DataFrame:
    manifest_raw = _read_regular_file(
        source.manifest_path, label="G1 release manifest"
    )
    if hashlib.sha256(manifest_raw).hexdigest() != source.manifest_sha256:
        raise ValueError("G1 release manifest 读取前漂移")
    path = dict(source.artifact_paths).get(name)
    if path is None:
        raise ValueError("G1 release artifact path 缺失")
    entry = next((item for item in source.files if item.path == name), None)
    if entry is None:
        raise ValueError("G1 release manifest artifact 缺失")
    raw = _read_regular_file(path, label="G1 release artifact")
    if len(raw) != entry.size_bytes or hashlib.sha256(raw).hexdigest() != entry.sha256:
        raise ValueError("G1 release artifact 读取前漂移")
    return pl.read_parquet(path)


def _validate_build_inputs(
    *, source: _SnapshotSourceView, config: LoadedM3Config, spec: SnapshotBuildSpec,
) -> None:
    if type(config) is not LoadedM3Config or type(spec) is not SnapshotBuildSpec:
        raise ValueError("snapshot config/spec 类型非法")
    config_hash = canonical_config_sha256(selector="snapshot", document=config.document)
    if config_hash != config.snapshot_config_sha256:
        raise ValueError("LoadedM3Config snapshot hash 非法")
    if spec.snapshot_config_sha256 != config_hash:
        raise ValueError("SnapshotBuildSpec config hash 非法")
    if spec.config_version != config.config_version:
        raise ValueError("SnapshotBuildSpec config_version 非法")
    if (spec.history_start, spec.history_end) != (
        source.history_start, source.history_end,
    ):
        raise ValueError("SnapshotBuildSpec history window 非法")
    data = config.section("data")
    signal_start = data["start_date"]
    signal_end = data["end_date"]
    if type(signal_start) is not dt.date or type(signal_end) is not dt.date:
        raise ValueError("snapshot config signal 日期非法")
    if (source.signal_start, source.signal_end) != (signal_start, signal_end):
        raise ValueError("G1 release 与 snapshot config signal window 不一致")
    if not spec.history_start <= signal_start <= signal_end <= spec.history_end:
        raise ValueError("snapshot history/signal 日期闭包非法")
    if source.trust_domain == "FORMAL_G1":
        expected_key = compute_snapshot_request_key(
            g1_release_id=source.source_id,
            g1_release_manifest_sha256=source.manifest_sha256,
            snapshot_config_sha256=config_hash,
            code_version=spec.code_version,
        )
    else:
        assert source.development_request_key is not None
        expected_key = compute_development_snapshot_request_key_from_parts(
            development_request_key=source.development_request_key,
            contract_release_id=source.source_id,
            manifest_sha256=source.manifest_sha256,
            snapshot_config_sha256=config_hash,
            code_version=spec.code_version,
        )
    if spec.snapshot_request_key != expected_key:
        raise ValueError("snapshot_request_key 非法")
    if spec.adjustment_formula_version != ADJUSTMENT_SPEC["formula_version"]:
        raise ValueError("snapshot adjustment formula version 非法")


def _calendar_from_frame(
    *, calendars: pl.DataFrame, history_start: dt.date, history_end: dt.date,
) -> pl.DataFrame:
    required = {"market", "date", "is_open"}
    if not required.issubset(calendars.columns):
        raise ValueError("G1 calendar 缺少 snapshot 所需字段")
    result = (
        calendars.filter(
            (pl.col("market") == "SH")
            & pl.col("is_open")
            & pl.col("date").is_between(history_start, history_end)
        )
        .select("date")
        .sort("date")
    )
    _validate_snapshot_calendar(result)
    return result


def _artifact_entries(
    *, root: Path, calendar_path: Path, staging_paths: Sequence[Path],
) -> tuple[SnapshotArtifactEntryV1, ...]:
    entries = [_entry_from_parquet(
        root=root, path=calendar_path, schema_name="SnapshotSessionCalendarSchema",
        symbol=None,
    )]
    for path in staging_paths:
        frame = _read_staging_file(path)
        symbol = frame.item(0, "symbol")
        entries.append(_entry_from_parquet(
            root=root, path=path, schema_name="M3QlibStagingV1", symbol=symbol,
            frame=frame,
        ))
    return tuple(sorted(entries, key=lambda item: item.path))


def _entry_from_parquet(
    *, root: Path, path: Path, schema_name: str, symbol: str | None,
    frame: pl.DataFrame | None = None,
) -> SnapshotArtifactEntryV1:
    raw = _read_regular_file(path, label="snapshot parquet")
    current = pl.read_parquet(path) if frame is None else frame
    if current.is_empty():
        raise ValueError("snapshot parquet 不得为空")
    date_col = "date"
    dates = current.get_column(date_col)
    min_date = dates.min()
    max_date = dates.max()
    if type(min_date) is not dt.date or type(max_date) is not dt.date:
        raise ValueError("snapshot parquet 日期类型非法")
    relative = path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()
    return SnapshotArtifactEntryV1(
        path=relative, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
        row_count=current.height, schema_name=schema_name, symbol=symbol,
        min_date=min_date, max_date=max_date,
    )


def _make_manifest(
    *, source: _SnapshotSourceView, config: LoadedM3Config, spec: SnapshotBuildSpec,
    calendar: pl.DataFrame, staging: pl.DataFrame,
    entries: tuple[SnapshotArtifactEntryV1, ...],
) -> SnapshotManifestV1:
    data = config.section("data")
    signal_start = data["start_date"]
    signal_end = data["end_date"]
    if type(signal_start) is not dt.date or type(signal_end) is not dt.date:
        raise ValueError("snapshot signal 日期非法")
    dates = calendar.get_column("date").to_list()
    staging_dates = staging.get_column("date")
    min_date = staging_dates.min()
    max_date = staging_dates.max()
    if type(min_date) is not dt.date or type(max_date) is not dt.date:
        raise ValueError("snapshot staging 日期类型非法")
    base = SnapshotManifestV1(
        schema_version="m3-snapshot-manifest-v1", snapshot_id="0" * 64,
        config_version=config.config_version,
        snapshot_config_sha256=spec.snapshot_config_sha256,
        g1_release_id=source.source_id,
        g1_release_manifest_sha256=source.manifest_sha256,
        source="tushare", universe="CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1",
        history_start=spec.history_start, history_end=spec.history_end,
        signal_start=signal_start, signal_end=signal_end,
        row_count=staging.height,
        symbol_count=staging.get_column("symbol").n_unique(),
        min_date=min_date, max_date=max_date,
        session_calendar_sha256=_sha256_json([item.isoformat() for item in dates]),
        session_count=len(dates), session_start=dates[0], session_end=dates[-1],
        staging_format="parquet", staging_schema_version=spec.staging_schema_version,
        adjustment_formula_version="qlib_yahoo_like_v1",
        adjustment_spec_sha256=_sha256_json(dict(ADJUSTMENT_SPEC)), files=entries,
    )
    values = asdict(base)
    values["snapshot_id"] = _sha256_json({
        key: value for key, value in values.items() if key != "snapshot_id"
    })
    values["files"] = entries
    return SnapshotManifestV1(**cast(Any, values))


def _snapshot_id(manifest: SnapshotManifestV1) -> str:
    values = asdict(manifest)
    return _sha256_json({key: value for key, value in values.items() if key != "snapshot_id"})


def _verify_request_and_manifest(
    *, request: SnapshotRequestRecordV1, manifest: SnapshotManifestV1,
    manifest_sha: str, source: _SnapshotSourceView, config: LoadedM3Config,
    spec: SnapshotBuildSpec,
) -> None:
    data = config.section("data")
    expected = (
        spec.snapshot_request_key, manifest.snapshot_id, manifest_sha,
        source.source_id, source.manifest_sha256,
        spec.snapshot_config_sha256, spec.code_version, spec.history_start,
        spec.history_end, data["start_date"], data["end_date"],
    )
    actual = (
        request.snapshot_request_key, request.snapshot_id,
        request.snapshot_manifest_sha256, request.g1_release_id,
        request.g1_release_manifest_sha256, request.snapshot_config_sha256,
        request.code_version, request.history_start, request.history_end,
        request.signal_start, request.signal_end,
    )
    if actual != expected:
        raise ValueError("snapshot request mapping 与 verified 输入不一致")
    _verify_manifest_identity(
        manifest=manifest, source=source, config=config, spec=spec
    )


def _verify_manifest_identity(
    *, manifest: SnapshotManifestV1, source: _SnapshotSourceView,
    config: LoadedM3Config, spec: SnapshotBuildSpec,
) -> None:
    data = config.section("data")
    manifest_expected = (
        config.config_version, spec.snapshot_config_sha256,
        source.source_id, source.manifest_sha256,
        spec.history_start, spec.history_end, data["start_date"], data["end_date"],
        spec.staging_schema_version, spec.adjustment_formula_version,
    )
    manifest_actual = (
        manifest.config_version, manifest.snapshot_config_sha256,
        manifest.g1_release_id, manifest.g1_release_manifest_sha256,
        manifest.history_start, manifest.history_end, manifest.signal_start,
        manifest.signal_end, manifest.staging_schema_version,
        manifest.adjustment_formula_version,
    )
    if manifest_actual != manifest_expected:
        raise ValueError("snapshot manifest 与 verified 输入不一致")


def _verify_manifest_files(
    root: Path, manifest: SnapshotManifestV1,
) -> tuple[Path, tuple[Path, ...]]:
    calendar_path = root / _CALENDAR_NAME
    staging_dir = root / _STAGING_DIR
    staging_names = {entry.name for entry in os.scandir(staging_dir)}
    expected_names = {
        Path(item.path).name for item in manifest.files if item.path.startswith("staging/")
    }
    if staging_names != expected_names:
        raise ValueError("snapshot staging 文件集合非法")
    staging_paths = tuple(staging_dir / name for name in sorted(expected_names))
    rebuilt_entries = _artifact_entries(
        root=root, calendar_path=calendar_path, staging_paths=staging_paths,
    )
    if rebuilt_entries != manifest.files:
        raise ValueError("snapshot manifest file entries 与物理文件不一致")
    calendar = pl.read_parquet(calendar_path)
    _validate_snapshot_calendar(calendar)
    frames = tuple(_read_staging_file(path) for path in staging_paths)
    staging = pl.concat(frames).sort(["symbol", "date"])
    dates = calendar.get_column("date").to_list()
    if set(staging.get_column("date").to_list()) != set(dates):
        raise ValueError("snapshot staging 日期并集与 calendar 不一致")
    expected_summary = (
        staging.height, staging.get_column("symbol").n_unique(),
        staging.get_column("date").min(), staging.get_column("date").max(),
        _sha256_json([item.isoformat() for item in dates]), len(dates),
        dates[0], dates[-1], _sha256_json(dict(ADJUSTMENT_SPEC)),
    )
    actual_summary = (
        manifest.row_count, manifest.symbol_count, manifest.min_date,
        manifest.max_date, manifest.session_calendar_sha256,
        manifest.session_count, manifest.session_start, manifest.session_end,
        manifest.adjustment_spec_sha256,
    )
    if actual_summary != expected_summary:
        raise ValueError("snapshot manifest 聚合字段非法")
    return calendar_path, staging_paths


def _read_staging_file(path: Path) -> pl.DataFrame:
    _read_regular_file(path, label="snapshot staging")
    frame = pl.read_parquet(path)
    if list(frame.columns) != list(STAGING_COLUMNS) or frame.is_empty():
        raise ValueError("snapshot staging schema 非法")
    expected_schema = {
        "symbol": pl.String,
        "date": pl.Date,
        **{name: pl.Float64 for name in STAGING_COLUMNS[2:]},
    }
    if frame.schema != expected_schema:
        raise ValueError("snapshot staging dtype 非法")
    symbol_values = frame.get_column("symbol").unique().to_list()
    if len(symbol_values) != 1 or type(symbol_values[0]) is not str:
        raise ValueError("snapshot staging 必须为单证券")
    symbol = symbol_values[0]
    if path.name != f"{to_qlib_symbol(symbol)}.parquet":
        raise ValueError("snapshot staging 文件名 codec 非法")
    if from_qlib_symbol(path.stem) != symbol:
        raise ValueError("snapshot staging 文件名不可逆")
    dates = frame.get_column("date").to_list()
    if not dates or dates != sorted(set(dates)):
        raise ValueError("snapshot staging 日期必须唯一严格递增")
    _reject_non_finite_staging(frame, path.name)
    return frame


def _validate_snapshot_calendar(frame: pl.DataFrame) -> None:
    if frame.columns != ["date"] or frame.schema["date"] != pl.Date:
        raise ValueError("snapshot session calendar schema 非法")
    dates = frame.get_column("date").to_list()
    if not dates or dates != sorted(set(dates)):
        raise ValueError("snapshot session calendar 必须非空唯一严格递增")
    SnapshotSessionCalendarSchema.validate(frame)


def _receipt_paths(
    digests: Sequence[ArtifactDigest], artifact_roots: Mapping[str, Path],
) -> set[Path]:
    result: set[Path] = set()
    for digest in digests:
        root = artifact_roots.get(digest.root_alias)
        if root is None:
            raise ValueError("snapshot receipt root alias 非法")
        result.add((root / Path(digest.relative_path)).resolve(strict=True))
    return result


def _strict_json_object(raw: bytes, *, label: str) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label} 含重复 JSON key")
            result[key] = value
        return result

    def reject_constant(_: str) -> object:
        raise ValueError(f"{label} 含 non-finite JSON number")

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError(f"{label} JSON 非法") from None
    if type(value) is not dict:
        raise ValueError(f"{label} 顶层必须为 object")
    return value


def _require_exact_keys(
    payload: Mapping[str, object], expected: set[str], *, label: str,
) -> None:
    if set(payload) != expected:
        raise ValueError(f"{label} 字段集合非法")


def _parse_date(value: object) -> dt.date:
    if type(value) is not str:
        raise ValueError("snapshot 日期必须为 ISO 字符串")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError("snapshot 日期格式非法") from None
    if parsed.isoformat() != value:
        raise ValueError("snapshot 日期必须为 canonical ISO")
    return parsed


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, default=_json_default, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if type(value) is dt.date:
        return value.isoformat()
    raise TypeError(f"不可序列化的 snapshot 类型: {type(value).__name__}")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _read_regular_file(path: Path, *, label: str) -> bytes:
    _reject_ancestor_links(path.parent, label=label)
    try:
        st = os.lstat(path)
    except OSError:
        raise ValueError(f"{label} 不可读") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise ValueError(f"{label} 必须为单链接普通文件")
    if _is_reparse(st):
        raise ValueError(f"{label} 不得为 reparse point")
    try:
        return path.read_bytes()
    except OSError:
        raise ValueError(f"{label} 不可读") from None


def _require_real_directory(path: Path, *, label: str) -> None:
    _reject_ancestor_links(path.parent, label=label)
    try:
        st = os.lstat(path)
    except OSError:
        raise ValueError(f"{label} 必须已存在") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or _is_reparse(st):
        raise ValueError(f"{label} 必须为真实目录")


def _require_empty_real_directory(path: Path, *, label: str) -> None:
    _require_real_directory(path, label=label)
    try:
        if any(os.scandir(path)):
            raise ValueError(f"{label} 必须为空")
    except OSError:
        raise ValueError(f"{label} 不可遍历") from None


def _is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _reject_ancestor_links(path: Path, *, label: str) -> None:
    current = path.absolute()
    for candidate in (current, *current.parents):
        try:
            st = os.lstat(candidate)
        except OSError:
            raise ValueError(f"{label} ancestor 不可读") from None
        if stat.S_ISLNK(st.st_mode) or _is_reparse(st):
            raise ValueError(f"{label} ancestor 不得为 symlink/reparse")


def _exclusive_write_bytes(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise ValueError("snapshot 文件已存在") from None
    except OSError:
        raise ValueError("snapshot 文件写入失败") from None


def _write_parquet(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(
        path,
        compression="zstd",
        compression_level=3,
        statistics=True,
        row_group_size=65536,
        use_pyarrow=False,
    )


def _iso_date(value: object) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_duplicates(bars: pl.DataFrame) -> None:
    dup = bars.group_by("symbol", "trade_date").len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise ValueError("选中 source 存在重复 (symbol, trade_date)")


def _reject_invalid_rows(bars: pl.DataFrame) -> None:
    numeric_cols = ("open", "high", "low", "close", "volume", "amount", "adj_factor")
    for col in numeric_cols:
        series = bars.get_column(col)
        if series.null_count() > 0:
            raise ValueError(f"选中 source 存在非法 OHLC/amount/volume/factor: {col} null")
        values = series.to_list()
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"选中 source 存在非法 OHLC/amount/volume/factor: {col} 非数值"
                )
            if not math.isfinite(float(value)):
                raise ValueError(
                    f"选中 source 存在非法 OHLC/amount/volume/factor: {col} 非 finite"
                )

    bad = bars.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("volume") <= 0)
        | (pl.col("amount") <= 0)
        | (pl.col("adj_factor") <= 0)
    )
    if not bad.is_empty():
        raise ValueError("选中 source 存在非正 OHLC/amount/volume/factor")


def _reject_non_finite_staging(frame: pl.DataFrame, relative_path: str) -> None:
    for col in ("open", "high", "low", "close", "vwap", "volume", "factor"):
        series = frame.get_column(col)
        if series.null_count() > 0:
            raise ValueError(f"{relative_path} 存在非 finite 数值: {col}")
        for value in series.to_list():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{relative_path} 存在非 finite 数值: {col}")
            if not math.isfinite(float(value)):
                raise ValueError(f"{relative_path} 存在非 finite 数值: {col}")
