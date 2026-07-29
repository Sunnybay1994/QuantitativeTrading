"""M3 G1 B2C execution facts: price limits and corporate-action reconciliation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import polars as pl

from quant.data.connectors.cninfo import CNINFO_SOURCE
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    HistoryWindow,
    VerifiedCninfoRawResponse,
    VerifiedRawResponse,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain import (
    AdjustmentFactorSchema,
    Bar1dSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    CorporateActionSelectionEvidenceSchema,
    InstrumentSchema,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TradeCalendarSchema,
)

G1_PRICE_LIMIT_METHOD_VERSION = "tushare_stk_limit_suspension_aware_v2"
G1_CORPORATE_ACTION_SELECTION_VERSION = (
    "tushare_dividend_cninfo_rights_capital_iso_date_cross_end_exact_fold_v6"
)
G1_CORPORATE_ACTION_RECONCILIATION_VERSION = (
    "tushare_factor_daily_preclose_suspension_resume_v6"
)

_SOURCE = "tushare"
_CNINFO_SOURCE = CNINFO_SOURCE
_LEDGER_SOURCES = frozenset({_SOURCE, _CNINFO_SOURCE})
_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_DATE8 = re.compile(r"^[0-9]{8}$")
_DATE_ISO = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_DATE_MIN = dt.date.min
_RIGHTS_SHARE_REL_TOL = 1e-6
_RIGHTS_SHARE_ABS_TOL = 1e-6

_ERROR_CODES = frozenset(
    {
        "G1_EXECUTION_FACT_RESPONSE_INVALID",
        "G1_EXECUTION_FACT_ENDPOINT_MISMATCH",
        "G1_EXECUTION_FACT_EMPTY",
        "G1_EXECUTION_FACT_COLUMNS_INVALID",
        "G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH",
        "G1_EXECUTION_FACT_VALUE_INVALID",
        "G1_EXECUTION_FACT_DUPLICATE_KEY",
        "G1_PRICE_LIMIT_UNPROVEN",
        "G1_PRICE_LIMIT_SCHEMA_INVALID",
        "G1_PRICE_LIMIT_COVERAGE_INVALID",
        "G1_CORPORATE_ACTION_EVENT_INVALID",
        "G1_CORPORATE_ACTION_VERSION_CONFLICT",
        "G1_CORPORATE_ACTION_SCHEMA_INVALID",
        "G1_CORPORATE_ACTION_RESULT_INVALID",
        "G1_CORPORATE_ACTION_CALENDAR_INVALID",
        "G1_CORPORATE_ACTION_FACTOR_INVALID",
        "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED",
        "G1_CORPORATE_ACTION_RECONCILIATION_INVALID",
    }
)

_PRICE_LIMIT_OUT = (
    "symbol",
    "trade_date",
    "pre_close",
    "has_price_limit",
    "up_limit",
    "down_limit",
    "source",
    "source_snapshot_id",
)

_LEDGER_OUT = (
    "event_id",
    "symbol",
    "ex_date",
    "action_type",
    "cash_per_share_gross",
    "stock_ratio",
    "rights_price",
    "rights_ratio",
    "rights_actual_shares",
    "rights_pre_shares",
    "rights_post_shares",
    "record_date",
    "pay_date",
    "stock_list_date",
    "vendor_record_id",
    "source",
    "source_snapshot_id",
)

_EVIDENCE_OUT = (
    "economic_event_key_sha256",
    "candidate_id",
    "symbol",
    "action_type",
    "end_date",
    "record_date",
    "ex_date",
    "imp_ann_date",
    "ann_date",
    "cash_per_share_gross",
    "stock_ratio",
    "rights_price",
    "rights_ratio",
    "rights_actual_shares",
    "rights_pre_shares",
    "rights_post_shares",
    "pay_date",
    "stock_list_date",
    "vendor_record_id",
    "candidate_rank",
    "candidate_count",
    "raw_row_count",
    "selected",
    "selection_reason",
    "source",
    "source_request_id",
    "source_snapshot_id",
)

_RECON_OUT = (
    "symbol",
    "previous_factor_date",
    "effective_date",
    "previous_close_date",
    "previous_close",
    "ex_reference_price",
    "daily_request_id",
    "daily_stable_response_sha256",
    "event_count",
    "event_ids_json",
    "event_ids_sha256",
    "cash_per_share_gross",
    "stock_ratio",
    "rights_ratio",
    "rights_subscription_cash_per_share",
    "declared_dividend_factor_ratio",
    "market_reference_factor_ratio",
    "actual_factor_ratio",
    "market_reference_relative_error",
    "declared_dividend_relative_error",
    "factor_ratio_rtol",
    "status",
    "source",
)


class M3G1ExecutionFactError(ValueError):
    """Stable execution-fact boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown execution-fact error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3G1ExecutionFactError({self.code!r})"


@dataclass(frozen=True)
class CorporateActionSelectionResult:
    ledger: pl.DataFrame
    selection_evidence: pl.DataFrame
    ledger_sha256: str
    selection_evidence_sha256: str

    def __post_init__(self) -> None:
        try:
            _verify_selection_result_body(self)
        except M3G1ExecutionFactError:
            raise
        except Exception:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID") from None


@dataclass(frozen=True)
class CorporateActionReconciliationResult:
    evidence: pl.DataFrame
    evidence_sha256: str

    def __post_init__(self) -> None:
        try:
            _verify_reconciliation_result_body(self)
        except M3G1ExecutionFactError:
            raise
        except Exception:
            raise M3G1ExecutionFactError(
                "G1_CORPORATE_ACTION_RECONCILIATION_INVALID"
            ) from None


def build_g1_daily_pre_close_lookup(
    *, daily_responses: Sequence[VerifiedRawResponse]
) -> dict[tuple[str, dt.date], float]:
    """Build ``(symbol, trade_date) -> daily.pre_close`` from verified daily responses.

    Used to repair ``stk_limit`` rows whose ``pre_close`` is a vendor sentinel while
    ``up_limit``/``down_limit`` remain positive vendor facts. Does not invent limits.
    """
    out: dict[tuple[str, dt.date], float] = {}
    if not isinstance(daily_responses, Sequence):
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_RESPONSE_INVALID")
    for response in daily_responses:
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="daily", allow_empty=True)
        start, end = _request_range(verified)
        ts_code = _require_param(verified, "ts_code")
        for raw in frame.iter_rows(named=True):
            symbol = _require_a_share(raw.get("ts_code"), expected=ts_code)
            trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            pre_close = _parse_strict_scalar(raw.get("pre_close"), allow_null=False)
            assert pre_close is not None
            if pre_close <= 0:
                raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
            key = (symbol, trade_date)
            if key in out:
                raise M3G1ExecutionFactError("G1_EXECUTION_FACT_DUPLICATE_KEY")
            out[key] = pre_close
    return out


def map_g1_price_limit_response(
    *,
    response: VerifiedRawResponse,
    daily_pre_close: Mapping[tuple[str, dt.date], float] | None = None,
) -> pl.DataFrame:
    """Map verified ``stk_limit`` rows to ``PriceLimit1d``; sentinel rows omitted.

    When ``pre_close`` is null/0 but both limit sides are positive, and
    ``daily_pre_close`` supplies a same-day daily ``pre_close`` that sits strictly
    between the vendor limits, emit a clean row using that daily value. Empty
    sentinel rows (null/0 pre_close with absent/zero sides) remain omitted.
    """
    try:
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="stk_limit", allow_empty=False)
        start, end = _request_range(verified)
        ts_code = _require_param(verified, "ts_code")
        snapshot = verified.receipt.raw_snapshot_id
        lookup = daily_pre_close
        if lookup is not None and not isinstance(lookup, Mapping):
            raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
        rows: list[dict[str, Any]] = []
        for raw in frame.iter_rows(named=True):
            symbol = _require_a_share(raw.get("ts_code"), expected=ts_code)
            trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            pre_close = _parse_strict_scalar(raw.get("pre_close"), allow_null=True)
            up_limit = _parse_strict_scalar(raw.get("up_limit"), allow_null=True)
            down_limit = _parse_strict_scalar(raw.get("down_limit"), allow_null=True)
            if pre_close is None or pre_close == 0.0:
                for side in (up_limit, down_limit):
                    if side is not None and side < 0:
                        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
                sides_absent = (up_limit is None or up_limit == 0.0) and (
                    down_limit is None or down_limit == 0.0
                )
                if sides_absent:
                    continue
                if (
                    up_limit is None
                    or down_limit is None
                    or up_limit <= 0
                    or down_limit <= 0
                ):
                    # One-sided / non-positive sides with sentinel pre_close: omit.
                    continue
                if lookup is None:
                    continue
                filled = lookup.get((symbol, trade_date))
                if filled is None or filled <= 0:
                    continue
                if not (down_limit < filled < up_limit):
                    raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
                pre_close = float(filled)
            if pre_close < 0:
                raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
            if up_limit is None or down_limit is None:
                raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
            if up_limit <= 0 or down_limit <= 0:
                raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
            if not (down_limit < pre_close < up_limit):
                raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "pre_close": pre_close,
                    "has_price_limit": True,
                    "up_limit": up_limit,
                    "down_limit": down_limit,
                    "source": _SOURCE,
                    "source_snapshot_id": snapshot,
                }
            )
        empty_schema = {
            "symbol": pl.Utf8,
            "trade_date": pl.Date,
            "pre_close": pl.Float64,
            "has_price_limit": pl.Boolean,
            "up_limit": pl.Float64,
            "down_limit": pl.Float64,
            "source": pl.Utf8,
            "source_snapshot_id": pl.Utf8,
        }
        out = (
            pl.DataFrame(rows, schema=empty_schema)
            if rows
            else pl.DataFrame(schema=empty_schema)
        ).select(list(_PRICE_LIMIT_OUT))
        _reject_duplicate(out, ["symbol", "trade_date", "source"])
        out = out.sort(["symbol", "trade_date", "source"])
        return _validate_schema(out, PriceLimit1dSchema, "G1_PRICE_LIMIT_SCHEMA_INVALID")
    except M3G1ExecutionFactError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_EXECUTION_FACT_VALUE_INVALID") from None


def require_g1_price_limit_coverage(
    *,
    price_limits: pl.DataFrame,
    eligible_keys: pl.DataFrame,
    suspensions: pl.DataFrame,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    bars: pl.DataFrame,
    history: HistoryWindow,
) -> pl.DataFrame:
    """Return sorted required ``(trade_date, symbol)`` keys for potential holdings.

    FULL_DAY suspensions are excluded. Keys without a same-day bar are also
    excluded: no executable OHLC evidence means the symbol is not tradeable that
    session (de-facto halt / data gap), same rationale as FULL_DAY.
    """
    try:
        history = _consume_history(
            history, code="G1_PRICE_LIMIT_COVERAGE_INVALID"
        )
        calendar = _validate_schema(
            calendars, TradeCalendarSchema, "G1_PRICE_LIMIT_COVERAGE_INVALID"
        )
        instrument_frame = _validate_schema(
            instruments, InstrumentSchema, "G1_PRICE_LIMIT_COVERAGE_INVALID"
        )
        suspension_frame = _validate_schema(
            suspensions, Suspension1dSchema, "G1_PRICE_LIMIT_COVERAGE_INVALID"
        )
        limits = _validate_schema(
            price_limits, PriceLimit1dSchema, "G1_PRICE_LIMIT_SCHEMA_INVALID"
        )
        bar_frame = _validate_schema(
            bars, Bar1dSchema, "G1_PRICE_LIMIT_COVERAGE_INVALID"
        )
        eligible = _validate_eligible_keys(eligible_keys)
        sh_sessions, _ = _prepare_history_calendar(
            calendar, history, code="G1_PRICE_LIMIT_COVERAGE_INVALID"
        )
        session_set = set(sh_sessions)
        for as_of in eligible.get_column("as_of").to_list():
            if as_of not in session_set:
                raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")

        instrument_map = _instrument_lifecycle(instrument_frame)
        eligible_symbols = sorted(set(eligible.get_column("symbol").to_list()))
        missing_instruments = set(eligible_symbols) - set(instrument_map)
        if missing_instruments:
            raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")

        for row in suspension_frame.iter_rows(named=True):
            if row["source"] != _SOURCE:
                raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")

        full_day: set[tuple[dt.date, str]] = set()
        partial: set[tuple[dt.date, str]] = set()
        for row in suspension_frame.iter_rows(named=True):
            key = (row["trade_date"], row["symbol"])
            if row["suspension_scope"] == "FULL_DAY":
                if key in full_day or key in partial:
                    raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
                full_day.add(key)
            else:
                if key in full_day or key in partial:
                    raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
                partial.add(key)

        bar_keys: set[tuple[dt.date, str]] = set()
        for row in bar_frame.iter_rows(named=True):
            if row["source"] != _SOURCE:
                raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
            bar_keys.add((row["trade_date"], row["symbol"]))

        required: list[tuple[dt.date, str]] = []
        for symbol in eligible_symbols:
            as_ofs = sorted(
                eligible.filter(pl.col("symbol") == symbol)
                .get_column("as_of")
                .to_list()
            )
            first_as_of = as_ofs[0]
            coverage_start = _next_session(first_as_of, sh_sessions)
            list_date, delist_date = instrument_map[symbol]
            if delist_date is not None:
                last_session = _last_session_on_or_before(delist_date, sh_sessions)
                if last_session is None:
                    raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
                coverage_end = min(history.end, last_session)
            else:
                coverage_end = history.end
            if coverage_start > coverage_end:
                continue
            if list_date > coverage_end:
                raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
            for session in sh_sessions:
                if session < coverage_start or session > coverage_end:
                    continue
                if session < list_date:
                    continue
                if delist_date is not None and session > delist_date:
                    continue
                key = (session, symbol)
                if key in full_day:
                    continue
                if key not in bar_keys:
                    continue
                required.append(key)

        required = sorted(set(required))
        limit_index: dict[tuple[dt.date, str], dict[str, Any]] = {}
        for row in limits.iter_rows(named=True):
            if row["source"] != _SOURCE:
                raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
            key = (row["trade_date"], row["symbol"])
            if key in limit_index:
                raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
            limit_index[key] = row

        for key in required:
            limit_row = limit_index.get(key)
            if limit_row is None or limit_row["has_price_limit"] is not True:
                raise M3G1ExecutionFactError("G1_PRICE_LIMIT_UNPROVEN")

        out = pl.DataFrame(
            {
                "trade_date": [day for day, _ in required],
                "symbol": [symbol for _, symbol in required],
            },
            schema={"trade_date": pl.Date, "symbol": pl.Utf8},
        ).sort(["trade_date", "symbol"])
        if out.height != out.unique(subset=["trade_date", "symbol"]).height:
            raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
        return out
    except M3G1ExecutionFactError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_PRICE_LIMIT_COVERAGE_INVALID") from None


def select_g1_corporate_actions(
    *, response: VerifiedRawResponse, history: HistoryWindow
) -> CorporateActionSelectionResult:
    """Select implemented dividend events inside ``history`` with version evidence."""
    try:
        history = _consume_history(
            history, code="G1_CORPORATE_ACTION_CALENDAR_INVALID"
        )
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="dividend", allow_empty=True)
        ts_code = _require_param(verified, "ts_code")
        request_id = verified.spec.request_id
        snapshot = verified.receipt.raw_snapshot_id

        parsed_rows: list[dict[str, Any]] = []
        for raw in frame.iter_rows(named=True):
            symbol = _require_a_share(raw.get("ts_code"), expected=ts_code)
            div_proc = raw.get("div_proc")
            if type(div_proc) is not str:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            if div_proc != "实施":
                continue
            ex_date = _parse_optional_date8(
                raw.get("ex_date"), allow_null=True, required=False
            )
            if ex_date is None:
                # Incomplete 实施: never invent ex_date from list/record/pay.
                # Omit from ledger (raw remains the vendor fact). Applies both
                # inside and outside the history window after vendor probe showed
                # persistent nulls and the same identity cannot be superseded.
                continue
            if ex_date < history.start or ex_date > history.end:
                continue
            end_date = _parse_optional_date8(
                raw.get("end_date"), allow_null=False, required=True
            )
            record_date = _parse_optional_date8(
                raw.get("record_date"), allow_null=False, required=True
            )
            assert end_date is not None and record_date is not None
            if record_date > ex_date:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            ann_date = _parse_optional_date8(raw.get("ann_date"), allow_null=True)
            imp_ann_date = _parse_optional_date8(
                raw.get("imp_ann_date"), allow_null=True
            )
            cash = _parse_dividend_leg_amount(raw.get("cash_div_tax"))
            stock = _parse_dividend_leg_amount(raw.get("stk_div"))
            if cash == 0.0 and stock == 0.0:
                # Zero-effect 实施 cannot enter the ledger; omit rather than invent.
                continue
            pay_date = _parse_optional_date8(raw.get("pay_date"), allow_null=True)
            list_date = _parse_optional_date8(raw.get("div_listdate"), allow_null=True)
            if cash > 0:
                if pay_date is None or pay_date < ex_date:
                    raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            elif pay_date is not None:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            if stock > 0:
                if list_date is None or list_date < ex_date:
                    raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            elif list_date is not None:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            base_date = _parse_optional_date8(raw.get("base_date"), allow_null=True)
            parsed_rows.append(
                {
                    "symbol": symbol,
                    "end_date": end_date,
                    "record_date": record_date,
                    "ex_date": ex_date,
                    "imp_ann_date": imp_ann_date,
                    "ann_date": ann_date,
                    "cash": cash,
                    "stock": stock,
                    "pay_date": pay_date,
                    "stock_list_date": list_date,
                    # Exact-identity provenance only; not used for ledger math.
                    "div_proc": div_proc,
                    "stk_div_raw": _parse_strict_scalar(
                        raw.get("stk_div"), allow_null=True
                    ),
                    "stk_bo_rate": _parse_strict_scalar(
                        raw.get("stk_bo_rate"), allow_null=True
                    ),
                    "stk_co_rate": _parse_strict_scalar(
                        raw.get("stk_co_rate"), allow_null=True
                    ),
                    "cash_div": _parse_strict_scalar(
                        raw.get("cash_div"), allow_null=True
                    ),
                    "cash_div_tax_raw": _parse_strict_scalar(
                        raw.get("cash_div_tax"), allow_null=True
                    ),
                    "base_date": base_date,
                    "base_share": _parse_strict_scalar(
                        raw.get("base_share"), allow_null=True
                    ),
                }
            )

        groups: dict[
            tuple[str, dt.date, dt.date, dt.date],
            list[dict[str, Any]],
        ] = {}
        for item in _fold_dividend_cross_end_exact_duplicates(parsed_rows):
            row = item["row"]
            group_key = (
                row["symbol"],
                row["end_date"],
                row["record_date"],
                row["ex_date"],
            )
            groups.setdefault(group_key, []).append(item)

        ledger_rows: list[dict[str, Any]] = []
        evidence_rows: list[dict[str, Any]] = []
        for group_key, candidates_raw in sorted(groups.items()):
            symbol, end_date, record_date, ex_date = group_key
            event_key = _economic_event_key_sha256(
                symbol, end_date, record_date, ex_date
            )
            folded = _fold_identical_candidates(candidates_raw)
            ranked = sorted(
                folded,
                key=lambda item: _version_rank_key(item["row"]),
                reverse=True,
            )
            rank_keys = [_version_rank_key(item["row"]) for item in ranked]
            if len(rank_keys) != len(set(rank_keys)):
                # Same rank with different decision fields already rejected in fold;
                # identical rank keys among distinct candidates means conflict.
                seen: dict[tuple[Any, ...], tuple[Any, ...]] = {}
                for item in ranked:
                    key = _version_rank_key(item["row"])
                    decision = _decision_fields(item["row"])
                    prior = seen.get(key)
                    if prior is None:
                        seen[key] = decision
                    elif prior != decision:
                        raise M3G1ExecutionFactError(
                            "G1_CORPORATE_ACTION_VERSION_CONFLICT"
                        )
            candidate_count = len(ranked)
            for index, item in enumerate(ranked, start=1):
                row = item["row"]
                candidate_id = _candidate_id_sha256(
                    event_key,
                    row["imp_ann_date"],
                    row["ann_date"],
                    row["cash"],
                    row["stock"],
                    row["pay_date"],
                    row["stock_list_date"],
                )
                selected = index == 1
                evidence_rows.append(
                    {
                        "economic_event_key_sha256": event_key,
                        "candidate_id": candidate_id,
                        "symbol": symbol,
                        "action_type": "DIVIDEND_DISTRIBUTION",
                        "end_date": end_date,
                        "record_date": record_date,
                        "ex_date": ex_date,
                        "imp_ann_date": row["imp_ann_date"],
                        "ann_date": row["ann_date"],
                        "cash_per_share_gross": row["cash"],
                        "stock_ratio": row["stock"],
                        "rights_price": None,
                        "rights_ratio": 0.0,
                        "rights_actual_shares": None,
                        "rights_pre_shares": None,
                        "rights_post_shares": None,
                        "pay_date": row["pay_date"],
                        "stock_list_date": row["stock_list_date"],
                        "vendor_record_id": None,
                        "candidate_rank": index,
                        "candidate_count": candidate_count,
                        "raw_row_count": item["raw_row_count"],
                        "selected": selected,
                        "selection_reason": (
                            "SELECTED_LATEST" if selected else "SUPERSEDED_OLDER"
                        ),
                        "source": _SOURCE,
                        "source_request_id": request_id,
                        "source_snapshot_id": snapshot,
                    }
                )
            selected_row = ranked[0]["row"]
            event_id = _event_id_sha256(
                symbol,
                end_date,
                record_date,
                ex_date,
                selected_row["cash"],
                selected_row["stock"],
            )
            ledger_rows.append(
                {
                    "event_id": event_id,
                    "symbol": symbol,
                    "ex_date": ex_date,
                    "action_type": "DIVIDEND_DISTRIBUTION",
                    "cash_per_share_gross": selected_row["cash"],
                    "stock_ratio": selected_row["stock"],
                    "rights_price": None,
                    "rights_ratio": 0.0,
                    "rights_actual_shares": None,
                    "rights_pre_shares": None,
                    "rights_post_shares": None,
                    "record_date": record_date,
                    "pay_date": selected_row["pay_date"],
                    "stock_list_date": selected_row["stock_list_date"],
                    "vendor_record_id": None,
                    "source": _SOURCE,
                    "source_snapshot_id": snapshot,
                }
            )

        ledger = _empty_or_frame(ledger_rows, _LEDGER_OUT, _ledger_schema())
        evidence = _empty_or_frame(evidence_rows, _EVIDENCE_OUT, _evidence_schema())
        ledger = ledger.sort(["symbol", "ex_date", "event_id"])
        evidence = evidence.sort(
            ["economic_event_key_sha256", "candidate_rank", "candidate_id"]
        )
        ledger = _validate_schema(
            ledger, CorporateActionLedgerSchema, "G1_CORPORATE_ACTION_SCHEMA_INVALID"
        )
        evidence = _validate_schema(
            evidence,
            CorporateActionSelectionEvidenceSchema,
            "G1_CORPORATE_ACTION_SCHEMA_INVALID",
        )
        ledger_sha = clean_table_content_sha256(
            table_name="corporate_action_ledger", frame=ledger
        )
        evidence_sha = clean_table_content_sha256(
            table_name="corporate_action_selection_evidence", frame=evidence
        )
        return CorporateActionSelectionResult(
            ledger=ledger,
            selection_evidence=evidence,
            ledger_sha256=ledger_sha,
            selection_evidence_sha256=evidence_sha,
        )
    except M3G1ExecutionFactError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_CORPORATE_ACTION_EVENT_INVALID") from None


def select_g1_cninfo_rights_actions(
    *,
    response: VerifiedCninfoRawResponse,
    history: HistoryWindow,
    symbols: Sequence[str],
) -> CorporateActionSelectionResult:
    """Select implemented A-share rights (配股) events from a CNINFO response.

    Each verified CNINFO record already carries a stable ``SUBID``; unlike
    Tushare dividend rows there is no multi-version candidate folding: one raw
    row is one candidate. Duplicate ``SUBID`` or multiple distinct rights rows
    resolving to the same ``(symbol, ex_date)`` fail closed rather than being
    silently merged, since there is no vendor-provided ranking signal to break
    the tie. Only successfully issued rights (actual/pre/post share counts
    mutually consistent) enter the ledger; failed issuances are omitted.
    """
    try:
        history = _consume_history(
            history, code="G1_CORPORATE_ACTION_CALENDAR_INVALID"
        )
        verified = _consume_cninfo_verified(response)
        code_to_symbol = _build_cninfo_symbol_map(symbols)
        request_id = verified.spec.request_id
        snapshot = verified.receipt.raw_snapshot_id

        seen_subids: set[str] = set()
        by_key: dict[tuple[str, dt.date], dict[str, Any]] = {}
        for raw in verified.frame.iter_rows(named=True):
            seccode = raw.get("SECCODE")
            if type(seccode) is not str or seccode not in code_to_symbol:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            symbol = code_to_symbol[seccode]

            subid = _require_cninfo_subid(raw.get("SUBID"))
            if subid in seen_subids:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            seen_subids.add(subid)

            f001v = raw.get("F001V")
            f002v = raw.get("F002V")
            is_a_share = (type(f001v) is str and f001v == "001001") or (
                type(f002v) is str and "A股" in f002v
            )
            if not is_a_share:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")

            declare_date = _parse_cninfo_iso_date(raw.get("DECLAREDATE"))
            record_date = _parse_cninfo_iso_date(raw.get("F011D"))
            ex_date = _parse_cninfo_iso_date(raw.get("F012D"))
            payment_start = _parse_cninfo_iso_date(raw.get("F013D"))
            payment_end = _parse_cninfo_iso_date(raw.get("F014D"))
            result_ann_date = _parse_cninfo_iso_date(raw.get("F052D"))
            list_date = _parse_cninfo_iso_date(raw.get("F038D"))

            rights_price = _parse_strict_scalar(raw.get("F005N"), allow_null=False)
            f004n = _parse_strict_scalar(raw.get("F004N"), allow_null=False)
            actual_shares = _parse_strict_scalar(raw.get("F017N"), allow_null=False)
            pre_shares = _parse_strict_scalar(raw.get("F024N"), allow_null=False)
            post_shares = _parse_strict_scalar(raw.get("F025N"), allow_null=False)
            assert (
                rights_price is not None
                and f004n is not None
                and actual_shares is not None
                and pre_shares is not None
                and post_shares is not None
            )
            if rights_price <= 0:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            if not math.isfinite(f004n) or f004n <= 0:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            rights_ratio = f004n / 10.0

            if ex_date < history.start or ex_date > history.end:
                # Out-of-window: omit, mirroring dividend selection semantics.
                continue

            if record_date >= ex_date:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            if declare_date > record_date:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            if payment_start > payment_end or payment_end >= ex_date:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            if result_ann_date > ex_date:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            if list_date < ex_date:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")

            if actual_shares <= 0 or pre_shares <= 0 or post_shares <= 0:
                # Failed/incomplete issuance: only successful rights are accepted.
                continue
            if post_shares <= pre_shares:
                continue
            if not math.isclose(
                post_shares - pre_shares,
                actual_shares,
                rel_tol=_RIGHTS_SHARE_REL_TOL,
                abs_tol=_RIGHTS_SHARE_ABS_TOL,
            ):
                continue

            key = (symbol, ex_date)
            if key in by_key:
                # Multiple (possibly conflicting) rights rows for the same
                # symbol/ex_date have no vendor ranking signal; fail closed.
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
            by_key[key] = {
                "symbol": symbol,
                "subid": subid,
                "declare_date": declare_date,
                "record_date": record_date,
                "ex_date": ex_date,
                "payment_start": payment_start,
                "payment_end": payment_end,
                "result_ann_date": result_ann_date,
                "list_date": list_date,
                "rights_price": rights_price,
                "rights_ratio": rights_ratio,
                "rights_actual_shares": actual_shares,
                "rights_pre_shares": pre_shares,
                "rights_post_shares": post_shares,
            }

        ledger_rows: list[dict[str, Any]] = []
        evidence_rows: list[dict[str, Any]] = []
        for key in sorted(by_key):
            item = by_key[key]
            symbol = item["symbol"]
            ex_date = item["ex_date"]
            record_date = item["record_date"]
            event_id = _rights_event_id_sha256(
                symbol,
                item["subid"],
                record_date,
                ex_date,
                item["rights_price"],
                item["rights_ratio"],
                item["rights_actual_shares"],
                item["rights_pre_shares"],
                item["rights_post_shares"],
            )
            event_key = _rights_economic_event_key_sha256(
                symbol, record_date, ex_date
            )
            candidate_id = _rights_candidate_id_sha256(
                event_key,
                item["subid"],
                item["rights_price"],
                item["rights_ratio"],
                item["rights_actual_shares"],
                item["rights_pre_shares"],
                item["rights_post_shares"],
            )
            ledger_rows.append(
                {
                    "event_id": event_id,
                    "symbol": symbol,
                    "ex_date": ex_date,
                    "action_type": "RIGHTS",
                    "cash_per_share_gross": 0.0,
                    "stock_ratio": 0.0,
                    "rights_price": item["rights_price"],
                    "rights_ratio": item["rights_ratio"],
                    "rights_actual_shares": item["rights_actual_shares"],
                    "rights_pre_shares": item["rights_pre_shares"],
                    "rights_post_shares": item["rights_post_shares"],
                    "record_date": record_date,
                    "pay_date": None,
                    "stock_list_date": item["list_date"],
                    "vendor_record_id": item["subid"],
                    "source": _CNINFO_SOURCE,
                    "source_snapshot_id": snapshot,
                }
            )
            evidence_rows.append(
                {
                    "economic_event_key_sha256": event_key,
                    "candidate_id": candidate_id,
                    "symbol": symbol,
                    "action_type": "RIGHTS",
                    "end_date": item["declare_date"],
                    "record_date": record_date,
                    "ex_date": ex_date,
                    "imp_ann_date": item["result_ann_date"],
                    "ann_date": item["declare_date"],
                    "cash_per_share_gross": 0.0,
                    "stock_ratio": 0.0,
                    "rights_price": item["rights_price"],
                    "rights_ratio": item["rights_ratio"],
                    "rights_actual_shares": item["rights_actual_shares"],
                    "rights_pre_shares": item["rights_pre_shares"],
                    "rights_post_shares": item["rights_post_shares"],
                    "pay_date": None,
                    "stock_list_date": item["list_date"],
                    "vendor_record_id": item["subid"],
                    "candidate_rank": 1,
                    "candidate_count": 1,
                    "raw_row_count": 1,
                    "selected": True,
                    "selection_reason": "SELECTED_LATEST",
                    "source": _CNINFO_SOURCE,
                    "source_request_id": request_id,
                    "source_snapshot_id": snapshot,
                }
            )

        ledger = _empty_or_frame(ledger_rows, _LEDGER_OUT, _ledger_schema())
        evidence = _empty_or_frame(evidence_rows, _EVIDENCE_OUT, _evidence_schema())
        ledger = ledger.sort(["symbol", "ex_date", "event_id"])
        evidence = evidence.sort(
            ["economic_event_key_sha256", "candidate_rank", "candidate_id"]
        )
        ledger = _validate_schema(
            ledger, CorporateActionLedgerSchema, "G1_CORPORATE_ACTION_SCHEMA_INVALID"
        )
        evidence = _validate_schema(
            evidence,
            CorporateActionSelectionEvidenceSchema,
            "G1_CORPORATE_ACTION_SCHEMA_INVALID",
        )
        ledger_sha = clean_table_content_sha256(
            table_name="corporate_action_ledger", frame=ledger
        )
        evidence_sha = clean_table_content_sha256(
            table_name="corporate_action_selection_evidence", frame=evidence
        )
        return CorporateActionSelectionResult(
            ledger=ledger,
            selection_evidence=evidence,
            ledger_sha256=ledger_sha,
            selection_evidence_sha256=evidence_sha,
        )
    except M3G1ExecutionFactError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_CORPORATE_ACTION_EVENT_INVALID") from None


def verify_corporate_action_selection_result(
    *, result: CorporateActionSelectionResult
) -> None:
    """Re-validate selection result Schema, closure and digests."""
    try:
        if type(result) is not CorporateActionSelectionResult:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
        _verify_selection_result_body(result)
    except M3G1ExecutionFactError:
        raise
    except Exception:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID") from None


def reconcile_g1_corporate_actions(
    *,
    corporate_actions: pl.DataFrame,
    bars: pl.DataFrame,
    adjustment_factors: pl.DataFrame,
    daily_responses: Sequence[VerifiedRawResponse],
    suspensions: pl.DataFrame,
    calendars: pl.DataFrame,
    history: HistoryWindow,
    factor_ratio_rtol: float,
) -> CorporateActionReconciliationResult:
    """Reconcile adjacent factor observations with declared and market references."""
    try:
        history = _consume_history(
            history, code="G1_CORPORATE_ACTION_CALENDAR_INVALID"
        )
        rtol = _validate_rtol(factor_ratio_rtol)
        calendar = _validate_schema(
            calendars, TradeCalendarSchema, "G1_CORPORATE_ACTION_CALENDAR_INVALID"
        )
        suspension_frame = _validate_schema(
            suspensions, Suspension1dSchema, "G1_CORPORATE_ACTION_FACTOR_INVALID"
        )
        actions = _validate_schema(
            corporate_actions,
            CorporateActionLedgerSchema,
            "G1_CORPORATE_ACTION_SCHEMA_INVALID",
        )
        bar_frame = _validate_schema(
            bars, Bar1dSchema, "G1_CORPORATE_ACTION_FACTOR_INVALID"
        )
        factor_frame = _validate_schema(
            adjustment_factors,
            AdjustmentFactorSchema,
            "G1_CORPORATE_ACTION_FACTOR_INVALID",
        )
        sh_sessions, _ = _prepare_history_calendar(
            calendar, history, code="G1_CORPORATE_ACTION_CALENDAR_INVALID"
        )
        session_set = set(sh_sessions)

        for frame, date_col in (
            (bar_frame, "trade_date"),
            (factor_frame, "effective_date"),
        ):
            if frame.height and (
                frame.filter(pl.col("source") != _SOURCE).height
                or frame.filter(
                    (pl.col(date_col) < history.start) | (pl.col(date_col) > history.end)
                ).height
            ):
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")

        if actions.height and (
            actions.filter(~pl.col("source").is_in(list(_LEDGER_SOURCES))).height
            or actions.filter(
                (pl.col("ex_date") < history.start) | (pl.col("ex_date") > history.end)
            ).height
        ):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")

        bar_symbols = set(bar_frame.get_column("symbol").to_list()) if bar_frame.height else set()
        factor_symbols = (
            set(factor_frame.get_column("symbol").to_list())
            if factor_frame.height
            else set()
        )
        if not bar_symbols or bar_symbols != factor_symbols:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
        action_symbols = (
            set(actions.get_column("symbol").to_list()) if actions.height else set()
        )
        if not action_symbols.issubset(bar_symbols):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")

        daily_by_symbol = _consume_daily_responses(
            daily_responses, symbols=bar_symbols, history=history
        )
        daily_proj = _project_daily_frames(daily_by_symbol)
        _assert_daily_matches_bars(daily_proj, bar_frame)

        full_day = _full_day_keys(suspension_frame)

        factors_by_symbol: dict[str, list[tuple[dt.date, float]]] = {
            symbol: [] for symbol in sorted(bar_symbols)
        }
        for row in factor_frame.sort(["symbol", "effective_date"]).iter_rows(named=True):
            day = row["effective_date"]
            if day not in session_set:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
            factors_by_symbol[row["symbol"]].append((day, float(row["adj_factor"])))
        for symbol, series in factors_by_symbol.items():
            # Publish-scoped factors may have a single observation (zero transitions).
            if len(series) < 1:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
            dates = [day for day, _ in series]
            if dates != sorted(set(dates)):
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")

        bar_factor_check = {
            (row["symbol"], row["trade_date"]): float(row["adj_factor"])
            for row in bar_frame.iter_rows(named=True)
        }
        independent_factors = {
            (symbol, day): factor
            for symbol, series in factors_by_symbol.items()
            for day, factor in series
        }
        for key, bar_factor in bar_factor_check.items():
            independent = independent_factors.get(key)
            if independent is None or independent != bar_factor:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")

        bars_by_symbol: dict[str, list[tuple[dt.date, float]]] = {
            symbol: [] for symbol in sorted(bar_symbols)
        }
        for row in bar_frame.sort(["symbol", "trade_date"]).iter_rows(named=True):
            bars_by_symbol[row["symbol"]].append(
                (row["trade_date"], float(row["close"]))
            )

        events_by_symbol_date: dict[tuple[str, dt.date], list[dict[str, Any]]] = {}
        for row in actions.iter_rows(named=True):
            if row["ex_date"] not in session_set:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
            key = (row["symbol"], row["ex_date"])
            series = factors_by_symbol[row["symbol"]]
            factor_dates = {day for day, _ in series}
            scoped_first = series[0][0]
            scoped_last = series[-1][0]
            # Ledger may retain history-window events whose ex_date lies outside
            # the publish-scoped factor range; omit from matching without failing.
            if row["ex_date"] < scoped_first or row["ex_date"] > scoped_last:
                continue
            if row["ex_date"] not in factor_dates:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
            # Window-edge: ex_date is the first factor observation, so no prior
            # factor day exists to form an actual ratio into the event. Omit from
            # reconciliation matching (ledger may still retain the economic event).
            if row["ex_date"] == scoped_first:
                continue
            bar_series = bars_by_symbol.get(row["symbol"], [])
            if not any(day < row["ex_date"] for day, _ in bar_series):
                # No unadjusted close strictly before ex_date (e.g. long halt
                # whose first bar is after the event). Declared/market formulas
                # are impossible; omit from matching.
                continue
            events_by_symbol_date.setdefault(key, []).append(dict(row))

        events_by_symbol_date = _assign_events_with_suspension_resume_delay(
            events_by_symbol_date=events_by_symbol_date,
            full_day=full_day,
            daily_proj=daily_proj,
            factors_by_symbol=factors_by_symbol,
            bars_by_symbol=bars_by_symbol,
            history=history,
            sh_sessions=sh_sessions,
            rtol=rtol,
        )

        evidence_rows: list[dict[str, Any]] = []
        for symbol in sorted(bar_symbols):
            series = factors_by_symbol[symbol]
            daily_verified = daily_by_symbol[symbol]
            daily_rows = daily_proj[symbol]
            bar_series = bars_by_symbol[symbol]
            request_id = daily_verified.spec.request_id
            stable = daily_verified.receipt.stable_response_sha256
            for index in range(1, len(series)):
                previous_factor_date, previous_factor = series[index - 1]
                effective_date, effective_factor = series[index]
                actual = effective_factor / previous_factor
                events = events_by_symbol_date.get((symbol, effective_date), [])
                if not events:
                    # B2C §9.2: no-event transition is fail-closed on factor jump.
                    evidence_rows.append(
                        _no_event_evidence_row(
                            symbol=symbol,
                            previous_factor_date=previous_factor_date,
                            effective_date=effective_date,
                            actual=actual,
                            request_id=request_id,
                            stable=stable,
                            rtol=rtol,
                        )
                    )
                    continue

                events_sorted = sorted(events, key=lambda item: item["event_id"])
                event_ids = [item["event_id"] for item in events_sorted]
                event_ids_json = _event_ids_json(event_ids)
                event_ids_digest = _event_set_sha256(event_ids)
                total_cash = math.fsum(
                    float(item["cash_per_share_gross"]) for item in events_sorted
                )
                total_stock = math.fsum(
                    float(item["stock_ratio"]) for item in events_sorted
                )
                total_rights_ratio = math.fsum(
                    float(item["rights_ratio"]) for item in events_sorted
                )
                total_rights_cash = math.fsum(
                    float(item["rights_price"]) * float(item["rights_ratio"])
                    for item in events_sorted
                    if item["action_type"] == "RIGHTS"
                )
                # Event branch failures must raise; never fall back to
                # event_count=0 / NO_EVENT_STABLE_FACTOR.
                prev_close_date, prev_close = _previous_close(
                    bar_series, effective_date
                )
                denominator = prev_close - total_cash + total_rights_cash
                if denominator <= 0 or not _supported_ratio(actual, rtol):
                    raise M3G1ExecutionFactError(
                        "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED"
                    )
                declared = (
                    prev_close
                    * (1.0 + total_stock + total_rights_ratio)
                    / denominator
                )
                if declared <= 1.0:
                    raise M3G1ExecutionFactError(
                        "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED"
                    )
                declared_error = abs(actual / declared - 1.0)
                daily_row = daily_rows.get(effective_date)
                if daily_row is not None:
                    ex_ref = float(daily_row["pre_close"])
                    market = prev_close / ex_ref
                    if not _supported_ratio(market, rtol):
                        raise M3G1ExecutionFactError(
                            "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED"
                        )
                    market_error = abs(actual / market - 1.0)
                    if market_error > rtol:
                        raise M3G1ExecutionFactError(
                            "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED"
                        )
                    status = (
                        "MATCHED_EVENT_DECLARED_FORMULA"
                        if declared_error <= rtol
                        else "MATCHED_EVENT_MARKET_REFERENCE"
                    )
                    evidence_rows.append(
                        {
                            "symbol": symbol,
                            "previous_factor_date": previous_factor_date,
                            "effective_date": effective_date,
                            "previous_close_date": prev_close_date,
                            "previous_close": prev_close,
                            "ex_reference_price": ex_ref,
                            "daily_request_id": request_id,
                            "daily_stable_response_sha256": stable,
                            "event_count": len(events_sorted),
                            "event_ids_json": event_ids_json,
                            "event_ids_sha256": event_ids_digest,
                            "cash_per_share_gross": total_cash,
                            "stock_ratio": total_stock,
                            "rights_ratio": total_rights_ratio,
                            "rights_subscription_cash_per_share": total_rights_cash,
                            "declared_dividend_factor_ratio": declared,
                            "market_reference_factor_ratio": market,
                            "actual_factor_ratio": actual,
                            "market_reference_relative_error": market_error,
                            "declared_dividend_relative_error": declared_error,
                            "factor_ratio_rtol": rtol,
                            "status": status,
                            "source": _SOURCE,
                        }
                    )
                    continue

                # Missing daily: only FULL_DAY + declared within rtol is allowed.
                if (effective_date, symbol) not in full_day:
                    raise M3G1ExecutionFactError(
                        "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED"
                    )
                if declared_error > rtol:
                    raise M3G1ExecutionFactError(
                        "G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED"
                    )
                evidence_rows.append(
                    {
                        "symbol": symbol,
                        "previous_factor_date": previous_factor_date,
                        "effective_date": effective_date,
                        "previous_close_date": prev_close_date,
                        "previous_close": prev_close,
                        "ex_reference_price": None,
                        "daily_request_id": request_id,
                        "daily_stable_response_sha256": stable,
                        "event_count": len(events_sorted),
                        "event_ids_json": event_ids_json,
                        "event_ids_sha256": event_ids_digest,
                        "cash_per_share_gross": total_cash,
                        "stock_ratio": total_stock,
                        "rights_ratio": total_rights_ratio,
                        "rights_subscription_cash_per_share": total_rights_cash,
                        "declared_dividend_factor_ratio": declared,
                        "market_reference_factor_ratio": None,
                        "actual_factor_ratio": actual,
                        "market_reference_relative_error": None,
                        "declared_dividend_relative_error": declared_error,
                        "factor_ratio_rtol": rtol,
                        "status": "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE",
                        "source": _SOURCE,
                    }
                )

        expected_rows = sum(max(len(series) - 1, 0) for series in factors_by_symbol.values())
        if len(evidence_rows) != expected_rows:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        evidence = _empty_or_frame(evidence_rows, _RECON_OUT, _recon_schema())
        evidence = evidence.sort(["symbol", "effective_date", "source"])
        evidence = _validate_schema(
            evidence,
            CorporateActionReconciliationSchema,
            "G1_CORPORATE_ACTION_RECONCILIATION_INVALID",
        )
        digest = clean_table_content_sha256(
            table_name="corporate_action_reconciliation", frame=evidence
        )
        return CorporateActionReconciliationResult(
            evidence=evidence, evidence_sha256=digest
        )
    except M3G1ExecutionFactError:
        raise
    except (pl.exceptions.PolarsError, TypeError, ValueError, OSError) as exc:
        raise _sanitize(exc, "G1_CORPORATE_ACTION_FACTOR_INVALID") from None


def verify_corporate_action_reconciliation_result(
    *, result: CorporateActionReconciliationResult
) -> None:
    """Re-validate reconciliation Schema, formulas and digest."""
    try:
        if type(result) is not CorporateActionReconciliationResult:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        _verify_reconciliation_result_body(result)
    except M3G1ExecutionFactError:
        raise
    except Exception:
        raise M3G1ExecutionFactError(
            "G1_CORPORATE_ACTION_RECONCILIATION_INVALID"
        ) from None


def _verify_selection_result_body(result: CorporateActionSelectionResult) -> None:
    ledger = _validate_schema(
        result.ledger,
        CorporateActionLedgerSchema,
        "G1_CORPORATE_ACTION_RESULT_INVALID",
    )
    evidence = _validate_schema(
        result.selection_evidence,
        CorporateActionSelectionEvidenceSchema,
        "G1_CORPORATE_ACTION_RESULT_INVALID",
    )
    object.__setattr__(result, "ledger", ledger)
    object.__setattr__(result, "selection_evidence", evidence)
    if type(result.ledger_sha256) is not str or not _HEX64.fullmatch(
        result.ledger_sha256
    ):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
    if type(result.selection_evidence_sha256) is not str or not _HEX64.fullmatch(
        result.selection_evidence_sha256
    ):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
    ledger_sha = clean_table_content_sha256(
        table_name="corporate_action_ledger", frame=result.ledger
    )
    evidence_sha = clean_table_content_sha256(
        table_name="corporate_action_selection_evidence",
        frame=result.selection_evidence,
    )
    if (
        ledger_sha != result.ledger_sha256
        or evidence_sha != result.selection_evidence_sha256
    ):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
    _assert_ledger_evidence_closure(result.ledger, result.selection_evidence)


def _verify_reconciliation_result_body(
    result: CorporateActionReconciliationResult,
) -> None:
    evidence = _validate_schema(
        result.evidence,
        CorporateActionReconciliationSchema,
        "G1_CORPORATE_ACTION_RECONCILIATION_INVALID",
    )
    object.__setattr__(result, "evidence", evidence)
    if type(result.evidence_sha256) is not str or not _HEX64.fullmatch(
        result.evidence_sha256
    ):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    digest = clean_table_content_sha256(
        table_name="corporate_action_reconciliation", frame=result.evidence
    )
    if digest != result.evidence_sha256:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    for row in result.evidence.iter_rows(named=True):
        _assert_reconciliation_row_formulas(row)


def _assert_ledger_evidence_closure(
    ledger: pl.DataFrame, evidence: pl.DataFrame
) -> None:
    selected = evidence.filter(pl.col("selected"))
    if selected.height != ledger.height:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in evidence.iter_rows(named=True):
        by_event.setdefault(row["economic_event_key_sha256"], []).append(row)
    for rows in by_event.values():
        count = rows[0]["candidate_count"]
        if any(item["candidate_count"] != count for item in rows):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
        ranks = sorted(item["candidate_rank"] for item in rows)
        if ranks != list(range(1, count + 1)):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
        selected_rows = [item for item in rows if item["selected"]]
        if len(selected_rows) != 1 or selected_rows[0]["candidate_rank"] != 1:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
    # Join ledger↔selected by event_id identity (includes end_date). Matching on
    # ex_date/cash/stock/... alone collides when two economic events share those
    # fields but differ only in end_date.
    selected_by_event_id: dict[str, dict[str, Any]] = {}
    for row in selected.iter_rows(named=True):
        action_type = row["action_type"]
        if action_type == "DIVIDEND_DISTRIBUTION":
            expected_event = _event_id_sha256(
                row["symbol"],
                row["end_date"],
                row["record_date"],
                row["ex_date"],
                float(row["cash_per_share_gross"]),
                float(row["stock_ratio"]),
            )
        elif action_type == "RIGHTS":
            rights_price = row["rights_price"]
            if rights_price is None:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
            if (
                row["rights_actual_shares"] is None
                or row["rights_pre_shares"] is None
                or row["rights_post_shares"] is None
            ):
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
            expected_event = _rights_event_id_sha256(
                row["symbol"],
                row["vendor_record_id"],
                row["record_date"],
                row["ex_date"],
                float(rights_price),
                float(row["rights_ratio"]),
                float(row["rights_actual_shares"]),
                float(row["rights_pre_shares"]),
                float(row["rights_post_shares"]),
            )
        else:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
        if expected_event in selected_by_event_id:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
        selected_by_event_id[expected_event] = row
    ledger_ids = [row["event_id"] for row in ledger.iter_rows(named=True)]
    if len(ledger_ids) != len(set(ledger_ids)):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
    if set(ledger_ids) != set(selected_by_event_id):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")
    for row in ledger.iter_rows(named=True):
        match = selected_by_event_id[row["event_id"]]
        if (
            row["symbol"] != match["symbol"]
            or row["ex_date"] != match["ex_date"]
            or row["action_type"] != match["action_type"]
            or float(row["cash_per_share_gross"])
            != float(match["cash_per_share_gross"])
            or float(row["stock_ratio"]) != float(match["stock_ratio"])
            or _nullable_float_differs(row["rights_price"], match["rights_price"])
            or float(row["rights_ratio"]) != float(match["rights_ratio"])
            or _nullable_float_differs(
                row["rights_actual_shares"], match["rights_actual_shares"]
            )
            or _nullable_float_differs(
                row["rights_pre_shares"], match["rights_pre_shares"]
            )
            or _nullable_float_differs(
                row["rights_post_shares"], match["rights_post_shares"]
            )
            or row["record_date"] != match["record_date"]
            or row["pay_date"] != match["pay_date"]
            or row["stock_list_date"] != match["stock_list_date"]
            or row["vendor_record_id"] != match["vendor_record_id"]
        ):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RESULT_INVALID")


def _nullable_float_differs(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is not right
    return float(left) != float(right)


def _assert_reconciliation_row_formulas(row: dict[str, Any]) -> None:
    _assert_event_ids_identity(row)
    actual = float(row["actual_factor_ratio"])
    declared = float(row["declared_dividend_factor_ratio"])
    rtol = float(row["factor_ratio_rtol"])
    status = row["status"]
    if status == "NO_EVENT_STABLE_FACTOR":
        if declared != 1.0:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if abs(actual - 1.0) != float(row["declared_dividend_relative_error"]):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if abs(actual - 1.0) > rtol:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if int(row["event_count"]) != 0:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        return
    prev_close = row["previous_close"]
    cash = float(row["cash_per_share_gross"])
    stock = float(row["stock_ratio"])
    rights_ratio = float(row["rights_ratio"])
    rights_cash = float(row["rights_subscription_cash_per_share"])
    if prev_close is None:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    denominator = float(prev_close) - cash + rights_cash
    expected_declared = (
        float(prev_close) * (1.0 + stock + rights_ratio) / denominator
    )
    if expected_declared != declared:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    expected_declared_error = abs(actual / declared - 1.0)
    if expected_declared_error != float(row["declared_dividend_relative_error"]):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    if not _supported_ratio(actual, rtol):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    if declared <= 1.0:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    if status in {
        "MATCHED_EVENT_DECLARED_FORMULA",
        "MATCHED_EVENT_MARKET_REFERENCE",
    }:
        ex_ref = row["ex_reference_price"]
        market = row["market_reference_factor_ratio"]
        if ex_ref is None or market is None:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        expected_market = float(prev_close) / float(ex_ref)
        if expected_market != float(market):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if not _supported_ratio(float(market), rtol):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        expected_market_error = abs(actual / float(market) - 1.0)
        if expected_market_error != float(row["market_reference_relative_error"]):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if expected_market_error > rtol:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if status == "MATCHED_EVENT_DECLARED_FORMULA" and expected_declared_error > rtol:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if status == "MATCHED_EVENT_MARKET_REFERENCE" and expected_declared_error <= rtol:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    elif status == "MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE":
        if row["ex_reference_price"] is not None:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        if expected_declared_error > rtol:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    else:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")


def _assert_event_ids_identity(row: dict[str, Any]) -> None:
    try:
        parsed_ids = _parse_event_ids_json(row.get("event_ids_json"))
        if int(row["event_count"]) != len(parsed_ids):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        expected_hash = _sha256_json(
            ["m3-g1-corporate-action-event-set-v1", *parsed_ids]
        )
        if row.get("event_ids_sha256") != expected_hash:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    except M3G1ExecutionFactError:
        raise
    except Exception:
        raise M3G1ExecutionFactError(
            "G1_CORPORATE_ACTION_RECONCILIATION_INVALID"
        ) from None


def _event_ids_json(event_ids: Sequence[str]) -> str:
    unique_sorted = sorted(set(event_ids))
    return _canonical_json(unique_sorted)


def _parse_event_ids_json(value: object) -> list[str]:
    if type(value) is not str:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise M3G1ExecutionFactError(
            "G1_CORPORATE_ACTION_RECONCILIATION_INVALID"
        ) from None
    if type(parsed) is not list:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    ids: list[str] = []
    for item in parsed:
        if type(item) is not str or not _HEX64.fullmatch(item):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
        ids.append(item)
    if len(ids) != len(set(ids)):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    if ids != sorted(ids):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    if _canonical_json(ids) != value:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_RECONCILIATION_INVALID")
    return ids


def _event_set_sha256(event_ids: list[str]) -> str:
    return _sha256_json(
        ["m3-g1-corporate-action-event-set-v1", *sorted(set(event_ids))]
    )


def _fold_dividend_cross_end_exact_duplicates(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fold 实施 rows that match on all formal fields except ``end_date``.

    Canonical ``end_date`` is the max within each exact cluster. ``raw_row_count``
    is the total number of original rows folded into the cluster. Each wrapper
    carries ``exact_identity`` so later candidate folding cannot wash away
    provenance distinctions after ``end_date`` is rewritten.
    """
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        identity = _dividend_cross_end_exact_identity(row)
        existing = buckets.get(identity)
        if existing is None:
            buckets[identity] = {
                "row": dict(row),
                "raw_row_count": 1,
                "exact_identity": identity,
            }
            continue
        existing["raw_row_count"] += 1
        if row["end_date"] > existing["row"]["end_date"]:
            existing["row"]["end_date"] = row["end_date"]
    return sorted(
        buckets.values(),
        key=lambda item: (
            item["row"]["symbol"],
            item["row"]["end_date"],
            item["row"]["record_date"],
            item["row"]["ex_date"],
            item["row"]["imp_ann_date"] is not None,
            item["row"]["imp_ann_date"]
            if item["row"]["imp_ann_date"] is not None
            else _DATE_MIN,
            item["row"]["ann_date"] is not None,
            item["row"]["ann_date"]
            if item["row"]["ann_date"] is not None
            else _DATE_MIN,
            _norm_float(item["row"]["cash"]),
            _norm_float(item["row"]["stock"]),
            item["row"]["pay_date"] is not None,
            item["row"]["pay_date"]
            if item["row"]["pay_date"] is not None
            else _DATE_MIN,
            item["row"]["stock_list_date"] is not None,
            item["row"]["stock_list_date"]
            if item["row"]["stock_list_date"] is not None
            else _DATE_MIN,
            item["raw_row_count"],
        ),
    )


def _dividend_cross_end_exact_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    """Identity for cross-``end_date`` exact fold: all formal fields except end_date."""
    return (
        row["symbol"],
        row["ann_date"],
        row["div_proc"],
        row["stk_div_raw"],
        row["stk_bo_rate"],
        row["stk_co_rate"],
        row["cash_div"],
        row["cash_div_tax_raw"],
        row["record_date"],
        row["ex_date"],
        row["pay_date"],
        row["stock_list_date"],
        row["imp_ann_date"],
        row["base_date"],
        row["base_share"],
    )


def _fold_identical_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fold candidates only when rank, decision, and exact identity all match.

    Each item is ``{row, raw_row_count, exact_identity}``. Same version rank with
    differing decision fields or differing exact identity is fail-closed as
    ``G1_CORPORATE_ACTION_VERSION_CONFLICT``.
    """
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for item in candidates:
        row = item["row"]
        count = int(item["raw_row_count"])
        decision = _decision_fields(row)
        rank_key = _version_rank_key(row)
        exact_identity = item["exact_identity"]
        fold_key = rank_key + decision + (exact_identity,)
        existing = buckets.get(fold_key)
        if existing is None:
            for other_key in buckets:
                if other_key[:4] == rank_key and other_key != fold_key:
                    raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_VERSION_CONFLICT")
            buckets[fold_key] = {
                "row": row,
                "raw_row_count": count,
                "exact_identity": exact_identity,
            }
            order.append(fold_key)
        else:
            existing["raw_row_count"] += count
    return [buckets[key] for key in order]


def _decision_fields(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _norm_float(row["cash"]),
        _norm_float(row["stock"]),
        row["pay_date"],
        row["stock_list_date"],
    )


def _version_rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    imp = row["imp_ann_date"]
    ann = row["ann_date"]
    return (
        imp is not None,
        imp if imp is not None else _DATE_MIN,
        ann is not None,
        ann if ann is not None else _DATE_MIN,
    )


def _economic_event_key_sha256(
    symbol: str, end_date: dt.date, record_date: dt.date, ex_date: dt.date
) -> str:
    return _sha256_json(
        [
            "m3-g1-corporate-action-key-v1",
            symbol,
            end_date.isoformat(),
            record_date.isoformat(),
            ex_date.isoformat(),
        ]
    )


def _candidate_id_sha256(
    event_key: str,
    imp_ann_date: dt.date | None,
    ann_date: dt.date | None,
    cash: float,
    stock: float,
    pay_date: dt.date | None,
    stock_list_date: dt.date | None,
) -> str:
    return _sha256_json(
        [
            "m3-g1-corporate-action-candidate-v1",
            event_key,
            None if imp_ann_date is None else imp_ann_date.isoformat(),
            None if ann_date is None else ann_date.isoformat(),
            _float_token(cash),
            _float_token(stock),
            None if pay_date is None else pay_date.isoformat(),
            None if stock_list_date is None else stock_list_date.isoformat(),
        ]
    )


def _event_id_sha256(
    symbol: str,
    end_date: dt.date,
    record_date: dt.date,
    ex_date: dt.date,
    cash: float,
    stock: float,
) -> str:
    return _sha256_json(
        [
            "m3-g1-corporate-action-event-v1",
            symbol,
            end_date.isoformat(),
            record_date.isoformat(),
            ex_date.isoformat(),
            _float_token(cash),
            _float_token(stock),
        ]
    )


def _rights_economic_event_key_sha256(
    symbol: str, record_date: dt.date, ex_date: dt.date
) -> str:
    return _sha256_json(
        [
            "m3-g1-corporate-action-rights-key-v1",
            symbol,
            record_date.isoformat(),
            ex_date.isoformat(),
        ]
    )


def _rights_candidate_id_sha256(
    event_key: str,
    subid: str,
    rights_price: float,
    rights_ratio: float,
    rights_actual_shares: float,
    rights_pre_shares: float,
    rights_post_shares: float,
) -> str:
    return _sha256_json(
        [
            "m3-g1-corporate-action-rights-candidate-v2",
            event_key,
            subid,
            _float_token(rights_price),
            _float_token(rights_ratio),
            _float_token(rights_actual_shares),
            _float_token(rights_pre_shares),
            _float_token(rights_post_shares),
        ]
    )


def _rights_event_id_sha256(
    symbol: str,
    subid: str,
    record_date: dt.date,
    ex_date: dt.date,
    rights_price: float,
    rights_ratio: float,
    rights_actual_shares: float,
    rights_pre_shares: float,
    rights_post_shares: float,
) -> str:
    return _sha256_json(
        [
            "m3-g1-corporate-action-rights-event-v2",
            "RIGHTS",
            symbol,
            subid,
            record_date.isoformat(),
            ex_date.isoformat(),
            _float_token(rights_price),
            _float_token(rights_ratio),
            _float_token(rights_actual_shares),
            _float_token(rights_pre_shares),
            _float_token(rights_post_shares),
        ]
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _float_token(value: float) -> str:
    normalized = 0.0 if value == 0.0 else float(value)
    if not math.isfinite(normalized):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
    return format(normalized, ".17g")


def _norm_float(value: float) -> float:
    return 0.0 if value == 0.0 else float(value)


def _consume_verified(response: object) -> VerifiedRawResponse:
    if type(response) is not VerifiedRawResponse:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_RESPONSE_INVALID")
    try:
        return VerifiedRawResponse(
            response.spec,
            response.receipt,
            response.receipt_sha256,
            response.frame,
        )
    except Exception:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_RESPONSE_INVALID") from None


def _consume_cninfo_verified(response: object) -> VerifiedCninfoRawResponse:
    if type(response) is not VerifiedCninfoRawResponse:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_RESPONSE_INVALID")
    try:
        return VerifiedCninfoRawResponse(
            response.spec,
            response.receipt,
            response.receipt_sha256,
            response.frame,
            response.resultcode,
            response.count,
            response.total,
        )
    except Exception:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_RESPONSE_INVALID") from None


def _build_cninfo_symbol_map(symbols: object) -> dict[str, str]:
    if (
        not isinstance(symbols, Sequence)
        or type(symbols) is str
        or not symbols
    ):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
    mapping: dict[str, str] = {}
    for symbol in symbols:
        if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
        code = symbol[:6]
        existing = mapping.get(code)
        if existing is not None and existing != symbol:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
        mapping[code] = symbol
    return mapping


def _require_cninfo_subid(value: object) -> str:
    if type(value) is str and value:
        return value
    if type(value) is int:
        return str(value)
    raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")


def _consume_history(history: object, *, code: str) -> HistoryWindow:
    if type(history) is not HistoryWindow:
        raise M3G1ExecutionFactError(code)
    try:
        return HistoryWindow(history.start, history.end)
    except Exception:
        raise M3G1ExecutionFactError(code) from None


def _prepare(
    response: VerifiedRawResponse, *, endpoint: str, allow_empty: bool
) -> pl.DataFrame:
    if response.spec.endpoint != endpoint or response.receipt.endpoint != endpoint:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_ENDPOINT_MISMATCH")
    expected = tuple(TUSHARE_FIELDS[endpoint].split(","))
    if tuple(response.frame.columns) != expected:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_COLUMNS_INVALID")
    if tuple(response.receipt.columns) != expected:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_COLUMNS_INVALID")
    params = dict(response.spec.parameters)
    if params.get("fields") != TUSHARE_FIELDS[endpoint]:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_COLUMNS_INVALID")
    if response.frame.is_empty() and not allow_empty:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_EMPTY")
    return response.frame


def _require_param(response: VerifiedRawResponse, key: str) -> str:
    value = dict(response.spec.parameters).get(key)
    if type(value) is not str or not value:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH")
    return value


def _request_range(response: VerifiedRawResponse) -> tuple[dt.date, dt.date]:
    params = dict(response.spec.parameters)
    try:
        start = _parse_request_date(params["start_date"])
        end = _parse_request_date(params["end_date"])
    except (KeyError, TypeError, ValueError):
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH") from None
    if start > end:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH")
    return start, end


def _parse_request_date(value: str) -> dt.date:
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise ValueError("bad date")
    return dt.datetime.strptime(value, "%Y%m%d").date()


def _parse_trade_date(value: object, *, start: dt.date, end: dt.date) -> dt.date:
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
    try:
        parsed = dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID") from None
    if parsed < start or parsed > end:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH")
    return parsed


def _parse_optional_date8(
    value: object, *, allow_null: bool, required: bool = False
) -> dt.date | None:
    if value is None:
        if required or not allow_null:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
        return None
    if type(value) is not str or not _DATE8.fullmatch(value):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID") from None


def _parse_cninfo_iso_date(value: object) -> dt.date:
    """Parse a CNINFO required date: exact ``YYYY-MM-DD`` calendar date only.

    Source-specific contract for CNINFO allotment rows. Rejects ``YYYYMMDD``,
    timestamps, whitespace padding, alternate separators, empty strings, nulls,
    and non-strings. Fail-closed as ``G1_CORPORATE_ACTION_EVENT_INVALID``.
    """
    if type(value) is not str or not _DATE_ISO.fullmatch(value):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID") from None


def _require_a_share(value: object, *, expected: str | None) -> str:
    if type(value) is not str or not _A_SHARE.fullmatch(value):
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
    if expected is not None and value != expected:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_REQUEST_SCOPE_MISMATCH")
    return value


def _parse_strict_scalar(value: object, *, allow_null: bool) -> float | None:
    if value is None:
        if allow_null:
            return None
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
    if type(value) is bool:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
    if type(value) is int:
        number = float(value)
    elif type(value) is float:
        number = value
    elif type(value) is str:
        if not value or not _DECIMAL.fullmatch(value):
            raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
        try:
            number = float(Decimal(value))
        except (InvalidOperation, ValueError):
            raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID") from None
    else:
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
    if not math.isfinite(number):
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_VALUE_INVALID")
    return 0.0 if number == 0.0 else number


def _parse_non_negative_number(value: object) -> float:
    number = _parse_strict_scalar(value, allow_null=False)
    assert number is not None
    if number < 0:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_EVENT_INVALID")
    return number


def _parse_dividend_leg_amount(value: object) -> float:
    """Normalize an unused cash/stock leg null to 0.0; otherwise strict non-negative.

    Vendor rows may omit the unused leg as null while other implementations use
    explicit 0.0. Both legs normalizing to 0.0 still fail closed upstream.
    """
    if value is None:
        return 0.0
    return _parse_non_negative_number(value)


def _reject_duplicate(frame: pl.DataFrame, keys: list[str]) -> None:
    if frame.is_empty():
        return
    dup = frame.group_by(keys).len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise M3G1ExecutionFactError("G1_EXECUTION_FACT_DUPLICATE_KEY")


def _validate_schema(frame: pl.DataFrame, schema: Any, code: str) -> pl.DataFrame:
    try:
        return schema.validate(frame)
    except Exception as exc:
        raise _sanitize(exc, code) from None


def _sanitize(exc: BaseException, code: str) -> M3G1ExecutionFactError:
    _ = exc
    return M3G1ExecutionFactError(code)


def _validate_eligible_keys(eligible_keys: pl.DataFrame) -> pl.DataFrame:
    if not isinstance(eligible_keys, pl.DataFrame):
        raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
    if tuple(eligible_keys.columns) != ("as_of", "symbol"):
        raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
    if eligible_keys.is_empty():
        raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
    if eligible_keys.dtypes != [pl.Date, pl.Utf8]:
        # Allow coercion via unique check path after cast attempt fails closed.
        try:
            eligible_keys = eligible_keys.select(
                pl.col("as_of").cast(pl.Date),
                pl.col("symbol").cast(pl.Utf8),
            )
        except Exception:
            raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID") from None
    if eligible_keys.height != eligible_keys.unique().height:
        raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
    for symbol in eligible_keys.get_column("symbol").to_list():
        if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
            raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
    return eligible_keys


def _prepare_history_calendar(
    calendar: pl.DataFrame, history: HistoryWindow, *, code: str
) -> tuple[list[dt.date], dict[dt.date, bool]]:
    by_market: dict[str, dict[dt.date, bool]] = {"SH": {}, "SZ": {}}
    for market, day, is_open in calendar.select("market", "date", "is_open").iter_rows():
        if market not in by_market:
            continue
        if day in by_market[market]:
            raise M3G1ExecutionFactError(code)
        by_market[market][day] = bool(is_open)
    cursor = history.start
    while cursor <= history.end:
        if cursor not in by_market["SH"] or cursor not in by_market["SZ"]:
            raise M3G1ExecutionFactError(code)
        if by_market["SH"][cursor] != by_market["SZ"][cursor]:
            raise M3G1ExecutionFactError(code)
        cursor += dt.timedelta(days=1)
    # Eligible as_of may need next session at/after history end; keep all SH opens.
    all_sh = sorted(day for day, is_open in by_market["SH"].items() if is_open)
    natural = {
        day: by_market["SH"][day]
        for day in sorted(by_market["SH"])
        if history.start <= day <= history.end
    }
    return all_sh, natural


def _instrument_lifecycle(
    instruments: pl.DataFrame,
) -> dict[str, tuple[dt.date, dt.date | None]]:
    mapping: dict[str, tuple[dt.date, dt.date | None]] = {}
    for row in instruments.iter_rows(named=True):
        symbol = row["symbol"]
        if symbol in mapping:
            raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
        suffix = symbol.rsplit(".", 1)[-1]
        if suffix != row["market"] or row["market"] not in {"SH", "SZ"}:
            raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")
        mapping[symbol] = (row["list_date"], row["delist_date"])
    return mapping


def _next_session(day: dt.date, sessions: Sequence[dt.date]) -> dt.date:
    for session in sessions:
        if session > day:
            return session
    raise M3G1ExecutionFactError("G1_PRICE_LIMIT_COVERAGE_INVALID")


def _last_session_on_or_before(
    day: dt.date, sessions: Sequence[dt.date]
) -> dt.date | None:
    previous = None
    for session in sessions:
        if session > day:
            break
        previous = session
    return previous


def _validate_rtol(value: object) -> float:
    if type(value) is bool or type(value) is not float:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
    if not math.isfinite(value) or value < 0.0 or value > 0.01:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
    return value


def _supported_ratio(value: float, rtol: float) -> bool:
    """Event-branch ratio support: strictly above 1, or within 1±rtol."""
    return value > 1.0 or abs(value - 1.0) <= rtol


def _consume_daily_responses(
    daily_responses: Sequence[VerifiedRawResponse],
    *,
    symbols: set[str],
    history: HistoryWindow,
) -> dict[str, VerifiedRawResponse]:
    if not isinstance(daily_responses, Sequence):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
    seen: dict[str, VerifiedRawResponse] = {}
    for response in daily_responses:
        verified = _consume_verified(response)
        frame = _prepare(verified, endpoint="daily", allow_empty=True)
        start, end = _request_range(verified)
        if start != history.start or end != history.end:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
        ts_code = _require_param(verified, "ts_code")
        if ts_code not in symbols:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
        if ts_code in seen:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
        for raw in frame.iter_rows(named=True):
            _require_a_share(raw.get("ts_code"), expected=ts_code)
        seen[ts_code] = verified
    if set(seen) != symbols:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
    return seen


def _project_daily_frames(
    daily_by_symbol: dict[str, VerifiedRawResponse],
) -> dict[str, dict[dt.date, dict[str, float]]]:
    projected: dict[str, dict[dt.date, dict[str, float]]] = {}
    for symbol, verified in daily_by_symbol.items():
        start, end = _request_range(verified)
        rows: dict[dt.date, dict[str, float]] = {}
        for raw in verified.frame.iter_rows(named=True):
            trade_date = _parse_trade_date(raw.get("trade_date"), start=start, end=end)
            close = _parse_strict_scalar(raw.get("close"), allow_null=False)
            pre_close = _parse_strict_scalar(raw.get("pre_close"), allow_null=False)
            assert close is not None and pre_close is not None
            if close <= 0 or pre_close <= 0:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
            if trade_date in rows:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
            rows[trade_date] = {"close": close, "pre_close": pre_close}
        projected[symbol] = rows
    return projected


def _assert_daily_matches_bars(
    daily_proj: dict[str, dict[dt.date, dict[str, float]]],
    bars: pl.DataFrame,
) -> None:
    bar_keys: dict[tuple[str, dt.date], float] = {}
    for row in bars.iter_rows(named=True):
        bar_keys[(row["symbol"], row["trade_date"])] = float(row["close"])
    daily_keys: dict[tuple[str, dt.date], float] = {}
    for symbol, rows in daily_proj.items():
        for day, values in rows.items():
            daily_keys[(symbol, day)] = values["close"]
    if set(bar_keys) != set(daily_keys):
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
    for key, close in bar_keys.items():
        if daily_keys[key] != close:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")


def _full_day_keys(suspensions: pl.DataFrame) -> set[tuple[dt.date, str]]:
    full_day: set[tuple[dt.date, str]] = set()
    seen: set[tuple[dt.date, str]] = set()
    for row in suspensions.iter_rows(named=True):
        if row["source"] != _SOURCE:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
        key = (row["trade_date"], row["symbol"])
        if key in seen:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
        seen.add(key)
        if row["suspension_scope"] == "FULL_DAY":
            full_day.add(key)
    return full_day


def _adjacent_factor_ratio(
    series: list[tuple[dt.date, float]], effective_date: dt.date
) -> float:
    previous: float | None = None
    for day, factor in series:
        if day == effective_date:
            if previous is None:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")
            return factor / previous
        previous = factor
    raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_INVALID")


def _event_cash_stock_rights_totals(
    events_sorted: Sequence[Mapping[str, Any]],
) -> tuple[float, float, float, float]:
    total_cash = math.fsum(float(item["cash_per_share_gross"]) for item in events_sorted)
    total_stock = math.fsum(float(item["stock_ratio"]) for item in events_sorted)
    total_rights_ratio = math.fsum(float(item["rights_ratio"]) for item in events_sorted)
    total_rights_cash = math.fsum(
        float(item["rights_price"]) * float(item["rights_ratio"])
        for item in events_sorted
        if item["action_type"] == "RIGHTS"
    )
    return total_cash, total_stock, total_rights_ratio, total_rights_cash


def _declared_factor_ratio(
    *,
    prev_close: float,
    total_cash: float,
    total_stock: float,
    total_rights_ratio: float,
    total_rights_cash: float,
) -> float | None:
    denominator = prev_close - total_cash + total_rights_cash
    if denominator <= 0:
        return None
    declared = prev_close * (1.0 + total_stock + total_rights_ratio) / denominator
    if declared <= 1.0:
        return None
    return declared


def _eligible_for_suspension_resume_delay(
    *,
    symbol: str,
    ex_date: dt.date,
    events: Sequence[Mapping[str, Any]],
    full_day: set[tuple[dt.date, str]],
    daily_rows: Mapping[dt.date, Mapping[str, float]],
    factor_series: list[tuple[dt.date, float]],
    bar_series: list[tuple[dt.date, float]],
    rtol: float,
) -> bool:
    """Strict delay gate: FULL_DAY + no daily + stable factor + declared unexplained."""
    if (ex_date, symbol) not in full_day:
        return False
    if ex_date in daily_rows:
        return False
    actual = _adjacent_factor_ratio(factor_series, ex_date)
    if abs(actual - 1.0) > rtol:
        return False
    events_sorted = sorted(events, key=lambda item: item["event_id"])
    total_cash, total_stock, total_rights_ratio, total_rights_cash = (
        _event_cash_stock_rights_totals(events_sorted)
    )
    _, prev_close = _previous_close(bar_series, ex_date)
    declared = _declared_factor_ratio(
        prev_close=prev_close,
        total_cash=total_cash,
        total_stock=total_stock,
        total_rights_ratio=total_rights_ratio,
        total_rights_cash=total_rights_cash,
    )
    if declared is None:
        return True
    return abs(actual / declared - 1.0) > rtol


def _resolve_suspension_resume_date(
    *,
    symbol: str,
    ex_date: dt.date,
    full_day: set[tuple[dt.date, str]],
    factor_dates: set[dt.date],
    daily_rows: Mapping[dt.date, Mapping[str, float]],
    bar_dates: set[dt.date],
    history: HistoryWindow,
    sh_sessions: Sequence[dt.date],
) -> dt.date:
    """First non-FULL_DAY SH session after a continuous FULL_DAY halt, or fail closed."""
    if ex_date not in factor_dates:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
    history_sessions = [
        day
        for day in sh_sessions
        if history.start <= day <= history.end and day >= ex_date
    ]
    if not history_sessions or history_sessions[0] != ex_date:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
    for day in history_sessions:
        if day == ex_date:
            continue
        if (day, symbol) in full_day:
            if day not in factor_dates:
                raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
            continue
        if day not in factor_dates or day not in bar_dates or day not in daily_rows:
            raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
        return day
    raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")


def _assign_events_with_suspension_resume_delay(
    *,
    events_by_symbol_date: Mapping[tuple[str, dt.date], list[dict[str, Any]]],
    full_day: set[tuple[dt.date, str]],
    daily_proj: Mapping[str, Mapping[dt.date, Mapping[str, float]]],
    factors_by_symbol: Mapping[str, list[tuple[dt.date, float]]],
    bars_by_symbol: Mapping[str, list[tuple[dt.date, float]]],
    history: HistoryWindow,
    sh_sessions: Sequence[dt.date],
    rtol: float,
) -> dict[tuple[str, dt.date], list[dict[str, Any]]]:
    assigned: dict[tuple[str, dt.date], list[dict[str, Any]]] = {}
    for symbol, ex_date in sorted(events_by_symbol_date):
        events = events_by_symbol_date[(symbol, ex_date)]
        daily_rows = daily_proj[symbol]
        factor_series = factors_by_symbol[symbol]
        bar_series = bars_by_symbol[symbol]
        if _eligible_for_suspension_resume_delay(
            symbol=symbol,
            ex_date=ex_date,
            events=events,
            full_day=full_day,
            daily_rows=daily_rows,
            factor_series=factor_series,
            bar_series=bar_series,
            rtol=rtol,
        ):
            target = _resolve_suspension_resume_date(
                symbol=symbol,
                ex_date=ex_date,
                full_day=full_day,
                factor_dates={day for day, _ in factor_series},
                daily_rows=daily_rows,
                bar_dates={day for day, _ in bar_series},
                history=history,
                sh_sessions=sh_sessions,
            )
            assigned.setdefault((symbol, target), []).extend(events)
        else:
            assigned.setdefault((symbol, ex_date), []).extend(events)
    return assigned


_EMPTY_EVENT_IDS_JSON = "[]"
_EMPTY_EVENT_IDS_SHA256: str | None = None


def _no_event_evidence_row(
    *,
    symbol: str,
    previous_factor_date: dt.date,
    effective_date: dt.date,
    actual: float,
    request_id: str,
    stable: str,
    rtol: float,
) -> dict[str, Any]:
    # B2C §9.2: only abs(actual-1)<=rtol may emit NO_EVENT_STABLE_FACTOR.
    if abs(actual - 1.0) > rtol:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
    global _EMPTY_EVENT_IDS_SHA256
    if _EMPTY_EVENT_IDS_SHA256 is None:
        _EMPTY_EVENT_IDS_SHA256 = _event_set_sha256([])
    return {
        "symbol": symbol,
        "previous_factor_date": previous_factor_date,
        "effective_date": effective_date,
        "previous_close_date": None,
        "previous_close": None,
        "ex_reference_price": None,
        "daily_request_id": request_id,
        "daily_stable_response_sha256": stable,
        "event_count": 0,
        "event_ids_json": _EMPTY_EVENT_IDS_JSON,
        "event_ids_sha256": _EMPTY_EVENT_IDS_SHA256,
        "cash_per_share_gross": 0.0,
        "stock_ratio": 0.0,
        "rights_ratio": 0.0,
        "rights_subscription_cash_per_share": 0.0,
        "declared_dividend_factor_ratio": 1.0,
        "market_reference_factor_ratio": None,
        "actual_factor_ratio": actual,
        "market_reference_relative_error": None,
        "declared_dividend_relative_error": abs(actual - 1.0),
        "factor_ratio_rtol": rtol,
        "status": "NO_EVENT_STABLE_FACTOR",
        "source": _SOURCE,
    }


def _previous_close(
    bar_series: list[tuple[dt.date, float]], ex_date: dt.date
) -> tuple[dt.date, float]:
    previous: tuple[dt.date, float] | None = None
    for day, close in bar_series:
        if day >= ex_date:
            break
        previous = (day, close)
    if previous is None:
        raise M3G1ExecutionFactError("G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED")
    return previous


def _ledger_schema() -> dict[str, Any]:
    return {
        "event_id": pl.Utf8,
        "symbol": pl.Utf8,
        "ex_date": pl.Date,
        "action_type": pl.Utf8,
        "cash_per_share_gross": pl.Float64,
        "stock_ratio": pl.Float64,
        "rights_price": pl.Float64,
        "rights_ratio": pl.Float64,
        "rights_actual_shares": pl.Float64,
        "rights_pre_shares": pl.Float64,
        "rights_post_shares": pl.Float64,
        "record_date": pl.Date,
        "pay_date": pl.Date,
        "stock_list_date": pl.Date,
        "vendor_record_id": pl.Utf8,
        "source": pl.Utf8,
        "source_snapshot_id": pl.Utf8,
    }


def _evidence_schema() -> dict[str, Any]:
    return {
        "economic_event_key_sha256": pl.Utf8,
        "candidate_id": pl.Utf8,
        "symbol": pl.Utf8,
        "action_type": pl.Utf8,
        "end_date": pl.Date,
        "record_date": pl.Date,
        "ex_date": pl.Date,
        "imp_ann_date": pl.Date,
        "ann_date": pl.Date,
        "cash_per_share_gross": pl.Float64,
        "stock_ratio": pl.Float64,
        "rights_price": pl.Float64,
        "rights_ratio": pl.Float64,
        "rights_actual_shares": pl.Float64,
        "rights_pre_shares": pl.Float64,
        "rights_post_shares": pl.Float64,
        "pay_date": pl.Date,
        "stock_list_date": pl.Date,
        "vendor_record_id": pl.Utf8,
        "candidate_rank": pl.Int64,
        "candidate_count": pl.Int64,
        "raw_row_count": pl.Int64,
        "selected": pl.Boolean,
        "selection_reason": pl.Utf8,
        "source": pl.Utf8,
        "source_request_id": pl.Utf8,
        "source_snapshot_id": pl.Utf8,
    }


def _recon_schema() -> dict[str, Any]:
    return {
        "symbol": pl.Utf8,
        "previous_factor_date": pl.Date,
        "effective_date": pl.Date,
        "previous_close_date": pl.Date,
        "previous_close": pl.Float64,
        "ex_reference_price": pl.Float64,
        "daily_request_id": pl.Utf8,
        "daily_stable_response_sha256": pl.Utf8,
        "event_count": pl.Int64,
        "event_ids_json": pl.Utf8,
        "event_ids_sha256": pl.Utf8,
        "cash_per_share_gross": pl.Float64,
        "stock_ratio": pl.Float64,
        "rights_ratio": pl.Float64,
        "rights_subscription_cash_per_share": pl.Float64,
        "declared_dividend_factor_ratio": pl.Float64,
        "market_reference_factor_ratio": pl.Float64,
        "actual_factor_ratio": pl.Float64,
        "market_reference_relative_error": pl.Float64,
        "declared_dividend_relative_error": pl.Float64,
        "factor_ratio_rtol": pl.Float64,
        "status": pl.Utf8,
        "source": pl.Utf8,
    }


def _empty_or_frame(
    rows: list[dict[str, Any]], columns: tuple[str, ...], schema: dict[str, Any]
) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=schema).select(list(columns))
    return pl.DataFrame(rows, schema=schema).select(list(columns))
