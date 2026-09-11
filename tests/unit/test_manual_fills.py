import copy
import datetime as dt

import pytest

from quant.execution.manual_fills import execution_deviation, import_events, reconcile_book

SESSIONS = (dt.date(2026, 9, 9), dt.date(2026, 9, 10), dt.date(2026, 9, 11), dt.date(2026, 9, 14))


def opening():
    return {'date': '2026-09-09', 'cash': 10000.0, 'holdings': {}, 'receivables': [], 'restricted_shares': []}


def fill(identifier='f1', **changes):
    return {'event_id': identifier, 'timestamp': '2026-09-10T09:30:00+08:00',
            'kind': 'BUY', 'symbol': 'A', 'quantity': 100, 'price': 10.0, 'fee': 5.0, **changes}


def run(state, events):
    return import_events(state=state, events=events, sessions=SESSIONS)


def test_partial_fills_are_actual_quantities_and_repeat_is_noop():
    state = opening()
    events = [fill(), fill('f2', quantity=37, timestamp='2026-09-10T09:31:00+08:00')]
    book, summary = run(state, events)
    assert book['holdings']['A']['quantity'] == 137
    assert book['cash'] == 8620
    assert summary['fees'] == 10 and summary['imported_count'] == 2
    again, result = run(book, events)
    assert again == book
    assert result['message'] == 'no-op' and result['duplicate_count'] == 2
    assert state == opening()


def test_duplicate_id_with_changed_content_is_atomic_failure():
    book, _ = run(opening(), [fill()])
    before = copy.deepcopy(book)
    with pytest.raises(ValueError, match='conflicting'):
        run(book, [fill(quantity=101)])
    assert book == before


def test_t1_same_day_sell_is_rejected_and_next_day_is_available():
    book, _ = run(opening(), [fill()])
    with pytest.raises(ValueError, match=r'T\+1'):
        run(book, [fill('sell', kind='SELL', timestamp='2026-09-10T10:00:00+08:00')])
    sold, _ = run(book, [fill('sell', kind='SELL', timestamp='2026-09-11T10:00:00+08:00')])
    assert sold['holdings'] == {}
    assert sold['cash'] == 9990
    assert sold['restricted_shares'] == []


def test_cash_flows_dividends_and_fees_are_separate():
    state = opening()
    state['receivables'] = [{'symbol': 'A', 'pay_date': '2026-09-10', 'amount': 100.0}]
    rows = [{'event_id': kind, 'timestamp': f'2026-09-10T{hour}:00:00+08:00',
             'kind': kind, 'amount': amount, **extra}
            for kind, hour, amount, extra in [('DEPOSIT', '08', 1000.0, {}),
                ('DIVIDEND', '09', 100.0, {'symbol': 'A', 'fee': 1.0}),
                ('WITHDRAWAL', '15', 500.0, {}), ('FEE', '16', 2.0, {})]]
    book, result = run(state, rows)
    assert book['cash'] == 10597
    assert book['receivables'] == []
    assert result['external_net_flow'] == 500
    assert result['cash_dividends'] == 99
    assert result['fees'] == 3


def test_late_unknown_event_requires_rebuild_not_silent_insertion():
    book, _ = run(opening(), [fill(timestamp='2026-09-10T10:00:00+08:00')])
    with pytest.raises(ValueError, match='precede'):
        run(book, [fill('late')])


@pytest.mark.parametrize('event', [fill(price=float('nan')), fill(quantity=1.5),
                                  fill(quantity=100000), fill(timestamp='2026-09-12T09:30:00+08:00')])
def test_invalid_or_unaffordable_trade_does_not_mutate_opening(event):
    state = opening()
    with pytest.raises(ValueError):
        run(state, [event])
    assert state == opening()


def test_reconciliation_reports_real_cash_and_share_differences():
    book, _ = run(opening(), [fill()])
    observed = copy.deepcopy(book)
    assert reconcile_book(book, observed)['matched']
    observed['cash'] -= 1
    observed['holdings']['A']['quantity'] -= 10
    result = reconcile_book(book, observed)
    assert not result['matched'] and result['cash_difference'] == 1
    assert result['position_differences'][0]['observed_quantity'] == 90


def test_partial_fill_deviation_and_unfilled_reference_remain_visible():
    reference = [{'execution_date': '2026-09-10', 'symbol': 'A', 'side': 'BUY',
                  'quantity': 200, 'reference_price': 10.0},
                 {'execution_date': '2026-09-10', 'symbol': 'B', 'side': 'BUY',
                  'quantity': 100, 'reference_price': 10.0}]
    report = execution_deviation([fill(price=10.1)], reference)
    assert report['adverse_price_cost'] == pytest.approx(10)
    assert report['fees'] == 5
    assert report['orders'][0]['quantity_difference'] == -100
    assert report['orders'][1]['quantity'] == 0


def test_sell_price_improvement_and_unmatched_fill_are_distinguished():
    reference = [{'execution_date': '2026-09-10', 'symbol': 'A', 'side': 'SELL',
                  'quantity': 100, 'reference_price': 10.0}]
    result = execution_deviation([fill(kind='SELL', price=10.1), fill('b', symbol='B')], reference)
    assert result['adverse_price_cost'] == pytest.approx(-10)
    assert result['unmatched_fill_groups'] == 1
