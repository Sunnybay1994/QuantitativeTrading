"""N4 whole-family controls for sue_family_v1 (S6)."""
from __future__ import annotations

CONTROLS = (
    "pit_sue8_context_v2",
    "ngp_804a131ba8cb5a88",
    "ngp_bbcc07585bc35fbe",
    "ngp_c8f096c17cdb7e19",
    "reversal_20",
    "report01_skip_month_momentum_n252",
    "amihud_illiquidity_monthly_calendar80_v1",
    "free_float_turnover_level_monthly_calendar80_v1",
    "market_beta_60_vs_510300",
    "ivol_ff3_60",
)


def check_sue_family_controls(panel, admitted, evaluate) -> dict:
    """Require incremental NW-t vs the frozen control set when those columns exist."""
    present = [c for c in CONTROLS if c in panel.columns or f"control_{c}_raw" in panel.columns
               or f"control_{c}_size_industry_neutral" in panel.columns]
    # Prefer admitted control_* columns produced by N4 panel join.
    control_names = []
    for base in CONTROLS:
        for candidate in (f"control_{base}_size_industry_neutral", f"control_{base}_raw", base):
            if candidate in panel.columns:
                control_names.append(candidate)
                break
    if not control_names:
        return {
            "passed": False,
            "reason": "sue_family_controls_absent",
            "controls": list(CONTROLS),
            "present": present,
        }
    stats = evaluate(panel, "candidate", control_names, 1)
    passed = (
        stats.get("months", 0) >= 96
        and stats.get("newey_west_t") is not None
        and stats["newey_west_t"] >= 2.5
    )
    return {
        "passed": bool(passed),
        "controls_used": control_names,
        "incremental": stats,
        "reason": None if passed else "incremental_nw_t_or_months_failed",
    }
