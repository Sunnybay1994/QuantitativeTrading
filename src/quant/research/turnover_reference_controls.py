"""Fixed matched/risk controls for the turnover-reference family's original N4."""
import polars as pl

from quant.factors.turnover_reference import CONTROLS as MATCHED_CONTROLS

RISK_CONTROLS = ('reversal_20', 'report01_skip_month_momentum_n252',
    'amihud_illiquidity_monthly_calendar80_v1', 'market_beta_60_vs_510300', 'ivol_ff3_60')


def check_turnover_reference_controls(panel, admitted, evaluate):
    names = list(dict.fromkeys([*admitted, *MATCHED_CONTROLS, *RISK_CONTROLS]))
    missing = sorted(set(names) - set(panel.columns))
    if missing:
        return {'passed': False, 'reason': 'missing_controls', 'missing': missing, 'controls': names}
    cohort = panel.filter(pl.col('candidate').is_finite() & pl.col('label').is_finite())
    incomplete = cohort.filter(~pl.all_horizontal(pl.col(c).is_finite().fill_null(False) for c in MATCHED_CONTROLS))
    if incomplete.height:
        return {'passed': False, 'reason': 'matched_control_cohort_differs',
            'incomplete_matched_control_rows': incomplete.height, 'controls': names}
    result = evaluate(cohort, 'candidate', names, 1)
    return {**result, 'controls': names, 'candidate_variant': 'size_industry_neutral',
        'signal_and_label_valid_rows': cohort.height, 'matched_controls_same_cohort': True,
        'passed': result['months'] >= 96 and result['newey_west_t'] is not None and result['newey_west_t'] >= 2.5}
