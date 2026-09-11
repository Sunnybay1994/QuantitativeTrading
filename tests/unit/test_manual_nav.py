import copy
import datetime as dt
import json
import sys

import polars as pl
import pytest

from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA
from quant.execution.manual_nav import close_manual_day

D0, D1, D2 = dt.date(2026, 9, 9), dt.date(2026, 9, 10), dt.date(2026, 9, 11)
SYMBOL = '000001.SZ'


def inputs(quantity=0):
    equity = 1000.0 + quantity * 10
    opening = {'date': str(D0), 'cash': 1000.0, 'holdings': {
        SYMBOL: {'quantity': quantity, 'mark_price': 10.0}} if quantity else {},
        'receivables': [], 'restricted_shares': [],
        'nav': [{'date': str(D0), 'equity': equity, 'unit_nav': 1.0}]}
    return dict(opening=opening, events=[], date=D1,
        bars=pl.DataFrame({'symbol': [SYMBOL], 'trade_date': [D1], 'close': [10.0]}),
        calendar=pl.DataFrame({'date': [D0, D1, D2], 'market': ['SZ']*3, 'is_open': [True]*3}),
        dividends=pl.DataFrame(schema=DIVIDEND_SCHEMA),
        suspensions=pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date}))


def test_actual_fills_close_marks_and_fees_determine_nav():
    args = inputs()
    args['events'] = [{'event_id': 'buy', 'timestamp': f'{D1}T09:30:00+08:00', 'kind': 'BUY',
                       'symbol': SYMBOL, 'quantity': 50, 'price': 10.0, 'fee': 5.0}]
    args['bars'] = args['bars'].with_columns(pl.lit(11.0).alias('close'))
    before = copy.deepcopy(args['opening'])
    book, summary = close_manual_day(**args)
    assert book['cash'] == 495
    assert summary['valuation']['equity'] == 1045
    assert summary['valuation']['unit_nav'] == pytest.approx(1.045)
    assert book['holdings'][SYMBOL]['mark_price'] == 11
    assert args['opening'] == before
    _, repeat = close_manual_day(**{**args, 'opening': book})
    assert repeat['message'] == 'no-op'


@pytest.mark.parametrize('kind,amount', [('DEPOSIT', 500.0), ('WITHDRAWAL', 500.0)])
def test_cash_flows_do_not_become_investment_returns(kind, amount):
    args = inputs()
    args['events'] = [{'event_id': 'cash', 'timestamp': f'{D1}T12:00:00+08:00',
                       'kind': kind, 'amount': amount}]
    _, result = close_manual_day(**args)
    assert result['valuation']['daily_return'] == 0
    assert result['valuation']['unit_nav'] == 1
    assert result['valuation']['weighted_external_flow'] == (1 if kind == 'DEPOSIT' else -1) * amount / 8


def dividend(ratio=0.0):
    return pl.DataFrame([{'symbol': SYMBOL, 'ann_date': D0, 'record_date': D0,
        'ex_date': D1, 'pay_date': D1, 'share_list_date': D2,
        'div_cash': 1.0 if not ratio else 0.0, 'share_ratio': ratio}], schema=DIVIDEND_SCHEMA)


@pytest.mark.parametrize('paid', [False, True])
def test_dividend_is_receivable_until_actual_payment_without_double_count(paid):
    args = inputs(100)
    args['dividends'] = dividend()
    args['bars'] = args['bars'].with_columns(pl.lit(9.0).alias('close'))
    if paid:
        args['events'] = [{'event_id': 'div', 'timestamp': f'{D1}T10:00:00+08:00',
                          'kind': 'DIVIDEND', 'symbol': SYMBOL, 'amount': 100.0}]
    book, result = close_manual_day(**args)
    assert result['valuation']['equity'] == 2000
    assert result['valuation']['daily_return'] == 0
    assert book['cash'] == (1100 if paid else 1000)
    assert result['valuation']['receivable'] == (0 if paid else 100)


def test_share_distribution_reuses_quantity_and_listing_restrictions():
    args = inputs(100)
    args['dividends'] = dividend(0.1)
    args['bars'] = args['bars'].with_columns(pl.lit(1000/110).alias('close'))
    book, summary = close_manual_day(**args)
    assert book['holdings'][SYMBOL]['quantity'] == 110
    assert book['restricted_shares'] == [{'symbol': SYMBOL, 'quantity': 10, 'list_date': str(D2)}]
    assert summary['valuation']['unit_nav'] == pytest.approx(1.0)


def test_after_close_cash_flow_belongs_to_next_valuation():
    args = inputs()
    args['events'] = [{'event_id': 'cash', 'timestamp': f'{D0}T16:00:00+08:00',
                       'kind': 'DEPOSIT', 'amount': 500.0}]
    _, summary = close_manual_day(**args)
    assert summary['valuation']['daily_return'] == 0
    args['events'][0]['timestamp'] = f'{D1}T16:00:00+08:00'
    with pytest.raises(ValueError, match='through this close'):
        close_manual_day(**args)


def test_missing_close_is_only_carried_with_official_suspension():
    args = inputs(100)
    args['bars'] = args['bars'].clear()
    with pytest.raises(ValueError, match='official suspension'):
        close_manual_day(**args)
    args['suspensions'] = pl.DataFrame({'symbol': [SYMBOL], 'trade_date': [D1]})
    _, summary = close_manual_day(**args)
    assert summary['valuation']['carried_suspended_symbols'] == [SYMBOL]
    assert summary['valuation']['unit_nav'] == 1


def test_skipped_session_is_not_silently_valued():
    args = inputs()
    with pytest.raises(ValueError, match='do not skip'):
        close_manual_day(**{**args, 'date': D2})


def test_cash_only_inception_starts_at_one_without_inventing_earlier_returns():
    args = inputs()
    args['opening']['nav'] = []
    book, result = close_manual_day(**args)
    assert book['nav'][0] == {'date': str(D0), 'equity': 1000.0, 'unit_nav': 1.0}
    assert result['valuation']['unit_nav'] == 1
    args['opening']['holdings'] = {SYMBOL: {'quantity': 100, 'mark_price': 10.0}}
    with pytest.raises(ValueError, match='dated closing valuation'):
        close_manual_day(**args)


def test_cli_writes_flat_nav_and_repeats_without_new_files(tmp_path, monkeypatch):
    from quant.data import manual_nav_inputs
    from quant.execution import manual_nav

    args = inputs()
    opening = tmp_path/'opening.json'
    opening.write_text(json.dumps(args['opening']))
    events = tmp_path/'events.json'
    events.write_text('[]')
    monkeypatch.setattr(manual_nav_inputs, 'read_manual_nav_inputs', lambda **kwargs:
                        {key: args[key] for key in ('bars', 'calendar', 'dividends', 'suspensions')})
    output = tmp_path/'closed'
    command = ['manual_nav', '--opening', str(opening), '--events', str(events),
               '--to', str(D1), '--output', str(output), '--rehearsal']
    monkeypatch.setattr(sys, 'argv', command)
    manual_nav.main()
    assert pl.read_csv(output/'nav.csv').height == 2
    assert (output/'report.md').is_file()
    before = (output/'state.json').read_bytes()
    command[2] = str(output/'state.json')
    manual_nav.main()
    assert (output/'state.json').read_bytes() == before
