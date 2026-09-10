"""Dated Shenwan membership intervals with version-specific parent mappings."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import polars as pl


_SWITCH = dt.date(2021, 12, 13)
_VERSIONS = {"SW2014": (dt.date(2014, 1, 1), _SWITCH), "SW2021": (_SWITCH, dt.date.max)}
_COLUMNS = {"symbol": pl.String, "valid_from": pl.Date, "valid_to": pl.Date,
            "industry_l1": pl.String, "industry_l2": pl.String, "industry_l3": pl.String}


def membership_intervals(
    taxonomy: pl.DataFrame, members: pl.DataFrame, *, as_of: dt.date,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Use [from, to), clamp version availability, and omit ambiguous intervals.

    2014 starts at classification launch; 2021 switches at the index migration.
    Exit dates are conservatively excluded, including Friday exits before a
    Monday migration. No classification is inferred before 2014 or after as_of.
    """
    parents: dict[tuple[str, str], dict[str, Any]] = {}
    by_index: dict[str, list[tuple[str, str, str, dt.date, dt.date]]] = defaultdict(list)
    for row in taxonomy.iter_rows(named=True):
        key = (row["src"], row["industry_code"])
        if key in parents:
            raise ValueError("Duplicate taxonomy code within one version")
        parents[key] = row
    for row in taxonomy.filter(pl.col("level") == "L3").iter_rows(named=True):
        version = row["src"]
        middle = parents[(version, row["parent_code"])]
        sector = parents[(version, middle["parent_code"])]
        if middle["level"] != "L2" or sector["level"] != "L1":
            raise ValueError("Broken taxonomy hierarchy")
        start, end = _VERSIONS[version]
        by_index[row["index_code"]].append((
            f"{version}:{sector['industry_code']}",
            f"{version}:{middle['industry_code']}",
            f"{version}:{row['industry_code']}", start, end,
        ))
    # Event counts permit duplicate/same-industry overlapping membership rows.
    events: dict[str, dict[dt.date, Counter[tuple[str, str, str]]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    excluded = 0
    for row in members.iter_rows(named=True):
        symbol = row["con_code"]
        if not isinstance(symbol, str) or not symbol.endswith((".SH", ".SZ")):
            excluded += 1
            continue
        if not row["in_date"] or (row["is_new"] == "N" and not row["out_date"]):
            excluded += 1
            continue
        entered = dt.datetime.strptime(row["in_date"], "%Y%m%d").date()
        exited = (dt.datetime.strptime(row["out_date"], "%Y%m%d").date()
                  if row["out_date"] else as_of + dt.timedelta(days=1))
        if exited <= entered:
            excluded += 1
            continue
        for l1, l2, l3, start, end in by_index.get(row["index_code"], []):
            left = max(start, entered)
            right = min(end, exited, as_of + dt.timedelta(days=1))
            if left < right:
                events[symbol][left][(l1, l2, l3)] += 1
                events[symbol][right][(l1, l2, l3)] -= 1

    output = []
    conflicts = 0
    conflict_symbols: set[str] = set()
    for symbol, changes in sorted(events.items()):
        active: Counter[tuple[str, str, str]] = Counter()
        dates = sorted(changes)
        for left, right in zip(dates, dates[1:], strict=False):
            active.update(changes[left])
            labels = [label for label, count in active.items() if count > 0]
            if len(labels) > 1:
                conflicts += (right - left).days
                conflict_symbols.add(symbol)
            elif len(labels) == 1:
                l1, l2, l3 = labels[0]
                output.append({"symbol": symbol, "valid_from": left, "valid_to": right,
                               "industry_l1": l1, "industry_l2": l2, "industry_l3": l3})
    return pl.DataFrame(output, schema=_COLUMNS), {
        "input_members": members.height, "excluded_members": excluded,
        "conflict_calendar_days": conflicts, "conflict_symbols": len(conflict_symbols),
        "output_intervals": len(output),
    }


def read_industry_raw(root: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Read a completed collector run, requiring terminal pages for each query."""
    taxonomy = pl.concat([
        pl.read_parquet(root / f"index_classify_{level}_{version}.parquet")
        for version in _VERSIONS for level in ("L1", "L2", "L3")
    ], how="vertical_relaxed")
    frames = []
    for code in taxonomy.filter(pl.col("level") == "L3")["index_code"].unique():
        for flag in ("Y", "N"):
            offset = 0
            while True:
                frame = pl.read_parquet(root / f"index_member_{code.replace('.', '_')}_{flag}_{offset}.parquet")
                if not frame.is_empty():
                    frames.append(frame)
                if frame.height < 2000:
                    break
                offset += frame.height
    return taxonomy, pl.concat(frames, how="vertical_relaxed")
