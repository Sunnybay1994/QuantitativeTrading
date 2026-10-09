"""Fixed co-movement controls for the existing N4, not a separate battery.

The caller supplies N3's already direction-adjusted raw or neutral candidate.
The same selected variant must also satisfy the original battery and N4 tests.
"""
import math

import polars as pl

from quant.factors.liquidity_comovement import CONTROLS as MATCHED_CONTROLS, SIGNALS

FIXED_CONTROLS = (
    'log_total_market_value', 'amihud_illiquidity_monthly_calendar80_v1',
    'free_float_turnover_level_monthly_calendar80_v1', 'reversal_20',
    'report01_skip_month_momentum_n252', 'market_beta_60_vs_510300', 'ivol_ff3_60',
)
MINIMUM_MONTHS = 96
MINIMUM_NW_T = 2.5
KEYS = ['symbol', 'trade_date']


def prepare_liquidity_comovement_controls(panel: pl.DataFrame, admitted: list[str], *,
        identifier: str, variant: str) -> tuple[pl.DataFrame, list[str]]:
    """Validate controls without using future returns to select a signal variant.

Missing columns, duplicate keys and broken same-window controls are computation
errors: raise before evaluation, so callers retain the unfinished batch rather
than recording a completed economic rejection. Ordinary fixed/admitted-control
missingness remains subject to the original evaluator's complete-case policy.
    """
    if identifier not in SIGNALS or variant not in ('raw', 'size_industry_neutral'):
        raise ValueError('Unregistered liquidity co-movement signal or variant')
    names = list(dict.fromkeys([*admitted, *FIXED_CONTROLS, *MATCHED_CONTROLS]))
    if set(names) & {*KEYS, 'candidate', 'label', *SIGNALS}:
        raise ValueError('Liquidity controls contain a key, response or candidate signal')
    missing = sorted(set([*KEYS, 'candidate', 'label', *names]) - set(panel.columns))
    if missing:
        raise ValueError(f'Liquidity co-movement control columns missing: {missing}')
    if panel.select(KEYS).is_duplicated().any() or panel.select(
            pl.any_horizontal(pl.col(c).is_null() for c in KEYS).any()).item():
        raise ValueError('Liquidity co-movement control keys are null or duplicated')
    finite_candidate = panel.filter(pl.col('candidate').is_finite())
    incomplete = finite_candidate.filter(~pl.all_horizontal(
        pl.col(c).is_finite().fill_null(False) for c in MATCHED_CONTROLS))
    if incomplete.height:
        raise ValueError(f'Liquidity same-window control cohort differs: {incomplete.height} rows')
    cohort = finite_candidate.filter(pl.col('label').is_finite())
    return cohort, names


def check_liquidity_comovement_controls(panel: pl.DataFrame, admitted: list[str], evaluate, *,
        identifier: str, variant: str) -> dict:
    """Apply the registered controls using N4's unmodified incremental evaluator.

This additional condition never substitutes for the original full-family
statistics, correlation and cost conditions. Insufficient/degenerate history
is distinguished from a completed negative incremental test.
    """
    cohort, names = prepare_liquidity_comovement_controls(
        panel, admitted, identifier=identifier, variant=variant)
    # N3 preprocessing already applied the registered + / - / - directions.
    result = evaluate(cohort, 'candidate', names, 1)
    months, statistic = result['months'], result['newey_west_t']
    finite_t = statistic is not None and math.isfinite(statistic)
    passed = months >= MINIMUM_MONTHS and finite_t and statistic >= MINIMUM_NW_T
    reason = ('insufficient_months' if months < MINIMUM_MONTHS else
              'undefined_incremental_statistic' if not finite_t else
              'incremental_t_pass' if passed else 'incremental_t_below_threshold')
    return {**result, 'controls': names, 'candidate_variant': variant,
        'signal_and_label_valid_rows': cohort.height, 'matched_controls_same_cohort': True,
        'passed': passed, 'reason': reason,
        'scope': 'Additional family controls only; original battery, costs and N4 still required'}
