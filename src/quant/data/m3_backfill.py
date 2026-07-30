"""Deterministic M3 G1 request planning and immutable request journals."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Sequence, cast

import polars as pl

from quant.data._journal_lock import M3JournalLockError, hold_journal_writer_lock
from quant.data.connectors.cninfo import (
    CNINFO_ADAPTER,
    CNINFO_DIVIDEND_ADAPTER,
    CNINFO_DIVIDEND_ENDPOINT,
    CNINFO_ENDPOINT,
    CNINFO_SHARE_CHANGE_ADAPTER,
    CNINFO_SHARE_CHANGE_ENDPOINT,
    CNINFO_SOURCE,
    CNINFO_STOCK_ALLOTMENT_FIELDS,
    CNINFO_STOCK_DIVIDEND_FIELDS,
    CNINFO_STOCK_SHARE_CHANGE_FIELDS,
    CninfoAllotmentRawResult,
    CninfoConnector,
    CninfoConnectorError,
    CninfoCorporateActionRawResult,
    batch_cninfo_symbol_groups,
    empty_cninfo_allotment_frame,
    empty_cninfo_dividend_frame,
    empty_cninfo_share_change_frame,
    normalize_cninfo_symbols,
)
from quant.data.connectors.tushare import TushareConnector
from quant.data.storage import RawStore, RequestRawSnapshot

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
TushareEndpoint = Literal[
    "index_weight",
    "daily",
    "adj_factor",
    "index_daily",
    "suspend_d",
    "stk_limit",
    "dividend",
    "fund_daily",
    "fund_adj",
    "fund_div",
]

TUSHARE_FIELDS = MappingProxyType(
    {
        "index_weight": "index_code,con_code,trade_date,weight",
        "daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        "adj_factor": "ts_code,trade_date,adj_factor",
        "index_daily": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
        "suspend_d": "ts_code,trade_date,suspend_timing,suspend_type",
        "stk_limit": "trade_date,ts_code,pre_close,up_limit,down_limit",
        "dividend": (
            "ts_code,end_date,ann_date,div_proc,stk_div,stk_bo_rate,stk_co_rate,"
            "cash_div,cash_div_tax,record_date,ex_date,pay_date,div_listdate,"
            "imp_ann_date,base_date,base_share"
        ),
        "fund_daily": (
            "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        ),
        "fund_adj": "ts_code,trade_date,adj_factor",
        "fund_div": (
            "ts_code,ann_date,imp_anndate,base_date,div_proc,record_date,ex_date,pay_date,"
            "earpay_date,net_ex_date,div_cash,base_unit,ear_distr,ear_amount,account_date,"
            "base_year"
        ),
    }
)
_ENDPOINTS = tuple(TUSHARE_FIELDS)
_RESPONSE_SORT_KEYS = {
    "index_weight": ("index_code", "con_code", "trade_date"),
    "daily": ("ts_code", "trade_date"),
    "adj_factor": ("ts_code", "trade_date"),
    "index_daily": ("ts_code", "trade_date"),
    "suspend_d": ("ts_code", "trade_date", "suspend_timing", "suspend_type"),
    "stk_limit": ("ts_code", "trade_date"),
    "dividend": (
        "ts_code", "end_date", "record_date", "ex_date", "imp_ann_date", "ann_date"
    ),
    "fund_daily": ("ts_code", "trade_date"),
    "fund_adj": ("ts_code", "trade_date"),
    "fund_div": (
        "ts_code", "ann_date", "imp_anndate", "record_date", "ex_date", "pay_date"
    ),
}


class M3BackfillError(RuntimeError):
    """Stable, sanitized failure for the B2A request boundary."""


@dataclass(frozen=True)
class EndpointPolicy:
    row_limit: int
    empty_response: Literal["ALLOW", "REJECT"]

    def __post_init__(self) -> None:
        if type(self.row_limit) is not int or self.row_limit <= 0:
            raise ValueError("row_limit 必须是正整数")
        if self.empty_response not in {"ALLOW", "REJECT"}:
            raise ValueError("empty_response 非法")


ENDPOINT_POLICIES_V1: Mapping[str, EndpointPolicy] = MappingProxyType(
    {
        "index_weight": EndpointPolicy(5000, "REJECT"),
        "daily": EndpointPolicy(6000, "REJECT"),
        "adj_factor": EndpointPolicy(6000, "REJECT"),
        "index_daily": EndpointPolicy(5000, "REJECT"),
        "suspend_d": EndpointPolicy(5000, "ALLOW"),
        "stk_limit": EndpointPolicy(5800, "REJECT"),
        "dividend": EndpointPolicy(5000, "ALLOW"),
        "fund_daily": EndpointPolicy(5000, "REJECT"),
        "fund_adj": EndpointPolicy(2000, "REJECT"),
        "fund_div": EndpointPolicy(5000, "REJECT"),
    }
)


@dataclass(frozen=True)
class TushareRequestSpec:
    schema_version: Literal["m3-g1-tushare-request-v1"]
    request_id: str
    endpoint: TushareEndpoint
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-tushare-request-v1":
            raise ValueError("request schema_version 非法")
        _validate_endpoint(self.endpoint)
        _validate_parameters(self.parameters)
        expected = _request_id(self.endpoint, self.parameters)
        if self.request_id != expected:
            raise ValueError("request_id 与 endpoint/parameters 不一致")

    @classmethod
    def create(
        cls, *, endpoint: str, parameters: Mapping[str, str]
    ) -> TushareRequestSpec:
        _validate_endpoint(endpoint)
        if not isinstance(parameters, Mapping) or not all(
            type(key) is str and type(value) is str for key, value in parameters.items()
        ):
            raise ValueError("request parameters 必须是字符串映射")
        normalized = tuple(sorted(parameters.items()))
        _validate_parameters(normalized)
        return cls(
            schema_version="m3-g1-tushare-request-v1",
            request_id=_request_id(endpoint, normalized),
            endpoint=cast(TushareEndpoint, endpoint),
            parameters=normalized,
        )


@dataclass(frozen=True)
class TushareRequestBatch:
    schema_version: Literal["m3-g1-tushare-request-batch-v1"]
    phase: Literal["INDEX_WEIGHT", "HISTORY"]
    requests: tuple[TushareRequestSpec, ...]
    batch_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-tushare-request-batch-v1":
            raise ValueError("batch schema_version 非法")
        if self.phase not in {"INDEX_WEIGHT", "HISTORY"}:
            raise ValueError("batch phase 非法")
        if type(self.requests) is not tuple or not all(
            isinstance(value, TushareRequestSpec) for value in self.requests
        ):
            raise ValueError("batch requests 必须是 request tuple")
        for value in self.requests:
            rebuilt = TushareRequestSpec(
                value.schema_version, value.request_id, value.endpoint, value.parameters
            )
            _validate_request_contract(rebuilt)
        ordered = tuple(sorted(self.requests, key=lambda value: value.request_id))
        if self.requests != ordered or len({item.request_id for item in self.requests}) != len(
            self.requests
        ):
            raise ValueError("batch requests 必须按 request_id 排序且唯一")
        if self.phase == "INDEX_WEIGHT" and (
            not self.requests or any(item.endpoint != "index_weight" for item in self.requests)
        ):
            raise ValueError("INDEX_WEIGHT batch 只能包含 index_weight request")
        if self.phase == "HISTORY" and any(
            item.endpoint == "index_weight" for item in self.requests
        ):
            raise ValueError("HISTORY batch 不得包含 index_weight request")
        if self.phase == "HISTORY" and not self.requests:
            raise ValueError("HISTORY batch 不能为空")
        if self.batch_sha256 != _batch_hash(self.phase, self.requests):
            raise ValueError("batch_sha256 不一致")


@dataclass(frozen=True)
class CninfoRequestSpec:
    schema_version: Literal["m3-g1-cninfo-request-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_allotment"]
    adapter: Literal["akshare_cninfo_p_stock2232_v1"]
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-cninfo-request-v1":
            raise ValueError("cninfo request schema_version 非法")
        if self.source != CNINFO_SOURCE:
            raise ValueError("cninfo request source 非法")
        if self.endpoint != CNINFO_ENDPOINT:
            raise ValueError("cninfo request endpoint 非法")
        if self.adapter != CNINFO_ADAPTER:
            raise ValueError("cninfo request adapter 非法")
        _validate_cninfo_parameters(self.parameters)
        expected = _cninfo_request_id(self.parameters)
        if self.request_id != expected:
            raise ValueError("cninfo request_id 与参数不一致")

    @classmethod
    def create(cls, *, parameters: Mapping[str, str]) -> CninfoRequestSpec:
        if not isinstance(parameters, Mapping) or not all(
            type(key) is str and type(value) is str for key, value in parameters.items()
        ):
            raise ValueError("cninfo request parameters 必须是字符串映射")
        normalized = tuple(sorted(parameters.items()))
        _validate_cninfo_parameters(normalized)
        return cls(
            schema_version="m3-g1-cninfo-request-v1",
            request_id=_cninfo_request_id(normalized),
            source="cninfo",
            endpoint="stock_allotment",
            adapter="akshare_cninfo_p_stock2232_v1",
            parameters=normalized,
        )


@dataclass(frozen=True)
class CninfoRequestBatch:
    schema_version: Literal["m3-g1-cninfo-request-batch-v1"]
    phase: Literal["HISTORY"]
    requests: tuple[CninfoRequestSpec, ...]
    batch_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-cninfo-request-batch-v1":
            raise ValueError("cninfo batch schema_version 非法")
        if self.phase != "HISTORY":
            raise ValueError("cninfo batch phase 非法")
        if type(self.requests) is not tuple or not self.requests:
            raise ValueError("cninfo batch requests 不能为空")
        if not all(isinstance(item, CninfoRequestSpec) for item in self.requests):
            raise ValueError("cninfo batch requests 类型非法")
        rebuilt = tuple(
            CninfoRequestSpec(
                item.schema_version,
                item.request_id,
                item.source,
                item.endpoint,
                item.adapter,
                item.parameters,
            )
            for item in self.requests
        )
        ordered = tuple(sorted(rebuilt, key=lambda value: value.request_id))
        if rebuilt != ordered or len({item.request_id for item in rebuilt}) != len(rebuilt):
            raise ValueError("cninfo batch requests 必须按 request_id 排序且唯一")
        object.__setattr__(self, "requests", rebuilt)
        if self.batch_sha256 != _cninfo_batch_hash(rebuilt):
            raise ValueError("cninfo batch_sha256 不一致")


@dataclass(frozen=True)
class CninfoCorporateActionRequestSpec:
    schema_version: Literal["m3-g1-cninfo-corporate-action-request-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_dividend", "stock_share_change"]
    adapter: Literal[
        "akshare_cninfo_p_sysapi1139_v1", "akshare_cninfo_p_stock2215_v1"
    ]
    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-cninfo-corporate-action-request-v1":
            raise ValueError("cninfo corporate-action request schema_version 非法")
        if self.source != CNINFO_SOURCE:
            raise ValueError("cninfo corporate-action request source 非法")
        expected_adapter = _ca_adapter_for_endpoint(self.endpoint)
        if self.adapter != expected_adapter:
            raise ValueError("cninfo corporate-action request adapter 非法")
        _validate_cninfo_corporate_action_parameters(self.endpoint, self.parameters)
        expected = _cninfo_corporate_action_request_id(
            endpoint=self.endpoint, adapter=self.adapter, parameters=self.parameters
        )
        if self.request_id != expected:
            raise ValueError("cninfo corporate-action request_id 与参数不一致")

    @classmethod
    def create(
        cls,
        *,
        endpoint: Literal["stock_dividend", "stock_share_change"],
        parameters: Mapping[str, str],
    ) -> CninfoCorporateActionRequestSpec:
        if not isinstance(parameters, Mapping) or not all(
            type(key) is str and type(value) is str for key, value in parameters.items()
        ):
            raise ValueError("cninfo corporate-action request parameters 必须是字符串映射")
        normalized = tuple(sorted(parameters.items()))
        adapter = _ca_adapter_for_endpoint(endpoint)
        _validate_cninfo_corporate_action_parameters(endpoint, normalized)
        return cls(
            schema_version="m3-g1-cninfo-corporate-action-request-v1",
            request_id=_cninfo_corporate_action_request_id(
                endpoint=endpoint, adapter=adapter, parameters=normalized
            ),
            source="cninfo",
            endpoint=endpoint,
            adapter=adapter,
            parameters=normalized,
        )


@dataclass(frozen=True)
class CninfoCorporateActionRequestBatch:
    schema_version: Literal["m3-g1-cninfo-corporate-action-request-batch-v1"]
    phase: Literal["HISTORY"]
    requests: tuple[CninfoCorporateActionRequestSpec, ...]
    batch_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-cninfo-corporate-action-request-batch-v1":
            raise ValueError("cninfo corporate-action batch schema_version 非法")
        if self.phase != "HISTORY":
            raise ValueError("cninfo corporate-action batch phase 非法")
        if type(self.requests) is not tuple or not self.requests:
            raise ValueError("cninfo corporate-action batch requests 不能为空")
        if not all(
            isinstance(item, CninfoCorporateActionRequestSpec) for item in self.requests
        ):
            raise ValueError("cninfo corporate-action batch requests 类型非法")
        rebuilt = tuple(
            CninfoCorporateActionRequestSpec(
                item.schema_version,
                item.request_id,
                item.source,
                item.endpoint,
                item.adapter,
                item.parameters,
            )
            for item in self.requests
        )
        endpoints = {item.endpoint for item in rebuilt}
        if len(endpoints) != 1:
            raise ValueError("cninfo corporate-action batch 只能包含单一 endpoint")
        ordered = tuple(sorted(rebuilt, key=lambda value: value.request_id))
        if rebuilt != ordered or len({item.request_id for item in rebuilt}) != len(rebuilt):
            raise ValueError(
                "cninfo corporate-action batch requests 必须按 request_id 排序且唯一"
            )
        object.__setattr__(self, "requests", rebuilt)
        if self.batch_sha256 != _cninfo_corporate_action_batch_hash(rebuilt):
            raise ValueError("cninfo corporate-action batch_sha256 不一致")


@dataclass(frozen=True)
class G1RequestPlan:
    schema_version: Literal["m3-g1-request-plan-v3"]
    index_weight_batch: TushareRequestBatch
    history_batch: TushareRequestBatch
    cninfo_rights_batch: CninfoRequestBatch
    cninfo_dividend_batch: CninfoCorporateActionRequestBatch
    cninfo_share_change_batch: CninfoCorporateActionRequestBatch
    plan_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-request-plan-v3":
            raise ValueError("plan schema_version 非法")
        if not isinstance(self.index_weight_batch, TushareRequestBatch) or not isinstance(
            self.history_batch, TushareRequestBatch
        ):
            raise ValueError("plan batch 类型非法")
        if not isinstance(self.cninfo_rights_batch, CninfoRequestBatch):
            raise ValueError("plan cninfo_rights_batch 类型非法")
        if not isinstance(self.cninfo_dividend_batch, CninfoCorporateActionRequestBatch):
            raise ValueError("plan cninfo_dividend_batch 类型非法")
        if not isinstance(
            self.cninfo_share_change_batch, CninfoCorporateActionRequestBatch
        ):
            raise ValueError("plan cninfo_share_change_batch 类型非法")
        TushareRequestBatch(
            self.index_weight_batch.schema_version,
            self.index_weight_batch.phase,
            self.index_weight_batch.requests,
            self.index_weight_batch.batch_sha256,
        )
        TushareRequestBatch(
            self.history_batch.schema_version,
            self.history_batch.phase,
            self.history_batch.requests,
            self.history_batch.batch_sha256,
        )
        CninfoRequestBatch(
            self.cninfo_rights_batch.schema_version,
            self.cninfo_rights_batch.phase,
            self.cninfo_rights_batch.requests,
            self.cninfo_rights_batch.batch_sha256,
        )
        CninfoCorporateActionRequestBatch(
            self.cninfo_dividend_batch.schema_version,
            self.cninfo_dividend_batch.phase,
            self.cninfo_dividend_batch.requests,
            self.cninfo_dividend_batch.batch_sha256,
        )
        CninfoCorporateActionRequestBatch(
            self.cninfo_share_change_batch.schema_version,
            self.cninfo_share_change_batch.phase,
            self.cninfo_share_change_batch.requests,
            self.cninfo_share_change_batch.batch_sha256,
        )
        if self.index_weight_batch.phase != "INDEX_WEIGHT" or self.history_batch.phase != "HISTORY":
            raise ValueError("plan batch phase 非法")
        if any(
            item.endpoint != CNINFO_DIVIDEND_ENDPOINT
            for item in self.cninfo_dividend_batch.requests
        ):
            raise ValueError("plan cninfo_dividend_batch endpoint 非法")
        if any(
            item.endpoint != CNINFO_SHARE_CHANGE_ENDPOINT
            for item in self.cninfo_share_change_batch.requests
        ):
            raise ValueError("plan cninfo_share_change_batch endpoint 非法")
        ids = [
            item.request_id
            for batch in (self.index_weight_batch, self.history_batch)
            for item in batch.requests
        ]
        ids.extend(item.request_id for item in self.cninfo_rights_batch.requests)
        ids.extend(item.request_id for item in self.cninfo_dividend_batch.requests)
        ids.extend(item.request_id for item in self.cninfo_share_change_batch.requests)
        if len(ids) != len(set(ids)):
            raise ValueError("plan 含跨 batch request_id 冲突")
        if self.plan_sha256 != _plan_hash(
            self.index_weight_batch,
            self.history_batch,
            self.cninfo_rights_batch,
            self.cninfo_dividend_batch,
            self.cninfo_share_change_batch,
        ):
            raise ValueError("plan_sha256 不一致")


@dataclass(frozen=True)
class TushareRequestIntentV1:
    schema_version: Literal["m3-g1-tushare-intent-v1"]
    request_id: str
    endpoint: str
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

    def __post_init__(self) -> None:
        spec = TushareRequestSpec(
            "m3-g1-tushare-request-v1",
            self.request_id,
            cast(TushareEndpoint, self.endpoint),
            self.parameters,
        )
        if self.schema_version != "m3-g1-tushare-intent-v1":
            raise ValueError("intent schema_version 非法")
        if self.parameters_sha256 != _parameters_hash(spec.parameters):
            raise ValueError("intent parameters_sha256 不一致")


@dataclass(frozen=True)
class TushareRawCandidateV1:
    schema_version: Literal["m3-g1-tushare-candidate-v1"]
    request_id: str
    endpoint: str
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
        if self.schema_version != "m3-g1-tushare-candidate-v1":
            raise ValueError("candidate schema_version 非法")
        _validate_endpoint(self.endpoint)
        for value in (
            self.request_id,
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


@dataclass(frozen=True)
class TushareRequestReceipt:
    schema_version: Literal["m3-g1-tushare-receipt-v1"]
    request_id: str
    endpoint: str
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
        spec = TushareRequestSpec(
            "m3-g1-tushare-request-v1",
            self.request_id,
            cast(TushareEndpoint, self.endpoint),
            self.parameters,
        )
        if self.schema_version != "m3-g1-tushare-receipt-v1":
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
        if self.stable_response_sha256 != _stable_response_hash(self):
            raise ValueError("stable_response_sha256 不一致")


@dataclass(frozen=True)
class CninfoRequestIntentV1:
    schema_version: Literal["m3-g1-cninfo-intent-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_allotment"]
    adapter: Literal["akshare_cninfo_p_stock2232_v1"]
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

    def __post_init__(self) -> None:
        spec = CninfoRequestSpec(
            "m3-g1-cninfo-request-v1",
            self.request_id,
            self.source,
            self.endpoint,
            self.adapter,
            self.parameters,
        )
        if self.schema_version != "m3-g1-cninfo-intent-v1":
            raise ValueError("cninfo intent schema_version 非法")
        if self.parameters_sha256 != _parameters_hash(spec.parameters):
            raise ValueError("cninfo intent parameters_sha256 不一致")


@dataclass(frozen=True)
class CninfoRawCandidateV1:
    schema_version: Literal["m3-g1-cninfo-candidate-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_allotment"]
    adapter: Literal["akshare_cninfo_p_stock2232_v1"]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    resultcode: int
    count: int
    total: int
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-cninfo-candidate-v1":
            raise ValueError("cninfo candidate schema_version 非法")
        if (
            self.source != CNINFO_SOURCE
            or self.endpoint != CNINFO_ENDPOINT
            or self.adapter != CNINFO_ADAPTER
        ):
            raise ValueError("cninfo candidate identity 非法")
        for value in (
            self.request_id,
            self.parameters_sha256,
            self.raw_snapshot_id,
            self.raw_file_sha256,
            self.raw_metadata_sha256,
            self.response_content_sha256,
        ):
            _validate_hex(value)
        if self.raw_snapshot_id != self.request_id:
            raise ValueError("cninfo candidate raw_snapshot_id 与 request_id 不一致")
        _validate_relative(self.raw_data_path)
        _validate_relative(self.raw_metadata_path)
        _validate_counts(self.raw_size_bytes, self.row_count, self.columns)
        if self.columns != CNINFO_STOCK_ALLOTMENT_FIELDS:
            raise ValueError("cninfo candidate columns 非法")
        if self.resultcode != 200 or self.count != self.total or self.count != self.row_count:
            raise ValueError("cninfo candidate 计数元数据非法")
        if self.count < 0:
            raise ValueError("cninfo candidate count 非法")


@dataclass(frozen=True)
class CninfoRequestReceipt:
    schema_version: Literal["m3-g1-cninfo-receipt-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_allotment"]
    adapter: Literal["akshare_cninfo_p_stock2232_v1"]
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    stable_response_sha256: str
    resultcode: int
    count: int
    total: int
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        spec = CninfoRequestSpec(
            "m3-g1-cninfo-request-v1",
            self.request_id,
            self.source,
            self.endpoint,
            self.adapter,
            self.parameters,
        )
        if self.schema_version != "m3-g1-cninfo-receipt-v1":
            raise ValueError("cninfo receipt schema_version 非法")
        if self.parameters_sha256 != _parameters_hash(spec.parameters):
            raise ValueError("cninfo receipt parameters_sha256 不一致")
        for value in (
            self.raw_snapshot_id,
            self.raw_file_sha256,
            self.raw_metadata_sha256,
            self.response_content_sha256,
            self.stable_response_sha256,
        ):
            _validate_hex(value)
        if self.raw_snapshot_id != self.request_id:
            raise ValueError("cninfo receipt raw_snapshot_id 与 request_id 不一致")
        _validate_relative(self.raw_data_path)
        _validate_relative(self.raw_metadata_path)
        _validate_counts(self.raw_size_bytes, self.row_count, self.columns)
        if self.columns != CNINFO_STOCK_ALLOTMENT_FIELDS:
            raise ValueError("cninfo receipt columns 非法")
        if self.resultcode != 200 or self.count != self.total or self.count != self.row_count:
            raise ValueError("cninfo receipt 计数元数据非法")
        if self.stable_response_sha256 != _cninfo_stable_response_hash(self):
            raise ValueError("cninfo stable_response_sha256 不一致")


@dataclass(frozen=True)
class VerifiedCninfoRawResponse:
    spec: CninfoRequestSpec
    receipt: CninfoRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame
    resultcode: int
    count: int
    total: int

    def __post_init__(self) -> None:
        if type(self.spec) is not CninfoRequestSpec or type(self.receipt) is not CninfoRequestReceipt:
            raise ValueError("verified cninfo spec/receipt 类型非法")
        rebuilt_spec = CninfoRequestSpec(
            self.spec.schema_version,
            self.spec.request_id,
            self.spec.source,
            self.spec.endpoint,
            self.spec.adapter,
            self.spec.parameters,
        )
        rebuilt_receipt = CninfoRequestReceipt(**asdict(self.receipt))
        if (
            rebuilt_receipt.request_id != rebuilt_spec.request_id
            or rebuilt_receipt.endpoint != rebuilt_spec.endpoint
            or rebuilt_receipt.parameters != rebuilt_spec.parameters
        ):
            raise ValueError("verified cninfo spec/receipt 不一致")
        expected_receipt_hash = _sha256(asdict(rebuilt_receipt))
        if self.receipt_sha256 != expected_receipt_hash:
            raise ValueError("verified cninfo receipt_sha256 不一致")
        if not isinstance(self.frame, pl.DataFrame):
            raise ValueError("verified cninfo frame 类型非法")
        if (
            self.frame.height != rebuilt_receipt.row_count
            or tuple(self.frame.columns) != rebuilt_receipt.columns
        ):
            raise ValueError("verified cninfo frame/receipt 不一致")
        if cninfo_response_content_sha256(self.frame) != rebuilt_receipt.response_content_sha256:
            raise ValueError("verified cninfo frame content digest 不一致")
        if (
            self.resultcode != rebuilt_receipt.resultcode
            or self.count != rebuilt_receipt.count
            or self.total != rebuilt_receipt.total
        ):
            raise ValueError("verified cninfo 计数元数据不一致")
        object.__setattr__(self, "spec", rebuilt_spec)
        object.__setattr__(self, "receipt", rebuilt_receipt)


@dataclass(frozen=True)
class CninfoBatchExecutionResult:
    receipts: tuple[CninfoRequestReceipt, ...]
    new_requests_committed: int

    def __post_init__(self) -> None:
        if type(self.receipts) is not tuple or any(
            type(item) is not CninfoRequestReceipt for item in self.receipts
        ):
            raise ValueError("cninfo execution receipts 非法")
        if type(self.new_requests_committed) is not int or self.new_requests_committed < 0:
            raise ValueError("cninfo new_requests_committed 非法")



@dataclass(frozen=True)
class CninfoCorporateActionRequestIntentV1:
    schema_version: Literal["m3-g1-cninfo-corporate-action-intent-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_dividend", "stock_share_change"]
    adapter: Literal[
        "akshare_cninfo_p_sysapi1139_v1", "akshare_cninfo_p_stock2215_v1"
    ]
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str

    def __post_init__(self) -> None:
        spec = CninfoCorporateActionRequestSpec(
            "m3-g1-cninfo-corporate-action-request-v1",
            self.request_id,
            self.source,
            self.endpoint,
            self.adapter,
            self.parameters,
        )
        if self.schema_version != "m3-g1-cninfo-corporate-action-intent-v1":
            raise ValueError("cninfo corporate-action intent schema_version 非法")
        if self.parameters_sha256 != _parameters_hash(spec.parameters):
            raise ValueError("cninfo corporate-action intent parameters_sha256 不一致")


@dataclass(frozen=True)
class _CninfoCorporateActionRawSnapshot:
    """Strictly verified immutable JSON raw pair for one CNINFO CA request."""

    snapshot_id: str
    data_path: Path
    metadata_path: Path
    checksum_sha256: str
    metadata_sha256: str
    size_bytes: int
    row_count: int
    columns: tuple[str, ...]
    resultcode: int
    resultmsg: str
    count: int
    total: int


@dataclass(frozen=True)
class CninfoCorporateActionRawCandidateV1:
    schema_version: Literal["m3-g1-cninfo-corporate-action-candidate-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_dividend", "stock_share_change"]
    adapter: Literal[
        "akshare_cninfo_p_sysapi1139_v1", "akshare_cninfo_p_stock2215_v1"
    ]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    resultcode: int
    resultmsg: str
    count: int
    total: int
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "m3-g1-cninfo-corporate-action-candidate-v1":
            raise ValueError("cninfo corporate-action candidate schema_version 非法")
        expected_adapter = _ca_adapter_for_endpoint(self.endpoint)
        if self.source != CNINFO_SOURCE or self.adapter != expected_adapter:
            raise ValueError("cninfo corporate-action candidate identity 非法")
        for value in (
            self.request_id,
            self.parameters_sha256,
            self.raw_snapshot_id,
            self.raw_file_sha256,
            self.raw_metadata_sha256,
            self.response_content_sha256,
        ):
            _validate_hex(value)
        if self.raw_snapshot_id != self.request_id:
            raise ValueError(
                "cninfo corporate-action candidate raw_snapshot_id 与 request_id 不一致"
            )
        _validate_relative(self.raw_data_path)
        _validate_relative(self.raw_metadata_path)
        _validate_counts(self.raw_size_bytes, self.row_count, self.columns)
        expected_fields = _ca_fields_for_endpoint(self.endpoint)
        if self.columns != expected_fields:
            raise ValueError("cninfo corporate-action candidate columns 非法")
        if (
            self.resultcode != 200
            or self.resultmsg != "success"
            or self.count != self.total
            or self.count != self.row_count
        ):
            raise ValueError("cninfo corporate-action candidate 计数元数据非法")
        if self.count < 0:
            raise ValueError("cninfo corporate-action candidate count 非法")


@dataclass(frozen=True)
class CninfoCorporateActionRequestReceipt:
    schema_version: Literal["m3-g1-cninfo-corporate-action-receipt-v1"]
    request_id: str
    source: Literal["cninfo"]
    endpoint: Literal["stock_dividend", "stock_share_change"]
    adapter: Literal[
        "akshare_cninfo_p_sysapi1139_v1", "akshare_cninfo_p_stock2215_v1"
    ]
    parameters: tuple[tuple[str, str], ...]
    parameters_sha256: str
    raw_snapshot_id: str
    raw_data_path: str
    raw_metadata_path: str
    raw_file_sha256: str
    raw_metadata_sha256: str
    response_content_sha256: str
    stable_response_sha256: str
    resultcode: int
    resultmsg: str
    count: int
    total: int
    raw_size_bytes: int
    row_count: int
    columns: tuple[str, ...]

    def __post_init__(self) -> None:
        spec = CninfoCorporateActionRequestSpec(
            "m3-g1-cninfo-corporate-action-request-v1",
            self.request_id,
            self.source,
            self.endpoint,
            self.adapter,
            self.parameters,
        )
        if self.schema_version != "m3-g1-cninfo-corporate-action-receipt-v1":
            raise ValueError("cninfo corporate-action receipt schema_version 非法")
        if self.parameters_sha256 != _parameters_hash(spec.parameters):
            raise ValueError("cninfo corporate-action receipt parameters_sha256 不一致")
        for value in (
            self.raw_snapshot_id,
            self.raw_file_sha256,
            self.raw_metadata_sha256,
            self.response_content_sha256,
            self.stable_response_sha256,
        ):
            _validate_hex(value)
        if self.raw_snapshot_id != self.request_id:
            raise ValueError(
                "cninfo corporate-action receipt raw_snapshot_id 与 request_id 不一致"
            )
        _validate_relative(self.raw_data_path)
        _validate_relative(self.raw_metadata_path)
        _validate_counts(self.raw_size_bytes, self.row_count, self.columns)
        if self.columns != _ca_fields_for_endpoint(self.endpoint):
            raise ValueError("cninfo corporate-action receipt columns 非法")
        if (
            self.resultcode != 200
            or self.resultmsg != "success"
            or self.count != self.total
            or self.count != self.row_count
        ):
            raise ValueError("cninfo corporate-action receipt 计数元数据非法")
        if self.stable_response_sha256 != _cninfo_ca_stable_response_hash_values(
            asdict(self)
        ):
            raise ValueError("cninfo corporate-action stable_response_sha256 不一致")


@dataclass(frozen=True)
class VerifiedCninfoCorporateActionRawResponse:
    spec: CninfoCorporateActionRequestSpec
    receipt: CninfoCorporateActionRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame
    resultcode: int
    resultmsg: str
    count: int
    total: int

    def __post_init__(self) -> None:
        if (
            type(self.spec) is not CninfoCorporateActionRequestSpec
            or type(self.receipt) is not CninfoCorporateActionRequestReceipt
        ):
            raise ValueError("verified cninfo corporate-action spec/receipt 类型非法")
        rebuilt_spec = CninfoCorporateActionRequestSpec(
            self.spec.schema_version,
            self.spec.request_id,
            self.spec.source,
            self.spec.endpoint,
            self.spec.adapter,
            self.spec.parameters,
        )
        rebuilt_receipt = CninfoCorporateActionRequestReceipt(**asdict(self.receipt))
        if (
            rebuilt_receipt.request_id != rebuilt_spec.request_id
            or rebuilt_receipt.endpoint != rebuilt_spec.endpoint
            or rebuilt_receipt.adapter != rebuilt_spec.adapter
            or rebuilt_receipt.parameters != rebuilt_spec.parameters
        ):
            raise ValueError("verified cninfo corporate-action spec/receipt 不一致")
        expected_receipt_hash = _sha256(asdict(rebuilt_receipt))
        if self.receipt_sha256 != expected_receipt_hash:
            raise ValueError("verified cninfo corporate-action receipt_sha256 不一致")
        if not isinstance(self.frame, pl.DataFrame):
            raise ValueError("verified cninfo corporate-action frame 类型非法")
        if (
            self.frame.height != rebuilt_receipt.row_count
            or tuple(self.frame.columns) != rebuilt_receipt.columns
        ):
            raise ValueError("verified cninfo corporate-action frame/receipt 不一致")
        if (
            cninfo_corporate_action_response_content_sha256(
                self.frame, endpoint=rebuilt_spec.endpoint
            )
            != rebuilt_receipt.response_content_sha256
        ):
            raise ValueError(
                "verified cninfo corporate-action frame content digest 不一致"
            )
        if (
            self.resultcode != rebuilt_receipt.resultcode
            or self.resultmsg != rebuilt_receipt.resultmsg
            or self.count != rebuilt_receipt.count
            or self.total != rebuilt_receipt.total
        ):
            raise ValueError("verified cninfo corporate-action 计数元数据不一致")
        object.__setattr__(self, "spec", rebuilt_spec)
        object.__setattr__(self, "receipt", rebuilt_receipt)


@dataclass(frozen=True)
class CninfoCorporateActionBatchExecutionResult:
    receipts: tuple[CninfoCorporateActionRequestReceipt, ...]
    new_requests_committed: int

    def __post_init__(self) -> None:
        if type(self.receipts) is not tuple or any(
            type(item) is not CninfoCorporateActionRequestReceipt for item in self.receipts
        ):
            raise ValueError("cninfo corporate-action execution receipts 非法")
        if type(self.new_requests_committed) is not int or self.new_requests_committed < 0:
            raise ValueError("cninfo corporate-action new_requests_committed 非法")


@dataclass(frozen=True)
class VerifiedRawResponse:
    spec: TushareRequestSpec
    receipt: TushareRequestReceipt
    receipt_sha256: str
    frame: pl.DataFrame

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TushareRequestSpec) or not isinstance(
            self.receipt, TushareRequestReceipt
        ):
            raise ValueError("verified response spec/receipt 类型非法")
        rebuilt_spec = TushareRequestSpec(
            self.spec.schema_version,
            self.spec.request_id,
            self.spec.endpoint,
            self.spec.parameters,
        )
        rebuilt_receipt = TushareRequestReceipt(**asdict(self.receipt))
        if (
            rebuilt_receipt.request_id != rebuilt_spec.request_id
            or rebuilt_receipt.endpoint != rebuilt_spec.endpoint
            or rebuilt_receipt.parameters != rebuilt_spec.parameters
        ):
            raise ValueError("verified response spec/receipt 不一致")
        expected_receipt_hash = _sha256(asdict(rebuilt_receipt))
        if self.receipt_sha256 != expected_receipt_hash:
            raise ValueError("verified response receipt_sha256 不一致")
        if not isinstance(self.frame, pl.DataFrame):
            raise ValueError("verified response frame 类型非法")
        if self.frame.height != rebuilt_receipt.row_count or tuple(self.frame.columns) != rebuilt_receipt.columns:
            raise ValueError("verified response frame/receipt 不一致")
        if response_content_sha256(self.frame, rebuilt_spec.endpoint) != rebuilt_receipt.response_content_sha256:
            raise ValueError("verified response frame content digest 不一致")


@dataclass(frozen=True)
class HistoryWindow:
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if type(self.start) is not dt.date or type(self.end) is not dt.date or self.start > self.end:
            raise ValueError("HistoryWindow 非法")


@dataclass(frozen=True)
class _NoReceiptPreflight:
    raw_state: Literal["ABSENT", "EMPTY", "COMPLETE"]
    intent_exists: bool
    candidate_exists: bool
    mode: Literal["NETWORK", "RECOVER"]

    def __post_init__(self) -> None:
        if type(self.raw_state) is not str or self.raw_state not in {
            "ABSENT",
            "EMPTY",
            "COMPLETE",
        }:
            raise ValueError("preflight raw_state 非法")
        if type(self.intent_exists) is not bool or type(self.candidate_exists) is not bool:
            raise ValueError("preflight evidence flag 必须是 bool")
        if type(self.mode) is not str or self.mode not in {"NETWORK", "RECOVER"}:
            raise ValueError("preflight mode 非法")
        if self.mode == "NETWORK" and (
            self.raw_state not in {"ABSENT", "EMPTY"} or self.candidate_exists
        ):
            raise ValueError("preflight NETWORK closure 非法")
        if self.mode == "RECOVER" and (
            self.raw_state != "COMPLETE" or not self.intent_exists
        ):
            raise ValueError("preflight RECOVER closure 非法")


def plan_index_weight_requests(
    *, index_code: str, start: dt.date, end: dt.date, warmup_months: int
) -> TushareRequestBatch:
    if type(start) is not dt.date or type(end) is not dt.date or start > end:
        raise ValueError("signal 日期范围非法")
    if type(warmup_months) is not int or warmup_months < 0:
        raise ValueError("warmup_months 必须是非负整数")
    _validate_index_code(index_code)
    first = _shift_month(start.replace(day=1), -warmup_months)
    last = end.replace(day=1)
    requests: list[TushareRequestSpec] = []
    cursor = first
    while cursor <= last:
        month_end = _shift_month(cursor, 1) - dt.timedelta(days=1)
        requests.append(
            _make_spec(
                "index_weight",
                index_code=index_code,
                start_date=_date_text(cursor),
                end_date=_date_text(month_end),
            )
        )
        cursor = _shift_month(cursor, 1)
    return _make_batch("INDEX_WEIGHT", requests)


def resolve_history_window(
    *,
    open_dates: Sequence[dt.date],
    signal_start: dt.date,
    signal_end: dt.date,
    feature_warmup_sessions: int,
    label_tail_sessions: int,
) -> HistoryWindow:
    if type(feature_warmup_sessions) is not int or feature_warmup_sessions < 0:
        raise ValueError("feature_warmup_sessions 非法")
    if type(label_tail_sessions) is not int or label_tail_sessions < 0:
        raise ValueError("label_tail_sessions 非法")
    if type(signal_start) is not dt.date or type(signal_end) is not dt.date:
        raise ValueError("signal 边界必须是 date")
    if signal_start > signal_end:
        raise ValueError("signal 日期范围非法")
    dates = tuple(open_dates)
    if any(type(value) is not dt.date for value in dates):
        raise ValueError("open_dates 必须只含 date")
    if dates != tuple(sorted(set(dates))):
        raise ValueError("open_dates 必须严格递增且唯一")
    try:
        start_index = dates.index(signal_start)
        end_index = dates.index(signal_end)
    except ValueError as exc:
        raise ValueError("signal 边界必须是 SH 开市日") from exc
    if start_index < feature_warmup_sessions or end_index + label_tail_sessions >= len(dates):
        raise ValueError("SH 日历不足以覆盖 warmup/tail")
    return HistoryWindow(
        dates[start_index - feature_warmup_sessions],
        dates[end_index + label_tail_sessions],
    )


def plan_cninfo_rights_requests(
    *,
    symbols: Sequence[str],
    history: HistoryWindow,
    batch_size: int = 50,
) -> CninfoRequestBatch:
    """Build deterministic CNINFO rights batches (sorted unique codes, size<=50)."""
    if type(history) is not HistoryWindow:
        raise ValueError("history 非法")
    history = HistoryWindow(history.start, history.end)
    groups = batch_cninfo_symbol_groups(symbols, batch_size=batch_size)
    start_text = _date_text(history.start)
    end_text = _date_text(history.end)
    requests = tuple(
        sorted(
            (
                CninfoRequestSpec.create(
                    parameters={
                        "symbols": ",".join(group),
                        "start_date": start_text,
                        "end_date": end_text,
                    }
                )
                for group in groups
            ),
            key=lambda item: item.request_id,
        )
    )
    return CninfoRequestBatch(
        schema_version="m3-g1-cninfo-request-batch-v1",
        phase="HISTORY",
        requests=requests,
        batch_sha256=_cninfo_batch_hash(requests),
    )



def plan_cninfo_corporate_action_requests(
    *,
    symbols: Sequence[str],
    history: HistoryWindow,
) -> tuple[CninfoCorporateActionRequestBatch, CninfoCorporateActionRequestBatch]:
    """Build one dividend + one share-change request per unique A-share symbol."""
    if type(history) is not HistoryWindow:
        raise ValueError("history 非法")
    history = HistoryWindow(history.start, history.end)
    if any(type(value) is not str or not _A_SHARE.fullmatch(value) for value in symbols):
        raise ValueError("symbols 必须是六位 A 股标准代码")
    codes = normalize_cninfo_symbols(symbols)
    start_text = _date_text(history.start)
    end_text = _date_text(history.end)
    dividend_requests = tuple(
        sorted(
            (
                CninfoCorporateActionRequestSpec.create(
                    endpoint=CNINFO_DIVIDEND_ENDPOINT,
                    parameters={"symbol": code},
                )
                for code in codes
            ),
            key=lambda item: item.request_id,
        )
    )
    share_change_requests = tuple(
        sorted(
            (
                CninfoCorporateActionRequestSpec.create(
                    endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
                    parameters={
                        "symbol": code,
                        "start_date": start_text,
                        "end_date": end_text,
                    },
                )
                for code in codes
            ),
            key=lambda item: item.request_id,
        )
    )
    dividend_batch = CninfoCorporateActionRequestBatch(
        schema_version="m3-g1-cninfo-corporate-action-request-batch-v1",
        phase="HISTORY",
        requests=dividend_requests,
        batch_sha256=_cninfo_corporate_action_batch_hash(dividend_requests),
    )
    share_change_batch = CninfoCorporateActionRequestBatch(
        schema_version="m3-g1-cninfo-corporate-action-request-batch-v1",
        phase="HISTORY",
        requests=share_change_requests,
        batch_sha256=_cninfo_corporate_action_batch_hash(share_change_requests),
    )
    return dividend_batch, share_change_batch


def plan_history_requests(
    *,
    index_weight_batch: TushareRequestBatch,
    symbols: Sequence[str],
    benchmark: str,
    history: HistoryWindow,
) -> G1RequestPlan:
    if index_weight_batch.phase != "INDEX_WEIGHT":
        raise ValueError("index_weight_batch phase 非法")
    _validate_index_code(benchmark)
    if any(type(value) is not str or not _A_SHARE.fullmatch(value) for value in symbols):
        raise ValueError("symbols 必须是六位 A 股标准代码")
    normalized_symbols = tuple(sorted(set(symbols)))
    if not normalized_symbols:
        raise ValueError("历史成分并集不能为空")
    requests: list[TushareRequestSpec] = []
    for symbol in normalized_symbols:
        common = {
            "ts_code": symbol,
            "start_date": _date_text(history.start),
            "end_date": _date_text(history.end),
        }
        for endpoint in ("daily", "adj_factor", "stk_limit"):
            requests.append(_make_spec(endpoint, **common))
        requests.append(_make_spec("dividend", ts_code=symbol))
        requests.append(_make_spec("suspend_d", **common, suspend_type="S"))
    requests.append(
        _make_spec(
            "index_daily",
            ts_code=benchmark,
            start_date=_date_text(history.start),
            end_date=_date_text(history.end),
        )
    )
    history_batch = _make_batch("HISTORY", requests)
    cninfo_rights_batch = plan_cninfo_rights_requests(
        symbols=normalized_symbols, history=history
    )
    cninfo_dividend_batch, cninfo_share_change_batch = plan_cninfo_corporate_action_requests(
        symbols=normalized_symbols, history=history
    )
    return G1RequestPlan(
        schema_version="m3-g1-request-plan-v3",
        index_weight_batch=index_weight_batch,
        history_batch=history_batch,
        cninfo_rights_batch=cninfo_rights_batch,
        cninfo_dividend_batch=cninfo_dividend_batch,
        cninfo_share_change_batch=cninfo_share_change_batch,
        plan_sha256=_plan_hash(
            index_weight_batch,
            history_batch,
            cninfo_rights_batch,
            cninfo_dividend_batch,
            cninfo_share_change_batch,
        ),
    )


def plan_fund_adj_requests(
    *, symbol: str, start: dt.date, end: dt.date
) -> tuple[TushareRequestSpec, ...]:
    """按至多四个完整自然年切分 fund_adj 请求；区间连续、不重叠、严格递增。"""
    if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
        raise ValueError("fund 证券代码非法")
    if type(start) is not dt.date or type(end) is not dt.date:
        raise ValueError("fund_adj 日期必须是 date")
    if start > end:
        raise ValueError("fund_adj 日期范围非法")
    requests: list[TushareRequestSpec] = []
    cursor = start
    while cursor <= end:
        segment_end = min(end, dt.date(cursor.year + 3, 12, 31))
        if (segment_end - cursor).days + 1 > 1461:
            raise AssertionError("fund_adj 分段超过 1461 自然日")
        requests.append(
            _make_spec(
                "fund_adj",
                ts_code=symbol,
                start_date=_date_text(cursor),
                end_date=_date_text(segment_end),
            )
        )
        cursor = dt.date(segment_end.year + 1, 1, 1)
    return tuple(requests)


@dataclass(frozen=True)
class TushareBatchExecutionResult:
    """One batch run: verified receipts plus newly committed request identities."""

    receipts: tuple[TushareRequestReceipt, ...]
    new_requests_committed: int

    def __post_init__(self) -> None:
        if type(self.receipts) is not tuple or any(
            type(item) is not TushareRequestReceipt for item in self.receipts
        ):
            raise ValueError("batch execution receipts \u975e\u6cd5")
        if type(self.new_requests_committed) is not int or self.new_requests_committed < 0:
            raise ValueError("new_requests_committed \u5fc5\u987b\u662f\u975e\u8d1f\u6574\u6570")
        if self.new_requests_committed > len(self.receipts):
            raise ValueError("new_requests_committed \u8d85\u8fc7 receipts")


def _validate_max_new_requests(value: int | None) -> int | None:
    """Reject negative/non-int; allow 0 for exhausted shared HISTORY budget."""
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("max_new_requests \u5fc5\u987b\u662f\u975e\u8d1f\u6574\u6570")
    return value


def execute_tushare_batch(
    *,
    batch: TushareRequestBatch,
    connector: TushareConnector,
    raw_store: RawStore,
    journal_root: Path,
    endpoint_policies: Mapping[str, EndpointPolicy],
    request_rate_per_minute: int,
    max_attempts: int,
    retry_base_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    classify_error: Callable[[BaseException], str],
    max_new_requests: int | None = None,
) -> TushareBatchExecutionResult:
    bound = _validate_max_new_requests(max_new_requests)
    # Reconstruct first: malformed caller-owned objects fail before filesystem IO.
    _validate_batch_again(batch)
    _validate_policies(endpoint_policies)
    if type(request_rate_per_minute) is not int or request_rate_per_minute <= 0:
        raise ValueError("request_rate_per_minute 必须是正整数")
    if type(max_attempts) is not int or max_attempts <= 0:
        raise ValueError("max_attempts 必须是正整数")
    if type(retry_base_seconds) not in {int, float} or not math.isfinite(
        float(retry_base_seconds)
    ) or retry_base_seconds < 0:
        raise ValueError("retry_base_seconds 必须是非负 finite 数")
    _preflight_controlled_root(raw_store.root)
    _preflight_controlled_root(journal_root)
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise M3BackfillError("JOURNAL_ROOT_CREATE_FAILED") from None
    _preflight_controlled_root(journal_root)
    try:
        with hold_journal_writer_lock(journal_root=journal_root):
            return _execute_tushare_batch_locked(
                batch=batch,
                connector=connector,
                raw_store=raw_store,
                journal_root=journal_root,
                endpoint_policies=endpoint_policies,
                request_rate_per_minute=request_rate_per_minute,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
                monotonic=monotonic,
                sleep=sleep,
                classify_error=classify_error,
                max_new_requests=bound,
            )
    except M3JournalLockError as exc:
        raise _map_journal_lock_error(exc) from None


def _request_dir_exists(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return False
    except OSError:
        raise M3BackfillError("JOURNAL_LAYOUT_INSPECTION_FAILED") from None
    if stat.S_ISLNK(mode):
        raise M3BackfillError("JOURNAL_UNKNOWN_OR_NON_REGULAR_ENTRY")
    if not stat.S_ISDIR(mode):
        raise M3BackfillError("JOURNAL_UNKNOWN_OR_NON_REGULAR_ENTRY")
    return True


def _execute_tushare_batch_locked(
    *,
    batch: TushareRequestBatch,
    connector: TushareConnector,
    raw_store: RawStore,
    journal_root: Path,
    endpoint_policies: Mapping[str, EndpointPolicy],
    request_rate_per_minute: int,
    max_attempts: int,
    retry_base_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    classify_error: Callable[[BaseException], str],
    max_new_requests: int | None,
) -> TushareBatchExecutionResult:
    receipts: list[TushareRequestReceipt] = []
    new_requests_committed = 0
    last_attempt_started: float | None = None
    interval = 60.0 / request_rate_per_minute
    for spec in batch.requests:
        request_dir = journal_root / spec.request_id
        _reject_path_symlinks(journal_root, request_dir)
        budget_exhausted = (
            max_new_requests is not None and new_requests_committed >= max_new_requests
        )
        dir_exists = _request_dir_exists(request_dir)
        if not dir_exists:
            if budget_exhausted:
                continue
            try:
                request_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise M3BackfillError("JOURNAL_REQUEST_DIR_CREATE_FAILED") from None
            _reject_path_symlinks(journal_root, request_dir)
        _validate_journal_files(request_dir)
        intent_path = request_dir / "intent.json"
        candidate_path = request_dir / "candidate.json"
        receipt_path = request_dir / "receipt.json"
        if receipt_path.exists():
            if not intent_path.exists() or not candidate_path.exists():
                raise M3BackfillError("COMMITTED_JOURNAL_INCOMPLETE")
            _verify_existing_intent(intent_path, spec)
            committed_candidate = _recover_candidate(
                spec=spec,
                candidate_path=candidate_path,
                raw_store=raw_store,
                policy=endpoint_policies[spec.endpoint],
                expected_mode="RECOVER",
                expected_candidate_exists=True,
            )
            assert committed_candidate is not None
            verified = verify_tushare_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_store.root,
                journal_root=journal_root,
                policy=endpoint_policies[spec.endpoint],
            )
            if verified.receipt != _receipt_from_candidate(spec, committed_candidate):
                raise M3BackfillError("COMMITTED_JOURNAL_CONFLICT")
            receipts.append(verified.receipt)
            continue
        preflight = _preflight_no_receipt(
            spec=spec,
            intent_path=intent_path,
            candidate_path=candidate_path,
            raw_store=raw_store,
        )
        if budget_exhausted:
            continue
        if not preflight.intent_exists:
            _ensure_intent(intent_path, spec)
        candidate = _recover_candidate(
            spec=spec,
            candidate_path=candidate_path,
            raw_store=raw_store,
            policy=endpoint_policies[spec.endpoint],
            expected_mode=preflight.mode,
            expected_candidate_exists=preflight.candidate_exists,
        )
        if (preflight.mode == "NETWORK") != (candidate is None):
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        if candidate is None:
            frame: pl.DataFrame | None = None
            for attempt in range(1, max_attempts + 1):
                if last_attempt_started is not None:
                    now = monotonic()
                    rate_deadline = last_attempt_started + interval
                    if now < rate_deadline:
                        sleep(rate_deadline - now)
                attempt_started = monotonic()
                last_attempt_started = attempt_started
                try:
                    frame = _fetch(connector, spec)
                    break
                except BaseException as exc:
                    category = _safe_classify(classify_error, exc)
                    if category not in {"NETWORK", "RATE_LIMIT", "TRANSIENT_SERVER"}:
                        raise M3BackfillError("TUSHARE_REQUEST_PERMANENT_FAILURE") from None
                    if attempt == max_attempts:
                        raise M3BackfillError("TUSHARE_REQUEST_ATTEMPTS_EXHAUSTED") from None
                    failure_time = monotonic()
                    rate_deadline = attempt_started + interval
                    backoff_deadline = failure_time + float(retry_base_seconds) * 2 ** (
                        attempt - 1
                    )
                    now = monotonic()
                    deadline = max(rate_deadline, backoff_deadline)
                    if now < deadline:
                        sleep(deadline - now)
                    # The generic rate wait above must not wait twice.
                    last_attempt_started = deadline - interval
            assert frame is not None
            _validate_frame(frame, spec, endpoint_policies[spec.endpoint])
            try:
                snapshot = raw_store.write_request(
                    source="tushare",
                    table=spec.endpoint,
                    request_id=spec.request_id,
                    frame=frame,
                    parameters=dict(spec.parameters),
                    after_data_write=lambda: _fault_point("after_data"),
                    after_metadata_write=lambda: _fault_point("after_metadata"),
                )
            except (OSError, ValueError):
                raise M3BackfillError("RAW_WRITE_CONFLICT") from None
            candidate = _candidate_from_snapshot(spec, snapshot, frame, raw_store.root)
            _write_dataclass_once(candidate_path, candidate)
            _fault_point("after_candidate")
        receipt = _receipt_from_candidate(spec, candidate)
        _fault_point("before_receipt")
        _write_dataclass_once(receipt_path, receipt)
        receipts.append(
            verify_tushare_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_store.root,
                journal_root=journal_root,
                policy=endpoint_policies[spec.endpoint],
            ).receipt
        )
        new_requests_committed += 1
    return TushareBatchExecutionResult(
        receipts=tuple(receipts), new_requests_committed=new_requests_committed
    )


def _map_journal_lock_error(exc: M3JournalLockError) -> M3BackfillError:
    code = exc.code
    if code == "JOURNAL_WRITER_ACTIVE":
        return M3BackfillError("JOURNAL_WRITER_ACTIVE")
    if code in {
        "JOURNAL_LOCK_INPUT_INVALID",
        "JOURNAL_LOCK_ROOT_INVALID",
    }:
        return M3BackfillError("CONTROLLED_ROOT_INVALID")
    if code == "JOURNAL_LOCK_FILE_INVALID":
        return M3BackfillError("JOURNAL_UNKNOWN_OR_NON_REGULAR_ENTRY")
    if code == "JOURNAL_LOCK_IO_FAILED":
        return M3BackfillError("JOURNAL_LOCK_OPEN_FAILED")
    if code == "JOURNAL_LOCK_RELEASE_FAILED":
        return M3BackfillError("JOURNAL_LOCK_CLEANUP_FAILED")
    return M3BackfillError("JOURNAL_LOCK_OPEN_FAILED")


def verify_tushare_receipt(
    *,
    spec: TushareRequestSpec,
    receipt_path: Path,
    raw_root: Path,
    journal_root: Path,
    policy: EndpointPolicy,
) -> VerifiedRawResponse:
    expected_path = journal_root / spec.request_id / "receipt.json"
    if receipt_path != expected_path:
        raise M3BackfillError("RECEIPT_PATH_INVALID")
    _reject_path_symlinks(journal_root, receipt_path)
    payload = _read_bytes(receipt_path, "RECEIPT_INVALID")
    try:
        receipt = _receipt_from_dict(_strict_json(payload))
    except (TypeError, ValueError, KeyError):
        raise M3BackfillError("RECEIPT_INVALID") from None
    if receipt.request_id != spec.request_id or receipt.endpoint != spec.endpoint or receipt.parameters != spec.parameters:
        raise M3BackfillError("RECEIPT_SPEC_MISMATCH")
    data_path = _resolve_relative(raw_root, receipt.raw_data_path)
    metadata_path = _resolve_relative(raw_root, receipt.raw_metadata_path)
    try:
        snapshot, frame = RawStore(raw_root).verify_request_bundle(
            source="tushare",
            table=spec.endpoint,
            request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
    except (OSError, ValueError):
        raise M3BackfillError("RECEIPT_RAW_INVALID") from None
    if data_path != snapshot.data_path or metadata_path != snapshot.metadata_path:
        raise M3BackfillError("RECEIPT_RAW_PATH_MISMATCH")
    _validate_frame(frame, spec, policy)
    content_hash = response_content_sha256(frame, spec.endpoint)
    if (
        receipt.raw_snapshot_id != snapshot.snapshot_id
        or receipt.raw_file_sha256 != snapshot.checksum_sha256
        or receipt.raw_metadata_sha256 != snapshot.metadata_sha256
        or receipt.raw_size_bytes != snapshot.size_bytes
        or receipt.row_count != snapshot.row_count
        or receipt.columns != snapshot.columns
        or receipt.response_content_sha256 != content_hash
    ):
        raise M3BackfillError("RECEIPT_RAW_EVIDENCE_MISMATCH")
    try:
        return VerifiedRawResponse(spec, receipt, hashlib.sha256(payload).hexdigest(), frame)
    except ValueError:
        raise M3BackfillError("RECEIPT_CANONICAL_BYTES_MISMATCH") from None


def response_content_sha256(frame: pl.DataFrame, endpoint: str) -> str:
    """Hash logical response content independently from Parquet bytes and row order."""
    _validate_endpoint(endpoint)
    columns = [
        {"name": name, "dtype": str(dtype)}
        for name, dtype in zip(frame.columns, frame.dtypes, strict=True)
    ]
    rows: list[tuple[str, list[list[Any]]]] = []
    for row in frame.iter_rows(named=True):
        canonical_row = [_canonical_scalar(row[name]) for name in frame.columns]
        business_key = [_canonical_scalar(row[name]) for name in _RESPONSE_SORT_KEYS[endpoint]]
        rows.append((_canonical_json([business_key, canonical_row]), canonical_row))
    rows.sort(key=lambda item: item[0])
    return _sha256(
        {"endpoint": endpoint, "columns": columns, "rows": [item[1] for item in rows]}
    )


def _make_spec(endpoint: str, **parameters: str) -> TushareRequestSpec:
    return TushareRequestSpec.create(
        endpoint=endpoint, parameters={**parameters, "fields": TUSHARE_FIELDS[endpoint]}
    )


def _make_batch(
    phase: Literal["INDEX_WEIGHT", "HISTORY"], requests: Sequence[TushareRequestSpec]
) -> TushareRequestBatch:
    ordered = tuple(sorted(requests, key=lambda value: value.request_id))
    return TushareRequestBatch(
        "m3-g1-tushare-request-batch-v1", phase, ordered, _batch_hash(phase, ordered)
    )


def _fetch(connector: TushareConnector, spec: TushareRequestSpec) -> pl.DataFrame:
    values = dict(spec.parameters)
    fields = values["fields"]
    if spec.endpoint == "index_weight":
        return connector.fetch_index_weight_raw(
            index_code=values["index_code"],
            start=_parse_date(values["start_date"]),
            end=_parse_date(values["end_date"]),
            fields=fields,
        )
    if spec.endpoint in {"daily", "adj_factor", "stk_limit"}:
        method = {
            "daily": connector.fetch_daily_raw,
            "adj_factor": connector.fetch_adj_factor_raw,
            "stk_limit": connector.fetch_stk_limit_raw,
        }[spec.endpoint]
        return method(
            symbol=values["ts_code"],
            start=_parse_date(values["start_date"]),
            end=_parse_date(values["end_date"]),
            fields=fields,
        )
    if spec.endpoint == "index_daily":
        return connector.fetch_index_daily_raw(
            index_code=values["ts_code"],
            start=_parse_date(values["start_date"]),
            end=_parse_date(values["end_date"]),
            fields=fields,
        )
    if spec.endpoint == "suspend_d":
        return connector.fetch_suspend_raw(
            symbol=values["ts_code"],
            start=_parse_date(values["start_date"]),
            end=_parse_date(values["end_date"]),
            fields=fields,
        )
    if spec.endpoint == "dividend":
        return connector.fetch_dividend_raw(symbol=values["ts_code"], fields=fields)
    if spec.endpoint == "fund_daily":
        return connector.fetch_fund_daily_raw(
            symbol=values["ts_code"],
            start=_parse_date(values["start_date"]),
            end=_parse_date(values["end_date"]),
            fields=fields,
        )
    if spec.endpoint == "fund_adj":
        return connector.fetch_fund_adj_raw(
            symbol=values["ts_code"],
            start=_parse_date(values["start_date"]),
            end=_parse_date(values["end_date"]),
            fields=fields,
        )
    if spec.endpoint == "fund_div":
        return connector.fetch_fund_div_raw(symbol=values["ts_code"], fields=fields)
    raise AssertionError("unreachable")


def _recover_candidate(
    *,
    spec: TushareRequestSpec,
    candidate_path: Path,
    raw_store: RawStore,
    policy: EndpointPolicy,
    expected_mode: Literal["NETWORK", "RECOVER"],
    expected_candidate_exists: bool,
) -> TushareRawCandidateV1 | None:
    candidate_exists = _regular_file_exists(candidate_path)
    if candidate_exists != expected_candidate_exists:
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
    try:
        state = raw_store.inspect_request_state(
            source="tushare", table=spec.endpoint, request_id=spec.request_id
        )
    except (OSError, ValueError):
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None

    if expected_mode == "NETWORK":
        if candidate_exists or state == "COMPLETE":
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        return None
    if state != "COMPLETE":
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
    if candidate_exists:
        try:
            candidate = _candidate_from_dict(_strict_json(_read_bytes(candidate_path, "CANDIDATE_INVALID")))
        except (TypeError, ValueError, KeyError):
            raise M3BackfillError("CANDIDATE_INVALID") from None
        return _verify_candidate(spec, candidate, raw_store, policy)
    try:
        snapshot, frame = raw_store.verify_request_bundle(
            source="tushare",
            table=spec.endpoint,
            request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
        _validate_frame(frame, spec, policy)
        candidate = _candidate_from_snapshot(spec, snapshot, frame, raw_store.root)
        current_state = raw_store.inspect_request_state(
            source="tushare", table=spec.endpoint, request_id=spec.request_id
        )
        if current_state != "COMPLETE":
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        _verify_candidate(spec, candidate, raw_store, policy)
        if _regular_file_exists(candidate_path):
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        _write_dataclass_once(candidate_path, candidate)
        return candidate
    except (OSError, ValueError):
        raise M3BackfillError("RAW_RECOVERY_INVALID") from None


def _preflight_no_receipt(
    *,
    spec: TushareRequestSpec,
    intent_path: Path,
    candidate_path: Path,
    raw_store: RawStore,
) -> _NoReceiptPreflight:
    """Read-only closure check that must pass before intent publication."""
    try:
        raw_state = raw_store.inspect_request_state(
            source="tushare", table=spec.endpoint, request_id=spec.request_id
        )
        intent_exists = _regular_file_exists(intent_path)
        candidate_exists = _regular_file_exists(candidate_path)
    except (OSError, ValueError):
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None

    if candidate_exists and (not intent_exists or raw_state != "COMPLETE"):
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if raw_state == "COMPLETE" and not intent_exists:
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if intent_exists:
        _verify_existing_intent(intent_path, spec)

    mode: Literal["NETWORK", "RECOVER"] = (
        "RECOVER" if raw_state == "COMPLETE" else "NETWORK"
    )
    return _NoReceiptPreflight(raw_state, intent_exists, candidate_exists, mode)


def _regular_file_exists(path: Path) -> bool:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return False
    except OSError:
        raise M3BackfillError("JOURNAL_LAYOUT_INSPECTION_FAILED") from None
    if not stat.S_ISREG(mode):
        raise M3BackfillError("JOURNAL_UNKNOWN_OR_NON_REGULAR_ENTRY")
    return True


def _verify_candidate(
    spec: TushareRequestSpec,
    candidate: TushareRawCandidateV1,
    raw_store: RawStore,
    policy: EndpointPolicy,
) -> TushareRawCandidateV1:
    if (
        candidate.request_id != spec.request_id
        or candidate.endpoint != spec.endpoint
        or candidate.parameters_sha256 != _parameters_hash(spec.parameters)
    ):
        raise M3BackfillError("CANDIDATE_SPEC_MISMATCH")
    try:
        snapshot, frame = raw_store.verify_request_bundle(
            source="tushare",
            table=spec.endpoint,
            request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
    except (OSError, ValueError):
        raise M3BackfillError("CANDIDATE_RAW_INVALID") from None
    _validate_frame(frame, spec, policy)
    expected = _candidate_from_snapshot(spec, snapshot, frame, raw_store.root)
    if candidate != expected:
        raise M3BackfillError("CANDIDATE_RAW_EVIDENCE_MISMATCH")
    return candidate


def _candidate_from_snapshot(
    spec: TushareRequestSpec,
    snapshot: RequestRawSnapshot,
    frame: pl.DataFrame,
    raw_root: Path,
) -> TushareRawCandidateV1:
    return TushareRawCandidateV1(
        "m3-g1-tushare-candidate-v1",
        spec.request_id,
        spec.endpoint,
        _parameters_hash(spec.parameters),
        snapshot.snapshot_id,
        snapshot.data_path.relative_to(raw_root).as_posix(),
        snapshot.metadata_path.relative_to(raw_root).as_posix(),
        snapshot.checksum_sha256,
        snapshot.metadata_sha256,
        response_content_sha256(frame, spec.endpoint),
        snapshot.size_bytes,
        snapshot.row_count,
        snapshot.columns,
    )


def _receipt_from_candidate(
    spec: TushareRequestSpec, candidate: TushareRawCandidateV1
) -> TushareRequestReceipt:
    values: dict[str, Any] = {
        "schema_version": "m3-g1-tushare-receipt-v1",
        "request_id": spec.request_id,
        "endpoint": spec.endpoint,
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
    return TushareRequestReceipt(**values)


def _ensure_intent(path: Path, spec: TushareRequestSpec) -> None:
    intent = TushareRequestIntentV1(
        "m3-g1-tushare-intent-v1",
        spec.request_id,
        spec.endpoint,
        spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if path.exists():
        _verify_existing_intent(path, spec)
    else:
        _write_dataclass_once(path, intent)


def _verify_existing_intent(path: Path, spec: TushareRequestSpec) -> None:
    try:
        existing = _intent_from_dict(_strict_json(_read_bytes(path, "INTENT_INVALID")))
    except (TypeError, ValueError, KeyError):
        raise M3BackfillError("INTENT_INVALID") from None
    expected = TushareRequestIntentV1(
        "m3-g1-tushare-intent-v1",
        spec.request_id,
        spec.endpoint,
        spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if existing != expected:
        raise M3BackfillError("INTENT_SPEC_MISMATCH")


def _write_dataclass_once(path: Path, value: Any) -> None:
    payload = _canonical_json(asdict(value)).encode("utf-8")
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise M3BackfillError("JOURNAL_CONCURRENT_PUBLISH") from None
        except OSError:
            raise M3BackfillError("JOURNAL_PUBLISH_IO_FAILED") from None
    except M3BackfillError:
        raise
    except OSError:
        raise M3BackfillError("JOURNAL_PUBLISH_IO_FAILED") from None
    finally:
        has_primary_error = sys.exc_info()[0] is not None
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            if not has_primary_error:
                raise M3BackfillError("JOURNAL_TEMP_CLEANUP_FAILED") from None


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


def _intent_from_dict(value: dict[str, Any]) -> TushareRequestIntentV1:
    _exact_keys(value, TushareRequestIntentV1)
    return TushareRequestIntentV1(
        value["schema_version"],
        value["request_id"],
        value["endpoint"],
        _parse_parameters(value["parameters"]),
        value["parameters_sha256"],
    )


def _candidate_from_dict(value: dict[str, Any]) -> TushareRawCandidateV1:
    _exact_keys(value, TushareRawCandidateV1)
    return TushareRawCandidateV1(
        value["schema_version"], value["request_id"], value["endpoint"],
        value["parameters_sha256"], value["raw_snapshot_id"], value["raw_data_path"],
        value["raw_metadata_path"], value["raw_file_sha256"],
        value["raw_metadata_sha256"], value["response_content_sha256"],
        value["raw_size_bytes"], value["row_count"], _parse_columns(value["columns"]),
    )


def _receipt_from_dict(value: dict[str, Any]) -> TushareRequestReceipt:
    _exact_keys(value, TushareRequestReceipt)
    return TushareRequestReceipt(
        value["schema_version"], value["request_id"], value["endpoint"],
        _parse_parameters(value["parameters"]), value["parameters_sha256"],
        value["raw_snapshot_id"], value["raw_data_path"], value["raw_metadata_path"],
        value["raw_file_sha256"], value["raw_metadata_sha256"],
        value["response_content_sha256"], value["stable_response_sha256"],
        value["raw_size_bytes"], value["row_count"], _parse_columns(value["columns"]),
    )


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


def _validate_journal_files(directory: Path) -> None:
    allowed = {"intent.json", "candidate.json", "receipt.json"}
    try:
        entries = list(directory.iterdir())
        for path in entries:
            mode = os.lstat(path).st_mode
            if path.name not in allowed or not stat.S_ISREG(mode):
                raise M3BackfillError("JOURNAL_UNKNOWN_OR_NON_REGULAR_ENTRY")
    except M3BackfillError:
        raise
    except OSError:
        raise M3BackfillError("JOURNAL_LAYOUT_INSPECTION_FAILED") from None


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
                raise M3BackfillError("CONTROLLED_ROOT_SYMLINK")
            if not stat.S_ISDIR(mode):
                raise M3BackfillError("CONTROLLED_ROOT_NOT_DIRECTORY")
        absolute.relative_to(absolute.anchor)
    except M3BackfillError:
        raise
    except (OSError, ValueError, TypeError):
        raise M3BackfillError("CONTROLLED_ROOT_INVALID") from None


def _validate_frame(frame: pl.DataFrame, spec: TushareRequestSpec, policy: EndpointPolicy) -> None:
    expected = tuple(TUSHARE_FIELDS[spec.endpoint].split(","))
    if tuple(frame.columns) != expected:
        raise M3BackfillError("TUSHARE_RESPONSE_COLUMNS_INVALID")
    if frame.height == 0 and policy.empty_response == "REJECT":
        raise M3BackfillError("TUSHARE_EMPTY_RESPONSE_REJECTED")
    if frame.height >= policy.row_limit:
        raise M3BackfillError("TUSHARE_RESPONSE_MAY_BE_TRUNCATED")


def _validate_policies(values: Mapping[str, EndpointPolicy]) -> None:
    if set(values) != set(_ENDPOINTS) or any(
        not isinstance(values[key], EndpointPolicy) for key in _ENDPOINTS
    ):
        raise ValueError("endpoint_policies 必须精确包含全部冻结 endpoint")
    if dict(values) != dict(ENDPOINT_POLICIES_V1):
        raise ValueError("endpoint_policies 与 M3 G1 v1 冻结值不一致")


def _validate_batch_again(batch: TushareRequestBatch) -> None:
    if not isinstance(batch, TushareRequestBatch):
        raise ValueError("batch 类型非法")
    TushareRequestBatch(batch.schema_version, batch.phase, batch.requests, batch.batch_sha256)
    for spec in batch.requests:
        TushareRequestSpec(spec.schema_version, spec.request_id, spec.endpoint, spec.parameters)
        _validate_request_contract(spec)


def _validate_request_contract(spec: TushareRequestSpec) -> None:
    values = dict(spec.parameters)
    common_range = {"fields", "start_date", "end_date"}
    expected_keys = (
        common_range | {"index_code"}
        if spec.endpoint == "index_weight"
        else common_range | {"ts_code"}
        if spec.endpoint in {
            "daily", "adj_factor", "index_daily", "stk_limit", "fund_daily", "fund_adj"
        }
        else common_range | {"ts_code", "suspend_type"}
        if spec.endpoint == "suspend_d"
        else {"fields", "ts_code"}
    )
    if set(values) != expected_keys or values.get("fields") != TUSHARE_FIELDS[spec.endpoint]:
        raise ValueError("request 参数字段集合或 fields 契约非法")
    if spec.endpoint == "index_weight":
        _validate_index_code(values["index_code"])
    elif spec.endpoint == "index_daily":
        _validate_index_code(values["ts_code"])
    elif spec.endpoint in {"daily", "adj_factor", "stk_limit", "dividend", "suspend_d"}:
        if not _A_SHARE.fullmatch(values["ts_code"]):
            raise ValueError("request A 股证券代码非法")
        if spec.endpoint == "suspend_d" and values["suspend_type"] != "S":
            raise ValueError("suspend_d 只允许 suspend_type=S")
    elif spec.endpoint in {"fund_daily", "fund_adj", "fund_div"}:
        if not _A_SHARE.fullmatch(values["ts_code"]):
            raise ValueError("request 基金证券代码非法")
    elif values.get("suspend_type") == "S":
        raise ValueError("suspend_d 参数字段集合或 fields 契约非法")
    if "start_date" in values:
        start = _parse_request_date(values["start_date"])
        end = _parse_request_date(values["end_date"])
        if start > end:
            raise ValueError("request 日期范围非法")


def _parse_request_date(value: str) -> dt.date:
    if not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("request 日期格式非法")
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise ValueError("request 日期格式非法") from None


def _validate_endpoint(endpoint: str) -> None:
    if type(endpoint) is not str or endpoint not in TUSHARE_FIELDS:
        raise ValueError("Tushare endpoint 非法")


def _validate_parameters(parameters: tuple[tuple[str, str], ...]) -> None:
    if type(parameters) is not tuple or not all(
        type(item) is tuple
        and len(item) == 2
        and type(item[0]) is str
        and type(item[1]) is str
        for item in parameters
    ):
        raise ValueError("parameters 必须是字符串 tuple")
    if parameters != tuple(sorted(parameters)) or len({key for key, _ in parameters}) != len(
        parameters
    ):
        raise ValueError("parameters 必须按 key 排序且唯一")


def _validate_counts(size: int, rows: int, columns: tuple[str, ...]) -> None:
    if type(size) is not int or size < 0 or type(rows) is not int or rows < 0:
        raise ValueError("raw size/row count 非法")
    if type(columns) is not tuple or not all(type(value) is str for value in columns):
        raise ValueError("columns 必须是字符串 tuple")


def _validate_hex(value: Any) -> None:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ValueError("identity 必须是 64 位小写裸 hex")


def _validate_relative(value: Any) -> None:
    if type(value) is not str or "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError("相对路径非法")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("相对路径逃逸")


def _resolve_relative(root: Path, value: str) -> Path:
    _validate_relative(value)
    target = root.joinpath(*PurePosixPath(value).parts)
    _reject_path_symlinks(root, target)
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        raise M3BackfillError("RAW_PATH_ESCAPE") from None
    return target


def _reject_path_symlinks(root: Path, target: Path) -> None:
    _preflight_controlled_root(root)
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        raise M3BackfillError("CONTROLLED_PATH_ESCAPE") from None
    cursor = root
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            mode = os.lstat(cursor).st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise M3BackfillError("CONTROLLED_PATH_INSPECTION_FAILED") from None
        if stat.S_ISLNK(mode):
            raise M3BackfillError("CONTROLLED_PATH_SYMLINK")
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise M3BackfillError("CONTROLLED_PATH_NOT_DIRECTORY")


def _read_bytes(path: Path, code: str) -> bytes:
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise OSError
        return path.read_bytes()
    except OSError:
        raise M3BackfillError(code) from None


def _request_id(endpoint: str, parameters: tuple[tuple[str, str], ...]) -> str:
    return _sha256({"endpoint": endpoint, "parameters": parameters})


def _parameters_hash(parameters: tuple[tuple[str, str], ...]) -> str:
    return _sha256(parameters)


def _batch_hash(phase: str, requests: Sequence[TushareRequestSpec]) -> str:
    return _sha256(
        {
            "schema_version": "m3-g1-tushare-request-batch-v1",
            "phase": phase,
            "request_ids": [value.request_id for value in requests],
        }
    )


def _plan_hash(
    weight: TushareRequestBatch,
    history: TushareRequestBatch,
    cninfo_rights: CninfoRequestBatch,
    cninfo_dividend: CninfoCorporateActionRequestBatch,
    cninfo_share_change: CninfoCorporateActionRequestBatch,
) -> str:
    return _sha256(
        {
            "schema_version": "m3-g1-request-plan-v3",
            "index_weight_batch_sha256": weight.batch_sha256,
            "history_batch_sha256": history.batch_sha256,
            "cninfo_rights_batch_sha256": cninfo_rights.batch_sha256,
            "cninfo_dividend_batch_sha256": cninfo_dividend.batch_sha256,
            "cninfo_share_change_batch_sha256": cninfo_share_change.batch_sha256,
        }
    )




def _ca_adapter_for_endpoint(
    endpoint: Literal["stock_dividend", "stock_share_change"],
) -> Literal["akshare_cninfo_p_sysapi1139_v1", "akshare_cninfo_p_stock2215_v1"]:
    if endpoint == CNINFO_DIVIDEND_ENDPOINT:
        return CNINFO_DIVIDEND_ADAPTER
    if endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        return CNINFO_SHARE_CHANGE_ADAPTER
    raise ValueError("cninfo corporate-action endpoint 非法")


def _ca_fields_for_endpoint(
    endpoint: Literal["stock_dividend", "stock_share_change"],
) -> tuple[str, ...]:
    if endpoint == CNINFO_DIVIDEND_ENDPOINT:
        return CNINFO_STOCK_DIVIDEND_FIELDS
    if endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        return CNINFO_STOCK_SHARE_CHANGE_FIELDS
    raise ValueError("cninfo corporate-action endpoint 非法")


def _ca_empty_frame(
    endpoint: Literal["stock_dividend", "stock_share_change"],
) -> pl.DataFrame:
    if endpoint == CNINFO_DIVIDEND_ENDPOINT:
        return empty_cninfo_dividend_frame()
    if endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        return empty_cninfo_share_change_frame()
    raise ValueError("cninfo corporate-action endpoint 非法")


def _cninfo_corporate_action_request_id(
    *,
    endpoint: Literal["stock_dividend", "stock_share_change"],
    adapter: str,
    parameters: tuple[tuple[str, str], ...],
) -> str:
    return _sha256(
        {
            "schema_version": "m3-g1-cninfo-corporate-action-request-v1",
            "source": CNINFO_SOURCE,
            "endpoint": endpoint,
            "adapter": adapter,
            "parameters": parameters,
        }
    )


def _cninfo_corporate_action_batch_hash(
    requests: Sequence[CninfoCorporateActionRequestSpec],
) -> str:
    return _sha256(
        {
            "schema_version": "m3-g1-cninfo-corporate-action-request-batch-v1",
            "phase": "HISTORY",
            "request_ids": [value.request_id for value in requests],
        }
    )


def _validate_cninfo_corporate_action_parameters(
    endpoint: Literal["stock_dividend", "stock_share_change"],
    parameters: tuple[tuple[str, str], ...],
) -> None:
    if type(parameters) is not tuple or parameters != tuple(sorted(parameters)):
        raise ValueError("cninfo corporate-action parameters 必须排序")
    values = dict(parameters)
    if endpoint == CNINFO_DIVIDEND_ENDPOINT:
        if set(values) != {"symbol"}:
            raise ValueError("cninfo dividend parameters 字段集合非法")
        symbol = values["symbol"]
        if type(symbol) is not str or len(symbol) != 6 or not symbol.isdigit():
            raise ValueError("cninfo dividend symbol 非法")
        return
    if endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        if set(values) != {"symbol", "start_date", "end_date"}:
            raise ValueError("cninfo share-change parameters 字段集合非法")
        symbol = values["symbol"]
        start = values["start_date"]
        end = values["end_date"]
        if type(symbol) is not str or len(symbol) != 6 or not symbol.isdigit():
            raise ValueError("cninfo share-change symbol 非法")
        start_date = _parse_request_date(start)
        end_date = _parse_request_date(end)
        if start_date > end_date:
            raise ValueError("cninfo share-change 日期范围非法")
        return
    raise ValueError("cninfo corporate-action endpoint 非法")


def cninfo_corporate_action_response_content_sha256(
    frame: pl.DataFrame,
    *,
    endpoint: Literal["stock_dividend", "stock_share_change"],
) -> str:
    fields = _ca_fields_for_endpoint(endpoint)
    if tuple(frame.columns) != fields:
        raise M3BackfillError("CNINFO_RESPONSE_COLUMNS_INVALID")
    rows: list[list[Any]] = []
    for row in frame.iter_rows(named=True):
        rows.append([_canonical_scalar(row[name]) for name in fields])
    return _sha256({"columns": list(fields), "rows": rows})


def _cninfo_request_id(parameters: tuple[tuple[str, str], ...]) -> str:
    return _sha256(
        {
            "source": CNINFO_SOURCE,
            "endpoint": CNINFO_ENDPOINT,
            "adapter": CNINFO_ADAPTER,
            "parameters": parameters,
        }
    )


def _cninfo_batch_hash(requests: Sequence[CninfoRequestSpec]) -> str:
    return _sha256(
        {
            "schema_version": "m3-g1-cninfo-request-batch-v1",
            "phase": "HISTORY",
            "request_ids": [value.request_id for value in requests],
        }
    )


def _validate_cninfo_parameters(parameters: tuple[tuple[str, str], ...]) -> None:
    if type(parameters) is not tuple or parameters != tuple(sorted(parameters)):
        raise ValueError("cninfo parameters 必须排序")
    values = dict(parameters)
    if set(values) != {"symbols", "start_date", "end_date"}:
        raise ValueError("cninfo parameters 字段集合非法")
    symbols = values["symbols"]
    start = values["start_date"]
    end = values["end_date"]
    if type(symbols) is not str or not symbols:
        raise ValueError("cninfo symbols 非法")
    parts = symbols.split(",")
    if not parts or any(not part for part in parts):
        raise ValueError("cninfo symbols 非法")
    if len(parts) != len(set(parts)):
        raise ValueError("cninfo symbols 必须唯一")
    if parts != sorted(parts):
        raise ValueError("cninfo symbols 必须排序")
    if not (1 <= len(parts) <= 50):
        raise ValueError("cninfo symbols 批次大小非法")
    for part in parts:
        if len(part) != 6 or not part.isdigit():
            raise ValueError("cninfo symbol 非法")
    for label, value in (("start_date", start), ("end_date", end)):
        if type(value) is not str or len(value) != 8 or not value.isdigit():
            raise ValueError(f"cninfo {label} 非法")
    if start > end:
        raise ValueError("cninfo 日期范围非法")


def cninfo_response_content_sha256(frame: pl.DataFrame) -> str:
    if tuple(frame.columns) != CNINFO_STOCK_ALLOTMENT_FIELDS:
        raise M3BackfillError("CNINFO_RESPONSE_COLUMNS_INVALID")
    rows: list[list[Any]] = []
    for row in frame.iter_rows(named=True):
        rows.append([_canonical_scalar(row[name]) for name in CNINFO_STOCK_ALLOTMENT_FIELDS])
    return _sha256({"columns": list(CNINFO_STOCK_ALLOTMENT_FIELDS), "rows": rows})


def _cninfo_stable_response_hash(receipt: CninfoRequestReceipt) -> str:
    return _cninfo_stable_response_hash_values(asdict(receipt))


def _cninfo_stable_response_hash_values(values: Mapping[str, Any]) -> str:
    return _sha256(
        {
            "request_id": values["request_id"],
            "endpoint": values["endpoint"],
            "adapter": values["adapter"],
            "parameters_sha256": values["parameters_sha256"],
            "response_content_sha256": values["response_content_sha256"],
            "resultcode": values["resultcode"],
            "count": values["count"],
            "total": values["total"],
            "row_count": values["row_count"],
            "columns": values["columns"],
        }
    )


def _cninfo_ca_stable_response_hash_values(values: Mapping[str, Any]) -> str:
    return _sha256(
        {
            "request_id": values["request_id"],
            "endpoint": values["endpoint"],
            "adapter": values["adapter"],
            "parameters_sha256": values["parameters_sha256"],
            "raw_snapshot_id": values["raw_snapshot_id"],
            "raw_data_path": values["raw_data_path"],
            "raw_metadata_path": values["raw_metadata_path"],
            "raw_file_sha256": values["raw_file_sha256"],
            "raw_metadata_sha256": values["raw_metadata_sha256"],
            "response_content_sha256": values["response_content_sha256"],
            "resultcode": values["resultcode"],
            "resultmsg": values["resultmsg"],
            "count": values["count"],
            "total": values["total"],
            "raw_size_bytes": values["raw_size_bytes"],
            "row_count": values["row_count"],
            "columns": values["columns"],
        }
    )


def _stable_response_hash(receipt: TushareRequestReceipt) -> str:
    return _stable_response_hash_values(asdict(receipt))


def _stable_response_hash_values(values: Mapping[str, Any]) -> str:
    return _sha256(
        {
            "request_id": values["request_id"],
            "endpoint": values["endpoint"],
            "parameters_sha256": values["parameters_sha256"],
            "response_content_sha256": values["response_content_sha256"],
            "row_count": values["row_count"],
            "columns": values["columns"],
        }
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_scalar(value: Any) -> list[Any]:
    if value is None:
        return ["null", None]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is float:
        if not math.isfinite(value):
            raise M3BackfillError("TUSHARE_RESPONSE_NON_FINITE")
        normalized = 0.0 if value == 0.0 else value
        return ["float", format(normalized, ".17g")]
    if isinstance(value, (dt.date, dt.datetime)):
        return ["datetime" if isinstance(value, dt.datetime) else "date", value.isoformat()]
    if type(value) is str:
        return ["str", value]
    raise M3BackfillError("TUSHARE_RESPONSE_TYPE_UNSUPPORTED")


def _safe_classify(classifier: Callable[[BaseException], str], error: BaseException) -> str:
    try:
        value = classifier(error)
    except BaseException:
        return "UNKNOWN"
    return value if type(value) is str else "UNKNOWN"


def _date_text(value: dt.date) -> str:
    return value.strftime("%Y%m%d")


def _parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise M3BackfillError("REQUEST_DATE_INVALID") from exc


def _shift_month(value: dt.date, amount: int) -> dt.date:
    index = value.year * 12 + value.month - 1 + amount
    return dt.date(index // 12, index % 12 + 1, 1)


def _validate_index_code(value: str) -> None:
    if not re.fullmatch(r"(?:[0-9]{6}\.(?:SH|SZ)|[A-Za-z0-9]+\.CSI)", value):
        raise ValueError("指数代码非法")


def _fault_point(name: str) -> None:
    """Private monkeypatch seam used only by deterministic crash tests."""
    del name

def execute_cninfo_batch(
    *,
    batch: CninfoRequestBatch,
    connector: CninfoConnector,
    raw_store: RawStore,
    journal_root: Path,
    row_limit: int,
    request_rate_per_minute: int,
    max_attempts: int,
    retry_base_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    classify_error: Callable[[BaseException], str],
    max_new_requests: int | None = None,
) -> CninfoBatchExecutionResult:
    bound = _validate_max_new_requests(max_new_requests)
    if not isinstance(batch, CninfoRequestBatch):
        raise ValueError("batch 类型非法")
    CninfoRequestBatch(
        batch.schema_version, batch.phase, batch.requests, batch.batch_sha256
    )
    if type(connector) is not CninfoConnector:
        raise ValueError("connector 必须是 CninfoConnector")
    if type(row_limit) is not int or row_limit <= 0:
        raise ValueError("row_limit 必须是正整数")
    if type(request_rate_per_minute) is not int or request_rate_per_minute <= 0:
        raise ValueError("request_rate_per_minute 必须是正整数")
    if type(max_attempts) is not int or max_attempts <= 0:
        raise ValueError("max_attempts 必须是正整数")
    if type(retry_base_seconds) not in {int, float} or not math.isfinite(
        float(retry_base_seconds)
    ) or retry_base_seconds < 0:
        raise ValueError("retry_base_seconds 必须是非负 finite 数")
    _preflight_controlled_root(raw_store.root)
    _preflight_controlled_root(journal_root)
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise M3BackfillError("JOURNAL_ROOT_CREATE_FAILED") from None
    _preflight_controlled_root(journal_root)
    try:
        with hold_journal_writer_lock(journal_root=journal_root):
            return _execute_cninfo_batch_locked(
                batch=batch,
                connector=connector,
                raw_store=raw_store,
                journal_root=journal_root,
                row_limit=row_limit,
                request_rate_per_minute=request_rate_per_minute,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
                monotonic=monotonic,
                sleep=sleep,
                classify_error=classify_error,
                max_new_requests=bound,
            )
    except M3JournalLockError as exc:
        raise _map_journal_lock_error(exc) from None


def _execute_cninfo_batch_locked(
    *,
    batch: CninfoRequestBatch,
    connector: CninfoConnector,
    raw_store: RawStore,
    journal_root: Path,
    row_limit: int,
    request_rate_per_minute: int,
    max_attempts: int,
    retry_base_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    classify_error: Callable[[BaseException], str],
    max_new_requests: int | None,
) -> CninfoBatchExecutionResult:
    receipts: list[CninfoRequestReceipt] = []
    new_requests_committed = 0
    last_attempt_started: float | None = None
    interval = 60.0 / request_rate_per_minute
    policy = EndpointPolicy(row_limit, "ALLOW")
    for spec in batch.requests:
        request_dir = journal_root / spec.request_id
        _reject_path_symlinks(journal_root, request_dir)
        budget_exhausted = (
            max_new_requests is not None and new_requests_committed >= max_new_requests
        )
        dir_exists = _request_dir_exists(request_dir)
        if not dir_exists:
            if budget_exhausted:
                continue
            try:
                request_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise M3BackfillError("JOURNAL_REQUEST_DIR_CREATE_FAILED") from None
            _reject_path_symlinks(journal_root, request_dir)
        _validate_journal_files(request_dir)
        intent_path = request_dir / "intent.json"
        candidate_path = request_dir / "candidate.json"
        receipt_path = request_dir / "receipt.json"
        if receipt_path.exists():
            if not intent_path.exists() or not candidate_path.exists():
                raise M3BackfillError("COMMITTED_JOURNAL_INCOMPLETE")
            _verify_existing_cninfo_intent(intent_path, spec)
            committed_candidate = _recover_cninfo_candidate(
                spec=spec,
                candidate_path=candidate_path,
                raw_store=raw_store,
                policy=policy,
                expected_mode="RECOVER",
                expected_candidate_exists=True,
            )
            assert committed_candidate is not None
            verified = verify_cninfo_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_store.root,
                journal_root=journal_root,
                policy=policy,
            )
            if verified.receipt != _cninfo_receipt_from_candidate(spec, committed_candidate):
                raise M3BackfillError("COMMITTED_JOURNAL_CONFLICT")
            receipts.append(verified.receipt)
            continue
        preflight = _preflight_cninfo_no_receipt(
            spec=spec,
            intent_path=intent_path,
            candidate_path=candidate_path,
            raw_store=raw_store,
        )
        if budget_exhausted:
            continue
        if not preflight.intent_exists:
            _ensure_cninfo_intent(intent_path, spec)
        candidate = _recover_cninfo_candidate(
            spec=spec,
            candidate_path=candidate_path,
            raw_store=raw_store,
            policy=policy,
            expected_mode=preflight.mode,
            expected_candidate_exists=preflight.candidate_exists,
        )
        if (preflight.mode == "NETWORK") != (candidate is None):
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        if candidate is None:
            result: CninfoAllotmentRawResult | None = None
            for attempt in range(1, max_attempts + 1):
                if last_attempt_started is not None:
                    now = monotonic()
                    rate_deadline = last_attempt_started + interval
                    if now < rate_deadline:
                        sleep(rate_deadline - now)
                attempt_started = monotonic()
                last_attempt_started = attempt_started
                try:
                    params = dict(spec.parameters)
                    result = connector.fetch_stock_allotment_raw(
                        symbols=params["symbols"],
                        start_date=params["start_date"],
                        end_date=params["end_date"],
                    )
                    break
                except CninfoConnectorError as exc:
                    category = _cninfo_error_category(exc)
                    if category not in {"NETWORK", "RATE_LIMIT", "TRANSIENT_SERVER"}:
                        raise M3BackfillError("CNINFO_REQUEST_PERMANENT_FAILURE") from None
                    if attempt == max_attempts:
                        raise M3BackfillError("CNINFO_REQUEST_ATTEMPTS_EXHAUSTED") from None
                    failure_time = monotonic()
                    rate_deadline = attempt_started + interval
                    backoff_deadline = failure_time + float(retry_base_seconds) * 2 ** (
                        attempt - 1
                    )
                    now = monotonic()
                    deadline = max(rate_deadline, backoff_deadline)
                    if now < deadline:
                        sleep(deadline - now)
                    last_attempt_started = deadline - interval
                except BaseException as exc:
                    category = _safe_classify(classify_error, exc)
                    if category not in {"NETWORK", "RATE_LIMIT", "TRANSIENT_SERVER"}:
                        raise M3BackfillError("CNINFO_REQUEST_PERMANENT_FAILURE") from None
                    if attempt == max_attempts:
                        raise M3BackfillError("CNINFO_REQUEST_ATTEMPTS_EXHAUSTED") from None
                    failure_time = monotonic()
                    rate_deadline = attempt_started + interval
                    backoff_deadline = failure_time + float(retry_base_seconds) * 2 ** (
                        attempt - 1
                    )
                    now = monotonic()
                    deadline = max(rate_deadline, backoff_deadline)
                    if now < deadline:
                        sleep(deadline - now)
                    last_attempt_started = deadline - interval
            assert result is not None
            _validate_cninfo_frame(result, policy)
            try:
                snapshot = raw_store.write_request(
                    source=CNINFO_SOURCE,
                    table=CNINFO_ENDPOINT,
                    request_id=spec.request_id,
                    frame=result.frame,
                    parameters=dict(spec.parameters),
                    after_data_write=lambda: _fault_point("after_data"),
                    after_metadata_write=lambda: _fault_point("after_metadata"),
                )
            except (OSError, ValueError):
                raise M3BackfillError("RAW_WRITE_CONFLICT") from None
            candidate = _cninfo_candidate_from_snapshot(
                spec, snapshot, result, raw_store.root
            )
            _write_dataclass_once(candidate_path, candidate)
            _fault_point("after_candidate")
        receipt = _cninfo_receipt_from_candidate(spec, candidate)
        _fault_point("before_receipt")
        _write_dataclass_once(receipt_path, receipt)
        receipts.append(
            verify_cninfo_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_store.root,
                journal_root=journal_root,
                policy=policy,
            ).receipt
        )
        new_requests_committed += 1
    return CninfoBatchExecutionResult(
        receipts=tuple(receipts), new_requests_committed=new_requests_committed
    )


def verify_cninfo_receipt(
    *,
    spec: CninfoRequestSpec,
    receipt_path: Path,
    raw_root: Path,
    journal_root: Path,
    policy: EndpointPolicy,
) -> VerifiedCninfoRawResponse:
    expected_path = journal_root / spec.request_id / "receipt.json"
    if receipt_path != expected_path:
        raise M3BackfillError("RECEIPT_PATH_INVALID")
    _reject_path_symlinks(journal_root, receipt_path)
    payload = _read_bytes(receipt_path, "RECEIPT_INVALID")
    try:
        parsed = _strict_json(payload)
        _exact_keys(parsed, CninfoRequestReceipt)
        receipt = CninfoRequestReceipt(
            parsed["schema_version"],
            parsed["request_id"],
            parsed["source"],
            parsed["endpoint"],
            parsed["adapter"],
            _parse_parameters(parsed["parameters"]),
            parsed["parameters_sha256"],
            parsed["raw_snapshot_id"],
            parsed["raw_data_path"],
            parsed["raw_metadata_path"],
            parsed["raw_file_sha256"],
            parsed["raw_metadata_sha256"],
            parsed["response_content_sha256"],
            parsed["stable_response_sha256"],
            parsed["resultcode"],
            parsed["count"],
            parsed["total"],
            parsed["raw_size_bytes"],
            parsed["row_count"],
            _parse_columns(parsed["columns"]),
        )
    except (TypeError, ValueError, KeyError):
        raise M3BackfillError("RECEIPT_INVALID") from None
    if (
        receipt.request_id != spec.request_id
        or receipt.endpoint != spec.endpoint
        or receipt.adapter != spec.adapter
        or receipt.parameters != spec.parameters
    ):
        raise M3BackfillError("RECEIPT_SPEC_MISMATCH")
    data_path = _resolve_relative(raw_root, receipt.raw_data_path)
    metadata_path = _resolve_relative(raw_root, receipt.raw_metadata_path)
    try:
        snapshot, frame = RawStore(raw_root).verify_request_bundle(
            source=CNINFO_SOURCE,
            table=CNINFO_ENDPOINT,
            request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
    except (OSError, ValueError):
        raise M3BackfillError("RECEIPT_RAW_INVALID") from None
    if data_path != snapshot.data_path or metadata_path != snapshot.metadata_path:
        raise M3BackfillError("RECEIPT_RAW_PATH_MISMATCH")
    normalized = frame
    if frame.height == 0 and tuple(frame.columns) != CNINFO_STOCK_ALLOTMENT_FIELDS:
        normalized = empty_cninfo_allotment_frame()
    result = CninfoAllotmentRawResult(
        frame=normalized,
        resultcode=receipt.resultcode,
        resultmsg="success",
        count=receipt.count,
        total=receipt.total,
    )
    _validate_cninfo_frame(result, policy)
    expected_candidate = _cninfo_candidate_from_snapshot(
        spec, snapshot, result, raw_root
    )
    expected_receipt = _cninfo_receipt_from_candidate(spec, expected_candidate)
    content_hash = cninfo_response_content_sha256(normalized)
    if (
        receipt.raw_snapshot_id != snapshot.snapshot_id
        or receipt.raw_file_sha256 != snapshot.checksum_sha256
        or receipt.raw_metadata_sha256 != snapshot.metadata_sha256
        or receipt.raw_size_bytes != snapshot.size_bytes
        or receipt.row_count != snapshot.row_count
        or receipt.columns != snapshot.columns
        or receipt.response_content_sha256 != content_hash
        or receipt.resultcode != expected_receipt.resultcode
        or receipt.count != expected_receipt.count
        or receipt.total != expected_receipt.total
        or receipt.stable_response_sha256 != expected_receipt.stable_response_sha256
    ):
        raise M3BackfillError("RECEIPT_RAW_EVIDENCE_MISMATCH")
    if receipt != expected_receipt:
        raise M3BackfillError("RECEIPT_RAW_EVIDENCE_MISMATCH")
    try:
        return VerifiedCninfoRawResponse(
            spec=spec,
            receipt=receipt,
            receipt_sha256=hashlib.sha256(payload).hexdigest(),
            frame=normalized,
            resultcode=receipt.resultcode,
            count=receipt.count,
            total=receipt.total,
        )
    except ValueError:
        raise M3BackfillError("RECEIPT_CANONICAL_BYTES_MISMATCH") from None


def _validate_cninfo_frame(
    result: CninfoAllotmentRawResult, policy: EndpointPolicy
) -> None:
    if tuple(result.frame.columns) != CNINFO_STOCK_ALLOTMENT_FIELDS:
        raise M3BackfillError("CNINFO_RESPONSE_COLUMNS_INVALID")
    if result.frame.height == 0 and policy.empty_response == "REJECT":
        raise M3BackfillError("CNINFO_EMPTY_RESPONSE_REJECTED")
    if result.frame.height >= policy.row_limit:
        raise M3BackfillError("CNINFO_RESPONSE_ROW_LIMIT")
    if (
        result.resultcode != 200
        or result.resultmsg != "success"
        or result.count != result.total
        or result.count != result.frame.height
    ):
        raise M3BackfillError("CNINFO_RESPONSE_COUNT_MISMATCH")


def _cninfo_error_category(exc: CninfoConnectorError) -> str:
    if exc.code in {"CNINFO_NETWORK_FAILED", "CNINFO_DEPENDENCY_MISSING"}:
        return "NETWORK"
    if exc.code in {
        "CNINFO_RESPONSE_SCHEMA_INVALID",
        "CNINFO_RESPONSE_SCOPE_INVALID",
        "CNINFO_RESPONSE_DUPLICATE_SUBID",
        "CNINFO_RESPONSE_ROW_LIMIT",
        "CNINFO_REQUEST_PARAMS_INVALID",
        "CNINFO_ENCKEY_INVALID",
    }:
        return "PERMANENT"
    return "UNKNOWN"


def _ensure_cninfo_intent(path: Path, spec: CninfoRequestSpec) -> None:
    intent = CninfoRequestIntentV1(
        "m3-g1-cninfo-intent-v1",
        spec.request_id,
        spec.source,
        spec.endpoint,
        spec.adapter,
        spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if path.exists():
        _verify_existing_cninfo_intent(path, spec)
    else:
        _write_dataclass_once(path, intent)


def _verify_existing_cninfo_intent(path: Path, spec: CninfoRequestSpec) -> None:
    try:
        parsed = _strict_json(_read_bytes(path, "INTENT_INVALID"))
        _exact_keys(parsed, CninfoRequestIntentV1)
        existing = CninfoRequestIntentV1(
            parsed["schema_version"],
            parsed["request_id"],
            parsed["source"],
            parsed["endpoint"],
            parsed["adapter"],
            _parse_parameters(parsed["parameters"]),
            parsed["parameters_sha256"],
        )
    except (TypeError, ValueError, KeyError):
        raise M3BackfillError("INTENT_INVALID") from None
    expected = CninfoRequestIntentV1(
        "m3-g1-cninfo-intent-v1",
        spec.request_id,
        spec.source,
        spec.endpoint,
        spec.adapter,
        spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if existing != expected:
        raise M3BackfillError("INTENT_SPEC_MISMATCH")


def _preflight_cninfo_no_receipt(
    *,
    spec: CninfoRequestSpec,
    intent_path: Path,
    candidate_path: Path,
    raw_store: RawStore,
) -> _NoReceiptPreflight:
    try:
        raw_state = raw_store.inspect_request_state(
            source=CNINFO_SOURCE, table=CNINFO_ENDPOINT, request_id=spec.request_id
        )
        intent_exists = _regular_file_exists(intent_path)
        candidate_exists = _regular_file_exists(candidate_path)
    except (OSError, ValueError):
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None
    if candidate_exists and (not intent_exists or raw_state != "COMPLETE"):
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if raw_state == "COMPLETE" and not intent_exists:
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if intent_exists:
        _verify_existing_cninfo_intent(intent_path, spec)
    mode: Literal["NETWORK", "RECOVER"] = (
        "RECOVER" if raw_state == "COMPLETE" else "NETWORK"
    )
    return _NoReceiptPreflight(raw_state, intent_exists, candidate_exists, mode)


def _recover_cninfo_candidate(
    *,
    spec: CninfoRequestSpec,
    candidate_path: Path,
    raw_store: RawStore,
    policy: EndpointPolicy,
    expected_mode: Literal["NETWORK", "RECOVER"],
    expected_candidate_exists: bool,
) -> CninfoRawCandidateV1 | None:
    candidate_exists = _regular_file_exists(candidate_path)
    if candidate_exists != expected_candidate_exists:
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
    try:
        state = raw_store.inspect_request_state(
            source=CNINFO_SOURCE, table=CNINFO_ENDPOINT, request_id=spec.request_id
        )
    except (OSError, ValueError):
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None
    if expected_mode == "NETWORK":
        if candidate_exists or state == "COMPLETE":
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        return None
    if state != "COMPLETE":
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
    if candidate_exists:
        try:
            parsed = _strict_json(_read_bytes(candidate_path, "CANDIDATE_INVALID"))
            _exact_keys(parsed, CninfoRawCandidateV1)
            candidate = CninfoRawCandidateV1(
                parsed["schema_version"],
                parsed["request_id"],
                parsed["source"],
                parsed["endpoint"],
                parsed["adapter"],
                parsed["parameters_sha256"],
                parsed["raw_snapshot_id"],
                parsed["raw_data_path"],
                parsed["raw_metadata_path"],
                parsed["raw_file_sha256"],
                parsed["raw_metadata_sha256"],
                parsed["response_content_sha256"],
                parsed["resultcode"],
                parsed["count"],
                parsed["total"],
                parsed["raw_size_bytes"],
                parsed["row_count"],
                _parse_columns(parsed["columns"]),
            )
        except (TypeError, ValueError, KeyError):
            raise M3BackfillError("CANDIDATE_INVALID") from None
        return _verify_cninfo_candidate(spec, candidate, raw_store, policy)
    try:
        snapshot, frame = raw_store.verify_request_bundle(
            source=CNINFO_SOURCE,
            table=CNINFO_ENDPOINT,
            request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
        normalized = frame
        if frame.height == 0 and tuple(frame.columns) != CNINFO_STOCK_ALLOTMENT_FIELDS:
            normalized = empty_cninfo_allotment_frame()
        result = CninfoAllotmentRawResult(
            frame=normalized,
            resultcode=200,
            resultmsg="success",
            count=normalized.height,
            total=normalized.height,
        )
        _validate_cninfo_frame(result, policy)
        candidate = _cninfo_candidate_from_snapshot(
            spec, snapshot, result, raw_store.root
        )
        current_state = raw_store.inspect_request_state(
            source=CNINFO_SOURCE, table=CNINFO_ENDPOINT, request_id=spec.request_id
        )
        if current_state != "COMPLETE":
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        _verify_cninfo_candidate(spec, candidate, raw_store, policy)
        if _regular_file_exists(candidate_path):
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        _write_dataclass_once(candidate_path, candidate)
        return candidate
    except M3BackfillError:
        raise
    except (OSError, ValueError):
        raise M3BackfillError("RAW_RECOVERY_INVALID") from None


def _verify_cninfo_candidate(
    spec: CninfoRequestSpec,
    candidate: CninfoRawCandidateV1,
    raw_store: RawStore,
    policy: EndpointPolicy,
) -> CninfoRawCandidateV1:
    if (
        candidate.request_id != spec.request_id
        or candidate.endpoint != spec.endpoint
        or candidate.adapter != spec.adapter
        or candidate.parameters_sha256 != _parameters_hash(spec.parameters)
    ):
        raise M3BackfillError("CANDIDATE_SPEC_MISMATCH")
    try:
        snapshot, frame = raw_store.verify_request_bundle(
            source=CNINFO_SOURCE,
            table=CNINFO_ENDPOINT,
            request_id=spec.request_id,
            parameters=dict(spec.parameters),
        )
    except (OSError, ValueError):
        raise M3BackfillError("CANDIDATE_RAW_INVALID") from None
    normalized = frame
    if frame.height == 0 and tuple(frame.columns) != CNINFO_STOCK_ALLOTMENT_FIELDS:
        normalized = empty_cninfo_allotment_frame()
    result = CninfoAllotmentRawResult(
        frame=normalized,
        resultcode=candidate.resultcode,
        resultmsg="success",
        count=candidate.count,
        total=candidate.total,
    )
    _validate_cninfo_frame(result, policy)
    expected = _cninfo_candidate_from_snapshot(
        spec, snapshot, result, raw_store.root
    )
    if candidate != expected:
        raise M3BackfillError("CANDIDATE_RAW_EVIDENCE_MISMATCH")
    return candidate


def _cninfo_candidate_from_snapshot(
    spec: CninfoRequestSpec,
    snapshot: RequestRawSnapshot,
    result: CninfoAllotmentRawResult,
    raw_root: Path,
) -> CninfoRawCandidateV1:
    return CninfoRawCandidateV1(
        "m3-g1-cninfo-candidate-v1",
        spec.request_id,
        "cninfo",
        "stock_allotment",
        "akshare_cninfo_p_stock2232_v1",
        _parameters_hash(spec.parameters),
        snapshot.snapshot_id,
        snapshot.data_path.relative_to(raw_root).as_posix(),
        snapshot.metadata_path.relative_to(raw_root).as_posix(),
        snapshot.checksum_sha256,
        snapshot.metadata_sha256,
        cninfo_response_content_sha256(result.frame),
        result.resultcode,
        result.count,
        result.total,
        snapshot.size_bytes,
        snapshot.row_count,
        snapshot.columns,
    )


def _cninfo_receipt_from_candidate(
    spec: CninfoRequestSpec, candidate: CninfoRawCandidateV1
) -> CninfoRequestReceipt:
    values: dict[str, Any] = {
        "schema_version": "m3-g1-cninfo-receipt-v1",
        "request_id": spec.request_id,
        "source": CNINFO_SOURCE,
        "endpoint": CNINFO_ENDPOINT,
        "adapter": CNINFO_ADAPTER,
        "parameters": spec.parameters,
        "parameters_sha256": candidate.parameters_sha256,
        "raw_snapshot_id": candidate.raw_snapshot_id,
        "raw_data_path": candidate.raw_data_path,
        "raw_metadata_path": candidate.raw_metadata_path,
        "raw_file_sha256": candidate.raw_file_sha256,
        "raw_metadata_sha256": candidate.raw_metadata_sha256,
        "response_content_sha256": candidate.response_content_sha256,
        "stable_response_sha256": "0" * 64,
        "resultcode": candidate.resultcode,
        "count": candidate.count,
        "total": candidate.total,
        "raw_size_bytes": candidate.raw_size_bytes,
        "row_count": candidate.row_count,
        "columns": candidate.columns,
    }
    values["stable_response_sha256"] = _cninfo_stable_response_hash_values(values)
    return CninfoRequestReceipt(**values)


def execute_cninfo_corporate_action_batch(
    *,
    batch: CninfoCorporateActionRequestBatch,
    connector: CninfoConnector,
    raw_store: RawStore,
    journal_root: Path,
    row_limit: int,
    request_rate_per_minute: int,
    max_attempts: int,
    retry_base_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    classify_error: Callable[[BaseException], str],
    max_new_requests: int | None = None,
) -> CninfoCorporateActionBatchExecutionResult:
    bound = _validate_max_new_requests(max_new_requests)
    if not isinstance(batch, CninfoCorporateActionRequestBatch):
        raise ValueError("batch 类型非法")
    CninfoCorporateActionRequestBatch(
        batch.schema_version, batch.phase, batch.requests, batch.batch_sha256
    )
    if type(connector) is not CninfoConnector:
        raise ValueError("connector 必须是 CninfoConnector")
    if type(row_limit) is not int or row_limit <= 0:
        raise ValueError("row_limit 必须是正整数")
    if type(request_rate_per_minute) is not int or request_rate_per_minute <= 0:
        raise ValueError("request_rate_per_minute 必须是正整数")
    if type(max_attempts) is not int or max_attempts <= 0:
        raise ValueError("max_attempts 必须是正整数")
    if type(retry_base_seconds) not in {int, float} or not math.isfinite(
        float(retry_base_seconds)
    ) or retry_base_seconds < 0:
        raise ValueError("retry_base_seconds 必须是非负 finite 数")
    _preflight_controlled_root(raw_store.root)
    _preflight_controlled_root(journal_root)
    try:
        journal_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise M3BackfillError("JOURNAL_ROOT_CREATE_FAILED") from None
    _preflight_controlled_root(journal_root)
    try:
        with hold_journal_writer_lock(journal_root=journal_root):
            return _execute_cninfo_corporate_action_batch_locked(
                batch=batch,
                connector=connector,
                raw_store=raw_store,
                journal_root=journal_root,
                row_limit=row_limit,
                request_rate_per_minute=request_rate_per_minute,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
                monotonic=monotonic,
                sleep=sleep,
                classify_error=classify_error,
                max_new_requests=bound,
            )
    except M3JournalLockError as exc:
        raise _map_journal_lock_error(exc) from None


def _execute_cninfo_corporate_action_batch_locked(
    *,
    batch: CninfoCorporateActionRequestBatch,
    connector: CninfoConnector,
    raw_store: RawStore,
    journal_root: Path,
    row_limit: int,
    request_rate_per_minute: int,
    max_attempts: int,
    retry_base_seconds: float,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    classify_error: Callable[[BaseException], str],
    max_new_requests: int | None,
) -> CninfoCorporateActionBatchExecutionResult:
    receipts: list[CninfoCorporateActionRequestReceipt] = []
    new_requests_committed = 0
    last_attempt_started: float | None = None
    interval = 60.0 / request_rate_per_minute
    policy = EndpointPolicy(row_limit, "ALLOW")
    for spec in batch.requests:
        request_dir = journal_root / spec.request_id
        _reject_path_symlinks(journal_root, request_dir)
        budget_exhausted = (
            max_new_requests is not None and new_requests_committed >= max_new_requests
        )
        dir_exists = _request_dir_exists(request_dir)
        if not dir_exists:
            if budget_exhausted:
                continue
            try:
                request_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise M3BackfillError("JOURNAL_REQUEST_DIR_CREATE_FAILED") from None
            _reject_path_symlinks(journal_root, request_dir)
        _validate_journal_files(request_dir)
        intent_path = request_dir / "intent.json"
        candidate_path = request_dir / "candidate.json"
        receipt_path = request_dir / "receipt.json"
        if receipt_path.exists():
            if not intent_path.exists() or not candidate_path.exists():
                raise M3BackfillError("COMMITTED_JOURNAL_INCOMPLETE")
            _verify_existing_cninfo_ca_intent(intent_path, spec)
            committed_candidate = _recover_cninfo_ca_candidate(
                spec=spec,
                candidate_path=candidate_path,
                raw_store=raw_store,
                policy=policy,
                expected_mode="RECOVER",
                expected_candidate_exists=True,
            )
            assert committed_candidate is not None
            verified = verify_cninfo_corporate_action_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_store.root,
                journal_root=journal_root,
                policy=policy,
            )
            if verified.receipt != _cninfo_ca_receipt_from_candidate(spec, committed_candidate):
                raise M3BackfillError("COMMITTED_JOURNAL_CONFLICT")
            receipts.append(verified.receipt)
            continue
        preflight = _preflight_cninfo_ca_no_receipt(
            spec=spec,
            intent_path=intent_path,
            candidate_path=candidate_path,
            raw_store=raw_store,
        )
        if budget_exhausted:
            continue
        if not preflight.intent_exists:
            _ensure_cninfo_ca_intent(intent_path, spec)
        candidate = _recover_cninfo_ca_candidate(
            spec=spec,
            candidate_path=candidate_path,
            raw_store=raw_store,
            policy=policy,
            expected_mode=preflight.mode,
            expected_candidate_exists=preflight.candidate_exists,
        )
        if (preflight.mode == "NETWORK") != (candidate is None):
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        if candidate is None:
            result: CninfoCorporateActionRawResult | None = None
            for attempt in range(1, max_attempts + 1):
                if last_attempt_started is not None:
                    now = monotonic()
                    rate_deadline = last_attempt_started + interval
                    if now < rate_deadline:
                        sleep(rate_deadline - now)
                attempt_started = monotonic()
                last_attempt_started = attempt_started
                try:
                    result = _fetch_cninfo_corporate_action(connector, spec)
                    break
                except CninfoConnectorError as exc:
                    category = _cninfo_error_category(exc)
                    if category not in {"NETWORK", "RATE_LIMIT", "TRANSIENT_SERVER"}:
                        raise M3BackfillError("CNINFO_REQUEST_PERMANENT_FAILURE") from None
                    if attempt == max_attempts:
                        raise M3BackfillError("CNINFO_REQUEST_ATTEMPTS_EXHAUSTED") from None
                    failure_time = monotonic()
                    rate_deadline = attempt_started + interval
                    backoff_deadline = failure_time + float(retry_base_seconds) * 2 ** (
                        attempt - 1
                    )
                    now = monotonic()
                    deadline = max(rate_deadline, backoff_deadline)
                    if now < deadline:
                        sleep(deadline - now)
                    last_attempt_started = deadline - interval
                except BaseException as exc:
                    category = _safe_classify(classify_error, exc)
                    if category not in {"NETWORK", "RATE_LIMIT", "TRANSIENT_SERVER"}:
                        raise M3BackfillError("CNINFO_REQUEST_PERMANENT_FAILURE") from None
                    if attempt == max_attempts:
                        raise M3BackfillError("CNINFO_REQUEST_ATTEMPTS_EXHAUSTED") from None
                    failure_time = monotonic()
                    rate_deadline = attempt_started + interval
                    backoff_deadline = failure_time + float(retry_base_seconds) * 2 ** (
                        attempt - 1
                    )
                    now = monotonic()
                    deadline = max(rate_deadline, backoff_deadline)
                    if now < deadline:
                        sleep(deadline - now)
                    last_attempt_started = deadline - interval
            assert result is not None
            _validate_cninfo_ca_frame(result, policy)
            try:
                snapshot, _ = _write_cninfo_ca_raw_bundle(
                    raw_root=raw_store.root,
                    spec=spec,
                    result=result,
                    after_data_write=lambda: _fault_point("after_data"),
                    after_metadata_write=lambda: _fault_point("after_metadata"),
                )
            except (OSError, ValueError, M3BackfillError):
                raise M3BackfillError("RAW_WRITE_CONFLICT") from None
            candidate = _cninfo_ca_candidate_from_snapshot(
                spec, snapshot, result, raw_store.root
            )
            _write_dataclass_once(candidate_path, candidate)
            _fault_point("after_candidate")
        receipt = _cninfo_ca_receipt_from_candidate(spec, candidate)
        _fault_point("before_receipt")
        _write_dataclass_once(receipt_path, receipt)
        receipts.append(
            verify_cninfo_corporate_action_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_store.root,
                journal_root=journal_root,
                policy=policy,
            ).receipt
        )
        new_requests_committed += 1
    return CninfoCorporateActionBatchExecutionResult(
        receipts=tuple(receipts), new_requests_committed=new_requests_committed
    )


def _fetch_cninfo_corporate_action(
    connector: CninfoConnector, spec: CninfoCorporateActionRequestSpec
) -> CninfoCorporateActionRawResult:
    params = dict(spec.parameters)
    if spec.endpoint == CNINFO_DIVIDEND_ENDPOINT:
        if set(params) != {"symbol"}:
            raise M3BackfillError("CNINFO_REQUEST_PERMANENT_FAILURE")
        return connector.fetch_stock_dividend_raw(symbol=params["symbol"])
    if spec.endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        if set(params) != {"symbol", "start_date", "end_date"}:
            raise M3BackfillError("CNINFO_REQUEST_PERMANENT_FAILURE")
        return connector.fetch_stock_share_change_raw(
            symbol=params["symbol"],
            start_date=params["start_date"],
            end_date=params["end_date"],
        )
    raise M3BackfillError("CNINFO_REQUEST_PERMANENT_FAILURE")


def _cninfo_ca_raw_paths(
    raw_root: Path, spec: CninfoCorporateActionRequestSpec
) -> tuple[Path, Path]:
    directory = raw_root / CNINFO_SOURCE / spec.endpoint
    return (
        directory / f"{spec.request_id}.json",
        directory / f"{spec.request_id}.metadata.json",
    )


def _inspect_cninfo_ca_raw_state(
    raw_root: Path, spec: CninfoCorporateActionRequestSpec
) -> Literal["ABSENT", "PARTIAL", "COMPLETE"]:
    _preflight_controlled_root(raw_root)
    data_path, metadata_path = _cninfo_ca_raw_paths(raw_root, spec)
    _reject_path_symlinks(raw_root, data_path)
    _reject_path_symlinks(raw_root, metadata_path)
    states: list[bool] = []
    for path in (data_path, metadata_path):
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            states.append(False)
            continue
        except OSError:
            raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None
        if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT")
        states.append(True)
    if states == [False, False]:
        return "ABSENT"
    if states == [True, True]:
        return "COMPLETE"
    return "PARTIAL"


def inspect_cninfo_corporate_action_raw_state(
    *, raw_root: Path, spec: CninfoCorporateActionRequestSpec
) -> Literal["ABSENT", "PARTIAL", "COMPLETE"]:
    """Read-only physical state for one frozen CNINFO CA JSON raw pair."""
    return _inspect_cninfo_ca_raw_state(raw_root, spec)


def _cninfo_ca_records_payload(frame: pl.DataFrame) -> bytes:
    records = [
        {column: row[column] for column in frame.columns}
        for row in frame.iter_rows(named=True)
    ]
    return _canonical_json(records).encode("utf-8")


def _strict_json_records(payload: bytes) -> list[dict[str, Any]]:
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
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise M3BackfillError("RECEIPT_RAW_INVALID") from None
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise M3BackfillError("RECEIPT_RAW_INVALID")
    return value


def _write_payload_once(path: Path, payload: bytes) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise M3BackfillError("RAW_WRITE_CONFLICT") from None
        except OSError:
            raise M3BackfillError("RAW_WRITE_CONFLICT") from None
    except M3BackfillError:
        raise
    except OSError:
        raise M3BackfillError("RAW_WRITE_CONFLICT") from None
    finally:
        has_primary_error = sys.exc_info()[0] is not None
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            if not has_primary_error:
                raise M3BackfillError("RAW_WRITE_CONFLICT") from None


def _cninfo_ca_metadata_payload(
    *,
    spec: CninfoCorporateActionRequestSpec,
    result: CninfoCorporateActionRawResult,
    raw_payload: bytes,
    fetched_at: dt.datetime,
) -> bytes:
    values: dict[str, Any] = {
        "schema_version": "m3-g1-cninfo-corporate-action-raw-metadata-v1",
        "snapshot_id": spec.request_id,
        "request_id": spec.request_id,
        "source": CNINFO_SOURCE,
        "endpoint": spec.endpoint,
        "adapter": spec.adapter,
        "parameters": dict(spec.parameters),
        "fetched_at": fetched_at.isoformat(),
        "resultcode": result.resultcode,
        "resultmsg": result.resultmsg,
        "count": result.count,
        "total": result.total,
        "row_count": result.frame.height,
        "columns": list(result.frame.columns),
        "response_content_sha256": cninfo_corporate_action_response_content_sha256(
            result.frame, endpoint=spec.endpoint
        ),
        "raw_file_sha256": hashlib.sha256(raw_payload).hexdigest(),
        "raw_size_bytes": len(raw_payload),
    }
    values["metadata_content_sha256"] = _sha256(values)
    return _canonical_json(values).encode("utf-8")


def _write_cninfo_ca_raw_bundle(
    *,
    raw_root: Path,
    spec: CninfoCorporateActionRequestSpec,
    result: CninfoCorporateActionRawResult,
    after_data_write: Callable[[], None] | None = None,
    after_metadata_write: Callable[[], None] | None = None,
) -> tuple[_CninfoCorporateActionRawSnapshot, pl.DataFrame]:
    state = _inspect_cninfo_ca_raw_state(raw_root, spec)
    raw_payload = _cninfo_ca_records_payload(result.frame)
    if state == "COMPLETE":
        snapshot, existing = _verify_cninfo_ca_raw_bundle(raw_root=raw_root, spec=spec)
        if (
            snapshot.checksum_sha256 != hashlib.sha256(raw_payload).hexdigest()
            or snapshot.resultcode != result.resultcode
            or snapshot.resultmsg != result.resultmsg
            or snapshot.count != result.count
            or snapshot.total != result.total
        ):
            raise M3BackfillError("RAW_WRITE_CONFLICT")
        return snapshot, existing
    if state != "ABSENT":
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT")
    data_path, metadata_path = _cninfo_ca_raw_paths(raw_root, spec)
    try:
        data_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise M3BackfillError("RAW_WRITE_CONFLICT") from None
    _reject_path_symlinks(raw_root, data_path)
    fetched_at = dt.datetime.now(dt.timezone.utc)
    metadata_payload = _cninfo_ca_metadata_payload(
        spec=spec, result=result, raw_payload=raw_payload, fetched_at=fetched_at
    )
    _write_payload_once(data_path, raw_payload)
    if after_data_write is not None:
        after_data_write()
    _write_payload_once(metadata_path, metadata_payload)
    if after_metadata_write is not None:
        after_metadata_write()
    return _verify_cninfo_ca_raw_bundle(raw_root=raw_root, spec=spec)


def _verify_cninfo_ca_raw_bundle(
    *, raw_root: Path, spec: CninfoCorporateActionRequestSpec
) -> tuple[_CninfoCorporateActionRawSnapshot, pl.DataFrame]:
    if _inspect_cninfo_ca_raw_state(raw_root, spec) != "COMPLETE":
        raise M3BackfillError("RECEIPT_RAW_INVALID")
    data_path, metadata_path = _cninfo_ca_raw_paths(raw_root, spec)
    raw_payload = _read_bytes(data_path, "RECEIPT_RAW_INVALID")
    metadata_payload = _read_bytes(metadata_path, "RECEIPT_RAW_INVALID")
    try:
        metadata = _strict_json(metadata_payload)
        expected_keys = {
            "schema_version",
            "snapshot_id",
            "request_id",
            "source",
            "endpoint",
            "adapter",
            "parameters",
            "fetched_at",
            "resultcode",
            "resultmsg",
            "count",
            "total",
            "row_count",
            "columns",
            "response_content_sha256",
            "raw_file_sha256",
            "raw_size_bytes",
            "metadata_content_sha256",
        }
        if set(metadata) != expected_keys:
            raise ValueError
        metadata_hash = metadata["metadata_content_sha256"]
        unsigned = dict(metadata)
        del unsigned["metadata_content_sha256"]
        if (
            metadata["schema_version"]
            != "m3-g1-cninfo-corporate-action-raw-metadata-v1"
            or metadata["snapshot_id"] != spec.request_id
            or metadata["request_id"] != spec.request_id
            or metadata["source"] != CNINFO_SOURCE
            or metadata["endpoint"] != spec.endpoint
            or metadata["adapter"] != spec.adapter
            or metadata["parameters"] != dict(spec.parameters)
            or metadata_hash != _sha256(unsigned)
        ):
            raise ValueError
        fetched_at = dt.datetime.fromisoformat(metadata["fetched_at"])
        if fetched_at.tzinfo is None:
            raise ValueError
        fields = _ca_fields_for_endpoint(spec.endpoint)
        if metadata["columns"] != list(fields):
            raise ValueError
        for key in ("resultcode", "count", "total", "row_count", "raw_size_bytes"):
            if type(metadata[key]) is not int:
                raise ValueError
        if (
            metadata["resultcode"] != 200
            or metadata["resultmsg"] != "success"
            or metadata["count"] < 0
            or metadata["count"] != metadata["total"]
            or metadata["count"] != metadata["row_count"]
        ):
            raise ValueError
        raw_sha256 = hashlib.sha256(raw_payload).hexdigest()
        if (
            metadata["raw_file_sha256"] != raw_sha256
            or metadata["raw_size_bytes"] != len(raw_payload)
        ):
            raise ValueError
        records = _strict_json_records(raw_payload)
        field_set = set(fields)
        if len(records) != metadata["row_count"]:
            raise ValueError
        if any(
            set(row) != field_set
            or any(value is not None and type(value) is not str for value in row.values())
            for row in records
        ):
            raise ValueError
        frame = (
            _ca_empty_frame(spec.endpoint)
            if not records
            else pl.DataFrame(records, schema={field: pl.Utf8 for field in fields})
        )
        content_sha256 = cninfo_corporate_action_response_content_sha256(
            frame, endpoint=spec.endpoint
        )
        if metadata["response_content_sha256"] != content_sha256:
            raise ValueError
    except (KeyError, TypeError, ValueError, M3BackfillError):
        raise M3BackfillError("RECEIPT_RAW_INVALID") from None
    return (
        _CninfoCorporateActionRawSnapshot(
            snapshot_id=spec.request_id,
            data_path=data_path,
            metadata_path=metadata_path,
            checksum_sha256=raw_sha256,
            metadata_sha256=hashlib.sha256(metadata_payload).hexdigest(),
            size_bytes=len(raw_payload),
            row_count=frame.height,
            columns=tuple(frame.columns),
            resultcode=metadata["resultcode"],
            resultmsg=metadata["resultmsg"],
            count=metadata["count"],
            total=metadata["total"],
        ),
        frame,
    )


def verify_cninfo_corporate_action_receipt(
    *,
    spec: CninfoCorporateActionRequestSpec,
    receipt_path: Path,
    raw_root: Path,
    journal_root: Path,
    policy: EndpointPolicy,
) -> VerifiedCninfoCorporateActionRawResponse:
    expected_path = journal_root / spec.request_id / "receipt.json"
    if receipt_path != expected_path:
        raise M3BackfillError("RECEIPT_PATH_INVALID")
    _reject_path_symlinks(journal_root, receipt_path)
    payload = _read_bytes(receipt_path, "RECEIPT_INVALID")
    try:
        parsed = _strict_json(payload)
        _exact_keys(parsed, CninfoCorporateActionRequestReceipt)
        receipt = CninfoCorporateActionRequestReceipt(
            parsed["schema_version"],
            parsed["request_id"],
            parsed["source"],
            parsed["endpoint"],
            parsed["adapter"],
            _parse_parameters(parsed["parameters"]),
            parsed["parameters_sha256"],
            parsed["raw_snapshot_id"],
            parsed["raw_data_path"],
            parsed["raw_metadata_path"],
            parsed["raw_file_sha256"],
            parsed["raw_metadata_sha256"],
            parsed["response_content_sha256"],
            parsed["stable_response_sha256"],
            parsed["resultcode"],
            parsed["resultmsg"],
            parsed["count"],
            parsed["total"],
            parsed["raw_size_bytes"],
            parsed["row_count"],
            _parse_columns(parsed["columns"]),
        )
    except (TypeError, ValueError, KeyError):
        raise M3BackfillError("RECEIPT_INVALID") from None
    if (
        receipt.request_id != spec.request_id
        or receipt.endpoint != spec.endpoint
        or receipt.adapter != spec.adapter
        or receipt.parameters != spec.parameters
    ):
        raise M3BackfillError("RECEIPT_SPEC_MISMATCH")
    data_path = _resolve_relative(raw_root, receipt.raw_data_path)
    metadata_path = _resolve_relative(raw_root, receipt.raw_metadata_path)
    try:
        snapshot, frame = _verify_cninfo_ca_raw_bundle(
            raw_root=raw_root, spec=spec
        )
    except M3BackfillError:
        raise M3BackfillError("RECEIPT_RAW_INVALID") from None
    if data_path != snapshot.data_path or metadata_path != snapshot.metadata_path:
        raise M3BackfillError("RECEIPT_RAW_PATH_MISMATCH")
    fields = _ca_fields_for_endpoint(spec.endpoint)
    normalized = frame
    if frame.height == 0 and tuple(frame.columns) != fields:
        normalized = _ca_empty_frame(spec.endpoint)
    result = CninfoCorporateActionRawResult(
        endpoint=spec.endpoint,
        frame=frame,
        resultcode=snapshot.resultcode,
        resultmsg=snapshot.resultmsg,
        count=snapshot.count,
        total=snapshot.total,
    )
    _validate_cninfo_ca_frame(result, policy)
    expected_candidate = _cninfo_ca_candidate_from_snapshot(
        spec, snapshot, result, raw_root
    )
    expected_receipt = _cninfo_ca_receipt_from_candidate(spec, expected_candidate)
    content_hash = cninfo_corporate_action_response_content_sha256(
        normalized, endpoint=spec.endpoint
    )
    if (
        receipt.raw_snapshot_id != snapshot.snapshot_id
        or receipt.raw_file_sha256 != snapshot.checksum_sha256
        or receipt.raw_metadata_sha256 != snapshot.metadata_sha256
        or receipt.raw_size_bytes != snapshot.size_bytes
        or receipt.row_count != snapshot.row_count
        or receipt.columns != snapshot.columns
        or receipt.response_content_sha256 != content_hash
        or receipt.resultcode != expected_receipt.resultcode
        or receipt.resultmsg != expected_receipt.resultmsg
        or receipt.count != expected_receipt.count
        or receipt.total != expected_receipt.total
        or receipt.stable_response_sha256 != expected_receipt.stable_response_sha256
    ):
        raise M3BackfillError("RECEIPT_RAW_EVIDENCE_MISMATCH")
    if receipt != expected_receipt:
        raise M3BackfillError("RECEIPT_RAW_EVIDENCE_MISMATCH")
    try:
        return VerifiedCninfoCorporateActionRawResponse(
            spec=spec,
            receipt=receipt,
            receipt_sha256=hashlib.sha256(payload).hexdigest(),
            frame=normalized,
            resultcode=receipt.resultcode,
            resultmsg=receipt.resultmsg,
            count=receipt.count,
            total=receipt.total,
        )
    except ValueError:
        raise M3BackfillError("RECEIPT_CANONICAL_BYTES_MISMATCH") from None


def _validate_cninfo_ca_frame(
    result: CninfoCorporateActionRawResult, policy: EndpointPolicy
) -> None:
    fields = _ca_fields_for_endpoint(result.endpoint)
    if tuple(result.frame.columns) != fields:
        raise M3BackfillError("CNINFO_RESPONSE_COLUMNS_INVALID")
    if result.frame.height == 0 and policy.empty_response == "REJECT":
        raise M3BackfillError("CNINFO_EMPTY_RESPONSE_REJECTED")
    if result.frame.height > policy.row_limit:
        raise M3BackfillError("CNINFO_RESPONSE_ROW_LIMIT")
    if (
        result.resultcode != 200
        or result.resultmsg != "success"
        or result.count != result.total
        or result.count != result.frame.height
    ):
        raise M3BackfillError("CNINFO_RESPONSE_COUNT_MISMATCH")


def _ensure_cninfo_ca_intent(
    path: Path, spec: CninfoCorporateActionRequestSpec
) -> None:
    intent = CninfoCorporateActionRequestIntentV1(
        "m3-g1-cninfo-corporate-action-intent-v1",
        spec.request_id,
        spec.source,
        spec.endpoint,
        spec.adapter,
        spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if path.exists():
        _verify_existing_cninfo_ca_intent(path, spec)
    else:
        _write_dataclass_once(path, intent)


def _verify_existing_cninfo_ca_intent(
    path: Path, spec: CninfoCorporateActionRequestSpec
) -> None:
    try:
        parsed = _strict_json(_read_bytes(path, "INTENT_INVALID"))
        _exact_keys(parsed, CninfoCorporateActionRequestIntentV1)
        existing = CninfoCorporateActionRequestIntentV1(
            parsed["schema_version"],
            parsed["request_id"],
            parsed["source"],
            parsed["endpoint"],
            parsed["adapter"],
            _parse_parameters(parsed["parameters"]),
            parsed["parameters_sha256"],
        )
    except (TypeError, ValueError, KeyError):
        raise M3BackfillError("INTENT_INVALID") from None
    expected = CninfoCorporateActionRequestIntentV1(
        "m3-g1-cninfo-corporate-action-intent-v1",
        spec.request_id,
        spec.source,
        spec.endpoint,
        spec.adapter,
        spec.parameters,
        _parameters_hash(spec.parameters),
    )
    if existing != expected:
        raise M3BackfillError("INTENT_SPEC_MISMATCH")


def _preflight_cninfo_ca_no_receipt(
    *,
    spec: CninfoCorporateActionRequestSpec,
    intent_path: Path,
    candidate_path: Path,
    raw_store: RawStore,
) -> _NoReceiptPreflight:
    try:
        raw_state = _inspect_cninfo_ca_raw_state(raw_store.root, spec)
        intent_exists = _regular_file_exists(intent_path)
        candidate_exists = _regular_file_exists(candidate_path)
    except (OSError, ValueError):
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None
    if raw_state == "PARTIAL":
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT")
    if candidate_exists and (not intent_exists or raw_state != "COMPLETE"):
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if raw_state == "COMPLETE" and not intent_exists:
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if intent_exists:
        _verify_existing_cninfo_ca_intent(intent_path, spec)
    mode: Literal["NETWORK", "RECOVER"] = (
        "RECOVER" if raw_state == "COMPLETE" else "NETWORK"
    )
    return _NoReceiptPreflight(raw_state, intent_exists, candidate_exists, mode)


def validate_cninfo_corporate_action_partial_evidence(
    *,
    spec: CninfoCorporateActionRequestSpec,
    raw_root: Path,
    journal_root: Path,
    policy: EndpointPolicy,
) -> None:
    """Read-only validation for an uncommitted CA request journal."""
    request_dir = journal_root / spec.request_id
    intent_path = request_dir / "intent.json"
    candidate_path = request_dir / "candidate.json"
    receipt_path = request_dir / "receipt.json"
    if _regular_file_exists(receipt_path):
        raise M3BackfillError("COMMITTED_JOURNAL_CONFLICT")
    try:
        raw_state = _inspect_cninfo_ca_raw_state(raw_root, spec)
        intent_exists = _regular_file_exists(intent_path)
        candidate_exists = _regular_file_exists(candidate_path)
    except (OSError, ValueError, M3BackfillError):
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None
    if raw_state == "PARTIAL":
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT")
    if candidate_exists and (not intent_exists or raw_state != "COMPLETE"):
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if raw_state == "COMPLETE" and not intent_exists:
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_INVALID")
    if intent_exists:
        _verify_existing_cninfo_ca_intent(intent_path, spec)
    if candidate_exists:
        try:
            parsed = _strict_json(_read_bytes(candidate_path, "CANDIDATE_INVALID"))
            _exact_keys(parsed, CninfoCorporateActionRawCandidateV1)
            candidate = CninfoCorporateActionRawCandidateV1(
                parsed["schema_version"],
                parsed["request_id"],
                parsed["source"],
                parsed["endpoint"],
                parsed["adapter"],
                parsed["parameters_sha256"],
                parsed["raw_snapshot_id"],
                parsed["raw_data_path"],
                parsed["raw_metadata_path"],
                parsed["raw_file_sha256"],
                parsed["raw_metadata_sha256"],
                parsed["response_content_sha256"],
                parsed["resultcode"],
                parsed["resultmsg"],
                parsed["count"],
                parsed["total"],
                parsed["raw_size_bytes"],
                parsed["row_count"],
                _parse_columns(parsed["columns"]),
            )
        except (TypeError, ValueError, KeyError):
            raise M3BackfillError("CANDIDATE_INVALID") from None
        _verify_cninfo_ca_candidate(spec, candidate, RawStore(raw_root), policy)
    elif raw_state == "COMPLETE":
        snapshot, frame = _verify_cninfo_ca_raw_bundle(raw_root=raw_root, spec=spec)
        _validate_cninfo_ca_frame(
            CninfoCorporateActionRawResult(
                endpoint=spec.endpoint,
                frame=frame,
                resultcode=snapshot.resultcode,
                resultmsg=snapshot.resultmsg,
                count=snapshot.count,
                total=snapshot.total,
            ),
            policy,
        )


def _recover_cninfo_ca_candidate(
    *,
    spec: CninfoCorporateActionRequestSpec,
    candidate_path: Path,
    raw_store: RawStore,
    policy: EndpointPolicy,
    expected_mode: Literal["NETWORK", "RECOVER"],
    expected_candidate_exists: bool,
) -> CninfoCorporateActionRawCandidateV1 | None:
    candidate_exists = _regular_file_exists(candidate_path)
    if candidate_exists != expected_candidate_exists:
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
    try:
        state = _inspect_cninfo_ca_raw_state(raw_store.root, spec)
    except (OSError, ValueError, M3BackfillError):
        raise M3BackfillError("RAW_ORPHAN_OR_INVALID_LAYOUT") from None
    if expected_mode == "NETWORK":
        if candidate_exists or state == "COMPLETE":
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        return None
    if state != "COMPLETE":
        raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
    if candidate_exists:
        try:
            parsed = _strict_json(_read_bytes(candidate_path, "CANDIDATE_INVALID"))
            _exact_keys(parsed, CninfoCorporateActionRawCandidateV1)
            candidate = CninfoCorporateActionRawCandidateV1(
                parsed["schema_version"],
                parsed["request_id"],
                parsed["source"],
                parsed["endpoint"],
                parsed["adapter"],
                parsed["parameters_sha256"],
                parsed["raw_snapshot_id"],
                parsed["raw_data_path"],
                parsed["raw_metadata_path"],
                parsed["raw_file_sha256"],
                parsed["raw_metadata_sha256"],
                parsed["response_content_sha256"],
                parsed["resultcode"],
                parsed["resultmsg"],
                parsed["count"],
                parsed["total"],
                parsed["raw_size_bytes"],
                parsed["row_count"],
                _parse_columns(parsed["columns"]),
            )
        except (TypeError, ValueError, KeyError):
            raise M3BackfillError("CANDIDATE_INVALID") from None
        return _verify_cninfo_ca_candidate(spec, candidate, raw_store, policy)
    try:
        snapshot, frame = _verify_cninfo_ca_raw_bundle(
            raw_root=raw_store.root, spec=spec
        )
        result = CninfoCorporateActionRawResult(
            endpoint=spec.endpoint,
            frame=frame,
            resultcode=snapshot.resultcode,
            resultmsg=snapshot.resultmsg,
            count=snapshot.count,
            total=snapshot.total,
        )
        _validate_cninfo_ca_frame(result, policy)
        candidate = _cninfo_ca_candidate_from_snapshot(
            spec, snapshot, result, raw_store.root
        )
        current_state = _inspect_cninfo_ca_raw_state(raw_store.root, spec)
        if current_state != "COMPLETE":
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        _verify_cninfo_ca_candidate(spec, candidate, raw_store, policy)
        if _regular_file_exists(candidate_path):
            raise M3BackfillError("REQUEST_EVIDENCE_CLOSURE_CHANGED")
        _write_dataclass_once(candidate_path, candidate)
        return candidate
    except M3BackfillError:
        raise
    except (OSError, ValueError):
        raise M3BackfillError("RAW_RECOVERY_INVALID") from None


def _verify_cninfo_ca_candidate(
    spec: CninfoCorporateActionRequestSpec,
    candidate: CninfoCorporateActionRawCandidateV1,
    raw_store: RawStore,
    policy: EndpointPolicy,
) -> CninfoCorporateActionRawCandidateV1:
    if (
        candidate.request_id != spec.request_id
        or candidate.endpoint != spec.endpoint
        or candidate.adapter != spec.adapter
        or candidate.parameters_sha256 != _parameters_hash(spec.parameters)
    ):
        raise M3BackfillError("CANDIDATE_SPEC_MISMATCH")
    try:
        snapshot, frame = _verify_cninfo_ca_raw_bundle(
            raw_root=raw_store.root, spec=spec
        )
    except M3BackfillError:
        raise M3BackfillError("CANDIDATE_RAW_INVALID") from None
    result = CninfoCorporateActionRawResult(
        endpoint=spec.endpoint,
        frame=frame,
        resultcode=snapshot.resultcode,
        resultmsg=snapshot.resultmsg,
        count=snapshot.count,
        total=snapshot.total,
    )
    _validate_cninfo_ca_frame(result, policy)
    expected = _cninfo_ca_candidate_from_snapshot(
        spec, snapshot, result, raw_store.root
    )
    if candidate != expected:
        raise M3BackfillError("CANDIDATE_RAW_EVIDENCE_MISMATCH")
    return candidate


def _cninfo_ca_candidate_from_snapshot(
    spec: CninfoCorporateActionRequestSpec,
    snapshot: _CninfoCorporateActionRawSnapshot,
    result: CninfoCorporateActionRawResult,
    raw_root: Path,
) -> CninfoCorporateActionRawCandidateV1:
    return CninfoCorporateActionRawCandidateV1(
        "m3-g1-cninfo-corporate-action-candidate-v1",
        spec.request_id,
        "cninfo",
        spec.endpoint,
        spec.adapter,
        _parameters_hash(spec.parameters),
        snapshot.snapshot_id,
        snapshot.data_path.relative_to(raw_root).as_posix(),
        snapshot.metadata_path.relative_to(raw_root).as_posix(),
        snapshot.checksum_sha256,
        snapshot.metadata_sha256,
        cninfo_corporate_action_response_content_sha256(
            result.frame, endpoint=spec.endpoint
        ),
        result.resultcode,
        result.resultmsg,
        result.count,
        result.total,
        snapshot.size_bytes,
        snapshot.row_count,
        snapshot.columns,
    )


def _cninfo_ca_receipt_from_candidate(
    spec: CninfoCorporateActionRequestSpec,
    candidate: CninfoCorporateActionRawCandidateV1,
) -> CninfoCorporateActionRequestReceipt:
    values: dict[str, Any] = {
        "schema_version": "m3-g1-cninfo-corporate-action-receipt-v1",
        "request_id": spec.request_id,
        "source": CNINFO_SOURCE,
        "endpoint": spec.endpoint,
        "adapter": spec.adapter,
        "parameters": spec.parameters,
        "parameters_sha256": candidate.parameters_sha256,
        "raw_snapshot_id": candidate.raw_snapshot_id,
        "raw_data_path": candidate.raw_data_path,
        "raw_metadata_path": candidate.raw_metadata_path,
        "raw_file_sha256": candidate.raw_file_sha256,
        "raw_metadata_sha256": candidate.raw_metadata_sha256,
        "response_content_sha256": candidate.response_content_sha256,
        "stable_response_sha256": "0" * 64,
        "resultcode": candidate.resultcode,
        "resultmsg": candidate.resultmsg,
        "count": candidate.count,
        "total": candidate.total,
        "raw_size_bytes": candidate.raw_size_bytes,
        "row_count": candidate.row_count,
        "columns": candidate.columns,
    }
    values["stable_response_sha256"] = _cninfo_ca_stable_response_hash_values(values)
    return CninfoCorporateActionRequestReceipt(**values)
