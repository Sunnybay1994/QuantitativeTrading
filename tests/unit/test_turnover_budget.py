import copy
import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.portfolio.turnover_budget import budget_targets
from quant.research.classic_monthly_baseline import replay
from tests.unit.test_batched_daily_replay import cash_inputs, replay_inputs
from tests.unit.test_paper_ledger import D1, D2, D3


def test_replacement_preserves_unsold_names_and_limits_one_way_distance():
    day = dt.date(2024, 1, 31)
    targets = pl.DataFrame({'as_of': [day], 'symbol': ['new'], 'weight': [1.]})
    state = {'date': str(day), 'nav': [{'equity': 1000.}],
             'holdings': {'old': {'quantity': 100, 'mark_price': 10.}}}
    saved = copy.deepcopy(state)
    result = budget_targets(targets, state, budget=.5)
    assert dict(result.select('symbol', 'weight').iter_rows()) == {'new': .5, 'old': .5}
    assert state == saved
    # Partial fills last month leave actual weights different from old targets.
    state['holdings']['old']['quantity'] = 50
    result = budget_targets(targets, state, budget=.25)
    assert dict(result.select('symbol', 'weight').iter_rows()) == pytest.approx({'new': 1/3, 'old': 1/3})
    state['date'] = str(day-dt.timedelta(days=1))
    with pytest.raises(ValueError, match='signal close'):
        budget_targets(targets, state, budget=.5)


def test_budget_integration_sizes_from_prior_close_and_continues_chunks():
    initial = cash_inputs()
    state = {}
    replay(**{**initial, 'sessions': [D1]}, account_state=state, validate_once=True)
    kwargs = replay_inputs()
    kwargs['targets'] = kwargs['targets'].filter(pl.col('execution_date') == D2).with_columns(
        pl.lit(1.).alias('weight'))
    kwargs['dividends'] = kwargs['dividends'].head(0)
    kwargs['sessions'] = [D2, D3]
    records = []
    replay(**kwargs, account_state=state, validate_once=True,
           target_turnover_budget=.25, target_records=records)
    assert len(records) == 1 and records[0]['weight'] == .5
    assert records[0]['as_of'] == D1


def test_cash_entry_and_full_exit_have_half_weight_distance():
    day = dt.date(2024, 1, 31)
    targets = pl.DataFrame({'as_of': [day], 'symbol': ['A'], 'weight': [1.]})
    state = {'date': str(day), 'nav': [{'equity': 1000.}], 'holdings': {}}
    assert budget_targets(targets, state, budget=.5)['weight'].item() == 1.
    state['holdings'] = {'A': {'quantity': 100, 'mark_price': 10.}}
    targets = targets.with_columns(pl.lit(0.).alias('weight'))
    assert budget_targets(targets, state, budget=.5)['weight'].item() == 0.


def test_budgeted_chunks_preserve_bonus_and_restricted_shares():
    kwargs = replay_inputs()
    initial = {}
    replay(**{**kwargs, 'sessions': [D1], 'targets': kwargs['targets'].head(1)},
           account_state=initial, validate_once=True)
    whole, chunks = copy.deepcopy(initial), copy.deepcopy(initial)
    expected = replay(**{**kwargs, 'sessions': [D2, D3], 'targets': kwargs['targets'].tail(2)},
        account_state=whole, target_turnover_budget=.1, validate_once=True)
    pieces = []
    for day in (D2, D3):
        pieces.append(replay(**{**kwargs, 'sessions': [day],
            'targets': kwargs['targets'].filter(pl.col('execution_date') == day)},
            account_state=chunks, target_turnover_budget=.1, validate_once=True))
    assert chunks == whole
    for index, frame in enumerate(expected):
        assert_frame_equal(frame, pl.concat([part[index] for part in pieces], how='vertical_relaxed'),
                           check_exact=True)
