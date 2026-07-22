"""M3 G1 B3: monthly index_weight observations -> conservative PIT membership."""

from __future__ import annotations

import calendar as py_calendar
import datetime as dt
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import polars as pl

from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    TushareRequestBatch,
    TushareRequestSpec,
    VerifiedRawResponse,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain import (
    IndexConstituentObservationSchema,
    InstrumentSchema,
    TradeCalendarSchema,
    UniverseMembershipSchema,
)

_UNIVERSE = "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
_SOURCE = "tushare"
_INDEX_CODE = "000300.SH"
_EXPECTED_COUNT = 300
_RAW_COLUMNS = tuple(TUSHARE_FIELDS["index_weight"].split(","))
_OBS_COLUMNS = (
    "universe",
    "observation_date",
    "symbol",
    "weight",
    "source",
    "source_snapshot_id",
)
_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_DATE8 = re.compile(r"^[0-9]{8}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_ERROR_CODES = frozenset(
    {
        "G1_MEMBERSHIP_BATCH_INVALID",
        "G1_MEMBERSHIP_RESPONSE_SET_MISMATCH",
        "G1_MEMBERSHIP_RESPONSE_INVALID",
        "G1_MEMBERSHIP_REQUEST_SCOPE_INVALID",
        "G1_MEMBERSHIP_COLUMNS_INVALID",
        "G1_MEMBERSHIP_VALUE_INVALID",
        "G1_MEMBERSHIP_DUPLICATE_KEY",
        "G1_MEMBERSHIP_MONTH_MISSING",
        "G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID",
        "G1_MEMBERSHIP_WEIGHT_SUM_INVALID",
        "G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID",
        "G1_MEMBERSHIP_CALENDAR_INVALID",
        "G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID",
        "G1_MEMBERSHIP_CALENDAR_MISMATCH",
        "G1_MEMBERSHIP_INSTRUMENT_INVALID",
        "G1_MEMBERSHIP_LIFECYCLE_INVALID",
        "G1_MEMBERSHIP_SIGNAL_RANGE_INVALID",
        "G1_MEMBERSHIP_WARMUP_MISSING",
        "G1_MEMBERSHIP_INTERVAL_INVALID",
        "G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID",
        "G1_MEMBERSHIP_RESULT_INVALID",
    }
)


class M3IndexMembershipError(ValueError):
    """Stable B3 membership boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown membership error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3IndexMembershipError({self.code!r})"


@dataclass(frozen=True)
class ObservedMembershipResult:
    observations: pl.DataFrame
    membership: pl.DataFrame
    eligible_keys: pl.DataFrame
    observations_sha256: str
    membership_sha256: str
    eligible_keys_sha256: str

    def __post_init__(self) -> None:
        try:
            observations = _validate_observation_frame(
                self.observations, require_universe=None
            )
            membership = _validate_membership_frame(self.membership)
            eligible = _validate_eligible_frame(self.eligible_keys)
            # Consume validator returns: never leave caller pre-validation frames exposed.
            object.__setattr__(self, "observations", observations)
            object.__setattr__(self, "membership", membership)
            object.__setattr__(self, "eligible_keys", eligible)
            reported = (
                self.observations_sha256,
                self.membership_sha256,
                self.eligible_keys_sha256,
            )
            if any(type(value) is not str or not _HEX64.fullmatch(value) for value in reported):
                raise M3IndexMembershipError("G1_MEMBERSHIP_RESULT_INVALID")
            digests = (
                clean_table_content_sha256(
                    table_name="index_constituent_observation",
                    frame=self.observations,
                ),
                clean_table_content_sha256(
                    table_name="universe_membership",
                    frame=self.membership,
                ),
                clean_table_content_sha256(
                    table_name="eligible_keys",
                    frame=self.eligible_keys,
                ),
            )
            if digests != reported:
                raise M3IndexMembershipError("G1_MEMBERSHIP_RESULT_INVALID")
        except M3IndexMembershipError:
            raise
        except Exception:
            raise M3IndexMembershipError("G1_MEMBERSHIP_RESULT_INVALID") from None


def normalize_index_weight_observations(
    *,
    batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse],
    universe: str,
) -> pl.DataFrame:
    """Normalize verified INDEX_WEIGHT responses into observation rows."""
    try:
        if universe != _UNIVERSE:
            raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
        rebuilt_batch = _consume_batch(batch)
        month_by_request = _validate_index_weight_batch(rebuilt_batch)
        verified_list = _consume_responses(responses)
        _match_response_set(rebuilt_batch, verified_list)

        rows: list[dict[str, Any]] = []
        seen_keys: set[tuple[dt.date, str, str]] = set()
        months_with_obs: set[tuple[int, int]] = set()

        for verified in verified_list:
            month_key = month_by_request[verified.spec.request_id]
            frame = _prepare_index_weight_frame(verified)
            snapshot = verified.receipt.raw_snapshot_id
            month_start, month_end = _request_month_bounds(verified)
            if frame.is_empty():
                raise M3IndexMembershipError("G1_MEMBERSHIP_MONTH_MISSING")
            for raw in frame.iter_rows(named=True):
                index_code = raw.get("index_code")
                if type(index_code) is not str or index_code != _INDEX_CODE:
                    raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
                symbol = _parse_symbol(raw.get("con_code"))
                observation_date = _parse_observation_date(
                    raw.get("trade_date"), start=month_start, end=month_end
                )
                weight = _parse_weight(raw.get("weight"))
                key = (observation_date, symbol, _SOURCE)
                if key in seen_keys:
                    raise M3IndexMembershipError("G1_MEMBERSHIP_DUPLICATE_KEY")
                seen_keys.add(key)
                months_with_obs.add(month_key)
                rows.append(
                    {
                        "universe": _UNIVERSE,
                        "observation_date": observation_date,
                        "symbol": symbol,
                        "weight": weight,
                        "source": _SOURCE,
                        "source_snapshot_id": snapshot,
                    }
                )

        expected_months = set(month_by_request.values())
        if months_with_obs != expected_months:
            raise M3IndexMembershipError("G1_MEMBERSHIP_MONTH_MISSING")

        out = pl.DataFrame(
            rows,
            schema={
                "universe": pl.Utf8,
                "observation_date": pl.Date,
                "symbol": pl.Utf8,
                "weight": pl.Float64,
                "source": pl.Utf8,
                "source_snapshot_id": pl.Utf8,
            },
        ).select(list(_OBS_COLUMNS))
        _assert_observation_groups(out)
        validated = _validate_schema(out, IndexConstituentObservationSchema)
        return validated.sort(
            ["observation_date", "symbol", "source", "source_snapshot_id"]
        )
    except M3IndexMembershipError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError):
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID") from None


def build_observed_membership(
    *,
    observations: pl.DataFrame,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    universe: str,
    signal_start: dt.date,
    signal_end: dt.date,
    expected_constituent_count: int,
) -> ObservedMembershipResult:
    """Build signal-window membership intervals and eligible keys from observations."""
    try:
        if universe != _UNIVERSE:
            raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
        if expected_constituent_count != _EXPECTED_COUNT:
            raise M3IndexMembershipError("G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID")
        if type(signal_start) is not dt.date or type(signal_end) is not dt.date:
            raise M3IndexMembershipError("G1_MEMBERSHIP_SIGNAL_RANGE_INVALID")
        if signal_start > signal_end:
            raise M3IndexMembershipError("G1_MEMBERSHIP_SIGNAL_RANGE_INVALID")

        obs = _validate_observation_frame(observations, require_universe=universe)
        if obs.is_empty():
            raise M3IndexMembershipError("G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID")
        _assert_observation_groups(obs)

        calendar = _validate_schema(calendars, TradeCalendarSchema)
        instrument = _validate_schema(instruments, InstrumentSchema)
        sh_sessions, natural_open = _prepare_calendar(
            calendar,
            observations=obs,
            signal_start=signal_start,
            signal_end=signal_end,
        )
        if signal_start not in sh_sessions or signal_end not in sh_sessions:
            raise M3IndexMembershipError("G1_MEMBERSHIP_SIGNAL_RANGE_INVALID")
        if not natural_open[signal_start] or not natural_open[signal_end]:
            raise M3IndexMembershipError("G1_MEMBERSHIP_SIGNAL_RANGE_INVALID")

        instrument_map = _prepare_instruments(instrument, obs)
        intervals = _build_raw_intervals(obs, sh_sessions)
        clipped = _clip_and_merge_intervals(
            intervals,
            sh_sessions=sh_sessions,
            signal_start=signal_start,
            signal_end=signal_end,
            instrument_map=instrument_map,
        )
        membership = UniverseMembershipSchema.validate(
            pl.DataFrame(
                clipped,
                schema={
                    "universe": pl.Utf8,
                    "symbol": pl.Utf8,
                    "effective_from": pl.Date,
                    "effective_to": pl.Date,
                },
            ).sort(["universe", "symbol", "effective_from", "effective_to"])
        )
        _assert_membership_invariants(membership, signal_start=signal_start, signal_end=signal_end)

        eligible = _build_eligible_keys(
            membership,
            sh_sessions=sh_sessions,
            signal_start=signal_start,
            signal_end=signal_end,
        )
        result = ObservedMembershipResult(
            observations=obs.sort(
                ["observation_date", "symbol", "source", "source_snapshot_id"]
            ),
            membership=membership,
            eligible_keys=eligible,
            observations_sha256=clean_table_content_sha256(
                table_name="index_constituent_observation", frame=obs
            ),
            membership_sha256=clean_table_content_sha256(
                table_name="universe_membership", frame=membership
            ),
            eligible_keys_sha256=clean_table_content_sha256(
                table_name="eligible_keys", frame=eligible
            ),
        )
        return result
    except M3IndexMembershipError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError):
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID") from None


def verify_observed_membership_result(
    *,
    batch: TushareRequestBatch,
    responses: Sequence[VerifiedRawResponse],
    result: ObservedMembershipResult,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    universe: str,
    signal_start: dt.date,
    signal_end: dt.date,
    expected_constituent_count: int,
) -> None:
    """Re-normalize and rebuild; compare frames and digests against ``result``."""
    try:
        if type(result) is not ObservedMembershipResult:
            raise M3IndexMembershipError("G1_MEMBERSHIP_RESULT_INVALID")
        # Re-enter constructor closure on the provided result object.
        ObservedMembershipResult(
            result.observations,
            result.membership,
            result.eligible_keys,
            result.observations_sha256,
            result.membership_sha256,
            result.eligible_keys_sha256,
        )
        observations = normalize_index_weight_observations(
            batch=batch, responses=responses, universe=universe
        )
        rebuilt = build_observed_membership(
            observations=observations,
            calendars=calendars,
            instruments=instruments,
            universe=universe,
            signal_start=signal_start,
            signal_end=signal_end,
            expected_constituent_count=expected_constituent_count,
        )
        if (
            rebuilt.observations_sha256 != result.observations_sha256
            or rebuilt.membership_sha256 != result.membership_sha256
            or rebuilt.eligible_keys_sha256 != result.eligible_keys_sha256
            or not _frames_equal(rebuilt.observations, result.observations)
            or not _frames_equal(rebuilt.membership, result.membership)
            or not _frames_equal(rebuilt.eligible_keys, result.eligible_keys)
        ):
            raise M3IndexMembershipError("G1_MEMBERSHIP_RESULT_INVALID")
    except M3IndexMembershipError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError):
        raise M3IndexMembershipError("G1_MEMBERSHIP_RESULT_INVALID") from None


def _consume_batch(batch: object) -> TushareRequestBatch:
    if type(batch) is not TushareRequestBatch:
        raise M3IndexMembershipError("G1_MEMBERSHIP_BATCH_INVALID")
    try:
        return TushareRequestBatch(
            batch.schema_version,
            batch.phase,
            batch.requests,
            batch.batch_sha256,
        )
    except Exception:
        raise M3IndexMembershipError("G1_MEMBERSHIP_BATCH_INVALID") from None


def _validate_index_weight_batch(
    batch: TushareRequestBatch,
) -> dict[str, tuple[int, int]]:
    if batch.phase != "INDEX_WEIGHT" or not batch.requests:
        raise M3IndexMembershipError("G1_MEMBERSHIP_BATCH_INVALID")
    month_by_request: dict[str, tuple[int, int]] = {}
    months: list[tuple[int, int]] = []
    for spec in batch.requests:
        try:
            rebuilt = TushareRequestSpec(
                spec.schema_version, spec.request_id, spec.endpoint, spec.parameters
            )
        except Exception:
            raise M3IndexMembershipError("G1_MEMBERSHIP_BATCH_INVALID") from None
        if rebuilt.endpoint != "index_weight":
            raise M3IndexMembershipError("G1_MEMBERSHIP_BATCH_INVALID")
        params = dict(rebuilt.parameters)
        if params.get("index_code") != _INDEX_CODE:
            raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
        if params.get("fields") != TUSHARE_FIELDS["index_weight"]:
            raise M3IndexMembershipError("G1_MEMBERSHIP_COLUMNS_INVALID")
        try:
            start = _parse_request_date(params["start_date"])
            end = _parse_request_date(params["end_date"])
        except (KeyError, TypeError, ValueError):
            raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID") from None
        if start.day != 1 or start > end:
            raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
        last_day = py_calendar.monthrange(start.year, start.month)[1]
        if end != dt.date(start.year, start.month, last_day):
            raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
        month_key = (start.year, start.month)
        month_by_request[rebuilt.request_id] = month_key
        months.append(month_key)
    if len(months) != len(set(months)):
        raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
    ordered = sorted(months)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if (current[0] * 12 + current[1]) - (previous[0] * 12 + previous[1]) != 1:
            raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
    return month_by_request


def _consume_responses(
    responses: Sequence[VerifiedRawResponse],
) -> list[VerifiedRawResponse]:
    if not isinstance(responses, Sequence) or isinstance(responses, (str, bytes)):
        raise M3IndexMembershipError("G1_MEMBERSHIP_RESPONSE_INVALID")
    out: list[VerifiedRawResponse] = []
    for response in responses:
        if type(response) is not VerifiedRawResponse:
            raise M3IndexMembershipError("G1_MEMBERSHIP_RESPONSE_INVALID")
        try:
            out.append(
                VerifiedRawResponse(
                    response.spec,
                    response.receipt,
                    response.receipt_sha256,
                    response.frame,
                )
            )
        except Exception:
            raise M3IndexMembershipError("G1_MEMBERSHIP_RESPONSE_INVALID") from None
    return out


def _match_response_set(
    batch: TushareRequestBatch, responses: Sequence[VerifiedRawResponse]
) -> None:
    expected = Counter(spec.request_id for spec in batch.requests)
    actual = Counter(item.spec.request_id for item in responses)
    if expected != actual:
        raise M3IndexMembershipError("G1_MEMBERSHIP_RESPONSE_SET_MISMATCH")
    for item in responses:
        if item.spec.endpoint != "index_weight" or item.receipt.endpoint != "index_weight":
            raise M3IndexMembershipError("G1_MEMBERSHIP_RESPONSE_INVALID")


def _prepare_index_weight_frame(response: VerifiedRawResponse) -> pl.DataFrame:
    if tuple(response.frame.columns) != _RAW_COLUMNS:
        raise M3IndexMembershipError("G1_MEMBERSHIP_COLUMNS_INVALID")
    if tuple(response.receipt.columns) != _RAW_COLUMNS:
        raise M3IndexMembershipError("G1_MEMBERSHIP_COLUMNS_INVALID")
    params = dict(response.spec.parameters)
    if params.get("fields") != TUSHARE_FIELDS["index_weight"]:
        raise M3IndexMembershipError("G1_MEMBERSHIP_COLUMNS_INVALID")
    for dtype in response.frame.dtypes:
        base = dtype.base_type() if hasattr(dtype, "base_type") else dtype
        if base in {pl.List, pl.Struct} or "List" in str(dtype) or "Struct" in str(dtype):
            raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID")
    return response.frame


def _request_month_bounds(response: VerifiedRawResponse) -> tuple[dt.date, dt.date]:
    params = dict(response.spec.parameters)
    try:
        start = _parse_request_date(params["start_date"])
        end = _parse_request_date(params["end_date"])
    except (KeyError, TypeError, ValueError):
        raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID") from None
    return start, end


def _parse_request_date(value: str) -> dt.date:
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise ValueError("bad date")
    return dt.datetime.strptime(value, "%Y%m%d").date()


def _parse_observation_date(
    value: object, *, start: dt.date, end: dt.date
) -> dt.date:
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID")
    try:
        parsed = dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID") from None
    if parsed < start or parsed > end:
        raise M3IndexMembershipError("G1_MEMBERSHIP_REQUEST_SCOPE_INVALID")
    return parsed


def _parse_symbol(value: object) -> str:
    if type(value) is not str or not _A_SHARE.fullmatch(value):
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID")
    return value


def _parse_weight(value: object) -> float:
    if type(value) is bool or value is None:
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID")
    if type(value) is int:
        number = float(value)
    elif type(value) is float:
        number = value
    elif type(value) is str:
        if value.strip() == "" or value.strip().lower() in {"nan", "inf", "+inf", "-inf"}:
            raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID")
        try:
            number = float(Decimal(value))
        except (InvalidOperation, ValueError):
            raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID") from None
    else:
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID")
    if not math.isfinite(number) or number <= 0:
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID")
    return number


def _assert_observation_groups(frame: pl.DataFrame) -> None:
    if frame.is_empty():
        raise M3IndexMembershipError("G1_MEMBERSHIP_MONTH_MISSING")
    for observation_date, group in frame.group_by("observation_date", maintain_order=True):
        _ = observation_date
        symbols = group.get_column("symbol").to_list()
        if len(symbols) != _EXPECTED_COUNT or len(set(symbols)) != _EXPECTED_COUNT:
            raise M3IndexMembershipError("G1_MEMBERSHIP_CONSTITUENT_COUNT_INVALID")
        ordered_weights = [
            float(weight)
            for _, weight in sorted(
                zip(
                    group.get_column("symbol").to_list(),
                    group.get_column("weight").to_list(),
                    strict=True,
                ),
                key=lambda item: item[0],
            )
        ]
        total = math.fsum(ordered_weights)
        if total < 99.0 or total > 101.0:
            raise M3IndexMembershipError("G1_MEMBERSHIP_WEIGHT_SUM_INVALID")


def _validate_observation_frame(
    frame: pl.DataFrame, *, require_universe: str | None
) -> pl.DataFrame:
    try:
        validated = IndexConstituentObservationSchema.validate(frame)
    except Exception:
        raise M3IndexMembershipError("G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID") from None
    universes = validated.get_column("universe").unique().to_list()
    sources = validated.get_column("source").unique().to_list()
    if len(universes) != 1 or len(sources) != 1 or sources[0] != _SOURCE:
        raise M3IndexMembershipError("G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID")
    if require_universe is not None and universes[0] != require_universe:
        raise M3IndexMembershipError("G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID")
    if universes[0] != _UNIVERSE:
        raise M3IndexMembershipError("G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID")
    return validated


def _validate_membership_frame(frame: pl.DataFrame) -> pl.DataFrame:
    try:
        validated = UniverseMembershipSchema.validate(frame)
    except Exception:
        raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID") from None
    if validated.is_empty() or validated.get_column("effective_to").null_count() != 0:
        raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")
    return validated


def _validate_eligible_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if not isinstance(frame, pl.DataFrame) or list(frame.columns) != ["as_of", "symbol"]:
        raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
    try:
        for name in ("as_of", "symbol"):
            dtype = frame.schema[name]
            text = str(dtype)
            base = dtype.base_type() if hasattr(dtype, "base_type") else dtype
            if base in {pl.List, pl.Struct} or "List" in text or "Struct" in text:
                raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
        # Canonicalize to the only public dtypes; Utf8 dates coerce like Schema boundaries.
        validated = frame.select(
            pl.col("as_of").cast(pl.Date),
            pl.col("symbol").cast(pl.Utf8),
        )
    except M3IndexMembershipError:
        raise
    except Exception:
        raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID") from None
    if validated.is_empty():
        raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
    if validated.height != validated.select(["as_of", "symbol"]).unique().height:
        raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
    return validated


def _validate_schema(frame: pl.DataFrame, schema: Any) -> pl.DataFrame:
    try:
        return schema.validate(frame)
    except Exception as exc:
        if schema is TradeCalendarSchema:
            raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_INVALID") from None
        if schema is InstrumentSchema:
            raise M3IndexMembershipError("G1_MEMBERSHIP_INSTRUMENT_INVALID") from None
        if schema is IndexConstituentObservationSchema:
            raise M3IndexMembershipError("G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID") from None
        _ = exc
        raise M3IndexMembershipError("G1_MEMBERSHIP_VALUE_INVALID") from None


def _prepare_calendar(
    calendar: pl.DataFrame,
    *,
    observations: pl.DataFrame,
    signal_start: dt.date,
    signal_end: dt.date,
) -> tuple[list[dt.date], dict[dt.date, bool]]:
    obs_dates = observations.get_column("observation_date").unique().sort().to_list()
    if not obs_dates:
        raise M3IndexMembershipError("G1_MEMBERSHIP_OBSERVATION_SCHEMA_INVALID")
    min_obs: dt.date = obs_dates[0]
    max_obs: dt.date = obs_dates[-1]
    calendar_anchor = max(max_obs, signal_end)

    by_market: dict[str, dict[dt.date, bool]] = {"SH": {}, "SZ": {}}
    for market, day, is_open in calendar.select("market", "date", "is_open").iter_rows():
        if market not in by_market:
            continue
        if day in by_market[market]:
            raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_INVALID")
        by_market[market][day] = bool(is_open)

    sh_dates = set(by_market["SH"])
    if not sh_dates:
        raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID")

    sh_open_sorted = sorted(day for day, is_open in by_market["SH"].items() if is_open)
    proof_candidates = [day for day in sh_open_sorted if day > calendar_anchor]
    if not proof_candidates:
        raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID")
    calendar_proof_end = proof_candidates[0]

    coverage_start = min(min_obs, signal_start)
    coverage_end = calendar_proof_end
    cursor = coverage_start
    while cursor <= coverage_end:
        if cursor not in by_market["SH"] or cursor not in by_market["SZ"]:
            raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID")
        if by_market["SH"][cursor] != by_market["SZ"][cursor]:
            raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_MISMATCH")
        cursor += dt.timedelta(days=1)

    natural_open = {
        day: by_market["SH"][day]
        for day in sorted(by_market["SH"])
        if coverage_start <= day <= coverage_end
    }
    for observation_date in obs_dates:
        if observation_date not in natural_open or not natural_open[observation_date]:
            raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_INVALID")
    return sh_open_sorted, natural_open


def _prepare_instruments(
    instruments: pl.DataFrame, observations: pl.DataFrame
) -> dict[str, tuple[dt.date, dt.date | None]]:
    """Validate instrument table; membership contract applies only to observed symbols.

    Full input must already pass ``InstrumentSchema`` and symbol uniqueness. Unrelated
    Schema-valid rows (e.g. ETF) do not affect membership. Observed symbols must be
    A-share STOCK/CNY with correct market suffix and a legal lifecycle at observation.
    """
    if instruments.height != instruments.get_column("symbol").n_unique():
        raise M3IndexMembershipError("G1_MEMBERSHIP_INSTRUMENT_INVALID")

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in instruments.iter_rows(named=True):
        by_symbol[row["symbol"]] = row

    needed = set(observations.get_column("symbol").to_list())
    missing = needed - set(by_symbol)
    if missing:
        raise M3IndexMembershipError("G1_MEMBERSHIP_INSTRUMENT_INVALID")

    mapping: dict[str, tuple[dt.date, dt.date | None]] = {}
    for symbol in needed:
        row = by_symbol[symbol]
        market = row["market"]
        suffix = symbol.rsplit(".", 1)[-1]
        if suffix != market or market not in {"SH", "SZ"}:
            raise M3IndexMembershipError("G1_MEMBERSHIP_INSTRUMENT_INVALID")
        if row["instrument_type"] != "STOCK" or row["currency"] != "CNY":
            raise M3IndexMembershipError("G1_MEMBERSHIP_INSTRUMENT_INVALID")
        mapping[symbol] = (row["list_date"], row["delist_date"])

    for observation_date, group in observations.group_by("observation_date"):
        day = observation_date[0] if isinstance(observation_date, tuple) else observation_date
        for symbol in group.get_column("symbol").to_list():
            list_date, delist_date = mapping[symbol]
            if list_date > day:
                raise M3IndexMembershipError("G1_MEMBERSHIP_LIFECYCLE_INVALID")
            if delist_date is not None and delist_date < day:
                raise M3IndexMembershipError("G1_MEMBERSHIP_LIFECYCLE_INVALID")
    return mapping


def _session_index(sessions: Sequence[dt.date]) -> dict[dt.date, int]:
    return {day: index for index, day in enumerate(sessions)}


def _next_session(day: dt.date, sessions: Sequence[dt.date]) -> dt.date:
    for session in sessions:
        if session > day:
            return session
    raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID")


def _prev_session(day: dt.date, sessions: Sequence[dt.date]) -> dt.date:
    previous = None
    for session in sessions:
        if session >= day:
            break
        previous = session
    if previous is None:
        raise M3IndexMembershipError("G1_MEMBERSHIP_CALENDAR_COVERAGE_INVALID")
    return previous


def _first_session_on_or_after(
    day: dt.date, sessions: Sequence[dt.date]
) -> dt.date | None:
    for session in sessions:
        if session >= day:
            return session
    return None


def _last_session_on_or_before(
    day: dt.date, sessions: Sequence[dt.date]
) -> dt.date | None:
    previous = None
    for session in sessions:
        if session > day:
            break
        previous = session
    return previous


def _build_raw_intervals(
    observations: pl.DataFrame, sh_sessions: Sequence[dt.date]
) -> list[dict[str, Any]]:
    grouped: dict[dt.date, list[str]] = {}
    for observation_date, group in observations.group_by("observation_date", maintain_order=True):
        day = observation_date[0] if isinstance(observation_date, tuple) else observation_date
        grouped[day] = sorted(group.get_column("symbol").to_list())
    obs_dates = sorted(grouped)
    activations: list[tuple[dt.date, dt.date, list[str]]] = []
    for obs_day in obs_dates:
        activation = _next_session(obs_day, sh_sessions)
        activations.append((obs_day, activation, grouped[obs_day]))

    intervals: list[dict[str, Any]] = []
    for position, (_obs_day, activation, symbols) in enumerate(activations):
        if position + 1 < len(activations):
            next_activation = activations[position + 1][1]
            end = _prev_session(next_activation, sh_sessions)
        else:
            # Open-ended until clipped to signal_end later; use a sentinel far end
            # that will be clipped. Use last known session for temporary bound.
            end = sh_sessions[-1]
        if end < activation:
            raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")
        for symbol in symbols:
            intervals.append(
                {
                    "universe": _UNIVERSE,
                    "symbol": symbol,
                    "effective_from": activation,
                    "effective_to": end,
                    "_activation": activation,
                    "_obs_pos": position,
                }
            )
    return intervals


def _clip_and_merge_intervals(
    intervals: list[dict[str, Any]],
    *,
    sh_sessions: Sequence[dt.date],
    signal_start: dt.date,
    signal_end: dt.date,
    instrument_map: dict[str, tuple[dt.date, dt.date | None]],
) -> list[dict[str, Any]]:
    session_set = set(sh_sessions)
    # Drop intervals that activate after signal_end (observation kept elsewhere).
    active_intervals = [
        item for item in intervals if item["effective_from"] <= signal_end
    ]
    activations = sorted({item["effective_from"] for item in active_intervals})
    if not activations or min(activations) > signal_start:
        raise M3IndexMembershipError("G1_MEMBERSHIP_WARMUP_MISSING")

    by_symbol: dict[str, list[tuple[dt.date, dt.date]]] = defaultdict(list)
    for item in active_intervals:
        symbol = item["symbol"]
        start = item["effective_from"]
        end = item["effective_to"]
        # Clip to signal window first.
        start = max(start, signal_start)
        end = min(end, signal_end)
        if end < start:
            continue
        list_date, delist_date = instrument_map[symbol]
        life_from = _first_session_on_or_after(list_date, sh_sessions)
        life_to = (
            _last_session_on_or_before(delist_date, sh_sessions)
            if delist_date is not None
            else signal_end
        )
        if life_from is None or life_to is None or life_from > life_to:
            # Empty lifecycle in audit domain.
            if start <= signal_end and end >= signal_start:
                raise M3IndexMembershipError("G1_MEMBERSHIP_LIFECYCLE_INVALID")
            continue
        start = max(start, life_from)
        end = min(end, life_to, signal_end)
        if end < start:
            # Lifecycle removed the interval before activation or after delist;
            # do not invent replacements — eligible may temporarily fall below 300.
            continue
        if start not in session_set or end not in session_set:
            raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")
        by_symbol[symbol].append((start, end))

    merged_rows: list[dict[str, Any]] = []
    session_index = _session_index(sh_sessions)

    for symbol, ranges in sorted(by_symbol.items()):
        ranges = sorted(ranges)
        merged: list[tuple[dt.date, dt.date]] = []
        for start, end in ranges:
            if not merged:
                merged.append((start, end))
                continue
            prev_start, prev_end = merged[-1]
            # Merge if continuous on adjacent SH sessions.
            prev_end_idx = session_index[prev_end]
            start_idx = session_index[start]
            if start_idx <= prev_end_idx + 1 and start <= signal_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))
        for start, end in merged:
            if end is None or end < start:
                raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")
            merged_rows.append(
                {
                    "universe": _UNIVERSE,
                    "symbol": symbol,
                    "effective_from": start,
                    "effective_to": end,
                }
            )

    if not merged_rows:
        raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")

    # Overlap check per symbol.
    per_symbol: dict[str, list[tuple[dt.date, dt.date]]] = defaultdict(list)
    for row in merged_rows:
        per_symbol[row["symbol"]].append((row["effective_from"], row["effective_to"]))
    for ranges in per_symbol.values():
        ordered = sorted(ranges)
        for (a_start, a_end), (b_start, b_end) in zip(ordered, ordered[1:], strict=False):
            _ = b_end
            if b_start <= a_end:
                raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")
            # Adjacent merge residual.
            if session_index[b_start] == session_index[a_end] + 1:
                raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")

    return merged_rows


def _assert_membership_invariants(
    membership: pl.DataFrame, *, signal_start: dt.date, signal_end: dt.date
) -> None:
    if membership.get_column("effective_to").null_count() != 0:
        raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")
    if (
        membership.filter(pl.col("effective_from") < signal_start).height > 0
        or membership.filter(pl.col("effective_to") > signal_end).height > 0
    ):
        raise M3IndexMembershipError("G1_MEMBERSHIP_INTERVAL_INVALID")


def _build_eligible_keys(
    membership: pl.DataFrame,
    *,
    sh_sessions: Sequence[dt.date],
    signal_start: dt.date,
    signal_end: dt.date,
) -> pl.DataFrame:
    signal_sessions = [day for day in sh_sessions if signal_start <= day <= signal_end]
    if not signal_sessions:
        raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
    rows: list[dict[str, Any]] = []
    intervals = list(
        membership.select("symbol", "effective_from", "effective_to").iter_rows()
    )
    for as_of in signal_sessions:
        symbols = sorted(
            {
                symbol
                for symbol, start, end in intervals
                if start <= as_of <= end
            }
        )
        # Observation remains exactly 300; lifecycle clip may leave a session
        # non-empty but below 300 until the next monthly observation activates.
        if not symbols or len(symbols) > _EXPECTED_COUNT:
            raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
        for symbol in symbols:
            rows.append({"as_of": as_of, "symbol": symbol})
    out = pl.DataFrame(
        rows,
        schema={"as_of": pl.Date, "symbol": pl.Utf8},
    ).sort(["as_of", "symbol"])
    if out.height != out.select(["as_of", "symbol"]).unique().height:
        raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
    if out.is_empty():
        raise M3IndexMembershipError("G1_MEMBERSHIP_ELIGIBLE_KEYS_INVALID")
    return out


def _frames_equal(left: pl.DataFrame, right: pl.DataFrame) -> bool:
    if list(left.columns) != list(right.columns) or left.dtypes != right.dtypes:
        return False
    if left.height != right.height:
        return False
    return left.equals(right)
