"""P7 text-versus-library redundancy using one shared statistical window."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import datetime as dt
import json
import math
import os
from pathlib import Path
import tomllib

import polars as pl

from quant.factors.forecast_text_score import DIMENSIONS
from quant.factors.library import FactorDefinition, load_library
from quant.research.factor_battery_redundancy import (
    correlation_maxima, monthly_rank_correlation, summarize_correlation,
)

TEXT_LIBRARY = Path(__file__).resolve().parents[3] / "configs/factors/p7_text_library"


def _same_icir(left: float | None, right: float | None) -> bool:
    def clean(value: float | None) -> float | None:
        if value is None or math.isnan(value):
            return None
        if not math.isfinite(value):
            raise ValueError("Infinite ICIR cannot order redundancy peers")
        return value

    return clean(left) == clean(right)


def _validate_statistics(root: Path, definitions: list[FactorDefinition], settings: dict) -> tuple[pl.DataFrame, set]:
    table = pl.read_parquet(root / "statistics.parquet")
    expected = {(d.id, variant) for d in definitions for variant in settings["variants"]}
    if (not {"factor", "variant", "icir"}.issubset(table.columns)
            or table.height != len(expected) or set(table.select("factor", "variant").rows()) != expected):
        raise ValueError("Requires complete unique registered factor/variant statistics")
    dates = set()
    for definition in definitions:
        folder = root / "factors" / definition.id
        scores, report = folder / "monthly_scores.parquet", folder / "statistics.json"
        if not scores.is_file() or not report.is_file():
            raise ValueError(f"Incomplete statistical artifacts: {definition.id}")
        saved = json.loads(report.read_text(encoding="utf-8"))
        rows = saved.get("statistics", [])
        if (saved.get("definition") != asdict(definition) or len(rows) != len(settings["variants"])
                or {row["variant"] for row in rows} != set(settings["variants"])):
            raise ValueError(f"Saved factor definition or variant statistics changed: {definition.id}")
        for row in rows:
            icir = table.filter((pl.col("factor") == definition.id) & (pl.col("variant") == row["variant"]))["icir"][0]
            if not _same_icir(icir, row["icir"]):
                raise ValueError("Aggregate ICIR disagrees with its saved factor statistics")
        scan = pl.scan_parquet(scores)
        schema = scan.collect_schema()
        if not {"trade_date", "symbol", *settings["variants"]}.issubset(schema.names()) or schema["trade_date"] != pl.Date:
            raise ValueError("Monthly score schema is incomplete")
        factor_dates = set(scan.select("trade_date").unique().collect()["trade_date"])
        if any(date is None or not settings["start"] <= date <= settings["run"]["as_of"] for date in factor_dates):
            raise ValueError("Monthly scores fall outside the shared P7 window")
        dates.update(factor_dates)
    return table.select("factor", "variant", pl.col("icir").cast(pl.Float64)), dates


def _compare_text(statistics: Path, left: str, others: list[tuple[str, Path]], settings: dict,
                  window_months: list[str]) -> list[dict]:
    columns = ["trade_date", "symbol", *settings["variants"]]
    first = pl.read_parquet(statistics / "factors" / left / "monthly_scores.parquet", columns=columns)
    rows = []
    for right, root in others:
        second = pl.read_parquet(root / "factors" / right / "monthly_scores.parquet", columns=columns)
        for variant in settings["variants"]:
            monthly = monthly_rank_correlation(first, second, variant=variant,
                                               minimum_symbols=settings["minimum_symbols"])
            valid_months = {date.strftime("%Y-%m") for date in monthly.filter(
                pl.col("rank_correlation").is_not_null())["trade_date"]}
            missing = [month for month in window_months if month not in valid_months]
            rows.append({"left": left, "right": right, "variant": variant,
                **summarize_correlation(monthly, minimum_months=settings["admission"]["minimum_months"]),
                "window_months": len(window_months), "observed_months": monthly.height,
                "missing_month_count": len(missing), "missing_months": missing,
                "below_minimum_symbols_months": monthly.filter(
                    pl.col("common_symbols") < settings["minimum_symbols"]).height})
    return rows


def run_redundancy(*, statistics: Path, peer_statistics: Path, peer_library: Path,
                   output: Path, workers: int) -> dict:
    """Compare only text-involving pairs; publish maxima only for the three texts."""
    config = (statistics / "battery.toml").read_bytes()
    settings = tomllib.loads(config.decode("utf-8"))
    peer_settings = tomllib.loads((peer_statistics / "battery.toml").read_text(encoding="utf-8"))
    if settings != peer_settings:
        raise ValueError("Text and peer battery settings must match, including start and as_of")
    if (workers < 1 or settings["run"]["selected"] != "all" or settings["start"] != dt.date(2017, 1, 1)
            or settings["run"]["as_of"] < settings["start"]
            or len(settings["variants"]) != 2 or set(settings["variants"]) != {"raw", "size_industry_neutral"}
            or settings["primary_variant"] != "size_industry_neutral"
            or settings["minimum_symbols"] != 100 or settings["admission"]["minimum_months"] != 96
            or settings["admission"]["maximum_absolute_rank_correlation_with_better"] != .7):
        raise ValueError("Requires complete all-factor runs under the frozen P7 window and thresholds")
    texts = load_library(TEXT_LIBRARY, "all")
    peers = load_library(peer_library, "all")
    expected_texts = {f"text_{name}": direction for name, direction in zip(DIMENSIONS, (1, -1, -1), strict=True)}
    if ({d.id: d.direction for d in texts} != expected_texts
            or any(d.expr != d.id or d.family != "forecast_text" for d in texts)):
        raise ValueError("Requires all three frozen text definitions")
    text_ids, peer_ids = sorted(d.id for d in texts), sorted(d.id for d in peers)
    if set(text_ids) & set(peer_ids):
        raise ValueError("Text and peer factor IDs overlap")
    text_table, text_dates = _validate_statistics(statistics, texts, settings)
    peer_table, peer_dates = _validate_statistics(peer_statistics, peers, settings)
    dates = text_dates | peer_dates
    if len({date.strftime("%Y-%m") for date in dates}) != len(dates):
        raise ValueError("Monthly scores must share a single signal date per calendar month")
    end = settings["run"]["as_of"]
    months = [f"{year:04d}-{month:02d}" for year in range(2017, end.year + 1) for month in range(1, 13)
              if (year, month) <= (end.year, end.month)]
    output.mkdir(parents=True, exist_ok=False)
    jobs = [(statistics, left, [(right, peer_statistics) for right in peer_ids]
             + [(right, statistics) for right in text_ids[index + 1:]], settings, months)
            for index, left in enumerate(text_ids)]
    rows = []
    if workers == 1:
        for job in jobs:
            rows.extend(_compare_text(*job))
    else:
        os.environ["POLARS_MAX_THREADS"] = "4"
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            futures = [pool.submit(_compare_text, *job) for job in jobs]
            for future in futures:
                rows.extend(future.result())
    pairs = pl.from_dicts(rows, infer_schema_length=None).sort("left", "right", "variant")
    combined = pl.concat([text_table, peer_table])
    maxima = correlation_maxima(pairs, combined, settings=settings).filter(pl.col("factor").is_in(text_ids))
    ordering = combined.filter(pl.col("variant") == settings["primary_variant"]).with_columns(
        pl.col("icir").fill_nan(None)).sort(["icir", "factor"], descending=[True, False], nulls_last=True)
    ranks = ordering.select("factor").with_row_index("comparison_primary_rank")
    maxima = maxima.join(ranks, on="factor", how="left", validate="m:1")
    pairs.write_parquet(output / "pairwise_correlations.parquet")
    maxima.write_parquet(output / "correlation_maxima.parquet")
    (output / "battery.toml").write_bytes(config)
    result = {"text_factors": text_ids, "peer_factors": peer_ids, "start": str(settings["start"]), "as_of": str(end),
        "statistics": str(statistics.resolve()), "peer_statistics": str(peer_statistics.resolve()),
        "scope": "each_text_vs_all_registered_peers_and_other_texts; no_peer_vs_peer_comparisons",
        "maxima_scope": "three_text_factors_only", "ordering": "combined_same_window_primary_icir_then_factor_id",
        "window_months": len(months), "minimum_symbols": 100, "minimum_months": 96,
        "maximum_absolute_rank_correlation_with_better": .7,
        "pair_variant_rows": pairs.height, "qualified_pair_variant_rows": pairs["comparison_qualified"].sum(),
        "unqualified_pair_variant_rows": pairs.filter(~pl.col("comparison_qualified")).height,
        "maxima_variant_rows": maxima.height, "redundant_variant_rows": maxima["redundant_with_higher"].sum(),
        "missing_months": "pair rows list all window months without finite correlation at >=100 common stocks; never zero-filled",
        "unqualified_pairs": "excluded from maxima; null maxima mean no qualified comparison, not evidence of independence"}
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
