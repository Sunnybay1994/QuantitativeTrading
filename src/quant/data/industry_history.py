"""Dated Shenwan membership intervals with version-specific parent mappings."""

from __future__ import annotations

import datetime as dt
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import polars as pl


_SWITCH = dt.date(2021, 8, 2)  # First session after the 2021-07-31 classification announcement.
_VERSIONS = {"SW2014": (dt.date(2014, 1, 1), _SWITCH), "SW2021": (_SWITCH, dt.date.max)}
_COLUMNS = {"symbol": pl.String, "valid_from": pl.Date, "valid_to": pl.Date,
            "industry_l1": pl.String, "industry_l2": pl.String, "industry_l3": pl.String}


def membership_intervals(
    taxonomy: pl.DataFrame, members: pl.DataFrame, *, as_of: dt.date,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Use [from, to), clamp version availability, and omit ambiguous intervals.

    2014 starts at classification launch; 2021 starts after its public announcement.
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
        if not isinstance(symbol, str) or not re.fullmatch(r"(?:6[0-9]{5}\.SH|[03][0-9]{5}\.SZ)", symbol):
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
            if row.get("source_version") and not l1.startswith(row["source_version"] + ":"):
                continue
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


def read_industry_raw(root: Path, *, with_current: bool = False,
                      historical_raw_root: Path | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Read a completed collector run, requiring terminal pages for each query."""
    taxonomy = pl.concat([
        pl.read_parquet(root / f"index_classify_{level}_{version}.parquet")
        for version in _VERSIONS for level in ("L1", "L2", "L3")
    ], how="vertical_relaxed")
    frames = []
    sources = (("index_member", "SW2014"), ("index_member_all", "SW2021")) if with_current else (("index_member", None),)
    for api, version in sources:
        member_root = historical_raw_root if api == 'index_member' and historical_raw_root else root
        categories = taxonomy.filter(pl.col("level") == "L3")
        if version is not None:
            categories = categories.filter(pl.col("src") == version)
        for code in categories["index_code"].unique():
            for flag in ("Y", "N"):
                offset = 0
                while True:
                    frame = pl.read_parquet(member_root / f"{api}_{code.replace('.', '_')}_{flag}_{offset}.parquet")
                    if not frame.is_empty():
                        if api == "index_member_all":
                            frame = frame.rename({"l3_code": "index_code", "ts_code": "con_code"})
                        frames.append(frame.select("index_code", "con_code", "in_date", "out_date", "is_new")
                                      .with_columns(pl.lit(version, dtype=pl.String).alias("source_version")))
                    if frame.height < 2000:
                        break
                    offset += frame.height
    return taxonomy, pl.concat(frames, how="vertical_relaxed")


def attach_industry(panel: pl.DataFrame, intervals: pl.DataFrame) -> pl.DataFrame:
    """Join an unambiguous classification at signal time, leaving history gaps null."""
    joined = panel.sort("symbol", "trade_date").join_asof(
        intervals.sort("symbol", "valid_from"), left_on="trade_date", right_on="valid_from",
        by="symbol", strategy="backward", check_sortedness=False,
    )
    return joined.with_columns(*[
        pl.when(pl.col("trade_date") < pl.col("valid_to")).then(pl.col(name)).alias(name)
        for name in ("industry_l1", "industry_l2", "industry_l3")
    ]).drop("valid_from", "valid_to")


def publish_industry_history(
    raw_root: Path, clean_root: Path, *, as_of: dt.date, with_current: bool = False,
    historical_raw_root: Path | None = None,
) -> dict[str, Any]:
    taxonomy, members = read_industry_raw(raw_root, with_current=with_current,
                                         historical_raw_root=historical_raw_root)
    intervals, stats = membership_intervals(taxonomy, members, as_of=as_of)
    if intervals.is_empty():
        raise ValueError("No dated A-share industry memberships")
    output = clean_root / dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    output.mkdir(parents=True, exist_ok=False)
    intervals.write_parquet(output / "intervals.parquet", compression="zstd")
    summary = {**stats, "as_of": str(as_of), "raw_root": str(raw_root), "with_current": with_current,
               "historical_raw_root": str(historical_raw_root or raw_root),
               "output": str(output), "symbols": intervals["symbol"].n_unique(),
               "versions": {key: str(bounds[0]) for key, bounds in _VERSIONS.items()},
               "exit_date": "exclusive; unknown and conflicting classifications remain null"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def refresh_daily(*, data_root: Path, end: dt.date) -> dict[str, Any]:
    """Refresh current memberships while reusing the closed SW2014 history."""
    from quant.data.collect_industry import collect_industry

    clean = data_root/'clean/tushare_industry'
    previous = None
    for path in sorted(clean.glob('*/summary.json'), reverse=True):
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('with_current'):
            previous = saved
            break
    if previous is None:
        raise ValueError('Publish both industry source versions before daily refresh')
    if dt.date.fromisoformat(previous['as_of']) >= end:
        return {'message': 'no-op', 'new_intervals': 0, 'as_of': previous['as_of'],
                'output': previous['output']}
    raw = data_root/'raw/tushare/industry'/f'daily_{end:%Y%m%d}'
    collected = collect_industry(raw, member_api='index_member_all')
    result = publish_industry_history(raw, clean, as_of=end, with_current=True,
        historical_raw_root=Path(previous.get('historical_raw_root', previous['raw_root'])))
    return {**result, 'message': 'updated', 'new_intervals': result['output_intervals'],
            'network_requests': collected['network_requests'],
            'rebuild_from': str(dt.date.fromisoformat(previous['as_of']) + dt.timedelta(days=1))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--clean-root", type=Path, default=Path("data/clean/tushare_industry"))
    parser.add_argument("--with-current", action="store_true", help="Use index_member_all for SW2021 memberships")
    args = parser.parse_args()
    print(json.dumps(publish_industry_history(args.raw_root, args.clean_root,
                                             as_of=args.as_of, with_current=args.with_current)))


if __name__ == "__main__":
    main()
