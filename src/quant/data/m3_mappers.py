"""M3 G1 core mappers: VerifiedRawResponse -> standard clean frames."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Sequence
from typing import Any

import polars as pl

from quant.data.m3_backfill import TUSHARE_FIELDS, VerifiedRawResponse
from quant.domain import AdjustmentFactorSchema, BenchmarkBar1dSchema, Suspension1dSchema

_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_DATE8 = re.compile(r"^[0-9]{8}$")
_SOURCE = "tushare"
_BENCHMARK = "510300.SH"
_BENCHMARK_MODE = "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
_BENCHMARK_METHOD_VERSION = "tushare_510300_fund_daily_fund_adj_hfq_v1"
_BENCHMARK_DIVIDEND_RECONCILIATION_VERSION = "tushare_fund_div_implemented_cash_v1"
_MAPPER_VERSION = "m3-g1-tushare-mapper-v2"
_DIV_PROC_IMPLEMENTED = "实施"
_FACTOR_RATIO_RTOL = 0.001

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
        "G1_MAPPER_BENCHMARK_CLOSURE_INVALID",
        "G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED",
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


def map_g1_benchmark_response(
    *,
    fund_daily: VerifiedRawResponse,
    fund_adj_segments: Sequence[VerifiedRawResponse],
    fund_div: VerifiedRawResponse,
    factor_ratio_rtol: float = _FACTOR_RATIO_RTOL,
) -> pl.DataFrame:
    """Map planned ``fund_daily`` + ``fund_adj`` + ``fund_div`` to ETF HFQ BenchmarkBar1d."""
    try:
        rtol = _validate_factor_rtol(factor_ratio_rtol)
        daily = _consume_verified(fund_daily)
        div = _consume_verified(fund_div)
        if type(fund_adj_segments) is not tuple and type(fund_adj_segments) is not list:
            raise M3G1MappingError("G1_MAPPER_BENCHMARK_CLOSURE_INVALID")
        adj_items = [_consume_verified(item) for item in fund_adj_segments]
        if not adj_items:
            raise M3G1MappingError("G1_MAPPER_BENCHMARK_CLOSURE_INVALID")

        daily_frame = _prepare(daily, endpoint="fund_daily", allow_empty=False)
        start, end = _request_range(daily)
        ts_code = _require_param(daily, "ts_code")
        if ts_code != _BENCHMARK:
            raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")

        _assert_fund_adj_closure(adj_items, benchmark=ts_code, start=start, end=end)
        div_frame = _prepare(div, endpoint="fund_div", allow_empty=False)
        div_code = _require_param(div, "ts_code")
        if div_code != _BENCHMARK:
            raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
        div_params = dict(div.spec.parameters)
        if "start_date" in div_params or "end_date" in div_params:
            raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")

        daily_rows = _parse_fund_daily_rows(daily_frame, expected=ts_code, start=start, end=end)
        factor_rows = _parse_fund_adj_rows(adj_items, expected=ts_code)
        _assert_daily_factor_coverage(daily_rows, factor_rows)
        events = _project_implemented_cash_events(div_frame, expected=ts_code)
        _reconcile_dividend_factors(
            daily_rows=daily_rows,
            factor_rows=factor_rows,
            events=events,
            window_start=start,
            window_end=end,
            rtol=rtol,
        )

        snapshot = _benchmark_source_snapshot_id(
            responses=(daily, *adj_items, div)
        )
        rows: list[dict[str, Any]] = []
        for day in sorted(daily_rows):
            raw = daily_rows[day]
            factor = factor_rows[day]
            rows.append(
                {
                    "benchmark": _BENCHMARK,
                    "trade_date": day,
                    "open": raw["open"] * factor,
                    "high": raw["high"] * factor,
                    "low": raw["low"] * factor,
                    "close": raw["close"] * factor,
                    "source": _SOURCE,
                    "source_snapshot_id": snapshot,
                }
            )
        out = pl.DataFrame(
            rows,
            schema={
                "benchmark": pl.Utf8,
                "trade_date": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "source": pl.Utf8,
                "source_snapshot_id": pl.Utf8,
            },
        ).select(list(_BENCH_OUT))
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


def _validate_factor_rtol(value: object) -> float:
    if type(value) is bool or type(value) is not float:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    if not math.isfinite(value) or value < 0.0 or value > 0.01:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    return value


def _assert_fund_adj_closure(
    adj_items: Sequence[VerifiedRawResponse],
    *,
    benchmark: str,
    start: dt.date,
    end: dt.date,
) -> None:
    request_ids = [item.spec.request_id for item in adj_items]
    if len(request_ids) != len(set(request_ids)):
        raise M3G1MappingError("G1_MAPPER_BENCHMARK_CLOSURE_INVALID")
    segments: list[tuple[dt.date, dt.date]] = []
    for item in adj_items:
        _prepare(item, endpoint="fund_adj", allow_empty=False)
        code = _require_param(item, "ts_code")
        if code != benchmark:
            raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
        seg_start, seg_end = _request_range(item)
        if seg_start > seg_end:
            raise M3G1MappingError("G1_MAPPER_BENCHMARK_CLOSURE_INVALID")
        segments.append((seg_start, seg_end))
    segments.sort(key=lambda row: (row[0], row[1]))
    if segments[0][0] != start or segments[-1][1] != end:
        raise M3G1MappingError("G1_MAPPER_BENCHMARK_CLOSURE_INVALID")
    for index in range(1, len(segments)):
        prev_end = segments[index - 1][1]
        seg_start = segments[index][0]
        if seg_start != prev_end + dt.timedelta(days=1):
            raise M3G1MappingError("G1_MAPPER_BENCHMARK_CLOSURE_INVALID")


def _parse_fund_daily_rows(
    frame: pl.DataFrame, *, expected: str, start: dt.date, end: dt.date
) -> dict[dt.date, dict[str, float]]:
    rows: dict[dt.date, dict[str, float]] = {}
    for raw in frame.iter_rows(named=True):
        code = raw.get("ts_code")
        if type(code) is not str or code != expected:
            raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
        trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
        open_, high, low, close = _parse_ohlc(raw)
        pre_close = _parse_positive(raw.get("pre_close"))
        if trade_date in rows:
            raise M3G1MappingError("G1_MAPPER_DUPLICATE_KEY")
        rows[trade_date] = {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "pre_close": pre_close,
        }
    if not rows:
        raise M3G1MappingError("G1_MAPPER_EMPTY")
    return rows


def _parse_fund_adj_rows(
    adj_items: Sequence[VerifiedRawResponse], *, expected: str
) -> dict[dt.date, float]:
    rows: dict[dt.date, float] = {}
    for item in adj_items:
        start, end = _request_range(item)
        for raw in item.frame.iter_rows(named=True):
            code = raw.get("ts_code")
            if type(code) is not str or code != expected:
                raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
            trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            factor = _parse_positive(raw.get("adj_factor"))
            if trade_date in rows:
                raise M3G1MappingError("G1_MAPPER_DUPLICATE_KEY")
            rows[trade_date] = factor
    if not rows:
        raise M3G1MappingError("G1_MAPPER_EMPTY")
    ordered = sorted(rows)
    if ordered != sorted(set(ordered)):
        raise M3G1MappingError("G1_MAPPER_DUPLICATE_KEY")
    return rows


def _assert_daily_factor_coverage(
    daily_rows: dict[dt.date, dict[str, float]],
    factor_rows: dict[dt.date, float],
) -> None:
    daily_dates = sorted(daily_rows)
    factor_dates = sorted(factor_rows)
    if daily_dates != factor_dates:
        raise M3G1MappingError("G1_MAPPER_BENCHMARK_CLOSURE_INVALID")
    for day in daily_dates:
        factor = factor_rows[day]
        if not math.isfinite(factor) or factor <= 0.0:
            raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")


def _parse_optional_date8(value: object) -> dt.date | None:
    if value is None:
        return None
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise M3G1MappingError("G1_MAPPER_VALUE_INVALID") from exc


def _project_implemented_cash_events(
    frame: pl.DataFrame, *, expected: str
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for raw in frame.iter_rows(named=True):
        code = raw.get("ts_code")
        if type(code) is not str or code != expected:
            raise M3G1MappingError("G1_MAPPER_REQUEST_SCOPE_MISMATCH")
        div_proc = raw.get("div_proc")
        if div_proc != _DIV_PROC_IMPLEMENTED:
            continue
        ann_date = _parse_optional_date8(raw.get("ann_date"))
        imp_anndate = _parse_optional_date8(raw.get("imp_anndate"))
        record_date = _parse_optional_date8(raw.get("record_date"))
        ex_date = _parse_optional_date8(raw.get("ex_date"))
        pay_date = _parse_optional_date8(raw.get("pay_date"))
        div_cash_raw = raw.get("div_cash")
        if (
            ann_date is None
            or imp_anndate is None
            or record_date is None
            or ex_date is None
            or pay_date is None
            or div_cash_raw is None
        ):
            raise M3G1MappingError("G1_MAPPER_VALUE_INVALID")
        div_cash = _parse_positive(div_cash_raw)
        projected.append(
            {
                "ts_code": code,
                "ann_date": ann_date,
                "imp_anndate": imp_anndate,
                "record_date": record_date,
                "ex_date": ex_date,
                "pay_date": pay_date,
                "div_cash": div_cash,
            }
        )

    # Collapse identical economic projections; conflict on core cash identity.
    by_event: dict[tuple[Any, ...], set[tuple[dt.date, float]]] = {}
    for item in projected:
        key = (
            item["ts_code"],
            item["ann_date"],
            item["imp_anndate"],
            item["record_date"],
            item["pay_date"],
        )
        by_event.setdefault(key, set()).add((item["ex_date"], item["div_cash"]))
    events: list[dict[str, Any]] = []
    for key, cash_set in sorted(by_event.items(), key=lambda row: row[0]):
        if len(cash_set) != 1:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        ex_date, div_cash = next(iter(cash_set))
        events.append(
            {
                "ts_code": key[0],
                "ann_date": key[1],
                "imp_anndate": key[2],
                "record_date": key[3],
                "pay_date": key[4],
                "ex_date": ex_date,
                "div_cash": div_cash,
            }
        )
    return events


def _relative_close(actual: float, expected: float, *, rtol: float) -> bool:
    if not math.isfinite(actual) or not math.isfinite(expected):
        return False
    if expected == 0.0 or actual == 0.0:
        return False
    return math.isclose(actual, expected, rel_tol=rtol, abs_tol=0.0)


def _reconcile_dividend_factors(
    *,
    daily_rows: dict[dt.date, dict[str, float]],
    factor_rows: dict[dt.date, float],
    events: Sequence[dict[str, Any]],
    window_start: dt.date,
    window_end: dt.date,
    rtol: float,
) -> None:
    sessions = sorted(daily_rows)
    session_index = {day: idx for idx, day in enumerate(sessions)}
    window_events = [
        item
        for item in events
        if window_start <= item["ex_date"] <= window_end
    ]
    explained_jumps: set[dt.date] = set()
    for event in window_events:
        ex_date = event["ex_date"]
        if ex_date not in session_index:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        idx = session_index[ex_date]
        if idx == 0:
            # First window session: prior factor jump is not decidable.
            continue
        prev_date = sessions[idx - 1]
        prev_close = daily_rows[prev_date]["close"]
        ex_pre_close = daily_rows[ex_date]["pre_close"]
        expected_pre = prev_close - event["div_cash"]
        if expected_pre <= 0.0 or ex_pre_close <= 0.0 or prev_close <= 0.0:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        if not _relative_close(ex_pre_close, expected_pre, rtol=rtol):
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        prev_factor = factor_rows[prev_date]
        ex_factor = factor_rows[ex_date]
        if prev_factor <= 0.0 or ex_factor <= 0.0:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        actual_ratio = ex_factor / prev_factor
        expected_ratio = prev_close / ex_pre_close
        if expected_ratio <= 0.0:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        if not _relative_close(actual_ratio, expected_ratio, rtol=rtol):
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        if actual_ratio == 1.0 or math.isclose(actual_ratio, 1.0, rel_tol=rtol, abs_tol=0.0):
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        explained_jumps.add(ex_date)

    for idx in range(1, len(sessions)):
        prev_date = sessions[idx - 1]
        cur_date = sessions[idx]
        prev_factor = factor_rows[prev_date]
        cur_factor = factor_rows[cur_date]
        if prev_factor <= 0.0 or cur_factor <= 0.0:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        ratio = cur_factor / prev_factor
        jumped = not math.isclose(ratio, 1.0, rel_tol=rtol, abs_tol=0.0)
        if jumped and cur_date not in explained_jumps:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")
        if (not jumped) and cur_date in explained_jumps:
            raise M3G1MappingError("G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED")


def _benchmark_source_snapshot_id(
    *, responses: Sequence[VerifiedRawResponse]
) -> str:
    identities = [
        {
            "endpoint": item.spec.endpoint,
            "request_id": item.spec.request_id,
            "stable_response_sha256": item.receipt.stable_response_sha256,
        }
        for item in responses
    ]
    identities.sort(
        key=lambda row: (
            row["endpoint"],
            row["request_id"],
            row["stable_response_sha256"],
        )
    )
    payload = json.dumps(
        identities,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
