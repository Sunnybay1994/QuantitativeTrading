"""Reconstruct Connect buy eligibility from saved official SSE/SZSE tables.

The result is a reconstruction, not a contemporaneously archived historical list.
It assumes the official adjustment table contains all changes since the requested
start. Snapshot dates are the upper bound; eligibility is not a trading calendar.
"""

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.connect_market import (
    map_sse_events,
    map_sse_snapshot,
    map_szse_events,
    map_szse_snapshot,
)


def read_official_table(path: Path) -> pl.DataFrame:
    match = re.fullmatch(r"jsonpCallback\((.*)\)\s*", path.read_text(encoding="utf-8"), re.S)
    if match is None:
        raise ValueError("Expected the saved official SSE JSONP response")
    payload = json.loads(match.group(1))
    page = payload["pageHelp"]
    rows = page["data"]
    if not rows or len(rows) != int(page["total"]) or int(page["pageCount"]) != 1:
        raise ValueError("Incomplete SSE table; retrieve every page before reconstruction")
    return pl.DataFrame(rows)


def normalize_tables(
    snapshot_raw: pl.DataFrame, events_raw: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    if not snapshot_raw["TRADE_FLAG"].is_in(["1"]).fill_null(False).all():
        raise ValueError("Expected a buy-eligible snapshot, not a sell-only/holding list")
    snapshot = map_sse_snapshot(snapshot_raw)
    # The official page JS labels FILE_DATE as the table update date, not publication.
    events = map_sse_events(events_raw).rename({"published_date": "source_updated_date"})
    events = events.with_columns(pl.lit(None, dtype=pl.Date).alias("published_date"))
    if snapshot["snapshot_date"].n_unique() != 1:
        raise ValueError("Snapshot dates differ")
    for frame in (snapshot, events):
        if frame["symbol"].null_count() or not frame["symbol"].str.contains(r"^\d{5}\.HK$").all():
            raise ValueError("Invalid Hong Kong security code")
    if snapshot["symbol"].n_unique() != snapshot.height:
        raise ValueError("Duplicate snapshot symbol")
    if events.select("symbol", "effective_date").unique().height != events.height:
        raise ValueError("Duplicate or conflicting same-day adjustment")
    if events["effective_date"].null_count():
        raise ValueError("Missing event effective date")
    return snapshot, events.sort("effective_date", "symbol")


def read_szse_pages(root: Path, kind: str) -> pl.DataFrame:
    paths = sorted(root.glob(f"{kind}_???.json"))
    if not paths:
        raise ValueError("No saved SZSE pages")
    rows: list[dict[str, Any]] = []
    expected: tuple[int, int, str] | None = None
    for number, path in enumerate(paths, 1):
        report = json.loads(path.read_text(encoding="utf-8"))[0]
        metadata = report["metadata"]
        current = (int(metadata["pagecount"]), int(metadata["recordcount"]), metadata["subname"])
        if expected is None:
            expected = current
        if current != expected or int(metadata["pageno"]) != number:
            raise ValueError("SZSE pagination changed or pages are missing")
        rows.extend({**row, "_snapshot_date": metadata["subname"]} for row in report["data"])
    assert expected is not None
    if len(paths) != expected[0] or len(rows) != expected[1]:
        raise ValueError("Incomplete SZSE table")
    return pl.DataFrame(rows)


def normalize_szse(root: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    raw = read_szse_pages(root, "events")
    if not raw["tznr"].is_in(["调入", "调出"]).fill_null(False).all():
        raise ValueError("Unknown SZSE adjustment direction")
    snapshot = map_szse_snapshot(read_szse_pages(root, "snapshot"))
    events = map_szse_events(raw).with_columns(
        raw["_snapshot_date"].str.to_date().alias("source_updated_date"))
    for frame in (snapshot, events):
        if not frame["symbol"].str.contains(r"^\d{5}\.HK$").fill_null(False).all():
            raise ValueError("Invalid Hong Kong security code")
    if events["effective_date"].null_count():
        raise ValueError("Missing event effective date")
    if snapshot["symbol"].n_unique() != snapshot.height:
        raise ValueError("Duplicate snapshot symbol")
    if events.select("symbol", "effective_date").unique().height != events.height:
        raise ValueError("Duplicate or conflicting same-day adjustment")
    return snapshot, events.sort("effective_date", "symbol")


def reconstruct(
    snapshot: pl.DataFrame, events: pl.DataFrame, start: dt.date,
) -> pl.DataFrame:
    """Return inclusive date intervals, reversing additions/removals before replay."""
    end: dt.date = snapshot["snapshot_date"][0]
    if start > end or start < events["effective_date"].min():
        raise ValueError("Requested start falls outside the available adjustment history")
    if events["effective_date"].max() > end:
        raise ValueError("Events are newer than the snapshot")
    state = set(snapshot.filter(pl.col("buy_eligible"))["symbol"].to_list())
    all_symbols = sorted(state | set(events["symbol"].to_list()))
    changes = events.filter(pl.col("effective_date") > start).to_dicts()
    for event in reversed(changes):
        symbol, add = event["symbol"], event["action"] == "ADD"
        if (symbol in state) != add:
            raise ValueError(f"Snapshot/event contradiction: {event['effective_date']} {symbol}")
        if add:
            state.remove(symbol)
        else:
            state.add(symbol)
    opened = {symbol: start for symbol in all_symbols}
    rows: list[dict[str, Any]] = []

    def append(symbol: str, through: dt.date) -> None:
        rows.append({"route": snapshot["route"][0], "symbol": symbol,
            "valid_from": opened[symbol], "valid_to": through,
            "buy_eligible": symbol in state,
            "evidence_kind": "official_snapshot_and_events_reconstruction"})

    for event in changes:
        symbol, date = event["symbol"], event["effective_date"]
        append(symbol, date - dt.timedelta(days=1))
        opened[symbol] = date
        if event["action"] == "ADD":
            state.add(symbol)
        else:
            state.remove(symbol)
    for symbol in all_symbols:
        append(symbol, end)
    return pl.DataFrame(rows).sort("symbol", "valid_from")


def read_eligibility_intervals(data_root: Path, snapshot_id: str) -> pl.DataFrame:
    return pl.read_parquet(data_root / "clean/hk_connect_eligibility" / snapshot_id
                           / "route_eligibility_intervals.parquet")


def eligibility_on(intervals: pl.DataFrame, date: dt.date) -> pl.DataFrame:
    if not intervals["valid_from"].min() <= date <= intervals["valid_to"].max():
        raise ValueError("Date outside reconstructed coverage")
    return intervals.filter(pl.col("valid_from") <= date, pl.col("valid_to") >= date)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2023, 11, 1))
    parser.add_argument("--route", choices=("SH_CONNECT", "SZ_CONNECT"), default="SH_CONNECT")
    args = parser.parse_args()
    if args.route == "SH_CONNECT":
        snapshot, events = normalize_tables(read_official_table(args.raw / "snapshot.jsonp"),
                                             read_official_table(args.raw / "events.jsonp"))
    else:
        snapshot, events = normalize_szse(args.raw)
    intervals = reconstruct(snapshot, events, args.start)
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot.write_parquet(args.output / "snapshot.parquet")
    events.write_parquet(args.output / "events.parquet")
    intervals.write_parquet(args.output / "eligibility_intervals.parquet")
    summary = {"route": args.route, "coverage_start": str(args.start),
        "coverage_end": str(snapshot["snapshot_date"][0]),
        "snapshot_securities": snapshot.height, "events": events.height,
        "event_first_date": str(events["effective_date"].min()),
        "event_last_date": str(events["effective_date"].max()),
        "known_symbols": intervals["symbol"].n_unique(), "intervals": intervals.height,
        "start_buy_eligible": eligibility_on(intervals, args.start).filter("buy_eligible").height,
        "assumption": "Official exchange adjustment table has all changes since coverage_start; "
                      "dates are effective dates, not historical download/publication dates."}
    (args.output / "coverage.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
