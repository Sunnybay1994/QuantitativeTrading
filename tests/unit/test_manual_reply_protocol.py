import pytest

from quant.execution.manual_reply_protocol import parse_reply


SUBMITTED = '委托 O001 v1 券商单号=B123 数量=1000 限价=10.52 时间=09:31:05'
FILL = '成交 O001 v1 成交号=F456 本次数量=400 成交价=10.50 时间=09:31:18 费用=待核'


@pytest.mark.parametrize(('text', 'expected'), [
    (SUBMITTED, {'kind': 'SUBMITTED', 'broker_order_id': 'B123', 'quantity': 1000,
                 'price': '10.52', 'execution_time': '09:31:05'}),
    (FILL, {'kind': 'FILL', 'broker_trade_id': 'F456', 'quantity': 400,
            'price': '10.5', 'execution_time': '09:31:18', 'fee': None}),
    ('撤单确认 O001 v1 券商单号=B123 已撤剩余=600 时间=09:34:10',
     {'kind': 'CANCELLED', 'broker_order_id': 'B123', 'quantity': 600, 'execution_time': '09:34:10'}),
    ('未操作 O001 v1 确认未委托=是 原因=错过窗口', {'kind': 'NOT_SUBMITTED', 'reason': '错过窗口'}),
    ('查单 O001 v1 状态=已委托未确认成交 券商单号=B125',
     {'kind': 'QUERY', 'status': '已委托未确认成交', 'broker_order_id': 'B125'}),
    ('费用确认 O001 v1 成交号=F456 费用=5.00', {'kind': 'FEE', 'broker_trade_id': 'F456', 'fee': '5'}),
])
def test_explicit_events(text, expected):
    assert parse_reply(text) == {'order_id': 'O001', 'version': 1, **expected}


def test_horizontal_unicode_whitespace_and_field_order():
    assert parse_reply('  委托\u3000O001\tv1 时间=09:31:05 限价=10.52 数量=1000 券商单号=B123  ') == parse_reply(SUBMITTED)


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '+1', '1e2', '0', '0.000', 'True', '１０', '.5', '1.', '1,000'])
def test_invalid_price(value):
    with pytest.raises(ValueError):
        parse_reply(SUBMITTED.replace('10.52', value))


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '+1', '1e2', 'True', '５', '待核'])
def test_invalid_confirmed_fee(value):
    with pytest.raises(ValueError):
        parse_reply(f'费用确认 O001 v1 成交号=F456 费用={value}')


def test_fee_zero_and_decimal_precision_preserved():
    assert parse_reply(FILL.replace('待核', '0.00'))['fee'] == '0'
    assert parse_reply(FILL.replace('10.50', '1234567890123456.12345678'))['price'] == '1234567890123456.12345678'


@pytest.mark.parametrize('value', ['0', '-1', 'True', 'false', '1.0', '+1', '１', '01', '1000000000000'])
def test_invalid_quantity(value):
    with pytest.raises(ValueError):
        parse_reply(SUBMITTED.replace('数量=1000', f'数量={value}'))


@pytest.mark.parametrize('value', ['v0', 'v-1', 'v01', 'V1', 'v1.0', 'vTrue', 'v１', 'v1000000000'])
def test_invalid_version(value):
    with pytest.raises(ValueError):
        parse_reply(SUBMITTED.replace('v1', value))


@pytest.mark.parametrize('value', ['24:00:00', '09:60:00', '09:30:60', '9:30:00', '09:31', '2026-09-21T09:31:05+08:00'])
def test_invalid_execution_time(value):
    with pytest.raises(ValueError):
        parse_reply(SUBMITTED.replace('09:31:05', value))


@pytest.mark.parametrize('text', [
    SUBMITTED + ' 数量=1000', SUBMITTED + ' 证券=600000.SH', SUBMITTED.replace(' 数量=1000', ''),
    SUBMITTED.replace('数量=1000', '数量='), SUBMITTED.replace('数量=1000', '数量==1000'),
    SUBMITTED.replace('O001', '../O001'), SUBMITTED.replace('O001', 'O' * 65),
    SUBMITTED.replace('B123', 'B/123'), SUBMITTED.replace('B123', 'B\u200b123'),
    SUBMITTED + '\n' + FILL, SUBMITTED + '\n', SUBMITTED + '\u2028', SUBMITTED + '\x00',
    '收到 O001 v1', '买入 O001 v1', '委托 O001', '', None, 1,
    '未操作 O001 v1 确认未委托=否 原因=错过窗口',
    '未操作 O001 v1 确认未委托=是 原因=' + 'a' * 121,
    '查单 O001 v1 状态=已成交 券商单号=B125',
])
def test_rejects_ambiguous_or_incomplete_messages(text):
    with pytest.raises(ValueError):
        parse_reply(text)
