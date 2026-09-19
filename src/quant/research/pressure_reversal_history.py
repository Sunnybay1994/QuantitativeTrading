"""Resumable label-free full-history coverage for the fixed reversal battery."""
from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_inputs
from quant.data.industry_history import attach_industry
from quant.data.refresh_stocks import TABLES
from quant.factors.expressions import evaluate_expressions, required_history
from quant.factors.library import load_library
from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.pressure_reversal_readiness import expression_key, profile


def digest(path: Path) -> str:
    before = path.stat()
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Input changed while hashing: {path}")
    return checksum.hexdigest()


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def month_ends(sessions: tuple[dt.date, ...], start: dt.date, end: dt.date) -> list[dt.date]:
    months = {}
    for day in sessions:
        if start <= day <= end:
            months[day.strftime("%Y-%m")] = day
    return sorted(months.values())


def input_files(data_root: Path, refresh: dict, reference: Path,
                start: dt.date, end: dt.date, *, universe_start: dt.date | None = None) -> list[Path]:
    files = [data_root / f"clean/trade_calendar/market={market}/data.parquet" for market in ("SH", "SZ")]
    roots = [data_root / "clean/tushare_bulk/snapshots" / refresh["stock_snapshot"] / "bar_1d/asset=stock",
             data_root / "clean/tushare_daily_basic/snapshots" / refresh["daily_basic_snapshot"]]
    for year in range(start.year, end.year + 1):
        for root in roots:
            partitions = sorted((root / f"year={year}").glob("*.parquet"))
            # Incremental-only years may have no historical partition.
            files.extend(partitions)
        if year >= (universe_start or start).year:
            files.append(reference / "inputs" / str(year) / "universe.parquet")
    for folder in sorted((data_root / "clean/tushare_incremental").glob("date=*")):
        if (str(start) <= folder.name[5:] <= str(end)
                and all((folder / f"{table}.parquet").is_file() for table in TABLES)):
            files.extend(folder / f"{table}.parquet" for table in TABLES)
    return sorted(set(files))


def monthly_coverage(values: pl.DataFrame, universe: pl.DataFrame,
                     settings: dict, expected: list[dt.date]) -> tuple[list[dict], pl.DataFrame]:
    """Count input sufficiency, never paired-label coverage or valid IC months."""
    rows, score_parts = [], []
    for identifier in values["candidate_id"].unique().sort().to_list():
        subset = values.filter(pl.col("candidate_id") == identifier).rename({"ts_code": "symbol"})
        scored = score_factor_sections(universe=universe, values=subset, direction=1, settings=settings)
        score_parts.append(scored.with_columns(pl.lit(identifier).alias("candidate_id")))
        eligible = universe.filter(pl.col("eligible")).group_by("trade_date").len()
        counts = scored.group_by("trade_date").agg(
            *[pl.col(name).is_finite().sum().alias(name) for name in settings["variants"]])
        by_date = {row["trade_date"]: row for row in counts.join(eligible, on="trade_date", how="left").to_dicts()}
        for day in expected:
            count = by_date.get(day, {})
            for variant in settings["variants"]:
                finite = count.get(variant, 0)
                rows.append({"candidate_id": identifier, "trade_date": str(day), "variant": variant,
                             "eligible_symbols": count.get("len", 0), "finite_symbols": finite,
                             "input_sufficient": finite >= settings["minimum_symbols"]})
    return rows, pl.concat(score_parts)


def completed_year(folder: Path) -> dict | None:
    receipt = folder / "summary.json"
    if not receipt.exists():
        return None
    result = json.loads(receipt.read_text(encoding="utf-8"))
    for name, checksum in result["output_hashes"].items():
        if digest(folder / name) != checksum:
            raise ValueError(f"Completed readiness output changed: {folder / name}")
    return result


def run_history(config: Path, output: Path, *, reference: Path, battery_config: Path,
                resume: bool = False) -> dict:
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    if settings["stage"] != "input_readiness_only" or settings["enqueue"] or settings["auto_trade"]:
        raise ValueError("Full-history readiness cannot enqueue or trade")
    if output.exists() and not resume:
        raise FileExistsError(output)
    if resume and not (output / "manifest.json").is_file():
        raise ValueError("Resume requires a completed frozen input manifest")
    output.mkdir(parents=True, exist_ok=resume)
    if not resume:
        for source, name in ((config, "config.toml"), (Path(settings["refresh_config"]), "refresh_config.toml"),
                             (battery_config, "battery.toml")):
            (output / name).write_bytes(source.read_bytes())
    elif digest(config) != digest(output / "config.toml"):
        raise ValueError("Cannot resume with a changed candidate specification")
    battery = tomllib.loads((output / "battery.toml").read_text(encoding="utf-8"))
    root = Path(settings["data_root"])
    start, end = map(dt.date.fromisoformat, (settings["history_start"], settings["history_end"]))
    if settings["direction"] != 1:
        raise ValueError("The frozen reversal readiness direction must remain +1")
    if resume:
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        for path, checksum in manifest["inputs"].items():
            if digest(Path(path)) != checksum:
                raise ValueError(f"Frozen readiness input changed: {path}")
        industry_path = Path(manifest["industry_path"])
    else:
        publications = sorted((root / "clean/tushare_industry").glob("*/summary.json"), reverse=True)
        publication = next(p for p in publications if json.loads(p.read_text(encoding="utf-8"))["with_current"])
        industry_path = publication.parent / "intervals.parquet"
    sessions = available_sessions(root, end)
    expressions = {r["id"]: r["expr"] for r in settings["candidates"] + settings["controls"]}
    warmup = max(required_history(expr) for expr in expressions.values())
    read_start = sessions[max(0, bisect.bisect_left(sessions, start) - warmup)]
    inputs = input_files(root, tomllib.loads((output / "refresh_config.toml").read_text()), reference,
                         read_start, end, universe_start=start)
    inputs += [industry_path, *[output / name for name in ("config.toml", "refresh_config.toml", "battery.toml")]]
    code_root = Path(__file__).resolve().parents[1]
    inputs += sorted((code_root / "factors").rglob("*.py"))
    inputs += [code_root / name for name in ("data/factor_panels.py", "data/industry_history.py",
               "data/refresh_stocks.py", "research/pressure_reversal_history.py",
               "research/pressure_reversal_readiness.py", "research/factor_battery_evaluation.py",
               "research/factor_battery_statistics.py")]
    definitions = load_library(Path(settings["library"]))
    library = [{"id": d.id, "expr": d.expr, "direction": d.direction} for d in definitions]
    candidate_manifest = {"inputs": {str(p.resolve()): digest(p) for p in inputs},
                          "industry_path": str(industry_path), "library": library,
                          "start": str(start), "end": str(end), "reference": str(reference.resolve())}
    if resume and candidate_manifest != manifest:
        raise ValueError("Readiness inputs or library changed; use a new run directory")
    manifest = candidate_manifest
    save_json(output / "manifest.json", manifest)
    intervals = pl.read_parquet(industry_path)
    expected = month_ends(sessions, start, end)
    annual = []
    for year in range(start.year, end.year + 1):
        folder = output / "years" / str(year)
        prior = completed_year(folder) if folder.exists() else None
        if prior:
            annual.append(prior)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        save_json(output / "progress.json", {"status": "running", "current_year": year,
                  "completed_years": [x["year"] for x in annual], "updated_at": dt.datetime.now().isoformat()})
        low, high = max(start, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
        padded = sessions[max(0, bisect.bisect_left(sessions, low) - warmup)]
        panel, bars = read_factor_inputs(root, output / "refresh_config.toml", padded, high, sessions)
        panel = attach_industry(panel, intervals)
        dates = [day for day in expected if low <= day <= high]
        values = evaluate_expressions(panel, expressions).filter(pl.col("trade_date").is_in(dates))
        values = values.join(bars.select("symbol", "trade_date"), on=["symbol", "trade_date"], how="semi")
        values = values.rename({"symbol": "ts_code"}).unpivot(
            on=list(expressions), index=["trade_date", "ts_code"], variable_name="candidate_id", value_name="value")
        universe = pl.read_parquet(reference / "inputs" / str(year) / "universe.parquet").filter(
            pl.col("trade_date").is_in(dates)).select("symbol", "trade_date", "eligible", "total_market_value", "industry_l1")
        if set(universe["trade_date"].unique()) != set(dates):
            raise ValueError(f"Frozen universe lacks expected month ends: {year}")
        counts, scores = monthly_coverage(values, universe, battery, dates)
        values.write_parquet(folder / "monthly_values.parquet")
        universe.write_parquet(folder / "universe.parquet")
        scores.write_parquet(folder / "monthly_scores.parquet")
        result = {"year": year, **profile(panel, bars, expressions, low, high), "monthly": counts,
                  "output_hashes": {name: digest(folder / name) for name in
                      ("monthly_values.parquet", "universe.parquet", "monthly_scores.parquet")}}
        save_json(folder / "summary.json", result)
        annual.append(result)
        print(json.dumps({"year": year, "completed_years": len(annual), "stock_days": result["observed_stock_days"]}), flush=True)
    for path, checksum in manifest["inputs"].items():
        if digest(Path(path)) != checksum:
            raise ValueError(f"Input changed during readiness: {path}")
    current_files = input_files(root, tomllib.loads((output / "refresh_config.toml").read_text()), reference,
                                read_start, end, universe_start=start)
    if not {str(p.resolve()) for p in current_files} <= set(manifest["inputs"]):
        raise ValueError("Additional input partitions appeared during readiness; use a new run directory")
    for name in ("monthly_values.parquet", "universe.parquet", "monthly_scores.parquet"):
        pl.concat([pl.read_parquet(output / "years" / str(row["year"]) / name) for row in annual]).write_parquet(output / name)
    monthly = [month for row in annual for month in row["monthly"]]
    counts = [{"candidate_id": identifier, "variant": variant,
               "input_sufficient_months": sum(r["input_sufficient"] for r in monthly
                    if r["candidate_id"] == identifier and r["variant"] == variant)}
              for identifier in expressions for variant in battery["variants"]]
    result = {"conclusion": "FULL_HISTORY_INPUT_DIAGNOSTIC_ONLY", "generated_at": dt.datetime.now().isoformat(),
              "start": str(start), "end": str(end), "expected_months": len(expected),
              "minimum_symbols": battery["minimum_symbols"], "minimum_months": battery["admission"]["minimum_months"],
              "input_months": counts, "years": annual, "library_count": len(definitions),
              "exact_ast_duplicates": {r["id"]: [d.id for d in definitions if expression_key(d.expr) == expression_key(r["expr"])]
                                       for r in settings["candidates"]},
              "return_labels_read": False, "queued": False, "auto_trade": False,
              "limitations": ["Input-sufficient months are not valid IC months: paired future-label coverage remains unevaluated",
                              "Industry history before 2014 is unavailable; no backfill from future membership",
                              "Full-history input coverage does not establish signal novelty, predictive power or cost-adjusted returns",
                              "Dated industry revisions are not independently PIT verified; volume-price data cannot prove absence of news"]}
    save_json(output / "summary.json", result)
    lines = ["# Pressure reversal full-history input coverage", "", f"{start} through {end}; {len(expected)} month ends. No labels read or candidates queued.", "",
             "| Candidate/control | Variant | Months with sufficient inputs |", "|---|---|---:|"]
    lines += [f"| {r['candidate_id']} | {r['variant']} | {r['input_sufficient_months']} |" for r in counts]
    lines += ["", *[f"- {line}" for line in result["limitations"]]]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_json(output / "progress.json", {"status": "complete", "completed_years": [r["year"] for r in annual],
                                         "updated_at": dt.datetime.now().isoformat(), "summary": str(output / "summary.json")})
    return result
