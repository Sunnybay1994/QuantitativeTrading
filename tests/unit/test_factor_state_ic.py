import datetime as dt

import polars as pl
import pytest

from quant.reporting.factor_state_ic import summarize_states
from quant.reporting.stratified_signals import market_states
from quant.research.factor_battery_statistics import monthly_ic_summary


def test_signal_alignment_missing_states_and_calendar_gaps():
    dates = [dt.date(2024, m, 28) for m in (1, 3, 8, 9)]
    frame = pl.DataFrame({'factor': ['a']*4, 'trade_date': dates,
        'raw_rank_ic': [.1, .2, .3, .4], 'partial_rank_ic': [.05, .3, -.1, None]})
    states = pl.DataFrame({'signal_date': dates[:3], 'trend': ['bull', 'bear', 'bull'],
        'volatility': ['low', 'high', 'low']})
    panel, summary = summarize_states(frame, states, lag=6, minimum_months_per_year=6)
    assert panel['trend'].to_list() == ['bull', 'bear', 'bull', 'unknown']
    bull = summary.filter((pl.col('metric') == 'partial_rank_ic') & (pl.col('state') == 'bull')).row(0, named=True)
    expected = monthly_ic_summary([dates[0], dates[2]], [.05, -.1], lag=6)
    assert bull['months'] == 2
    assert bull['newey_west_t'] == pytest.approx(expected['newey_west_t'])
    unknown = summary.filter((pl.col('metric') == 'partial_rank_ic') &
        (pl.col('dimension') == 'trend') & (pl.col('state') == 'unknown')).row(0, named=True)
    assert unknown['selected_months'] == 1 and unknown['months'] == 0
    with pytest.raises(ValueError):
        summarize_states(pl.concat([frame, frame]), states, lag=6, minimum_months_per_year=6)


def test_future_prices_do_not_change_signal_state():
    dates = [dt.date(2022, 1, 1)+dt.timedelta(days=i) for i in range(520)]
    prices = pl.DataFrame({'date': dates, 'unit_nav': [1+i*.001+(i % 7)*.003 for i in range(520)]})
    cutoff = dates[480]
    changed = prices.with_columns(pl.when(pl.col('date') > cutoff).then(pl.col('unit_nav')*100)
        .otherwise(pl.col('unit_nav')).alias('unit_nav'))
    before = market_states(prices).filter(pl.col('signal_date') <= cutoff)
    after = market_states(changed).filter(pl.col('signal_date') <= cutoff)
    assert before.equals(after)
