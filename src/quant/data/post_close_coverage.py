"""Coverage against the full pre-collection universe, including unattempted symbols."""

import datetime as dt
import json
import uuid
from pathlib import Path

from quant.data.realtime_store import atomic_json

THRESHOLDS = {"cn": 0.95, "hk": 0.90, "us": 0.90}
DEFAULT_BARS = {"cn": 240, "hk": 330, "us": 390}


def save_universe(output: Path, sessions: dict, symbols: list[str], targets: dict[str, int]) -> None:
    """Append a full-pool snapshot before applying probe limits or connecting to OpenD."""
    for market, session in sessions.items():
        suffixes = {"cn": (".SH", ".SZ"), "hk": (".HK",), "us": (".US",)}[market]
        members = {s: targets[s] for s in symbols if s.endswith(suffixes)}
        path = output / "universes" / f"date={session}" / market / f"{uuid.uuid4().hex}.json"
        atomic_json(path, {"date": str(session), "market": market, "expected_bars": members})


def write_coverage(output: Path) -> dict:
    # Same-day reruns can expand the denominator, never erase missing names by shrinking it.
    pools: dict[tuple[str, str], dict[str, int]] = {}
    for path in sorted((output / "universes").glob("date=*/*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        day, market = payload["date"], payload["market"]
        dt.date.fromisoformat(day)
        if market not in THRESHOLDS or not isinstance(payload["expected_bars"], dict):
            raise ValueError(f"Invalid coverage universe: {path}")
        pool = pools.setdefault((day, market), {})
        for symbol, bars in payload["expected_bars"].items():
            if not isinstance(bars, int) or bars <= 0:
                raise ValueError(f"Invalid expected bars in {path}")
            pool[symbol] = max(pool.get(symbol, 0), bars)

    receipts: dict[tuple[str, str], dict[str, dict]] = {}
    errors = []
    for path in sorted(output.glob("date=*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            day = path.parent.name.split("=", 1)[1]
            symbol = str(payload.get("symbol") or path.stem)
            # Legacy cache-hit receipts omitted market/ok; only a dated, successful
            # cache skip with a real symbol can be interpreted as complete.
            market = payload.get("market")
            if market is None:
                market = next((m for m, suffixes in (
                    ("cn", (".SH", ".SZ")), ("hk", (".HK",)), ("us", (".US",))
                ) if symbol.endswith(suffixes)), None)
            if market not in THRESHOLDS:
                continue
            receipts.setdefault((day, market), {})[symbol] = payload
        except (OSError, ValueError, TypeError) as exc:
            errors.append({"path": str(path), "error": str(exc)})

    rows = []
    for day, market in sorted(set(pools) | set(receipts)):
        found = receipts.get((day, market), {})
        declared = pools.get((day, market))
        members = declared if declared is not None else {
            symbol: int(p.get("expected_bars") or DEFAULT_BARS[market]) for symbol, p in found.items()
        }
        complete = partial = missing = 0
        for symbol, target in members.items():
            p = found.get(symbol, {})
            bars = int(p.get("session_bars") or 0)
            dated = p.get("as_of", day) == day
            success = p.get("ok") is True or (p.get("skipped") is True and p.get("as_of") == day)
            if dated and success and bars >= target:
                complete += 1
            elif dated and bars > 0:
                partial += 1
            else:
                missing += 1
        expected = len(members)
        rows.append({"date": day, "market": market, "expected": expected, "complete": complete,
                     "partial": partial, "missing": missing,
                     "complete_rate": complete / expected if expected else 0.0,
                     "denominator_verified": declared is not None and expected > 0,
                     "denominator_basis": "pre_collection_pool" if declared is not None else "receipts_only",
                     "outside_pool": len(set(found) - set(members))})
    lines = ["# post-close K_1M coverage", "",
             "| date | market | expected | complete | partial | missing | complete_rate | denominator |",
             "|---|---|---:|---:|---:|---:|---:|---|"]
    for row in rows:
        lines.append(f"| {row['date']} | {row['market']} | {row['expected']} | {row['complete']} | "
                     f"{row['partial']} | {row['missing']} | {row['complete_rate']:.1%} | "
                     f"{row['denominator_basis']} |")
    lines.extend(["", "Complete bars: cn 240, hk 330 (half day 150), us 390 (early close 210).",
                  "receipts_only: full expected universe is unverified; not D1 acceptance evidence."])
    output.mkdir(parents=True, exist_ok=True)
    (output / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {"rows": rows, "thresholds": THRESHOLDS, "errors": errors}
    atomic_json(output / "coverage.json", summary)
    return summary
