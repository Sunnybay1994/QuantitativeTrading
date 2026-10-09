"""Protect continuity and frozen identities when long daily replays resume."""
import datetime as dt
import json

import polars as pl
import pytest

from quant.research.pead_account import FRAME_NAMES, read_checkpoint, save_checkpoint


def sample():
    day = dt.date(2020, 1, 2)
    nav = pl.DataFrame({'date': [day], 'cash': [70000.], 'equity': [101000.],
                        'market_value': [30000.], 'receivable': [1000.], 'unit_nav': [1.01]})
    state = {'date': str(day), 'cash': 70000.,
             'holdings': {'600000.SH': {'quantity': 1000, 'mark_price': 30.}},
             'receivables': [{'symbol': '600000.SH', 'pay_date': '2020-01-10', 'amount': 1000.}],
             'pead_books': {'600000.SH': {'expiry_date': '2020-02-12', 'event_keys': ['frozen_event']}},
             'nav': [{**nav.row(0, named=True), 'date': str(day)}]}
    result = {name: pl.DataFrame() for name in FRAME_NAMES}
    result.update(nav=nav, state=state)
    return day, result


def test_checkpoint_carries_holdings_receivable_and_event_clock(tmp_path):
    day, result = sample()
    folder = tmp_path/'2020'
    save_checkpoint(folder, result, previous={}, plan_sha='fixed')
    loaded = read_checkpoint(folder, dates=[day], previous={}, plan_sha='fixed')
    assert loaded == result['state']
    assert loaded['pead_books']['600000.SH']['expiry_date'] == '2020-02-12'


def test_checkpoint_rejects_different_prior_account_or_plan(tmp_path):
    day, result = sample()
    folder = tmp_path/'2020'
    save_checkpoint(folder, result, previous={}, plan_sha='fixed')
    with pytest.raises(ValueError, match='context'):
        read_checkpoint(folder, dates=[day], previous={'cash': 80000.}, plan_sha='fixed')
    with pytest.raises(ValueError, match='context'):
        read_checkpoint(folder, dates=[day], previous={}, plan_sha='changed')


def test_checkpoint_rejects_incomplete_calendar(tmp_path):
    day, result = sample()
    folder = tmp_path/'2020'
    save_checkpoint(folder, result, previous={}, plan_sha='fixed')
    with pytest.raises(ValueError, match='continue'):
        read_checkpoint(folder, dates=[day, dt.date(2020, 1, 3)], previous={}, plan_sha='fixed')


def test_checkpoint_rejects_modified_account_even_when_nav_unchanged(tmp_path):
    day, result = sample()
    folder = tmp_path/'2020'
    save_checkpoint(folder, result, previous={}, plan_sha='fixed')
    result['state']['pead_books']['600000.SH']['expiry_date'] = '2020-03-10'
    (folder/'account.json').write_text(json.dumps(result['state']), encoding='utf8')
    with pytest.raises(ValueError, match='checkpoint changed'):
        read_checkpoint(folder, dates=[day], previous={}, plan_sha='fixed')
