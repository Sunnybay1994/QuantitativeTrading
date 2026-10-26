"""Registry path guard, Q10 canonical rows, and size-on turnover repair."""

from __future__ import annotations

import json
import os
from pathlib import Path

import polars as pl

Q10_MARKERS = (
    "r1_q10_calendar",
    "r1_q10_rolling",
    "r4_constrained_q10",
    "q10_sue_v2_turnover",
    "q10-sue-v2-turnover",
)
_TURNOVER = ((0.5, "0_5x"), (1.0, "1x"), (2.0, "2x"))


def registry_file(default: Path, explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    override = os.environ.get("QUANT_REGISTRY_ROOT")
    return Path(override) if override else default


def outside_repository(run_path: str, root: Path) -> bool:
    path = Path(run_path)
    if not path.is_absolute():
        path = root / path
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False


def canonical_id(row: dict) -> str:
    blob = f"{row.get('run_path', '')} {row.get('experiment_id', '')}".replace("\\", "/").lower()
    variant = str(row.get("variant") or "")
    if any(marker in blob for marker in Q10_MARKERS):
        return "q10_sue_v2"
    return f"{row.get('experiment_id')}|{variant}"


def _primary_key(row: dict) -> tuple:
    path = str(row.get("run_path", "")).replace("\\", "/").lower()
    return (
        row.get("conclusion") == "PAPER_CANDIDATE",
        "r1_q10_calendar" in path,
        str(row.get("result_time") or ""),
    )


def collapse_duplicate_keys(rows: list[dict]) -> list[dict]:
    """One row per experiment_id+variant. Conclusion of the kept row is unchanged."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row.get("experiment_id"), row.get("variant")), []).append(row)
    kept = []
    for group in groups.values():
        primary = dict(max(group, key=_primary_key))
        aliases = [str(row.get("run_path")) for row in group if row.get("run_path") != primary.get("run_path")]
        primary["aliases"] = "|".join(aliases)
        primary["canonical_id"] = canonical_id(primary)
        kept.append(primary)
    return kept


def board_rows(rows: list[dict]) -> list[dict]:
    """One displayed row per canonical id. Other run paths stay in aliases."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(canonical_id(row), []).append(row)
    shown = []
    for cid, group in groups.items():
        primary = dict(max(group, key=_primary_key))
        extra = [str(row.get("run_path")) for row in group if row.get("run_path") != primary.get("run_path")]
        prior = [part for part in str(primary.get("aliases") or "").split("|") if part]
        primary["aliases"] = "|".join(dict.fromkeys([*prior, *extra]))
        primary["canonical_id"] = cid
        shown.append(repair_size_on_turnover(primary))
    return shown


def repair_size_on_turnover(row: dict) -> dict:
    """size_on assessments stored 0 after a calendar median wiped the summary figure."""
    path = Path(str(row.get("run_path") or ""))
    if "size_on" not in path.as_posix():
        return row
    summary = path / "summary.json"
    if not summary.is_file():
        return row
    try:
        payload = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return row
    by_cost = {item.get("cost_multiplier"): item for item in payload.get("rows") or []}
    updated = dict(row)
    for multiplier, suffix in _TURNOVER:
        key = f"turnover_{suffix}"
        current = updated.get(key)
        if current not in (0, 0.0, None):
            continue
        value = (by_cost.get(multiplier) or {}).get("annualized_one_way_turnover")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            updated[key] = float(value)
    return updated


def quarantine_outside(registry: Path, quarantine: Path, root: Path) -> dict:
    frame = pl.read_parquet(registry)
    rows = frame.to_dicts()
    keep, bad = [], []
    for row in rows:
        (bad if outside_repository(str(row.get("run_path")), root) else keep).append(row)
    kept = [repair_size_on_turnover(row) for row in collapse_duplicate_keys(keep)]
    quarantine.parent.mkdir(parents=True, exist_ok=True)
    if bad:
        pl.from_dicts(bad, infer_schema_length=None).write_parquet(quarantine)
    else:
        pl.DataFrame().write_parquet(quarantine)
    temporary = registry.with_suffix(".parquet.tmp")
    pl.from_dicts(kept, infer_schema_length=None).write_parquet(temporary)
    temporary.replace(registry)
    note = quarantine.with_suffix(".json")
    note.write_text(json.dumps({
        "quarantine_rows": len(bad),
        "kept_rows": len(kept),
        "quarantine": str(quarantine),
    }, indent=2), encoding="utf-8")
    return {"quarantine_rows": len(bad), "kept_rows": len(kept)}
