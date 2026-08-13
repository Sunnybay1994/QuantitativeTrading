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
import os
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.research.m3.contracts import (
    FEATURE_DEVELOPMENT_REQUEST_KEYS,
    FEATURE_FORMAL_REQUEST_KEYS,
)

_FIELDS = ("open", "high", "low", "close", "vwap", "volume", "factor")
_REQUEST_KEYS = {
    "schema_version", "worker_protocol_version", "provider_validation_key",
    "provider_key", "snapshot_id", "qlib_version", "provider_uri",
    "provider_uri_sha256", "fields", "selected_rows", "selected_gap_rows",
}
_LABEL_REQUEST_KEYS = {
    "schema_version", "worker_protocol_version", "reconciliation_key",
    "experiment_key", "provider_validation_receipt_sha256",
    "label_manifest_sha256", "label_reconciliation_config_sha256",
    "dependency_fingerprint_sha256", "code_version", "snapshot_id",
    "provider_key", "qlib_version",
    "provider_uri", "provider_uri_sha256", "horizon_sessions",
    "qlib_expression", "label_rows", "row_key_sha256",
}
_RAW_SCHEMA = {
    "sample_kind": pl.Utf8,
    "symbol": pl.Utf8,
    "date": pl.Date,
    "field": pl.Utf8,
    "api_row_present": pl.Boolean,
    "actual": pl.Float64,
}
_LABEL_RAW_SCHEMA = {
    "as_of": pl.Date,
    "symbol": pl.Utf8,
    "benchmark": pl.Utf8,
    "horizon_sessions": pl.Int64,
    "label_version": pl.Utf8,
    "return_start_date": pl.Date,
    "return_end_date": pl.Date,
    "qlib_expression_raw": pl.Float64,
    "provider_direct_raw": pl.Float64,
}


def is_qlib_importable() -> bool:
    """Probe Qlib lazily without spreading its import outside this adapter."""
    try:
        import qlib  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


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


def _is_bare_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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


def _parse_label_rows(
    value: object,
) -> tuple[tuple[dt.date, str, str, int, str, dt.date, dt.date], ...]:
    if type(value) is not list:
        raise ValueError("label rows invalid")
    rows: list[tuple[dt.date, str, str, int, str, dt.date, dt.date]] = []
    for item in value:
        if type(item) is not list or len(item) != 7:
            raise ValueError("label row invalid")
        as_of_text, symbol, benchmark, horizon, version, start_text, end_text = item
        if (
            any(type(part) is not str for part in (
                as_of_text, symbol, benchmark, version, start_text, end_text
            ))
            or type(horizon) is not int
            or horizon not in {5, 10}
            or benchmark != "510300.SH"
        ):
            raise ValueError("label row invalid")
        rows.append((
            dt.date.fromisoformat(cast(str, as_of_text)), cast(str, symbol),
            cast(str, benchmark), cast(int, horizon), cast(str, version),
            dt.date.fromisoformat(cast(str, start_text)),
            dt.date.fromisoformat(cast(str, end_text)),
        ))
    result = tuple(rows)
    keys = tuple(row[:5] for row in result)
    if keys != tuple(sorted(set(keys))) or any(row[6] < row[5] for row in result):
        raise ValueError("label rows must be unique and sorted")
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
            elif type(value) is float and value == 0.0:
                clean[key] = 0.0
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


def reconcile_labels(
    request_path: Path, response_path: Path, details_path: Path
) -> None:
    """Read Qlib expression/direct prices; leave all comparisons to parent."""
    request = _strict_json(request_path.read_bytes())
    if set(request) != _LABEL_REQUEST_KEYS:
        raise ValueError("label worker request schema invalid")
    horizon = request["horizon_sessions"]
    expression = request["qlib_expression"]
    if (
        request["schema_version"]
        != "m3-label-reconciliation-worker-request-v1"
        or request["worker_protocol_version"] != "m3-qlib-worker-v1"
        or request["qlib_version"] != "0.9.7"
        or type(horizon) is not int
        or horizon not in {5, 10}
        or expression != f"Ref($close,-{horizon})/Ref($open,-1)-1"
    ):
        raise ValueError("label worker protocol invalid")
    rows = _parse_label_rows(request["label_rows"])
    identity_names = (
        "reconciliation_key", "experiment_key",
        "provider_validation_receipt_sha256", "label_manifest_sha256",
        "label_reconciliation_config_sha256", "dependency_fingerprint_sha256",
        "snapshot_id", "provider_key", "provider_uri_sha256", "row_key_sha256",
    )
    key_rows = [
        [
            row[0].isoformat(), row[1], row[2], row[3], row[4],
        ]
        for row in rows
    ]
    if (
        not rows
        or {row[3] for row in rows} != {horizon}
        or any(not _is_bare_hex64(request[name]) for name in identity_names)
        or type(request["code_version"]) is not str
        or not cast(str, request["code_version"]).strip()
        or request["row_key_sha256"] != _hash(key_rows)
        or request["provider_uri_sha256"]
        != _hash([request["provider_key"], "provider"])
    ):
        raise ValueError("label worker row closure invalid")
    if importlib.metadata.version("pyqlib") != "0.9.7":
        raise ValueError("label worker Qlib version invalid")
    provider_uri = Path(cast(str, request["provider_uri"])).resolve(strict=True)

    import qlib  # type: ignore[import-not-found]
    from qlib.constant import REG_CN  # type: ignore[import-not-found]
    from qlib.data import D  # type: ignore[import-not-found]

    qlib.init(provider_uri=str(provider_uri), region=REG_CN)
    by_symbol: dict[str, list[tuple[dt.date, str, str, int, str, dt.date, dt.date]]] = {}
    for row in rows:
        by_symbol.setdefault(row[1], []).append(row)
    output_rows: list[dict[str, object]] = []
    for symbol, symbol_rows in sorted(by_symbol.items()):
        qlib_symbol = _qlib_symbol(symbol)
        as_of_dates = tuple(row[0] for row in symbol_rows)
        expression_frame = D.features(
            [qlib_symbol], [cast(str, expression)],
            start_time=min(as_of_dates), end_time=max(as_of_dates),
            freq="day", disk_cache=0,
        )
        _require_feature_frame_contract(expression_frame, [cast(str, expression)])
        expression_values: dict[dt.date, list[float | None]] = {}
        for (instrument, timestamp), values in expression_frame.iterrows():
            if type(instrument) is not str or instrument.upper() != qlib_symbol:
                raise ValueError("Qlib expression instrument invalid")
            value = values[cast(str, expression)]
            pandas = __import__("pandas")
            actual = None if value is None or value is pandas.NA else float(value)
            expression_values.setdefault(_date_only(timestamp), []).append(actual)
        direct_dates = tuple(
            day for row in symbol_rows for day in (row[5], row[6])
        )
        direct_frame = D.features(
            [qlib_symbol], ["$open", "$close"],
            start_time=min(direct_dates), end_time=max(direct_dates),
            freq="day", disk_cache=0,
        )
        _require_feature_frame_contract(direct_frame, ["$open", "$close"])
        direct_values: dict[dt.date, list[tuple[float | None, float | None]]] = {}
        for (instrument, timestamp), values in direct_frame.iterrows():
            if type(instrument) is not str or instrument.upper() != qlib_symbol:
                raise ValueError("Qlib direct instrument invalid")
            pandas = __import__("pandas")
            opened = values["$open"]
            closed = values["$close"]
            direct_values.setdefault(_date_only(timestamp), []).append((
                None if opened is None or opened is pandas.NA else float(opened),
                None if closed is None or closed is pandas.NA else float(closed),
            ))
        for row in symbol_rows:
            as_of, row_symbol, benchmark, row_horizon, version, start, end = row
            expression_matches = expression_values.get(as_of, [])
            start_matches = direct_values.get(start, [])
            end_matches = direct_values.get(end, [])
            if (
                len(expression_matches) > 1
                or len(start_matches) > 1
                or len(end_matches) > 1
            ):
                raise ValueError("Qlib label lookup duplicate")
            expression_raw = expression_matches[0] if expression_matches else None
            entry_open = start_matches[0][0] if start_matches else None
            exit_close = end_matches[0][1] if end_matches else None
            direct_raw = (
                exit_close / entry_open - 1.0
                if entry_open is not None and exit_close is not None
                and entry_open != 0.0 else None
            )
            output_rows.append({
                "as_of": as_of, "symbol": row_symbol, "benchmark": benchmark,
                "horizon_sessions": row_horizon, "label_version": version,
                "return_start_date": start, "return_end_date": end,
                "qlib_expression_raw": expression_raw,
                "provider_direct_raw": direct_raw,
            })
    output_rows.sort(key=lambda row: (
        cast(dt.date, row["as_of"]), cast(str, row["symbol"]),
        cast(str, row["benchmark"]), cast(int, row["horizon_sessions"]),
        cast(str, row["label_version"]),
    ))
    details = pl.DataFrame(output_rows, schema=_LABEL_RAW_SCHEMA).select(
        *_LABEL_RAW_SCHEMA
    )
    details.write_parquet(
        details_path, compression="zstd", compression_level=3, statistics=True,
        row_group_size=65536, use_pyarrow=False,
    )
    echo_keys = tuple(sorted(_LABEL_REQUEST_KEYS - {"provider_uri", "label_rows"}))
    response = {
        **{key: request[key] for key in echo_keys},
        "response_schema_version": "m3-label-reconciliation-worker-response-v1",
        "response_rows_sha256": _hash(_json_rows(output_rows)),
    }
    response_path.write_bytes(_canonical_bytes(response))


def _parse_feature_request(
    request: dict[str, object], *, formal: bool,
) -> tuple[tuple[tuple[str, str, str], ...], dict[str, list[str]]]:
    expected_keys = (
        FEATURE_FORMAL_REQUEST_KEYS
        if formal else FEATURE_DEVELOPMENT_REQUEST_KEYS
    )
    identity_names = (
        "experiment_key", "experiment_manifest_sha256", "g1_release_id",
        "g1_release_manifest_sha256", "snapshot_id", "snapshot_manifest_sha256",
        "provider_key", "provider_manifest_sha256", "provider_receipt_sha256",
        "planned_fold_sha256", "scientific_config_sha256",
    )
    expected_kind = "formal" if formal else "development_example"
    if (
        set(request) != expected_keys
        or request.get("schema_version") != "m3-feature-worker-request-v1"
        or request.get("worker_protocol_version") != "m3-qlib-worker-v1"
        or request.get("release_kind") != expected_kind
        or request.get("formal_gate_eligible") is not formal
        or request.get("qlib_version") != "0.9.7"
        or request.get("feature_version") != "alpha158_v1"
        or any(not _is_bare_hex64(request.get(name)) for name in identity_names)
        or request.get("provider_uri_sha256")
        != _hash([request.get("provider_key"), "provider"])
        or type(request.get("fold")) is not str
        or type(request.get("history_start")) is not str
    ):
        raise ValueError("feature worker identity invalid")
    dt.date.fromisoformat(cast(str, request["history_start"]))
    if not formal and (
        type(request.get("example_id")) is not str
        or not cast(str, request["example_id"]).startswith("development-example-")
    ):
        raise ValueError("development feature worker identity invalid")
    segments = request.get("segments")
    eligible_rows = request.get("eligible_rows")
    if (
        type(segments) is not dict
        or set(cast(dict[object, object], segments))
        != {"train", "validation", "test"}
        or type(eligible_rows) is not list
    ):
        raise ValueError("feature worker rows invalid")
    parsed_rows: list[tuple[str, str, str]] = []
    for row in cast(list[object], eligible_rows):
        if (
            type(row) is not list
            or len(cast(list[object], row)) != 3
            or any(type(value) is not str for value in cast(list[object], row))
        ):
            raise ValueError("feature worker eligible row invalid")
        segment, date_text, symbol = cast(list[str], row)
        if segment not in {"train", "validation", "test"}:
            raise ValueError("feature worker segment invalid")
        dt.date.fromisoformat(date_text)
        _qlib_symbol(symbol)
        parsed_rows.append((segment, date_text, symbol))
    segment_rank = {"train": 0, "validation": 1, "test": 2}
    if tuple(parsed_rows) != tuple(sorted(
        set(parsed_rows), key=lambda row: (segment_rank[row[0]], row[1], row[2])
    )):
        raise ValueError("feature worker rows must be unique and sorted")
    clean_segments: dict[str, list[str]] = {}
    for name, values in cast(dict[str, object], segments).items():
        if (
            type(values) is not list
            or any(type(value) is not str for value in cast(list[object], values))
            or tuple(cast(list[str], values))
            != tuple(sorted(set(cast(list[str], values))))
            or not cast(list[str], values)
            or any(
                row[1] not in cast(list[str], values)
                for row in parsed_rows if row[0] == name
            )
        ):
            raise ValueError("feature worker segment dates invalid")
        for value in cast(list[str], values):
            dt.date.fromisoformat(value)
        clean_segments[name] = cast(list[str], values)
    return tuple(parsed_rows), clean_segments


def build_formal_alpha158(request_path: Path, output_root: Path) -> None:
    """Build formal Alpha158 frames; Qlib is imported only in this worker."""
    request = _strict_json(request_path.read_bytes())
    parsed_rows, segments = _parse_feature_request(request, formal=True)
    if not output_root.is_dir() or any(output_root.iterdir()):
        raise ValueError("formal feature worker output root must be empty")
    if importlib.metadata.version("pyqlib") != "0.9.7":
        raise ValueError("formal feature worker Qlib version invalid")
    provider_text = os.environ.get("M3_QLIB_PROVIDER_URI")
    if type(provider_text) is not str or not provider_text:
        raise ValueError("formal feature worker provider missing")
    provider_uri = Path(provider_text).resolve(strict=True)

    import pandas as pd  # type: ignore[import-untyped]
    import qlib  # type: ignore[import-not-found]
    from qlib.constant import REG_CN  # type: ignore[import-not-found]
    from qlib.contrib.data.handler import Alpha158  # type: ignore[import-not-found]
    from qlib.data.dataset import DatasetH  # type: ignore[import-not-found]
    from qlib.data.dataset.handler import DataHandlerLP  # type: ignore[import-not-found]

    from quant.research.m3.snapshot import from_qlib_symbol

    qlib.init(provider_uri=str(provider_uri), region=REG_CN)
    segment_bounds = {
        name: (values[0], values[-1]) for name, values in segments.items()
    }
    handler = Alpha158(
        instruments="all",
        start_time=cast(str, request["history_start"]),
        end_time=segments["test"][-1],
        infer_processors=[], learn_processors=[], label=([], []),
    )
    expressions_raw, names_raw = handler.get_feature_config()
    expressions = tuple(cast(list[str], expressions_raw))
    names = tuple(cast(list[str], names_raw))
    if len(names) != 158 or len(set(names)) != 158 or len(expressions) != 158:
        raise ValueError("formal Alpha158 config invalid")
    dataset = DatasetH(handler=handler, segments=segment_bounds)
    eligible = {
        name: tuple((day, symbol) for segment, day, symbol in parsed_rows if segment == name)
        for name in ("train", "validation", "test")
    }
    for segment in ("train", "validation", "test"):
        frame = dataset.prepare(
            segment, col_set="feature", data_key=DataHandlerLP.DK_I
        )
        if not isinstance(frame, pd.DataFrame):
            raise ValueError("formal feature worker frame invalid")
        if frame.index.nlevels != 2 or set(frame.index.names) != {
            "datetime", "instrument"
        }:
            raise ValueError("formal feature worker index invalid")
        if getattr(frame.columns, "nlevels", 1) == 2:
            columns = tuple(frame.columns)
            if any(item[0] != "feature" for item in columns):
                raise ValueError("formal feature worker column group invalid")
            leaf_names = tuple(cast(str, item[1]) for item in columns)
        elif getattr(frame.columns, "nlevels", 1) == 1:
            leaf_names = tuple(cast(str, item) for item in frame.columns)
        else:
            raise ValueError("formal feature worker columns invalid")
        if leaf_names != names:
            raise ValueError("formal feature worker schema drift")
        values_by_key: dict[tuple[str, str], tuple[float, ...]] = {}
        for index, values in frame.iterrows():
            index_map = dict(zip(frame.index.names, index, strict=True))
            day = _date_only(index_map["datetime"]).isoformat()
            symbol = from_qlib_symbol(cast(str, index_map["instrument"]))
            key = (day, symbol)
            if key not in eligible[segment]:
                continue
            if key in values_by_key:
                raise ValueError("formal feature worker duplicate key")
            values_by_key[key] = tuple(
                math.nan if pd.isna(value) else float(value) for value in values
            )
        records: list[dict[str, object]] = []
        for day, symbol in eligible[segment]:
            row_values = values_by_key.get((day, symbol), (math.nan,) * len(names))
            records.append({
                "as_of": dt.date.fromisoformat(day), "symbol": symbol,
                **dict(zip(names, row_values, strict=True)),
            })
        schema = {
            "as_of": pl.Date, "symbol": pl.Utf8,
            **{name: pl.Float64 for name in names},
        }
        pl.DataFrame(records, schema=schema).select(*schema).write_parquet(
            output_root / f"raw_{segment}.parquet", compression="zstd",
            compression_level=3, statistics=True, row_group_size=65536,
            use_pyarrow=False,
        )
    echo_keys = tuple(sorted(FEATURE_FORMAL_REQUEST_KEYS - {"eligible_rows"}))
    response = {
        **{key: request[key] for key in echo_keys},
        "response_schema_version": "m3-feature-worker-response-v1",
        "input_names": list(names), "expressions": list(expressions),
    }
    (output_root / "worker-response.json").write_bytes(_canonical_bytes(response))


def build_development_example_alpha158(request_path: Path, output_root: Path) -> None:
    """Emit deterministic Alpha158-shaped raw frames without importing Qlib."""
    request = _strict_json(request_path.read_bytes())
    parsed_rows, _ = _parse_feature_request(request, formal=False)
    if not output_root.is_dir() or any(output_root.iterdir()):
        raise ValueError("development feature worker output root must be empty")

    names = tuple(f"ALPHA{index:03d}" for index in range(1, 159))
    expressions = tuple(
        f"DEVELOPMENT_EXAMPLE_ALPHA158_{index:03d}" for index in range(1, 159)
    )
    for segment in ("train", "validation", "test"):
        records: list[dict[str, object]] = []
        for row_index, (_, date_text, symbol) in enumerate(
            row for row in parsed_rows if row[0] == segment
        ):
            record: dict[str, object] = {
                "as_of": dt.date.fromisoformat(date_text), "symbol": symbol,
            }
            symbol_seed = sum(ord(character) for character in symbol)
            for feature_index, name in enumerate(names, start=1):
                value: float | None = float(
                    (dt.date.fromisoformat(date_text).toordinal() % 997)
                    + symbol_seed / 1000.0 + feature_index / 10000.0
                )
                if segment == "test" and row_index == 0 and feature_index <= 157:
                    value = math.nan
                elif feature_index == 158 and segment == "train":
                    value = None
                elif feature_index == 157 and row_index == 0:
                    value = math.nan
                record[name] = value
            records.append(record)
        schema = {"as_of": pl.Date, "symbol": pl.Utf8, **{name: pl.Float64 for name in names}}
        pl.DataFrame(records, schema=schema).select(*schema).write_parquet(
            output_root / f"raw_{segment}.parquet",
            compression="zstd", compression_level=3, statistics=True,
            row_group_size=65536, use_pyarrow=False,
        )
    echo_keys = tuple(sorted(
        FEATURE_DEVELOPMENT_REQUEST_KEYS - {"eligible_rows"}
    ))
    response = {
        **{key: request[key] for key in echo_keys},
        "response_schema_version": "m3-feature-worker-response-v1",
        "input_names": list(names),
        "expressions": list(expressions),
    }
    (output_root / "worker-response.json").write_bytes(_canonical_bytes(response))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-provider")
    validate.add_argument("--request", type=Path, required=True)
    validate.add_argument("--response", type=Path, required=True)
    validate.add_argument("--details", type=Path, required=True)
    reconcile = subparsers.add_parser("reconcile-labels")
    reconcile.add_argument("--request", type=Path, required=True)
    reconcile.add_argument("--response", type=Path, required=True)
    reconcile.add_argument("--details", type=Path, required=True)
    feature_example = subparsers.add_parser("build-alpha158-example")
    feature_example.add_argument("--request", type=Path, required=True)
    feature_example.add_argument("--output-root", type=Path, required=True)
    feature_formal = subparsers.add_parser("build-alpha158-formal")
    feature_formal.add_argument("--request", type=Path, required=True)
    feature_formal.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "validate-provider":
        validate_provider(args.request, args.response, args.details)
    elif args.command == "reconcile-labels":
        reconcile_labels(args.request, args.response, args.details)
    elif args.command == "build-alpha158-example":
        build_development_example_alpha158(args.request, args.output_root)
    elif args.command == "build-alpha158-formal":
        build_formal_alpha158(args.request, args.output_root)
    else:
        raise ValueError("unknown worker command")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
