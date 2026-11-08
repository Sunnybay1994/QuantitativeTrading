"""Read dated K2/A2 outputs against native time-triggered scheduler events."""

import datetime as dt
import hashlib
import json

import polars as pl

from quant.reporting.doctor_scheduler import normalize_events

SH = dt.timezone(dt.timedelta(hours=8))
DAILY = "QuantitativeTrading-DailyObservation"
ACCOUNTS = {
    "q10": "q10_sue_v2",
    "q10_shadow": "q10_size_neutral_shadow",
    "account_30w_top15": "account_30w_top15_v1",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stamp(value):
    result = dt.datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Naive receipt timestamp")
    return result


def native_match(history, task, day, clock, paths):
    if (
        not history
        or history.get("enabled") is not True
        or history.get("truncated")
        or history.get("error")
    ):
        raise ValueError("Complete native scheduler history unavailable")
    # Recompute from native event records; do not trust an edited success flag.
    for row in normalize_events(history.get("events", [])):
        if row["task"].lstrip("\\") != task or not row["natural_zero_exit"]:
            continue
        start, end = stamp(row["start_time"]), stamp(row["last_event_time"])
        if start.astimezone(SH).date() != day or end > clock:
            continue
        if all(start.timestamp() <= p.stat().st_mtime <= end.timestamp() for p in paths):
            return dict(
                task=task,
                instance_id=row["instance_id"],
                record_ids=row["record_ids"],
                started_at=row["start_time"],
                finished_at=row["last_event_time"],
            )
    raise ValueError("No matching completed time-triggered zero-exit instance for these files")


def daily_record(root, day, clock, history):
    issues = []
    for path in sorted((root / "artifacts/daily/sue_v2").glob("*/summary.json"), reverse=True):
        try:
            item = read(path)
            if item.get("as_of") != str(day):
                continue
            if item.get("status") != "complete" or any(
                item.get(k) is not False for k in ("rehearsal", "saved_data", "auto_trade")
            ):
                raise ValueError("Daily completion or actual-data mode invalid")
            if stamp(item["started_at"]).astimezone(SH).date() != day:
                raise ValueError("Delayed recording cannot establish the target-day scheduled run")
            if not item.get("stages") or any(
                v.get("status") != "complete" for v in item["stages"].values()
            ):
                raise ValueError("Daily stages incomplete")
            execution = path.parent / "scheduler.json"
            code = read(execution).get("exit_code")
            if type(code) is not int or code != 0:
                raise ValueError("Daily process did not exit zero")
            match = native_match(history, DAILY, day, clock, [path, execution])
            if (
                not stamp(match["started_at"])
                <= stamp(item["started_at"])
                <= stamp(match["finished_at"])
            ):
                raise ValueError("Daily start does not belong to the native instance")
            return item, path, match
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(str(exc))
    raise ValueError("; ".join(dict.fromkeys(issues)) or "No target-day daily receipt")


def signal_orders(root, clock, history):
    day = dt.date(2026, 11, 30)
    _, _, native = daily_record(root, day, clock, history)
    counts = {}
    deadline = dt.datetime(2026, 11, 30, 22, 30, tzinfo=SH)
    for name, folder in ACCOUNTS.items():
        base = root / "artifacts/paper" / folder / str(day)
        paths = [base / "state.json", base / "orders.csv", base / "orders.md"]
        state = read(paths[0])
        if state.get("date") != str(day) or state.get("auto_trade") is not False:
            raise ValueError(f"{name}: invalid formal signal state")
        if name == "account_30w_top15" and (
            state.get("rehearsal") is not False or state.get("shadow") is not True
        ):
            raise ValueError("A2 signal is a rehearsal or not shadow-only")
        orders = pl.read_csv(paths[1])
        if not {"as_of", "execution_date", "symbol", "quantity"} <= set(orders.columns):
            raise ValueError(f"{name}: order schema missing")
        if set(orders["as_of"]) - {str(day)} or set(orders["execution_date"]) - {"2026-12-01"}:
            raise ValueError(f"{name}: wrong order dates")
        if any(p.stat().st_mtime > deadline.timestamp() for p in paths):
            raise ValueError(f"{name}: signal orders were not ready before 22:30")
        native_match(history, DAILY, day, clock, paths)
        counts[name] = dict(
            orders=orders.height,
            orders_sha256=hashlib.sha256(paths[1].read_bytes()).hexdigest(),
            signal_day_orders=str(paths[1]),
        )
        if name == "account_30w_top15":
            counts[name].update(
                stock_orders=orders.filter(pl.col("asset_type") == "STOCK").height,
                etf_orders=orders.filter(pl.col("asset_type") == "ETF").height,
                estimated_notional=orders["estimated_notional"].sum(),
            )
    return dict(native=native, accounts=counts)


def account_day(root, day, clock, history):
    item, path, native = daily_record(root, day, clock, history)
    observation = item.get("observation_accounts", {}).get("account_30w_top15", {})
    if observation.get("status") != "complete" or observation.get("as_of") != str(day):
        raise ValueError("A2 observation did not complete in the actual daily run")
    base = root / "artifacts/paper" / ACCOUNTS["account_30w_top15"] / str(day)
    state = read(base / "state.json")
    if (
        state.get("date") != str(day)
        or state.get("auto_trade") is not False
        or state.get("rehearsal") is not False
        or state.get("shadow") is not True
    ):
        raise ValueError("A2 dated formal state invalid")
    products = [base / "state.json", base / "nav.csv", base / "fills.csv"]
    native_match(history, DAILY, day, clock, products)
    fills = pl.read_csv(base / "fills.csv")
    if day == dt.date(2026, 12, 1) and fills.is_empty():
        raise ValueError("December 1 simulated fills have not occurred")
    if set(fills["date"]) - {str(day)}:
        raise ValueError("A2 fills from another session")
    return dict(
        native=native,
        daily=str(path),
        fills=fills.height,
        state_sha256=hashlib.sha256(products[0].read_bytes()).hexdigest(),
    )


def notification(root, clock, history):
    day = dt.date(2026, 12, 1)
    base = root / "artifacts/paper" / ACCOUNTS["account_30w_top15"]
    path = base / "manual_rehearsal_notification.json"
    receipt = read(path)
    sent = stamp(receipt["as_of"]).astimezone(SH)
    if (
        sent.date() != day
        or not dt.time(8, 30) <= sent.time() < dt.time(9, 30)
        or receipt.get("status") != "submitted"
        or receipt.get("transport_accepted") is not True
        or receipt.get("auto_trade") is not False
    ):
        raise ValueError("Preopen accepted transport receipt missing")
    if dt.datetime.fromtimestamp(path.stat().st_mtime, SH).time() >= dt.time(9, 30):
        raise ValueError("Notification completion was after preopen window")
    orders = base / "2026-11-30/orders.csv"
    if hashlib.sha256(orders.read_bytes()).hexdigest() != receipt["orders_sha256"]:
        raise ValueError("Notification does not match frozen signal orders")
    return dict(
        native=native_match(history, DAILY, day, clock, [path]),
        transport_accepted=True,
        delivery_read_by_user_verified=False,
        orders_sha256=receipt["orders_sha256"],
    )


def evaluate(root, clock, history=None):
    from quant.reporting.worklist_period_reports import rehearsal, second_monthly

    targets = {
        "k2_nov27_rehearsal": (dt.date(2026, 11, 27), lambda: rehearsal(root, clock, history)),
        "k2_nov30_orders": (dt.date(2026, 11, 30), lambda: signal_orders(root, clock, history)),
        "a2_dec1_fills": (
            dt.date(2026, 12, 1),
            lambda: account_day(root, dt.date(2026, 12, 1), clock, history),
        ),
        "a2_dec2_daily": (
            dt.date(2026, 12, 2),
            lambda: account_day(root, dt.date(2026, 12, 2), clock, history),
        ),
        "a2_dec1_notification": (dt.date(2026, 12, 1), lambda: notification(root, clock, history)),
        "q10_second_monthly": (dt.date(2026, 12, 1), lambda: second_monthly(root, clock, history)),
    }
    results = {}
    for name, (day, operation) in targets.items():
        if clock.astimezone(SH).date() < day:
            results[name] = dict(status="pending_future", target_date=str(day))
            continue
        try:
            results[name] = dict(status="verified", target_date=str(day), evidence=operation())
        except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
            results[name] = dict(status="unverified", target_date=str(day), issue=str(exc))
    return results
