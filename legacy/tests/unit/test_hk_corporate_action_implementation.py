"""Source-neutral HK corporate-action implementation capability tests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pickle
import traceback
from copy import copy
from dataclasses import replace
from typing import Any

import polars as pl
import pytest

import quant.data.hk_corporate_action_implementation as impl
import quant.data.hk_corporate_actions as ca
from quant.domain import CorporateActionType, Currency

UTC = dt.UTC
SOURCE = "FIXTURE_OFFICIAL"
AS_OF = dt.datetime(2026, 5, 10, tzinfo=UTC)
OBSERVED = dt.datetime(2026, 8, 1, 12, tzinfo=UTC)


def _p0_candidate(
    *, event: str, revision: str, symbol: str, action: str, **economics: object
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "economic_event_key_sha256": "0" * 64,
        "candidate_id": "0" * 64,
        "symbol": symbol,
        "action_type": action,
        "source": SOURCE,
        "source_event_id": event,
        "source_revision_id": revision,
        "revision_sequence": 1,
        "predecessor_candidate_id": None,
        "revision_status": "ACTIVE",
        "published_at": dt.datetime(2026, 5, 4, tzinfo=UTC),
        "source_observed_at": OBSERVED,
        "record_date": dt.date(2026, 5, 7),
        "ex_date": dt.date(2026, 5, 8),
        "pay_date": None,
        "stock_list_date": None,
        "declared_currency": None,
        "cash_per_share_gross": None,
        "stock_ratio": None,
        "share_multiplier": None,
        "rights_ratio": None,
        "rights_subscription_price": None,
        "rights_subscription_start": None,
        "rights_subscription_end": None,
        "raw_bundle_sha256": "0" * 64,
        "raw_file_sha256": "0" * 64,
        "raw_metadata_sha256": "0" * 64,
        "raw_selector": f"records/{event}",
    }
    row.update(economics)
    return row


class _P0Adapter:
    source = SOURCE

    def __init__(self) -> None:
        self.capability = ca.HkCorporateActionCapability(
            source=SOURCE,
            adapter_version="p0-fixture-v1",
            supported_action_types=tuple(
                sorted(CorporateActionType, key=lambda item: item.value)
            ),
            supported_currencies=tuple(sorted(Currency, key=lambda item: item.value)),
            retained_bytes_verifiable=True,
            official_published_at_available=True,
            stable_event_identity_available=True,
            stable_revision_identity_available=True,
            revision_predecessor_available=True,
            withdrawal_history_complete=True,
            correction_supplement_closure_complete=True,
            scope_completeness_verifiable=True,
        )

    def verify_retained(
        self, *, query: ca.HkCorporateActionQuery, bundle: ca.HkCorporateActionRawBundle
    ) -> ca.VerifiedHkCorporateActionProjection:
        raw = bundle.files[0]
        if raw.content != b'{"complete":true}' or raw.metadata != b'{"issue":"p0"}':
            raise ca.HkCorporateActionError("HK_CA_EVIDENCE_INVALID")
        rows = [
            _p0_candidate(
                event="bonus",
                revision="bonus-r1",
                symbol="00005.HK",
                action="BONUS",
                stock_list_date=dt.date(2026, 5, 12),
                stock_ratio=0.1,
            ),
            _p0_candidate(
                event="dividend",
                revision="dividend-r1",
                symbol="00700.HK",
                action="DIVIDEND",
                pay_date=dt.date(2026, 5, 20),
                declared_currency="HKD",
                cash_per_share_gross=0.5,
            ),
        ]
        for row in rows:
            row["raw_bundle_sha256"] = bundle.bundle_sha256
            row["raw_file_sha256"] = raw.content_sha256
            row["raw_metadata_sha256"] = raw.metadata_sha256
            row["economic_event_key_sha256"] = ca._event_key(row)
            row["candidate_id"] = ca._candidate_id(row)
        frame = ca._candidate_frame(rows).sort(
            ["source", "source_event_id", "revision_sequence"]
        )
        return ca.build_verified_hk_corporate_action_projection(
            capability=self.capability,
            query=query,
            bundle=bundle,
            candidates=frame,
        )


def _p0() -> tuple[ca.HkCorporateActionSelectionResult, ca.VerifiedHkCorporateActionProjection]:
    query = ca.HkCorporateActionQuery(
        symbols=("00005.HK", "00700.HK"),
        event_date_start=dt.date(2026, 5, 1),
        event_date_end=dt.date(2026, 5, 31),
        as_of=AS_OF,
        required_action_types=(CorporateActionType.BONUS, CorporateActionType.DIVIDEND),
        accepted_currencies=(Currency.HKD,),
    )
    raw = ca.HkCorporateActionRawFile.create(
        role="MAIN", content=b'{"complete":true}', metadata=b'{"issue":"p0"}'
    )
    bundle = ca.HkCorporateActionRawBundle.create(
        query=query,
        source=SOURCE,
        source_issue_id="p0-issue",
        files=(raw,),
        source_observed_at=OBSERVED,
        coverage_as_of=AS_OF,
    )
    projection = ca.verify_hk_corporate_action_source(
        adapter=_P0Adapter(), query=query, bundle=bundle
    )
    return ca.select_hk_corporate_actions(projection=projection), projection


def _query(
    p0_result: ca.HkCorporateActionSelectionResult,
) -> impl.HkCorporateActionImplementationQuery:
    return impl.HkCorporateActionImplementationQuery(
        p0_query_sha256=p0_result.query_identity_sha256,
        p0_actions_content_sha256=p0_result.actions_sha256,
        p0_evidence_content_sha256=p0_result.revision_evidence_sha256,
        event_ids=tuple(sorted(p0_result.actions.get_column("event_id").to_list())),
        as_of=AS_OF,
    )


def _capability(**overrides: object) -> impl.HkCorporateActionImplementationCapability:
    values: dict[str, object] = {
        "source": SOURCE,
        "adapter_version": "implementation-fixture-v1",
        "retained_bytes_verifiable": True,
        "exact_scope_complete": True,
        "implementation_status_available": True,
        "stable_revision_identity_available": True,
        "correction_history_complete": True,
        "withdrawal_history_complete": True,
        "official_confirmed_at_available": True,
        "source_observed_at_available": True,
    }
    values.update(overrides)
    return impl.HkCorporateActionImplementationCapability(**values)  # type: ignore[arg-type]


class _ImplementationAdapter:
    source = SOURCE

    def __init__(
        self,
        *,
        p0_result: ca.HkCorporateActionSelectionResult,
        capability: impl.HkCorporateActionImplementationCapability | None = None,
    ) -> None:
        self.p0_result = p0_result
        self.capability = capability or _capability()
        self.calls = 0

    def verify_retained(
        self,
        *,
        query: impl.HkCorporateActionImplementationQuery,
        bundle: impl.HkCorporateActionImplementationRawBundle,
    ) -> impl.VerifiedHkCorporateActionImplementationProjection:
        self.calls += 1
        raw = bundle.files[0]
        if raw.metadata != b'{"issue":"impl","retained":true}':
            raise impl.HkCorporateActionImplementationError(
                "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"
            )
        try:
            def strict_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, value in values:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result

            payload = json.loads(raw.content, object_pairs_hook=strict_pairs)
            if (
                type(payload) is not dict
                or set(payload)
                != {
                    "schema_version",
                    "scope_complete",
                    "correction_history_complete",
                    "withdrawal_history_complete",
                    "records",
                    "withdrawals",
                }
                or payload["schema_version"] != "fixture-hk-ca-implementation-v1"
                or payload["scope_complete"] is not True
                or payload["correction_history_complete"] is not True
                or payload["withdrawal_history_complete"] is not True
                or type(payload["records"]) is not list
                or type(payload["withdrawals"]) is not list
            ):
                raise ValueError
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise impl.HkCorporateActionImplementationError(
                "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"
            ) from None

        record_keys = {
            "event_id",
            "symbol",
            "action_type",
            "source",
            "source_event_id",
            "source_revision_id",
            "implementation_status",
            "implementation_effective_date",
            "implementation_confirmed_at",
            "source_observed_at",
            "source_record_id",
        }
        withdrawal_keys = {
            "event_id",
            "source",
            "source_event_id",
            "source_revision_id",
            "withdrawal_confirmed_at",
            "source_record_id",
        }
        actions = {
            row["event_id"]: row
            for row in self.p0_result.actions.iter_rows(named=True)
        }
        rows: list[dict[str, Any]] = []
        seen_records: set[str] = set()
        try:
            parsed_withdrawals: list[
                tuple[tuple[str, str, str, str, str], dt.datetime]
            ] = []
            withdrawal_record_keys: set[tuple[str, str]] = set()
            withdrawal_business_keys: set[tuple[str, str, str]] = set()
            for withdrawal in payload["withdrawals"]:
                if type(withdrawal) is not dict or set(withdrawal) != withdrawal_keys:
                    raise ValueError
                for name in withdrawal_keys:
                    value = withdrawal[name]
                    if (
                        type(value) is not str
                        or not value
                        or value != value.strip()
                    ):
                        raise ValueError
                event_id = withdrawal["event_id"]
                action = actions.get(event_id)
                confirmed = dt.datetime.fromisoformat(
                    withdrawal["withdrawal_confirmed_at"].replace("Z", "+00:00")
                )
                if (
                    confirmed.tzinfo is None
                    or confirmed.utcoffset() != dt.timedelta(0)
                    or confirmed > bundle.source_observed_at
                ):
                    raise ValueError
                if action is None or any(
                    withdrawal[name] != action[name]
                    for name in (
                        "source",
                        "source_event_id",
                        "source_revision_id",
                    )
                ):
                    raise impl.HkCorporateActionImplementationError(
                        "HK_CA_IMPLEMENTATION_SCOPE_INVALID"
                    )
                record_key = (withdrawal["source"], withdrawal["source_record_id"])
                business_key = (
                    withdrawal["source"],
                    withdrawal["source_event_id"],
                    withdrawal["source_revision_id"],
                )
                if (
                    record_key in withdrawal_record_keys
                    or business_key in withdrawal_business_keys
                ):
                    raise ValueError
                withdrawal_record_keys.add(record_key)
                withdrawal_business_keys.add(business_key)
                canonical_key = (
                    withdrawal["source"],
                    withdrawal["source_event_id"],
                    withdrawal["source_revision_id"],
                    withdrawal["withdrawal_confirmed_at"],
                    withdrawal["source_record_id"],
                )
                parsed_withdrawals.append((canonical_key, confirmed))

            if parsed_withdrawals != sorted(parsed_withdrawals):
                raise ValueError
            if any(confirmed <= query.as_of for _, confirmed in parsed_withdrawals):
                raise ValueError

            for index, record in enumerate(payload["records"]):
                if type(record) is not dict or set(record) != record_keys:
                    raise ValueError
                event_id = record["event_id"]
                action = actions.get(event_id)
                if (
                    type(event_id) is not str
                    or event_id in seen_records
                    or record["implementation_status"] != "IMPLEMENTED"
                    or type(record["source_record_id"]) is not str
                    or not record["source_record_id"]
                ):
                    raise ValueError
                if action is None or any(
                    record[name] != action[name]
                    for name in (
                        "symbol",
                        "action_type",
                        "source",
                        "source_event_id",
                        "source_revision_id",
                    )
                ):
                    raise impl.HkCorporateActionImplementationError(
                        "HK_CA_IMPLEMENTATION_SCOPE_INVALID"
                    )
                seen_records.add(event_id)
                effective = dt.date.fromisoformat(
                    str(record["implementation_effective_date"])
                )
                confirmed = dt.datetime.fromisoformat(
                    str(record["implementation_confirmed_at"]).replace("Z", "+00:00")
                )
                observed = dt.datetime.fromisoformat(
                    str(record["source_observed_at"]).replace("Z", "+00:00")
                )
                if (
                    confirmed.tzinfo is None
                    or confirmed.utcoffset() != dt.timedelta(0)
                    or observed.tzinfo is None
                    or observed.utcoffset() != dt.timedelta(0)
                ):
                    raise ValueError
                row = {
                    **record,
                    "implementation_effective_date": effective,
                    "implementation_confirmed_at": confirmed,
                    "source_observed_at": observed,
                    "raw_selector": f"records/{index}",
                    "raw_file_sha256": raw.content_sha256,
                    "raw_metadata_sha256": raw.metadata_sha256,
                    "raw_bundle_sha256": bundle.bundle_sha256,
                    "p0_actions_content_sha256": query.p0_actions_content_sha256,
                    "p0_evidence_content_sha256": query.p0_evidence_content_sha256,
                    "p0_query_sha256": query.p0_query_sha256,
                    "implementation_evidence_sha256": "0" * 64,
                }
                row["implementation_evidence_sha256"] = (
                    impl._implementation_evidence_sha256(row)
                )
                rows.append(row)
            if seen_records != set(actions):
                raise impl.HkCorporateActionImplementationError(
                    "HK_CA_IMPLEMENTATION_SCOPE_INVALID"
                )
        except impl.HkCorporateActionImplementationError:
            raise
        except (KeyError, TypeError, ValueError):
            raise impl.HkCorporateActionImplementationError(
                "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"
            ) from None
        frame = pl.DataFrame(rows, schema=impl._evidence_schema(), orient="row").sort(
            "event_id"
        )
        return impl.build_hk_corporate_action_implementation_projection(
            capability=self.capability, query=query, bundle=bundle, evidence=frame
        )


def _implementation_payload(
    p0_result: ca.HkCorporateActionSelectionResult,
    *,
    record_overrides: dict[str, object] | None = None,
    first_record_overrides: dict[str, object] | None = None,
    remove_first_record_field: str | None = None,
    drop_last: bool = False,
    only_scope: bool = False,
    withdrawals: list[dict[str, object]] | None = None,
    top_level_overrides: dict[str, object] | None = None,
) -> bytes:
    records: list[dict[str, object]] = []
    for index, action in enumerate(p0_result.actions.sort("event_id").iter_rows(named=True)):
        record: dict[str, object] = {
            "event_id": action["event_id"],
            "symbol": action["symbol"],
            "action_type": action["action_type"],
            "source": action["source"],
            "source_event_id": action["source_event_id"],
            "source_revision_id": action["source_revision_id"],
            "implementation_status": "IMPLEMENTED",
            "implementation_effective_date": f"2026-05-{8 + index:02d}",
            "implementation_confirmed_at": f"2026-05-09T0{index}:00:00Z",
            "source_observed_at": "2026-08-01T12:00:00Z",
            "source_record_id": f"implementation/{index}",
        }
        record.update(record_overrides or {})
        if index == 0:
            record.update(first_record_overrides or {})
            if remove_first_record_field is not None:
                record.pop(remove_first_record_field, None)
        records.append(record)
    if drop_last:
        records.pop()
    payload: dict[str, object] = {
        "schema_version": "fixture-hk-ca-implementation-v1",
        "scope_complete": True,
        "correction_history_complete": True,
        "withdrawal_history_complete": True,
        "records": records,
        "withdrawals": withdrawals or [],
    }
    if only_scope:
        payload = {"scope_complete": True}
    payload.update(top_level_overrides or {})
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _verified(
    *,
    capability: impl.HkCorporateActionImplementationCapability | None = None,
    record_overrides: dict[str, object] | None = None,
    first_record_overrides: dict[str, object] | None = None,
    remove_first_record_field: str | None = None,
    drop_last: bool = False,
    only_scope: bool = False,
    withdrawals: list[dict[str, object]] | None = None,
    top_level_overrides: dict[str, object] | None = None,
    raw_content: bytes | None = None,
) -> tuple[
    impl.VerifiedHkCorporateActionImplementationProjection,
    ca.HkCorporateActionSelectionResult,
    ca.VerifiedHkCorporateActionProjection,
    _ImplementationAdapter,
]:
    p0_result, p0_projection = _p0()
    query = _query(p0_result)
    raw = impl.HkCorporateActionImplementationRawFile.create(
        role="MAIN",
        content=(
            raw_content
            if raw_content is not None
            else _implementation_payload(
                p0_result,
                record_overrides=record_overrides,
                first_record_overrides=first_record_overrides,
                remove_first_record_field=remove_first_record_field,
                drop_last=drop_last,
                only_scope=only_scope,
                withdrawals=withdrawals,
                top_level_overrides=top_level_overrides,
            )
        ),
        metadata=b'{"issue":"impl","retained":true}',
    )
    bundle = impl.HkCorporateActionImplementationRawBundle.create(
        query=query,
        source=SOURCE,
        source_issue_id="implementation-issue",
        files=(raw,),
        source_observed_at=OBSERVED,
        coverage_as_of=AS_OF,
    )
    adapter = _ImplementationAdapter(
        p0_result=p0_result,
        capability=capability,
    )
    projection = impl.verify_hk_corporate_action_implementation_source(
        adapter=adapter,
        query=query,
        bundle=bundle,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )
    return projection, p0_result, p0_projection, adapter


def test_exact_implemented_set_is_fresh_verifiable() -> None:
    projection, p0_result, p0_projection, _ = _verified()
    result = impl.select_implemented_hk_corporate_actions(
        projection=projection,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )
    assert result.actions.height == result.implementation_evidence.height == 2
    assert result.implementation_evidence.get_column(
        "implementation_status"
    ).to_list() == ["IMPLEMENTED", "IMPLEMENTED"]
    impl.verify_implemented_hk_corporate_action_set(
        implemented=result,
        projection=projection,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"implementation_status": "PENDING"}, "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"),
        (
            {"implementation_confirmed_at": "2026-05-11T00:00:00Z"},
            "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID",
        ),
        ({"source_revision_id": "wrong-revision"}, "HK_CA_IMPLEMENTATION_SCOPE_INVALID"),
        ({"source": "OTHER_SOURCE"}, "HK_CA_IMPLEMENTATION_SCOPE_INVALID"),
    ],
)
def test_pending_future_and_cross_identity_fail_closed(
    overrides: dict[str, object], code: str
) -> None:
    with pytest.raises(impl.HkCorporateActionImplementationError, match=f"^{code}$"):
        _verified(record_overrides=overrides)


def test_missing_event_is_scope_invalid() -> None:
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_SCOPE_INVALID$",
    ):
        _verified(drop_last=True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"symbol": "00999.HK"},
        {"action_type": "SPLIT"},
        {"source_event_id": "other-event"},
        {"source_revision_id": "other-revision"},
    ],
)
def test_cross_p0_identity_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_SCOPE_INVALID$",
    ):
        _verified(first_record_overrides=overrides)


@pytest.mark.parametrize(
    "status", ["PENDING", "ANNOUNCED", "APPROVED", "COMPLETED_BY_DATE"]
)
def test_retained_non_implemented_status_is_rejected(status: str) -> None:
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(first_record_overrides={"implementation_status": status})


@pytest.mark.parametrize(
    "field",
    [
        "implementation_status",
        "implementation_confirmed_at",
        "source_record_id",
        "source_revision_id",
    ],
)
def test_missing_retained_implementation_field_is_rejected(field: str) -> None:
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(remove_first_record_field=field)


def test_scope_only_raw_cannot_promote_active_p0_actions() -> None:
    p0_result, _ = _p0()
    assert set(p0_result.revision_evidence.get_column("revision_status")) == {"ACTIVE"}
    assert all(
        value <= AS_OF.date()
        for value in p0_result.actions.get_column("ex_date").to_list()
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(only_scope=True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"top_level_overrides": {"unknown": True}},
        {"top_level_overrides": {"correction_history_complete": False}},
        {"raw_content": b'{"schema_version":'},
        {"raw_content": b'{"scope_complete":true,"scope_complete":true}'},
    ],
)
def test_unknown_truncated_duplicate_or_incomplete_scope_raw_is_rejected(
    kwargs: dict[str, object]
) -> None:
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(**kwargs)  # type: ignore[arg-type]


def _retained_withdrawal(
    p0_result: ca.HkCorporateActionSelectionResult,
    *,
    confirmed_at: str,
    action_index: int = 0,
    source_record_id: object = "withdrawals/0",
) -> dict[str, object]:
    action = p0_result.actions.sort("event_id").row(action_index, named=True)
    return {
        "event_id": action["event_id"],
        "source": action["source"],
        "source_event_id": action["source_event_id"],
        "source_revision_id": action["source_revision_id"],
        "withdrawal_confirmed_at": confirmed_at,
        "source_record_id": source_record_id,
    }


def test_future_withdrawal_does_not_erase_earlier_as_of_but_known_one_rejects() -> None:
    p0_result, _ = _p0()
    future = _retained_withdrawal(
        p0_result, confirmed_at="2026-05-11T00:00:00Z"
    )
    projection, current_result, current_projection, _ = _verified(
        withdrawals=[future]
    )
    implemented = impl.select_implemented_hk_corporate_actions(
        projection=projection,
        p0_result=current_result,
        p0_projection=current_projection,
    )
    assert implemented.actions.height == 2

    known = _retained_withdrawal(
        p0_result, confirmed_at="2026-05-10T00:00:00Z"
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(withdrawals=[known])


@pytest.mark.parametrize("source_record_id", ["", " ", " withdrawals/0 ", 7])
def test_withdrawal_source_record_is_strict_text(source_record_id: object) -> None:
    p0_result, _ = _p0()
    withdrawal = _retained_withdrawal(
        p0_result,
        confirmed_at="2026-05-11T00:00:00Z",
        source_record_id=source_record_id,
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(withdrawals=[withdrawal])


def test_withdrawal_must_be_observed_and_unique_before_as_of_selection() -> None:
    p0_result, _ = _p0()
    after_observation = _retained_withdrawal(
        p0_result, confirmed_at="2026-08-02T00:00:00Z"
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(withdrawals=[after_observation])

    future = _retained_withdrawal(
        p0_result, confirmed_at="2026-05-11T00:00:00Z"
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(withdrawals=[future, dict(future)])

    same_business_other_record = {
        **future,
        "source_record_id": "withdrawals/other",
    }
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(withdrawals=[future, same_business_other_record])

    same_business_different_time = {
        **future,
        "withdrawal_confirmed_at": "2026-05-12T00:00:00Z",
        "source_record_id": "withdrawals/later",
    }
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(withdrawals=[future, same_business_different_time])


def test_distinct_future_withdrawals_require_canonical_order() -> None:
    p0_result, _ = _p0()
    withdrawals = [
        _retained_withdrawal(
            p0_result,
            action_index=index,
            confirmed_at=f"2026-05-{11 + index:02d}T00:00:00Z",
            source_record_id=f"withdrawals/{index}",
        )
        for index in range(2)
    ]
    def key(item: dict[str, object]) -> tuple[object, ...]:
        return (
            item["source"],
            item["source_event_id"],
            item["source_revision_id"],
            item["withdrawal_confirmed_at"],
            item["source_record_id"],
        )
    canonical = sorted(withdrawals, key=key)
    projection, current_result, current_projection, _ = _verified(
        withdrawals=canonical
    )
    implemented = impl.select_implemented_hk_corporate_actions(
        projection=projection,
        p0_result=current_result,
        p0_projection=current_projection,
    )
    assert implemented.actions.height == 2
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        _verified(withdrawals=list(reversed(canonical)))


def _sub_capability() -> impl.HkCorporateActionImplementationCapability:
    class SubCapability(impl.HkCorporateActionImplementationCapability):
        pass

    return SubCapability(
        source=SOURCE,
        adapter_version="implementation-fixture-v1",
        retained_bytes_verifiable=True,
        exact_scope_complete=True,
        implementation_status_available=True,
        stable_revision_identity_available=True,
        correction_history_complete=True,
        withdrawal_history_complete=True,
        official_confirmed_at_available=True,
        source_observed_at_available=True,
    )


def test_capability_subclass_is_rejected_at_all_fresh_boundaries() -> None:
    projection, p0_result, p0_projection, _ = _verified()
    implemented = impl.select_implemented_hk_corporate_actions(
        projection=projection,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )
    subclass = _sub_capability()

    builder_adapter = _ImplementationAdapter(
        p0_result=p0_result, capability=subclass
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        builder_adapter.verify_retained(
            query=projection.query, bundle=projection.bundle
        )

    wrapper_adapter = _ImplementationAdapter(
        p0_result=p0_result, capability=subclass
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        impl.verify_hk_corporate_action_implementation_source(
            adapter=wrapper_adapter,
            query=projection.query,
            bundle=projection.bundle,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )
    assert wrapper_adapter.calls == 0

    object.__setattr__(projection, "capability", subclass)
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        impl.select_implemented_hk_corporate_actions(
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        impl.verify_implemented_hk_corporate_action_set(
            implemented=implemented,
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )


def test_exact_content_capability_clone_remains_valid() -> None:
    projection, p0_result, p0_projection, _ = _verified()
    cloned = copy(projection.capability)
    assert type(cloned) is impl.HkCorporateActionImplementationCapability
    object.__setattr__(projection, "capability", cloned)
    implemented = impl.select_implemented_hk_corporate_actions(
        projection=projection,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )
    impl.verify_implemented_hk_corporate_action_set(
        implemented=implemented,
        projection=projection,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", ""),
        ("source", " "),
        ("source", 7),
        ("source", "OTHER_SOURCE"),
        ("adapter_version", ""),
        ("adapter_version", " "),
        ("adapter_version", 7),
        ("adapter_version", "wrong-version"),
    ],
)
def test_capability_source_and_version_are_fresh_at_every_boundary(
    field: str, value: object
) -> None:
    projection, p0_result, p0_projection, adapter = _verified()
    implemented = impl.select_implemented_hk_corporate_actions(
        projection=projection,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )
    capability = projection.capability
    object.__setattr__(capability, field, value)

    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        adapter.verify_retained(query=projection.query, bundle=projection.bundle)
    calls = adapter.calls
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        impl.verify_hk_corporate_action_implementation_source(
            adapter=adapter,
            query=projection.query,
            bundle=projection.bundle,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )
    assert adapter.calls == calls
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        impl.select_implemented_hk_corporate_actions(
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        impl.verify_implemented_hk_corporate_action_set(
            implemented=implemented,
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )


def test_capability_preflight_precedes_adapter() -> None:
    p0_result, p0_projection = _p0()
    query = _query(p0_result)
    raw = impl.HkCorporateActionImplementationRawFile.create(
        role="MAIN", content=b"not-json", metadata=b"metadata"
    )
    bundle = impl.HkCorporateActionImplementationRawBundle.create(
        query=query,
        source=SOURCE,
        source_issue_id="issue",
        files=(raw,),
        source_observed_at=OBSERVED,
        coverage_as_of=AS_OF,
    )
    adapter = _ImplementationAdapter(
        p0_result=p0_result,
        capability=_capability(withdrawal_history_complete=False),
    )
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_CAPABILITY_UNSUPPORTED$",
    ):
        impl.verify_hk_corporate_action_implementation_source(
            adapter=adapter,
            query=query,
            bundle=bundle,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )
    assert adapter.calls == 0


def test_factory_only_pickle_and_old_attestation_reuse_fail() -> None:
    projection, p0_result, p0_projection, adapter = _verified()
    implemented = impl.select_implemented_hk_corporate_actions(
        projection=projection,
        p0_result=p0_result,
        p0_projection=p0_projection,
    )
    parsed = adapter.verify_retained(query=projection.query, bundle=projection.bundle)
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_VERIFY_FAILED$",
    ):
        impl.select_implemented_hk_corporate_actions(
            projection=parsed,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )
    with pytest.raises(TypeError):
        pickle.dumps(projection)
    with pytest.raises(TypeError):
        pickle.dumps(implemented)
    old_attestation = projection._attestation
    object.__setattr__(
        projection,
        "evidence",
        projection.evidence.with_columns(
            pl.lit("changed-record").alias("source_record_id")
        ),
    )
    object.__setattr__(projection, "_attestation", old_attestation)
    with pytest.raises(impl.HkCorporateActionImplementationError):
        impl.select_implemented_hk_corporate_actions(
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )


def test_fresh_raw_digest_and_p0_result_drift_fail() -> None:
    projection, p0_result, p0_projection, _ = _verified()
    raw = projection.bundle.files[0]
    object.__setattr__(raw, "content", b"DRIFT")
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_EVIDENCE_INVALID$",
    ):
        impl.select_implemented_hk_corporate_actions(
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )

    projection, p0_result, p0_projection, _ = _verified()
    object.__setattr__(p0_result, "actions_sha256", "f" * 64)
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_VERIFY_FAILED$",
    ):
        impl.select_implemented_hk_corporate_actions(
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )


def test_query_and_raw_file_are_strict() -> None:
    p0_result, _ = _p0()
    with pytest.raises(impl.HkCorporateActionImplementationError):
        replace(_query(p0_result), event_ids=tuple(reversed(_query(p0_result).event_ids)))
    with pytest.raises(impl.HkCorporateActionImplementationError):
        impl.HkCorporateActionImplementationRawFile(
            role="MAIN",
            content=b"x",
            metadata=b"m",
            content_sha256="0" * 64,
            metadata_sha256="0" * 64,
        )


def test_hostile_adapter_error_is_stable_and_redacted() -> None:
    projection, p0_result, p0_projection, _ = _verified()

    class Hostile:
        source = SOURCE
        capability = projection.capability

        def verify_retained(
            self,
            *,
            query: impl.HkCorporateActionImplementationQuery,
            bundle: impl.HkCorporateActionImplementationRawBundle,
        ) -> impl.VerifiedHkCorporateActionImplementationProjection:
            del query, bundle
            try:
                raise RuntimeError("SECRET_SENTINEL")
            except RuntimeError:
                raise impl.HkCorporateActionImplementationError(
                    "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"
                )

    with pytest.raises(impl.HkCorporateActionImplementationError) as raised:
        impl.verify_hk_corporate_action_implementation_source(
            adapter=Hostile(),
            query=projection.query,
            bundle=projection.bundle,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )
    error = raised.value
    assert str(error) == "HK_CA_IMPLEMENTATION_EVIDENCE_INVALID"
    assert error.__cause__ is None and error.__context__ is None
    assert "SECRET_SENTINEL" not in "".join(traceback.format_exception(error))


def test_whole_rehash_cannot_reuse_old_attestation() -> None:
    projection, p0_result, p0_projection, _ = _verified()
    old_attestation = projection._attestation
    raw = projection.bundle.files[0]
    object.__setattr__(raw, "content", b'{"scope_complete":true,"v":2}')
    object.__setattr__(raw, "content_sha256", hashlib.sha256(raw.content).hexdigest())
    object.__setattr__(projection.bundle, "bundle_sha256", impl._bundle_sha256(
        query=projection.bundle.query,
        source=projection.bundle.source,
        source_issue_id=projection.bundle.source_issue_id,
        files=projection.bundle.files,
        source_observed_at=projection.bundle.source_observed_at,
        coverage_as_of=projection.bundle.coverage_as_of,
    ))
    frame = projection.evidence.with_columns(
        pl.lit(raw.content_sha256).alias("raw_file_sha256"),
        pl.lit(projection.bundle.bundle_sha256).alias("raw_bundle_sha256"),
    )
    rows = []
    for row in frame.iter_rows(named=True):
        row["implementation_evidence_sha256"] = impl._implementation_evidence_sha256(row)
        rows.append(row)
    frame = pl.DataFrame(rows, schema=impl._evidence_schema(), orient="row")
    object.__setattr__(projection, "evidence", frame)
    digest = impl._table_sha256("hk_ca_implementation_evidence", frame)
    object.__setattr__(projection, "evidence_content_sha256", digest)
    object.__setattr__(projection, "projection_sha256", impl._projection_sha256(
        projection.capability, projection.query, projection.bundle, digest
    ))
    object.__setattr__(projection, "_attestation", old_attestation)
    with pytest.raises(
        impl.HkCorporateActionImplementationError,
        match="^HK_CA_IMPLEMENTATION_VERIFY_FAILED$",
    ):
        impl.select_implemented_hk_corporate_actions(
            projection=projection,
            p0_result=p0_result,
            p0_projection=p0_projection,
        )


def test_adapter_retained_payload_is_not_in_repr() -> None:
    projection, _, _, _ = _verified()
    assert '"implementation_status":"IMPLEMENTED"' not in repr(projection)
    assert '{"issue":"impl","retained":true}' not in repr(projection)
