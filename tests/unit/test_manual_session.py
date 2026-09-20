"""Offline integration acceptance for durable manual execution sessions."""
import datetime as dt

import pytest

from quant.execution.manual_session import ManualSession


def at(time='09:32:00', day='2026-09-21'):
    return dt.datetime.fromisoformat(f'{day}T{time}+08:00')


def order(identifier='O001', **changes):
    return dict(order_id=identifier, version=1, account_id='galaxy-test',
                strategy_version='frozen-rehearsal-v1', symbol='600000.SH', side='BUY',
                quantity=1000, limit_price=10., valid_from=at('09:30:00').isoformat(),
                valid_until=at('09:35:00').isoformat(), signal_at=at('08:00:00').isoformat(), **changes)


@pytest.fixture
def session(tmp_path):
    value = ManualSession(tmp_path / 'session.sqlite')
    value.initialize(opening={'date': '2026-09-18', 'cash': 100000., 'holdings': {}},
                     sessions=['2026-09-21', '2026-09-22', '2026-09-23'],
                     account_id='galaxy-test', sender_id='user-1', chat_id='chat-1')
    yield value
    value.close()


def add(session, identifier='O001', **changes):
    data = order(identifier)
    data.update(changes)
    session.add_order(data, now=at('09:00:00'))
    return data


def receive(session, text, identifier='m1', **changes):
    envelope = dict(message_id=identifier, sender_id='user-1', chat_id='chat-1', text=text)
    envelope.update(changes)
    return session.receive(envelope)


def apply(session, text, identifier='m1', now=None):
    receive(session, text, identifier)
    return session.process(now=now or at())[-1]


def fill(order_id='O001', trade='F1', quantity=100, price=10, time='09:31:00', fee='待核', version=1):
    return f'成交 {order_id} v{version} 成交号={trade} 本次数量={quantity} 成交价={price} 时间={time} 费用={fee}'


def states(session):
    return {row['order_id']: row['state'] for row in session.snapshot()['orders']}


def outbox(session):
    return {row['id']: row for row in session.snapshot()['outbox']}


def accept(chat, text, token):
    assert chat == 'chat-1'
    assert text.startswith('【演练 · 不下真实单】')
    return {'provider_accepted': True, 'message_id': 'provider-' + token}


def test_restart_recovers_pending_inbox_fills_and_dedup(tmp_path):
    path = tmp_path / 'session.sqlite'
    first = ManualSession(path)
    first.initialize(opening={'date': '2026-09-18', 'cash': 100000., 'holdings': {}},
                     sessions=['2026-09-21', '2026-09-22', '2026-09-23'],
                     account_id='galaxy-test', sender_id='user-1', chat_id='chat-1')
    add(first)
    receive(first, fill())
    first.close()
    second = ManualSession(path)
    assert second.process(now=at())[0]['status'] == 'processed'
    before = second.snapshot()
    second.close()
    third = ManualSession(path)
    try:
        assert third.snapshot() == before
        assert receive(third, fill()) == {'status': 'processed', 'duplicate': True}
        assert third.process(now=at()) == []
        assert third.book()['cash'] == 99000
        assert third.book()['holdings']['600000.SH']['quantity'] == 100
    finally:
        third.close()


def test_submitted_partial_fill_cancel_fee_lifecycle(session):
    add(session)
    assert apply(session, '委托 O001 v1 券商单号=B1 数量=1000 限价=10 时间=09:30:10')['state'] == 'SUBMITTED'
    assert session.book()['holdings'] == {}
    assert apply(session, fill(quantity=400), 'm2')['state'] == 'PARTIAL'
    assert session.snapshot()['fee_pending_fills'] == 1
    assert apply(session, '撤单确认 O001 v1 券商单号=B1 已撤剩余=600 时间=09:31:30', 'm3')['state'] == 'CANCELLED'
    assert session.book()['holdings']['600000.SH']['quantity'] == 400
    assert session.book()['cash'] == 96000
    assert apply(session, '费用确认 O001 v1 成交号=F1 费用=5.00', 'm4')['status'] == 'processed'
    assert session.book()['cash'] == 95995
    assert session.snapshot()['fee_pending_fills'] == 0
    apply(session, '费用确认 O001 v1 成交号=F1 费用=5.00', 'm5')
    assert session.book()['cash'] == 95995
    assert apply(session, '费用确认 O001 v1 成交号=F1 费用=6.00', 'm6')['status'] == 'review'
    assert session.book()['cash'] == 95995


def test_trade_id_duplicate_different_message_does_not_double_fill(session):
    add(session)
    apply(session, fill(fee='5'))
    assert apply(session, fill(fee='5'), 'm2')['status'] == 'processed'
    assert len(session.events()) == 1
    assert session.book()['cash'] == 98995
    assert apply(session, fill(quantity=200), 'm3')['status'] == 'review'
    assert len(session.events()) == 1
    assert session.book()['cash'] == 98995


def test_trade_id_account_day_scope_rejects_different_order(session):
    add(session)
    add(session, 'O002', symbol='600001.SH')
    apply(session, fill())
    assert apply(session, fill(order_id='O002'), 'm2')['status'] == 'review'
    assert '600001.SH' not in session.book()['holdings']


def test_same_message_id_conflict_preserves_original_book(session):
    add(session)
    apply(session, fill())
    assert receive(session, fill(quantity=200))['status'] == 'review'
    assert session.process(now=at()) == []
    assert session.book()['holdings']['600000.SH']['quantity'] == 100
    with pytest.raises(ValueError, match='Resolve pending'):
        add(session, 'O002', symbol='600001.SH')


def test_out_of_order_actual_fills_rebuild_by_execution_time(session):
    add(session)
    apply(session, fill(trade='LATE', quantity=600, price=10, time='09:31:40', fee='3'))
    apply(session, fill(trade='EARLY', quantity=400, price=9, time='09:30:40', fee='2'), 'm2')
    assert [e['event_id'].split(':')[-1] for e in session.events()] == ['EARLY', 'LATE']
    assert session.book()['cash'] == 90395
    assert session.book()['holdings']['600000.SH']['quantity'] == 1000
    assert session.book()['holdings']['600000.SH']['mark_price'] == 10
    assert states(session)['O001'] == 'FILLED'


def test_explicit_no_operation_releases_reserve_and_requires_new_version(session):
    add(session, quantity=9000)
    with pytest.raises(ValueError, match='Insufficient cash'):
        add(session, 'O002', symbol='600001.SH', quantity=1000)
    assert apply(session, '未操作 O001 v1 确认未委托=是 原因=错过窗口')['state'] == 'NOT_SUBMITTED'
    assert session.book()['cash'] == 100000
    add(session, 'O002', version=2, quantity=9000, supersedes_order_id='O001')
    assert states(session) == {'O001': 'SUPERSEDED', 'O002': 'PLANNED'}


def test_query_reserves_unknown_working_order_without_inventing_fill(session):
    add(session, quantity=9000)
    assert apply(session, '查单 O001 v1 状态=已委托未确认成交 券商单号=B1')['state'] == 'AWAITING_CONFIRMATION'
    assert session.book()['holdings'] == {}
    with pytest.raises(ValueError, match='Insufficient cash'):
        add(session, 'O002', symbol='600001.SH', quantity=1000)
    assert apply(session, '未操作 O001 v1 确认未委托=是 原因=漏操作', 'm2')['status'] == 'review'


def test_missed_sell_does_not_finance_dependent_buy(tmp_path):
    value = ManualSession(tmp_path / 'holdings.sqlite')
    value.initialize(opening={'date': '2026-09-18', 'cash': 100000.,
                              'holdings': {'600000.SH': {'quantity': 1000, 'mark_price': 10}}},
                     sessions=['2026-09-21', '2026-09-22', '2026-09-23'],
                     account_id='galaxy-test', sender_id='user-1', chat_id='chat-1')
    try:
        add(value, side='SELL')
        with pytest.raises(ValueError, match='Insufficient cash'):
            add(value, 'O002', symbol='600001.SH', quantity=10500)
        apply(value, '未操作 O001 v1 确认未委托=是 原因=错过窗口')
        assert value.book()['holdings']['600000.SH']['quantity'] == 1000
        assert value.book()['cash'] == 100000
        with pytest.raises(ValueError, match='Insufficient cash'):
            add(value, 'O002', symbol='600001.SH', quantity=10500)
    finally:
        value.close()


def test_late_fill_invalidates_replacement_and_preserves_actual_trade(session):
    add(session)
    apply(session, '未操作 O001 v1 确认未委托=是 原因=误记')
    add(session, 'O002', version=2, supersedes_order_id='O001')
    assert apply(session, fill(quantity=1000), 'm2')['status'] == 'processed'
    assert states(session)['O002'] == 'AWAITING_CONFIRMATION'
    assert outbox(session)['order:O002']['status'] == 'cancelled'
    assert session.book()['holdings']['600000.SH']['quantity'] == 1000
    assert any(k.startswith('late:') for k in outbox(session))


def test_dispatch_failure_is_uncertain_and_not_retried_after_restart(session, tmp_path):
    add(session)
    calls = []

    def fails(*args):
        calls.append(args)
        raise TimeoutError('Acceptance unknown')

    assert session.dispatch(fails, now=at()) == [{'id': 'order:O001', 'status': 'uncertain'}]
    assert session.dispatch(fails, now=at()) == []
    reopened = ManualSession(tmp_path / 'session.sqlite')
    try:
        assert reopened.dispatch(fails, now=at()) == []
        assert states(reopened)['O001'] == 'AWAITING_CONFIRMATION'
        assert len(calls) == 1
    finally:
        reopened.close()


@pytest.mark.parametrize('receipt', [{}, {'provider_accepted': False, 'message_id': 'x'},
                                    {'provider_accepted': True}])
def test_http_success_without_business_acceptance_is_uncertain(session, receipt):
    add(session)
    assert session.dispatch(lambda *args: receipt, now=at())[0]['status'] == 'uncertain'


def test_unsent_expiry_never_delivers_order(session):
    add(session)
    assert session.dispatch(accept, now=at('09:29:00')) == []
    assert session.dispatch(accept, now=at('09:36:00')) == []
    assert states(session)['O001'] == 'EXPIRED_UNSENT'
    assert outbox(session)['order:O001']['status'] == 'expired'


def test_sent_expiry_is_unknown_not_assumed_unexecuted_reminds_once(session):
    add(session, quantity=9000)
    session.dispatch(accept, now=at())
    session.tick(now=at('09:36:00'))
    session.tick(now=at('09:37:00'))
    assert states(session)['O001'] == 'AWAITING_CONFIRMATION'
    assert len([k for k in outbox(session) if k.startswith('check:')]) == 1
    assert session.book()['holdings'] == {}
    with pytest.raises(ValueError, match='Insufficient cash'):
        add(session, 'O002', symbol='600001.SH', quantity=1000)


@pytest.mark.parametrize('changes', [{'sender_id': 'intruder'}, {'chat_id': 'other-chat'}])
def test_untrusted_sender_or_chat_cannot_write_inbox_or_account(session, changes):
    add(session)
    before = session.snapshot()
    with pytest.raises(ValueError, match='not authorized'):
        receive(session, fill(), **changes)
    assert session.snapshot() == before


def test_future_fill_and_excess_quantity_roll_back_atomically(session):
    add(session)
    assert apply(session, fill(time='09:33:00'))['status'] == 'review'
    assert apply(session, fill(quantity=1001), 'm2')['status'] == 'review'
    assert session.book()['cash'] == 100000
    assert session.events() == []


def test_late_and_price_deviating_actual_fill_kept(session):
    add(session)
    result = apply(session, fill(quantity=1000, price=11, time='09:36:00'), now=at('09:37:00'))
    assert result['status'] == 'processed'
    assert '偏差' in result['action']
    assert session.book()['cash'] == 89000


def test_pending_fee_reserve_blocks_overallocation(session):
    add(session, quantity=100)
    apply(session, fill(quantity=100))
    with pytest.raises(ValueError, match='Insufficient cash'):
        add(session, 'O002', symbol='600001.SH', quantity=100, limit_price=989.6)


def test_submitted_reply_prevents_later_dispatch_of_original_proposal(session):
    add(session)
    apply(session, '委托 O001 v1 券商单号=B1 数量=1000 限价=10 时间=09:30:10')
    dispatched = session.dispatch(accept, now=at())
    assert all(row['id'] != 'order:O001' for row in dispatched)


def test_changed_submitted_quantity_same_broker_is_conflict(session):
    add(session)
    apply(session, '委托 O001 v1 券商单号=B1 数量=1000 限价=10 时间=09:30:10')
    result = apply(session, '委托 O001 v1 券商单号=B1 数量=100 限价=10 时间=09:30:10', 'm2')
    assert result['status'] == 'review'


def test_changed_submitted_price_same_broker_is_conflict(session):
    add(session)
    apply(session, '委托 O001 v1 券商单号=B1 数量=1000 限价=10 时间=09:30:10')
    result = apply(session, '委托 O001 v1 券商单号=B1 数量=1000 限价=11 时间=09:30:10', 'm2')
    assert result['status'] == 'review'


def test_fill_before_allowed_window_retained_but_marked_deviation(session):
    add(session)
    result = apply(session, fill(time='09:29:00'))
    assert result['status'] == 'processed'
    assert '偏差' in result['action']
    assert session.book()['holdings']['600000.SH']['quantity'] == 100


@pytest.mark.parametrize('process_bad_reply', [False, True])
def test_pending_or_conflicting_receipt_blocks_existing_queued_proposals(session, process_bad_reply):
    add(session)
    add(session, 'O002', symbol='600001.SH')
    receive(session, fill(quantity=1001))
    if process_bad_reply:
        assert session.process(now=at())[0]['status'] == 'review'
    sent = session.dispatch(accept, now=at())
    assert all(not row['id'].startswith('order:') for row in sent)


def test_t1_blocks_same_day_sale_after_actual_fill(session):
    add(session, quantity=100)
    apply(session, fill(quantity=100))
    with pytest.raises(ValueError, match='Insufficient sellable T\\+1'):
        add(session, 'O002', side='SELL', quantity=100)
    add(session, 'O003', side='SELL', quantity=100,
        valid_from=at('09:30:00', '2026-09-22').isoformat(),
        valid_until=at('09:35:00', '2026-09-22').isoformat())


def test_duplicate_pending_fill_after_fee_confirmation_keeps_confirmed_fee(session):
    add(session)
    apply(session, fill())
    apply(session, '费用确认 O001 v1 成交号=F1 费用=5', 'm2')
    assert apply(session, fill(), 'm3')['status'] == 'processed'
    assert session.book()['cash'] == 98995
    assert session.snapshot()['fee_pending_fills'] == 0


def test_contradictory_cancel_rolls_back_and_retains_reservation(session):
    add(session)
    apply(session, '委托 O001 v1 券商单号=B1 数量=1000 限价=10 时间=09:30:10')
    apply(session, fill(quantity=400), 'm2')
    result = apply(session, '撤单确认 O001 v1 券商单号=B1 已撤剩余=1000 时间=09:31:30', 'm3')
    assert result['status'] == 'review'
    assert states(session)['O001'] == 'PARTIAL'
    assert session.book()['holdings']['600000.SH']['quantity'] == 400


def test_actual_higher_submitted_limit_reserves_actual_working_notional(session):
    add(session, quantity=4000)
    result = apply(session, '委托 O001 v1 券商单号=B1 数量=4000 限价=20 时间=09:30:10')
    assert result['status'] == 'processed'
    assert session.book()['cash'] == 100000
    # Actual broker commitment is 80000, despite the original 40000 proposal.
    with pytest.raises(ValueError, match='Insufficient cash'):
        add(session, 'O002', symbol='600001.SH', quantity=3000)


def test_explicit_failure_does_not_count_as_provider_delivery(session):
    add(session)
    session.dispatch(lambda *args: {'provider_accepted': False, 'message_id': 'not-accepted'}, now=at())
    assert outbox(session)['order:O001']['status'] == 'uncertain'
    assert states(session)['O001'] == 'AWAITING_CONFIRMATION'
    assert session.book()['holdings'] == {}
