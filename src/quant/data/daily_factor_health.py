"""Join existing daily/raw readers to descriptive factor-health logging."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import tomllib
from typing import Any

import polars as pl

from quant.data.daily_factor_health_inputs import (
    read_daily_health_factor,
    read_daily_health_universe,
)
from quant.data.factor_health_inputs import (
    read_factor_health_inputs,
    read_factor_health_month_ends,
    read_factor_health_selection,
)
from quant.reporting.factor_health import HealthParameters, diagnose_factor_health
from quant.reporting.run_factor_health import _flat, reference_start


def run_daily_factor_health(
    *, data_root: Path, refresh_config: Path, health_config: Path, as_of: dt.date,
    output: Path,
) -> dict[str, Any]:
    """Publish a new diagnostic log; input failures propagate to the public caller.

    The current panel is the actual as_of eligible pool. References use only
    frozen completed month ends in the preceding calendar-month window. Missing
    current raw values remain missing, including monthly factors off month-end.
    No value, threshold, admission decision or refresh success flag is changed.
    """
    if output.exists():
        raise FileExistsError("Choose a new daily-factor-health output directory")
    if type(as_of) is not dt.date:
        raise ValueError("Daily factor health requires a date cutoff")
    settings = tomllib.loads(health_config.read_text(encoding="utf-8"))
    scope = settings["diagnostics"]
    months, maximum = scope["reference_months"], scope["maximum_factors"]
    if (scope.get("diagnostics_only") is not True or type(months) is not int or months < 1
            or type(maximum) is not int or not 1 <= maximum <= 20):
        raise ValueError("Daily factor health requires diagnostics-only scope and at most 20 factors")
    parameters = HealthParameters(**settings["statistics"])
    if parameters.minimum_reference_months > months:
        raise ValueError("Reference requirement exceeds the fixed reference window")
    statistics, battery_config = Path(scope["statistics"]), Path(scope["battery_config"])
    plan = read_factor_health_selection(selection=Path(scope["selection"]), as_of_dates=[as_of],
        max_factors=maximum, replacements=settings.get("replacements", {}))
    if plan.is_empty():
        raise ValueError("No annually selected factors for the daily diagnostic")
    universe = read_daily_health_universe(data_root=data_root, refresh_config=refresh_config,
        battery_config=battery_config, as_of=as_of)
    if (not {"symbol", "trade_date", "eligible"} <= set(universe.columns)
            or universe.schema["eligible"] != pl.Boolean or universe["eligible"].null_count()
            or universe["trade_date"].null_count()
            or universe.filter(pl.col("trade_date") != as_of).height
            or universe.select("symbol", "trade_date").is_duplicated().any()):
        raise ValueError("Daily health universe requires unique same-day keys and explicit eligibility")
    eligible = universe.filter(pl.col("eligible")).select("symbol", "trade_date").sort("symbol")
    start = reference_start(as_of, months)
    end = as_of.replace(day=1) - dt.timedelta(days=1)
    reference_dates = read_factor_health_month_ends(data_root=data_root, statistics=statistics,
        start=start, end=end)
    if not reference_dates:
        raise ValueError("No frozen historical month ends for the daily diagnostic")
    records: list[dict[str, Any]] = []
    no_finite: list[str] = []
    for selected in plan.sort("factor").iter_rows(named=True):
        factor_id = selected["factor_id"]
        current = read_daily_health_factor(data_root=data_root, factor_id=factor_id,
            universe=universe, as_of=as_of)
        current_keys = current.select("symbol", "trade_date").sort("symbol")
        if not current_keys.equals(eligible):
            raise ValueError(f"Daily raw factor panel does not retain the eligible pool: {factor_id}")
        reference = read_factor_health_inputs(data_root=data_root, statistics=statistics,
            factor_id=factor_id, as_of_dates=reference_dates)
        diagnostic = diagnose_factor_health(current, reference, as_of=as_of, parameters=parameters)
        status_counts = {row["raw_value_status"]: row["len"] for row in
            current.group_by("raw_value_status").len().iter_rows(named=True)}
        record = {**selected, **diagnostic, "diagnostics_only": True,
            "reference_start": start, "reference_end": end,
            "raw_status_counts": {key: status_counts.get(key, 0) for key in
                ("observed", "null_value", "nonfinite_value", "missing_row", "missing_partition")}}
        json.dumps(record, allow_nan=False, default=str)
        records.append(record)
        if diagnostic["counts"]["finite"] == 0:
            no_finite.append(factor_id)
    summary = {"as_of": as_of.isoformat(), "factor_count": len(records),
        "current_eligible_symbols": eligible["symbol"].n_unique(),
        "measured_factors": len(records) - len(no_finite), "no_finite_factors": len(no_finite),
        "no_finite_factor_ids": sorted(no_finite), "output": str(output),
        "diagnostics_only": True, "reference_start": start.isoformat(), "reference_end": end.isoformat(),
        "selection": scope["selection"], "statistics": str(statistics),
        "factor_replacements": settings.get("replacements", {})}
    flat = pl.from_dicts([_flat(record) for record in records], infer_schema_length=None).with_columns(
        pl.col("as_of").str.to_date()).sort("factor")
    health_jsonl = "\n".join(json.dumps(record, ensure_ascii=False, allow_nan=False, default=str)
                             for record in records) + "\n"
    summary_json = json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2)
    output.mkdir(parents=True, exist_ok=False)
    universe.write_parquet(output / "current_universe.parquet")
    flat.write_parquet(output / "health.parquet")
    (output / "health.jsonl").write_text(health_jsonl, encoding="utf-8")
    (output / "summary.json").write_text(summary_json, encoding="utf-8")
    return summary
