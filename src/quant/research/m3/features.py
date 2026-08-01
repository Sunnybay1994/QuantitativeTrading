"""Safe parent-side contracts and logical digests for M3 feature artifacts.

This module never imports Qlib.  Qlib execution belongs exclusively to the
fresh-worker entrypoint in :mod:`quant.research.m3.qlib_adapter`.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Sequence

_DIGEST_VERSION = "m3-f64-matrix-digest-v1"
_CANONICAL_NAN_LE = bytes.fromhex("000000000000f87f")


def canonical_row_keys_sha256(rows: Sequence[tuple[str, str]]) -> str:
    """Hash row keys in their frozen order; never sort away alignment errors."""
    normalized: list[list[str]] = []
    for row in rows:
        if (
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value for value in row)
        ):
            raise ValueError("feature row key 非法")
        normalized.append([row[0], row[1]])
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def f64_matrix_sha256(
    *, columns: Sequence[str], rows: Sequence[Sequence[float | int | None]]
) -> str:
    """Return the cross-platform logical digest frozen by the G4-G6 SSOT."""
    names = _column_names(columns)
    header = {
        "digest_version": _DIGEST_VERSION,
        "n_rows": len(rows),
        "columns": list(names),
        "dtype": "float64-le",
    }
    digest = hashlib.sha256()
    digest.update(_canonical_bytes(header))
    digest.update(b"\n")
    for row in rows:
        if len(row) != len(names):
            raise ValueError("feature matrix width 非法")
        for value in row:
            if value is None:
                digest.update(_CANONICAL_NAN_LE)
                continue
            if type(value) not in {int, float}:
                raise ValueError("feature matrix value 非法")
            number = float(value)
            if math.isinf(number):
                raise ValueError("feature matrix 不允许 infinity")
            digest.update(
                _CANONICAL_NAN_LE if math.isnan(number) else struct.pack("<d", number)
            )
    return digest.hexdigest()


def feature_schema_sha256(*, names: Sequence[str]) -> str:
    """Hash an ordered Float64 feature projection."""
    columns = _column_names(names)
    return hashlib.sha256(_canonical_bytes({
        "columns": [
            {"name": name, "dtype": "Float64"}
            for name in columns
        ]
    })).hexdigest()


def feature_segment_content_sha256(
    *, name: str, feature_row_keys_sha256: str,
    feature_matrix_sha256: str, selected_schema_sha256: str,
) -> str:
    """Hash the exact logical FeatureSegment content envelope."""
    if name not in {"train", "validation", "test"}:
        raise ValueError("feature segment name 非法")
    for value in (
        feature_row_keys_sha256, feature_matrix_sha256, selected_schema_sha256,
    ):
        if not _is_hex64(value):
            raise ValueError("feature segment digest 非法")
    return hashlib.sha256(_canonical_bytes({
        "name": name,
        "feature_row_keys_sha256": feature_row_keys_sha256,
        "feature_matrix_sha256": feature_matrix_sha256,
        "selected_schema_sha256": selected_schema_sha256,
    })).hexdigest()


def _column_names(columns: Sequence[str]) -> tuple[str, ...]:
    result = tuple(columns)
    if (
        not result
        or any(type(name) is not str or not name for name in result)
        or len(set(result)) != len(result)
    ):
        raise ValueError("feature columns 非法")
    return result


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _is_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
