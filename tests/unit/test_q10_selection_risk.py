import numpy as np
import pytest

from quant.reporting.q10_selection_risk import dsr, pbo


def test_more_trial_attempts_reduce_deflated_sharpe_confidence():
    rng=np.random.default_rng(42)
    values=rng.normal(.0006,.01,1000)
    few=dsr(values,trials=41,trial_sharpe_std=.02)
    many=dsr(values,trials=863,trial_sharpe_std=.02)
    assert 0<many['dsr']<few['dsr']<1
    assert many['expected_maximum_daily_sharpe']>few['expected_maximum_daily_sharpe']
    assert many['annualized_sharpe']==pytest.approx(values.mean()/values.std(ddof=1)*np.sqrt(252))
    with pytest.raises(ValueError,match='finite'):
        dsr([np.nan]*100,trials=41,trial_sharpe_std=.02)


def test_cscv_detects_train_winners_that_always_reverse_in_complement():
    noise=(np.arange(20)-9.5)*.0001
    first=np.concatenate([noise+mu for mu in (.001,.002,.004,-.007)])
    matrix=np.column_stack([first,-first])
    result=pbo(matrix,blocks=4)
    assert result['combinations']==6 and result['sessions']==80
    assert result['pbo']==1.
    assert pbo(matrix[:,::-1],blocks=4)['pbo']==result['pbo']
    with pytest.raises(ValueError,match='multiple'):
        pbo(matrix[:,:1],blocks=4)
