"""Report payload assembly for classic factor runs."""

from __future__ import annotations

import datetime as dt
import io
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import polars as pl

from quant.research.lightweight_run import canonical_json_bytes
from quant.research.run_classic_factors_admission import _SIXTH_BATCH_CATALOG

def _report(
    *,
    config: Mapping[str, Any],
    snapshot_id: str,
    snapshot_manifest_sha256: str,
    candidates: tuple[str, ...],
    panel: pl.DataFrame,
    results: Mapping[str, pl.DataFrame],
    summary: pl.DataFrame,
    conclusion: str,
) -> dict[str, object]:
    caveats = [
        "The 2019 liquid universe is PIT at its freeze date but is not an "
        "evolving historical constituent universe.",
        "Historical ST flags, industry membership and authoritative suspension "
        "facts are unavailable in this snapshot.",
        "Missing exact next-session opens produce null labels and are never forward-filled.",
        "The non-overlapping 20-session portfolio is a factor diagnostic, not "
        "the formal A-share account replay.",
        "Minimum commission uses one million CNY; order-book impact and capacity "
        "are not estimated.",
        "Minute, L2 and fundamental factors are not approximated with daily bars.",
        "No result from this run may exceed RESEARCH_ONLY without separate forward "
        "and market-event admission evidence.",
    ]
    if "market_risk" in config:
        caveats.extend(
            [
                "The registered negative direction is a defensive low-beta/BAB-style "
                "hypothesis, not a claim that the classic downside-risk premium "
                "predicts a negative return relation.",
                "Downside-beta evidence is mixed in the literature; direction, "
                "coverage, redundancy and exact rebalance-schedule gates are "
                "therefore fail-closed.",
            ]
        )
    if cast(Mapping[str, Any], config["factors"]).get("catalog") == (
        "alpha158_fourth_batch_v1"
    ):
        caveats.extend(
            [
                "RESI20, IMXD20 and VSUMD20 have no pre-registered permanent "
                "cross-sectional sign; each fold freezes its sign on validation only.",
                "Missing exchange-session observations invalidate rolling windows; "
                "coverage, redundancy and exact rebalance-schedule gates are fail-closed.",
            ]
        )
    if cast(Mapping[str, Any], config["factors"]).get("catalog") == (
        "max_lottery_fifth_batch_v1"
    ):
        caveats.extend(
            [
                "MAX is the greatest signed daily adjusted-close return over twenty "
                "sessions, not absolute return and not Qlib Alpha158 Max(high,20)/close.",
                "The economic direction is pre-registered at -1; validation may reject "
                "that direction but cannot reverse the tested portfolio.",
                "A historical pass would still require daily-basic size and turnover "
                "controls before forward observation.",
                "This primary MAX gate does not close PIT symmetric redundancy coverage, "
                "audit-v4, R3 or any trading Gate.",
            ]
        )
    if cast(Mapping[str, Any], config["factors"]).get("catalog") == (
        _SIXTH_BATCH_CATALOG
    ):
        caveats.extend(
            [
                "Alpha101 #006 and #012 use adjusted open/close with raw volume; "
                "Alpha101 #041 intentionally remains raw CNY/share versus amount/volume.",
                "The three price-volume candidates are one frozen trial family; "
                "directions are selected on validation only and no candidate may be substituted.",
                "Strict exchange-session gaps, non-positive factor-specific denominators, "
                "redundancy, coverage, schedule and two-times-cost gates are fail-closed.",
            ]
        )
    report: dict[str, object] = {
        "schema_version": "m2-classic-factor-report-v1",
        "conclusion": conclusion,
        "hypothesis": config["research"]["hypothesis"],
        "snapshot_id": snapshot_id,
        "snapshot_manifest_sha256": snapshot_manifest_sha256,
        "candidate_symbol_count": len(candidates),
        "panel_rows": panel.height,
        "daily_ic_rows": results["daily_ic"].height,
        "target_rows": results["targets"].height,
        "factor_summary": summary.to_dicts(),
        "redundancy_summary": (
            results["redundancy_summary"].to_dicts() if "redundancy_summary" in results else []
        ),
        "factor_coverage_summary": (
            results["factor_coverage_summary"].to_dicts()
            if "factor_coverage_summary" in results
            else []
        ),
        "rebalance_schedule_alignment": (
            results["rebalance_schedule_alignment"].to_dicts()
            if "rebalance_schedule_alignment" in results
            else []
        ),
        "primary_group_monotonicity": (
            results["primary_group_monotonicity"].to_dicts()
            if "primary_group_monotonicity" in results
            else []
        ),
        "market_risk": config.get("market_risk", {}),
        "max_lottery": config.get("max_lottery", {}),
        "timing": {
            "signal": "close of as_of session",
            "execution": "next exchange session open",
            "label": "adjusted open(t+1+h)/adjusted open(t+1)-1",
        },
        "caveats": caveats,
    }
    factor_catalog = cast(Mapping[str, Any], config["factors"]).get("catalog")
    if factor_catalog == _SIXTH_BATCH_CATALOG:
        report["alpha101_sixth_batch"] = config["alpha101_sixth_batch"]
    if factor_catalog in (
        "max_lottery_fifth_batch_v1",
        _SIXTH_BATCH_CATALOG,
    ):
        expected_cost_semantic_sha256 = cast(
            Mapping[str, Any], config["portfolio"]
        ).get("cost_schedule_semantic_sha256")
        if expected_cost_semantic_sha256 is not None:
            report["cost_schedule_semantic_sha256"] = expected_cost_semantic_sha256
    return report


def _parquet(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd", statistics=True)
    return buffer.getvalue()


def _inside(root: Path, path: Path, *, strict: bool = True) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=strict)
    if resolved != root and root not in resolved.parents:
        raise ValueError("path escapes project root")
    return resolved
