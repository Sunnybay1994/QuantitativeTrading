"""Fresh Qlib worker entrypoint.

This module is deliberately excluded from :mod:`quant.research.m3` imports.
Only the subprocess entrypoint may import Qlib.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any, cast

import polars as pl

_FIELDS = ("open", "high", "low", "close", "vwap", "volume", "factor")
_REQUEST_KEYS = {
    "schema_version", "worker_protocol_version", "provider_validation_key",
    "provider_key", "snapshot_id", "qlib_version", "provider_uri",
    "provider_uri_sha256", "fields", "selected_rows", "selected_gap_rows",
}
_RAW_SCHEMA = {
    "sample_kind": pl.Utf8,
    "symbol": pl.Utf8,
    "date": pl.Date,
    "field": pl.Utf8,
    "api_row_present": pl.Boolean,
    "actual": pl.Float64,
}


def _require_feature_frame_contract(frame: Any, qlib_fields: list[str]) -> None:
    """Reject Qlib frames whose public feature shape could be misinterpreted."""
    if list(frame.columns) != qlib_fields:
        raise ValueError("Qlib feature columns invalid")
    if frame.index.nlevels != 2 or tuple(frame.index.names) != (
        "instrument", "datetime",
    ):
        raise ValueError("Qlib feature MultiIndex invalid")


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
        raise ValueError("request must be object")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _parse_rows(value: object) -> tuple[tuple[str, dt.date], ...]:
    if type(value) is not list:
        raise ValueError("probe rows invalid")
    rows: list[tuple[str, dt.date]] = []
    for item in value:
        if type(item) is not list or len(item) != 2 or any(type(part) is not str for part in item):
            raise ValueError("probe row invalid")
        symbol, date_text = cast(list[str], item)
        rows.append((symbol, dt.date.fromisoformat(date_text)))
    result = tuple(rows)
    if result != tuple(sorted(set(result))):
        raise ValueError("probe rows must be unique and sorted")
    return result


def _qlib_symbol(symbol: str) -> str:
    code, market = symbol.split(".")
    if market not in {"SH", "SZ"} or len(code) != 6:
        raise ValueError("symbol invalid")
    return f"{market}{code}"


def _date_only(value: object) -> dt.date:
    import pandas as pd  # type: ignore[import-untyped]

    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None or stamp.time() != dt.time.min:
        raise ValueError("Qlib datetime must be naive midnight")
    return stamp.date()


def _normalise_ranges(value: object) -> tuple[tuple[str, str, str], ...]:
    if type(value) is not dict:
        raise ValueError("Qlib instrument ranges invalid")
    rows: list[tuple[str, str, str]] = []
    for symbol, ranges in cast(dict[object, object], value).items():
        if type(symbol) is not str or type(ranges) not in {list, tuple} or not ranges:
            raise ValueError("Qlib instrument range invalid")
        segments = cast(list[Any] | tuple[Any, ...], ranges)
        if len(segments) != 1:
            raise ValueError("Qlib instrument must have exactly one segment")
        first = segments[0]
        if type(first) not in {list, tuple} or len(first) != 2:
            raise ValueError("Qlib instrument segment invalid")
        rows.append((symbol.upper(), _date_only(first[0]).isoformat(), _date_only(first[1]).isoformat()))
    return tuple(sorted(rows))


def _json_rows(rows: list[dict[str, object]]) -> tuple[dict[str, object], ...]:
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


def validate_provider(request_path: Path, response_path: Path, details_path: Path) -> None:
    request = _strict_json(request_path.read_bytes())
    if set(request) != _REQUEST_KEYS:
        raise ValueError("worker request schema invalid")
    if (
        request["schema_version"] != "m3-qlib-worker-request-v1"
        or request["worker_protocol_version"] != "m3-qlib-worker-v1"
        or request["qlib_version"] != "0.9.7"
        or request["fields"] != list(_FIELDS)
        or importlib.metadata.version("pyqlib") != "0.9.7"
    ):
        raise ValueError("worker request protocol invalid")
    emitted = _parse_rows(request["selected_rows"])
    gaps = _parse_rows(request["selected_gap_rows"])
    if len(emitted) != 60 or len(gaps) > 15 or set(emitted) & set(gaps):
        raise ValueError("worker probe closure invalid")
    provider_uri = Path(cast(str, request["provider_uri"])).resolve(strict=True)

    import qlib  # type: ignore[import-not-found]
    from qlib.constant import REG_CN  # type: ignore[import-not-found]
    from qlib.data import D  # type: ignore[import-not-found]

    qlib.init(provider_uri=str(provider_uri), region=REG_CN)
    api_calendar = tuple(_date_only(value).isoformat() for value in D.calendar(freq="day"))
    if api_calendar != tuple(sorted(set(api_calendar))):
        raise ValueError("Qlib calendar invalid")
    instruments = D.instruments(market="all")
    api_ranges = _normalise_ranges(
        D.list_instruments(instruments, freq="day", as_list=False)
    )

    planned_by_symbol: dict[str, list[tuple[str, dt.date]]] = {}
    for kind, planned_set in (("EMITTED", emitted), ("GAP", gaps)):
        for symbol, day in planned_set:
            planned_by_symbol.setdefault(symbol, []).append((kind, day))
    raw_rows: list[dict[str, object]] = []
    qlib_fields = [f"${field}" for field in _FIELDS]
    for symbol, planned_rows in sorted(planned_by_symbol.items()):
        dates = tuple(day for _, day in planned_rows)
        frame = D.features(
            [_qlib_symbol(symbol)], qlib_fields,
            start_time=min(dates), end_time=max(dates), freq="day", disk_cache=0,
        )
        _require_feature_frame_contract(frame, qlib_fields)
        matches: dict[dt.date, list[Any]] = {}
        for (instrument, timestamp), values in frame.iterrows():
            if type(instrument) is not str or instrument.upper() != _qlib_symbol(symbol):
                raise ValueError("Qlib feature instrument invalid")
            matches.setdefault(_date_only(timestamp), []).append(values)
        for kind, day in sorted(planned_rows):
            matching_rows = matches.get(day, [])
            if not matching_rows:
                for field in _FIELDS:
                    raw_rows.append({
                        "sample_kind": kind, "symbol": symbol, "date": day,
                        "field": field, "api_row_present": False, "actual": None,
                    })
                continue
            for values in matching_rows:
                value_row = cast(Any, values)
                for field, qlib_field in zip(_FIELDS, qlib_fields, strict=True):
                    value = value_row[qlib_field]
                    pandas = __import__("pandas")
                    actual = None if value is None or value is pandas.NA else float(value)
                    raw_rows.append({
                        "sample_kind": kind, "symbol": symbol, "date": day,
                        "field": field, "api_row_present": True, "actual": actual,
                    })
    raw_rows.sort(key=lambda row: (
        cast(str, row["sample_kind"]), cast(str, row["symbol"]),
        cast(dt.date, row["date"]), cast(str, row["field"]),
    ))
    details = pl.DataFrame(raw_rows, schema=_RAW_SCHEMA).select(*_RAW_SCHEMA)
    details.write_parquet(
        details_path, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
    echo_keys = (
        "schema_version", "worker_protocol_version", "provider_validation_key",
        "provider_key", "snapshot_id", "qlib_version", "provider_uri_sha256",
        "fields", "selected_rows", "selected_gap_rows",
    )
    response = {
        **{key: request[key] for key in echo_keys},
        "response_schema_version": "m3-qlib-worker-response-v1",
        "api_calendar": list(api_calendar),
        "api_instrument_ranges": [list(row) for row in api_ranges],
        "response_rows_sha256": _hash(_json_rows(raw_rows)),
    }
    response_path.write_bytes(_canonical_bytes(response))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-provider")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--response", type=Path, required=True)
    validate.add_argument("--details", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command != "validate-provider":
        raise ValueError("unknown worker command")
    validate_provider(args.request, args.response, args.details)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
