"""M3 G1 core mappers: VerifiedRawResponse -> standard clean frames."""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

import polars as pl

from quant.data.m3_backfill import TUSHARE_FIELDS, VerifiedRawResponse
from quant.domain import AdjustmentFactorSchema, BenchmarkBar1dSchema, Suspension1dSchema

_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_DATE8 = re.compile(r"^[0-9]{8}$")
_SOURCE = "tushare"
_BENCHMARK = "H00300.CSI"

_ERROR_CODES = frozenset(
    {
        "G1_MAPPER_RESPONSE_INVALID",
        "G1_MAPPER_ENDPOINT_MISMATCH",
        "G1_MAPPER_EMPTY",
        "G1_MAPPER_COLUMNS_INVALID",
        "G1_MAPPER_REQUEST_SCOPE_MISMATCH",
        "G1_MAPPER_VALUE_INVALID",
        "G1_MAPPER_DUPLICATE_KEY",
        "G1_MAPPER_SUSPENSION_CONFLICT",
        "G1_MAPPER_SCHEMA_INVALID",
    }
)

_DAILY_OUT = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "source",
)
_FACTOR_OUT = ("symbol", "effective_date", "adj_factor", "source")
_BENCH_OUT = (
    "benchmark",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "source",
    "source_snapshot_id",
)
_SUSP_OUT = (
    "symbol",
    "trade_date",
    "suspension_scope",
    "suspension_detail",
    "source",
    "source_snapshot_id",
)


class M3G1MappingError(ValueError):
    """Stable mapper boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown mapper error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3G1MappingError({self.code!r})"


def map_g1_daily_response(*, response: VerifiedRawResponse) -> pl.DataFrame:
    """Map a verified ``daily`` response to G1 bars without adj_factor."""
    try:
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="daily", allow_empty=False)
        start, end = _request_range(verified)
        ts_code = _require_param(verified, "ts_code")
        rows: list[dict[str, Any]] = []
        for raw in frame.iter_rows(named=True):
            symbol = _require_a_share(raw.get("ts_code"), expected=ts_code)
            trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            open_, high, low, close = _parse_ohlc(raw)
            volume = _parse_non_negative(raw.get("vol"), scale=100.0)
            amount = _parse_non_negative(raw.get("amount"), scale=1000.0)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "amount": amount,
                    "source": _SOURCE,
                }
            )
        out = pl.DataFrame(rows, schema={
            "symbol": pl.Utf8,
            "trade_date": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
            "amount": pl.Float64,
            "source": pl.Utf8,
        }).select(list(_DAILY_OUT))
        _reject_duplicate(out, ["symbol", "trade_date", "source"])
        return out.sort(["symbol", "trade_date", "source"])
    except M3G1MappingError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_MAPPER_VALUE_INVALID") from None


def map_g1_adjustment_factor_response(*, response: VerifiedRawResponse) -> pl.DataFrame:
    """Map a verified ``adj_factor`` response; keep every vendor trade date."""
    try:
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="adj_factor", allow_empty=False)
        start, end = _request_range(verified)
        ts_code = _require_param(verified, "ts_code")
        rows: list[dict[str, Any]] = []
        for raw in frame.iter_rows(named=True):
            symbol = _require_a_share(raw.get("ts_code"), expected=ts_code)
            effective_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            factor = _parse_positive(raw.get("adj_factor"))
            rows.append(
                {
                    "symbol": symbol,
                    "effective_date": effective_date,
                    "adj_factor": factor,
                    "source": _SOURCE,
                }
            )
        out = pl.DataFrame(rows, schema={
            "symbol": pl.Utf8,
            "effective_date": pl.Date,
            "adj_factor": pl.Float64,
            "source": pl.Utf8,
        }).select(list(_FACTOR_OUT))
        _reject_duplicate(out, ["symbol", "effective_date", "source"])
        out = out.sort(["symbol", "effective_date", "source"])
        return _validate_schema(out, AdjustmentFactorSchema)
    except M3G1MappingError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_MAPPER_VALUE_INVALID") from None


def map_g1_benchmark_response(*, response: VerifiedRawResponse) -> pl.DataFrame:
    """Map a verified ``index_daily`` response to BenchmarkBar1d."""
    try:
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="index_daily", allow_empty=False)
        start, end = _request_range(verified)
        ts_code = _require_param(verified, "ts_code")
        if ts_code != _BENCHMARK:
            raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
        snapshot = verified.receipt.raw_snapshot_id
        rows: list[dict[str, Any]] = []
        for raw in frame.iter_rows(named=True):
            code = raw.get("ts_code")
            if type(code) is not str or code != _BENCHMARK:
                raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
            trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            open_, high, low, close = _parse_ohlc(raw)
            rows.append(
                {
                    "benchmark": _BENCHMARK,
                    "trade_date": trade_date,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "source": _SOURCE,
                    "source_snapshot_id": snapshot,
                }
            )
        out = pl.DataFrame(rows, schema={
            "benchmark": pl.Utf8,
            "trade_date": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "source": pl.Utf8,
            "source_snapshot_id": pl.Utf8,
        }).select(list(_BENCH_OUT))
        _reject_duplicate(out, ["benchmark", "trade_date", "source"])
        out = out.sort(["benchmark", "trade_date", "source"])
        return _validate_schema(out, BenchmarkBar1dSchema)
    except M3G1MappingError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_MAPPER_VALUE_INVALID") from None


def map_g1_suspension_response(*, response: VerifiedRawResponse) -> pl.DataFrame:
    """Map a verified ``suspend_d`` response; empty is allowed."""
    try:
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="suspend_d", allow_empty=True)
        start, end = _request_range(verified)
        snapshot = verified.receipt.raw_snapshot_id
        empty = pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "trade_date": pl.Date,
                "suspension_scope": pl.Utf8,
                "suspension_detail": pl.Utf8,
                "source": pl.Utf8,
                "source_snapshot_id": pl.Utf8,
            }
        ).select(list(_SUSP_OUT))
        if frame.is_empty():
            return _validate_schema(empty, Suspension1dSchema)

        groups: dict[tuple[str, dt.date], list[str | None]] = {}
        for raw in frame.iter_rows(named=True):
            symbol = _require_a_share(raw.get("ts_code"), expected=None)
            trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            suspend_type = raw.get("suspend_type")
            if suspend_type != "S":
                raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
            timing = raw.get("suspend_timing")
            if timing is not None and type(timing) is not str:
                raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
            key = (symbol, trade_date)
            groups.setdefault(key, []).append(timing)

        rows: list[dict[str, Any]] = []
        for (symbol, trade_date), timings in groups.items():
            nulls = [t for t in timings if t is None]
            parts = [t for t in timings if t is not None]
            if nulls and parts:
                raise M3G1MappingError("G1_MAPPER_SUSPENSION_CONFLICT")
            if nulls:
                rows.append(
                    {
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "suspension_scope": "FULL_DAY",
                        "suspension_detail": None,
                        "source": _SOURCE,
                        "source_snapshot_id": snapshot,
                    }
                )
                continue
            unique_parts = sorted(set(parts))
            detail = " | ".join(unique_parts)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "suspension_scope": "PARTIAL",
                    "suspension_detail": detail,
                    "source": _SOURCE,
                    "source_snapshot_id": snapshot,
                }
            )

        out = pl.DataFrame(rows, schema={
            "symbol": pl.Utf8,
            "trade_date": pl.Date,
            "suspension_scope": pl.Utf8,
            "suspension_detail": pl.Utf8,
            "source": pl.Utf8,
            "source_snapshot_id": pl.Utf8,
        }).select(list(_SUSP_OUT))
        _reject_duplicate(out, ["symbol", "trade_date", "source"])
        out = out.sort(["symbol", "trade_date", "source"])
        return _validate_schema(out, Suspension1dSchema)
    except M3G1MappingError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_MAPPER_VALUE_INVALID") from None


def _consume_verified(response: object) -> VerifiedRawResponse:
    """Rebuild exact VerifiedRawResponse; only consume a successful rebuild."""
    if type(response) is not VerifiedRawResponse:
        raise M3G1MappingError("G1_MAPPER_RESPONSE_INVALID")
    try:
        return VerifiedRawResponse(
            response.spec,
            response.receipt,
            response.receipt_sha256,
            response.frame,
        )
    except Exception:
        raise M3G1MappingError("G1_MAPPER_RESPONSE_INVALID") from None


def _prepare(
    response: VerifiedRawResponse, *, endpoint: str, allow_empty: bool
) -> pl.DataFrame:
    if (
        response.spec.endpoint != endpoint
        or response.receipt.endpoint != endpoint
    ):
        raise M3G1MappingError("G1_MAPPER_ENDPOINT_MISMATCH")
    expected = tuple(TUSHARE_FIELDS[endpoint].split(","))
    if tuple(response.frame.columns) != expected:
        raise M3G1MappingError("G1_MAPPER_COLUMNS_INVALID")
    if tuple(response.receipt.columns) != expected:
        raise M3G1MappingError("G1_MAPPER_COLUMNS_INVALID")
    params = dict(response.spec.parameters)
    if params.get("fields") != TUSHARE_FIELDS[endpoint]:
        raise M3G1MappingError("G1_MAPPER_COLUMNS_INVALID")
    if response.frame.is_empty() and not allow_empty:
        raise M3G1MappingError("G1_MAPPER_EMPTY")
    return response.frame


def _require_param(response: VerifiedRawResponse, key: str) -> str:
    value = dict(response.spec.parameters).get(key)
    if type(value) is not str or not value:
        raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
    return value


def _request_range(response: VerifiedRawResponse) -> tuple[dt.date, dt.date]:
    params = dict(response.spec.parameters)
    try:
        start = _parse_request_date(params["start_date"])
        end = _parse_request_date(params["end_date"])
    except (KeyError, TypeError, ValueError):
        raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH") from None
    if start > end:
        raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
    return start, end


def _parse_request_date(value: str) -> dt.date:
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise ValueError("bad date")
    return dt.datetime.strptime(value, "%Y%m%d").date()


def _parse_trade_date(
    value: object, *, start: dt.date, end: dt.date
) -> dt.date:
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    try:
        parsed = dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID") from None
    if parsed < start or parsed > end:
        raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
    return parsed


def _require_a_share(value: object, *, expected: str | None) -> str:
    if type(value) is not str or not _A_SHARE.fullmatch(value):
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    if expected is not None and value != expected:
        raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
    return value


def _parse_ohlc(raw: dict[str, Any]) -> tuple[float, float, float, float]:
    open_ = _parse_positive(raw.get("open"))
    high = _parse_positive(raw.get("high"))
    low = _parse_positive(raw.get("low"))
    close = _parse_positive(raw.get("close"))
    if not (low <= open_ <= high and low <= close <= high):
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    return open_, high, low, close


def _parse_positive(value: object) -> float:
    number = _parse_finite_number(value)
    if number <= 0:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    return number


def _parse_non_negative(value: object, *, scale: float) -> float:
    number = _parse_finite_number(value)
    if number < 0:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    return number * scale


def _parse_finite_number(value: object) -> float:
    if type(value) is bool or value is None:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    if type(value) is int:
        number = float(value)
    elif type(value) is float:
        number = value
    else:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    if not math.isfinite(number):
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    return number


def _reject_duplicate(frame: pl.DataFrame, keys: list[str]) -> None:
    if frame.is_empty():
        return
    dup = frame.group_by(keys).len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise M3G1MappingError("G1_MAPPER_DUPLICATE_KEY")


def _validate_schema(frame: pl.DataFrame, schema: Any) -> pl.DataFrame:
    try:
        return schema.validate(frame)
    except Exception as exc:
        raise _sanitize(exc, "G1_MAPPER_SCHEMA_INVALID") from None


def _sanitize(exc: BaseException, code: str) -> M3G1MappingError:
    """Convert underlying errors without leaking paths/tokens/rows."""
    _ = exc  # intentionally unused; prevents attaching cause/message
    return M3G1MappingError(code)
