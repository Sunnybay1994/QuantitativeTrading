"""M3 G1-R1B: recoverable five-stage workflow service skeleton."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from quant.data.connectors.baostock import BaostockConnector
from quant.data.connectors.cninfo import CninfoConnector
from quant.data.connectors.tushare import TushareConnector
from quant.data.m3_backfill import (
    CninfoRequestBatch,
    EndpointPolicy,
    M3BackfillError,
    TushareRequestBatch,
    VerifiedCninfoRawResponse,
    VerifiedRawResponse,
    execute_cninfo_batch,
    execute_tushare_batch,
    verify_cninfo_receipt,
    verify_tushare_receipt,
)
from quant.data.m3_g1_candidate import (
    G1BuildInputs,
    G1Candidate,
    M3G1CandidateError,
    audit_g1_candidate,
    build_g1_candidate,
    verify_g1_candidate,
)
from quant.data.m3_reference import (
    M3ReferenceError,
    VerifiedReferenceResponse,
    execute_baostock_reference_plan,
    plan_baostock_reference_requests,
    plan_cross_source_reconciliation,
    reconcile_cross_source,
    verify_reference_receipt,
)
from quant.data.m3_release import (
    G1PreparedRelease,
    G1Release,
    G1ReleaseInputs,
    M3ReleaseError,
    VerifiedG1Release,
    platform_supports_renameat2_noreplace,
    prepare_g1_release,
    publish_g1_release,
    verify_g1_release,
)
from quant.data.storage import RawStore
from quant.domain import InstrumentSchema, TradeCalendarSchema
from quant.research.m3.config import LoadedM3Config
from quant.research.m3.g1_planning import (
    G1DerivedHistoryPlanV1,
    G1StaticPlanV1,
    M3G1PlanningError,
    build_g1_static_plan,
    derive_g1_history_plan,
)

Stage = Literal["INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"]
Operation = Literal["INSPECT", "INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"]
CauseCategory = Literal[
    "INPUT",
    "PATH",
    "SOURCE_SCHEMA",
    "JOURNAL",
    "NETWORK",
    "MEMBERSHIP",
    "CANDIDATE",
    "REFERENCE",
    "RELEASE",
    "UNSUPPORTED",
]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_A_SHARE = re.compile(r"^[0-9]{6}\.(?:SH|SZ)$")
_SCHEMA: Literal["m3-g1-workflow-state-v1"] = "m3-g1-workflow-state-v1"
_STAGE_ORDER: tuple[Stage, ...] = (
    "INDEX",
    "HISTORY",
    "REFERENCE",
    "PREPARE",
    "PUBLISH",
)

_REL_CAL_SH = "data/clean/trade_calendar/market=SH/data.parquet"
_REL_CAL_SZ = "data/clean/trade_calendar/market=SZ/data.parquet"
_REL_INST_SH = "data/clean/instrument/market=SH/data.parquet"
_REL_INST_SZ = "data/clean/instrument/market=SZ/data.parquet"
_REL_RAW = "data/raw/m3_g1"
_REL_JOURNAL_TS = "data/run_state/m3_g1/tushare"
_REL_JOURNAL_BS = "data/run_state/m3_g1/baostock"
_REL_JOURNAL_CN = "data/run_state/m3_g1/cninfo"
_REL_RELEASE = "data/clean/m3_g1/releases"

_ERROR_CODES = frozenset(
    {
        "G1_WORKFLOW_INPUT_INVALID",
        "G1_WORKFLOW_PROJECT_ROOT_INVALID",
        "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
        "G1_WORKFLOW_INDEX_INCOMPLETE",
        "G1_WORKFLOW_HISTORY_INCOMPLETE",
        "G1_WORKFLOW_REFERENCE_INCOMPLETE",
        "G1_WORKFLOW_JOURNAL_INVALID",
        "G1_WORKFLOW_EXECUTION_FAILED",
        "G1_WORKFLOW_QUALITY_FAILED",
        "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
        "G1_WORKFLOW_PUBLISH_FAILED",
        "G1_WORKFLOW_IDENTITY_MISMATCH",
    }
)
_CLASSIFY_ALLOWED = frozenset(
    {"NETWORK", "RATE_LIMIT", "TRANSIENT_SERVER", "PERMANENT"}
)


class M3G1WorkflowError(ValueError):
    """Stable R1B workflow boundary error; ``str(error)`` equals ``operation:code``."""

    code: Literal[
        "G1_WORKFLOW_INPUT_INVALID",
        "G1_WORKFLOW_PROJECT_ROOT_INVALID",
        "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
        "G1_WORKFLOW_INDEX_INCOMPLETE",
        "G1_WORKFLOW_HISTORY_INCOMPLETE",
        "G1_WORKFLOW_REFERENCE_INCOMPLETE",
        "G1_WORKFLOW_JOURNAL_INVALID",
        "G1_WORKFLOW_EXECUTION_FAILED",
        "G1_WORKFLOW_QUALITY_FAILED",
        "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
        "G1_WORKFLOW_PUBLISH_FAILED",
        "G1_WORKFLOW_IDENTITY_MISMATCH",
    ]
    operation: Operation
    cause_category: CauseCategory

    def __init__(
        self,
        code: str,
        *,
        operation: Operation,
        cause_category: CauseCategory,
    ) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown g1 workflow error code")
        if operation not in {
            "INSPECT",
            "INDEX",
            "HISTORY",
            "REFERENCE",
            "PREPARE",
            "PUBLISH",
        }:
            raise ValueError("unknown g1 workflow operation")
        if cause_category not in {
            "INPUT",
            "PATH",
            "SOURCE_SCHEMA",
            "JOURNAL",
            "NETWORK",
            "MEMBERSHIP",
            "CANDIDATE",
            "REFERENCE",
            "RELEASE",
            "UNSUPPORTED",
        }:
            raise ValueError("unknown g1 workflow cause category")
        self.code = cast(Any, code)
        self.operation = operation
        self.cause_category = cause_category
        super().__init__(f"{operation}:{code}")

    def __str__(self) -> str:
        return f"{self.operation}:{self.code}"

    def __repr__(self) -> str:
        return (
            f"M3G1WorkflowError({self.code!r}, operation={self.operation!r}, "
            f"cause_category={self.cause_category!r})"
        )


@dataclass(frozen=True)
class G1WorkflowCountsV1:
    index_requests: int
    history_requests: int
    reference_requests: int
    history_symbols: int

    def __post_init__(self) -> None:
        for name in (
            "index_requests",
            "history_requests",
            "reference_requests",
            "history_symbols",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError("g1 workflow counts 非法")


@dataclass(frozen=True)
class VerifiedG1WorkflowStateV1:
    schema_version: Literal["m3-g1-workflow-state-v1"]
    static_plan: G1StaticPlanV1
    derived_plan: G1DerivedHistoryPlanV1 | None
    index_responses: tuple[VerifiedRawResponse, ...]
    history_responses: tuple[VerifiedRawResponse, ...]
    cninfo_responses: tuple[VerifiedCninfoRawResponse, ...]
    reference_responses: tuple[VerifiedReferenceResponse, ...]
    candidate: G1Candidate | None
    prepared: G1PreparedRelease | None
    published: VerifiedG1Release | None
    completed_stages: tuple[Stage, ...]
    counts: G1WorkflowCountsV1

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA:
            raise ValueError("workflow state schema_version 非法")
        if type(self.static_plan) is not G1StaticPlanV1:
            raise ValueError("workflow state static_plan 类型非法")
        if self.derived_plan is not None and type(self.derived_plan) is not G1DerivedHistoryPlanV1:
            raise ValueError("workflow state derived_plan 类型非法")
        if type(self.index_responses) is not tuple or any(
            type(item) is not VerifiedRawResponse for item in self.index_responses
        ):
            raise ValueError("workflow state index_responses 非法")
        if type(self.history_responses) is not tuple or any(
            type(item) is not VerifiedRawResponse for item in self.history_responses
        ):
            raise ValueError("workflow state history_responses 非法")
        if type(self.cninfo_responses) is not tuple or any(
            type(item) is not VerifiedCninfoRawResponse for item in self.cninfo_responses
        ):
            raise ValueError("workflow state cninfo_responses 非法")
        if type(self.reference_responses) is not tuple or any(
            type(item) is not VerifiedReferenceResponse for item in self.reference_responses
        ):
            raise ValueError("workflow state reference_responses 非法")
        if self.candidate is not None and type(self.candidate) is not G1Candidate:
            raise ValueError("workflow state candidate 类型非法")
        if self.prepared is not None and type(self.prepared) is not G1PreparedRelease:
            raise ValueError("workflow state prepared 类型非法")
        if self.published is not None and type(self.published) is not VerifiedG1Release:
            raise ValueError("workflow state published 类型非法")
        if type(self.completed_stages) is not tuple or any(
            item not in _STAGE_ORDER for item in self.completed_stages
        ):
            raise ValueError("workflow state completed_stages 非法")
        if self.completed_stages != _STAGE_ORDER[: len(self.completed_stages)]:
            raise ValueError("workflow state completed_stages 必须是固定前缀")
        if type(self.counts) is not G1WorkflowCountsV1:
            raise ValueError("workflow state counts 类型非法")
        try:
            _validate_workflow_state_closure(self)
        except ValueError:
            raise
        except Exception:
            raise ValueError("workflow state 阶段产物闭包非法") from None


@dataclass(frozen=True)
class _FileFingerprint:
    sha256: str
    st_dev: int
    st_ino: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _Layout:
    root: Path
    root_id: tuple[int, int]
    ancestors: tuple[tuple[str, tuple[int, int]], ...]
    raw_root: Path
    tushare_journal: Path
    baostock_journal: Path
    cninfo_journal: Path
    release_root: Path
    cal_sh: Path
    cal_sz: Path
    inst_sh: Path
    inst_sz: Path


@dataclass(frozen=True)
class _SourceContext:
    calendars: pl.DataFrame
    instruments: pl.DataFrame


def inspect_g1_workflow(
    *, project_root: Path, config: LoadedM3Config
) -> VerifiedG1WorkflowStateV1:
    return _inspect(project_root=project_root, config=config, operation="INSPECT")


def run_g1_index_stage(
    *,
    project_root: Path,
    config: LoadedM3Config,
    connector: TushareConnector,
    classify_error: Callable[[BaseException], str],
) -> VerifiedG1WorkflowStateV1:
    operation: Operation = "INDEX"
    if type(connector) is not TushareConnector:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INPUT_INVALID", operation=operation, cause_category="INPUT"
        ) from None
    state = _inspect(project_root=project_root, config=config, operation=operation)
    if "INDEX" in state.completed_stages:
        return state
    layout = _open_layout(project_root, operation=operation)
    policies = dict(state.static_plan.endpoint_policies)
    try:
        execute_tushare_batch(
            batch=state.static_plan.index_weight_batch,
            connector=connector,
            raw_store=RawStore(layout.raw_root),
            journal_root=layout.tushare_journal,
            endpoint_policies=policies,
            request_rate_per_minute=state.static_plan.request_rate_per_minute,
            max_attempts=state.static_plan.max_attempts,
            retry_base_seconds=state.static_plan.retry_base_seconds,
            classify_error=_checked_classify(classify_error),
        )
    except M3BackfillError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_EXECUTION_FAILED",
            operation=operation,
            cause_category="NETWORK",
        ) from None
    except M3G1WorkflowError:
        raise
    except Exception:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_EXECUTION_FAILED",
            operation=operation,
            cause_category="NETWORK",
        ) from None
    again = _inspect(project_root=project_root, config=config, operation=operation)
    if "INDEX" not in again.completed_stages:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INDEX_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    return again


@dataclass(frozen=True)
class G1HistoryStageResultV1:
    state: VerifiedG1WorkflowStateV1
    max_new_requests: int | None
    new_requests_committed: int

    def __post_init__(self) -> None:
        if type(self.state) is not VerifiedG1WorkflowStateV1:
            raise ValueError("history stage state type invalid")
        if self.max_new_requests is not None and (
            type(self.max_new_requests) is not int or self.max_new_requests <= 0
        ):
            raise ValueError("history stage max_new_requests invalid")
        if type(self.new_requests_committed) is not int or self.new_requests_committed < 0:
            raise ValueError("history stage new_requests_committed invalid")


def run_g1_history_stage(
    *,
    project_root: Path,
    config: LoadedM3Config,
    connector: TushareConnector,
    classify_error: Callable[[BaseException], str],
    max_new_requests: int | None = None,
    cninfo_connector: CninfoConnector | None = None,
) -> G1HistoryStageResultV1:
    operation: Operation = "HISTORY"
    if max_new_requests is not None and (
        type(max_new_requests) is not int or max_new_requests <= 0
    ):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INPUT_INVALID", operation=operation, cause_category="INPUT"
        ) from None
    if type(connector) is not TushareConnector:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INPUT_INVALID", operation=operation, cause_category="INPUT"
        ) from None
    if cninfo_connector is not None and type(cninfo_connector) is not CninfoConnector:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INPUT_INVALID", operation=operation, cause_category="INPUT"
        ) from None
    state = _inspect(project_root=project_root, config=config, operation=operation)
    if "INDEX" not in state.completed_stages:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INDEX_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    if "HISTORY" in state.completed_stages:
        return G1HistoryStageResultV1(
            state=state,
            max_new_requests=max_new_requests,
            new_requests_committed=0,
        )
    if state.derived_plan is None:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INDEX_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    layout = _open_layout(project_root, operation=operation)
    policies = dict(state.static_plan.endpoint_policies)
    remaining = max_new_requests
    committed = 0
    try:
        executed = execute_tushare_batch(
            batch=state.derived_plan.request_plan.history_batch,
            connector=connector,
            raw_store=RawStore(layout.raw_root),
            journal_root=layout.tushare_journal,
            endpoint_policies=policies,
            request_rate_per_minute=state.static_plan.request_rate_per_minute,
            max_attempts=state.static_plan.max_attempts,
            retry_base_seconds=state.static_plan.retry_base_seconds,
            classify_error=_checked_classify(classify_error),
            max_new_requests=remaining,
        )
        committed += executed.new_requests_committed
        if remaining is not None:
            remaining = max(0, remaining - executed.new_requests_committed)
        cninfo = cninfo_connector if cninfo_connector is not None else CninfoConnector(
            row_limit=_cninfo_row_limit(config)
        )
        cninfo_executed = execute_cninfo_batch(
            batch=state.derived_plan.request_plan.cninfo_rights_batch,
            connector=cninfo,
            raw_store=RawStore(layout.raw_root),
            journal_root=layout.cninfo_journal,
            row_limit=_cninfo_row_limit(config),
            request_rate_per_minute=state.static_plan.request_rate_per_minute,
            max_attempts=state.static_plan.max_attempts,
            retry_base_seconds=state.static_plan.retry_base_seconds,
            classify_error=_checked_classify(classify_error),
            max_new_requests=remaining,
        )
        committed += cninfo_executed.new_requests_committed
    except M3BackfillError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_EXECUTION_FAILED",
            operation=operation,
            cause_category="NETWORK",
        ) from None
    except M3G1WorkflowError:
        raise
    except Exception:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_EXECUTION_FAILED",
            operation=operation,
            cause_category="NETWORK",
        ) from None
    again = _inspect(project_root=project_root, config=config, operation=operation)
    if "HISTORY" not in again.completed_stages:
        if max_new_requests is None:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_HISTORY_INCOMPLETE",
                operation=operation,
                cause_category="JOURNAL",
            ) from None
        return G1HistoryStageResultV1(
            state=again,
            max_new_requests=max_new_requests,
            new_requests_committed=committed,
        )
    return G1HistoryStageResultV1(
        state=again,
        max_new_requests=max_new_requests,
        new_requests_committed=committed,
    )


# Frozen default; TOML knobs require config.py whitelist expansion (outside P0F).
_CNINFO_STOCK_ALLOTMENT_ROW_LIMIT = 5000


def _cninfo_row_limit(config: LoadedM3Config) -> int:
    del config
    return _CNINFO_STOCK_ALLOTMENT_ROW_LIMIT


def run_g1_reference_stage(
    *,
    project_root: Path,
    config: LoadedM3Config,
    connector: BaostockConnector,
) -> VerifiedG1WorkflowStateV1:
    operation: Operation = "REFERENCE"
    if type(connector) is not BaostockConnector:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INPUT_INVALID", operation=operation, cause_category="INPUT"
        ) from None
    state = _inspect(project_root=project_root, config=config, operation=operation)
    if "HISTORY" not in state.completed_stages:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_HISTORY_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    if "REFERENCE" in state.completed_stages:
        return state
    if state.candidate is None:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_HISTORY_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    layout = _open_layout(project_root, operation=operation)
    try:
        sample_plan = plan_cross_source_reconciliation(
            candidate=state.candidate, policy=state.static_plan.cross_source_policy
        )
        request_plan = plan_baostock_reference_requests(sample_plan=sample_plan)
        execute_baostock_reference_plan(
            sample_plan=sample_plan,
            plan=request_plan,
            connector=connector,
            raw_store=RawStore(layout.raw_root),
            journal_root=layout.baostock_journal,
        )
    except M3ReferenceError as exc:
        code, category = _map_reference_error(exc)
        raise M3G1WorkflowError(code, operation=operation, cause_category=category) from None
    except M3G1WorkflowError:
        raise
    except Exception:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_EXECUTION_FAILED",
            operation=operation,
            cause_category="REFERENCE",
        ) from None
    again = _inspect(project_root=project_root, config=config, operation=operation)
    if "REFERENCE" not in again.completed_stages:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_REFERENCE_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    return again


def prepare_g1_workflow(
    *, project_root: Path, config: LoadedM3Config
) -> VerifiedG1WorkflowStateV1:
    operation: Operation = "PREPARE"
    state = _inspect(project_root=project_root, config=config, operation=operation)
    if "REFERENCE" not in state.completed_stages:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_REFERENCE_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    prepared = _prepare_from_state(state, operation=operation)
    completed = cast(tuple[Stage, ...], ("INDEX", "HISTORY", "REFERENCE", "PREPARE"))
    return VerifiedG1WorkflowStateV1(
        schema_version=_SCHEMA,
        static_plan=state.static_plan,
        derived_plan=state.derived_plan,
        index_responses=state.index_responses,
        history_responses=state.history_responses,
        cninfo_responses=state.cninfo_responses,
        reference_responses=state.reference_responses,
        candidate=state.candidate,
        prepared=prepared,
        published=None,
        completed_stages=completed,
        counts=state.counts,
    )


def publish_g1_workflow(
    *, project_root: Path, config: LoadedM3Config
) -> VerifiedG1WorkflowStateV1:
    operation: Operation = "PUBLISH"
    prepared_state = prepare_g1_workflow(project_root=project_root, config=config)
    if prepared_state.prepared is None or prepared_state.candidate is None:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_REFERENCE_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    if not platform_supports_renameat2_noreplace():
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
            operation=operation,
            cause_category="UNSUPPORTED",
        ) from None
    layout = _open_layout(project_root, operation=operation)
    release_inputs = G1ReleaseInputs(
        build_inputs=_build_inputs_from_state(prepared_state, operation=operation),
        cross_source_policy=prepared_state.static_plan.cross_source_policy,
        reference_responses=prepared_state.reference_responses,
    )
    try:
        publish_g1_release(output_root=layout.release_root, inputs=release_inputs)
    except M3ReleaseError as exc:
        if exc.code == "G1_RELEASE_PUBLISH_UNSUPPORTED":
            raise M3G1WorkflowError(
                "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
                operation=operation,
                cause_category="UNSUPPORTED",
            ) from None
        if exc.code in {"G1_RELEASE_QUALITY_FAILED"}:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_QUALITY_FAILED",
                operation=operation,
                cause_category="RELEASE",
            ) from None
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PUBLISH_FAILED",
            operation=operation,
            cause_category="RELEASE",
        ) from None
    except Exception:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PUBLISH_FAILED",
            operation=operation,
            cause_category="RELEASE",
        ) from None
    again = _inspect(project_root=project_root, config=config, operation=operation)
    if "PUBLISH" not in again.completed_stages:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PUBLISH_FAILED",
            operation=operation,
            cause_category="RELEASE",
        ) from None
    return again


def _inspect(
    *, project_root: Path, config: LoadedM3Config, operation: Operation
) -> VerifiedG1WorkflowStateV1:
    layout = _open_layout(project_root, operation=operation)
    try:
        static_plan = build_g1_static_plan(config=config, project_root=layout.root)
    except M3G1PlanningError as exc:
        raise _map_planning_error(exc, operation=operation) from None
    except Exception:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_INPUT_INVALID", operation=operation, cause_category="INPUT"
        ) from None

    source = _load_source_context(layout, static_plan=static_plan, operation=operation)
    policies = dict(static_plan.endpoint_policies)
    index_status = _recover_tushare_batch(
        batch=static_plan.index_weight_batch,
        raw_root=layout.raw_root,
        journal_root=layout.tushare_journal,
        policies=policies,
        operation=operation,
    )
    derived: G1DerivedHistoryPlanV1 | None = None
    history_responses: tuple[VerifiedRawResponse, ...] = ()
    cninfo_responses: tuple[VerifiedCninfoRawResponse, ...] = ()
    candidate: G1Candidate | None = None
    reference_responses: tuple[VerifiedReferenceResponse, ...] = ()
    prepared: G1PreparedRelease | None = None
    published: VerifiedG1Release | None = None
    completed: list[Stage] = []

    if index_status == "complete":
        index_responses = _verify_tushare_complete(
            batch=static_plan.index_weight_batch,
            raw_root=layout.raw_root,
            journal_root=layout.tushare_journal,
            policies=policies,
            operation=operation,
        )
        try:
            derived = derive_g1_history_plan(
                config=config,
                project_root=layout.root,
                static_plan=static_plan,
                index_responses=index_responses,
                calendars=source.calendars,
                instruments=source.instruments,
            )
        except M3G1PlanningError as exc:
            raise _map_planning_error(exc, operation=operation) from None
        completed.append("INDEX")
        history_status = _recover_tushare_batch(
            batch=derived.request_plan.history_batch,
            raw_root=layout.raw_root,
            journal_root=layout.tushare_journal,
            policies=policies,
            operation=operation,
        )
        if history_status == "complete":
            history_responses = _verify_tushare_complete(
                batch=derived.request_plan.history_batch,
                raw_root=layout.raw_root,
                journal_root=layout.tushare_journal,
                policies=policies,
                operation=operation,
            )
            cninfo_status = _recover_cninfo_batch(
                batch=derived.request_plan.cninfo_rights_batch,
                raw_root=layout.raw_root,
                journal_root=layout.cninfo_journal,
                row_limit=_cninfo_row_limit(config),
                operation=operation,
            )
            if cninfo_status == "complete":
                cninfo_responses = _verify_cninfo_complete(
                    batch=derived.request_plan.cninfo_rights_batch,
                    raw_root=layout.raw_root,
                    journal_root=layout.cninfo_journal,
                    row_limit=_cninfo_row_limit(config),
                    operation=operation,
                )
                build_inputs = _make_build_inputs(
                    static_plan=static_plan,
                    derived=derived,
                    index_responses=index_responses,
                    history_responses=history_responses,
                    cninfo_responses=cninfo_responses,
                    calendars=source.calendars,
                    instruments=source.instruments,
                    operation=operation,
                )
                try:
                    candidate = build_g1_candidate(inputs=build_inputs)
                    verify_g1_candidate(inputs=build_inputs, candidate=candidate)
                    audit = audit_g1_candidate(candidate=candidate)
                except M3G1CandidateError:
                    raise M3G1WorkflowError(
                        "G1_WORKFLOW_QUALITY_FAILED",
                        operation=operation,
                        cause_category="CANDIDATE",
                    ) from None
                except Exception:
                    raise M3G1WorkflowError(
                        "G1_WORKFLOW_IDENTITY_MISMATCH",
                        operation=operation,
                        cause_category="MEMBERSHIP",
                    ) from None
                if not audit.passed:
                    raise M3G1WorkflowError(
                        "G1_WORKFLOW_QUALITY_FAILED",
                        operation=operation,
                        cause_category="CANDIDATE",
                    ) from None
                completed.append("HISTORY")
                try:
                    sample_plan = plan_cross_source_reconciliation(
                        candidate=candidate, policy=static_plan.cross_source_policy
                    )
                    request_plan = plan_baostock_reference_requests(sample_plan=sample_plan)
                except M3ReferenceError as exc:
                    code, category = _map_reference_error(exc)
                    raise M3G1WorkflowError(
                        code, operation=operation, cause_category=category
                    ) from None
                ref_status = _recover_reference_batch(
                    specs=request_plan.requests,
                    raw_root=layout.raw_root,
                    journal_root=layout.baostock_journal,
                    operation=operation,
                )
                if ref_status == "complete":
                    reference_responses = _verify_reference_complete(
                        specs=request_plan.requests,
                        raw_root=layout.raw_root,
                        journal_root=layout.baostock_journal,
                        operation=operation,
                    )
                    try:
                        reconciliation = reconcile_cross_source(
                            candidate=candidate,
                            sample_plan=sample_plan,
                            reference_responses=reference_responses,
                            policy=static_plan.cross_source_policy,
                        )
                    except M3ReferenceError as exc:
                        code, category = _map_reference_error(exc)
                        raise M3G1WorkflowError(
                            code, operation=operation, cause_category=category
                        ) from None
                    if not reconciliation.passed:
                        raise M3G1WorkflowError(
                            "G1_WORKFLOW_QUALITY_FAILED",
                            operation=operation,
                            cause_category="REFERENCE",
                        ) from None
                    completed.append("REFERENCE")
                    try:
                        transient = prepare_g1_release(
                            inputs=G1ReleaseInputs(
                                build_inputs=build_inputs,
                                cross_source_policy=static_plan.cross_source_policy,
                                reference_responses=reference_responses,
                            )
                        )
                    except M3ReleaseError as exc:
                        raise _map_release_error(exc, operation=operation) from None
                    release_dir = layout.release_root / transient.release_id
                    if _path_exists_nofollow(release_dir):
                        try:
                            release = G1Release(
                                release_id=transient.release_id,
                                root=release_dir,
                                manifest_path=release_dir / "manifest.json",
                                quality_path=release_dir / "quality.json",
                            )
                            verified = verify_g1_release(release=release)
                            _assert_prepared_matches_verified(transient, verified)
                        except M3ReleaseError:
                            raise M3G1WorkflowError(
                                "G1_WORKFLOW_PUBLISH_FAILED",
                                operation=operation,
                                cause_category="RELEASE",
                            ) from None
                        except Exception:
                            raise M3G1WorkflowError(
                                "G1_WORKFLOW_IDENTITY_MISMATCH",
                                operation=operation,
                                cause_category="RELEASE",
                            ) from None
                        prepared = transient
                        published = verified
                        completed.extend(["PREPARE", "PUBLISH"])
    else:
        index_responses = ()

    counts = _counts(
        static_plan=static_plan,
        derived=derived,
        candidate=candidate,
    )
    _assert_root_unchanged(layout, operation=operation)
    return VerifiedG1WorkflowStateV1(
        schema_version=_SCHEMA,
        static_plan=static_plan,
        derived_plan=derived,
        index_responses=index_responses,
        history_responses=history_responses,
        cninfo_responses=cninfo_responses,
        reference_responses=reference_responses,
        candidate=candidate,
        prepared=prepared,
        published=published,
        completed_stages=tuple(completed),
        counts=counts,
    )


def _validate_workflow_state_closure(state: VerifiedG1WorkflowStateV1) -> None:
    """Bidirectional stage/artifact/counts closure for verified workflow state."""
    stages = state.completed_stages
    has_index = "INDEX" in stages
    has_history = "HISTORY" in stages
    has_reference = "REFERENCE" in stages
    has_prepare = "PREPARE" in stages
    has_publish = "PUBLISH" in stages
    index_total = len(state.static_plan.index_weight_batch.requests)

    if not has_index:
        if (
            state.index_responses != ()
            or state.derived_plan is not None
            or state.history_responses != ()
            or state.reference_responses != ()
            or state.candidate is not None
            or state.prepared is not None
            or state.published is not None
        ):
            raise ValueError("workflow state INDEX 未完成产物闭包非法")
        expected = G1WorkflowCountsV1(
            index_requests=index_total,
            history_requests=0,
            reference_requests=0,
            history_symbols=0,
        )
        if state.counts != expected:
            raise ValueError("workflow state counts 与计划 totals 不一致")
        return

    expected_index_ids = tuple(
        spec.request_id for spec in state.static_plan.index_weight_batch.requests
    )
    actual_index_ids = tuple(item.spec.request_id for item in state.index_responses)
    if actual_index_ids != expected_index_ids:
        raise ValueError("workflow state index responses 闭包非法")
    if state.derived_plan is None:
        raise ValueError("workflow state INDEX 完成必须有 derived_plan")

    history_total = len(state.derived_plan.request_plan.history_batch.requests)
    history_symbols = len(state.derived_plan.history_symbols)

    if not has_history:
        if (
            state.history_responses != ()
            or state.reference_responses != ()
            or state.candidate is not None
            or state.prepared is not None
            or state.published is not None
        ):
            raise ValueError("workflow state HISTORY 未完成产物闭包非法")
        expected = G1WorkflowCountsV1(
            index_requests=index_total,
            history_requests=history_total,
            reference_requests=0,
            history_symbols=history_symbols,
        )
        if state.counts != expected:
            raise ValueError("workflow state counts 与计划 totals 不一致")
        return

    expected_history_ids = tuple(
        spec.request_id
        for spec in state.derived_plan.request_plan.history_batch.requests
    )
    actual_history_ids = tuple(item.spec.request_id for item in state.history_responses)
    if actual_history_ids != expected_history_ids:
        raise ValueError("workflow state history responses 闭包非法")
    if state.candidate is None:
        raise ValueError("workflow state HISTORY 完成必须有 candidate")

    try:
        sample_plan = plan_cross_source_reconciliation(
            candidate=state.candidate,
            policy=state.static_plan.cross_source_policy,
        )
        request_plan = plan_baostock_reference_requests(sample_plan=sample_plan)
    except Exception:
        raise ValueError("workflow state reference plan 派生非法") from None
    expected_ref_ids = tuple(spec.request_id for spec in request_plan.requests)
    reference_total = len(expected_ref_ids)
    expected = G1WorkflowCountsV1(
        index_requests=index_total,
        history_requests=history_total,
        reference_requests=reference_total,
        history_symbols=history_symbols,
    )
    if state.counts != expected:
        raise ValueError("workflow state counts 与计划 totals 不一致")

    if not has_reference:
        if (
            state.reference_responses != ()
            or state.prepared is not None
            or state.published is not None
        ):
            raise ValueError("workflow state REFERENCE 未完成产物闭包非法")
        return

    actual_ref_ids = tuple(item.spec.request_id for item in state.reference_responses)
    if actual_ref_ids != expected_ref_ids:
        raise ValueError("workflow state reference responses 闭包非法")

    if not has_prepare:
        if state.prepared is not None or state.published is not None:
            raise ValueError("workflow state PREPARE 未完成产物闭包非法")
        return

    if state.prepared is None:
        raise ValueError("workflow state PREPARE 完成必须有 prepared")
    if (
        state.prepared.candidate.primary_candidate_key
        != state.candidate.primary_candidate_key
        or state.prepared.candidate.request_plan.plan_sha256
        != state.candidate.request_plan.plan_sha256
    ):
        raise ValueError("workflow state prepared 与 candidate 不一致")

    if not has_publish:
        if state.published is not None:
            raise ValueError("workflow state PUBLISH 未完成产物闭包非法")
        return

    if state.published is None:
        raise ValueError("workflow state PUBLISH 完成必须有 published")
    try:
        _assert_prepared_matches_verified(state.prepared, state.published)
    except Exception:
        raise ValueError("workflow state prepared/published 不一致") from None


def _counts(
    *,
    static_plan: G1StaticPlanV1,
    derived: G1DerivedHistoryPlanV1 | None,
    candidate: G1Candidate | None,
) -> G1WorkflowCountsV1:
    index_requests = len(static_plan.index_weight_batch.requests)
    if derived is None:
        return G1WorkflowCountsV1(
            index_requests=index_requests,
            history_requests=0,
            reference_requests=0,
            history_symbols=0,
        )
    history_requests = len(derived.request_plan.history_batch.requests)
    history_symbols = len(derived.history_symbols)
    reference_requests = 0
    if candidate is not None:
        sample_plan = plan_cross_source_reconciliation(
            candidate=candidate, policy=static_plan.cross_source_policy
        )
        request_plan = plan_baostock_reference_requests(sample_plan=sample_plan)
        reference_requests = len(request_plan.requests)
    return G1WorkflowCountsV1(
        index_requests=index_requests,
        history_requests=history_requests,
        reference_requests=reference_requests,
        history_symbols=history_symbols,
    )


def _prepare_from_state(
    state: VerifiedG1WorkflowStateV1, *, operation: Operation
) -> G1PreparedRelease:
    try:
        return prepare_g1_release(
            inputs=G1ReleaseInputs(
                build_inputs=_build_inputs_from_state(state, operation=operation),
                cross_source_policy=state.static_plan.cross_source_policy,
                reference_responses=state.reference_responses,
            )
        )
    except M3ReleaseError as exc:
        raise _map_release_error(exc, operation=operation) from None


def _build_inputs_from_state(
    state: VerifiedG1WorkflowStateV1, *, operation: Operation
) -> G1BuildInputs:
    if state.derived_plan is None or state.candidate is None:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_HISTORY_INCOMPLETE",
            operation=operation,
            cause_category="JOURNAL",
        ) from None
    return G1BuildInputs(
        build_spec=state.candidate.build_spec,
        request_plan=state.candidate.request_plan,
        responses=state.index_responses + state.history_responses,
        cninfo_responses=state.cninfo_responses,
        calendars=state.candidate.calendars,
        instruments=state.candidate.instruments,
        universe=state.static_plan.universe,
        signal_start=state.static_plan.signal_start,
        signal_end=state.static_plan.signal_end,
        history=state.derived_plan.history,
        expected_constituent_count=state.static_plan.expected_constituent_count,
        factor_ratio_rtol=state.static_plan.factor_ratio_rtol,
    )


def _make_build_inputs(
    *,
    static_plan: G1StaticPlanV1,
    derived: G1DerivedHistoryPlanV1,
    index_responses: Sequence[VerifiedRawResponse],
    history_responses: Sequence[VerifiedRawResponse],
    cninfo_responses: Sequence[VerifiedCninfoRawResponse],
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
    operation: Operation,
) -> G1BuildInputs:
    history = derived.history
    cal_slice = calendars.filter(
        (pl.col("date") >= history.start) & (pl.col("date") <= history.end)
    )
    _assert_calendar_slice(
        cal_slice,
        history_start=history.start,
        history_end=history.end,
        operation=operation,
    )
    inst_slice = instruments.filter(pl.col("symbol").is_in(list(derived.history_symbols)))
    if inst_slice.height != len(derived.history_symbols):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if set(inst_slice.get_column("symbol").to_list()) != set(derived.history_symbols):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    responses = tuple(index_responses) + tuple(history_responses)
    try:
        return G1BuildInputs(
            build_spec=static_plan.build_spec,
            request_plan=derived.request_plan,
            responses=responses,
            cninfo_responses=tuple(cninfo_responses),
            calendars=cal_slice,
            instruments=inst_slice,
            universe=static_plan.universe,
            signal_start=static_plan.signal_start,
            signal_end=static_plan.signal_end,
            history=history,
            expected_constituent_count=static_plan.expected_constituent_count,
            factor_ratio_rtol=static_plan.factor_ratio_rtol,
        )
    except M3G1CandidateError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_IDENTITY_MISMATCH",
            operation=operation,
            cause_category="MEMBERSHIP",
        ) from None


def _assert_calendar_slice(
    frame: pl.DataFrame,
    *,
    history_start: dt.date,
    history_end: dt.date,
    operation: Operation,
) -> None:
    sh = frame.filter(pl.col("market") == "SH").sort("date")
    sz = frame.filter(pl.col("market") == "SZ").sort("date")
    if sh.height == 0 or sz.height == 0:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    sh_dates = sh.get_column("date").to_list()
    sz_dates = sz.get_column("date").to_list()
    if sh_dates != sz_dates:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if sh.get_column("is_open").to_list() != sz.get_column("is_open").to_list():
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if not sh_dates or sh_dates[0] != history_start or sh_dates[-1] != history_end:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    expected: list[dt.date] = []
    cursor = history_start
    while cursor <= history_end:
        expected.append(cursor)
        cursor += dt.timedelta(days=1)
    if sh_dates != expected:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None


def _recover_tushare_batch(
    *,
    batch: TushareRequestBatch,
    raw_root: Path,
    journal_root: Path,
    policies: Mapping[str, EndpointPolicy],
    operation: Operation,
) -> Literal["missing", "partial", "complete"]:
    del policies  # policies used only when verifying complete set
    _preflight_optional_root(journal_root, operation=operation)
    _preflight_optional_root(raw_root, operation=operation)
    if not _path_exists_nofollow(journal_root):
        return "missing"
    _validate_tushare_journal_root(journal_root, operation=operation)
    present = 0
    for spec in batch.requests:
        request_dir = journal_root / spec.request_id
        receipt_path = request_dir / "receipt.json"
        if _regular_file_exists(receipt_path):
            present += 1
            continue
        if _path_exists_nofollow(request_dir):
            _validate_request_journal_dir(request_dir, operation=operation)
            return "partial"
        # also treat raw-only orphans for this request as partial recovery state
        try:
            state = RawStore(raw_root).inspect_request_state(
                source="tushare", table=spec.endpoint, request_id=spec.request_id
            )
        except (OSError, ValueError):
            raise M3G1WorkflowError(
                "G1_WORKFLOW_JOURNAL_INVALID",
                operation=operation,
                cause_category="JOURNAL",
            ) from None
        if state != "ABSENT":
            return "partial"
    if present == 0:
        return "missing"
    if present == len(batch.requests):
        return "complete"
    return "partial"


def _verify_tushare_complete(
    *,
    batch: TushareRequestBatch,
    raw_root: Path,
    journal_root: Path,
    policies: Mapping[str, EndpointPolicy],
    operation: Operation,
) -> tuple[VerifiedRawResponse, ...]:
    out: list[VerifiedRawResponse] = []
    for spec in batch.requests:
        request_dir = journal_root / spec.request_id
        _validate_request_journal_dir(request_dir, operation=operation)
        receipt_path = request_dir / "receipt.json"
        try:
            verified = verify_tushare_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_root,
                journal_root=journal_root,
                policy=policies[spec.endpoint],
            )
        except M3BackfillError:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_JOURNAL_INVALID",
                operation=operation,
                cause_category="JOURNAL",
            ) from None
        out.append(verified)
    return tuple(out)


def _recover_cninfo_batch(
    *,
    batch: CninfoRequestBatch,
    raw_root: Path,
    journal_root: Path,
    row_limit: int,
    operation: Operation,
) -> Literal["missing", "partial", "complete"]:
    del row_limit
    _preflight_optional_root(journal_root, operation=operation)
    _preflight_optional_root(raw_root, operation=operation)
    if not _path_exists_nofollow(journal_root):
        return "missing"
    _validate_tushare_journal_root(journal_root, operation=operation)
    present = 0
    for spec in batch.requests:
        request_dir = journal_root / spec.request_id
        receipt_path = request_dir / "receipt.json"
        if _regular_file_exists(receipt_path):
            present += 1
            continue
        if _path_exists_nofollow(request_dir):
            _validate_request_journal_dir(request_dir, operation=operation)
            return "partial"
        try:
            state = RawStore(raw_root).inspect_request_state(
                source="cninfo", table="stock_allotment", request_id=spec.request_id
            )
        except (OSError, ValueError):
            raise M3G1WorkflowError(
                "G1_WORKFLOW_JOURNAL_INVALID",
                operation=operation,
                cause_category="JOURNAL",
            ) from None
        if state != "ABSENT":
            return "partial"
    if present == 0:
        return "missing"
    if present == len(batch.requests):
        return "complete"
    return "partial"


def _verify_cninfo_complete(
    *,
    batch: CninfoRequestBatch,
    raw_root: Path,
    journal_root: Path,
    row_limit: int,
    operation: Operation,
) -> tuple[VerifiedCninfoRawResponse, ...]:
    policy = EndpointPolicy(row_limit, "ALLOW")
    out: list[VerifiedCninfoRawResponse] = []
    for spec in batch.requests:
        request_dir = journal_root / spec.request_id
        _validate_request_journal_dir(request_dir, operation=operation)
        receipt_path = request_dir / "receipt.json"
        try:
            verified = verify_cninfo_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_root,
                journal_root=journal_root,
                policy=policy,
            )
        except M3BackfillError:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_JOURNAL_INVALID",
                operation=operation,
                cause_category="JOURNAL",
            ) from None
        out.append(verified)
    return tuple(out)


def _recover_reference_batch(
    *,
    specs: Sequence[Any],
    raw_root: Path,
    journal_root: Path,
    operation: Operation,
) -> Literal["missing", "partial", "complete"]:
    _preflight_optional_root(journal_root, operation=operation)
    _preflight_optional_root(raw_root, operation=operation)
    if not _path_exists_nofollow(journal_root):
        return "missing"
    expected_ids = {spec.request_id for spec in specs}
    _validate_baostock_journal_root(
        journal_root, expected_ids=expected_ids, operation=operation
    )
    present = 0
    for spec in specs:
        request_dir = journal_root / spec.request_id
        receipt_path = request_dir / "receipt.json"
        if _regular_file_exists(receipt_path):
            present += 1
            continue
        if _path_exists_nofollow(request_dir):
            _validate_request_journal_dir(request_dir, operation=operation)
            return "partial"
        try:
            state = RawStore(raw_root).inspect_request_state(
                source="baostock",
                table="query_history_k_data_plus",
                request_id=spec.request_id,
            )
        except (OSError, ValueError):
            raise M3G1WorkflowError(
                "G1_WORKFLOW_JOURNAL_INVALID",
                operation=operation,
                cause_category="JOURNAL",
            ) from None
        if state != "ABSENT":
            return "partial"
    if present == 0:
        return "missing"
    if present == len(specs):
        return "complete"
    return "partial"


def _verify_reference_complete(
    *,
    specs: Sequence[Any],
    raw_root: Path,
    journal_root: Path,
    operation: Operation,
) -> tuple[VerifiedReferenceResponse, ...]:
    out: list[VerifiedReferenceResponse] = []
    for spec in specs:
        request_dir = journal_root / spec.request_id
        _validate_request_journal_dir(request_dir, operation=operation)
        receipt_path = request_dir / "receipt.json"
        try:
            verified = verify_reference_receipt(
                spec=spec,
                receipt_path=receipt_path,
                raw_root=raw_root,
                journal_root=journal_root,
            )
        except M3ReferenceError:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_JOURNAL_INVALID",
                operation=operation,
                cause_category="JOURNAL",
            ) from None
        out.append(verified)
    return tuple(out)


def _validate_tushare_journal_root(journal_root: Path, *, operation: Operation) -> None:
    try:
        for child in journal_root.iterdir():
            mode = os.lstat(child).st_mode
            if child.name == ".writer.lock":
                if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                    raise M3G1WorkflowError(
                        "G1_WORKFLOW_JOURNAL_INVALID",
                        operation=operation,
                        cause_category="JOURNAL",
                    ) from None
                continue
            if stat.S_ISLNK(mode):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
            if not stat.S_ISDIR(mode):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
            if not _HEX64.fullmatch(child.name):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
            _validate_request_journal_dir(child, operation=operation)
    except M3G1WorkflowError:
        raise
    except OSError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_JOURNAL_INVALID",
            operation=operation,
            cause_category="JOURNAL",
        ) from None


def _validate_baostock_journal_root(
    journal_root: Path, *, expected_ids: set[str], operation: Operation
) -> None:
    try:
        for child in journal_root.iterdir():
            mode = os.lstat(child).st_mode
            if child.name == ".writer.lock":
                if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                    raise M3G1WorkflowError(
                        "G1_WORKFLOW_JOURNAL_INVALID",
                        operation=operation,
                        cause_category="JOURNAL",
                    ) from None
                continue
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
            if not _HEX64.fullmatch(child.name):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
            if child.name not in expected_ids:
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
            _validate_request_journal_dir(child, operation=operation)
    except M3G1WorkflowError:
        raise
    except OSError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_JOURNAL_INVALID",
            operation=operation,
            cause_category="JOURNAL",
        ) from None


def _validate_request_journal_dir(directory: Path, *, operation: Operation) -> None:
    allowed = {"intent.json", "candidate.json", "receipt.json"}
    try:
        for path in directory.iterdir():
            mode = os.lstat(path).st_mode
            if path.name not in allowed or not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
    except M3G1WorkflowError:
        raise
    except OSError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_JOURNAL_INVALID",
            operation=operation,
            cause_category="JOURNAL",
        ) from None


def _load_source_context(
    layout: _Layout, *, static_plan: G1StaticPlanV1, operation: Operation
) -> _SourceContext:
    cal_sh_fp = _fingerprint_file(layout.cal_sh, operation=operation)
    cal_sz_fp = _fingerprint_file(layout.cal_sz, operation=operation)
    inst_sh_fp = _fingerprint_file(layout.inst_sh, operation=operation)
    inst_sz_fp = _fingerprint_file(layout.inst_sz, operation=operation)
    try:
        cal_sh = TradeCalendarSchema.validate(pl.read_parquet(layout.cal_sh))
        cal_sz = TradeCalendarSchema.validate(pl.read_parquet(layout.cal_sz))
        inst_sh = InstrumentSchema.validate(pl.read_parquet(layout.inst_sh))
        inst_sz = InstrumentSchema.validate(pl.read_parquet(layout.inst_sz))
    except Exception:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if (
        _fingerprint_file(layout.cal_sh, operation=operation) != cal_sh_fp
        or _fingerprint_file(layout.cal_sz, operation=operation) != cal_sz_fp
        or _fingerprint_file(layout.inst_sh, operation=operation) != inst_sh_fp
        or _fingerprint_file(layout.inst_sz, operation=operation) != inst_sz_fp
    ):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if set(cal_sh.get_column("market").unique().to_list()) != {"SH"}:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if set(cal_sz.get_column("market").unique().to_list()) != {"SZ"}:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    calendars = pl.concat([cal_sh, cal_sz], how="vertical")
    _validate_calendar_pair(calendars, static_plan=static_plan, operation=operation)
    instruments = pl.concat([inst_sh, inst_sz], how="vertical")
    try:
        instruments = InstrumentSchema.validate(instruments)
    except Exception:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    symbols = instruments.get_column("symbol").to_list()
    if len(symbols) != len(set(symbols)):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    for symbol, market in zip(
        instruments.get_column("symbol").to_list(),
        instruments.get_column("market").to_list(),
        strict=True,
    ):
        if type(symbol) is not str or not _A_SHARE.fullmatch(symbol):
            raise M3G1WorkflowError(
                "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
                operation=operation,
                cause_category="SOURCE_SCHEMA",
            ) from None
        if symbol.rsplit(".", 1)[-1] != market:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
                operation=operation,
                cause_category="SOURCE_SCHEMA",
            ) from None
    return _SourceContext(calendars=calendars, instruments=instruments)


def _validate_calendar_pair(
    calendars: pl.DataFrame, *, static_plan: G1StaticPlanV1, operation: Operation
) -> None:
    sh = calendars.filter(pl.col("market") == "SH").sort("date")
    sz = calendars.filter(pl.col("market") == "SZ").sort("date")
    if sh.height == 0 or sz.height == 0:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    sh_dates = sh.get_column("date").to_list()
    sz_dates = sz.get_column("date").to_list()
    if sh_dates != sz_dates:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if sh.get_column("is_open").to_list() != sz.get_column("is_open").to_list():
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if sh_dates != sorted(set(sh_dates)):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    expected: list[dt.date] = []
    cursor = sh_dates[0]
    while cursor <= sh_dates[-1]:
        expected.append(cursor)
        cursor += dt.timedelta(days=1)
    if sh_dates != expected:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    open_dates = tuple(
        day
        for day, is_open in zip(sh_dates, sh.get_column("is_open").to_list(), strict=True)
        if is_open is True
    )
    try:
        start_index = open_dates.index(static_plan.signal_start)
        end_index = open_dates.index(static_plan.signal_end)
    except ValueError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if start_index < static_plan.feature_warmup_sessions:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None
    if end_index + static_plan.label_tail_sessions >= len(open_dates):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None


def _open_layout(project_root: Path, *, operation: Operation) -> _Layout:
    if not isinstance(project_root, Path):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            operation=operation,
            cause_category="PATH",
        ) from None
    try:
        root = Path(os.path.abspath(os.fspath(project_root)))
    except OSError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            operation=operation,
            cause_category="PATH",
        ) from None
    ancestors = _snapshot_ancestors(root, operation=operation)
    root_id = _dir_identity(root, operation=operation)
    layout = _Layout(
        root=root,
        root_id=root_id,
        ancestors=ancestors,
        raw_root=root / _REL_RAW,
        tushare_journal=root / _REL_JOURNAL_TS,
        baostock_journal=root / _REL_JOURNAL_BS,
        cninfo_journal=root / _REL_JOURNAL_CN,
        release_root=root / _REL_RELEASE,
        cal_sh=root / _REL_CAL_SH,
        cal_sz=root / _REL_CAL_SZ,
        inst_sh=root / _REL_INST_SH,
        inst_sz=root / _REL_INST_SZ,
    )
    for path in (
        layout.cal_sh,
        layout.cal_sz,
        layout.inst_sh,
        layout.inst_sz,
    ):
        _reject_path_symlinks(root, path, operation=operation)
    return layout


def _assert_root_unchanged(layout: _Layout, *, operation: Operation) -> None:
    current = _dir_identity(layout.root, operation=operation)
    if current != layout.root_id:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            operation=operation,
            cause_category="PATH",
        ) from None
    for abs_text, expected in layout.ancestors:
        try:
            st = os.lstat(abs_text)
        except OSError:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_PROJECT_ROOT_INVALID",
                operation=operation,
                cause_category="PATH",
            ) from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3G1WorkflowError(
                "G1_WORKFLOW_PROJECT_ROOT_INVALID",
                operation=operation,
                cause_category="PATH",
            ) from None
        if (st.st_dev, st.st_ino) != expected:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_PROJECT_ROOT_INVALID",
                operation=operation,
                cause_category="PATH",
            ) from None


def _snapshot_ancestors(
    path: Path, *, operation: Operation
) -> tuple[tuple[str, tuple[int, int]], ...]:
    current = Path(os.path.abspath(os.fspath(path)))
    snapshots: list[tuple[str, tuple[int, int]]] = []
    while True:
        abs_text = os.path.abspath(os.fspath(current))
        try:
            st = os.lstat(abs_text)
        except OSError:
            raise M3G1WorkflowError(
                "G1_WORKFLOW_PROJECT_ROOT_INVALID",
                operation=operation,
                cause_category="PATH",
            ) from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise M3G1WorkflowError(
                "G1_WORKFLOW_PROJECT_ROOT_INVALID",
                operation=operation,
                cause_category="PATH",
            ) from None
        snapshots.append((abs_text, (st.st_dev, st.st_ino)))
        parent = Path(abs_text).parent
        if parent == Path(abs_text):
            break
        current = parent
    return tuple(snapshots)


def _dir_identity(path: Path, *, operation: Operation) -> tuple[int, int]:
    try:
        st = os.lstat(path)
    except OSError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            operation=operation,
            cause_category="PATH",
        ) from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            operation=operation,
            cause_category="PATH",
        ) from None
    return (st.st_dev, st.st_ino)


def _reject_path_symlinks(root: Path, target: Path, *, operation: Operation) -> None:
    try:
        absolute_root = Path(os.path.abspath(root))
        absolute_target = Path(os.path.abspath(target))
        absolute_target.relative_to(absolute_root)
        chain = [absolute_target, *absolute_target.parents]
        for path in chain:
            if path == absolute_root.parent:
                break
            try:
                mode = os.lstat(path).st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_PROJECT_ROOT_INVALID",
                    operation=operation,
                    cause_category="PATH",
                ) from None
    except M3G1WorkflowError:
        raise
    except (OSError, ValueError):
        raise M3G1WorkflowError(
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            operation=operation,
            cause_category="PATH",
        ) from None


def _preflight_optional_root(root: Path, *, operation: Operation) -> None:
    if not _path_exists_nofollow(root):
        return
    try:
        absolute = Path(os.path.abspath(root))
        for path in reversed((absolute, *absolute.parents)):
            try:
                mode = os.lstat(path).st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(mode):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
            if not stat.S_ISDIR(mode):
                raise M3G1WorkflowError(
                    "G1_WORKFLOW_JOURNAL_INVALID",
                    operation=operation,
                    cause_category="JOURNAL",
                ) from None
    except M3G1WorkflowError:
        raise
    except OSError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_JOURNAL_INVALID",
            operation=operation,
            cause_category="JOURNAL",
        ) from None


def _fingerprint_file(path: Path, *, operation: Operation) -> _FileFingerprint:
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise M3G1WorkflowError(
                "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
                operation=operation,
                cause_category="SOURCE_SCHEMA",
            ) from None
        payload = Path(path).read_bytes()
        return _FileFingerprint(
            sha256=hashlib.sha256(payload).hexdigest(),
            st_dev=st.st_dev,
            st_ino=st.st_ino,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
        )
    except M3G1WorkflowError:
        raise
    except OSError:
        raise M3G1WorkflowError(
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            operation=operation,
            cause_category="SOURCE_SCHEMA",
        ) from None


def _regular_file_exists(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _path_exists_nofollow(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def _checked_classify(
    classify_error: Callable[[BaseException], str],
) -> Callable[[BaseException], str]:
    def wrapped(error: BaseException) -> str:
        try:
            value = classify_error(error)
        except BaseException:
            return "PERMANENT"
        if value not in _CLASSIFY_ALLOWED:
            return "PERMANENT"
        return value

    return wrapped


def _map_planning_error(
    exc: M3G1PlanningError, *, operation: Operation
) -> M3G1WorkflowError:
    mapping: dict[str, tuple[str, CauseCategory]] = {
        "G1_PLANNING_INPUT_INVALID": ("G1_WORKFLOW_INPUT_INVALID", "INPUT"),
        "G1_PLANNING_PROJECT_ROOT_INVALID": (
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            "PATH",
        ),
        "G1_PLANNING_SOURCE_TREE_INVALID": (
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            "PATH",
        ),
        "G1_PLANNING_DEPENDENCY_INVALID": ("G1_WORKFLOW_INPUT_INVALID", "INPUT"),
        "G1_PLANNING_CONFIG_INVALID": ("G1_WORKFLOW_INPUT_INVALID", "INPUT"),
        "G1_PLANNING_CALENDAR_INVALID": (
            "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
            "SOURCE_SCHEMA",
        ),
        "G1_PLANNING_MEMBERSHIP_INVALID": (
            "G1_WORKFLOW_IDENTITY_MISMATCH",
            "MEMBERSHIP",
        ),
        "G1_PLANNING_IDENTITY_MISMATCH": (
            "G1_WORKFLOW_IDENTITY_MISMATCH",
            "MEMBERSHIP",
        ),
    }
    code, category = mapping.get(exc.code, ("G1_WORKFLOW_INPUT_INVALID", "INPUT"))
    return M3G1WorkflowError(code, operation=operation, cause_category=category)


def _map_reference_error(exc: M3ReferenceError) -> tuple[str, CauseCategory]:
    if exc.code in {
        "G1_REFERENCE_NETWORK_FAILED",
        "G1_REFERENCE_IO_FAILED",
    }:
        return "G1_WORKFLOW_EXECUTION_FAILED", "REFERENCE"
    if exc.code in {
        "G1_CROSS_SOURCE_RECONCILIATION_INVALID",
        "G1_REFERENCE_PLAN_INVALID",
    }:
        return "G1_WORKFLOW_QUALITY_FAILED", "REFERENCE"
    if "JOURNAL" in exc.code or "RECEIPT" in exc.code:
        return "G1_WORKFLOW_JOURNAL_INVALID", "JOURNAL"
    return "G1_WORKFLOW_EXECUTION_FAILED", "REFERENCE"


def _map_release_error(exc: M3ReleaseError, *, operation: Operation) -> M3G1WorkflowError:
    if exc.code == "G1_RELEASE_QUALITY_FAILED":
        return M3G1WorkflowError(
            "G1_WORKFLOW_QUALITY_FAILED",
            operation=operation,
            cause_category="RELEASE",
        )
    if exc.code == "G1_RELEASE_PUBLISH_UNSUPPORTED":
        return M3G1WorkflowError(
            "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
            operation=operation,
            cause_category="UNSUPPORTED",
        )
    if "PATH" in exc.code:
        return M3G1WorkflowError(
            "G1_WORKFLOW_PROJECT_ROOT_INVALID",
            operation=operation,
            cause_category="PATH",
        )
    return M3G1WorkflowError(
        "G1_WORKFLOW_PUBLISH_FAILED",
        operation=operation,
        cause_category="RELEASE",
    )


def _assert_prepared_matches_verified(
    prepared: G1PreparedRelease, verified: VerifiedG1Release
) -> None:
    if verified.manifest.release_id != prepared.release_id:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if verified.manifest.primary_candidate_key != prepared.candidate.primary_candidate_key:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if (
        verified.manifest.sample_plan_sha256
        != prepared.reconciliation.sample_plan.sample_plan_sha256
    ):
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if verified.quality != prepared.quality:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
    if verified.manifest.cross_source_summary_sha256 != prepared.reconciliation.summary_sha256:
        raise M3ReleaseError("G1_RELEASE_VERIFY_FAILED")
