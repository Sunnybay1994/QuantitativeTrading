"""Persist complete annual cost-account chunks for explicit interrupted-run resume."""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
import uuid
import time

import polars as pl

OPTIONAL_STATE: dict[str, list | dict] = {"restricted_shares": [], "share_reduction_entitlements": {},
                  "share_distribution_entitlements": {}}
REQUIRED_STATE = {"date", "cash", "holdings", "receivables", "pending", "nav",
                  "inception_date", "started_with_cash", "cumulative_fees", *OPTIONAL_STATE}
KINDS = ("nav", "trades", "rejections")


def prepare_resume(*, output: Path, settings: dict, plans: dict, sessions: tuple[dt.date, ...],
                   data_root: Path, snapshot: str, factor: str, start: dt.date | None,
                   turnover_budgets: dict[str, float] | None, resume: bool) -> None:
    """Reuse only the same saved settings, target plans and execution snapshot."""
    context = {"version": 1, "settings": settings, "factor": factor, "snapshot": snapshot,
               "data_root": str(data_root.resolve()), "start": start,
               "sessions": sessions, "turnover_budgets": turnover_budgets or {},
               "names": {variant: name for variant, (name, _) in plans.items()}}
    content = json.dumps(context, default=str, sort_keys=True, allow_nan=False)
    path = output / "replay_config.json"
    if resume:
        if not path.is_file():
            raise ValueError("Old partial run lacks complete account checkpoints; retain it and use a new output")
        if json.loads(path.read_text(encoding="utf-8")) != json.loads(content):
            raise ValueError("Resume settings, calendar or execution snapshot changed")
        for variant, (_, targets) in plans.items():
            saved = pl.read_parquet(output / f"targets_{variant}.parquet")
            if not saved.equals(targets):
                raise ValueError("Resume target plan changed")
            inception = start if start is not None else targets["execution_date"].min()
            years = sorted({date.year for date in sessions if inception <= date <= settings["run"]["as_of"]})
            for multiplier in settings["portfolio"]["cost_multipliers"]:
                root = output / variant / f"cost_{multiplier:g}"
                existing = sorted(int(p.name) for p in root.glob("*") if p.is_dir() and p.name.isdigit())
                if existing != years[:len(existing)]:
                    raise ValueError("Checkpoint years contain a gap; retain partial output")
                if any(not (root / str(year) / "account.json").is_file() for year in existing):
                    raise ValueError("Old partial year lacks complete account state; retain it and use a new output")
    else:
        if path.exists() or any(output.glob("targets_*.parquet")):
            raise ValueError("Existing cost work requires explicit resume or a new output")
        for variant, (_, targets) in plans.items():
            targets.write_parquet(output / f"targets_{variant}.parquet")
        path.write_text(content, encoding="utf-8")


def read_year(folder: Path, *, dates: list[dt.date], previous: dict) -> tuple[dict, tuple]:
    path = folder / "account.json"
    if not path.is_file():
        raise ValueError("Old partial year lacks complete account state; retain it and use a new output")
    saved = json.loads(path.read_text(encoding="utf-8"))
    state = saved.get("account", {})
    if saved.get("version") != 1 or not REQUIRED_STATE.issubset(state):
        raise ValueError("Incomplete annual account checkpoint")
    chunks = tuple(pl.read_parquet(folder / f"{kind}.parquet") for kind in KINDS)
    nav = chunks[0]
    if (not dates or nav["date"].to_list() != dates or state["date"] != str(dates[-1])
            or state["nav"][:-len(dates)] != previous.get("nav", [])):
        raise ValueError("Annual checkpoint does not continue the saved account calendar")
    saved_nav = pl.from_dicts(state["nav"][-len(dates):], infer_schema_length=None).with_columns(
        pl.col("date").str.to_date())
    if not saved_nav.equals(nav) or state["cash"] != nav["cash"][-1]:
        raise ValueError("Annual account and NAV disagree")
    return state, chunks


def save_year(folder: Path, *, account: dict, chunks: tuple,
              target_records: list[dict]) -> None:
    """Publish a year only after all outputs and the complete state are written.

    Interrupted staging folders remain beside the published years and are never
    read as checkpoints. Resume recomputes that unfinished year in a new folder.
    """
    if folder.exists():
        raise ValueError("Completed annual output already exists")
    folder.parent.mkdir(parents=True, exist_ok=True)
    stage = folder.parent / f".{folder.name}-unfinished-{uuid.uuid4().hex}"
    stage.mkdir()
    state = copy.deepcopy(account)
    for key, empty in OPTIONAL_STATE.items():
        state.setdefault(key, empty)
    if not REQUIRED_STATE.issubset(state):
        raise ValueError("Replay did not return a complete account state")
    for kind, frame in zip(KINDS, chunks, strict=True):
        frame.write_parquet(stage / f"{kind}.parquet")
    if target_records:
        pl.from_dicts(target_records).write_parquet(stage / "budget_targets.parquet")
    (stage / "account.json").write_text(json.dumps({"version": 1, "account": state},
        allow_nan=False, ensure_ascii=False), encoding="utf-8")
    for attempt in range(4):
        try:
            stage.rename(folder)
            break
        except PermissionError:
            # Windows can briefly deny a just-written directory rename. Retry
            # only publication; never rerun the account or replace a target.
            if attempt == 3 or folder.exists() or not stage.is_dir():
                raise
            time.sleep((0.1, 0.3, 1.0)[attempt])
