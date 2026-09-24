import pandas as pd
import pytest

from quant.research.market_state_adaptation import DIMENSIONS, align_states
from quant.research.market_state_adaptation import holding_window, event_metrics


def test_holding_prefix_removed_first_loss_and_later_cash_preserved():
    dates = pd.date_range('2020-01-01', periods=5)
    nav = pd.DataFrame(dict(equity=[100, 100, 90, 90, 90],
                            position_count=[0, 0, 1, 0, 0],
                            market_value=[0, 0, 80, 0, 0]), index=dates)
    nav['return'] = nav.equity.pct_change()
    trades = pd.DataFrame(dict(date=[dates[2], dates[3]], side=['BUY', 'SELL'], quantity=[100, 100]))
    trimmed, audit = holding_window(nav, trades)
    assert audit['excluded_prefix_rows'] == 2
    assert len(trimmed) == 3
    assert trimmed['return'].iloc[0] == pytest.approx(-.1)
    assert trimmed.holding_exposure.tolist() == [True, True, False]
    assert event_metrics(trimmed.iloc[-1:]) == dict(applicable=False, reason='no_holding_exposure',
                                                  event_return=None, max_drawdown=None)
    assert event_metrics(trimmed)['event_return'] == pytest.approx(-.1)
    with pytest.raises(ValueError, match='BUY evidence'):
        holding_window(nav, trades.iloc[1:])


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
