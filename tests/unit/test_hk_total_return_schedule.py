"""Contract tests for the source-neutral HK total-return application schedule."""

from __future__ import annotations

import datetime as dt
import pickle
import traceback
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest

import quant.data.hk_total_return_schedule as schedule

UTC = dt.UTC
AS_OF = dt.datetime(2026, 5, 10, 12, tzinfo=UTC)
HEX = "a" * 64


def _action(
    *,
    event: str,
    symbol: str,
    action_type: str,
    ex_date: dt.date,
    currency: str | None = None,
) -> dict[str, Any]:
    is_dividend = action_type == "DIVIDEND"
    is_bonus = action_type == "BONUS"
    is_split = action_type == "SPLIT"
    is_rights = action_type == "RIGHTS"
    return {
        "event_id": event * 64,
        "symbol": symbol,
        "action_type": action_type,
        "source": "FIXTURE_OFFICIAL",
        "source_event_id": f"source-{event}",
        "source_revision_id": f"revision-{event}",
        "ex_date": ex_date,
        "pay_date": ex_date + dt.timedelta(days=5) if is_dividend else None,
        "stock_list_date": ex_date + dt.timedelta(days=2) if (is_bonus or is_split or is_rights) else None,
        "declared_currency": currency if (is_dividend or is_rights) else None,
        "cash_per_share_gross": 0.5 if is_dividend else None,
        "stock_ratio": 0.1 if is_bonus else None,
        "share_multiplier": 2.0 if is_split else None,
    }


def _context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    actions: list[dict[str, Any]] | None = None,
    future_availability: bool = False,
) -> schedule.HkTotalReturnFreshContext:
    rows = actions or [
        _action(
            event="1",
            symbol="00005.HK",
            action_type="BONUS",
            ex_date=dt.date(2026, 5, 5),
        ),
        _action(
            event="2",
            symbol="00005.HK",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 7),
            currency="HKD",
        ),
        _action(
            event="3",
            symbol="00005.HK",
            action_type="SPLIT",
            ex_date=dt.date(2026, 5, 7),
        ),
        _action(
            event="4",
            symbol="00005.HK",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 9),
            currency="HKD",
        ),
        _action(
            event="5",
            symbol="00700.HK",
            action_type="BONUS",
            ex_date=dt.date(2026, 5, 6),
        ),
    ]
    action_frame = pl.DataFrame(rows)
    evidence = pl.DataFrame(
        [
            {
                "event_id": row["event_id"],
                "symbol": row["symbol"],
                "action_type": row["action_type"],
                "source": row["source"],
                "source_event_id": row["source_event_id"],
                "source_revision_id": row["source_revision_id"],
                "implementation_status": "IMPLEMENTED",
                "implementation_effective_date": row["ex_date"] + dt.timedelta(days=1),
                "implementation_confirmed_at": AS_OF - dt.timedelta(hours=2),
                "source_observed_at": AS_OF - dt.timedelta(hours=1),
            }
            for row in rows
        ]
    )
    bar_rows: list[dict[str, Any]] = []
    availability_rows: list[dict[str, Any]] = []
    for symbol in sorted({row["symbol"] for row in rows}):
        for index, trade_date in enumerate(
            (dt.date(2026, 5, 5), dt.date(2026, 5, 6), dt.date(2026, 5, 8))
        ):
            bar_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "close": 10.0 + index,
                }
            )
            availability_rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "bar_available_at": (
                        AS_OF + dt.timedelta(seconds=1)
                        if future_availability and index == 2
                        else AS_OF - dt.timedelta(days=1)
                    ),
                    "availability_evidence_sha256": f"{index + 1:x}" * 64,
                }
            )
    implemented = SimpleNamespace(
        actions=action_frame,
        implementation_evidence=evidence,
        p0_query_sha256="b" * 64,
        p0_actions_content_sha256="c" * 64,
        p0_evidence_content_sha256="9" * 64,
        implementation_evidence_content_sha256="d" * 64,
        projection_sha256="e" * 64,
    )
    projection = SimpleNamespace(query=SimpleNamespace(as_of=AS_OF))
    p0_projection = SimpleNamespace(query=SimpleNamespace(as_of=AS_OF))
    bundle = SimpleNamespace(
        bars=pl.DataFrame(bar_rows),
        availability=pl.DataFrame(availability_rows),
        plan_sha256="f" * 64,
        publication_sha256=HEX,
    )
    history_plan = SimpleNamespace(plan_sha256="f" * 64)
    calls = {"implementation": 0, "bars": 0}

    def verify_implementation(**_kwargs: object) -> None:
        calls["implementation"] += 1

    def verify_bars(*_args: object, **_kwargs: object) -> None:
        calls["bars"] += 1

    monkeypatch.setattr(schedule, "verify_implemented_hk_corporate_action_set", verify_implementation)
    monkeypatch.setattr(schedule, "verify_hk_bar_bundle", verify_bars)
    context = schedule.HkTotalReturnFreshContext(
        implemented=implemented,  # type: ignore[arg-type]
        implementation_projection=projection,  # type: ignore[arg-type]
        p0_result=SimpleNamespace(),  # type: ignore[arg-type]
        p0_projection=p0_projection,  # type: ignore[arg-type]
        bar_bundle=bundle,  # type: ignore[arg-type]
        history_plan=history_plan,  # type: ignore[arg-type]
        journal_root=SimpleNamespace(),  # type: ignore[arg-type]
        seed_raw_root=SimpleNamespace(),  # type: ignore[arg-type]
        raw_store=SimpleNamespace(),  # type: ignore[arg-type]
        clean_root=SimpleNamespace(),  # type: ignore[arg-type]
        as_of=AS_OF,
    )
    return context


def test_schedule_maps_no_trade_date_and_binds_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(monkeypatch)
    plan = schedule.build_hk_total_return_application_plan(context=context)
    rows = plan.schedule
    assert rows.height == 5
    assert rows.get_column("event_id").to_list() == [f"{value}" * 64 for value in "12345"]
    assert rows.filter(pl.col("event_id") == "1" * 64).item(0, "window_disposition") == "BASELINE_PREWINDOW"
    for event in ("2", "3"):
        row = rows.filter(pl.col("event_id") == event * 64).row(0, named=True)
        assert row["window_disposition"] == "APPLY_IN_WINDOW"
        assert row["application_trade_date"] == dt.date(2026, 5, 8)
    assert rows.filter(pl.col("event_id") == "4" * 64).item(0, "window_disposition") == "OUTSIDE_FUTURE_WINDOW"
    schedule.verify_hk_total_return_application_plan(plan, context=context)
    assert plan.schedule is not rows
    with pytest.raises(TypeError):
        pickle.dumps(plan)


def test_input_shuffle_preserves_canonical_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _context(monkeypatch)
    plan_a = schedule.build_hk_total_return_application_plan(context=first)
    shuffled_rows = list(reversed(first.implemented.actions.to_dicts()))
    second = _context(monkeypatch, actions=shuffled_rows)
    plan_b = schedule.build_hk_total_return_application_plan(context=second)
    assert plan_a.plan_identity_sha256 == plan_b.plan_identity_sha256
    assert plan_a.schedule.equals(plan_b.schedule)


@pytest.mark.parametrize(
    "action",
    [
        _action(event="6", symbol="00005.HK", action_type="RIGHTS", ex_date=dt.date(2026, 5, 7), currency="HKD"),
        _action(event="7", symbol="00005.HK", action_type="DIVIDEND", ex_date=dt.date(2026, 5, 7), currency="CNY"),
    ],
)
def test_window_rights_and_cny_dividend_fail_closed(
    monkeypatch: pytest.MonkeyPatch, action: dict[str, Any]
) -> None:
    context = _context(monkeypatch, actions=[action])
    with pytest.raises(schedule.HkTotalReturnScheduleError, match="HK_TOTAL_RETURN_ACTION_UNSUPPORTED"):
        schedule.build_hk_total_return_application_plan(context=context)


def test_future_application_availability_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch, future_availability=True)
    with pytest.raises(schedule.HkTotalReturnScheduleError, match="HK_TOTAL_RETURN_INPUT_INVALID"):
        schedule.build_hk_total_return_application_plan(context=context)


def test_prewindow_cny_and_future_rights_are_bound_but_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions = [
        _action(
            event="6",
            symbol="00005.HK",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 5),
            currency="CNY",
        ),
        _action(
            event="7",
            symbol="00005.HK",
            action_type="RIGHTS",
            ex_date=dt.date(2026, 5, 9),
            currency="HKD",
        ),
    ]
    plan = schedule.build_hk_total_return_application_plan(
        context=_context(monkeypatch, actions=actions)
    )
    rows = plan.schedule.sort("event_id")
    assert rows.get_column("window_disposition").to_list() == [
        "BASELINE_PREWINDOW",
        "OUTSIDE_FUTURE_WINDOW",
    ]
    assert rows.get_column("application_trade_date").null_count() == 2
    assert rows.get_column("cash_per_share_gross_hkd").null_count() == 2


def test_ordinary_context_and_plan_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    with pytest.raises(schedule.HkTotalReturnScheduleError, match="HK_TOTAL_RETURN_INPUT_INVALID"):
        schedule.build_hk_total_return_application_plan(
            context=cast(schedule.HkTotalReturnFreshContext, SimpleNamespace())
        )
    with pytest.raises(schedule.HkTotalReturnScheduleError, match="HK_TOTAL_RETURN_VERIFY_FAILED"):
        schedule.verify_hk_total_return_application_plan(
            cast(schedule.VerifiedHkTotalReturnApplicationPlan, pl.DataFrame()),
            context=context,
        )


def test_hostile_public_verifier_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)

    def hostile(**_kwargs: object) -> None:
        raise RuntimeError("SECRET_PATH/TOKEN")

    monkeypatch.setattr(schedule, "verify_implemented_hk_corporate_action_set", hostile)
    with pytest.raises(schedule.HkTotalReturnScheduleError) as caught:
        schedule.build_hk_total_return_application_plan(context=context)
    error = caught.value
    rendered = "".join(traceback.format_exception(error))
    assert error.code == "HK_TOTAL_RETURN_INPUT_INVALID"
    assert error.__cause__ is None and error.__context__ is None
    assert "SECRET_PATH" not in rendered and "TOKEN" not in rendered


def test_fresh_rebuild_rejects_wholesale_resigned_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(monkeypatch)
    plan = schedule.build_hk_total_return_application_plan(context=context)
    tampered = plan.schedule.with_columns(
        pl.when(pl.col("event_id") == "2" * 64)
        .then(pl.lit(dt.date(2026, 5, 6)))
        .otherwise(pl.col("application_trade_date"))
        .alias("application_trade_date")
    )
    object.__setattr__(plan, "_schedule", tampered)
    object.__setattr__(plan, "schedule_content_sha256", schedule._payload_hash({"tampered": True}))
    object.__setattr__(plan, "plan_identity_sha256", schedule._payload_hash({"tampered-plan": True}))
    object.__setattr__(plan, "_attestation", schedule._attestation(plan))
    with pytest.raises(schedule.HkTotalReturnScheduleError, match="HK_TOTAL_RETURN_VERIFY_FAILED"):
        schedule.verify_hk_total_return_application_plan(plan, context=context)
