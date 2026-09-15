"""Read one bounded, receipt-backed source slice for M2 forward observation."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Protocol, cast

import polars as pl

from quant.domain import ResearchPrice1dSchema, TradeCalendarSchema

_ADJUSTMENT_METHOD = "TOTAL_RETURN_DIVIDEND"
_CALENDAR_MARKETS = ("SH", "SZ")
_DATE_DIRECTORY = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")
_MARKET_DIRECTORY = re.compile(r"^market=(HK|SH|SZ)$")
_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ)$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_SCHEMA = "m2-forward-source-receipt-v1"
_SNAPSHOT_DOMAIN = "m2-forward-source-snapshot-id-v1"


class M2ForwardSourceError(ValueError):
    """Stable, path-free failure for an invalid or unstable source read."""


def _invalid_source() -> NoReturn:
    raise M2ForwardSourceError("M2_FORWARD_SOURCE_INVALID") from None


@dataclass(frozen=True, slots=True)
class M2ForwardSourceSlice:
    """Validated frames and exact canonical receipt from one stable read."""

    prices: pl.DataFrame
    calendars: pl.DataFrame
    source_snapshot_id: str
    source_receipt: bytes

    def __post_init__(self) -> None:
        if (
            type(self.prices) is not pl.DataFrame
            or type(self.calendars) is not pl.DataFrame
            or type(self.source_snapshot_id) is not str
            or _HEX64.fullmatch(self.source_snapshot_id) is None
            or type(self.source_receipt) is not bytes
        ):
            raise ValueError("invalid M2 forward source slice")
        receipt = _parse_receipt(self.source_receipt)
        if receipt["source_snapshot_id"] != self.source_snapshot_id:
            raise ValueError("source receipt identity mismatch")
        body = dict(receipt)
        body.pop("source_snapshot_id")
        if _sha256([_SNAPSHOT_DOMAIN, body]) != self.source_snapshot_id:
            raise ValueError("source receipt digest mismatch")
        expected = cast(list[dict[str, object]], receipt["logical_inputs"])
        actual = (
            _logical_input(
                name="calendars",
                frame=self.calendars,
                sort_by=("market", "date"),
                date_column="date",
            ),
            _logical_input(
                name="research-prices",
                frame=self.prices,
                sort_by=("trade_date", "symbol"),
                date_column="trade_date",
            ),
        )
        canonical_actual = cast(
            list[dict[str, object]],
            json.loads(_canonical_json_bytes(list(actual))),
        )
        if expected != canonical_actual:
            raise ValueError("source receipt logical inputs mismatch")


class M2ForwardSourceLoader(Protocol):
    """Narrow callable shape for repository consumers and contract tests."""

    def __call__(
        self,
        *,
        data_root: Path,
        candidate_symbols: tuple[str, ...],
        data_start: dt.date,
        as_of: dt.date,
    ) -> M2ForwardSourceSlice: ...


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    relative_path: str
    path: Path
    info: os.stat_result


@dataclass(frozen=True, slots=True)
class _LayoutSnapshot:
    directories: tuple[tuple[str, os.stat_result], ...]
    files: tuple[_FileSnapshot, ...]


def load_m2_forward_source_slice(
    *,
    data_root: Path,
    candidate_symbols: tuple[str, ...],
    data_start: dt.date,
    as_of: dt.date,
) -> M2ForwardSourceSlice:
    """Return one stable, query-bound source slice without writing to disk."""
    failed = False
    result: M2ForwardSourceSlice | None = None
    try:
        result = _load_m2_forward_source_slice(
            data_root=data_root,
            candidate_symbols=candidate_symbols,
            data_start=data_start,
            as_of=as_of,
        )
    except Exception:
        failed = True
    if failed or result is None:
        _invalid_source()
    return result


def _load_m2_forward_source_slice(
    *,
    data_root: Path,
    candidate_symbols: tuple[str, ...],
    data_start: dt.date,
    as_of: dt.date,
) -> M2ForwardSourceSlice:
    _validate_query(
        data_root=data_root,
        candidate_symbols=candidate_symbols,
        data_start=data_start,
        as_of=as_of,
    )
    root = _anchored_root(data_root)
    before = _scan_layout(root=root, data_start=data_start, as_of=as_of)

    identities: set[tuple[int, int]] = set()
    payloads: list[tuple[_FileSnapshot, bytes]] = []
    for selected in before.files:
        payload, opened = _read_stable_file(selected.path, expected=selected.info)
        identity = _file_identity(opened)
        if identity in identities:
            raise ValueError("source files alias")
        identities.add(identity)
        payloads.append((selected, payload))

    price_frames: list[pl.DataFrame] = []
    calendar_frames: list[pl.DataFrame] = []
    file_entries: list[dict[str, object]] = []
    for selected, payload in payloads:
        frame = pl.read_parquet(io.BytesIO(payload))
        if selected.relative_path.startswith("clean/research_price_1d/"):
            price_frames.append(frame)
        else:
            calendar_frames.append(frame)
        file_entries.append(
            {
                "relative_path": selected.relative_path,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        )

    prices = _validated_prices(
        pl.concat(price_frames, how="vertical"),
        candidate_symbols=candidate_symbols,
        data_start=data_start,
        as_of=as_of,
    )
    calendars = _validated_calendars(pl.concat(calendar_frames, how="vertical"))
    logical_inputs = [
        _logical_input(
            name="calendars",
            frame=calendars,
            sort_by=("market", "date"),
            date_column="date",
        ),
        _logical_input(
            name="research-prices",
            frame=prices,
            sort_by=("trade_date", "symbol"),
            date_column="trade_date",
        ),
    ]
    body: dict[str, object] = {
        "schema_version": _RECEIPT_SCHEMA,
        "query": {
            "adjustment_method": _ADJUSTMENT_METHOD,
            "as_of": as_of,
            "calendar_markets": list(_CALENDAR_MARKETS),
            "candidate_symbols": list(candidate_symbols),
            "data_start": data_start,
        },
        "files": sorted(file_entries, key=lambda item: cast(str, item["relative_path"])),
        "logical_inputs": logical_inputs,
    }
    source_snapshot_id = _sha256([_SNAPSHOT_DOMAIN, body])
    receipt = _canonical_json_bytes({"source_snapshot_id": source_snapshot_id, **body})

    after = _scan_layout(root=root, data_start=data_start, as_of=as_of)
    if not _same_layout(before, after):
        raise ValueError("source layout changed during read")
    return M2ForwardSourceSlice(
        prices=prices,
        calendars=calendars,
        source_snapshot_id=source_snapshot_id,
        source_receipt=receipt,
    )


def _validate_query(
    *,
    data_root: Path,
    candidate_symbols: tuple[str, ...],
    data_start: dt.date,
    as_of: dt.date,
) -> None:
    if (
        not isinstance(data_root, Path)
        or type(candidate_symbols) is not tuple
        or not candidate_symbols
        or candidate_symbols != tuple(sorted(candidate_symbols))
        or len(candidate_symbols) != len(set(candidate_symbols))
        or any(
            type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None
            for symbol in candidate_symbols
        )
        or type(data_start) is not dt.date
        or type(as_of) is not dt.date
        or as_of < data_start
    ):
        raise ValueError("invalid source query")


def _anchored_root(data_root: Path) -> Path:
    root = Path(os.path.abspath(data_root))
    resolved = root.resolve(strict=True)
    if os.path.normcase(os.fspath(root)) != os.path.normcase(os.fspath(resolved)):
        raise ValueError("linked data root")
    _require_directory(root)
    return root


def _scan_layout(*, root: Path, data_start: dt.date, as_of: dt.date) -> _LayoutSnapshot:
    clean = root / "clean"
    prices_root = clean / "research_price_1d"
    calendars_root = clean / "trade_calendar"
    directories: dict[str, os.stat_result] = {
        ".": _require_directory(root),
        "clean": _require_directory(clean),
        "clean/research_price_1d": _require_directory(prices_root),
        "clean/trade_calendar": _require_directory(calendars_root),
    }
    selected: list[_FileSnapshot] = []

    with os.scandir(prices_root) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            match = _DATE_DIRECTORY.fullmatch(entry.name)
            info = os.lstat(entry.path)
            if match is None or not _valid_directory(info):
                raise ValueError("invalid research-price inventory")
            relative_directory = f"clean/research_price_1d/{entry.name}"
            directories[relative_directory] = info
            partition_date = dt.date.fromisoformat(match.group(1))
            if not data_start <= partition_date <= as_of:
                continue
            child = Path(entry.path)
            children = _directory_children(child)
            if tuple(children) != ("data.parquet",):
                raise ValueError("invalid research-price partition")
            selected.append(
                _file_snapshot(
                    root=root,
                    path=child / "data.parquet",
                    expected_relative=f"{relative_directory}/data.parquet",
                )
            )

    with os.scandir(calendars_root) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            match = _MARKET_DIRECTORY.fullmatch(entry.name)
            info = os.lstat(entry.path)
            if match is None or not _valid_directory(info):
                raise ValueError("invalid calendar inventory")
            relative_directory = f"clean/trade_calendar/{entry.name}"
            directories[relative_directory] = info
            if match.group(1) not in _CALENDAR_MARKETS:
                continue
            child = Path(entry.path)
            children = _directory_children(child)
            if tuple(children) != ("data.parquet",):
                raise ValueError("invalid calendar partition")
            selected.append(
                _file_snapshot(
                    root=root,
                    path=child / "data.parquet",
                    expected_relative=f"{relative_directory}/data.parquet",
                )
            )

    expected_calendars = {
        f"clean/trade_calendar/market={market}/data.parquet"
        for market in _CALENDAR_MARKETS
    }
    actual_calendars = {
        item.relative_path
        for item in selected
        if item.relative_path.startswith("clean/trade_calendar/")
    }
    if not selected or actual_calendars != expected_calendars:
        raise ValueError("source files missing")
    return _LayoutSnapshot(
        directories=tuple(sorted(directories.items())),
        files=tuple(sorted(selected, key=lambda item: item.relative_path)),
    )


def _directory_children(path: Path) -> list[str]:
    with os.scandir(path) as entries:
        return sorted(entry.name for entry in entries)


def _file_snapshot(*, root: Path, path: Path, expected_relative: str) -> _FileSnapshot:
    relative = path.relative_to(root).as_posix()
    if relative != expected_relative:
        raise ValueError("source path mismatch")
    info = os.lstat(path)
    if (
        not stat.S_ISREG(info.st_mode)
        or _is_link_or_reparse(info)
        or getattr(info, "st_nlink", 1) != 1
    ):
        raise ValueError("invalid source file")
    return _FileSnapshot(relative_path=relative, path=path, info=info)


def _require_directory(path: Path) -> os.stat_result:
    info = os.lstat(path)
    if not _valid_directory(info):
        raise ValueError("invalid source directory")
    return info


def _valid_directory(info: os.stat_result) -> bool:
    return stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info)


def _read_stable_file(
    path: Path, *, expected: os.stat_result
) -> tuple[bytes, os.stat_result]:
    before = os.lstat(path)
    if (
        not stat.S_ISREG(before.st_mode)
        or _is_link_or_reparse(before)
        or getattr(before, "st_nlink", 1) != 1
        or not _same_file_snapshot(expected, before)
    ):
        raise ValueError("invalid source file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    after = os.lstat(path)
    if (
        not _same_open_file(before, opened)
        or not _same_file_snapshot(before, after)
        or _is_link_or_reparse(after)
        or getattr(after, "st_nlink", 1) != 1
    ):
        raise ValueError("unstable source file")
    return b"".join(chunks), opened


def _validated_prices(
    frame: pl.DataFrame,
    *,
    candidate_symbols: tuple[str, ...],
    data_start: dt.date,
    as_of: dt.date,
) -> pl.DataFrame:
    validated = ResearchPrice1dSchema.validate(frame).select(
        "symbol",
        "trade_date",
        "adjusted_close",
        "adjustment_method",
        "source",
    )
    selected = validated.filter(
        pl.col("symbol").is_in(candidate_symbols)
        & pl.col("trade_date").is_between(data_start, as_of, closed="both")
        & (pl.col("adjustment_method") == _ADJUSTMENT_METHOD)
    ).sort("trade_date", "symbol")
    coverage = {
        symbol: maximum
        for symbol, maximum in selected.group_by("symbol").agg(
            pl.col("trade_date").max().alias("maximum")
        ).iter_rows()
    }
    if (
        selected.is_empty()
        or set(coverage) != set(candidate_symbols)
        or any(coverage[symbol] != as_of for symbol in candidate_symbols)
    ):
        raise ValueError("candidate price coverage invalid")
    return selected


def _validated_calendars(frame: pl.DataFrame) -> pl.DataFrame:
    validated = TradeCalendarSchema.validate(frame).select(
        "market", "date", "is_open", "is_connect_open", "is_half_day"
    )
    result = validated.filter(pl.col("market").is_in(_CALENDAR_MARKETS)).sort(
        "market", "date"
    )
    if result.is_empty() or set(result.get_column("market").unique()) != set(
        _CALENDAR_MARKETS
    ):
        raise ValueError("calendar coverage invalid")
    return result


def _logical_input(
    *,
    name: str,
    frame: pl.DataFrame,
    sort_by: tuple[str, ...],
    date_column: str,
) -> dict[str, object]:
    if frame.is_empty() or any(column not in frame.columns for column in (*sort_by, date_column)):
        raise ValueError("logical input invalid")
    ordered = frame.sort(list(sort_by))
    dates = ordered.get_column(date_column)
    minimum = dates.min()
    maximum = dates.max()
    if type(minimum) is not dt.date or type(maximum) is not dt.date:
        raise ValueError("logical input dates invalid")
    rows = [[_json_scalar(value) for value in row] for row in ordered.iter_rows()]
    content_sha256 = _sha256(
        [ordered.columns, [str(dtype) for dtype in ordered.dtypes], rows]
    )
    return {
        "content_sha256": content_sha256,
        "max_date": maximum,
        "min_date": minimum,
        "name": name,
        "rows": ordered.height,
    }


def _parse_receipt(payload: bytes) -> dict[str, object]:
    text = payload.decode("utf-8")
    parsed = json.loads(
        text,
        object_pairs_hook=_unique_json_object,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON")),
    )
    if type(parsed) is not dict or payload != _canonical_json_bytes(parsed):
        raise ValueError("source receipt is not canonical")
    receipt = cast(dict[str, object], parsed)
    if set(receipt) != {
        "files",
        "logical_inputs",
        "query",
        "schema_version",
        "source_snapshot_id",
    } or receipt["schema_version"] != _RECEIPT_SCHEMA:
        raise ValueError("source receipt fields mismatch")
    if type(receipt["logical_inputs"]) is not list:
        raise ValueError("source receipt inputs invalid")
    return receipt


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _same_layout(left: _LayoutSnapshot, right: _LayoutSnapshot) -> bool:
    if tuple(name for name, _ in left.directories) != tuple(
        name for name, _ in right.directories
    ) or tuple(item.relative_path for item in left.files) != tuple(
        item.relative_path for item in right.files
    ):
        return False
    return all(
        _same_file_snapshot(left_info, right_info)
        for (_, left_info), (_, right_info) in zip(
            left.directories, right.directories, strict=True
        )
    ) and all(
        _same_file_snapshot(left_item.info, right_item.info)
        for left_item, right_item in zip(left.files, right.files, strict=True)
    )


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return os.path.samestat(left, right) and (
        stat.S_IFMT(left.st_mode),
        left.st_size,
        getattr(left, "st_mtime_ns", int(left.st_mtime * 1_000_000_000)),
        getattr(left, "st_ctime_ns", int(left.st_ctime * 1_000_000_000)),
        getattr(left, "st_nlink", 1),
    ) == (
        stat.S_IFMT(right.st_mode),
        right.st_size,
        getattr(right, "st_mtime_ns", int(right.st_mtime * 1_000_000_000)),
        getattr(right, "st_ctime_ns", int(right.st_ctime * 1_000_000_000)),
        getattr(right, "st_nlink", 1),
    )


def _same_open_file(left: os.stat_result, right: os.stat_result) -> bool:
    return os.path.samestat(left, right) and (
        stat.S_IFMT(left.st_mode),
        left.st_size,
        getattr(left, "st_nlink", 1),
    ) == (
        stat.S_IFMT(right.st_mode),
        right.st_size,
        getattr(right, "st_nlink", 1),
    )


def _file_identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & marker)


def _json_scalar(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite source value")
        return value
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is dt.datetime:
        if value.tzinfo is None:
            raise ValueError("naive source timestamp")
        return value.isoformat()
    raise ValueError("unsupported source value")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if type(value) is dt.date:
        return value.isoformat()
    raise TypeError("unsupported JSON value")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


__all__ = [
    "M2ForwardSourceError",
    "M2ForwardSourceLoader",
    "M2ForwardSourceSlice",
    "load_m2_forward_source_slice",
]
