import datetime as dt
import hashlib
import uuid

import polars as pl
import pytest

from quant.reporting import worklist_dated_observations as observed
from quant.reporting import worklist_period_reports as reports
from tests.unit import test_worklist_dated_observations as base

case = base.case


@pytest.fixture
def periods(case):
    root, history, clock = case
    days = [
        dt.date(2026, 9, 30),
        dt.date(2026, 10, 30),
        dt.date(2026, 11, 2),
        dt.date(2026, 11, 30),
        dt.date(2026, 12, 1),
    ]
    nav = pl.DataFrame(dict(date=days, unit_nav=[1.0, 0.9, 0.91, 0.95, 0.96]))
    calendar = root / "data/clean/trade_calendar/market=SH/data.parquet"
    calendar.parent.mkdir(parents=True)
    pl.DataFrame(dict(date=days, is_open=[True] * len(days))).write_parquet(calendar)
    for day in [dt.date(2026, 11, 2), dt.date(2026, 12, 1)]:
        at = dt.datetime.combine(day, dt.time(21, 40), observed.SH)
        folder = (
            root
            / "artifacts/daily/sue_v2"
            / ("2026-11-03_120000" if day.month == 11 else f"{day}_213000")
        )
        if day.month == 11:
            at = at + dt.timedelta(days=1)
            base.write(
                folder / "summary.json",
                dict(
                    as_of=str(day),
                    status="incomplete",
                    auto_trade=False,
                    rehearsal=False,
                    saved_data=False,
                ),
                at,
            )
            base.write(folder / "scheduler.json", dict(exit_code=1), at)
        source = root / "artifacts/paper/q10_sue_v2" / str(day)
        base.write(source / "state.json", dict(date=str(day), auto_trade=False), at)
        base.write(source / "nav.csv", nav.filter(pl.col("date") <= day), at)
        base.write(
            folder / "q10_monthly/summary.json",
            dict(as_of=str(day), status="recorded", auto_trade=False),
            at,
        )
        month = "2026-10" if day.month == 11 else "2026-11"
        value = -0.1 if day.month == 11 else 0.95 / 0.9 - 1
        base.write(
            folder / "q10_monthly/forward_monthly.csv",
            pl.DataFrame(dict(month=[month], complete_month=[True], observed_return=[value])),
            at,
        )
        base.write(folder / "q10_monthly/report.md", "real account monthly", at)
    day = dt.date(2026, 11, 27)
    at = dt.datetime(2026, 11, 27, 22, 10, tzinfo=observed.SH)
    formal = {
        "q10": {"state.json": "0" * 64},
        "q10_shadow": {"state.json": "1" * 64},
        "account_30w_top15": {},
    }
    item = dict(
        target=str(day),
        observed_at=at.isoformat(),
        finished_at=at.isoformat(),
        status="complete",
        rehearsal=True,
        auto_trade=False,
        pushed=False,
        formal_unchanged=True,
        formal_before=formal,
        formal_after=formal,
        accounts={},
        artifact_hashes={},
    )
    for name in observed.ACCOUNTS:
        output = root / "rehearsal" / name
        orders = pl.DataFrame(
            dict(
                as_of=[str(day)],
                execution_date=["2026-11-30"],
                quantity=[100],
                symbol=["600000.SH"],
            )
        )
        base.write(output / "latest_orders.csv", orders, at)
        item["accounts"][name] = dict(status="complete", output=str(output))
        item["artifact_hashes"][name] = {
            "latest_orders.csv": hashlib.sha256(
                (output / "latest_orders.csv").read_bytes()
            ).hexdigest()
        }
    base.write(root / "artifacts/paper/dated_rehearsal/rehearsal/2026-11-27/receipt.json", item, at)
    base.write(
        root / "artifacts/paper/dated_rehearsal/scheduler/native.log.json",
        dict(target=str(day), exit_code=0, rehearsal=True, auto_trade=False),
        at,
    )
    instance = str(uuid.uuid4())
    record = max(e["record_id"] for e in history["events"]) + 1
    for index, (kind, minute) in enumerate([(107, 0), (201, 19), (102, 20)]):
        history["events"].append(
            dict(
                task="\\QuantitativeTrading-DatedPaperRehearsal-20261127",
                instance_id=instance,
                event_id=kind,
                record_id=record + index,
                occurred_at=at.replace(minute=minute).isoformat(),
                result=0 if kind == 201 else None,
                action="powershell.exe" if kind == 201 else None,
            )
        )
    return root, history, clock


def test_natural_rehearsal_and_two_distinct_actual_months_are_verified(periods):
    root, history, clock = periods
    result = observed.evaluate(root, clock, history)
    assert {r["status"] for r in result.values()} == {"verified"}
    first = result["q10_second_monthly"]["evidence"]["first"]
    assert first["parent_daily_status"] == "incomplete" and first["scheduler_exit_code"] == 1
    assert (
        result["q10_second_monthly"]["evidence"]["first_natural_scheduler_success_claimed"] is False
    )


@pytest.mark.parametrize("change", ["nan", "wrong_return", "wrong_mode"])
def test_monthly_labels_cannot_replace_actual_nav_and_mode(periods, change):
    root, _, clock = periods
    folder = root / "artifacts/daily/sue_v2/2026-11-03_120000/q10_monthly"
    if change == "wrong_mode":
        parent = observed.read(folder.parent / "summary.json")
        parent["rehearsal"] = True
        base.write(folder.parent / "summary.json", parent, clock - dt.timedelta(days=1))
    else:
        path = folder / "forward_monthly.csv"
        pl.read_csv(path).with_columns(
            pl.lit(float("nan") if change == "nan" else 0.8).alias("observed_return")
        ).write_csv(path)
    with pytest.raises(ValueError):
        reports.real_month(root, folder, "2026-10", clock)


def test_changed_rehearsal_product_is_not_accepted_even_with_native_zero_exit(periods):
    root, history, clock = periods
    (root / "rehearsal/q10/latest_orders.csv").write_text("modified")
    assert observed.evaluate(root, clock, history)["k2_nov27_rehearsal"]["status"] == "unverified"
