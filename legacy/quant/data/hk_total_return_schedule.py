"""Fresh-verified, source-neutral HK total-return application schedule.

This module assigns implemented actions to retained daily bars.  It deliberately
does not calculate prices, infer trading availability, or persist any artifact.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never, SupportsIndex

import pandera.errors
import polars as pl

from quant.data.hk_corporate_action_implementation import (
    VerifiedHkCorporateActionImplementationProjection,
    VerifiedImplementedHkCorporateActionSet,
    verify_implemented_hk_corporate_action_set,
)
from quant.data.hk_corporate_actions import (
    HkCorporateActionSelectionResult,
    VerifiedHkCorporateActionProjection,
)
from quant.data.hk_history_backfill import (
    HKHistoryPlan,
    VerifiedHkBarBundle,
    verify_hk_bar_bundle,
)
from quant.data.storage import RawStore
from quant.domain import HkTotalReturnApplicationScheduleSchema

HK_GROSS_TOTAL_RETURN_SCHEDULE_V1 = "HK_GROSS_TOTAL_RETURN_SCHEDULE_V1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$", flags=re.ASCII)
_ERROR_CODES = frozenset(
    {
        "HK_TOTAL_RETURN_INPUT_INVALID",
        "HK_TOTAL_RETURN_ACTION_UNSUPPORTED",
        "HK_TOTAL_RETURN_SCHEDULE_INVALID",
        "HK_TOTAL_RETURN_VERIFY_FAILED",
    }
)
_ATTESTATION_KEY = secrets.token_bytes(32)
_SCHEDULE_SCHEMA: dict[
    str, type[str] | type[dt.date] | type[float] | pl.Datetime
] = {
    "event_id": str,
    "symbol": str,
    "action_type": str,
    "source": str,
    "source_event_id": str,
    "source_revision_id": str,
    "ex_date": dt.date,
    "pay_date": dt.date,
    "stock_list_date": dt.date,
    "declared_currency": str,
    "implementation_effective_date": dt.date,
    "implementation_confirmed_at": pl.Datetime("us", "UTC"),
    "source_observed_at": pl.Datetime("us", "UTC"),
    "window_disposition": str,
    "application_trade_date": dt.date,
    "application_bar_available_at": pl.Datetime("us", "UTC"),
    "application_availability_evidence_sha256": str,
    "cash_per_share_gross_hkd": float,
    "stock_ratio": float,
    "share_multiplier": float,
    "policy_version": str,
    "p0_query_sha256": str,
    "p0_actions_content_sha256": str,
    "p0_evidence_content_sha256": str,
    "implementation_evidence_content_sha256": str,
    "implementation_projection_sha256": str,
    "bar_plan_sha256": str,
    "bar_publication_sha256": str,
    "bars_content_sha256": str,
    "bar_availability_content_sha256": str,
    "row_identity_sha256": str,
}


class HkTotalReturnScheduleError(ValueError):
    """Stable, redacted public error for schedule construction and verification."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown HK total-return schedule error")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"HkTotalReturnScheduleError({self.code!r})"


def _fail(code: str) -> HkTotalReturnScheduleError:
    return HkTotalReturnScheduleError(code)


@dataclass(frozen=True, slots=True)
class HkTotalReturnFreshContext:
    """Non-serializable arguments needed by both public upstream verifiers."""

    implemented: VerifiedImplementedHkCorporateActionSet
    implementation_projection: VerifiedHkCorporateActionImplementationProjection
    p0_result: HkCorporateActionSelectionResult
    p0_projection: VerifiedHkCorporateActionProjection
    bar_bundle: VerifiedHkBarBundle
    history_plan: HKHistoryPlan
    journal_root: Path
    seed_raw_root: Path
    raw_store: RawStore
    clean_root: Path
    as_of: dt.datetime

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("HK total-return fresh context is process-local")


class VerifiedHkTotalReturnApplicationPlan:
    """Process-local immutable schedule capability, never a research-price result."""

    __slots__ = (
        "_schedule",
        "schedule_content_sha256",
        "plan_identity_sha256",
        "policy_version",
        "as_of",
        "_attestation",
    )

    _schedule: pl.DataFrame
    schedule_content_sha256: str
    plan_identity_sha256: str
    policy_version: str
    as_of: dt.datetime
    _attestation: bytes

    def __new__(
        cls, *_args: object, **_kwargs: object
    ) -> VerifiedHkTotalReturnApplicationPlan:
        del cls
        raise HkTotalReturnScheduleError("HK_TOTAL_RETURN_SCHEDULE_INVALID") from None

    def __init_subclass__(cls, **_kwargs: object) -> None:
        del cls
        raise TypeError("VerifiedHkTotalReturnApplicationPlan is final")

    def __setattr__(self, _name: str, _value: object) -> Never:
        raise HkTotalReturnScheduleError("HK_TOTAL_RETURN_SCHEDULE_INVALID") from None

    @property
    def schedule(self) -> pl.DataFrame:
        return self._schedule.clone()

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("verified HK total-return application plan is process-local")


def build_hk_total_return_application_plan(
    *, context: HkTotalReturnFreshContext
) -> VerifiedHkTotalReturnApplicationPlan:
    """Fresh-verify both upstream capabilities and build the canonical schedule."""
    result: VerifiedHkTotalReturnApplicationPlan | None = None
    error_code: str | None = None
    try:
        _fresh_verify(context, failure_code="HK_TOTAL_RETURN_INPUT_INVALID")
        schedule = _build_schedule(context)
        result = _issue_plan(schedule, context.as_of)
    except HkTotalReturnScheduleError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_TOTAL_RETURN_SCHEDULE_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if result is None:
        raise _fail("HK_TOTAL_RETURN_SCHEDULE_INVALID") from None
    return result


def verify_hk_total_return_application_plan(
    plan: VerifiedHkTotalReturnApplicationPlan,
    *,
    context: HkTotalReturnFreshContext,
) -> None:
    """Fresh-rebuild the complete schedule and compare all public and sealed state."""
    error_code: str | None = None
    try:
        if type(plan) is not VerifiedHkTotalReturnApplicationPlan:
            raise _fail("HK_TOTAL_RETURN_VERIFY_FAILED")
        _fresh_verify(context, failure_code="HK_TOTAL_RETURN_VERIFY_FAILED")
        expected = _issue_plan(_build_schedule(context), context.as_of)
        if (
            plan.policy_version != expected.policy_version
            or plan.as_of != expected.as_of
            or plan.schedule_content_sha256 != expected.schedule_content_sha256
            or plan.plan_identity_sha256 != expected.plan_identity_sha256
            or not plan._schedule.equals(expected._schedule)
            or not hmac.compare_digest(plan._attestation, _attestation(plan))
            or not hmac.compare_digest(plan._attestation, expected._attestation)
        ):
            raise _fail("HK_TOTAL_RETURN_VERIFY_FAILED")
    except HkTotalReturnScheduleError:
        error_code = "HK_TOTAL_RETURN_VERIFY_FAILED"
    except Exception:
        error_code = "HK_TOTAL_RETURN_VERIFY_FAILED"
    if error_code is not None:
        raise _fail(error_code) from None


def _fresh_verify(context: object, *, failure_code: str) -> None:
    try:
        if type(context) is not HkTotalReturnFreshContext or not _utc(context.as_of):
            raise ValueError
        if (
            context.implementation_projection.query.as_of != context.as_of
            or context.p0_projection.query.as_of != context.as_of
            or context.bar_bundle.plan_sha256 != context.history_plan.plan_sha256
        ):
            raise ValueError
        verify_implemented_hk_corporate_action_set(
            implemented=context.implemented,
            projection=context.implementation_projection,
            p0_result=context.p0_result,
            p0_projection=context.p0_projection,
        )
        verify_hk_bar_bundle(
            context.bar_bundle,
            plan=context.history_plan,
            journal_root=context.journal_root,
            seed_raw_root=context.seed_raw_root,
            raw_store=context.raw_store,
            clean_root=context.clean_root,
            as_of=context.as_of,
        )
    except Exception:
        raise _fail(failure_code) from None


def _build_schedule(context: HkTotalReturnFreshContext) -> pl.DataFrame:
    actions = context.implemented.actions
    evidence = context.implemented.implementation_evidence
    bars = context.bar_bundle.bars
    availability = context.bar_bundle.availability
    if not actions.height or actions.height != evidence.height or not bars.height:
        raise _fail("HK_TOTAL_RETURN_INPUT_INVALID")
    action_symbols = set(actions.get_column("symbol").to_list())
    bar_symbols = set(bars.get_column("symbol").to_list())
    if action_symbols != bar_symbols:
        raise _fail("HK_TOTAL_RETURN_INPUT_INVALID")
    bar_keys = set(bars.select("symbol", "trade_date").iter_rows())
    availability_keys = set(availability.select("symbol", "trade_date").iter_rows())
    if bar_keys != availability_keys or bars.height != availability.height:
        raise _fail("HK_TOTAL_RETURN_INPUT_INVALID")
    if availability.filter(pl.col("bar_available_at") > context.as_of).height:
        raise _fail("HK_TOTAL_RETURN_INPUT_INVALID")

    action_by_id = {row["event_id"]: row for row in actions.iter_rows(named=True)}
    evidence_by_id = {
        row["event_id"]: row for row in evidence.iter_rows(named=True)
    }
    if set(action_by_id) != set(evidence_by_id) or len(action_by_id) != actions.height:
        raise _fail("HK_TOTAL_RETURN_INPUT_INVALID")

    bars_content = _frame_hash("hk_total_return_bars", bars.sort(["symbol", "trade_date"]))
    availability_content = _frame_hash(
        "hk_total_return_bar_availability",
        availability.sort(["symbol", "trade_date"]),
    )
    bars_by_symbol = {
        symbol: frame.sort("trade_date")
        for symbol, frame in bars.partition_by("symbol", as_dict=True).items()
    }
    availability_by_key = {
        (row["symbol"], row["trade_date"]): row
        for row in availability.iter_rows(named=True)
    }

    rows: list[dict[str, Any]] = []
    ordered_actions = sorted(
        action_by_id.values(),
        key=lambda row: (row["symbol"], row["ex_date"], row["event_id"]),
    )
    for action in ordered_actions:
        implementation = evidence_by_id[action["event_id"]]
        _validate_pair(action, implementation, context.as_of)
        symbol_bars = bars_by_symbol.get((action["symbol"],))
        if symbol_bars is None:
            raise _fail("HK_TOTAL_RETURN_INPUT_INVALID")
        dates = symbol_bars.get_column("trade_date").to_list()
        first_date, last_date = dates[0], dates[-1]
        ex_date = action["ex_date"]
        if ex_date <= first_date:
            disposition = "BASELINE_PREWINDOW"
            application_date = None
        elif ex_date <= last_date:
            disposition = "APPLY_IN_WINDOW"
            application_date = next((value for value in dates if value >= ex_date), None)
            if application_date is None:
                raise _fail("HK_TOTAL_RETURN_SCHEDULE_INVALID")
        else:
            disposition = "OUTSIDE_FUTURE_WINDOW"
            application_date = None

        action_type = action["action_type"]
        currency = action["declared_currency"]
        if disposition == "APPLY_IN_WINDOW" and (
            action_type == "RIGHTS" or (action_type == "DIVIDEND" and currency != "HKD")
        ):
            raise _fail("HK_TOTAL_RETURN_ACTION_UNSUPPORTED")
        if action_type not in {"DIVIDEND", "BONUS", "SPLIT", "RIGHTS"}:
            raise _fail("HK_TOTAL_RETURN_ACTION_UNSUPPORTED")

        application_evidence = (
            availability_by_key[(action["symbol"], application_date)]
            if application_date is not None
            else None
        )
        row: dict[str, Any] = {
            "event_id": action["event_id"],
            "symbol": action["symbol"],
            "action_type": action_type,
            "source": action["source"],
            "source_event_id": action["source_event_id"],
            "source_revision_id": action["source_revision_id"],
            "ex_date": ex_date,
            "pay_date": action["pay_date"],
            "stock_list_date": action["stock_list_date"],
            "declared_currency": currency,
            "implementation_effective_date": implementation[
                "implementation_effective_date"
            ],
            "implementation_confirmed_at": implementation[
                "implementation_confirmed_at"
            ],
            "source_observed_at": implementation["source_observed_at"],
            "window_disposition": disposition,
            "application_trade_date": application_date,
            "application_bar_available_at": (
                application_evidence["bar_available_at"]
                if application_evidence is not None
                else None
            ),
            "application_availability_evidence_sha256": (
                application_evidence["availability_evidence_sha256"]
                if application_evidence is not None
                else None
            ),
            "cash_per_share_gross_hkd": (
                action["cash_per_share_gross"]
                if action_type == "DIVIDEND" and currency == "HKD"
                else None
            ),
            "stock_ratio": action["stock_ratio"] if action_type == "BONUS" else None,
            "share_multiplier": (
                1.0 + action["stock_ratio"]
                if action_type == "BONUS"
                else action["share_multiplier"] if action_type == "SPLIT" else None
            ),
            "policy_version": HK_GROSS_TOTAL_RETURN_SCHEDULE_V1,
            "p0_query_sha256": context.implemented.p0_query_sha256,
            "p0_actions_content_sha256": context.implemented.p0_actions_content_sha256,
            "p0_evidence_content_sha256": context.implemented.p0_evidence_content_sha256,
            "implementation_evidence_content_sha256": context.implemented.implementation_evidence_content_sha256,
            "implementation_projection_sha256": context.implemented.projection_sha256,
            "bar_plan_sha256": context.bar_bundle.plan_sha256,
            "bar_publication_sha256": context.bar_bundle.publication_sha256,
            "bars_content_sha256": bars_content,
            "bar_availability_content_sha256": availability_content,
        }
        row["row_identity_sha256"] = _payload_hash(
            {"algorithm": "hk-total-return-schedule-row-v1", "row": row}
        )
        rows.append(row)

    frame = pl.DataFrame(rows, schema=_SCHEDULE_SCHEMA, orient="row")
    try:
        validated = HkTotalReturnApplicationScheduleSchema.validate(frame)
    except (pandera.errors.SchemaError, pandera.errors.SchemaErrors, pl.exceptions.PolarsError):
        raise _fail("HK_TOTAL_RETURN_SCHEDULE_INVALID") from None
    return validated


def _validate_pair(
    action: dict[str, Any], implementation: dict[str, Any], as_of: dt.datetime
) -> None:
    if any(
        action[name] != implementation[name]
        for name in (
            "event_id",
            "symbol",
            "action_type",
            "source",
            "source_event_id",
            "source_revision_id",
        )
    ) or (
        implementation["implementation_status"] != "IMPLEMENTED"
        or implementation["implementation_confirmed_at"] > as_of
    ):
        raise _fail("HK_TOTAL_RETURN_INPUT_INVALID")


def _issue_plan(
    schedule: pl.DataFrame, as_of: dt.datetime
) -> VerifiedHkTotalReturnApplicationPlan:
    content = _payload_hash(
        {
            "algorithm": "hk-total-return-ordered-schedule-v1",
            "columns": schedule.columns,
            "rows": list(schedule.iter_rows(named=True)),
        }
    )
    identity = _payload_hash(
        {
            "algorithm": "hk-total-return-application-plan-v1",
            "as_of": as_of,
            "policy_version": HK_GROSS_TOTAL_RETURN_SCHEDULE_V1,
            "schedule_content_sha256": content,
        }
    )
    result = object.__new__(VerifiedHkTotalReturnApplicationPlan)
    object.__setattr__(result, "_schedule", schedule.clone())
    object.__setattr__(result, "schedule_content_sha256", content)
    object.__setattr__(result, "plan_identity_sha256", identity)
    object.__setattr__(result, "policy_version", HK_GROSS_TOTAL_RETURN_SCHEDULE_V1)
    object.__setattr__(result, "as_of", as_of)
    object.__setattr__(result, "_attestation", b"")
    object.__setattr__(result, "_attestation", _attestation(result))
    return result


def _attestation(plan: VerifiedHkTotalReturnApplicationPlan) -> bytes:
    payload = _payload_hash(
        {
            "algorithm": "hk-total-return-plan-attestation-v1",
            "as_of": plan.as_of,
            "plan_identity_sha256": plan.plan_identity_sha256,
            "policy_version": plan.policy_version,
            "schedule_content_sha256": plan.schedule_content_sha256,
            "schedule": list(plan._schedule.iter_rows(named=True)),
        }
    ).encode("ascii")
    return hmac.digest(_ATTESTATION_KEY, payload, "sha256")


def _frame_hash(name: str, frame: pl.DataFrame) -> str:
    return _payload_hash(
        {
            "algorithm": "hk-total-return-input-frame-v1",
            "name": name,
            "columns": [
                {"name": column, "dtype": str(dtype)}
                for column, dtype in zip(frame.columns, frame.dtypes, strict=True)
            ],
            "rows": list(frame.iter_rows(named=True)),
        }
    )


def _payload_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            _json_value(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise _fail("HK_TOTAL_RETURN_SCHEDULE_INVALID") from None
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: object) -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError
        return {"float64": format(0.0 if value == 0.0 else value, ".17g")}
    if type(value) is dt.datetime:
        if not _utc(value):
            raise ValueError
        return {"datetime_utc": value.isoformat(timespec="microseconds")}
    if type(value) is dt.date:
        return {"date": value.isoformat()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError


def _utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and value.tzinfo is not None
        and value.utcoffset() == dt.timedelta(0)
    )


__all__ = [
    "HK_GROSS_TOTAL_RETURN_SCHEDULE_V1",
    "HkTotalReturnFreshContext",
    "HkTotalReturnScheduleError",
    "VerifiedHkTotalReturnApplicationPlan",
    "build_hk_total_return_application_plan",
    "verify_hk_total_return_application_plan",
]
