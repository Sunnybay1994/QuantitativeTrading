import datetime as dt
import hashlib
import json
import os
import uuid

import polars as pl
import pytest

from quant.reporting import worklist_dated_observations as observed


def write(path, payload, at):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, pl.DataFrame):
        payload.write_csv(path)
    else:
        path.write_text(
            json.dumps(payload) if isinstance(payload, dict) else payload, encoding="utf-8"
        )
    os.utime(path, (at.timestamp(), at.timestamp()))


@pytest.fixture
def case(tmp_path):
    history = dict(enabled=True, truncated=False, error=None, events=[])

    def native(day, hour):
        instance = str(uuid.uuid4())
        base = len(history["events"])
        start = dt.datetime.combine(day, dt.time(hour), observed.SH)
        for kind, minute in [(107, 0), (201, 44), (102, 45)]:
            history["events"].append(
                dict(
                    task="\\" + observed.DAILY,
                    instance_id=instance,
                    event_id=kind,
                    record_id=base + len(history["events"]) + 1,
                    occurred_at=(start + dt.timedelta(minutes=minute)).isoformat(),
                    result=0 if kind == 201 else None,
                    action="powershell.exe" if kind == 201 else None,
                )
            )

    def daily(day):
        at = dt.datetime.combine(day, dt.time(21, 40), observed.SH)
        native(day, 21)
        folder = tmp_path / "artifacts/daily/sue_v2" / f"{day}_213000"
        summary = dict(
            status="complete",
            as_of=str(day),
            started_at=at.replace(minute=1).isoformat(),
            auto_trade=False,
            rehearsal=False,
            saved_data=False,
            stages={"q10": {"status": "complete"}},
            observation_accounts={"account_30w_top15": dict(status="complete", as_of=str(day))},
        )
        write(folder / "summary.json", summary, at)
        write(folder / "scheduler.json", dict(exit_code=0), at)
        return at

    signal = dt.date(2026, 11, 30)
    at = daily(signal)
    for name, folder in observed.ACCOUNTS.items():
        base = tmp_path / "artifacts/paper" / folder / str(signal)
        state = dict(date=str(signal), auto_trade=False)
        if name == "account_30w_top15":
            state.update(shadow=True, rehearsal=False)
        orders = pl.DataFrame(
            dict(
                as_of=[str(signal)] * 2,
                execution_date=["2026-12-01"] * 2,
                symbol=["600000.SH", "511010.SH"],
                quantity=[100, 100],
                asset_type=["STOCK", "ETF"],
                estimated_notional=[1000.0, 10000.0],
            )
        )
        write(base / "state.json", state, at)
        write(base / "orders.csv", orders, at)
        write(base / "orders.md", "paper", at)
    for day in [dt.date(2026, 12, 1), dt.date(2026, 12, 2)]:
        at = daily(day)
        base = tmp_path / "artifacts/paper" / observed.ACCOUNTS["account_30w_top15"] / str(day)
        write(
            base / "state.json",
            dict(date=str(day), auto_trade=False, shadow=True, rehearsal=False),
            at,
        )
        write(base / "nav.csv", pl.DataFrame(dict(date=[str(day)], unit_nav=[1.0])), at)
        write(base / "fills.csv", pl.DataFrame(dict(date=[str(day)], quantity=[100])), at)
    native(dt.date(2026, 12, 1), 8)
    at = dt.datetime(2026, 12, 1, 8, 35, tzinfo=observed.SH)
    root = tmp_path / "artifacts/paper" / observed.ACCOUNTS["account_30w_top15"]
    write(
        root / "manual_rehearsal_notification.json",
        dict(
            as_of=at.isoformat(),
            status="submitted",
            transport_accepted=True,
            auto_trade=False,
            orders_sha256=hashlib.sha256((root / "2026-11-30/orders.csv").read_bytes()).hexdigest(),
        ),
        at,
    )
    return tmp_path, history, dt.datetime(2026, 12, 3, tzinfo=observed.SH)


def test_future_files_are_not_accepted_before_actual_date(case):
    root, history, _ = case
    results = observed.evaluate(root, dt.datetime(2026, 11, 9, tzinfo=observed.SH), history)
    assert {r["status"] for r in results.values()} == {"pending_future"}


def test_matching_native_events_and_dated_products_verify_each_required_observation(case):
    root, history, clock = case
    results = observed.evaluate(root, clock, history)
    execution = ["k2_nov30_orders", "a2_dec1_fills", "a2_dec2_daily", "a2_dec1_notification"]
    assert {results[name]["status"] for name in execution} == {"verified"}
    assert (
        results["k2_nov30_orders"]["evidence"]["accounts"]["account_30w_top15"]["etf_orders"] == 1
    )
    assert results["a2_dec1_notification"]["evidence"]["delivery_read_by_user_verified"] is False


@pytest.mark.parametrize("change", ["manual", "unfinished", "nonzero", "disabled"])
def test_success_flags_without_complete_natural_zero_exit_events_cannot_pass(case, change):
    root, history, clock = case
    if change == "disabled":
        history["enabled"] = False
    elif change == "unfinished":
        history["events"] = [e for e in history["events"] if e["event_id"] != 102]
    else:
        for event in history["events"]:
            if change == "manual" and event["event_id"] == 107:
                event["event_id"] = 110
            if change == "nonzero" and event["event_id"] == 201:
                event["result"] = 1
    history["instances"] = [dict(natural_zero_exit=True, result=0)]
    assert {r["status"] for r in observed.evaluate(root, clock, history).values()} == {"unverified"}


@pytest.mark.parametrize(
    "change", ["late", "wrong_order_date", "rehearsal", "no_fills", "queued_notification"]
)
def test_daily_success_cannot_hide_missing_or_ineligible_account_outputs(case, change):
    root, history, clock = case
    base = root / "artifacts/paper" / observed.ACCOUNTS["account_30w_top15"]
    if change == "late":
        path = base / "2026-11-30/orders.csv"
        at = dt.datetime(2026, 11, 30, 22, 31, tzinfo=observed.SH)
        os.utime(path, (at.timestamp(), at.timestamp()))
        key = "k2_nov30_orders"
    elif change == "wrong_order_date":
        path = base / "2026-11-30/orders.csv"
        at = path.stat().st_mtime
        pl.read_csv(path).with_columns(pl.lit("2026-12-02").alias("execution_date")).write_csv(path)
        os.utime(path, (at, at))
        key = "k2_nov30_orders"
    elif change == "rehearsal":
        path = base / "2026-12-01/state.json"
        at = path.stat().st_mtime
        item = observed.read(path)
        item["rehearsal"] = True
        path.write_text(json.dumps(item))
        os.utime(path, (at, at))
        key = "a2_dec1_fills"
    elif change == "no_fills":
        path = base / "2026-12-01/fills.csv"
        at = path.stat().st_mtime
        pl.read_csv(path).clear().write_csv(path)
        os.utime(path, (at, at))
        key = "a2_dec1_fills"
    else:
        path = base / "manual_rehearsal_notification.json"
        at = path.stat().st_mtime
        item = observed.read(path)
        item["transport_accepted"] = False
        path.write_text(json.dumps(item))
        os.utime(path, (at, at))
        key = "a2_dec1_notification"
    assert observed.evaluate(root, clock, history)[key]["status"] == "unverified"
