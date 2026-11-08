"""Specific November rehearsal and Q10 monthly evidence used by doctor."""

import datetime as dt
import hashlib
import math
from pathlib import Path

import polars as pl

from quant.reporting.worklist_dated_observations import (
    ACCOUNTS,
    DAILY,
    SH,
    daily_record,
    native_match,
    read,
    stamp,
)


def rehearsal(root, clock, history):
    day = dt.date(2026, 11, 27)
    path = root / "artifacts/paper/dated_rehearsal/rehearsal" / str(day) / "receipt.json"
    item = read(path)
    if (
        item.get("target") != str(day)
        or item.get("status") != "complete"
        or item.get("rehearsal") is not True
        or item.get("auto_trade") is not False
        or item.get("pushed") is not False
        or item.get("formal_unchanged") is not True
        or set(item.get("formal_before", {})) != set(ACCOUNTS)
        or item["formal_before"] != item.get("formal_after")
    ):
        raise ValueError("Three-account isolated rehearsal receipt invalid")
    if stamp(item["observed_at"]).astimezone(SH).date() != day:
        raise ValueError("Historical rehearsal cannot establish November 27 execution")
    if stamp(item["finished_at"]) > dt.datetime(2026, 11, 27, 22, 30, tzinfo=SH):
        raise ValueError("November 27 rehearsal completed after 22:30")
    counts = {}
    if not item["formal_before"]["q10"] or not item["formal_before"]["q10_shadow"]:
        raise ValueError("Original formal account baselines missing")
    for name in ACCOUNTS:
        account = item["accounts"][name]
        if account.get("status") != "complete":
            raise ValueError("Rehearsal account incomplete")
        output = Path(account["output"])
        output = (output if output.is_absolute() else root / output).resolve()
        if not output.is_relative_to(root.resolve()) or "rehearsal" not in output.parts:
            raise ValueError("Rehearsal output outside isolated project directory")
        hashes = item["artifact_hashes"][name]
        if not hashes:
            raise ValueError("Rehearsal hashes missing")
        for relative, digest in hashes.items():
            product = (output / relative).resolve()
            if (
                not product.is_relative_to(output)
                or hashlib.sha256(product.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("Rehearsal artifact changed")
        orders = pl.read_csv(output / "latest_orders.csv")
        if set(orders["as_of"]) - {str(day)} or set(orders["execution_date"]) - {"2026-11-30"}:
            raise ValueError("Rehearsal order dates incorrect")
        counts[name] = orders.height
    task = "QuantitativeTrading-DatedPaperRehearsal-20261127"
    for launcher in (root / "artifacts/paper/dated_rehearsal/scheduler").glob("*.log.json"):
        record = read(launcher)
        if (
            record.get("target") == str(day)
            and record.get("rehearsal") is True
            and record.get("auto_trade") is False
            and type(record.get("exit_code")) is int
            and record["exit_code"] == 0
        ):
            native = native_match(history, task, day, clock, [path, launcher])
            if (
                not stamp(native["started_at"])
                <= stamp(item["observed_at"])
                <= stamp(item["finished_at"])
                <= stamp(native["finished_at"])
            ):
                raise ValueError("Rehearsal times do not belong to native instance")
            return dict(
                native=native,
                orders=counts,
                formal_sha_unchanged=True,
            )
    raise ValueError("Native rehearsal launcher zero-exit receipt missing")


def real_month(root, folder, month, clock):
    summary = read(folder / "summary.json")
    day = dt.date.fromisoformat(summary["as_of"])
    parent = read(folder.parent / "summary.json")
    if (
        summary.get("status") != "recorded"
        or summary.get("auto_trade") is not False
        or parent.get("as_of") != str(day)
        or any(parent.get(k) is not False for k in ("rehearsal", "saved_data", "auto_trade"))
    ):
        raise ValueError("Monthly report does not come from an actual formal account run")
    state = root / "artifacts/paper/q10_sue_v2" / str(day)
    if read(state / "state.json").get("auto_trade") is not False:
        raise ValueError("Invalid source account")
    nav = pl.read_csv(state / "nav.csv", try_parse_dates=True).with_columns(
        pl.col("date").cast(pl.Date)
    )
    calendar = pl.read_parquet(root / "data/clean/trade_calendar/market=SH/data.parquet")
    sessions = sorted(calendar.filter(pl.col("is_open"))["date"].to_list())
    dates = [d for d in sessions if d.strftime("%Y-%m") == month]
    if not dates or max(dates) > day or day > clock.astimezone(SH).date():
        raise ValueError("Month incomplete")
    if nav["date"].is_duplicated().any() or nav["date"].max() != day:
        raise ValueError("Invalid dated source NAV")
    prior = max(d for d in sessions if d < min(dates))
    part = nav.filter(pl.col("date").is_in(dates)).sort("date")
    if set(part["date"]) != set(dates):
        raise ValueError("Incomplete real monthly NAV coverage")
    base = nav.filter(pl.col("date") == prior)["unit_nav"].item()
    if not math.isfinite(base) or base == 0:
        raise ValueError("Invalid monthly NAV boundary")
    expected = part["unit_nav"][-1] / base - 1
    row = pl.read_csv(folder / "forward_monthly.csv").filter(pl.col("month") == month)
    if (
        row.height != 1
        or row["complete_month"].item() is not True
        or not math.isfinite(expected)
        or not math.isfinite(row["observed_return"].item())
        or abs(row["observed_return"].item() - expected) > 1e-12
    ):
        raise ValueError("Monthly report disagrees with actual account NAV")
    if any(
        p.stat().st_mtime > clock.timestamp()
        for p in [folder / "summary.json", folder / "report.md"]
    ):
        raise ValueError("Monthly report not yet observable")
    return dict(
        month=month,
        as_of=str(day),
        actual_return=expected,
        observed_points=len(dates),
        report=str(folder / "report.md"),
        parent_daily_status=parent.get("status"),
        scheduler_exit_code=read(folder.parent / "scheduler.json").get("exit_code"),
    )


def second_monthly(root, clock, history):
    day = dt.date(2026, 12, 1)
    _, path, native = daily_record(root, day, clock, history)
    folder = path.parent / "q10_monthly"
    second = real_month(root, folder, "2026-11", clock)
    native_match(
        history,
        DAILY,
        day,
        clock,
        [folder / name for name in ["summary.json", "report.md", "forward_monthly.csv"]],
    )
    for source in sorted((root / "artifacts/daily/sue_v2").glob("*/q10_monthly/summary.json")):
        try:
            if read(source).get("as_of") != "2026-11-02":
                continue
            first = real_month(root, source.parent, "2026-10", clock)
            return dict(
                native=native,
                first=first,
                second=second,
                first_natural_scheduler_success_claimed=False,
            )
        except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError):
            continue
    raise ValueError("First actual October Q10 monthly report not verified")
