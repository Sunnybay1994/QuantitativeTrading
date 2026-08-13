"""Low-level canonical JSON wire primitives shared across domain consumers."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import NoReturn, TypeVar, cast

_E = TypeVar("_E")

__all__ = [
    "WireError",
    "canonical_json_bytes",
    "parse_canonical_json_object",
    "raise_wire_error",
    "require_boolean",
    "require_date",
    "require_decimal",
    "require_enum",
    "require_exact_object",
    "require_integer",
    "require_string",
    "require_utc_datetime",
    "require_wire_root",
    "utc_datetime_text",
]


class WireError(ValueError):
    """Stable, path-free canonical-wire error with no wrapped input exception."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def raise_wire_error(code: str = "WIRE_INVALID") -> NoReturn:
    """Raise the stable public wire failure without an explicit cause."""
    raise WireError(code) from None


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    """Return the one accepted UTF-8 JSON representation."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except Exception:
        pass
    raise_wire_error()


def _unique_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise_wire_error()
        result[key] = value
    return result


def _reject_constant(_: str) -> NoReturn:
    raise_wire_error()


def parse_canonical_json_object(payload: bytes) -> dict[str, object]:
    """Parse a canonical JSON object while rejecting aliases and duplicate keys."""
    if type(payload) is not bytes or payload.startswith(b"\xef\xbb\xbf"):
        raise_wire_error()
    failed = False
    try:
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except WireError:
        raise
    except Exception:
        failed = True
    if failed:
        raise_wire_error()
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise_wire_error()
    return value


def require_exact_object(
    value: object,
    keys: set[str],
    *,
    schema: str | None = None,
) -> dict[str, object]:
    """Require an object with exactly the declared keys and optional schema."""
    if type(value) is not dict or set(value) != keys:
        raise_wire_error()
    result = cast(dict[str, object], value)
    if schema is not None and result["schema_version"] != schema:
        raise_wire_error()
    return result


def require_wire_root(payload: bytes, *, schema: str, keys: set[str]) -> dict[str, object]:
    """Require the expected schema, distinguishing only canonical future versions."""
    value = parse_canonical_json_object(payload)
    version = value.get("schema_version")
    if version != schema:
        family, separator, expected_number = schema.rpartition("-v")
        pattern = rf"{re.escape(family)}-v[1-9][0-9]*"
        if separator and expected_number.isdigit() and type(version) is str:
            if re.fullmatch(pattern, version):
                raise_wire_error("WIRE_VERSION_UNSUPPORTED")
        raise_wire_error()
    return require_exact_object(value, keys | {"schema_version"}, schema=schema)


def require_string(value: object, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value:
        raise_wire_error()
    return cast(str, value)


def require_integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise_wire_error()
    return cast(int, value)


def require_boolean(value: object) -> bool:
    if type(value) is not bool:
        raise_wire_error()
    return cast(bool, value)


def require_decimal(value: object, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise_wire_error()
    parsed: Decimal | None = None
    try:
        parsed = Decimal(cast(str, value))
    except InvalidOperation:
        pass
    if parsed is None or not parsed.is_finite() or format(parsed, "f") != value:
        raise_wire_error()
    return parsed


def require_date(value: object) -> dt.date:
    parsed: dt.date | None = None
    try:
        if type(value) is str:
            parsed = dt.date.fromisoformat(value)
    except ValueError:
        pass
    if parsed is None or parsed.isoformat() != value:
        raise_wire_error()
    return parsed


def utc_datetime_text(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        raise_wire_error()
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def require_utc_datetime(value: object) -> dt.datetime:
    parsed: dt.datetime | None = None
    try:
        if type(value) is str and value.endswith("Z"):
            parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        pass
    if parsed is None or utc_datetime_text(parsed) != value:
        raise_wire_error()
    return parsed


def require_enum(cls: type[_E], value: object) -> _E:
    if type(value) is not str:
        raise_wire_error()
    try:
        return cls(value)  # type: ignore[call-arg]
    except (TypeError, ValueError):
        pass
    raise_wire_error()
