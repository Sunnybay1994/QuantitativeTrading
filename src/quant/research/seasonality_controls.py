"""Fixed long-term-return controls for seasonality, within the original N4."""
from quant.factors.return_seasonality import CONTROL_NAMES
from quant.research.price_delay_controls import CONTROLS as RISK_CONTROLS


def check_seasonality_controls(panel, admitted, evaluate):
    names=list(dict.fromkeys([*admitted,*CONTROL_NAMES,*RISK_CONTROLS]))
    missing=sorted(set(names)-set(panel.columns))
    if missing:
        return {'passed':False,'reason':'missing_controls','missing':missing,'controls':names}
    result=evaluate(panel,'candidate',names,1)
    return {**result,'controls':names,'candidate_variant':'size_industry_neutral',
            'passed':result['months']>=96 and result['newey_west_t'] is not None and result['newey_west_t']>=2.5}
