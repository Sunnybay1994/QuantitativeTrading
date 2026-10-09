"""Fixed statement family controls, evaluated only inside original N4 admission."""

CONTROLS = ('pit_sue8_context_v2', 'reversal_20', 'report01_skip_month_momentum_n252',
    'amihud_illiquidity_monthly_calendar80_v1', 'free_float_turnover_level_monthly_calendar80_v1')


def check_statement_controls(panel, admitted, evaluate):
    names = list(dict.fromkeys([*admitted, *CONTROLS]))
    missing = sorted(set(names) - set(panel.columns))
    if missing:
        return {'passed': False, 'reason': 'missing_controls', 'missing': missing, 'controls': names}
    result = evaluate(panel, 'candidate', names, 1)
    return {**result, 'controls': names, 'candidate_variant': 'size_industry_neutral',
        'passed': result['months'] >= 96 and result['newey_west_t'] is not None and result['newey_west_t'] >= 2.5}
