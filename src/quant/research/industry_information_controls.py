"""Industry-allocation controls inside the original raw/neutral N4 admission."""
import polars as pl

from quant.factors.industry_information import CONTROL, SIGNALS

FIXED_CONTROLS = ('log_total_market_value', 'amihud_illiquidity_monthly_calendar80_v1',
    'free_float_turnover_level_monthly_calendar80_v1', 'reversal_20',
    'report01_skip_month_momentum_n252', 'market_beta_60_vs_510300', 'ivol_ff3_60')


def check_industry_information_controls(panel, admitted, evaluate, identifier):
    if identifier not in SIGNALS:
        raise ValueError('Unregistered industry information signal')
    matched = [CONTROL] if identifier == SIGNALS[1] else []
    names = list(dict.fromkeys([*admitted, *matched, *FIXED_CONTROLS]))
    missing = sorted(set([*names, 'candidate', 'label', 'industry_neutral'])-set(panel.columns))
    if missing:
        return {'passed':False, 'reason':'missing_controls', 'missing':missing, 'controls':names}
    # A nonzero neutral score here means a taxonomy/source mismatch, not stock alpha.
    neutral_rows = panel.filter(pl.col('industry_neutral').is_finite()).height
    if neutral_rows:
        return {'passed':False, 'reason':'industry_neutral_not_identically_unavailable',
            'neutral_finite_rows':neutral_rows, 'controls':names}
    cohort = panel.filter(pl.col('candidate').is_finite() & pl.col('label').is_finite())
    result = evaluate(cohort,'candidate',names,1)
    return {**result,'controls':names,'candidate_variant':'raw',
        'neutral_finite_rows':0,'signal_and_label_valid_rows':cohort.height,
        'interpretation':'Industry allocation information; no independent stock-selection alpha',
        'passed':result['months']>=96 and result['newey_west_t'] is not None and result['newey_west_t']>=2.5}
