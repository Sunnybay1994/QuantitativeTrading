"""M3 G1-P4A: primary candidate rebuild and global primary-source audit."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal

import polars as pl

from quant.data import index_membership as index_membership
from quant.data import m3_execution_facts as execution_facts
from quant.data import m3_mappers as mappers
from quant.data.connectors.cninfo import (
    CNINFO_DIVIDEND_ENDPOINT,
    CNINFO_ENDPOINT,
    CNINFO_SHARE_CHANGE_ENDPOINT,
    CNINFO_SOURCE,
    CNINFO_STOCK_ALLOTMENT_FIELDS,
    CNINFO_STOCK_DIVIDEND_FIELDS,
    CNINFO_STOCK_SHARE_CHANGE_FIELDS,
)
from quant.data.m3_backfill import (
    G1RequestPlan,
    HistoryWindow,
    VerifiedCninfoRawResponse,
    VerifiedCninfoCorporateActionRawResponse,
    VerifiedRawResponse,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.domain import (
    AdjustmentFactorMatchSchema,
    AdjustmentFactorSchema,
    Bar1dSchema,
    BenchmarkBar1dSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    CorporateActionSelectionEvidenceSchema,
    IndexConstituentObservationSchema,
    InstrumentSchema,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TradeCalendarSchema,
    UniverseMembershipSchema,
)

G1_MEMBERSHIP_METHOD_VERSION = "tushare_monthly_observed_next_session_close_v1"
# Re-export frozen P3 version literals via module attribute access so importlib.reload
# of execution_facts in upstream tests cannot desync bound class/function identities.
G1_PRICE_LIMIT_METHOD_VERSION = execution_facts.G1_PRICE_LIMIT_METHOD_VERSION
G1_CORPORATE_ACTION_SELECTION_VERSION = (
    execution_facts.G1_CORPORATE_ACTION_SELECTION_VERSION
)
G1_CORPORATE_ACTION_RECONCILIATION_VERSION = (
    execution_facts.G1_CORPORATE_ACTION_RECONCILIATION_VERSION
)
_UNIVERSE: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"] = (
    "CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"
)
_EXPECTED_COUNT = 300
_SOURCE = "tushare"
_BENCHMARK = "510300.SH"
_BENCHMARK_MODE = "TRADEABLE_ETF_TOTAL_RETURN_PROXY"
_BENCHMARK_METHOD_VERSION = "tushare_510300_fund_daily_fund_adj_hfq_v1"
_BENCHMARK_DIVIDEND_RECONCILIATION_VERSION = "tushare_fund_div_implemented_cash_v1"
_MAPPER_VERSION = "m3-g1-tushare-mapper-v5"
_IDENTITY_SCHEMA = "m3-g1-primary-candidate-identity-v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")

_TABLE_NAMES = (
    "adjustment_factor",
    "adjustment_factor_match",
    "bar_1d",
    "benchmark_bar_1d",
    "corporate_action_ledger",
    "corporate_action_reconciliation",
    "corporate_action_selection_evidence",
    "eligible_keys",
    "index_constituent_observation",
    "instrument",
    "price_limit_1d",
    "suspension_1d",
    "trade_calendar",
    "universe_membership",
)

# table_name -> G1Candidate attribute name (bijection with _TABLE_NAMES).
_TABLE_ATTRS: dict[str, str] = {
    "adjustment_factor": "adjustment_factors",
    "adjustment_factor_match": "factor_match_evidence",
    "bar_1d": "bars",
    "benchmark_bar_1d": "benchmark_bars",
    "corporate_action_ledger": "corporate_actions",
    "corporate_action_reconciliation": "corporate_action_reconciliation",
    "corporate_action_selection_evidence": "corporate_action_selection_evidence",
    "eligible_keys": "eligible_keys",
    "index_constituent_observation": "observations",
    "instrument": "instruments",
    "price_limit_1d": "price_limits",
    "suspension_1d": "suspensions",
    "trade_calendar": "calendars",
    "universe_membership": "membership",
}

_TABLE_SCHEMAS: dict[str, Any] = {
    "adjustment_factor": AdjustmentFactorSchema,
    "adjustment_factor_match": AdjustmentFactorMatchSchema,
    "bar_1d": Bar1dSchema,
    "benchmark_bar_1d": BenchmarkBar1dSchema,
    "corporate_action_ledger": CorporateActionLedgerSchema,
    "corporate_action_reconciliation": CorporateActionReconciliationSchema,
    "corporate_action_selection_evidence": CorporateActionSelectionEvidenceSchema,
    "index_constituent_observation": IndexConstituentObservationSchema,
    "instrument": InstrumentSchema,
    "price_limit_1d": PriceLimit1dSchema,
    "suspension_1d": Suspension1dSchema,
    "trade_calendar": TradeCalendarSchema,
    "universe_membership": UniverseMembershipSchema,
}

_ISSUE_CODES = frozenset(
    {
        "REQUEST_PLAN_MISMATCH",
        "RECEIPT_INVALID",
        "SCHEMA_INVALID",
        "DUPLICATE_KEY",
        "UNKNOWN_INSTRUMENT",
        "MEMBERSHIP_MISSING_MONTH",
        "MEMBERSHIP_COUNT_MISMATCH",
        "MEMBERSHIP_WEIGHT_INVALID",
        "MEMBERSHIP_INTERVAL_OVERLAP",
        "CALENDAR_MISMATCH",
        "HISTORY_WINDOW_INCOMPLETE",
        "BAR_OR_SUSPENSION_MISSING",
        "BAR_FULL_SUSPENSION_CONFLICT",
        "PARTIAL_SUSPENSION_BAR_MISSING",
        "FACTOR_MISSING",
        "FACTOR_INVALID",
        "PRICE_LIMIT_MISSING",
        "PRICE_LIMIT_INVALID",
        "BENCHMARK_MISSING",
        "CORPORATE_ACTION_INVALID",
        "CORPORATE_ACTION_FACTOR_MISMATCH",
        "CROSS_SOURCE_INCOMPLETE",
        "CROSS_SOURCE_MISMATCH",
    }
)

_ERROR_CODES = frozenset(
    {
        "G1_CANDIDATE_INPUT_INVALID",
        "G1_CANDIDATE_PLAN_RESPONSE_MISMATCH",
        "G1_CANDIDATE_COMPONENT_INVALID",
        "G1_CANDIDATE_IDENTITY_MISMATCH",
    }
)

_MATCH_COLUMNS = (
    "symbol",
    "trade_date",
    "source",
    "adj_factor",
    "bar_request_id",
    "bar_stable_response_sha256",
    "factor_request_id",
    "factor_stable_response_sha256",
)


class M3G1CandidateError(ValueError):
    """Stable P4A boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown g1 candidate error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3G1CandidateError({self.code!r})"


@dataclass(frozen=True)
class G1QualityIssue:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str
    count: int
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.code not in _ISSUE_CODES:
            raise ValueError("G1QualityIssue code 非法")
        if self.severity not in {"ERROR", "WARNING"}:
            raise ValueError("G1QualityIssue severity 非法")
        if type(self.message) is not str or not self.message:
            raise ValueError("G1QualityIssue message 非法")
        if type(self.count) is not int or self.count < 1:
            raise ValueError("G1QualityIssue count 非法")
        if type(self.evidence) is not tuple or any(
            type(item) is not str for item in self.evidence
        ):
            raise ValueError("G1QualityIssue evidence 非法")
        if self.evidence != tuple(sorted(self.evidence)):
            raise ValueError("G1QualityIssue evidence 必须排序")


@dataclass(frozen=True)
class AdjustmentApplicationResult:
    bars: pl.DataFrame
    factor_match_evidence: pl.DataFrame

    def __post_init__(self) -> None:
        bars = _validate_schema(self.bars, Bar1dSchema, "G1_CANDIDATE_COMPONENT_INVALID")
        evidence = _validate_schema(
            self.factor_match_evidence,
            AdjustmentFactorMatchSchema,
            "G1_CANDIDATE_COMPONENT_INVALID",
        )
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "factor_match_evidence", evidence)
        if bars.height != evidence.height:
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")


@dataclass(frozen=True)
class G1BuildSpec:
    config_version: str
    g1_config_sha256: str
    mapper_version: str
    schema_version: str
    membership_method_version: str
    price_limit_method_version: str
    corporate_action_selection_version: str
    corporate_action_reconciliation_version: str
    benchmark_mode: str
    benchmark_method_version: str
    benchmark_dividend_reconciliation_version: str
    build_code_version: str
    dependency_fingerprint_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "config_version",
            "mapper_version",
            "schema_version",
            "build_code_version",
            "benchmark_mode",
            "benchmark_method_version",
            "benchmark_dividend_reconciliation_version",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError("G1BuildSpec 字符串字段非法")
        for name in ("g1_config_sha256", "dependency_fingerprint_sha256"):
            value = getattr(self, name)
            if type(value) is not str or not _HEX64.fullmatch(value):
                raise ValueError("G1BuildSpec digest 非法")
        if self.mapper_version != _MAPPER_VERSION:
            raise ValueError("mapper_version 非法")
        if self.benchmark_mode != _BENCHMARK_MODE:
            raise ValueError("benchmark_mode 非法")
        if self.benchmark_method_version != _BENCHMARK_METHOD_VERSION:
            raise ValueError("benchmark_method_version 非法")
        if (
            self.benchmark_dividend_reconciliation_version
            != _BENCHMARK_DIVIDEND_RECONCILIATION_VERSION
        ):
            raise ValueError("benchmark_dividend_reconciliation_version 非法")
        if self.membership_method_version != G1_MEMBERSHIP_METHOD_VERSION:
            raise ValueError("membership_method_version 非法")
        if self.price_limit_method_version != G1_PRICE_LIMIT_METHOD_VERSION:
            raise ValueError("price_limit_method_version 非法")
        if self.corporate_action_selection_version != G1_CORPORATE_ACTION_SELECTION_VERSION:
            raise ValueError("corporate_action_selection_version 非法")
        if (
            self.corporate_action_reconciliation_version
            != G1_CORPORATE_ACTION_RECONCILIATION_VERSION
        ):
            raise ValueError("corporate_action_reconciliation_version 非法")


@dataclass(frozen=True)
class G1ReceiptProjectionV1:
    source: Literal["tushare", "baostock", "cninfo"]
    request_id: str
    endpoint: str
    parameters_sha256: str
    stable_response_sha256: str
    row_count: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.source not in {"tushare", "baostock", "cninfo"}:
            raise ValueError("receipt projection source 非法")
        if type(self.request_id) is not str or not _HEX64.fullmatch(self.request_id):
            raise ValueError("receipt projection request_id 非法")
        if type(self.endpoint) is not str or not self.endpoint:
            raise ValueError("receipt projection endpoint 非法")
        if type(self.parameters_sha256) is not str or not _HEX64.fullmatch(
            self.parameters_sha256
        ):
            raise ValueError("receipt projection parameters_sha256 非法")
        if type(self.stable_response_sha256) is not str or not _HEX64.fullmatch(
            self.stable_response_sha256
        ):
            raise ValueError("receipt projection stable_response_sha256 非法")
        if type(self.row_count) is not int or self.row_count < 0:
            raise ValueError("receipt projection row_count 非法")
        if type(self.columns) is not tuple or any(
            type(item) is not str for item in self.columns
        ):
            raise ValueError("receipt projection columns 非法")
        if self.source == CNINFO_SOURCE and self.endpoint == CNINFO_ENDPOINT:
            if self.columns != CNINFO_STOCK_ALLOTMENT_FIELDS:
                raise ValueError("cninfo stock_allotment columns 必须精确绑定官方字段")
        if self.source == CNINFO_SOURCE and self.endpoint == CNINFO_DIVIDEND_ENDPOINT:
            if self.columns != CNINFO_STOCK_DIVIDEND_FIELDS:
                raise ValueError("cninfo stock_dividend columns 必须精确绑定官方字段")
        if self.source == CNINFO_SOURCE and self.endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
            if self.columns != CNINFO_STOCK_SHARE_CHANGE_FIELDS:
                raise ValueError("cninfo stock_share_change columns 必须精确绑定官方字段")


@dataclass(frozen=True)
class G1BuildInputs:
    build_spec: G1BuildSpec
    request_plan: G1RequestPlan
    responses: tuple[VerifiedRawResponse, ...]
    cninfo_responses: tuple[VerifiedCninfoRawResponse, ...]
    cninfo_dividend_responses: tuple[VerifiedCninfoCorporateActionRawResponse, ...]
    cninfo_share_change_responses: tuple[VerifiedCninfoCorporateActionRawResponse, ...]
    calendars: pl.DataFrame
    instruments: pl.DataFrame
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    signal_start: dt.date
    signal_end: dt.date
    history: HistoryWindow
    expected_constituent_count: int
    factor_ratio_rtol: float

    def __post_init__(self) -> None:
        try:
            build_spec = _consume_build_spec(self.build_spec)
            request_plan = _consume_request_plan(self.request_plan)
            history = _consume_history(self.history)
            responses = _consume_responses(self.responses)
            cninfo_responses = _consume_cninfo_responses(self.cninfo_responses)
            cninfo_dividend_responses = _consume_cninfo_corporate_action_responses(
                self.cninfo_dividend_responses
            )
            cninfo_share_change_responses = _consume_cninfo_corporate_action_responses(
                self.cninfo_share_change_responses
            )
            calendars = _validate_schema(
                self.calendars, TradeCalendarSchema, "G1_CANDIDATE_INPUT_INVALID"
            )
            instruments = _validate_schema(
                self.instruments, InstrumentSchema, "G1_CANDIDATE_INPUT_INVALID"
            )
            if self.universe != _UNIVERSE:
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            if type(self.signal_start) is not dt.date or type(self.signal_end) is not dt.date:
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            if self.signal_start > self.signal_end:
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            if not (
                history.start
                <= self.signal_start
                <= self.signal_end
                <= history.end
            ):
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            if (
                type(self.expected_constituent_count) is not int
                or self.expected_constituent_count != _EXPECTED_COUNT
            ):
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            rtol = _validate_rtol(self.factor_ratio_rtol)
            object.__setattr__(self, "build_spec", build_spec)
            object.__setattr__(self, "request_plan", request_plan)
            object.__setattr__(self, "responses", responses)
            object.__setattr__(self, "cninfo_responses", cninfo_responses)
            object.__setattr__(
                self, "cninfo_dividend_responses", cninfo_dividend_responses
            )
            object.__setattr__(
                self, "cninfo_share_change_responses", cninfo_share_change_responses
            )
            object.__setattr__(self, "calendars", calendars)
            object.__setattr__(self, "instruments", instruments)
            object.__setattr__(self, "history", history)
            object.__setattr__(self, "factor_ratio_rtol", rtol)
        except M3G1CandidateError:
            raise
        except Exception:
            raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID") from None


@dataclass(frozen=True)
class G1Candidate:
    build_spec: G1BuildSpec
    request_plan: G1RequestPlan
    signal_start: dt.date
    signal_end: dt.date
    history_start: dt.date
    history_end: dt.date
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    calendars: pl.DataFrame
    instruments: pl.DataFrame
    observations: pl.DataFrame
    membership: pl.DataFrame
    eligible_keys: pl.DataFrame
    bars: pl.DataFrame
    adjustment_factors: pl.DataFrame
    factor_match_evidence: pl.DataFrame
    benchmark_bars: pl.DataFrame
    suspensions: pl.DataFrame
    price_limits: pl.DataFrame
    corporate_actions: pl.DataFrame
    corporate_action_selection_evidence: pl.DataFrame
    corporate_action_reconciliation: pl.DataFrame
    table_content_digests: tuple[tuple[str, str], ...]
    price_limit_required_keys_sha256: str
    primary_candidate_key: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "build_spec", _consume_build_spec(self.build_spec))
            object.__setattr__(
                self, "request_plan", _consume_request_plan(self.request_plan)
            )
            if any(
                type(value) is not dt.date
                for value in (
                    self.signal_start,
                    self.signal_end,
                    self.history_start,
                    self.history_end,
                )
            ):
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            if not (
                self.history_start
                <= self.signal_start
                <= self.signal_end
                <= self.history_end
            ):
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            if type(self.input_receipts) is not tuple or not self.input_receipts:
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            rebuilt_receipts: list[G1ReceiptProjectionV1] = []
            for item in self.input_receipts:
                if type(item) is not G1ReceiptProjectionV1 or item.source not in {
                    "tushare",
                    "cninfo",
                }:
                    raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
                rebuilt_receipts.append(
                    G1ReceiptProjectionV1(
                        source=item.source,
                        request_id=item.request_id,
                        endpoint=item.endpoint,
                        parameters_sha256=item.parameters_sha256,
                        stable_response_sha256=item.stable_response_sha256,
                        row_count=item.row_count,
                        columns=item.columns,
                    )
                )
            ordered = tuple(
                sorted(
                    rebuilt_receipts,
                    key=lambda value: (value.source, value.endpoint, value.request_id),
                )
            )
            if tuple(rebuilt_receipts) != ordered:
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
            object.__setattr__(self, "input_receipts", ordered)
            _verify_candidate_identity_closure(self)
        except M3G1CandidateError:
            raise
        except Exception:
            raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID") from None


def _canonical_eligible_keys(frame: object) -> pl.DataFrame:
    if not isinstance(frame, pl.DataFrame) or list(frame.columns) != ["as_of", "symbol"]:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    try:
        for name in ("as_of", "symbol"):
            dtype = frame.schema[name]
            text = str(dtype)
            base = dtype.base_type() if hasattr(dtype, "base_type") else dtype
            if base in {pl.List, pl.Struct} or "List" in text or "Struct" in text:
                raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
        validated = frame.select(
            pl.col("as_of").cast(pl.Date),
            pl.col("symbol").cast(pl.Utf8),
        )
    except M3G1CandidateError:
        raise
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID") from None
    if validated.is_empty():
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    if validated.height != validated.select(["as_of", "symbol"]).unique().height:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    return validated.sort(["as_of", "symbol"])


def _recompute_required_keys_digest(
    *,
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    eligible_keys: pl.DataFrame,
    suspensions: pl.DataFrame,
    price_limits: pl.DataFrame,
    bars: pl.DataFrame,
    history_start: dt.date,
    history_end: dt.date,
) -> str:
    try:
        required = execution_facts.require_g1_price_limit_coverage(
            price_limits=price_limits,
            eligible_keys=eligible_keys,
            suspensions=suspensions,
            calendars=calendars,
            instruments=instruments,
            bars=bars,
            history=HistoryWindow(history_start, history_end),
        )
        return clean_table_content_sha256(
            table_name="price_limit_required_keys", frame=required
        )
    except M3G1CandidateError:
        raise
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH") from None


def _verify_candidate_identity_closure(candidate: G1Candidate) -> None:
    """Object-internal identity self-proof; no IO, no audit report, no BuildInputs."""
    try:
        _validate_digest_table(candidate.table_content_digests)
        if type(candidate.price_limit_required_keys_sha256) is not str or not _HEX64.fullmatch(
            candidate.price_limit_required_keys_sha256
        ):
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        if type(candidate.primary_candidate_key) is not str or not _HEX64.fullmatch(
            candidate.primary_candidate_key
        ):
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")

        for table_name in _TABLE_NAMES:
            attr = _TABLE_ATTRS[table_name]
            raw_frame = getattr(candidate, attr)
            if table_name == "eligible_keys":
                canonical = _canonical_eligible_keys(raw_frame)
            else:
                if not isinstance(raw_frame, pl.DataFrame):
                    raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
                canonical = _validate_schema(
                    raw_frame,
                    _TABLE_SCHEMAS[table_name],
                    "G1_CANDIDATE_INPUT_INVALID",
                )
            object.__setattr__(candidate, attr, canonical)

        recomputed = tuple(
            (
                table_name,
                clean_table_content_sha256(
                    table_name=table_name,
                    frame=getattr(candidate, _TABLE_ATTRS[table_name]),
                ),
            )
            for table_name in _TABLE_NAMES
        )
        if recomputed != candidate.table_content_digests:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")

        required_digest = _recompute_required_keys_digest(
            calendars=candidate.calendars,
            instruments=candidate.instruments,
            eligible_keys=candidate.eligible_keys,
            suspensions=candidate.suspensions,
            price_limits=candidate.price_limits,
            bars=candidate.bars,
            history_start=candidate.history_start,
            history_end=candidate.history_end,
        )
        if required_digest != candidate.price_limit_required_keys_sha256:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")

        expected_key = _primary_candidate_key(
            build_spec=candidate.build_spec,
            request_plan_sha256=candidate.request_plan.plan_sha256,
            signal_start=candidate.signal_start,
            signal_end=candidate.signal_end,
            history_start=candidate.history_start,
            history_end=candidate.history_end,
            input_receipts=candidate.input_receipts,
            table_content_digests=recomputed,
            price_limit_required_keys_sha256=required_digest,
        )
        if expected_key != candidate.primary_candidate_key:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
    except M3G1CandidateError:
        raise
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH") from None


@dataclass(frozen=True)
class G1PrimaryAuditResult:
    primary_candidate_key: str
    plan_sha256: str
    input_receipts: tuple[G1ReceiptProjectionV1, ...]
    table_content_digests: tuple[tuple[str, str], ...]
    issues: tuple[G1QualityIssue, ...]
    passed: bool

    def __post_init__(self) -> None:
        if type(self.primary_candidate_key) is not str or not _HEX64.fullmatch(
            self.primary_candidate_key
        ):
            raise ValueError("primary audit key 非法")
        if type(self.plan_sha256) is not str or not _HEX64.fullmatch(self.plan_sha256):
            raise ValueError("primary audit plan_sha256 非法")
        if type(self.input_receipts) is not tuple:
            raise ValueError("primary audit receipts 非法")
        _validate_digest_table(self.table_content_digests)
        if type(self.issues) is not tuple or any(
            type(item) is not G1QualityIssue for item in self.issues
        ):
            raise ValueError("primary audit issues 非法")
        ordered = tuple(
            sorted(
                self.issues,
                key=lambda item: (item.severity, item.code, item.message, item.evidence),
            )
        )
        if self.issues != ordered:
            raise ValueError("primary audit issues 必须排序")
        if type(self.passed) is not bool:
            raise ValueError("primary audit passed 必须是 bool")
        if self.passed is not (len(self.issues) == 0):
            raise ValueError("primary audit passed 与 issues 不一致")


def apply_adjustment_factors_strict(
    *,
    bars: pl.DataFrame,
    adjustment_factors: pl.DataFrame,
    daily_responses: Sequence[VerifiedRawResponse],
    factor_responses: Sequence[VerifiedRawResponse],
) -> AdjustmentApplicationResult:
    """Exact-join bars with factors and inject verified response lineage."""
    try:
        bar_frame = bars
        if not isinstance(bar_frame, pl.DataFrame):
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        if "adj_factor" in bar_frame.columns:
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        required = [
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "source",
        ]
        if list(bar_frame.columns) != required:
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        factor_frame = _validate_schema(
            adjustment_factors,
            AdjustmentFactorSchema,
            "G1_CANDIDATE_COMPONENT_INVALID",
        )
        daily_list = [_consume_verified(item) for item in daily_responses]
        factor_list = [_consume_verified(item) for item in factor_responses]
        if not daily_list or not factor_list:
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        for item in daily_list:
            if item.spec.endpoint != "daily":
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        for item in factor_list:
            if item.spec.endpoint != "adj_factor":
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")

        bar_lineage = _symbol_lineage(daily_list, date_param=True)
        factor_lineage = _symbol_lineage(factor_list, date_param=True)

        bar_keys: dict[tuple[str, dt.date, str], dict[str, Any]] = {}
        for row in bar_frame.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["trade_date"]
            source = row["source"]
            if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            if type(day) is not dt.date or source != _SOURCE:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            key = (symbol, day, source)
            if key in bar_keys:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            for field in ("open", "high", "low", "close", "volume", "amount"):
                value = row[field]
                if type(value) is not float or not math.isfinite(value) or value <= 0:
                    raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            lineage = bar_lineage.get(symbol)
            if lineage is None:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            start, end, request_id, stable = lineage
            if day < start or day > end:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            bar_keys[key] = {
                **row,
                "bar_request_id": request_id,
                "bar_stable_response_sha256": stable,
            }

        factor_keys: dict[tuple[str, dt.date, str], dict[str, Any]] = {}
        for row in factor_frame.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["effective_date"]
            source = row["source"]
            key = (symbol, day, source)
            if key in factor_keys:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            factor = float(row["adj_factor"])
            if not math.isfinite(factor) or factor <= 0:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            lineage = factor_lineage.get(symbol)
            if lineage is None:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            start, end, request_id, stable = lineage
            if day < start or day > end:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            factor_keys[key] = {
                "adj_factor": factor,
                "factor_request_id": request_id,
                "factor_stable_response_sha256": stable,
            }

        if not set(bar_keys).issubset(factor_keys):
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")

        out_bars: list[dict[str, Any]] = []
        out_match: list[dict[str, Any]] = []
        for key in sorted(bar_keys):
            bar_row = bar_keys[key]
            factor_row = factor_keys[key]
            out_bars.append(
                {
                    "symbol": key[0],
                    "trade_date": key[1],
                    "open": bar_row["open"],
                    "high": bar_row["high"],
                    "low": bar_row["low"],
                    "close": bar_row["close"],
                    "volume": bar_row["volume"],
                    "amount": bar_row["amount"],
                    "adj_factor": factor_row["adj_factor"],
                    "source": key[2],
                }
            )
            out_match.append(
                {
                    "symbol": key[0],
                    "trade_date": key[1],
                    "source": key[2],
                    "adj_factor": factor_row["adj_factor"],
                    "bar_request_id": bar_row["bar_request_id"],
                    "bar_stable_response_sha256": bar_row["bar_stable_response_sha256"],
                    "factor_request_id": factor_row["factor_request_id"],
                    "factor_stable_response_sha256": factor_row[
                        "factor_stable_response_sha256"
                    ],
                }
            )
        bars_out = pl.DataFrame(out_bars).select(
            [
                "symbol",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "adj_factor",
                "source",
            ]
        ).sort(["symbol", "trade_date", "source"])
        match_out = pl.DataFrame(out_match).select(list(_MATCH_COLUMNS)).sort(
            ["symbol", "trade_date", "source"]
        )
        return AdjustmentApplicationResult(bars=bars_out, factor_match_evidence=match_out)
    except M3G1CandidateError:
        raise
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID") from None


def project_scoped_adjustment_factors(
    *,
    bars: pl.DataFrame,
    adjustment_factors: pl.DataFrame,
) -> pl.DataFrame:
    """Project raw-mapped factors to publish scope ``first_bar..last_bar`` per symbol.

    Keeps suspension-day factor observations strictly inside the bar span; drops
    observations before the first or after the last candidate bar. Raw receipts are
    untouched by this projection.
    """
    try:
        if not isinstance(bars, pl.DataFrame) or not isinstance(
            adjustment_factors, pl.DataFrame
        ):
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        empty_schema = {
            "symbol": pl.Utf8,
            "effective_date": pl.Date,
            "adj_factor": pl.Float64,
            "source": pl.Utf8,
        }
        if bars.height == 0:
            if adjustment_factors.height:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            return pl.DataFrame(schema=empty_schema)
        required_bar_cols = {"symbol", "trade_date"}
        if not required_bar_cols.issubset(set(bars.columns)):
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        factor_frame = _validate_schema(
            adjustment_factors,
            AdjustmentFactorSchema,
            "G1_CANDIDATE_COMPONENT_INVALID",
        )
        bounds: dict[str, tuple[dt.date, dt.date]] = {}
        for row in bars.select(["symbol", "trade_date"]).iter_rows(named=True):
            symbol = row["symbol"]
            day = row["trade_date"]
            if type(symbol) is not str or type(day) is not dt.date:
                raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
            current = bounds.get(symbol)
            if current is None:
                bounds[symbol] = (day, day)
            else:
                first, last = current
                bounds[symbol] = (min(first, day), max(last, day))
        scoped_rows: list[dict[str, Any]] = []
        for row in factor_frame.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["effective_date"]
            span = bounds.get(symbol)
            if span is None:
                continue
            first_bar, last_bar = span
            if first_bar <= day <= last_bar:
                scoped_rows.append(dict(row))
        if not scoped_rows:
            return pl.DataFrame(schema=empty_schema)
        return (
            pl.DataFrame(scoped_rows)
            .select(["symbol", "effective_date", "adj_factor", "source"])
            .sort(["symbol", "effective_date", "source"])
        )
    except M3G1CandidateError:
        raise
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID") from None


def build_g1_candidate(*, inputs: G1BuildInputs) -> G1Candidate:
    """Rebuild primary candidate from frozen plan/responses/tables."""
    try:
        rebuilt_inputs = _consume_build_inputs(inputs)
        return _build_candidate_body(rebuilt_inputs)
    except M3G1CandidateError:
        raise
    except (
        index_membership.M3IndexMembershipError,
        mappers.M3G1MappingError,
        execution_facts.M3G1ExecutionFactError,
    ):
        raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID") from None
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID") from None


def verify_g1_candidate(*, inputs: G1BuildInputs, candidate: G1Candidate) -> None:
    """Rebuild from inputs and compare against reported candidate."""
    try:
        if type(candidate) is not G1Candidate:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        rebuilt = build_g1_candidate(inputs=inputs)
        if rebuilt.primary_candidate_key != candidate.primary_candidate_key:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        if rebuilt.table_content_digests != candidate.table_content_digests:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        if (
            rebuilt.price_limit_required_keys_sha256
            != candidate.price_limit_required_keys_sha256
        ):
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        if rebuilt.input_receipts != candidate.input_receipts:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        if (
            rebuilt.signal_start != candidate.signal_start
            or rebuilt.signal_end != candidate.signal_end
            or rebuilt.history_start != candidate.history_start
            or rebuilt.history_end != candidate.history_end
        ):
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        for left, right in (
            (rebuilt.calendars, candidate.calendars),
            (rebuilt.instruments, candidate.instruments),
            (rebuilt.observations, candidate.observations),
            (rebuilt.membership, candidate.membership),
            (rebuilt.eligible_keys, candidate.eligible_keys),
            (rebuilt.bars, candidate.bars),
            (rebuilt.adjustment_factors, candidate.adjustment_factors),
            (rebuilt.factor_match_evidence, candidate.factor_match_evidence),
            (rebuilt.benchmark_bars, candidate.benchmark_bars),
            (rebuilt.suspensions, candidate.suspensions),
            (rebuilt.price_limits, candidate.price_limits),
            (rebuilt.corporate_actions, candidate.corporate_actions),
            (
                rebuilt.corporate_action_selection_evidence,
                candidate.corporate_action_selection_evidence,
            ),
            (
                rebuilt.corporate_action_reconciliation,
                candidate.corporate_action_reconciliation,
            ),
        ):
            if not _frames_equal(left, right):
                raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
    except M3G1CandidateError:
        raise
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH") from None


def audit_g1_candidate(*, candidate: G1Candidate) -> G1PrimaryAuditResult:
    """Collect cross-table primary-source issues; never short-circuit on first issue."""
    issues: list[G1QualityIssue] = []
    try:
        if type(candidate) is not G1Candidate:
            issues.append(
                _issue("SCHEMA_INVALID", "candidate type invalid", 1, ())
            )
            return _audit_result(candidate=None, issues=issues)

        digests = dict(candidate.table_content_digests)
        frames: dict[str, pl.DataFrame] = {
            "trade_calendar": candidate.calendars,
            "instrument": candidate.instruments,
            "index_constituent_observation": candidate.observations,
            "universe_membership": candidate.membership,
            "eligible_keys": candidate.eligible_keys,
            "bar_1d": candidate.bars,
            "adjustment_factor": candidate.adjustment_factors,
            "adjustment_factor_match": candidate.factor_match_evidence,
            "benchmark_bar_1d": candidate.benchmark_bars,
            "suspension_1d": candidate.suspensions,
            "price_limit_1d": candidate.price_limits,
            "corporate_action_ledger": candidate.corporate_actions,
            "corporate_action_selection_evidence": (
                candidate.corporate_action_selection_evidence
            ),
            "corporate_action_reconciliation": candidate.corporate_action_reconciliation,
        }
        schema_map: dict[str, Any] = {
            "trade_calendar": TradeCalendarSchema,
            "instrument": InstrumentSchema,
            "index_constituent_observation": IndexConstituentObservationSchema,
            "universe_membership": UniverseMembershipSchema,
            "bar_1d": Bar1dSchema,
            "adjustment_factor": AdjustmentFactorSchema,
            "adjustment_factor_match": AdjustmentFactorMatchSchema,
            "benchmark_bar_1d": BenchmarkBar1dSchema,
            "suspension_1d": Suspension1dSchema,
            "price_limit_1d": PriceLimit1dSchema,
            "corporate_action_ledger": CorporateActionLedgerSchema,
            "corporate_action_selection_evidence": CorporateActionSelectionEvidenceSchema,
            "corporate_action_reconciliation": CorporateActionReconciliationSchema,
        }

        for name in _TABLE_NAMES:
            frame = frames[name]
            if name == "eligible_keys":
                if (
                    not isinstance(frame, pl.DataFrame)
                    or list(frame.columns) != ["as_of", "symbol"]
                ):
                    issues.append(
                        _issue("SCHEMA_INVALID", "eligible_keys schema invalid", 1, ())
                    )
                    continue
            else:
                try:
                    schema_map[name].validate(frame)
                except Exception:
                    issues.append(
                        _issue("SCHEMA_INVALID", f"{name} schema invalid", 1, (name,))
                    )
                    continue
            try:
                digest = clean_table_content_sha256(table_name=name, frame=frame)
            except Exception:
                issues.append(
                    _issue("SCHEMA_INVALID", f"{name} digest invalid", 1, (name,))
                )
                continue
            if digests.get(name) != digest:
                issues.append(
                    _issue("SCHEMA_INVALID", f"{name} digest mismatch", 1, (name,))
                )

        # Calendar SH/SZ exact date domain and is_open parity.
        try:
            cal = candidate.calendars
            sh = {
                row["date"]: bool(row["is_open"])
                for row in cal.filter(pl.col("market") == "SH").iter_rows(named=True)
            }
            sz = {
                row["date"]: bool(row["is_open"])
                for row in cal.filter(pl.col("market") == "SZ").iter_rows(named=True)
            }
            if set(sh) != set(sz):
                issues.append(
                    _issue(
                        "CALENDAR_MISMATCH",
                        "SH/SZ date domain mismatch",
                        1,
                        (),
                    )
                )
            else:
                mismatched = sorted(
                    day.isoformat() for day in sh if sh[day] != sz[day]
                )
                if mismatched:
                    issues.append(
                        _issue(
                            "CALENDAR_MISMATCH",
                            "SH/SZ is_open mismatch",
                            len(mismatched),
                            tuple(mismatched[:32]),
                        )
                    )
            sh_sessions = sorted(day for day, is_open in sh.items() if is_open)
        except Exception:
            sh_sessions = []
            issues.append(_issue("CALENDAR_MISMATCH", "calendar unreadable", 1, ()))

        history_sessions = [
            day
            for day in sh_sessions
            if candidate.history_start <= day <= candidate.history_end
        ]

        # Membership / eligible: rebuild from candidate observations via the
        # authoritative builder; count∈[1,300] is not a sufficient condition.
        try:
            rebuilt_membership = index_membership.build_observed_membership(
                observations=candidate.observations,
                calendars=candidate.calendars,
                instruments=candidate.instruments,
                universe=_UNIVERSE,
                signal_start=candidate.signal_start,
                signal_end=candidate.signal_end,
                expected_constituent_count=_EXPECTED_COUNT,
            )
            if not _frames_equal(
                rebuilt_membership.membership, candidate.membership
            ):
                issues.append(
                    _issue(
                        "MEMBERSHIP_COUNT_MISMATCH",
                        "membership does not match authoritative rebuild",
                        1,
                        (),
                    )
                )
            elif digests.get("universe_membership") != (
                rebuilt_membership.membership_sha256
            ):
                issues.append(
                    _issue(
                        "MEMBERSHIP_COUNT_MISMATCH",
                        "membership digest does not match authoritative rebuild",
                        1,
                        (),
                    )
                )
            if not _frames_equal(
                rebuilt_membership.eligible_keys, candidate.eligible_keys
            ):
                issues.append(
                    _issue(
                        "MEMBERSHIP_COUNT_MISMATCH",
                        "eligible_keys does not match authoritative rebuild",
                        1,
                        (),
                    )
                )
            elif digests.get("eligible_keys") != (
                rebuilt_membership.eligible_keys_sha256
            ):
                issues.append(
                    _issue(
                        "MEMBERSHIP_COUNT_MISMATCH",
                        "eligible_keys digest does not match authoritative rebuild",
                        1,
                        (),
                    )
                )
        except Exception:
            issues.append(
                _issue(
                    "MEMBERSHIP_COUNT_MISMATCH",
                    "membership authoritative rebuild failed",
                    1,
                    (),
                )
            )

        # Instrument index.
        try:
            instrument_map = {
                row["symbol"]: (row["list_date"], row["delist_date"])
                for row in candidate.instruments.iter_rows(named=True)
            }
        except Exception:
            instrument_map = {}
            issues.append(_issue("SCHEMA_INVALID", "instrument unreadable", 1, ()))

        bar_keys = {
            (row["symbol"], row["trade_date"])
            for row in candidate.bars.iter_rows(named=True)
        }
        full_day = {
            (row["symbol"], row["trade_date"])
            for row in candidate.suspensions.iter_rows(named=True)
            if row["suspension_scope"] == "FULL_DAY"
        }
        partial = {
            (row["symbol"], row["trade_date"])
            for row in candidate.suspensions.iter_rows(named=True)
            if row["suspension_scope"] == "PARTIAL"
        }
        # Last lifecycle SH session per symbol (delist_date mapped on-or-before).
        # Absorb-merge delist days are often eligible yet lack daily + suspend_d.
        delist_lifecycle_keys: set[tuple[str, dt.date]] = set()
        for symbol, (_list_date, delist_date) in instrument_map.items():
            if delist_date is None:
                continue
            prior = [day for day in sh_sessions if day <= delist_date]
            if prior:
                delist_lifecycle_keys.add((symbol, prior[-1]))

        missing: list[str] = []
        conflicts: list[str] = []
        partial_missing: list[str] = []
        try:
            for row in candidate.eligible_keys.iter_rows(named=True):
                key = (row["symbol"], row["as_of"])
                has_bar = key in bar_keys
                has_full = key in full_day
                if has_bar and has_full:
                    conflicts.append(f"{key[0]}|{key[1].isoformat()}")
                elif not has_bar and not has_full:
                    if key in delist_lifecycle_keys:
                        continue
                    missing.append(f"{key[0]}|{key[1].isoformat()}")
                if key in partial and not has_bar:
                    partial_missing.append(f"{key[0]}|{key[1].isoformat()}")
        except Exception:
            issues.append(
                _issue("BAR_OR_SUSPENSION_MISSING", "eligible coverage unreadable", 1, ())
            )
        if missing:
            issues.append(
                _issue(
                    "BAR_OR_SUSPENSION_MISSING",
                    "eligible key missing bar and full suspension",
                    len(missing),
                    tuple(sorted(missing)[:32]),
                )
            )
        if conflicts:
            issues.append(
                _issue(
                    "BAR_FULL_SUSPENSION_CONFLICT",
                    "bar and FULL_DAY both present",
                    len(conflicts),
                    tuple(sorted(conflicts)[:32]),
                )
            )
        if partial_missing:
            issues.append(
                _issue(
                    "PARTIAL_SUSPENSION_BAR_MISSING",
                    "PARTIAL suspension without bar",
                    len(partial_missing),
                    tuple(sorted(partial_missing)[:32]),
                )
            )

        # Bar quality and lifecycle.
        bad_bars: list[str] = []
        unknown: list[str] = []
        for row in candidate.bars.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["trade_date"]
            life = instrument_map.get(symbol)
            if life is None:
                unknown.append(f"{symbol}|{day.isoformat()}")
                continue
            list_date, delist_date = life
            if day < list_date or (delist_date is not None and day > delist_date):
                unknown.append(f"{symbol}|{day.isoformat()}")
            for field in ("open", "high", "low", "close", "volume", "amount", "adj_factor"):
                value = float(row[field])
                if not math.isfinite(value) or value <= 0:
                    bad_bars.append(f"{symbol}|{day.isoformat()}|{field}")
        if unknown:
            issues.append(
                _issue(
                    "UNKNOWN_INSTRUMENT",
                    "bar outside instrument lifecycle or unknown",
                    len(unknown),
                    tuple(sorted(unknown)[:32]),
                )
            )
        if bad_bars:
            issues.append(
                _issue(
                    "SCHEMA_INVALID",
                    "bar numeric fields must be positive finite",
                    len(bad_bars),
                    tuple(sorted(bad_bars)[:32]),
                )
            )

        # Factor match evidence closure.
        match_keys = {
            (row["symbol"], row["trade_date"], row["source"]): float(row["adj_factor"])
            for row in candidate.factor_match_evidence.iter_rows(named=True)
        }
        factor_index = {
            (row["symbol"], row["effective_date"], row["source"]): float(row["adj_factor"])
            for row in candidate.adjustment_factors.iter_rows(named=True)
        }
        receipt_ids = {item.request_id: item for item in candidate.input_receipts}
        missing_match: list[str] = []
        bad_factor: list[str] = []
        for row in candidate.bars.iter_rows(named=True):
            match_key = (row["symbol"], row["trade_date"], row["source"])
            evidence_factor = match_keys.get(match_key)
            if evidence_factor is None:
                missing_match.append(f"{match_key[0]}|{match_key[1].isoformat()}")
                continue
            base = factor_index.get(match_key)
            if base is None or base != evidence_factor or base != float(row["adj_factor"]):
                bad_factor.append(f"{match_key[0]}|{match_key[1].isoformat()}")
        if missing_match:
            issues.append(
                _issue(
                    "FACTOR_MISSING",
                    "emitted bar missing factor-match evidence",
                    len(missing_match),
                    tuple(sorted(missing_match)[:32]),
                )
            )
        if bad_factor:
            issues.append(
                _issue(
                    "FACTOR_INVALID",
                    "factor evidence does not match adjustment factor/bar",
                    len(bad_factor),
                    tuple(sorted(bad_factor)[:32]),
                )
            )
        # Self-contained publish-scope check from candidate tables only
        # (audit has no frozen inputs). Exact scoped rebuild from inputs is
        # verify_g1_candidate / build_g1_candidate responsibility.
        bar_bounds: dict[str, tuple[dt.date, dt.date]] = {}
        for row in candidate.bars.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["trade_date"]
            current = bar_bounds.get(symbol)
            if current is None:
                bar_bounds[symbol] = (day, day)
            else:
                first, last = current
                bar_bounds[symbol] = (min(first, day), max(last, day))
        out_of_scope: list[str] = []
        for row in candidate.adjustment_factors.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["effective_date"]
            span = bar_bounds.get(symbol)
            if span is None or day < span[0] or day > span[1]:
                out_of_scope.append(f"{symbol}|{day.isoformat()}")
        if out_of_scope:
            issues.append(
                _issue(
                    "FACTOR_INVALID",
                    "adjustment factor outside publish bar scope",
                    len(out_of_scope),
                    tuple(sorted(out_of_scope)[:32]),
                )
            )
        for row in candidate.factor_match_evidence.iter_rows(named=True):
            for field in ("bar_request_id", "factor_request_id"):
                if row[field] not in receipt_ids:
                    issues.append(
                        _issue(
                            "RECEIPT_INVALID",
                            "factor-match lineage missing from receipts",
                            1,
                            (row[field],),
                        )
                    )

        # Benchmark coverage over full history open sessions.
        bench_days = {
            row["trade_date"]
            for row in candidate.benchmark_bars.iter_rows(named=True)
            if row["benchmark"] == _BENCHMARK
        }
        missing_bench = [day.isoformat() for day in history_sessions if day not in bench_days]
        if missing_bench:
            issues.append(
                _issue(
                    "BENCHMARK_MISSING",
                    "benchmark missing history SH open session",
                    len(missing_bench),
                    tuple(missing_bench[:32]),
                )
            )
        if len(bench_days) != len(history_sessions):
            issues.append(
                _issue(
                    "BENCHMARK_MISSING",
                    "benchmark row count differs from history sessions",
                    1,
                    (),
                )
            )

        # Price-limit required keys: recompute from candidate components.
        try:
            required = execution_facts.require_g1_price_limit_coverage(
                price_limits=candidate.price_limits,
                eligible_keys=candidate.eligible_keys,
                suspensions=candidate.suspensions,
                calendars=candidate.calendars,
                instruments=candidate.instruments,
                bars=candidate.bars,
                history=HistoryWindow(candidate.history_start, candidate.history_end),
            )
            required_digest = clean_table_content_sha256(
                table_name="price_limit_required_keys", frame=required
            )
            if required_digest != candidate.price_limit_required_keys_sha256:
                issues.append(
                    _issue(
                        "PRICE_LIMIT_INVALID",
                        "required price-limit key digest mismatch",
                        1,
                        (),
                    )
                )
            limit_index = {
                (row["trade_date"], row["symbol"]): row
                for row in candidate.price_limits.iter_rows(named=True)
            }
            missing_limits: list[str] = []
            for row in required.iter_rows(named=True):
                key = (row["trade_date"], row["symbol"])
                limit = limit_index.get(key)
                if limit is None or limit["has_price_limit"] is not True:
                    missing_limits.append(f"{key[1]}|{key[0].isoformat()}")
            if missing_limits:
                issues.append(
                    _issue(
                        "PRICE_LIMIT_MISSING",
                        "required price-limit key missing or unproven",
                        len(missing_limits),
                        tuple(sorted(missing_limits)[:32]),
                    )
                )
            # Build once: per-key set comprehension over required is O(|full_day|·|required|).
            required_trade_symbol_keys = {
                (row["trade_date"], row["symbol"])
                for row in required.iter_rows(named=True)
            }
            for key in full_day:
                if (key[1], key[0]) in required_trade_symbol_keys:
                    issues.append(
                        _issue(
                            "PRICE_LIMIT_INVALID",
                            "FULL_DAY key must not be required",
                            1,
                            (f"{key[0]}|{key[1].isoformat()}",),
                        )
                    )
        except execution_facts.M3G1ExecutionFactError:
            issues.append(
                _issue(
                    "PRICE_LIMIT_MISSING",
                    "price-limit coverage rebuild failed",
                    1,
                    (),
                )
            )
        except Exception:
            issues.append(
                _issue(
                    "PRICE_LIMIT_INVALID",
                    "price-limit coverage check failed",
                    1,
                    (),
                )
            )

        # Corporate-action result digests and receipt lineage.
        try:
            execution_facts.verify_corporate_action_selection_result(
                result=execution_facts.CorporateActionSelectionResult(
                    ledger=candidate.corporate_actions,
                    selection_evidence=candidate.corporate_action_selection_evidence,
                    ledger_sha256=digests["corporate_action_ledger"],
                    selection_evidence_sha256=digests[
                        "corporate_action_selection_evidence"
                    ],
                )
            )
        except Exception:
            issues.append(
                _issue(
                    "CORPORATE_ACTION_INVALID",
                    "selection result failed verification",
                    1,
                    (),
                )
            )
        try:
            execution_facts.verify_corporate_action_reconciliation_result(
                result=execution_facts.CorporateActionReconciliationResult(
                    evidence=candidate.corporate_action_reconciliation,
                    evidence_sha256=digests["corporate_action_reconciliation"],
                )
            )
            execution_facts.assert_corporate_action_reconciliation_ledger_closure(
                corporate_actions=candidate.corporate_actions,
                reconciliation=candidate.corporate_action_reconciliation,
                input_receipts=candidate.input_receipts,
            )
        except Exception:
            issues.append(
                _issue(
                    "CORPORATE_ACTION_FACTOR_MISMATCH",
                    "reconciliation result failed verification",
                    1,
                    (),
                )
            )
        # Self-contained bind: scoped adjacent factor transitions ↔ evidence keys,
        # row count sum(max(n-1,0)), and exact actual_factor_ratio. Audit has no
        # frozen inputs; verify_g1_candidate remains the inputs-rebuild path.
        topology_issue = _audit_scoped_factor_reconciliation_topology(
            adjustment_factors=candidate.adjustment_factors,
            reconciliation=candidate.corporate_action_reconciliation,
        )
        if topology_issue is not None:
            issues.append(topology_issue)
        for row in candidate.corporate_action_reconciliation.iter_rows(named=True):
            if row["daily_request_id"] not in receipt_ids:
                issues.append(
                    _issue(
                        "RECEIPT_INVALID",
                        "reconciliation daily lineage missing",
                        1,
                        (row["daily_request_id"],),
                    )
                )
            else:
                projection = receipt_ids[row["daily_request_id"]]
                if projection.stable_response_sha256 != row["daily_stable_response_sha256"]:
                    issues.append(
                        _issue(
                            "RECEIPT_INVALID",
                            "reconciliation daily stable digest mismatch",
                            1,
                            (row["daily_request_id"],),
                        )
                    )

        # Identity self-check from candidate projections.
        try:
            expected_key = _primary_candidate_key(
                build_spec=candidate.build_spec,
                request_plan_sha256=candidate.request_plan.plan_sha256,
                signal_start=candidate.signal_start,
                signal_end=candidate.signal_end,
                history_start=candidate.history_start,
                history_end=candidate.history_end,
                input_receipts=candidate.input_receipts,
                table_content_digests=candidate.table_content_digests,
                price_limit_required_keys_sha256=candidate.price_limit_required_keys_sha256,
            )
            if expected_key != candidate.primary_candidate_key:
                issues.append(
                    _issue(
                        "SCHEMA_INVALID",
                        "primary_candidate_key mismatch",
                        1,
                        (),
                    )
                )
        except Exception:
            issues.append(
                _issue("SCHEMA_INVALID", "primary identity rebuild failed", 1, ())
            )

        return _audit_result(candidate=candidate, issues=issues)
    except Exception:
        issues.append(_issue("SCHEMA_INVALID", "audit failed closed", 1, ()))
        return _audit_result(candidate=candidate if type(candidate) is G1Candidate else None, issues=issues)


def _build_candidate_body(inputs: G1BuildInputs) -> G1Candidate:
    plan = inputs.request_plan
    responses = list(inputs.responses)
    cninfo_responses = list(inputs.cninfo_responses)
    cninfo_dividend_responses = list(inputs.cninfo_dividend_responses)
    cninfo_share_change_responses = list(inputs.cninfo_share_change_responses)
    _assert_plan_response_multiset(plan, responses)
    _assert_cninfo_response_multiset(plan, cninfo_responses)
    _assert_cninfo_corporate_action_response_multiset(
        plan.cninfo_dividend_batch, cninfo_dividend_responses
    )
    _assert_cninfo_corporate_action_response_multiset(
        plan.cninfo_share_change_batch, cninfo_share_change_responses
    )
    _assert_endpoint_closures(plan, responses, history=inputs.history)

    by_id = {item.spec.request_id: item for item in responses}
    weight_responses = [
        by_id[spec.request_id] for spec in plan.index_weight_batch.requests
    ]
    history_responses = [
        by_id[spec.request_id] for spec in plan.history_batch.requests
    ]

    observations = index_membership.normalize_index_weight_observations(
        batch=plan.index_weight_batch,
        responses=weight_responses,
        universe=inputs.universe,
    )
    membership_result = index_membership.build_observed_membership(
        observations=observations,
        calendars=inputs.calendars,
        instruments=inputs.instruments,
        universe=inputs.universe,
        signal_start=inputs.signal_start,
        signal_end=inputs.signal_end,
        expected_constituent_count=inputs.expected_constituent_count,
    )
    index_membership.verify_observed_membership_result(
        batch=plan.index_weight_batch,
        responses=weight_responses,
        result=membership_result,
        calendars=inputs.calendars,
        instruments=inputs.instruments,
        universe=inputs.universe,
        signal_start=inputs.signal_start,
        signal_end=inputs.signal_end,
        expected_constituent_count=inputs.expected_constituent_count,
    )

    history_symbols = sorted(
        set(membership_result.observations.get_column("symbol").to_list())
    )
    if not history_symbols:
        raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")

    daily_responses = [
        item for item in history_responses if item.spec.endpoint == "daily"
    ]
    factor_responses = [
        item for item in history_responses if item.spec.endpoint == "adj_factor"
    ]
    limit_responses = [
        item for item in history_responses if item.spec.endpoint == "stk_limit"
    ]
    dividend_responses = [
        item for item in history_responses if item.spec.endpoint == "dividend"
    ]
    suspend_responses = [
        item for item in history_responses if item.spec.endpoint == "suspend_d"
    ]
    fund_daily_responses = [
        item for item in history_responses if item.spec.endpoint == "fund_daily"
    ]
    fund_adj_responses = [
        item for item in history_responses if item.spec.endpoint == "fund_adj"
    ]
    fund_div_responses = [
        item for item in history_responses if item.spec.endpoint == "fund_div"
    ]
    if len(fund_daily_responses) != 1 or len(fund_div_responses) != 1:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if not fund_adj_responses:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    # Stable order by request_id; mapper re-validates contiguous coverage.
    fund_adj_ordered = tuple(
        sorted(fund_adj_responses, key=lambda item: item.spec.request_id)
    )

    mapped_daily = [
        mappers.map_g1_daily_response(response=item) for item in daily_responses
    ]
    mapped_factors = [
        mappers.map_g1_adjustment_factor_response(response=item)
        for item in factor_responses
    ]
    bars_no_factor = (
        pl.concat(mapped_daily).sort(["symbol", "trade_date", "source"])
        if mapped_daily
        else pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "trade_date": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
                "amount": pl.Float64,
                "source": pl.Utf8,
            }
        )
    )
    adjustment_factors = (
        pl.concat(mapped_factors).sort(["symbol", "effective_date", "source"])
        if mapped_factors
        else pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "effective_date": pl.Date,
                "adj_factor": pl.Float64,
                "source": pl.Utf8,
            }
        )
    )
    # Publish-scope: drop factor observations strictly before first / after last bar.
    # Raw-mapped history remains in receipts; only candidate tables are scoped.
    adjustment_factors = project_scoped_adjustment_factors(
        bars=bars_no_factor,
        adjustment_factors=adjustment_factors,
    )
    applied = apply_adjustment_factors_strict(
        bars=bars_no_factor,
        adjustment_factors=adjustment_factors,
        daily_responses=daily_responses,
        factor_responses=factor_responses,
    )

    daily_pre_close = execution_facts.build_g1_daily_pre_close_lookup(
        daily_responses=daily_responses
    )
    mapped_limits = [
        execution_facts.map_g1_price_limit_response(
            response=item, daily_pre_close=daily_pre_close
        )
        for item in limit_responses
    ]
    price_limits = (
        pl.concat(mapped_limits).sort(["symbol", "trade_date", "source"])
        if mapped_limits
        else pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "trade_date": pl.Date,
                "pre_close": pl.Float64,
                "has_price_limit": pl.Boolean,
                "up_limit": pl.Float64,
                "down_limit": pl.Float64,
                "source": pl.Utf8,
                "source_snapshot_id": pl.Utf8,
            }
        )
    )
    price_limits = PriceLimit1dSchema.validate(price_limits)

    suspension_frames = [
        mappers.map_g1_suspension_response(response=item) for item in suspend_responses
    ]
    suspensions = (
        pl.concat(suspension_frames).sort(["symbol", "trade_date", "source"])
        if suspension_frames
        else pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "trade_date": pl.Date,
                "suspension_scope": pl.Utf8,
                "suspension_detail": pl.Utf8,
                "source": pl.Utf8,
                "source_snapshot_id": pl.Utf8,
            }
        )
    )
    history_symbol_set = set(history_symbols)
    if suspensions.height:
        suspensions = suspensions.filter(pl.col("symbol").is_in(sorted(history_symbol_set)))
    suspensions = Suspension1dSchema.validate(
        suspensions.sort(["symbol", "trade_date", "source"])
    )

    benchmark_bars = mappers.map_g1_benchmark_response(
        fund_daily=fund_daily_responses[0],
        fund_adj_segments=fund_adj_ordered,
        fund_div=fund_div_responses[0],
        factor_ratio_rtol=inputs.factor_ratio_rtol,
    )
    benchmark_bars = BenchmarkBar1dSchema.validate(
        benchmark_bars.sort(["benchmark", "trade_date", "source"])
    )

    ledger_parts: list[pl.DataFrame] = []
    evidence_parts: list[pl.DataFrame] = []
    for response in dividend_responses:
        selected = execution_facts.select_g1_corporate_actions(
            response=response, history=inputs.history
        )
        execution_facts.verify_corporate_action_selection_result(result=selected)
        ledger_parts.append(selected.ledger)
        evidence_parts.append(selected.selection_evidence)
    for cninfo_response in cninfo_responses:
        selected = execution_facts.select_g1_cninfo_rights_actions(
            response=cninfo_response,
            history=inputs.history,
            symbols=history_symbols,
        )
        execution_facts.verify_corporate_action_selection_result(result=selected)
        ledger_parts.append(selected.ledger)
        evidence_parts.append(selected.selection_evidence)
    normalization_facts: list[execution_facts.StockRatioNormalizationFact] = []
    pre_consideration_actions = _concat_or_empty(
        ledger_parts,
        schema={
            "event_id": pl.Utf8,
            "symbol": pl.Utf8,
            "ex_date": pl.Date,
            "cash_per_share_gross": pl.Float64,
            "stock_ratio": pl.Float64,
            "record_date": pl.Date,
            "pay_date": pl.Date,
            "stock_list_date": pl.Date,
            "source": pl.Utf8,
            "source_snapshot_id": pl.Utf8,
            "action_type": pl.Utf8,
            "rights_price": pl.Float64,
            "rights_ratio": pl.Float64,
            "rights_actual_shares": pl.Float64,
            "rights_pre_shares": pl.Float64,
            "rights_post_shares": pl.Float64,
            "vendor_record_id": pl.Utf8,
        },
        sort_keys=["symbol", "ex_date", "event_id"],
        schema_model=CorporateActionLedgerSchema,
    )
    share_change_by_symbol = {
        dict(response.spec.parameters)["symbol"]: response
        for response in cninfo_share_change_responses
    }
    if len(share_change_by_symbol) != len(cninfo_share_change_responses):
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    for dividend_response in cninfo_dividend_responses:
        code = dict(dividend_response.spec.parameters).get("symbol")
        if type(code) is not str:
            raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
        share_change_response = share_change_by_symbol.get(code)
        if share_change_response is None:
            raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
        symbol = next(
            (item for item in history_symbols if item.startswith(f"{code}.")),
            None,
        )
        if symbol is None:
            raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
        selected, facts = (
            execution_facts.select_g1_cninfo_share_consideration_actions(
                dividend_response=dividend_response,
                share_change_response=share_change_response,
                history=inputs.history,
                symbols=(symbol,),
                existing_actions=pre_consideration_actions.filter(
                    pl.col("symbol") == symbol
                ),
            )
        )
        execution_facts.verify_corporate_action_selection_result(result=selected)
        ledger_parts.append(selected.ledger)
        evidence_parts.append(selected.selection_evidence)
        normalization_facts.extend(facts)
    corporate_actions = _concat_or_empty(
        ledger_parts,
        schema={
            "event_id": pl.Utf8,
            "symbol": pl.Utf8,
            "ex_date": pl.Date,
            "cash_per_share_gross": pl.Float64,
            "stock_ratio": pl.Float64,
            "record_date": pl.Date,
            "pay_date": pl.Date,
            "stock_list_date": pl.Date,
            "source": pl.Utf8,
            "source_snapshot_id": pl.Utf8,
            "action_type": pl.Utf8,
            "rights_price": pl.Float64,
            "rights_ratio": pl.Float64,
            "rights_actual_shares": pl.Float64,
            "rights_pre_shares": pl.Float64,
            "rights_post_shares": pl.Float64,
            "vendor_record_id": pl.Utf8,
        },
        sort_keys=["symbol", "ex_date", "event_id"],
        schema_model=CorporateActionLedgerSchema,
    )
    selection_evidence = _concat_or_empty(
        evidence_parts,
        schema={
            "economic_event_key_sha256": pl.Utf8,
            "candidate_id": pl.Utf8,
            "symbol": pl.Utf8,
            "end_date": pl.Date,
            "record_date": pl.Date,
            "ex_date": pl.Date,
            "imp_ann_date": pl.Date,
            "ann_date": pl.Date,
            "cash_per_share_gross": pl.Float64,
            "stock_ratio": pl.Float64,
            "pay_date": pl.Date,
            "stock_list_date": pl.Date,
            "candidate_rank": pl.Int64,
            "candidate_count": pl.Int64,
            "raw_row_count": pl.Int64,
            "selected": pl.Boolean,
            "selection_reason": pl.Utf8,
            "source": pl.Utf8,
            "source_request_id": pl.Utf8,
            "source_snapshot_id": pl.Utf8,
            "action_type": pl.Utf8,
            "rights_price": pl.Float64,
            "rights_ratio": pl.Float64,
            "rights_actual_shares": pl.Float64,
            "rights_pre_shares": pl.Float64,
            "rights_post_shares": pl.Float64,
            "vendor_record_id": pl.Utf8,
        },
        sort_keys=["symbol", "ex_date", "candidate_rank", "candidate_id"],
        schema_model=CorporateActionSelectionEvidenceSchema,
    )
    selection_result = execution_facts.CorporateActionSelectionResult(
        ledger=corporate_actions,
        selection_evidence=selection_evidence,
        ledger_sha256=clean_table_content_sha256(
            table_name="corporate_action_ledger", frame=corporate_actions
        ),
        selection_evidence_sha256=clean_table_content_sha256(
            table_name="corporate_action_selection_evidence", frame=selection_evidence
        ),
    )
    execution_facts.verify_corporate_action_selection_result(result=selection_result)

    required_keys = execution_facts.require_g1_price_limit_coverage(
        price_limits=price_limits,
        eligible_keys=membership_result.eligible_keys,
        suspensions=suspensions,
        calendars=inputs.calendars,
        instruments=inputs.instruments,
        bars=applied.bars,
        history=inputs.history,
    )
    required_digest = clean_table_content_sha256(
        table_name="price_limit_required_keys", frame=required_keys
    )

    reconciliation = execution_facts.reconcile_g1_corporate_actions(
        corporate_actions=corporate_actions,
        bars=applied.bars,
        adjustment_factors=adjustment_factors,
        daily_responses=daily_responses,
        suspensions=suspensions,
        calendars=inputs.calendars,
        history=inputs.history,
        factor_ratio_rtol=inputs.factor_ratio_rtol,
        stock_ratio_normalization_facts=tuple(normalization_facts),
    )
    execution_facts.verify_corporate_action_reconciliation_result(result=reconciliation)

    calendars = TradeCalendarSchema.validate(
        inputs.calendars.sort(["market", "date"])
    )
    instruments = InstrumentSchema.validate(
        inputs.instruments.sort(["symbol"])
    )
    observations = IndexConstituentObservationSchema.validate(
        membership_result.observations.sort(
            ["observation_date", "symbol", "source", "source_snapshot_id"]
        )
    )
    membership = UniverseMembershipSchema.validate(
        membership_result.membership.sort(
            ["universe", "symbol", "effective_from", "effective_to"]
        )
    )
    eligible_keys = membership_result.eligible_keys.sort(["as_of", "symbol"])
    bars = Bar1dSchema.validate(
        applied.bars.sort(["symbol", "trade_date", "source"])
    )
    adjustment_factors = AdjustmentFactorSchema.validate(
        adjustment_factors.sort(["symbol", "effective_date", "source"])
    )
    factor_match_evidence = AdjustmentFactorMatchSchema.validate(
        applied.factor_match_evidence.sort(["symbol", "trade_date", "source"])
    )
    corporate_action_reconciliation = CorporateActionReconciliationSchema.validate(
        reconciliation.evidence.sort(
            ["symbol", "previous_factor_date", "effective_date"]
        )
    )

    table_frames: dict[str, pl.DataFrame] = {
        "adjustment_factor": adjustment_factors,
        "adjustment_factor_match": factor_match_evidence,
        "bar_1d": bars,
        "benchmark_bar_1d": benchmark_bars,
        "corporate_action_ledger": corporate_actions,
        "corporate_action_reconciliation": corporate_action_reconciliation,
        "corporate_action_selection_evidence": selection_evidence,
        "eligible_keys": eligible_keys,
        "index_constituent_observation": observations,
        "instrument": instruments,
        "price_limit_1d": price_limits,
        "suspension_1d": suspensions,
        "trade_calendar": calendars,
        "universe_membership": membership,
    }
    digests = tuple(
        (name, clean_table_content_sha256(table_name=name, frame=table_frames[name]))
        for name in _TABLE_NAMES
    )
    receipts = tuple(
        sorted(
            [_project_receipt(item) for item in responses]
            + [_project_cninfo_receipt(item) for item in cninfo_responses]
            + [
                _project_cninfo_corporate_action_receipt(item)
                for item in cninfo_dividend_responses
            ]
            + [
                _project_cninfo_corporate_action_receipt(item)
                for item in cninfo_share_change_responses
            ],
            key=lambda value: (value.source, value.endpoint, value.request_id),
        )
    )
    execution_facts.assert_corporate_action_reconciliation_ledger_closure(
        corporate_actions=corporate_actions,
        reconciliation=corporate_action_reconciliation,
        input_receipts=receipts,
    )
    primary_key = _primary_candidate_key(
        build_spec=inputs.build_spec,
        request_plan_sha256=plan.plan_sha256,
        signal_start=inputs.signal_start,
        signal_end=inputs.signal_end,
        history_start=inputs.history.start,
        history_end=inputs.history.end,
        input_receipts=receipts,
        table_content_digests=digests,
        price_limit_required_keys_sha256=required_digest,
    )
    return G1Candidate(
        build_spec=inputs.build_spec,
        request_plan=plan,
        signal_start=inputs.signal_start,
        signal_end=inputs.signal_end,
        history_start=inputs.history.start,
        history_end=inputs.history.end,
        input_receipts=receipts,
        calendars=calendars,
        instruments=instruments,
        observations=observations,
        membership=membership,
        eligible_keys=eligible_keys,
        bars=bars,
        adjustment_factors=adjustment_factors,
        factor_match_evidence=factor_match_evidence,
        benchmark_bars=benchmark_bars,
        suspensions=suspensions,
        price_limits=price_limits,
        corporate_actions=corporate_actions,
        corporate_action_selection_evidence=selection_evidence,
        corporate_action_reconciliation=corporate_action_reconciliation,
        table_content_digests=digests,
        price_limit_required_keys_sha256=required_digest,
        primary_candidate_key=primary_key,
    )


def _assert_plan_response_multiset(
    plan: G1RequestPlan, responses: Sequence[VerifiedRawResponse]
) -> None:
    plan_ids = [spec.request_id for spec in plan.index_weight_batch.requests] + [
        spec.request_id for spec in plan.history_batch.requests
    ]
    response_ids = [item.spec.request_id for item in responses]
    if Counter(plan_ids) != Counter(response_ids):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if len(set(response_ids)) != len(response_ids):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    by_id = {item.spec.request_id: item for item in responses}
    for spec in list(plan.index_weight_batch.requests) + list(plan.history_batch.requests):
        verified = by_id[spec.request_id]
        if verified.spec != spec and (
            verified.spec.request_id != spec.request_id
            or verified.spec.endpoint != spec.endpoint
            or verified.spec.parameters != spec.parameters
        ):
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
        # Rebuild proves receipt/frame/digest closure.
        _consume_verified(verified)


def _assert_endpoint_closures(
    plan: G1RequestPlan,
    responses: Sequence[VerifiedRawResponse],
    *,
    history: HistoryWindow,
) -> None:
    by_id = {item.spec.request_id: item for item in responses}
    history_specs = list(plan.history_batch.requests)
    symbols: list[str] = []
    for spec in history_specs:
        if spec.endpoint in {"daily", "adj_factor", "stk_limit", "dividend"}:
            params = dict(spec.parameters)
            symbol = params.get("ts_code")
            if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
                raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
            symbols.append(symbol)
    history_symbols = sorted(set(symbols))
    if not history_symbols:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    for symbol in history_symbols:
        for endpoint in ("daily", "adj_factor", "stk_limit", "dividend"):
            matches = [
                spec
                for spec in history_specs
                if spec.endpoint == endpoint and dict(spec.parameters).get("ts_code") == symbol
            ]
            if len(matches) != 1:
                raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
            if endpoint != "dividend":
                params = dict(matches[0].parameters)
                if params.get("start_date") != history.start.strftime("%Y%m%d"):
                    raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
                if params.get("end_date") != history.end.strftime("%Y%m%d"):
                    raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    fund_daily = [spec for spec in history_specs if spec.endpoint == "fund_daily"]
    fund_adj = [spec for spec in history_specs if spec.endpoint == "fund_adj"]
    fund_div = [spec for spec in history_specs if spec.endpoint == "fund_div"]
    if len(fund_daily) != 1 or len(fund_div) != 1 or not fund_adj:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if any(spec.endpoint == "index_daily" for spec in history_specs):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    daily_params = dict(fund_daily[0].parameters)
    if daily_params.get("ts_code") != _BENCHMARK:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if daily_params.get("start_date") != history.start.strftime("%Y%m%d"):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if daily_params.get("end_date") != history.end.strftime("%Y%m%d"):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    div_params = dict(fund_div[0].parameters)
    if div_params.get("ts_code") != _BENCHMARK:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if "start_date" in div_params or "end_date" in div_params:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    adj_sorted = sorted(fund_adj, key=lambda spec: dict(spec.parameters).get("start_date", ""))
    if dict(adj_sorted[0].parameters).get("start_date") != history.start.strftime("%Y%m%d"):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if dict(adj_sorted[-1].parameters).get("end_date") != history.end.strftime("%Y%m%d"):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    for spec in adj_sorted:
        params = dict(spec.parameters)
        if params.get("ts_code") != _BENCHMARK:
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")

    # HISTORY-H1/H3: each history_symbol has exactly one full-window suspend_d.
    suspend_specs = [spec for spec in history_specs if spec.endpoint == "suspend_d"]
    if len(suspend_specs) != len(history_symbols):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    start_text = history.start.strftime("%Y%m%d")
    end_text = history.end.strftime("%Y%m%d")
    for symbol in history_symbols:
        matches = [
            spec
            for spec in suspend_specs
            if dict(spec.parameters).get("ts_code") == symbol
        ]
        if len(matches) != 1:
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
        params = dict(matches[0].parameters)
        if params.get("start_date") != start_text:
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
        if params.get("end_date") != end_text:
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
        if params.get("suspend_type") != "S":
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    weight_months = {
        (dict(spec.parameters)["start_date"], dict(spec.parameters)["end_date"])
        for spec in plan.index_weight_batch.requests
    }
    if not weight_months:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    _ = by_id  # closure already rebuilt


def _symbol_lineage(
    responses: Sequence[VerifiedRawResponse], *, date_param: bool
) -> dict[str, tuple[dt.date, dt.date, str, str]]:
    out: dict[str, tuple[dt.date, dt.date, str, str]] = {}
    for item in responses:
        params = dict(item.spec.parameters)
        symbol = params.get("ts_code")
        if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        if symbol in out:
            raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
        if date_param:
            start = _parse_date8(params.get("start_date"))
            end = _parse_date8(params.get("end_date"))
        else:
            start = dt.date.min
            end = dt.date.max
        out[symbol] = (
            start,
            end,
            item.spec.request_id,
            item.receipt.stable_response_sha256,
        )
    return out


def _project_receipt(response: VerifiedRawResponse) -> G1ReceiptProjectionV1:
    return G1ReceiptProjectionV1(
        source="tushare",
        request_id=response.spec.request_id,
        endpoint=response.spec.endpoint,
        parameters_sha256=response.receipt.parameters_sha256,
        stable_response_sha256=response.receipt.stable_response_sha256,
        row_count=response.receipt.row_count,
        columns=response.receipt.columns,
    )


def _project_cninfo_corporate_action_receipt(
    response: VerifiedCninfoCorporateActionRawResponse,
) -> G1ReceiptProjectionV1:
    return G1ReceiptProjectionV1(
        source="cninfo",
        request_id=response.spec.request_id,
        endpoint=response.spec.endpoint,
        parameters_sha256=response.receipt.parameters_sha256,
        stable_response_sha256=response.receipt.stable_response_sha256,
        row_count=response.receipt.row_count,
        columns=response.receipt.columns,
    )


def _assert_cninfo_corporate_action_response_multiset(
    batch: object, responses: Sequence[VerifiedCninfoCorporateActionRawResponse]
) -> None:
    from quant.data.m3_backfill import CninfoCorporateActionRequestBatch

    if type(batch) is not CninfoCorporateActionRequestBatch:
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    plan_ids = [spec.request_id for spec in batch.requests]
    response_ids = [item.spec.request_id for item in responses]
    if Counter(plan_ids) != Counter(response_ids):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if len(set(response_ids)) != len(response_ids):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    by_id = {item.spec.request_id: item for item in responses}
    for spec in batch.requests:
        verified = by_id[spec.request_id]
        if (
            verified.spec.request_id != spec.request_id
            or verified.spec.endpoint != spec.endpoint
            or verified.spec.parameters != spec.parameters
            or verified.spec.adapter != spec.adapter
        ):
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")


def _consume_cninfo_corporate_action_responses(
    responses: object,
) -> tuple[VerifiedCninfoCorporateActionRawResponse, ...]:
    if not isinstance(responses, tuple):
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    rebuilt: list[VerifiedCninfoCorporateActionRawResponse] = []
    for item in responses:
        if type(item) is not VerifiedCninfoCorporateActionRawResponse:
            raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
        rebuilt.append(
            VerifiedCninfoCorporateActionRawResponse(
                spec=item.spec,
                receipt=item.receipt,
                receipt_sha256=item.receipt_sha256,
                frame=item.frame,
                resultcode=item.resultcode,
                resultmsg=item.resultmsg,
                count=item.count,
                total=item.total,
            )
        )
    return tuple(rebuilt)


def _project_cninfo_receipt(response: VerifiedCninfoRawResponse) -> G1ReceiptProjectionV1:
    return G1ReceiptProjectionV1(
        source="cninfo",
        request_id=response.spec.request_id,
        endpoint=response.spec.endpoint,
        parameters_sha256=response.receipt.parameters_sha256,
        stable_response_sha256=response.receipt.stable_response_sha256,
        row_count=response.receipt.row_count,
        columns=response.receipt.columns,
    )


def _assert_cninfo_response_multiset(
    plan: G1RequestPlan, responses: Sequence[VerifiedCninfoRawResponse]
) -> None:
    plan_ids = [spec.request_id for spec in plan.cninfo_rights_batch.requests]
    response_ids = [item.spec.request_id for item in responses]
    if Counter(plan_ids) != Counter(response_ids):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    if len(set(response_ids)) != len(response_ids):
        raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")
    by_id = {item.spec.request_id: item for item in responses}
    for spec in plan.cninfo_rights_batch.requests:
        verified = by_id[spec.request_id]
        if (
            verified.spec.request_id != spec.request_id
            or verified.spec.endpoint != spec.endpoint
            or verified.spec.parameters != spec.parameters
            or verified.spec.adapter != spec.adapter
        ):
            raise M3G1CandidateError("G1_CANDIDATE_PLAN_RESPONSE_MISMATCH")


def _consume_cninfo_responses(
    responses: object,
) -> tuple[VerifiedCninfoRawResponse, ...]:
    if not isinstance(responses, tuple):
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    rebuilt: list[VerifiedCninfoRawResponse] = []
    for item in responses:
        if type(item) is not VerifiedCninfoRawResponse:
            raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
        rebuilt.append(
            VerifiedCninfoRawResponse(
                spec=item.spec,
                receipt=item.receipt,
                receipt_sha256=item.receipt_sha256,
                frame=item.frame,
                resultcode=item.resultcode,
                count=item.count,
                total=item.total,
            )
        )
    return tuple(rebuilt)


def _primary_candidate_key(
    *,
    build_spec: G1BuildSpec,
    request_plan_sha256: str,
    signal_start: dt.date,
    signal_end: dt.date,
    history_start: dt.date,
    history_end: dt.date,
    input_receipts: tuple[G1ReceiptProjectionV1, ...],
    table_content_digests: tuple[tuple[str, str], ...],
    price_limit_required_keys_sha256: str,
) -> str:
    payload = {
        "schema_version": _IDENTITY_SCHEMA,
        "build_spec": {
            "config_version": build_spec.config_version,
            "g1_config_sha256": build_spec.g1_config_sha256,
            "mapper_version": build_spec.mapper_version,
            "schema_version": build_spec.schema_version,
            "membership_method_version": build_spec.membership_method_version,
            "price_limit_method_version": build_spec.price_limit_method_version,
            "corporate_action_selection_version": (
                build_spec.corporate_action_selection_version
            ),
            "corporate_action_reconciliation_version": (
                build_spec.corporate_action_reconciliation_version
            ),
            "benchmark_mode": build_spec.benchmark_mode,
            "benchmark_method_version": build_spec.benchmark_method_version,
            "benchmark_dividend_reconciliation_version": (
                build_spec.benchmark_dividend_reconciliation_version
            ),
            "build_code_version": build_spec.build_code_version,
            "dependency_fingerprint_sha256": build_spec.dependency_fingerprint_sha256,
        },
        "request_plan_sha256": request_plan_sha256,
        "signal_start": signal_start.isoformat(),
        "signal_end": signal_end.isoformat(),
        "history_start": history_start.isoformat(),
        "history_end": history_end.isoformat(),
        "input_receipts": [asdict(item) for item in input_receipts],
        "table_content_digests": [list(item) for item in table_content_digests],
        "price_limit_required_keys_sha256": price_limit_required_keys_sha256,
    }
    return _sha256_json(payload)


def _consume_build_inputs(inputs: object) -> G1BuildInputs:
    if type(inputs) is not G1BuildInputs:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    return G1BuildInputs(
        build_spec=inputs.build_spec,
        request_plan=inputs.request_plan,
        responses=inputs.responses,
        cninfo_responses=inputs.cninfo_responses,
        cninfo_dividend_responses=inputs.cninfo_dividend_responses,
        cninfo_share_change_responses=inputs.cninfo_share_change_responses,
        calendars=inputs.calendars,
        instruments=inputs.instruments,
        universe=inputs.universe,
        signal_start=inputs.signal_start,
        signal_end=inputs.signal_end,
        history=inputs.history,
        expected_constituent_count=inputs.expected_constituent_count,
        factor_ratio_rtol=inputs.factor_ratio_rtol,
    )


def _consume_build_spec(spec: object) -> G1BuildSpec:
    if type(spec) is not G1BuildSpec:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    try:
        return G1BuildSpec(
            config_version=spec.config_version,
            g1_config_sha256=spec.g1_config_sha256,
            mapper_version=spec.mapper_version,
            schema_version=spec.schema_version,
            membership_method_version=spec.membership_method_version,
            price_limit_method_version=spec.price_limit_method_version,
            corporate_action_selection_version=spec.corporate_action_selection_version,
            corporate_action_reconciliation_version=(
                spec.corporate_action_reconciliation_version
            ),
            benchmark_mode=spec.benchmark_mode,
            benchmark_method_version=spec.benchmark_method_version,
            benchmark_dividend_reconciliation_version=(
                spec.benchmark_dividend_reconciliation_version
            ),
            build_code_version=spec.build_code_version,
            dependency_fingerprint_sha256=spec.dependency_fingerprint_sha256,
        )
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID") from None


def _consume_request_plan(plan: object) -> G1RequestPlan:
    if type(plan) is not G1RequestPlan:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    try:
        return G1RequestPlan(
            plan.schema_version,
            plan.index_weight_batch,
            plan.history_batch,
            plan.cninfo_rights_batch,
            plan.cninfo_dividend_batch,
            plan.cninfo_share_change_batch,
            plan.plan_sha256,
        )
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID") from None


def _consume_history(history: object) -> HistoryWindow:
    if type(history) is not HistoryWindow:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    try:
        return HistoryWindow(history.start, history.end)
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID") from None


def _consume_responses(
    responses: object,
) -> tuple[VerifiedRawResponse, ...]:
    if type(responses) is not tuple or not responses:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    out: list[VerifiedRawResponse] = []
    for item in responses:
        out.append(_consume_verified(item))
    return tuple(out)


def _consume_verified(response: object) -> VerifiedRawResponse:
    if type(response) is not VerifiedRawResponse:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    try:
        return VerifiedRawResponse(
            response.spec,
            response.receipt,
            response.receipt_sha256,
            response.frame,
        )
    except Exception:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID") from None


def _validate_rtol(value: object) -> float:
    if type(value) is bool or type(value) is not float:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    if not math.isfinite(value) or value < 0.0 or value > 0.01:
        raise M3G1CandidateError("G1_CANDIDATE_INPUT_INVALID")
    return value


def _validate_digest_table(digests: object) -> None:
    if type(digests) is not tuple or len(digests) != len(_TABLE_NAMES):
        raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
    names: list[str] = []
    for item in digests:
        if type(item) is not tuple or len(item) != 2:
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        name, digest = item
        if type(name) is not str or type(digest) is not str or not _HEX64.fullmatch(digest):
            raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")
        names.append(name)
    if tuple(names) != _TABLE_NAMES:
        raise M3G1CandidateError("G1_CANDIDATE_IDENTITY_MISMATCH")


def _validate_schema(frame: pl.DataFrame, schema: Any, code: str) -> pl.DataFrame:
    try:
        return schema.validate(frame)
    except Exception:
        raise M3G1CandidateError(code) from None


def _concat_or_empty(
    parts: Sequence[pl.DataFrame],
    *,
    schema: Mapping[str, Any],
    sort_keys: Sequence[str],
    schema_model: Any,
) -> pl.DataFrame:
    if not parts:
        frame = pl.DataFrame(schema=dict(schema))
    else:
        nonempty = [part for part in parts if part.height]
        frame = pl.concat(nonempty) if nonempty else parts[0]
    frame = frame.select(list(schema)).sort(list(sort_keys))
    return schema_model.validate(frame)


def _frames_equal(left: pl.DataFrame, right: pl.DataFrame) -> bool:
    if list(left.columns) != list(right.columns):
        return False
    if left.height != right.height:
        return False
    return left.sort(left.columns).equals(right.sort(right.columns))


def _parse_date8(value: object) -> dt.date:
    if type(value) is not str or len(value) != 8 or not value.isdigit():
        raise M3G1CandidateError("G1_CANDIDATE_COMPONENT_INVALID")
    return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def _audit_scoped_factor_reconciliation_topology(
    *,
    adjustment_factors: pl.DataFrame,
    reconciliation: pl.DataFrame,
) -> G1QualityIssue | None:
    """Bind evidence keys/ratios to immediate adjacent scoped factor transitions.

    Returns a mismatch issue, or None when topology, row count and exact ratios
    match. Never raises: read/compute failures become the same stable issue.
    """
    mismatch_message = "scoped factor transition topology mismatch"
    try:
        factors = adjustment_factors.sort(["symbol", "effective_date"])
        series_by_symbol: dict[str, list[tuple[dt.date, float]]] = {}
        for row in factors.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["effective_date"]
            factor = float(row["adj_factor"])
            if type(symbol) is not str or type(day) is not dt.date:
                return _issue(
                    "CORPORATE_ACTION_FACTOR_MISMATCH",
                    mismatch_message,
                    1,
                    (),
                )
            if not math.isfinite(factor) or factor <= 0:
                return _issue(
                    "CORPORATE_ACTION_FACTOR_MISMATCH",
                    mismatch_message,
                    1,
                    (),
                )
            series_by_symbol.setdefault(symbol, []).append((day, factor))

        expected_keys: set[tuple[str, dt.date, dt.date]] = set()
        expected_ratios: dict[tuple[str, dt.date, dt.date], float] = {}
        expected_rows = 0
        for symbol, series in series_by_symbol.items():
            expected_rows += max(len(series) - 1, 0)
            for index in range(1, len(series)):
                previous_factor_date, previous_factor = series[index - 1]
                effective_date, effective_factor = series[index]
                key = (symbol, previous_factor_date, effective_date)
                expected_keys.add(key)
                expected_ratios[key] = effective_factor / previous_factor

        actual_keys: set[tuple[str, dt.date, dt.date]] = set()
        mismatch_count = 0
        evidence_rows = list(reconciliation.iter_rows(named=True))
        if len(evidence_rows) != expected_rows:
            mismatch_count += 1
        for row in evidence_rows:
            key = (
                row["symbol"],
                row["previous_factor_date"],
                row["effective_date"],
            )
            if key in actual_keys:
                mismatch_count += 1
            actual_keys.add(key)
            expected_ratio = expected_ratios.get(key)
            if expected_ratio is None:
                mismatch_count += 1
                continue
            actual_ratio = float(row["actual_factor_ratio"])
            # Exact Float64 identity bind; no business rtol slack.
            if actual_ratio != expected_ratio:
                mismatch_count += 1
        if actual_keys != expected_keys:
            mismatch_count += 1
        if mismatch_count == 0:
            return None
        return _issue(
            "CORPORATE_ACTION_FACTOR_MISMATCH",
            mismatch_message,
            mismatch_count,
            (),
        )
    except Exception:
        return _issue(
            "CORPORATE_ACTION_FACTOR_MISMATCH",
            mismatch_message,
            1,
            (),
        )


def _issue(
    code: str, message: str, count: int, evidence: tuple[str, ...]
) -> G1QualityIssue:
    return G1QualityIssue(
        code=code,
        severity="ERROR",
        message=message,
        count=count,
        evidence=tuple(sorted(evidence)),
    )


def _audit_result(
    *, candidate: G1Candidate | None, issues: Sequence[G1QualityIssue]
) -> G1PrimaryAuditResult:
    ordered = tuple(
        sorted(
            issues,
            key=lambda item: (item.severity, item.code, item.message, item.evidence),
        )
    )
    if candidate is None:
        empty_key = "0" * 64
        return G1PrimaryAuditResult(
            primary_candidate_key=empty_key,
            plan_sha256=empty_key,
            input_receipts=(),
            table_content_digests=tuple((name, empty_key) for name in _TABLE_NAMES),
            issues=ordered,
            passed=len(ordered) == 0,
        )
    return G1PrimaryAuditResult(
        primary_candidate_key=candidate.primary_candidate_key,
        plan_sha256=candidate.request_plan.plan_sha256,
        input_receipts=candidate.input_receipts,
        table_content_digests=candidate.table_content_digests,
        issues=ordered,
        passed=len(ordered) == 0,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
