"""M3 G1-P4B: BaoStock reference evidence and cross-source reconciliation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping, Sequence

import polars as pl

from quant.data._journal_lock import M3JournalLockError, hold_journal_writer_lock
from quant.data.connectors.baostock import BaostockConnector
from quant.data.m3_g1_candidate import (
    G1Candidate,
    G1QualityIssue,
    G1ReceiptProjectionV1,
    audit_g1_candidate,
)
from quant.data.m3_identity import clean_table_content_sha256
from quant.data.storage import RawStore

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_A_SHARE = re.compile(r"^\d{6}\.(SH|SZ)$")
_ENDPOINT: Literal["query_history_k_data_plus"] = "query_history_k_data_plus"
_FIELDS = "date,code,open,high,low,close,volume,amount,adjustflag,tradestatus"
_FIELD_COLUMNS = tuple(_FIELDS.split(","))
_COMPARE_FIELDS = ("open", "high", "low", "close", "volume")
_SAMPLE_SCHEMA: Literal["m3-g1-cross-source-sample-v1"] = "m3-g1-cross-source-sample-v1"
_REQUEST_SCHEMA: Literal["m3-g1-baostock-request-v1"] = "m3-g1-baostock-request-v1"
_PLAN_SCHEMA: Literal["m3-g1-baostock-request-plan-v1"] = "m3-g1-baostock-request-plan-v1"
_INTENT_SCHEMA: Literal["m3-g1-baostock-intent-v1"] = "m3-g1-baostock-intent-v1"
_CANDIDATE_SCHEMA: Literal["m3-g1-baostock-candidate-v1"] = "m3-g1-baostock-candidate-v1"
_RECEIPT_SCHEMA: Literal["m3-g1-baostock-receipt-v1"] = "m3-g1-baostock-receipt-v1"
_SUMMARY_SCHEMA: Literal["m3-g1-cross-source-v1"] = "m3-g1-cross-source-v1"
_ROW_LIMIT = 6000
_SAMPLE_SYMBOLS = 30
_DATES_PER_SYMBOL = 20
_KEY_COUNT = 600
_FIELD_COUNT = 5
_COMPARISON_COUNT = 3000
_JOURNAL_FILES = frozenset({"intent.json", "candidate.json", "receipt.json"})
_ERROR_CODES = frozenset(
    {
        "G1_REFERENCE_INPUT_INVALID",
        "G1_REFERENCE_IDENTITY_MISMATCH",
        "G1_REFERENCE_PLAN_INVALID",
        "G1_REFERENCE_JOURNAL_INVALID",
        "G1_REFERENCE_IO_FAILED",
        "G1_REFERENCE_NETWORK_FAILED",
        "G1_REFERENCE_RESPONSE_INVALID",
        "G1_REFERENCE_RECEIPT_INVALID",
        "G1_CROSS_SOURCE_RECONCILIATION_INVALID",
    }
)
_DETAIL_COLUMNS = (
    "symbol",
    "trade_date",
    "field",
    "primary_value",
    "reference_value",
    "abs_diff",
    "relative_diff",
    "tolerance",
    "missing_side",
    "matched",
)


class M3ReferenceError(ValueError):
    """Stable P4B boundary error; ``str(error)`` equals ``code``."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown g1 reference error code")
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"M3ReferenceError({self.code!r})"


@dataclass(frozen=True)
class G1CrossSourcePolicy:
    reference_source: Literal["baostock"]
    sample_symbols: Literal[30]
    dates_per_symbol: Literal[20]
    price_atol: float
    price_rtol: float
    volume_rtol: float
    max_mismatch_rate: float

    def __post_init__(self) -> None:
        if self.reference_source != "baostock":
            raise ValueError("policy reference_source 非法")
        if type(self.sample_symbols) is not int or self.sample_symbols != _SAMPLE_SYMBOLS:
            raise ValueError("policy sample_symbols 非法")
        if type(self.dates_per_symbol) is not int or self.dates_per_symbol != _DATES_PER_SYMBOL:
            raise ValueError("policy dates_per_symbol 非法")
        if (
            type(self.price_atol) is not float
            or not math.isfinite(self.price_atol)
            or self.price_atol < 0.0
        ):
            raise ValueError("policy price_atol 非法")
        for name in ("price_rtol", "volume_rtol", "max_mismatch_rate"):
            value = getattr(self, name)
            if type(value) is not float or not math.isfinite(value) or not (0.0 <= value <= 1.0):
                raise ValueError(f"policy {name} 非法")


@dataclass(frozen=True)
class CrossSourceSamplePlan:
    schema_version: Literal["m3-g1-cross-source-sample-v1"]
    primary_candidate_key: str
    sample_symbols: Literal[30]
    dates_per_symbol: Literal[20]
    keys: tuple[tuple[str, dt.date], ...]
    sample_plan_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _SAMPLE_SCHEMA:
            raise ValueError("sample plan schema_version 非法")
        if type(self.primary_candidate_key) is not str or not _HEX64.fullmatch(
            self.primary_candidate_key
        ):
            raise ValueError("sample plan primary_candidate_key 非法")
        if type(self.sample_symbols) is not int or self.sample_symbols != _SAMPLE_SYMBOLS:
            raise ValueError("sample plan sample_symbols 非法")
        if type(self.dates_per_symbol) is not int or self.dates_per_symbol != _DATES_PER_SYMBOL:
            raise ValueError("sample plan dates_per_symbol 非法")
        if type(self.keys) is not tuple or len(self.keys) != _KEY_COUNT:
            raise ValueError("sample plan keys 数量非法")
        by_symbol: dict[str, list[dt.date]] = {}
        for item in self.keys:
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("sample plan key 结构非法")
            symbol, day = item
            if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
                raise ValueError("sample plan symbol 非法")
            if type(day) is not dt.date:
                raise ValueError("sample plan date 非法")
            by_symbol.setdefault(symbol, []).append(day)
        if self.keys != tuple(sorted(self.keys, key=lambda kv: (kv[0], kv[1]))):
            raise ValueError("sample plan keys 必须排序")
        if len(by_symbol) != self.sample_symbols:
            raise ValueError("sample plan symbol 数量非法")
        for _, days in by_symbol.items():
            if len(days) != self.dates_per_symbol or len(set(days)) != len(days):
                raise ValueError("sample plan 每证券日期数量非法")
        if type(self.sample_plan_sha256) is not str or not _HEX64.fullmatch(
            self.sample_plan_sha256
        ):
            raise ValueError("sample plan sample_plan_sha256 非法")
        expected = _sample_plan_sha256(
            primary_candidate_key=self.primary_candidate_key,
            sample_symbols=self.sample_symbols,
            dates_per_symbol=self.dates_per_symbol,
            keys=self.keys,
        )
        if expected != self.sample_plan_sha256:
            raise ValueError("sample plan sample_plan_sha256 不一致")


@dataclass(frozen=True)
class ReferenceRequestSpec:
    schema_version: Literal["m3-g1-baostock-request-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != _REQUEST_SCHEMA:
            raise ValueError("request schema_version 非法")
        if self.endpoint != _ENDPOINT:
            raise ValueError("request endpoint 非法")
        if type(self.symbol) is not str or not _A_SHARE.fullmatch(self.symbol):
            raise ValueError("request symbol 非法")
        _validate_parameters(self.parameters)
        params = dict(self.parameters)
        if set(params) != {"fields", "frequency", "adjustflag", "start_date", "end_date"}:
            raise ValueError("request parameters 字段集合非法")
        if (
            params["fields"] != _FIELDS
            or params["frequency"] != "d"
            or params["adjustflag"] != "3"
        ):
            raise ValueError("request parameters 契约非法")
        start = _validate_iso_date(params["start_date"])
        end = _validate_iso_date(params["end_date"])
        if start > end:
            raise ValueError("request 日期范围非法")
        if type(self.request_id) is not str or not _HEX64.fullmatch(self.request_id):
            raise ValueError("request_id 非法")
        expected = _request_id(symbol=self.symbol, parameters=self.parameters)
        if self.request_id != expected:
            raise ValueError("request_id 与 symbol/parameters 不一致")


@dataclass(frozen=True)
class ReferenceRequestPlanV1:
    schema_version: Literal["m3-g1-baostock-request-plan-v1"]
    sample_plan_sha256: str
    requests: tuple[ReferenceRequestSpec, ...]
    request_plan_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != _PLAN_SCHEMA:
            raise ValueError("plan schema_version 非法")
        if type(self.sample_plan_sha256) is not str or not _HEX64.fullmatch(
            self.sample_plan_sha256
        ):
            raise ValueError("plan sample_plan_sha256 非法")
        if type(self.requests) is not tuple or len(self.requests) != _SAMPLE_SYMBOLS:
            raise ValueError("plan requests 数量非法")
        rebuilt: list[ReferenceRequestSpec] = []
        for item in self.requests:
            if type(item) is not ReferenceRequestSpec:
                raise ValueError("plan requests 类型非法")
            rebuilt.append(
                ReferenceRequestSpec(
                    item.schema_version, item.request_id, item.endpoint, item.symbol,
                    item.parameters,
                )
            )
        ordered = tuple(sorted(rebuilt, key=lambda value: value.request_id))
        if tuple(rebuilt) != ordered:
            raise ValueError("plan requests 必须按 request_id 排序")
        if len({item.request_id for item in rebuilt}) != len(rebuilt):
            raise ValueError("plan requests request_id 必须唯一")
        if len({item.symbol for item in rebuilt}) != len(rebuilt):
            raise ValueError("plan requests symbol 必须唯一")
        object.__setattr__(self, "requests", tuple(rebuilt))
        if self.request_plan_sha256 != _request_plan_sha256(
            sample_plan_sha256=self.sample_plan_sha256, requests=self.requests
        ):
            raise ValueError("plan request_plan_sha256 不一致")


@dataclass(frozen=True)
class ReferenceRequestIntentV1:
    schema_version: Literal["m3-g1-baostock-intent-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

    def __post_init__(self) -> None:
        spec = ReferenceRequestSpec(
            _REQUEST_SCHEMA, self.request_id, self.endpoint, self.symbol, self.parameters
        )
        if self.schema_version != _INTENT_SCHEMA:
            raise ValueError("intent schema_version 非法")
        if self.parameters_sha256 != _parameters_hash(spec.parameters):
            raise ValueError("intent parameters_sha256 不一致")


@dataclass(frozen=True)
class ReferenceRawCandidateV1:
    schema_version: Literal["m3-g1-baostock-candidate-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _CANDIDATE_SCHEMA:
            raise ValueError("candidate schema_version 非法")
        if self.endpoint != _ENDPOINT:
            raise ValueError("candidate endpoint 非法")
        if type(self.symbol) is not str or not _A_SHARE.fullmatch(self.symbol):
            raise ValueError("candidate symbol 非法")
        if type(self.request_id) is not str or not _HEX64.fullmatch(self.request_id):
            raise ValueError("candidate request_id 非法")
        for value in (
            self.parameters_sha256,
            self.raw_snapshot_id,
            self.raw_file_sha256,
            self.raw_metadata_sha256,
            self.response_content_sha256,
        ):
            _validate_hex(value)
        if self.raw_snapshot_id != self.request_id:
            raise ValueError("candidate raw_snapshot_id 与 request_id 不一致")
        _validate_relative(self.raw_data_path)
        _validate_relative(self.raw_metadata_path)
        _validate_counts(self.raw_size_bytes, self.row_count, self.columns)
        if self.columns != _FIELD_COLUMNS:
            raise ValueError("candidate columns 非法")


@dataclass(frozen=True)
class ReferenceRequestReceipt:
    schema_version: Literal["m3-g1-baostock-receipt-v1"]
    request_id: str
    endpoint: Literal["query_history_k_data_plus"]
    symbol: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    stable_response_sha256: str
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        spec = ReferenceRequestSpec(
            _REQUEST_SCHEMA, self.request_id, self.endpoint, self.symbol, self.parameters
        )
        if self.schema_version != _RECEIPT_SCHEMA:
            raise ValueError("receipt schema_version 非法")
        if self.parameters_sha256 != _parameters_hash(spec.parameters):
            raise ValueError("receipt parameters_sha256 不一致")
        for value in (
            self.raw_snapshot_id,
            self.raw_file_sha256,
            self.raw_metadata_sha256,
            self.response_content_sha256,
            self.stable_response_sha256,
        ):
            _validate_hex(value)
        if self.raw_snapshot_id != self.request_id:
            raise ValueError("receipt raw_snapshot_id 与 request_id 不一致")
        _validate_relative(self.raw_data_path)
        _validate_relative(self.raw_metadata_path)
        _validate_counts(self.raw_size_bytes, self.row_count, self.columns)
        if self.columns != _FIELD_COLUMNS:
            raise ValueError("receipt columns 非法")
        if self.stable_response_sha256 != _stable_response_hash(self):
            raise ValueError("receipt stable_response_sha256 不一致")


@dataclass(frozen=True)
class VerifiedReferenceResponse:
    spec: ReferenceRequestSpec
    receipt: ReferenceRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame

    def __post_init__(self) -> None:
        if type(self.spec) is not ReferenceRequestSpec or type(
            self.receipt
        ) is not ReferenceRequestReceipt:
            raise ValueError("verified reference spec/receipt 类型非法")
        rebuilt_spec = ReferenceRequestSpec(
            self.spec.schema_version, self.spec.request_id, self.spec.endpoint,
            self.spec.symbol, self.spec.parameters,
        )
        rebuilt_receipt = ReferenceRequestReceipt(**asdict(self.receipt))
        if (
            rebuilt_receipt.request_id != rebuilt_spec.request_id
            or rebuilt_receipt.endpoint != rebuilt_spec.endpoint
            or rebuilt_receipt.symbol != rebuilt_spec.symbol
            or rebuilt_receipt.parameters != rebuilt_spec.parameters
        ):
            raise ValueError("verified reference spec/receipt 不一致")
        if type(self.receipt_sha256) is not str or not _HEX64.fullmatch(self.receipt_sha256):
            raise ValueError("verified reference receipt_sha256 非法")
        expected_receipt_hash = _sha256_json(asdict(rebuilt_receipt))
        if self.receipt_sha256 != expected_receipt_hash:
            raise ValueError("verified reference receipt_sha256 不一致")
        if not isinstance(self.frame, pl.DataFrame):
            raise ValueError("verified reference frame 类型非法")
        if (
            self.frame.height != rebuilt_receipt.row_count
            or tuple(self.frame.columns) != rebuilt_receipt.columns
        ):
            raise ValueError("verified reference frame/receipt 不一致")
        if (
            _reference_response_content_sha256(self.frame)
            != rebuilt_receipt.response_content_sha256
        ):
            raise ValueError("verified reference frame content digest 不一致")
        object.__setattr__(self, "spec", rebuilt_spec)
        object.__setattr__(self, "receipt", rebuilt_receipt)


@dataclass(frozen=True)
class CrossSourceFieldStatsV1:
    field: Literal["open", "high", "low", "close", "volume"]
    comparison_count: int
    mismatch_count: int
    max_abs_diff: float
    max_relative_diff: float

    def __post_init__(self) -> None:
        if self.field not in _COMPARE_FIELDS:
            raise ValueError("field stats field 非法")
        if type(self.comparison_count) is not int or self.comparison_count != _KEY_COUNT:
            raise ValueError("field stats comparison_count 非法")
        if (
            type(self.mismatch_count) is not int
            or self.mismatch_count < 0
            or self.mismatch_count > self.comparison_count
        ):
            raise ValueError("field stats mismatch_count 非法")
        for name in ("max_abs_diff", "max_relative_diff"):
            value = getattr(self, name)
            if type(value) is not float or not math.isfinite(value) or value < 0.0:
                raise ValueError(f"field stats {name} 非法")


@dataclass(frozen=True)
class CrossSourceSummaryV1:
    schema_version: Literal["m3-g1-cross-source-v1"]
    primary_candidate_key: str
    sample_plan_sha256: str
    sample_symbol_count: int
    dates_per_symbol: int
    key_count: int
    field_count: int
    comparison_count: int
    primary_receipt_digests: tuple[str, ...]
    reference_receipt_digests: tuple[str, ...]
    price_atol: float
    price_rtol: float
    volume_rtol: float
    max_mismatch_rate: float
    missing_primary_rows: int
    missing_reference_rows: int
    mismatch_cells: int
    mismatch_rate: float
    field_stats: tuple[CrossSourceFieldStatsV1, ...]
    detail_sha256: str
    passed: bool

    def __post_init__(self) -> None:
        if self.schema_version != _SUMMARY_SCHEMA:
            raise ValueError("summary schema_version 非法")
        if type(self.primary_candidate_key) is not str or not _HEX64.fullmatch(
            self.primary_candidate_key
        ):
            raise ValueError("summary primary_candidate_key 非法")
        if type(self.sample_plan_sha256) is not str or not _HEX64.fullmatch(
            self.sample_plan_sha256
        ):
            raise ValueError("summary sample_plan_sha256 非法")
        int_fields = {
            "sample_symbol_count": _SAMPLE_SYMBOLS,
            "dates_per_symbol": _DATES_PER_SYMBOL,
            "key_count": _KEY_COUNT,
            "field_count": _FIELD_COUNT,
            "comparison_count": _COMPARISON_COUNT,
        }
        for name, expected in int_fields.items():
            value = getattr(self, name)
            if type(value) is not int or value != expected:
                raise ValueError(f"summary {name} 非法")
        for name in ("primary_receipt_digests", "reference_receipt_digests"):
            value = getattr(self, name)
            if type(value) is not tuple or any(
                type(item) is not str or not _HEX64.fullmatch(item) for item in value
            ):
                raise ValueError(f"summary {name} 非法")
            if value != tuple(sorted(set(value))):
                raise ValueError(f"summary {name} 必须排序且唯一")
        if (
            type(self.price_atol) is not float
            or not math.isfinite(self.price_atol)
            or self.price_atol < 0.0
        ):
            raise ValueError("summary price_atol 非法")
        for name in ("price_rtol", "volume_rtol", "max_mismatch_rate"):
            value = getattr(self, name)
            if type(value) is not float or not math.isfinite(value) or not (0.0 <= value <= 1.0):
                raise ValueError(f"summary {name} 非法")
        for name in ("missing_primary_rows", "missing_reference_rows", "mismatch_cells"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"summary {name} 非法")
        if self.mismatch_cells > self.comparison_count:
            raise ValueError("summary mismatch_cells 超过 comparison_count")
        if type(self.mismatch_rate) is not float or not math.isfinite(self.mismatch_rate) or (
            self.mismatch_rate < 0.0
        ):
            raise ValueError("summary mismatch_rate 非法")
        if abs(self.mismatch_rate - self.mismatch_cells / self.comparison_count) > 1e-12:
            raise ValueError("summary mismatch_rate 与 mismatch_cells 不一致")
        if type(self.field_stats) is not tuple or len(self.field_stats) != len(_COMPARE_FIELDS):
            raise ValueError("summary field_stats 数量非法")
        rebuilt_stats: list[CrossSourceFieldStatsV1] = []
        for item in self.field_stats:
            if type(item) is not CrossSourceFieldStatsV1:
                raise ValueError("summary field_stats 元素类型非法")
            rebuilt_stats.append(
                CrossSourceFieldStatsV1(
                    item.field, item.comparison_count, item.mismatch_count,
                    item.max_abs_diff, item.max_relative_diff,
                )
            )
        if tuple(item.field for item in rebuilt_stats) != _COMPARE_FIELDS:
            raise ValueError("summary field_stats 顺序非法")
        if sum(item.mismatch_count for item in rebuilt_stats) != self.mismatch_cells:
            raise ValueError("summary field_stats mismatch 总数不一致")
        if sum(item.comparison_count for item in rebuilt_stats) != self.comparison_count:
            raise ValueError("summary field_stats comparison 总数不一致")
        object.__setattr__(self, "field_stats", tuple(rebuilt_stats))
        if type(self.detail_sha256) is not str or not _HEX64.fullmatch(self.detail_sha256):
            raise ValueError("summary detail_sha256 非法")
        if type(self.passed) is not bool:
            raise ValueError("summary passed 必须是 bool")


def _validate_present_side_value(field: str, value: object) -> None:
    if type(value) is not float:
        raise ValueError("bundle detail 现存侧数值类型非法")
    if not math.isfinite(value):
        raise ValueError("bundle detail 现存侧数值非 finite")
    if field == "volume":
        if value < 0.0:
            raise ValueError("bundle detail volume 非法")
    elif value <= 0.0:
        raise ValueError("bundle detail 价格非法")


_INCOMPLETE_MESSAGE = "cross-source sample row missing primary or reference bar"
_MISMATCH_MESSAGE = "cross-source mismatch rate exceeds policy threshold"
_RATE_EPS = 1e-12


@dataclass(frozen=True)
class _DetailDerivedClosure:
    detail_sha256: str
    missing_primary_rows: int
    missing_reference_rows: int
    mismatch_cells: int
    mismatch_rate: float
    field_stats: tuple[CrossSourceFieldStatsV1, ...]
    issues: tuple[G1QualityIssue, ...]
    passed: bool


def _derive_cross_source_from_detail(
    *,
    detail: pl.DataFrame,
    sample_plan: CrossSourceSamplePlan,
    price_atol: float,
    price_rtol: float,
    volume_rtol: float,
    max_mismatch_rate: float,
) -> _DetailDerivedClosure:
    """Validate detail and recompute stats/issues; shared by reconcile and bundle."""
    try:
        if not isinstance(detail, pl.DataFrame):
            raise ValueError("bundle detail 类型非法")
        if list(detail.columns) != list(_DETAIL_COLUMNS):
            raise ValueError("bundle detail 列非法")
        expected_dtypes = {
            "symbol": pl.Utf8,
            "trade_date": pl.Date,
            "field": pl.Utf8,
            "primary_value": pl.Float64,
            "reference_value": pl.Float64,
            "abs_diff": pl.Float64,
            "relative_diff": pl.Float64,
            "tolerance": pl.Float64,
            "missing_side": pl.Utf8,
            "matched": pl.Boolean,
        }
        for name, dtype in zip(detail.columns, detail.dtypes, strict=True):
            if dtype != expected_dtypes[name]:
                raise ValueError("bundle detail dtype 非法")
        if detail.height != _COMPARISON_COUNT:
            raise ValueError("bundle detail 行数非法")

        expected_keys: list[tuple[str, dt.date, str]] = [
            (symbol, day, field)
            for symbol, day in sample_plan.keys
            for field in _COMPARE_FIELDS
        ]
        ordered_expected = sorted(
            expected_keys, key=lambda item: (item[0], item[1], _COMPARE_FIELDS.index(item[2]))
        )
        seen: set[tuple[str, dt.date, str]] = set()
        rows_by_key: dict[tuple[str, dt.date], list[dict[str, Any]]] = {}
        previous: tuple[str, dt.date, str] | None = None
        mismatch_cells = 0
        field_mismatch = {field: 0 for field in _COMPARE_FIELDS}
        field_max_abs = {field: 0.0 for field in _COMPARE_FIELDS}
        field_max_rel = {field: 0.0 for field in _COMPARE_FIELDS}

        for row in detail.iter_rows(named=True):
            symbol = row["symbol"]
            day = row["trade_date"]
            field = row["field"]
            if type(symbol) is not str or type(day) is not dt.date or type(field) is not str:
                raise ValueError("bundle detail 键类型非法")
            if field not in _COMPARE_FIELDS:
                raise ValueError("bundle detail field 非法")
            key3 = (symbol, day, field)
            if key3 in seen:
                raise ValueError("bundle detail 键重复")
            seen.add(key3)
            if previous is not None:
                prev_rank = (previous[0], previous[1], _COMPARE_FIELDS.index(previous[2]))
                cur_rank = (symbol, day, _COMPARE_FIELDS.index(field))
                if cur_rank < prev_rank:
                    raise ValueError("bundle detail 未规范排序")
            previous = key3
            rows_by_key.setdefault((symbol, day), []).append(row)

            missing_side = row["missing_side"]
            matched = row["matched"]
            if missing_side not in {"NONE", "PRIMARY", "REFERENCE", "BOTH"}:
                raise ValueError("bundle detail missing_side 非法")
            if type(matched) is not bool:
                raise ValueError("bundle detail matched 非法")
            primary_value = row["primary_value"]
            reference_value = row["reference_value"]
            abs_diff = row["abs_diff"]
            relative_diff = row["relative_diff"]
            tolerance = row["tolerance"]

            if missing_side == "NONE":
                if primary_value is None or reference_value is None:
                    raise ValueError("bundle detail null 组合非法")
                if abs_diff is None or relative_diff is None or tolerance is None:
                    raise ValueError("bundle detail null 组合非法")
                if type(primary_value) is not float or type(reference_value) is not float:
                    raise ValueError("bundle detail 数值类型非法")
                if type(abs_diff) is not float or type(relative_diff) is not float:
                    raise ValueError("bundle detail 数值类型非法")
                if type(tolerance) is not float:
                    raise ValueError("bundle detail 数值类型非法")
                if not all(
                    math.isfinite(value)
                    for value in (primary_value, reference_value, abs_diff, relative_diff, tolerance)
                ):
                    raise ValueError("bundle detail 数值非 finite")
                if abs_diff < 0.0 or relative_diff < 0.0 or tolerance < 0.0:
                    raise ValueError("bundle detail 差值/容差为负")
                expected_abs = abs(primary_value - reference_value)
                expected_rel = expected_abs / max(abs(reference_value), 1e-300)
                if field == "volume":
                    expected_tol = volume_rtol * max(abs(reference_value), 1.0)
                else:
                    expected_tol = price_atol + price_rtol * abs(reference_value)
                if abs(abs_diff - expected_abs) > _RATE_EPS:
                    raise ValueError("bundle detail abs_diff 不一致")
                if abs(relative_diff - expected_rel) > _RATE_EPS:
                    raise ValueError("bundle detail relative_diff 不一致")
                if abs(tolerance - expected_tol) > _RATE_EPS:
                    raise ValueError("bundle detail tolerance 不一致")
                expected_matched = expected_abs <= expected_tol
                if matched is not expected_matched:
                    raise ValueError("bundle detail matched 不一致")
                field_max_abs[field] = max(field_max_abs[field], expected_abs)
                field_max_rel[field] = max(field_max_rel[field], expected_rel)
            else:
                if abs_diff is not None or relative_diff is not None:
                    raise ValueError("bundle detail null 组合非法")
                if type(tolerance) is not float or not math.isfinite(tolerance) or tolerance != 0.0:
                    raise ValueError("bundle detail tolerance 非法")
                if matched is not False:
                    raise ValueError("bundle detail matched 不一致")
                if missing_side == "PRIMARY":
                    if primary_value is not None or reference_value is None:
                        raise ValueError("bundle detail null 组合非法")
                    _validate_present_side_value(field, reference_value)
                elif missing_side == "REFERENCE":
                    if reference_value is not None or primary_value is None:
                        raise ValueError("bundle detail null 组合非法")
                    _validate_present_side_value(field, primary_value)
                elif missing_side == "BOTH":
                    if primary_value is not None or reference_value is not None:
                        raise ValueError("bundle detail null 组合非法")
            if not matched:
                mismatch_cells += 1
                field_mismatch[field] += 1

        if seen != set(ordered_expected):
            raise ValueError("bundle detail 键集合非法")
        if [key3 for key3 in ordered_expected] != [
            (row["symbol"], row["trade_date"], row["field"]) for row in detail.iter_rows(named=True)
        ]:
            # Ensure exact order equals sample_plan.keys × fields order.
            actual = [
                (row["symbol"], row["trade_date"], row["field"])
                for row in detail.iter_rows(named=True)
            ]
            if actual != ordered_expected:
                raise ValueError("bundle detail 排序或键顺序非法")

        missing_primary = 0
        missing_reference = 0
        missing_evidence: list[str] = []
        for symbol, day in sample_plan.keys:
            group = rows_by_key.get((symbol, day))
            if group is None or len(group) != _FIELD_COUNT:
                raise ValueError("bundle detail 键集合非法")
            sides = {row["missing_side"] for row in group}
            if len(sides) != 1:
                raise ValueError("bundle detail missing_side 同键不一致")
            side = next(iter(sides))
            if side in {"PRIMARY", "BOTH"}:
                missing_primary += 1
            if side in {"REFERENCE", "BOTH"}:
                missing_reference += 1
            if side != "NONE":
                missing_evidence.append(f"{symbol}|{day.isoformat()}")

        mismatch_rate = mismatch_cells / float(_COMPARISON_COUNT)
        field_stats = tuple(
            CrossSourceFieldStatsV1(
                field=field,  # type: ignore[arg-type]
                comparison_count=_KEY_COUNT,
                mismatch_count=field_mismatch[field],
                max_abs_diff=field_max_abs[field],
                max_relative_diff=field_max_rel[field],
            )
            for field in _COMPARE_FIELDS
        )
        issues: list[G1QualityIssue] = []
        if missing_evidence:
            issues.append(
                G1QualityIssue(
                    code="CROSS_SOURCE_INCOMPLETE",
                    severity="ERROR",
                    message=_INCOMPLETE_MESSAGE,
                    count=missing_primary + missing_reference,
                    evidence=tuple(sorted(missing_evidence)),
                )
            )
        if mismatch_rate > max_mismatch_rate:
            issues.append(
                G1QualityIssue(
                    code="CROSS_SOURCE_MISMATCH",
                    severity="ERROR",
                    message=_MISMATCH_MESSAGE,
                    count=mismatch_cells,
                    evidence=(),
                )
            )
        ordered_issues = tuple(
            sorted(
                issues,
                key=lambda item: (item.severity, item.code, item.message, item.evidence),
            )
        )
        detail_sha256 = clean_table_content_sha256(
            table_name="cross_source_detail", frame=detail
        )
        return _DetailDerivedClosure(
            detail_sha256=detail_sha256,
            missing_primary_rows=missing_primary,
            missing_reference_rows=missing_reference,
            mismatch_cells=mismatch_cells,
            mismatch_rate=mismatch_rate,
            field_stats=field_stats,
            issues=ordered_issues,
            passed=len(ordered_issues) == 0,
        )
    except ValueError:
        raise
    except Exception:
        raise ValueError("bundle detail 非法") from None


@dataclass(frozen=True)
class CrossSourceReconciliationBundle:
    sample_plan: CrossSourceSamplePlan
    reference_receipts: tuple[G1ReceiptProjectionV1, ...]
    detail: pl.DataFrame
    detail_sha256: str
    summary: CrossSourceSummaryV1
    summary_sha256: str
    issues: tuple[G1QualityIssue, ...]
    passed: bool

    def __post_init__(self) -> None:
        if type(self.sample_plan) is not CrossSourceSamplePlan:
            raise ValueError("bundle sample_plan 类型非法")
        rebuilt_plan = CrossSourceSamplePlan(
            self.sample_plan.schema_version, self.sample_plan.primary_candidate_key,
            self.sample_plan.sample_symbols, self.sample_plan.dates_per_symbol,
            self.sample_plan.keys, self.sample_plan.sample_plan_sha256,
        )
        if type(self.reference_receipts) is not tuple:
            raise ValueError("bundle reference_receipts 类型非法")
        if len(self.reference_receipts) != _SAMPLE_SYMBOLS:
            raise ValueError("bundle reference_receipts 数量非法")
        rebuilt_receipts: list[G1ReceiptProjectionV1] = []
        for item in self.reference_receipts:
            if type(item) is not G1ReceiptProjectionV1 or item.source != "baostock":
                raise ValueError("bundle reference_receipts 元素非法")
            rebuilt_receipts.append(
                G1ReceiptProjectionV1(
                    source=item.source, request_id=item.request_id, endpoint=item.endpoint,
                    parameters_sha256=item.parameters_sha256,
                    stable_response_sha256=item.stable_response_sha256,
                    row_count=item.row_count, columns=item.columns,
                )
            )
        ordered_receipts = tuple(
            sorted(
                rebuilt_receipts, key=lambda value: (value.source, value.endpoint, value.request_id)
            )
        )
        if tuple(rebuilt_receipts) != ordered_receipts:
            raise ValueError("bundle reference_receipts 必须排序")
        if len({item.request_id for item in ordered_receipts}) != len(ordered_receipts):
            raise ValueError("bundle reference_receipts request_id 必须唯一")
        stable_digests = [item.stable_response_sha256 for item in ordered_receipts]
        if len(set(stable_digests)) != _SAMPLE_SYMBOLS:
            raise ValueError("bundle reference_receipts stable_response_sha256 必须唯一")

        if type(self.summary) is not CrossSourceSummaryV1:
            raise ValueError("bundle summary 类型非法")
        # Rebuild summary shell for exact-type validation before detail-derived compare.
        rebuilt_field_stats_list: list[CrossSourceFieldStatsV1] = []
        for stats_item in self.summary.field_stats:
            if type(stats_item) is not CrossSourceFieldStatsV1:
                raise ValueError("bundle summary field_stats 元素非法")
            rebuilt_field_stats_list.append(
                CrossSourceFieldStatsV1(
                    stats_item.field,
                    stats_item.comparison_count,
                    stats_item.mismatch_count,
                    stats_item.max_abs_diff,
                    stats_item.max_relative_diff,
                )
            )
        rebuilt_field_stats = tuple(rebuilt_field_stats_list)
        if len(rebuilt_field_stats) != _FIELD_COUNT:
            raise ValueError("bundle summary field_stats 元素非法")
        rebuilt_summary = CrossSourceSummaryV1(
            self.summary.schema_version, self.summary.primary_candidate_key,
            self.summary.sample_plan_sha256, self.summary.sample_symbol_count,
            self.summary.dates_per_symbol, self.summary.key_count, self.summary.field_count,
            self.summary.comparison_count, self.summary.primary_receipt_digests,
            self.summary.reference_receipt_digests, self.summary.price_atol,
            self.summary.price_rtol, self.summary.volume_rtol, self.summary.max_mismatch_rate,
            self.summary.missing_primary_rows, self.summary.missing_reference_rows,
            self.summary.mismatch_cells, self.summary.mismatch_rate, rebuilt_field_stats,
            self.summary.detail_sha256, self.summary.passed,
        )

        derived = _derive_cross_source_from_detail(
            detail=self.detail,
            sample_plan=rebuilt_plan,
            price_atol=rebuilt_summary.price_atol,
            price_rtol=rebuilt_summary.price_rtol,
            volume_rtol=rebuilt_summary.volume_rtol,
            max_mismatch_rate=rebuilt_summary.max_mismatch_rate,
        )
        if type(self.detail_sha256) is not str or self.detail_sha256 != derived.detail_sha256:
            raise ValueError("bundle detail_sha256 不一致")
        if rebuilt_summary.detail_sha256 != derived.detail_sha256:
            raise ValueError("bundle summary detail_sha256 不一致")
        if rebuilt_summary.primary_candidate_key != rebuilt_plan.primary_candidate_key:
            raise ValueError("bundle summary primary_candidate_key 不一致")
        if rebuilt_summary.sample_plan_sha256 != rebuilt_plan.sample_plan_sha256:
            raise ValueError("bundle summary sample_plan_sha256 不一致")
        if (
            rebuilt_summary.sample_symbol_count != _SAMPLE_SYMBOLS
            or rebuilt_summary.dates_per_symbol != _DATES_PER_SYMBOL
            or rebuilt_summary.key_count != _KEY_COUNT
            or rebuilt_summary.field_count != _FIELD_COUNT
            or rebuilt_summary.comparison_count != _COMPARISON_COUNT
        ):
            raise ValueError("bundle summary 守恒字段非法")
        expected_ref_digests = tuple(sorted(stable_digests))
        if len(rebuilt_summary.reference_receipt_digests) != _SAMPLE_SYMBOLS:
            raise ValueError("bundle summary reference_receipt_digests 数量非法")
        if rebuilt_summary.reference_receipt_digests != expected_ref_digests:
            raise ValueError("bundle summary reference_receipt_digests 不一致")
        if rebuilt_summary.missing_primary_rows != derived.missing_primary_rows:
            raise ValueError("bundle summary missing_primary_rows 不一致")
        if rebuilt_summary.missing_reference_rows != derived.missing_reference_rows:
            raise ValueError("bundle summary missing_reference_rows 不一致")
        if rebuilt_summary.mismatch_cells != derived.mismatch_cells:
            raise ValueError("bundle summary mismatch_cells 不一致")
        if abs(rebuilt_summary.mismatch_rate - derived.mismatch_rate) > _RATE_EPS:
            raise ValueError("bundle summary mismatch_rate 不一致")
        if rebuilt_summary.field_stats != derived.field_stats:
            raise ValueError("bundle summary field_stats 不一致")
        if rebuilt_summary.passed is not derived.passed:
            raise ValueError("bundle summary passed 不一致")

        if type(self.summary_sha256) is not str or not _HEX64.fullmatch(self.summary_sha256):
            raise ValueError("bundle summary_sha256 非法")
        recomputed_summary_hash = _sha256_json(asdict(rebuilt_summary))
        if recomputed_summary_hash != self.summary_sha256:
            raise ValueError("bundle summary_sha256 不一致")

        if type(self.issues) is not tuple:
            raise ValueError("bundle issues 类型非法")
        for issue_item in self.issues:
            if type(issue_item) is not G1QualityIssue:
                raise ValueError("bundle issues 元素非法")
            if issue_item.code not in {"CROSS_SOURCE_INCOMPLETE", "CROSS_SOURCE_MISMATCH"}:
                raise ValueError("bundle issues 元素非法")
            if issue_item.severity != "ERROR":
                raise ValueError("bundle issues severity 必须是 ERROR")
        ordered_issues = tuple(
            sorted(
                self.issues,
                key=lambda issue: (issue.severity, issue.code, issue.message, issue.evidence),
            )
        )
        if self.issues != ordered_issues:
            raise ValueError("bundle issues 必须排序")
        if ordered_issues != derived.issues:
            raise ValueError("bundle issues 与 detail 派生结果不一致")
        if type(self.passed) is not bool:
            raise ValueError("bundle passed 必须是 bool")
        if self.passed is not derived.passed:
            raise ValueError("bundle passed 与 detail 派生结果不一致")
        if self.passed is not (len(ordered_issues) == 0):
            raise ValueError("bundle passed 与 issues 不一致")
        if self.passed != rebuilt_summary.passed:
            raise ValueError("bundle passed 与 summary.passed 不一致")
        object.__setattr__(self, "sample_plan", rebuilt_plan)
        object.__setattr__(self, "reference_receipts", ordered_receipts)
        object.__setattr__(self, "summary", rebuilt_summary)
        object.__setattr__(self, "issues", ordered_issues)


@dataclass(frozen=True)
class _RequestPreflight:
    mode: Literal["REPLAY", "RECOVER", "NETWORK"]


def plan_cross_source_reconciliation(
    *, candidate: G1Candidate, policy: G1CrossSourcePolicy,
) -> CrossSourceSamplePlan:
    if type(candidate) is not G1Candidate:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID")
    try:
        rebuilt_policy = _consume_policy(policy)
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID") from None
    try:
        audit = audit_g1_candidate(candidate=candidate)
        if not audit.passed:
            raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID")
        primary_key = candidate.primary_candidate_key
        symbols = sorted(set(candidate.bars.get_column("symbol").to_list()))
        if len(symbols) < rebuilt_policy.sample_symbols:
            raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID")
        ranked_symbols = sorted(
            symbols,
            key=lambda symbol: (
                _sha256_json(["m3-g1-cross-source-symbol-v1", primary_key, symbol]),
                symbol,
            ),
        )
        selected_symbols = ranked_symbols[: rebuilt_policy.sample_symbols]
        keys: list[tuple[str, dt.date]] = []
        for symbol in selected_symbols:
            dates = sorted(
                set(
                    candidate.bars.filter(pl.col("symbol") == symbol)
                    .get_column("trade_date")
                    .to_list()
                )
            )
            if len(dates) < rebuilt_policy.dates_per_symbol:
                raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID")
            ranked_dates = sorted(
                dates,
                key=lambda day: (
                    _sha256_json(
                        ["m3-g1-cross-source-date-v1", primary_key, symbol, day.isoformat()]
                    ),
                    day,
                ),
            )
            for day in ranked_dates[: rebuilt_policy.dates_per_symbol]:
                keys.append((symbol, day))
        ordered_keys = tuple(sorted(keys, key=lambda item: (item[0], item[1])))
        sample_hash = _sample_plan_sha256(
            primary_candidate_key=primary_key,
            sample_symbols=rebuilt_policy.sample_symbols,
            dates_per_symbol=rebuilt_policy.dates_per_symbol,
            keys=ordered_keys,
        )
        return CrossSourceSamplePlan(
            _SAMPLE_SCHEMA, primary_key, rebuilt_policy.sample_symbols,
            rebuilt_policy.dates_per_symbol, ordered_keys, sample_hash,
        )
    except M3ReferenceError:
        raise
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID") from None


def plan_baostock_reference_requests(
    *, sample_plan: CrossSourceSamplePlan,
) -> ReferenceRequestPlanV1:
    try:
        rebuilt = _consume_sample_plan(sample_plan)
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID") from None
    try:
        by_symbol: dict[str, list[dt.date]] = {}
        for symbol, day in rebuilt.keys:
            by_symbol.setdefault(symbol, []).append(day)
        if len(by_symbol) != rebuilt.sample_symbols:
            raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID")
        specs: list[ReferenceRequestSpec] = []
        for symbol, days in by_symbol.items():
            if len(days) != rebuilt.dates_per_symbol:
                raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID")
            start = min(days)
            end = max(days)
            parameters = tuple(
                sorted(
                    (
                        ("fields", _FIELDS),
                        ("frequency", "d"),
                        ("adjustflag", "3"),
                        ("start_date", start.isoformat()),
                        ("end_date", end.isoformat()),
                    )
                )
            )
            request_id = _request_id(symbol=symbol, parameters=parameters)
            specs.append(
                ReferenceRequestSpec(_REQUEST_SCHEMA, request_id, _ENDPOINT, symbol, parameters)
            )
        ordered = tuple(sorted(specs, key=lambda spec: spec.request_id))
        if len(ordered) != rebuilt.sample_symbols:
            raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID")
        plan_hash = _request_plan_sha256(
            sample_plan_sha256=rebuilt.sample_plan_sha256, requests=ordered
        )
        return ReferenceRequestPlanV1(_PLAN_SCHEMA, rebuilt.sample_plan_sha256, ordered, plan_hash)
    except M3ReferenceError:
        raise
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID") from None


def execute_baostock_reference_plan(
    *,
    sample_plan: CrossSourceSamplePlan,
    plan: ReferenceRequestPlanV1,
    connector: BaostockConnector,
    raw_store: RawStore,
    journal_root: Path,
) -> tuple[ReferenceRequestReceipt, ...]:
    try:
        rebuilt_sample_plan = _consume_sample_plan(sample_plan)
        rebuilt_plan = _consume_request_plan(plan)
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID") from None
    if type(connector) is not BaostockConnector:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID")
    if type(raw_store) is not RawStore:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID")
    if not isinstance(journal_root, Path):
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID")

    expected_plan = plan_baostock_reference_requests(sample_plan=rebuilt_sample_plan)
    if (
        expected_plan.sample_plan_sha256 != rebuilt_plan.sample_plan_sha256
        or expected_plan.requests != rebuilt_plan.requests
        or expected_plan.request_plan_sha256 != rebuilt_plan.request_plan_sha256
    ):
        raise M3ReferenceError("G1_REFERENCE_PLAN_INVALID")

    _preflight_controlled_root(raw_store.root)
    _preflight_controlled_root(journal_root)

    try:
        journal_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
    _preflight_controlled_root(journal_root)

    try:
        with hold_journal_writer_lock(journal_root=journal_root):
            return _execute_baostock_reference_plan_locked(
                rebuilt_plan=rebuilt_plan,
                connector=connector,
                raw_store=raw_store,
                journal_root=journal_root,
            )
    except M3JournalLockError as exc:
        raise _map_journal_lock_error(exc) from None


def _execute_baostock_reference_plan_locked(
    *,
    rebuilt_plan: ReferenceRequestPlanV1,
    connector: BaostockConnector,
    raw_store: RawStore,
    journal_root: Path,
) -> tuple[ReferenceRequestReceipt, ...]:
    preflights: dict[str, _RequestPreflight] = {
        spec.request_id: _inspect_request_preflight(
            spec=spec, journal_root=journal_root, raw_store=raw_store
        )
        for spec in rebuilt_plan.requests
    }

    receipts: list[ReferenceRequestReceipt] = []
    for spec in rebuilt_plan.requests:
        preflight = preflights[spec.request_id]
        request_dir = journal_root / spec.request_id
        intent_path = request_dir / "intent.json"
        candidate_path = request_dir / "candidate.json"
        receipt_path = request_dir / "receipt.json"

        if preflight.mode == "REPLAY":
            verified = verify_reference_receipt(
                spec=spec, receipt_path=receipt_path,
                raw_root=raw_store.root, journal_root=journal_root,
            )
            receipts.append(verified.receipt)
            continue

        try:
            request_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
        _reject_path_symlinks(journal_root, request_dir)
        _validate_journal_dir_entries(request_dir)

        if not _regular_file_exists(intent_path):
            _ensure_intent(intent_path, spec)

        if preflight.mode == "RECOVER":
            candidate = _recover_candidate(
                spec=spec, candidate_path=candidate_path, raw_store=raw_store
            )
        else:
            frame = _fetch_reference(connector, spec)
            try:
                snapshot = raw_store.write_request(
                    source="baostock", table=_ENDPOINT, request_id=spec.request_id,
                    frame=frame, parameters=dict(spec.parameters),
                )
            except (OSError, ValueError):
                raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
            candidate = _candidate_from_snapshot(spec, snapshot, frame, raw_store.root)
            if _regular_file_exists(candidate_path):
                raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
            _write_dataclass_once(candidate_path, candidate)

        receipt = _receipt_from_candidate(spec, candidate)
        if _regular_file_exists(receipt_path):
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        _write_dataclass_once(receipt_path, receipt)
        verified = verify_reference_receipt(
            spec=spec, receipt_path=receipt_path,
            raw_root=raw_store.root, journal_root=journal_root,
        )
        receipts.append(verified.receipt)
    return tuple(sorted(receipts, key=lambda item: item.request_id))


def _map_journal_lock_error(exc: M3JournalLockError) -> M3ReferenceError:
    code = exc.code
    if code in {
        "JOURNAL_WRITER_ACTIVE",
        "JOURNAL_LOCK_INPUT_INVALID",
        "JOURNAL_LOCK_ROOT_INVALID",
        "JOURNAL_LOCK_FILE_INVALID",
    }:
        return M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
    if code in {"JOURNAL_LOCK_IO_FAILED", "JOURNAL_LOCK_RELEASE_FAILED"}:
        return M3ReferenceError("G1_REFERENCE_IO_FAILED")
    return M3ReferenceError("G1_REFERENCE_IO_FAILED")


def verify_reference_receipt(
    *, spec: ReferenceRequestSpec, receipt_path: Path, raw_root: Path, journal_root: Path,
) -> VerifiedReferenceResponse:
    try:
        rebuilt_spec = _consume_spec(spec)
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID") from None
    if (
        not isinstance(receipt_path, Path)
        or not isinstance(raw_root, Path)
        or not isinstance(journal_root, Path)
    ):
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID")
    try:
        expected_path = journal_root / rebuilt_spec.request_id / "receipt.json"
        if receipt_path != expected_path:
            raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID")
        _reject_path_symlinks(journal_root, receipt_path)
        payload = _read_bytes(receipt_path, "G1_REFERENCE_RECEIPT_INVALID")
        try:
            receipt = _receipt_from_dict(_strict_json(payload))
        except (TypeError, ValueError, KeyError):
            raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID") from None
        if (
            receipt.request_id != rebuilt_spec.request_id
            or receipt.endpoint != rebuilt_spec.endpoint
            or receipt.symbol != rebuilt_spec.symbol
            or receipt.parameters != rebuilt_spec.parameters
        ):
            raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID")
        raw_store = RawStore(raw_root)
        data_path = _resolve_relative(raw_root, receipt.raw_data_path)
        metadata_path = _resolve_relative(raw_root, receipt.raw_metadata_path)
        try:
            snapshot, frame = raw_store.verify_request_bundle(
                source="baostock", table=_ENDPOINT, request_id=rebuilt_spec.request_id,
                parameters=dict(rebuilt_spec.parameters),
            )
        except (OSError, ValueError):
            raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID") from None
        if data_path != snapshot.data_path or metadata_path != snapshot.metadata_path:
            raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID")
        _validate_reference_frame(frame)
        content_hash = _reference_response_content_sha256(frame)
        if (
            receipt.raw_snapshot_id != snapshot.snapshot_id
            or receipt.raw_file_sha256 != snapshot.checksum_sha256
            or receipt.raw_metadata_sha256 != snapshot.metadata_sha256
            or receipt.raw_size_bytes != snapshot.size_bytes
            or receipt.row_count != snapshot.row_count
            or receipt.columns != snapshot.columns
            or receipt.response_content_sha256 != content_hash
        ):
            raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID")
        receipt_sha256 = hashlib.sha256(payload).hexdigest()
        return VerifiedReferenceResponse(rebuilt_spec, receipt, receipt_sha256, frame)
    except M3ReferenceError:
        raise
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID") from None


def reconcile_cross_source(
    *,
    candidate: G1Candidate,
    sample_plan: CrossSourceSamplePlan,
    reference_responses: Sequence[VerifiedReferenceResponse],
    policy: G1CrossSourcePolicy,
) -> CrossSourceReconciliationBundle:
    if type(candidate) is not G1Candidate:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID")
    try:
        rebuilt_policy = _consume_policy(policy)
        rebuilt_sample_plan = _consume_sample_plan(sample_plan)
        responses = [_consume_verified_reference(item) for item in reference_responses]
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_INPUT_INVALID") from None

    try:
        if rebuilt_sample_plan.primary_candidate_key != candidate.primary_candidate_key:
            raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
        expected_sample_plan = plan_cross_source_reconciliation(
            candidate=candidate, policy=rebuilt_policy
        )
        if expected_sample_plan != rebuilt_sample_plan:
            raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")

        expected_request_plan = plan_baostock_reference_requests(
            sample_plan=rebuilt_sample_plan
        )
        if len(responses) != len(expected_request_plan.requests):
            raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
        by_request_id = {item.spec.request_id: item for item in responses}
        if len(by_request_id) != len(responses):
            raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
        if set(by_request_id) != {spec.request_id for spec in expected_request_plan.requests}:
            raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")

        verified_by_symbol: dict[str, VerifiedReferenceResponse] = {}
        for spec in expected_request_plan.requests:
            verified = by_request_id[spec.request_id]
            if verified.spec != spec:
                raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
            verified_by_symbol[spec.symbol] = verified

        reference_rows: dict[tuple[str, dt.date], dict[str, float] | None] = {}
        for symbol, verified in verified_by_symbol.items():
            params = dict(verified.spec.parameters)
            start = _validate_iso_date(params["start_date"])
            end = _validate_iso_date(params["end_date"])
            expected_code = _symbol_to_baostock_code(symbol)
            seen_dates: set[dt.date] = set()
            for row in verified.frame.iter_rows(named=True):
                if row["code"] != expected_code:
                    raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
                day = _validate_iso_date(row["date"])
                if day < start or day > end:
                    raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
                if day in seen_dates:
                    raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
                seen_dates.add(day)
                if row["adjustflag"] != "3":
                    raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
                tradestatus = row["tradestatus"]
                if tradestatus not in {"0", "1"}:
                    raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
                key = (symbol, day)
                if tradestatus == "0":
                    reference_rows[key] = None
                    continue
                values: dict[str, float] = {}
                for field in ("open", "high", "low", "close", "volume", "amount"):
                    parsed = _parse_reference_numeric(row[field])
                    if field in {"volume", "amount"}:
                        if parsed < 0.0:
                            raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
                    elif parsed <= 0.0:
                        raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
                    if field in _COMPARE_FIELDS:
                        values[field] = parsed
                reference_rows[key] = values

        primary_rows: dict[tuple[str, dt.date], dict[str, float]] = {}
        for row in candidate.bars.iter_rows(named=True):
            primary_rows[(row["symbol"], row["trade_date"])] = {
                field: float(row[field]) for field in _COMPARE_FIELDS
            }

        detail_rows: list[dict[str, Any]] = []

        for symbol, day in rebuilt_sample_plan.keys:
            key = (symbol, day)
            primary_values = primary_rows.get(key)
            reference_values = reference_rows.get(key)
            for field in _COMPARE_FIELDS:
                primary_value: float | None = (
                    primary_values[field] if primary_values is not None else None
                )
                reference_value: float | None = (
                    reference_values[field] if reference_values is not None else None
                )
                if primary_value is not None and reference_value is not None:
                    if field == "volume":
                        tolerance = rebuilt_policy.volume_rtol * max(abs(reference_value), 1.0)
                    else:
                        tolerance = rebuilt_policy.price_atol + rebuilt_policy.price_rtol * abs(
                            reference_value
                        )
                    computed_abs = abs(primary_value - reference_value)
                    computed_rel = computed_abs / max(abs(reference_value), 1e-300)
                    abs_diff = computed_abs
                    relative_diff = computed_rel
                    matched = computed_abs <= tolerance
                    missing_side = "NONE"
                else:
                    abs_diff = None
                    relative_diff = None
                    tolerance = 0.0
                    matched = False
                    if primary_value is None and reference_value is None:
                        missing_side = "BOTH"
                    elif primary_value is None:
                        missing_side = "PRIMARY"
                    else:
                        missing_side = "REFERENCE"
                detail_rows.append(
                    {
                        "symbol": symbol,
                        "trade_date": day,
                        "field": field,
                        "primary_value": primary_value,
                        "reference_value": reference_value,
                        "abs_diff": abs_diff,
                        "relative_diff": relative_diff,
                        "tolerance": float(tolerance),
                        "missing_side": missing_side,
                        "matched": matched,
                    }
                )

        detail = pl.DataFrame(
            detail_rows,
            schema={
                "symbol": pl.Utf8,
                "trade_date": pl.Date,
                "field": pl.Utf8,
                "primary_value": pl.Float64,
                "reference_value": pl.Float64,
                "abs_diff": pl.Float64,
                "relative_diff": pl.Float64,
                "tolerance": pl.Float64,
                "missing_side": pl.Utf8,
                "matched": pl.Boolean,
            },
        )
        derived = _derive_cross_source_from_detail(
            detail=detail,
            sample_plan=rebuilt_sample_plan,
            price_atol=rebuilt_policy.price_atol,
            price_rtol=rebuilt_policy.price_rtol,
            volume_rtol=rebuilt_policy.volume_rtol,
            max_mismatch_rate=rebuilt_policy.max_mismatch_rate,
        )
        primary_receipt_digests = tuple(
            sorted({item.stable_response_sha256 for item in candidate.input_receipts})
        )
        reference_receipt_digests = tuple(
            sorted({item.receipt.stable_response_sha256 for item in responses})
        )
        summary = CrossSourceSummaryV1(
            _SUMMARY_SCHEMA,
            candidate.primary_candidate_key,
            rebuilt_sample_plan.sample_plan_sha256,
            rebuilt_policy.sample_symbols,
            rebuilt_policy.dates_per_symbol,
            _KEY_COUNT,
            _FIELD_COUNT,
            _COMPARISON_COUNT,
            primary_receipt_digests,
            reference_receipt_digests,
            rebuilt_policy.price_atol,
            rebuilt_policy.price_rtol,
            rebuilt_policy.volume_rtol,
            rebuilt_policy.max_mismatch_rate,
            derived.missing_primary_rows,
            derived.missing_reference_rows,
            derived.mismatch_cells,
            derived.mismatch_rate,
            derived.field_stats,
            derived.detail_sha256,
            derived.passed,
        )
        summary_hash = _sha256_json(asdict(summary))
        reference_receipts_proj = tuple(
            sorted(
                (
                    G1ReceiptProjectionV1(
                        source="baostock",
                        request_id=item.receipt.request_id,
                        endpoint=item.receipt.endpoint,
                        parameters_sha256=item.receipt.parameters_sha256,
                        stable_response_sha256=item.receipt.stable_response_sha256,
                        row_count=item.receipt.row_count,
                        columns=item.receipt.columns,
                    )
                    for item in responses
                ),
                key=lambda value: (value.source, value.endpoint, value.request_id),
            )
        )
        return CrossSourceReconciliationBundle(
            rebuilt_sample_plan,
            reference_receipts_proj,
            detail,
            derived.detail_sha256,
            summary,
            summary_hash,
            derived.issues,
            derived.passed,
        )
    except M3ReferenceError:
        raise
    except Exception:
        raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID") from None


def _inspect_request_preflight(
    *, spec: ReferenceRequestSpec, journal_root: Path, raw_store: RawStore,
) -> _RequestPreflight:
    request_dir = journal_root / spec.request_id
    _reject_path_symlinks(journal_root, request_dir)
    try:
        dir_mode = os.lstat(request_dir).st_mode
        dir_present = True
    except FileNotFoundError:
        dir_present = False
    except OSError:
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
    if dir_present:
        if not stat.S_ISDIR(dir_mode):
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        _validate_journal_dir_entries(request_dir)
    intent_path = request_dir / "intent.json"
    candidate_path = request_dir / "candidate.json"
    receipt_path = request_dir / "receipt.json"
    intent_exists = _regular_file_exists(intent_path)
    candidate_exists = _regular_file_exists(candidate_path)
    receipt_exists = _regular_file_exists(receipt_path)
    try:
        raw_state = raw_store.inspect_request_state(
            source="baostock", table=_ENDPOINT, request_id=spec.request_id
        )
    except ValueError:
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID") from None
    except OSError:
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None

    if intent_exists:
        _verify_existing_intent(intent_path, spec)

    if receipt_exists:
        if not intent_exists or not candidate_exists or raw_state != "COMPLETE":
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        # Fully verify receipt/raw/frame closure before any later intent/network.
        candidate = _recover_candidate(
            spec=spec, candidate_path=candidate_path, raw_store=raw_store
        )
        verified = verify_reference_receipt(
            spec=spec,
            receipt_path=receipt_path,
            raw_root=raw_store.root,
            journal_root=journal_root,
        )
        if verified.receipt != _receipt_from_candidate(spec, candidate):
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        return _RequestPreflight("REPLAY")
    if candidate_exists:
        if not intent_exists or raw_state != "COMPLETE":
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        _recover_candidate(spec=spec, candidate_path=candidate_path, raw_store=raw_store)
        return _RequestPreflight("RECOVER")
    if raw_state == "COMPLETE":
        if not intent_exists:
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        return _RequestPreflight("RECOVER")
    if intent_exists and raw_state not in {"ABSENT", "EMPTY"}:
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
    return _RequestPreflight("NETWORK")


def _fetch_reference(connector: BaostockConnector, spec: ReferenceRequestSpec) -> pl.DataFrame:
    params = dict(spec.parameters)
    try:
        frame = connector.fetch_reference_bar_raw(
            symbol=spec.symbol,
            start=_validate_iso_date(params["start_date"]),
            end=_validate_iso_date(params["end_date"]),
            fields=params["fields"],
            frequency=params["frequency"],
            adjustflag=params["adjustflag"],
        )
    except Exception:
        raise M3ReferenceError("G1_REFERENCE_NETWORK_FAILED") from None
    _validate_reference_frame(frame)
    return frame


def _recover_candidate(
    *, spec: ReferenceRequestSpec, candidate_path: Path, raw_store: RawStore,
) -> ReferenceRawCandidateV1:
    if _regular_file_exists(candidate_path):
        try:
            candidate = _candidate_from_dict(
                _strict_json(_read_bytes(candidate_path, "G1_REFERENCE_JOURNAL_INVALID"))
            )
        except (TypeError, ValueError, KeyError):
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID") from None
        return _verify_candidate_matches(spec, candidate, raw_store)
    try:
        snapshot, frame = raw_store.verify_request_bundle(
            source="baostock", table=_ENDPOINT, request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
    except (OSError, ValueError):
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
    _validate_reference_frame(frame)
    candidate = _candidate_from_snapshot(spec, snapshot, frame, raw_store.root)
    if _regular_file_exists(candidate_path):
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
    _write_dataclass_once(candidate_path, candidate)
    return candidate


def _verify_candidate_matches(
    spec: ReferenceRequestSpec, candidate: ReferenceRawCandidateV1, raw_store: RawStore,
) -> ReferenceRawCandidateV1:
    if (
        candidate.request_id != spec.request_id
        or candidate.endpoint != spec.endpoint
        or candidate.symbol != spec.symbol
        or candidate.parameters_sha256 != _parameters_hash(spec.parameters)
    ):
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
    try:
        snapshot, frame = raw_store.verify_request_bundle(
            source="baostock", table=_ENDPOINT, request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
    except (OSError, ValueError):
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
    _validate_reference_frame(frame)
    expected = _candidate_from_snapshot(spec, snapshot, frame, raw_store.root)
    if candidate != expected:
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
    return candidate


def _candidate_from_snapshot(
    spec: ReferenceRequestSpec, snapshot: Any, frame: pl.DataFrame, raw_root: Path,
) -> ReferenceRawCandidateV1:
    return ReferenceRawCandidateV1(
        _CANDIDATE_SCHEMA,
        spec.request_id,
        spec.endpoint,
        spec.symbol,
        _parameters_hash(spec.parameters),
        snapshot.snapshot_id,
        snapshot.data_path.relative_to(raw_root).as_posix(),
        snapshot.metadata_path.relative_to(raw_root).as_posix(),
        snapshot.checksum_sha256,
        snapshot.metadata_sha256,
        _reference_response_content_sha256(frame),
        snapshot.size_bytes,
        snapshot.row_count,
        snapshot.columns,
    )


def _receipt_from_candidate(
    spec: ReferenceRequestSpec, candidate: ReferenceRawCandidateV1,
) -> ReferenceRequestReceipt:
    values: dict[str, Any] = {
        "schema_version": _RECEIPT_SCHEMA,
        "request_id": spec.request_id,
        "endpoint": spec.endpoint,
        "symbol": spec.symbol,
        "parameters": spec.parameters,
        "parameters_sha256": candidate.parameters_sha256,
        "raw_snapshot_id": candidate.raw_snapshot_id,
        "raw_data_path": candidate.raw_data_path,
        "raw_metadata_path": candidate.raw_metadata_path,
        "raw_file_sha256": candidate.raw_file_sha256,
        "raw_metadata_sha256": candidate.raw_metadata_sha256,
        "response_content_sha256": candidate.response_content_sha256,
        "stable_response_sha256": "0" * 64,
        "raw_size_bytes": candidate.raw_size_bytes,
        "row_count": candidate.row_count,
        "columns": candidate.columns,
    }
    values["stable_response_sha256"] = _stable_response_hash_values(values)
    return ReferenceRequestReceipt(**values)


def _ensure_intent(path: Path, spec: ReferenceRequestSpec) -> None:
    intent = ReferenceRequestIntentV1(
        _INTENT_SCHEMA, spec.request_id, spec.endpoint, spec.symbol, spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if path.exists():
        _verify_existing_intent(path, spec)
    else:
        _write_dataclass_once(path, intent)


def _verify_existing_intent(path: Path, spec: ReferenceRequestSpec) -> None:
    try:
        existing = _intent_from_dict(
            _strict_json(_read_bytes(path, "G1_REFERENCE_JOURNAL_INVALID"))
        )
    except (TypeError, ValueError, KeyError):
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID") from None
    expected = ReferenceRequestIntentV1(
        _INTENT_SCHEMA, spec.request_id, spec.endpoint, spec.symbol, spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if existing != expected:
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")


def _write_dataclass_once(path: Path, value: Any) -> None:
    """Publish immutable JSON once via exclusive temporary + hardlink.

    File content is flushed and ``os.fsync``'d before ``os.link``. After a
    successful link the complete canonical target is already visible; a later
    directory-persist failure still returns ``G1_REFERENCE_IO_FAILED`` but must
    retain that full target (no check-then-unlink) so a same-spec retry can
    recover via ``_verify_existing_intent``. Temporary files are always cleaned.
    """
    payload = _canonical_json(asdict(value)).encode("utf-8")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{id(value)}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID") from None
        except OSError:
            raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
        # Link success = complete immutable target visible. Directory fsync may
        # still fail (POSIX); keep the target for same-spec recovery.
        _fsync_directory(path.parent)
    except M3ReferenceError:
        raise
    except OSError:
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
    finally:
        has_primary_error = sys.exc_info()[0] is not None
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            if not has_primary_error:
                raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory persist after exclusive hardlink publish.

    POSIX/Linux: ``open(directory, O_RDONLY)`` + ``fsync`` + ``close``. Any step
    failure maps to ``G1_REFERENCE_IO_FAILED``.

    Windows: standard user environments have no verified POSIX-equivalent
    directory fsync (``os.open(dir, O_RDONLY)`` raises ``PermissionError``;
    even a ``FILE_FLAG_BACKUP_SEMANTICS`` handle still gets
    ``FlushFileBuffers`` ``ERROR_ACCESS_DENIED``). After file-level fsync and
    exclusive hardlink this function returns without attempting the failing
    ``os.open``. Guarantees: complete file content was file-fsync'd before
    link, and exclusive no-overwrite publish. Does **not** claim POSIX
    directory-entry crash durability. Windows green tests do not substitute
    for WSL Gate.
    """
    if sys.platform == "win32":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None


def _validate_reference_frame(frame: pl.DataFrame) -> None:
    if not isinstance(frame, pl.DataFrame):
        raise M3ReferenceError("G1_REFERENCE_RESPONSE_INVALID")
    if tuple(frame.columns) != _FIELD_COLUMNS:
        raise M3ReferenceError("G1_REFERENCE_RESPONSE_INVALID")
    if frame.height >= _ROW_LIMIT:
        raise M3ReferenceError("G1_REFERENCE_RESPONSE_INVALID")


def _parse_reference_numeric(value: object) -> float:
    if type(value) is not str or not value:
        raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
    try:
        parsed = float(value)
    except ValueError:
        raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID") from None
    if not math.isfinite(parsed):
        raise M3ReferenceError("G1_CROSS_SOURCE_RECONCILIATION_INVALID")
    return parsed


def _symbol_to_baostock_code(symbol: str) -> str:
    code, market = symbol.split(".", maxsplit=1)
    return f"{market.lower()}.{code}"


def _consume_policy(value: object) -> G1CrossSourcePolicy:
    if type(value) is not G1CrossSourcePolicy:
        raise ValueError("policy 类型非法")
    return G1CrossSourcePolicy(
        value.reference_source, value.sample_symbols, value.dates_per_symbol,
        value.price_atol, value.price_rtol, value.volume_rtol, value.max_mismatch_rate,
    )


def _consume_sample_plan(value: object) -> CrossSourceSamplePlan:
    if type(value) is not CrossSourceSamplePlan:
        raise ValueError("sample plan 类型非法")
    return CrossSourceSamplePlan(
        value.schema_version, value.primary_candidate_key, value.sample_symbols,
        value.dates_per_symbol, value.keys, value.sample_plan_sha256,
    )


def _consume_request_plan(value: object) -> ReferenceRequestPlanV1:
    if type(value) is not ReferenceRequestPlanV1:
        raise ValueError("request plan 类型非法")
    return ReferenceRequestPlanV1(
        value.schema_version, value.sample_plan_sha256, value.requests, value.request_plan_sha256,
    )


def _consume_spec(value: object) -> ReferenceRequestSpec:
    if type(value) is not ReferenceRequestSpec:
        raise ValueError("request spec 类型非法")
    return ReferenceRequestSpec(
        value.schema_version, value.request_id, value.endpoint, value.symbol, value.parameters,
    )


def _consume_verified_reference(value: object) -> VerifiedReferenceResponse:
    if type(value) is not VerifiedReferenceResponse:
        raise ValueError("verified reference 类型非法")
    return VerifiedReferenceResponse(value.spec, value.receipt, value.receipt_sha256, value.frame)


def _regular_file_exists(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return False
    except OSError:
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
    if not stat.S_ISREG(mode):
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
    return True


def _preflight_controlled_root(root: Path) -> None:
    try:
        absolute = Path(os.path.abspath(root))
        chain = list(reversed((absolute, *absolute.parents)))
        for path in chain:
            try:
                mode = os.lstat(path).st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
            if not stat.S_ISDIR(mode):
                raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        absolute.relative_to(absolute.anchor)
    except M3ReferenceError:
        raise
    except (OSError, ValueError, TypeError):
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID") from None


def _reject_path_symlinks(root: Path, target: Path) -> None:
    _preflight_controlled_root(root)
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID") from None
    cursor = root
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            mode = os.lstat(cursor).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None
        if stat.S_ISLNK(mode):
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")


def _resolve_relative(root: Path, value: str) -> Path:
    _validate_relative(value)
    target = root.joinpath(*PurePosixPath(value).parts)
    _reject_path_symlinks(root, target)
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        raise M3ReferenceError("G1_REFERENCE_RECEIPT_INVALID") from None
    return target


def _validate_relative(value: Any) -> None:
    if type(value) is not str or "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError("相对路径非法")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("相对路径逃逸")


def _read_bytes(path: Path, code: str) -> bytes:
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise OSError
        return path.read_bytes()
    except OSError:
        raise M3ReferenceError(code) from None


def _strict_json(payload: bytes) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8", errors="strict")

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            output: dict[str, Any] = {}
            for key, value in items:
                if key in output:
                    raise ValueError("duplicate JSON key")
                output[key] = value
            return output

        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be object")
    return value


def _exact_keys(value: dict[str, Any], cls: type[Any]) -> None:
    expected = set(cls.__dataclass_fields__)
    if set(value) != expected:
        raise ValueError("JSON field set mismatch")


def _parse_parameters(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, list)
        and len(item) == 2
        and type(item[0]) is str
        and type(item[1]) is str
        for item in value
    ):
        raise ValueError("parameters JSON invalid")
    return tuple((item[0], item[1]) for item in value)


def _parse_columns(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(type(item) is str for item in value):
        raise ValueError("columns JSON invalid")
    return tuple(value)


def _intent_from_dict(value: dict[str, Any]) -> ReferenceRequestIntentV1:
    _exact_keys(value, ReferenceRequestIntentV1)
    return ReferenceRequestIntentV1(
        value["schema_version"], value["request_id"], value["endpoint"], value["symbol"],
        _parse_parameters(value["parameters"]), value["parameters_sha256"],
    )


def _candidate_from_dict(value: dict[str, Any]) -> ReferenceRawCandidateV1:
    _exact_keys(value, ReferenceRawCandidateV1)
    return ReferenceRawCandidateV1(
        value["schema_version"], value["request_id"], value["endpoint"], value["symbol"],
        value["parameters_sha256"], value["raw_snapshot_id"], value["raw_data_path"],
        value["raw_metadata_path"], value["raw_file_sha256"], value["raw_metadata_sha256"],
        value["response_content_sha256"], value["raw_size_bytes"], value["row_count"],
        _parse_columns(value["columns"]),
    )


def _receipt_from_dict(value: dict[str, Any]) -> ReferenceRequestReceipt:
    _exact_keys(value, ReferenceRequestReceipt)
    return ReferenceRequestReceipt(
        value["schema_version"], value["request_id"], value["endpoint"], value["symbol"],
        _parse_parameters(value["parameters"]), value["parameters_sha256"],
        value["raw_snapshot_id"], value["raw_data_path"], value["raw_metadata_path"],
        value["raw_file_sha256"], value["raw_metadata_sha256"], value["response_content_sha256"],
        value["stable_response_sha256"], value["raw_size_bytes"], value["row_count"],
        _parse_columns(value["columns"]),
    )


def _validate_journal_dir_entries(directory: Path) -> None:
    try:
        entries = list(directory.iterdir())
        for path in entries:
            mode = os.lstat(path).st_mode
            if path.name not in _JOURNAL_FILES or not stat.S_ISREG(mode):
                raise M3ReferenceError("G1_REFERENCE_JOURNAL_INVALID")
    except M3ReferenceError:
        raise
    except OSError:
        raise M3ReferenceError("G1_REFERENCE_IO_FAILED") from None


def _validate_hex(value: Any) -> None:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError("identity 必须是 64 位小写裸 hex")


def _validate_counts(size: Any, rows: Any, columns: Any) -> None:
    if type(size) is not int or size < 0:
        raise ValueError("raw size 非法")
    if type(rows) is not int or rows < 0:
        raise ValueError("row count 非法")
    if type(columns) is not tuple or not all(type(value) is str for value in columns):
        raise ValueError("columns 必须是字符串 tuple")


def _validate_parameters(parameters: tuple[tuple[str, str], ...]) -> None:
    if type(parameters) is not tuple or not all(
        type(item) is tuple
        and len(item) == 2
        and type(item[0]) is str
        and type(item[1]) is str
        for item in parameters
    ):
        raise ValueError("parameters 必须是字符串 tuple")
    if parameters != tuple(sorted(parameters)) or len(
        {key for key, _ in parameters}
    ) != len(parameters):
        raise ValueError("parameters 必须按 key 排序且唯一")


def _validate_iso_date(value: object) -> dt.date:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("日期格式非法")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError("日期格式非法") from None


def _sample_plan_sha256(
    *,
    primary_candidate_key: str,
    sample_symbols: int,
    dates_per_symbol: int,
    keys: tuple[tuple[str, dt.date], ...],
) -> str:
    return _sha256_json(
        {
            "schema_version": _SAMPLE_SCHEMA,
            "primary_candidate_key": primary_candidate_key,
            "sample_symbols": sample_symbols,
            "dates_per_symbol": dates_per_symbol,
            "keys": [[symbol, day.isoformat()] for symbol, day in keys],
        }
    )


def _request_id(*, symbol: str, parameters: tuple[tuple[str, str], ...]) -> str:
    return _sha256_json(
        {
            "schema_version": _REQUEST_SCHEMA,
            "endpoint": _ENDPOINT,
            "symbol": symbol,
            "parameters": [list(item) for item in parameters],
        }
    )


def _parameters_hash(parameters: tuple[tuple[str, str], ...]) -> str:
    return _sha256_json([list(item) for item in parameters])


def _request_plan_sha256(
    *, sample_plan_sha256: str, requests: tuple[ReferenceRequestSpec, ...]
) -> str:
    return _sha256_json(
        {
            "schema_version": _PLAN_SCHEMA,
            "sample_plan_sha256": sample_plan_sha256,
            "requests": [asdict(spec) for spec in requests],
        }
    )


def _stable_response_hash(receipt: ReferenceRequestReceipt) -> str:
    return _stable_response_hash_values(asdict(receipt))


def _stable_response_hash_values(values: Mapping[str, Any]) -> str:
    return _sha256_json(
        {
            "request_id": values["request_id"],
            "endpoint": values["endpoint"],
            "parameters_sha256": values["parameters_sha256"],
            "response_content_sha256": values["response_content_sha256"],
            "row_count": values["row_count"],
            "columns": values["columns"],
        }
    )


def _reference_response_content_sha256(frame: pl.DataFrame) -> str:
    if not isinstance(frame, pl.DataFrame) or tuple(frame.columns) != _FIELD_COLUMNS:
        raise ValueError("reference frame columns 非法")
    columns = [
        {"name": name, "dtype": str(dtype)}
        for name, dtype in zip(frame.columns, frame.dtypes, strict=True)
    ]
    rows: list[tuple[str, list[Any]]] = []
    for row in frame.iter_rows(named=True):
        canonical_row = [_canonical_scalar(row[name]) for name in frame.columns]
        business_key = [_canonical_scalar(row["code"]), _canonical_scalar(row["date"])]
        rows.append((_canonical_json([business_key, canonical_row]), canonical_row))
    rows.sort(key=lambda item: item[0])
    return _sha256_json(
        {"endpoint": _ENDPOINT, "columns": columns, "rows": [item[1] for item in rows]}
    )


def _canonical_scalar(value: Any) -> list[Any]:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("reference frame 数值非 finite")
        normalized = 0.0 if value == 0.0 else value
        return ["float", format(normalized, ".17g")]
    if isinstance(value, (dt.date, dt.datetime)):
        return ["datetime" if isinstance(value, dt.datetime) else "date", value.isoformat()]
    if type(value) is str:
        return ["str", value]
    raise ValueError("reference frame 值类型不支持")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
