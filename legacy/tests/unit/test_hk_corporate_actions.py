"""Source-neutral retained-bytes HK corporate-action PIT contract tests."""

from __future__ import annotations

import datetime as dt
import importlib
import json
import pickle
import sys
import traceback
from dataclasses import replace
from typing import Any

import polars as pl
import pytest

import quant.data.hk_corporate_actions as ca
from quant.domain import CorporateActionType, Currency

UTC = dt.UTC
SOURCE = "FIXTURE_OFFICIAL"


def _capability(**overrides: object) -> ca.HkCorporateActionCapability:
    values: dict[str, object] = {
        "source": SOURCE,
        "adapter_version": "fixture-v1",
        "supported_action_types": tuple(sorted(CorporateActionType, key=lambda item: item.value)),
        "supported_currencies": tuple(sorted(Currency, key=lambda item: item.value)),
        "retained_bytes_verifiable": True,
        "official_published_at_available": True,
        "stable_event_identity_available": True,
        "stable_revision_identity_available": True,
        "revision_predecessor_available": True,
        "withdrawal_history_complete": True,
        "correction_supplement_closure_complete": True,
        "scope_completeness_verifiable": True,
    }
    values.update(overrides)
    return ca.HkCorporateActionCapability(**values)  # type: ignore[arg-type]


def _query(as_of: dt.datetime) -> ca.HkCorporateActionQuery:
    return ca.HkCorporateActionQuery(
        symbols=("00005.HK", "00700.HK"),
        event_date_start=dt.date(2026, 5, 1),
        event_date_end=dt.date(2026, 5, 31),
        as_of=as_of,
        required_action_types=tuple(sorted(CorporateActionType, key=lambda item: item.value)),
        accepted_currencies=tuple(sorted(Currency, key=lambda item: item.value)),
    )


def _record(
    *,
    event: str,
    revision: str,
    sequence: int,
    symbol: str,
    action: str,
    published_at: str,
    status: str = "ACTIVE",
    **overrides: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "source_event_id": event,
        "source_revision_id": revision,
        "revision_sequence": sequence,
        "revision_status": status,
        "symbol": symbol,
        "action_type": action,
        "published_at": published_at,
        "record_date": "2026-05-08",
        "ex_date": "2026-05-11",
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
    }
    row.update(overrides)
    return row


def _records() -> list[dict[str, object]]:
    return [
        _record(
            event="dividend", revision="dividend-r1", sequence=1,
            symbol="00700.HK", action="DIVIDEND", published_at="2026-05-04T09:00:00Z",
            pay_date="2026-05-20", declared_currency="HKD", cash_per_share_gross=0.5,
        ),
        _record(
            event="dividend", revision="dividend-r2", sequence=2,
            symbol="00700.HK", action="DIVIDEND", published_at="2026-05-05T02:00:00Z",
            pay_date="2026-05-22", declared_currency="HKD", cash_per_share_gross=0.6,
        ),
        _record(
            event="split", revision="split-r1", sequence=1,
            symbol="00005.HK", action="SPLIT", published_at="2026-05-04T10:00:00Z",
            stock_list_date="2026-05-12", share_multiplier=0.5,
        ),
        _record(
            event="withdrawal", revision="withdrawal-r1", sequence=1,
            symbol="00700.HK", action="BONUS", published_at="2026-05-04T11:00:00Z",
            stock_list_date="2026-05-12", stock_ratio=0.1,
        ),
        _record(
            event="withdrawal", revision="withdrawal-r2", sequence=2,
            symbol="00700.HK", action="BONUS", published_at="2026-05-06T03:00:00Z",
            status="WITHDRAWN", stock_list_date="2026-05-12", stock_ratio=0.1,
        ),
        _record(
            event="rights", revision="rights-r1", sequence=1,
            symbol="00005.HK", action="RIGHTS", published_at="2026-05-04T12:00:00Z",
            stock_list_date="2026-05-29", declared_currency="HKD", rights_ratio=0.2,
            rights_subscription_price=45.0, rights_subscription_start="2026-05-12",
            rights_subscription_end="2026-05-20",
        ),
    ]


class FixtureHkCorporateActionSourceAdapter:
    """Strict parser for this test's tiny, deterministic retained JSON format."""

    source = SOURCE

    def __init__(self, capability: ca.HkCorporateActionCapability | None = None) -> None:
        self.capability = capability or _capability()
        self.calls = 0

    def verify_retained(
        self,
        *,
        query: ca.HkCorporateActionQuery,
        bundle: ca.HkCorporateActionRawBundle,
    ) -> ca.VerifiedHkCorporateActionProjection:
        self.calls += 1
        raw = bundle.files[0]
        try:
            metadata = json.loads(raw.metadata)
            payload = json.loads(raw.content)
        except (UnicodeError, json.JSONDecodeError, TypeError):
            raise ca.HkCorporateActionError("HK_CA_EVIDENCE_INVALID") from None
        if metadata != {"complete": True} or set(payload) != {"records"} or not isinstance(payload["records"], list):
            raise ca.HkCorporateActionError("HK_CA_EVIDENCE_INVALID")
        rows: list[dict[str, Any]] = []
        previous: dict[str, str] = {}
        expected = set(_record(event="e", revision="r", sequence=1, symbol="00700.HK", action="BONUS", published_at="2026-05-04T00:00:00Z"))
        for index, record in enumerate(payload["records"]):
            if not isinstance(record, dict) or set(record) != expected:
                raise ca.HkCorporateActionError("HK_CA_EVIDENCE_INVALID")
            def parse_date(value: object) -> dt.date | None:
                return None if value is None else dt.date.fromisoformat(str(value))
            published = dt.datetime.fromisoformat(str(record["published_at"]).replace("Z", "+00:00"))
            row = {
                **record,
                "published_at": published,
                "source": SOURCE,
                "source_observed_at": bundle.source_observed_at,
                "predecessor_candidate_id": previous.get(str(record["source_event_id"])),
                "raw_bundle_sha256": bundle.bundle_sha256,
                "raw_file_sha256": raw.content_sha256,
                "raw_metadata_sha256": raw.metadata_sha256,
                "raw_selector": f"records/{index}",
            }
            for name in (
                "record_date", "ex_date", "pay_date", "stock_list_date",
                "rights_subscription_start", "rights_subscription_end",
            ):
                row[name] = parse_date(row[name])
            row["economic_event_key_sha256"] = ca._event_key(row)
            row["candidate_id"] = ca._candidate_id(row)
            previous[str(record["source_event_id"])] = row["candidate_id"]
            rows.append(row)
        frame = ca._candidate_frame(rows).sort(["source", "source_event_id", "revision_sequence"])
        return ca.build_verified_hk_corporate_action_projection(
            capability=self.capability, query=query, bundle=bundle, candidates=frame
        )


def _projection(
    as_of: dt.datetime,
    records: list[dict[str, object]] | None = None,
    capability: ca.HkCorporateActionCapability | None = None,
) -> tuple[ca.VerifiedHkCorporateActionProjection, FixtureHkCorporateActionSourceAdapter]:
    query = _query(as_of)
    content = json.dumps({"records": records if records is not None else _records()}, sort_keys=True, separators=(",", ":")).encode()
    raw = ca.HkCorporateActionRawFile.create(role="MAIN", content=content, metadata=b'{"complete":true}')
    bundle = ca.HkCorporateActionRawBundle.create(
        query=query, source=SOURCE, source_issue_id="fixture-issue-v1", files=(raw,),
        source_observed_at=dt.datetime(2026, 8, 1, tzinfo=UTC),
        coverage_as_of=dt.datetime(2026, 8, 1, tzinfo=UTC),
    )
    adapter = FixtureHkCorporateActionSourceAdapter(capability)
    return ca.verify_hk_corporate_action_source(adapter=adapter, query=query, bundle=bundle), adapter


def test_no_lookahead_correction_and_same_date_distinct_events() -> None:
    before, _ = _projection(dt.datetime(2026, 5, 5, 1, 59, 59, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=before)
    dividend = result.actions.filter(pl.col("source_event_id") == "dividend").row(0, named=True)
    assert dividend["cash_per_share_gross"] == 0.5
    assert result.actions.filter(pl.col("ex_date") == dt.date(2026, 5, 11)).height == 4
    after, _ = _projection(dt.datetime(2026, 5, 5, 2, tzinfo=UTC))
    corrected = ca.select_hk_corporate_actions(projection=after)
    assert corrected.actions.filter(pl.col("source_event_id") == "dividend")["cash_per_share_gross"].item() == 0.6


def test_future_withdrawal_does_not_erase_history_then_becomes_tombstone() -> None:
    before, _ = _projection(dt.datetime(2026, 5, 6, 2, 59, 59, tzinfo=UTC))
    assert "withdrawal" in ca.select_hk_corporate_actions(projection=before).actions["source_event_id"].to_list()
    after, _ = _projection(dt.datetime(2026, 5, 6, 3, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=after)
    assert "withdrawal" not in result.actions["source_event_id"].to_list()
    tombstone = result.revision_evidence.filter(pl.col("source_revision_id") == "withdrawal-r2").row(0, named=True)
    assert tombstone["selected"] is True and tombstone["selection_reason"] == "WITHDRAWN_AS_OF"


def test_split_and_rights_units_are_distinct_and_strict() -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=projection)
    split = result.actions.filter(pl.col("action_type") == "SPLIT").row(0, named=True)
    assert split["share_multiplier"] == 0.5 and split["stock_ratio"] is None
    broken = _records()
    broken[-1] = {**broken[-1], "rights_subscription_price": None}
    with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_ACTION_UNSUPPORTED$"):
        _projection(dt.datetime(2026, 5, 7, tzinfo=UTC), broken)


def test_replay_is_stable_and_result_tampering_fails_fresh_verification() -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    first = ca.select_hk_corporate_actions(projection=projection)
    second = ca.select_hk_corporate_actions(projection=projection)
    assert first.actions_sha256 == second.actions_sha256
    assert first.revision_evidence_sha256 == second.revision_evidence_sha256
    ca.verify_hk_corporate_action_selection_result(result=first, projection=projection)
    object.__setattr__(first, "actions", first.actions.with_columns(pl.lit("x" * 64).alias("event_id")))
    with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_RESULT_INVALID$"):
        ca.verify_hk_corporate_action_selection_result(result=first, projection=projection)


@pytest.mark.parametrize("mutation", ["start_at_two", "gap", "wrong_predecessor", "change_symbol", "same_published"])
def test_revision_chain_conflicts_fail_closed(mutation: str) -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    frame = projection.candidates
    if mutation == "start_at_two":
        frame = frame.with_columns(pl.when(pl.col("source_event_id") == "split").then(2).otherwise(pl.col("revision_sequence")).alias("revision_sequence"))
    elif mutation == "gap":
        frame = frame.with_columns(pl.when(pl.col("source_revision_id") == "dividend-r2").then(3).otherwise(pl.col("revision_sequence")).alias("revision_sequence"))
    elif mutation == "wrong_predecessor":
        frame = frame.with_columns(pl.when(pl.col("source_revision_id") == "dividend-r2").then(pl.lit("f" * 64)).otherwise(pl.col("predecessor_candidate_id")).alias("predecessor_candidate_id"))
    elif mutation == "change_symbol":
        frame = frame.with_columns(pl.when(pl.col("source_revision_id") == "dividend-r2").then(pl.lit("00005.HK")).otherwise(pl.col("symbol")).alias("symbol"))
    else:
        frame = frame.with_columns(pl.when(pl.col("source_revision_id") == "dividend-r2").then(dt.datetime(2026, 5, 4, 9, tzinfo=UTC)).otherwise(pl.col("published_at")).alias("published_at"))
    with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_REVISION_CONFLICT$"):
        ca.build_verified_hk_corporate_action_projection(
            capability=projection.capability, query=projection.query,
            bundle=projection.bundle, candidates=frame,
        )


def test_capability_preflight_happens_before_adapter_parse() -> None:
    capability = _capability(withdrawal_history_complete=False)
    query = _query(dt.datetime(2026, 5, 7, tzinfo=UTC))
    raw = ca.HkCorporateActionRawFile.create(role="MAIN", content=b"not-json", metadata=b"metadata")
    bundle = ca.HkCorporateActionRawBundle.create(
        query=query, source=SOURCE, source_issue_id="issue", files=(raw,),
        source_observed_at=dt.datetime(2026, 8, 1, tzinfo=UTC), coverage_as_of=dt.datetime(2026, 8, 1, tzinfo=UTC),
    )
    adapter = FixtureHkCorporateActionSourceAdapter(capability)
    with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_CAPABILITY_UNSUPPORTED$"):
        ca.verify_hk_corporate_action_source(adapter=adapter, query=query, bundle=bundle)
    assert adapter.calls == 0


def test_raw_digest_query_and_utc_boundaries_fail_closed() -> None:
    with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_EVIDENCE_INVALID$"):
        ca.HkCorporateActionRawFile(role="MAIN", content=b"x", metadata=b"m", content_sha256="0" * 64, metadata_sha256="0" * 64)
    for invalid in (
        dt.datetime(2026, 5, 7),
        dt.datetime(2026, 5, 7, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    ):
        with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_INPUT_INVALID$"):
            _query(invalid)
    with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_INPUT_INVALID$"):
        replace(_query(dt.datetime(2026, 5, 7, tzinfo=UTC)), symbols=("００７００.HK",))


def test_empty_complete_projection_is_valid_but_ordinary_frame_is_not_verified() -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC), [])
    result = ca.select_hk_corporate_actions(projection=projection)
    assert result.actions.is_empty() and result.revision_evidence.is_empty()
    with pytest.raises(ca.HkCorporateActionError, match="^HK_CA_EVIDENCE_INVALID$"):
        ca.select_hk_corporate_actions(projection=pl.DataFrame())  # type: ignore[arg-type]


def test_import_has_no_network_or_research_sdk_side_effects() -> None:
    names = ("requests", "tushare", "akshare", "baostock", "qlib")
    before = {name: name in sys.modules for name in names}
    importlib.reload(ca)
    assert {name: name in sys.modules for name in names} == before


def _assert_clean_error(error: ca.HkCorporateActionError, code: str) -> None:
    assert str(error) == code
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "SECRET_SENTINEL" not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize("field", ["content", "metadata", "both"])
def test_consumers_fresh_rehash_retained_bytes(field: str) -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=projection)
    raw = projection.bundle.files[0]
    if field in {"content", "both"}:
        object.__setattr__(raw, "content", b"SECRET_SENTINEL_CONTENT_DRIFT")
    if field in {"metadata", "both"}:
        object.__setattr__(raw, "metadata", b"SECRET_SENTINEL_METADATA_DRIFT")
    with pytest.raises(ca.HkCorporateActionError) as select_error:
        ca.select_hk_corporate_actions(projection=projection)
    _assert_clean_error(select_error.value, "HK_CA_EVIDENCE_INVALID")
    with pytest.raises(ca.HkCorporateActionError) as verify_error:
        ca.verify_hk_corporate_action_selection_result(
            result=result, projection=projection
        )
    _assert_clean_error(verify_error.value, "HK_CA_EVIDENCE_INVALID")


@pytest.mark.parametrize("context_type", [None, ValueError, RuntimeError])
@pytest.mark.parametrize("code", sorted(ca._ERROR_CODES))
def test_hostile_adapter_stable_errors_are_reconstructed_without_chain(
    context_type: type[Exception] | None,
    code: str,
) -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))

    class HostileAdapter:
        source = SOURCE
        capability = projection.capability

        def verify_retained(
            self,
            *,
            query: ca.HkCorporateActionQuery,
            bundle: ca.HkCorporateActionRawBundle,
        ) -> ca.VerifiedHkCorporateActionProjection:
            del query, bundle
            if context_type is None:
                raise ca.HkCorporateActionError(code)
            try:
                raise context_type("SECRET_SENTINEL")
            except (ValueError, RuntimeError):
                raise ca.HkCorporateActionError(code)

    with pytest.raises(ca.HkCorporateActionError) as captured:
        ca.verify_hk_corporate_action_source(
            adapter=HostileAdapter(),
            query=projection.query,
            bundle=projection.bundle,
        )
    _assert_clean_error(captured.value, code)


def test_hostile_adapter_unknown_error_maps_to_clean_evidence_error() -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))

    class HostileAdapter:
        source = SOURCE
        capability = projection.capability

        def verify_retained(
            self,
            *,
            query: ca.HkCorporateActionQuery,
            bundle: ca.HkCorporateActionRawBundle,
        ) -> ca.VerifiedHkCorporateActionProjection:
            del query, bundle
            raise RuntimeError("SECRET_SENTINEL")

    with pytest.raises(ca.HkCorporateActionError) as captured:
        ca.verify_hk_corporate_action_source(
            adapter=HostileAdapter(), query=projection.query, bundle=projection.bundle
        )
    _assert_clean_error(captured.value, "HK_CA_EVIDENCE_INVALID")


def test_factory_selector_and_result_verifier_reconstruct_nested_stable_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=projection)

    def hostile(*args: object, **kwargs: object) -> None:
        del args, kwargs
        try:
            raise RuntimeError("SECRET_SENTINEL")
        except RuntimeError:
            raise ca.HkCorporateActionError("HK_CA_REVISION_CONFLICT")

    with monkeypatch.context() as scoped:
        scoped.setattr(ca, "_select_frames", hostile)
        with pytest.raises(ca.HkCorporateActionError) as factory_error:
            ca.build_verified_hk_corporate_action_projection(
                capability=projection.capability,
                query=projection.query,
                bundle=projection.bundle,
                candidates=projection.candidates,
            )
        _assert_clean_error(factory_error.value, "HK_CA_REVISION_CONFLICT")

    with monkeypatch.context() as scoped:
        scoped.setattr(ca, "_verify_projection", hostile)
        with pytest.raises(ca.HkCorporateActionError) as selector_error:
            ca.select_hk_corporate_actions(projection=projection)
        _assert_clean_error(selector_error.value, "HK_CA_REVISION_CONFLICT")
        with pytest.raises(ca.HkCorporateActionError) as verifier_error:
            ca.verify_hk_corporate_action_selection_result(
                result=result, projection=projection
            )
        _assert_clean_error(verifier_error.value, "HK_CA_REVISION_CONFLICT")


def test_factory_projection_is_parsed_only_until_source_wrapper_attests() -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=projection)
    parsed = ca.build_verified_hk_corporate_action_projection(
        capability=projection.capability,
        query=projection.query,
        bundle=projection.bundle,
        candidates=projection.candidates,
    )

    assert parsed._attestation is None
    assert projection._attestation is not None
    with pytest.raises(ca.HkCorporateActionError) as select_error:
        ca.select_hk_corporate_actions(projection=parsed)
    _assert_clean_error(select_error.value, "HK_CA_EVIDENCE_INVALID")
    with pytest.raises(ca.HkCorporateActionError) as verify_error:
        ca.verify_hk_corporate_action_selection_result(
            result=result, projection=parsed
        )
    _assert_clean_error(verify_error.value, "HK_CA_EVIDENCE_INVALID")


def test_source_wrapper_rejects_replayed_source_verified_projection() -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))

    class ReplayAdapter:
        source = SOURCE
        capability = projection.capability

        def verify_retained(
            self,
            *,
            query: ca.HkCorporateActionQuery,
            bundle: ca.HkCorporateActionRawBundle,
        ) -> ca.VerifiedHkCorporateActionProjection:
            del query, bundle
            return projection

    with pytest.raises(ca.HkCorporateActionError) as captured:
        ca.verify_hk_corporate_action_source(
            adapter=ReplayAdapter(),
            query=projection.query,
            bundle=projection.bundle,
        )
    _assert_clean_error(captured.value, "HK_CA_EVIDENCE_INVALID")


def _rehash_projection_public_chain(
    projection: ca.VerifiedHkCorporateActionProjection,
    mutation: str,
) -> None:
    raw = projection.bundle.files[0]
    if mutation == "content":
        object.__setattr__(raw, "content", b'{"records":[]}')
    elif mutation == "metadata":
        object.__setattr__(raw, "metadata", b'{"complete":false}')
    elif mutation == "source_issue":
        object.__setattr__(projection.bundle, "source_issue_id", "fixture-issue-v2")
    elif mutation not in {"candidate", "projection_digest"}:
        raise AssertionError(f"unknown mutation: {mutation}")

    if mutation in {"content", "metadata"}:
        object.__setattr__(raw, "content_sha256", ca.hashlib.sha256(raw.content).hexdigest())
        object.__setattr__(
            raw, "metadata_sha256", ca.hashlib.sha256(raw.metadata).hexdigest()
        )
    if mutation != "projection_digest":
        object.__setattr__(
            projection.bundle,
            "bundle_sha256",
            ca._bundle_sha256(
                query=projection.bundle.query,
                source=projection.bundle.source,
                source_issue_id=projection.bundle.source_issue_id,
                files=projection.bundle.files,
                source_observed_at=projection.bundle.source_observed_at,
                coverage_as_of=projection.bundle.coverage_as_of,
            ),
        )
        rows = projection.candidates.sort(
            ["source", "source_event_id", "revision_sequence"]
        ).to_dicts()
        previous: dict[tuple[str, str], str] = {}
        for index, row in enumerate(rows):
            event = (str(row["source"]), str(row["source_event_id"]))
            row["raw_bundle_sha256"] = projection.bundle.bundle_sha256
            row["raw_file_sha256"] = raw.content_sha256
            row["raw_metadata_sha256"] = raw.metadata_sha256
            row["predecessor_candidate_id"] = previous.get(event)
            if mutation == "candidate" and index == 0:
                row["raw_selector"] = f'{row["raw_selector"]}-changed'
            row["economic_event_key_sha256"] = ca._event_key(row)
            row["candidate_id"] = ca._candidate_id(row)
            previous[event] = str(row["candidate_id"])
        frame = ca._candidate_frame(rows).sort(
            ["source", "source_event_id", "revision_sequence"]
        )
        object.__setattr__(projection, "candidates", frame)
        object.__setattr__(
            projection,
            "projection_sha256",
            ca._projection_sha256(
                projection.capability,
                projection.query,
                projection.bundle,
                frame,
            ),
        )
    else:
        object.__setattr__(projection, "projection_sha256", "0" * 64)


@pytest.mark.parametrize(
    "mutation", ["content", "metadata", "source_issue", "candidate", "projection_digest"]
)
def test_old_attestation_reuse_on_rehashed_public_chain_fails_closed(
    mutation: str,
) -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=projection)
    old_attestation = projection._attestation
    _rehash_projection_public_chain(projection, mutation)

    assert projection._attestation is old_attestation
    with pytest.raises(ca.HkCorporateActionError) as select_error:
        ca.select_hk_corporate_actions(projection=projection)
    _assert_clean_error(select_error.value, "HK_CA_EVIDENCE_INVALID")
    with pytest.raises(ca.HkCorporateActionError) as verify_error:
        ca.verify_hk_corporate_action_selection_result(
            result=result, projection=projection
        )
    _assert_clean_error(verify_error.value, "HK_CA_EVIDENCE_INVALID")


def test_process_attestation_is_redacted_and_not_serializable() -> None:
    projection, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    attestation = projection._attestation

    assert attestation is not None
    assert "digest" not in repr(attestation)
    assert repr(attestation) not in repr(projection)
    assert "_ATTESTATION_KEY" not in ca.__all__
    with pytest.raises(TypeError, match="process-local"):
        pickle.dumps(attestation)
    with pytest.raises(TypeError, match="process-local"):
        pickle.dumps(projection)


def test_module_reload_requires_fresh_source_verification() -> None:
    stale, _ = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    importlib.reload(ca)

    with pytest.raises(ca.HkCorporateActionError) as captured:
        ca.select_hk_corporate_actions(projection=stale)
    _assert_clean_error(captured.value, "HK_CA_EVIDENCE_INVALID")
    fresh, adapter = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    assert adapter.calls == 1
    assert ca.select_hk_corporate_actions(projection=fresh).actions.height == 3


@pytest.mark.parametrize("boundary", ["source", "selector", "result_verifier"])
def test_hostile_hmac_errors_are_reconstructed_without_secret_chain(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    projection, adapter = _projection(dt.datetime(2026, 5, 7, tzinfo=UTC))
    result = ca.select_hk_corporate_actions(projection=projection)

    def hostile(*args: object, **kwargs: object) -> bytes:
        del args, kwargs
        try:
            raise RuntimeError("SECRET_SENTINEL_HMAC")
        except RuntimeError:
            raise ca.HkCorporateActionError("HK_CA_EVIDENCE_INVALID")

    if boundary == "source":
        monkeypatch.setattr(ca.hmac, "digest", hostile)
    else:
        monkeypatch.setattr(ca.hmac, "compare_digest", hostile)

    def call() -> object:
        if boundary == "source":
            return ca.verify_hk_corporate_action_source(
                adapter=adapter, query=projection.query, bundle=projection.bundle
            )
        if boundary == "selector":
            return ca.select_hk_corporate_actions(projection=projection)
        return ca.verify_hk_corporate_action_selection_result(
            result=result, projection=projection
        )
    with pytest.raises(ca.HkCorporateActionError) as captured:
        call()
    _assert_clean_error(captured.value, "HK_CA_EVIDENCE_INVALID")
