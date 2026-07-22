"""M3 clean-table content identity (B3/B4 logical digests)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from typing import Any

import polars as pl

_ALGORITHM = "m3-clean-table-content-v1"
_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_ERROR_CODES = frozenset({"G1_TABLE_IDENTITY_INVALID"})


class M3CleanTableIdentityError(ValueError):
    """Stable clean-table identity boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown clean-table identity error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3CleanTableIdentityError({self.code!r})"


def clean_table_content_sha256(*, table_name: str, frame: pl.DataFrame) -> str:
    """Hash a clean logical table independent of row order and Parquet bytes.

    Algorithm version ``m3-clean-table-content-v1``: versioned envelope with table
    name, ordered column name/dtype pairs, and row encodings sorted by their
    canonical JSON bytes. Duplicate rows are retained.
    """
    try:
        if type(table_name) is not str or not _TABLE_NAME.fullmatch(table_name):
            raise M3CleanTableIdentityError("G1_TABLE_IDENTITY_INVALID")
        if not isinstance(frame, pl.DataFrame):
            raise M3CleanTableIdentityError("G1_TABLE_IDENTITY_INVALID")
        columns = [
            {"name": name, "dtype": str(dtype)}
            for name, dtype in zip(frame.columns, frame.dtypes, strict=True)
        ]
        encoded_rows: list[str] = []
        for row in frame.iter_rows(named=True):
            payload = {name: _scalar_tag(row[name]) for name in frame.columns}
            encoded_rows.append(_canonical_json(payload))
        encoded_rows.sort()
        digest = hashlib.sha256(
            _canonical_json(
                {
                    "algorithm": _ALGORITHM,
                    "columns": columns,
                    "rows": encoded_rows,
                    "table_name": table_name,
                }
            ).encode("utf-8")
        ).hexdigest()
        return digest
    except M3CleanTableIdentityError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError):
        raise M3CleanTableIdentityError("G1_TABLE_IDENTITY_INVALID") from None


def _scalar_tag(value: object) -> list[Any]:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            raise M3CleanTableIdentityError("G1_TABLE_IDENTITY_INVALID")
        normalized = 0.0 if value == 0.0 else value
        return ["float", format(normalized, ".17g")]
    if type(value) is dt.date and type(value) is not dt.datetime:
        return ["date", value.isoformat()]
    if type(value) is str:
        return ["string", value]
    raise M3CleanTableIdentityError("G1_TABLE_IDENTITY_INVALID")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
