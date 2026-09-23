import pandas as pd
import pytest

from quant.research.market_state_adaptation import DIMENSIONS, align_states


def test_states_join_next_session_not_same_day_and_missing_stays_unknown():
    dates = pd.to_datetime(['2026-09-22', '2026-09-23', '2026-09-24'])
    returns = pd.DataFrame({'return': [.01, -.01, .02]}, index=dates)
    states = pd.DataFrame({'trade_date': dates[:2], 'effective_date': dates[1:],
                           **{key: ['low', 'high'] for key in DIMENSIONS}})
    result = align_states(returns, states)
    assert result.market_state.tolist() == ['unknown', 'low', 'high']
    states.loc[0, 'effective_date'] = dates[0]
    with pytest.raises(ValueError, match='next-session'):
        align_states(returns, states)


def test_ambiguous_effective_dates_rejected():
    dates = pd.to_datetime(['2026-09-22', '2026-09-23'])
    states = pd.DataFrame({'trade_date': [dates[0]]*2, 'effective_date': [dates[1]]*2,
                           **{key: ['low', 'high'] for key in DIMENSIONS}})
    with pytest.raises(ValueError, match='unique'):
        align_states(pd.DataFrame({'return': [0., 0.]}, index=dates), states)
