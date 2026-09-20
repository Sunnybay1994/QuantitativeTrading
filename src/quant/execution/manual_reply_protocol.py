"""Strict, deterministic parsing of one manual execution reply (no I/O or LLM)."""

import re
from decimal import Decimal
from typing import Any

_SCHEMAS = {
    '委托': ('SUBMITTED', {'券商单号', '数量', '限价', '时间'}),
    '成交': ('FILL', {'成交号', '本次数量', '成交价', '时间', '费用'}),
    '撤单确认': ('CANCELLED', {'券商单号', '已撤剩余', '时间'}),
    '未操作': ('NOT_SUBMITTED', {'确认未委托', '原因'}),
    '查单': ('QUERY', {'状态', '券商单号'}),
    '费用确认': ('FEE', {'成交号', '费用'}),
}
_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', re.ASCII)
_INTEGER = re.compile(r'[1-9][0-9]{0,11}', re.ASCII)
_DECIMAL = re.compile(r'[0-9]{1,16}(?:\.[0-9]{1,8})?', re.ASCII)
_TIME = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]', re.ASCII)


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError('Identifier must contain 1-64 ASCII letters, digits, underscores or hyphens')
    return value


def _decimal(value: str, *, zero_allowed: bool) -> str:
    if not _DECIMAL.fullmatch(value):
        raise ValueError('Price or fee must be a finite unsigned decimal, without exponent notation')
    number = Decimal(value)
    if not zero_allowed and number == 0:
        raise ValueError('Price must be positive')
    # No floating-point conversion or context-dependent Decimal.normalize rounding.
    integer, dot, fraction = format(number, 'f').partition('.')
    fraction = fraction.rstrip('0')
    return integer + (dot + fraction if fraction else '')


def parse_reply(text: str) -> dict[str, Any]:
    """Parse one Chinese command, or raise ValueError without guessing any field.

    All results contain kind (str), order_id (str), version (positive int).
    SUBMITTED adds broker_order_id (str), quantity (positive int), price (decimal
    str), execution_time (HH:mm:ss str). FILL adds broker_trade_id (str), quantity,
    price, execution_time, fee (nonnegative decimal str or None for 待核).
    CANCELLED adds broker_order_id, quantity (cancelled remainder, positive int),
    execution_time. NOT_SUBMITTED adds reason (str), after requiring explicit
    确认未委托=是. QUERY adds broker_order_id and status (str, exactly
    已委托未确认成交). FEE adds broker_trade_id and fee (known decimal str).

    Horizontal Unicode whitespace is accepted between tokens; line separators,
    invisible control characters, unknown/duplicate/missing fields are rejected.
    Prices are not tick-rounded. Order/account/date binding, event idempotency,
    quantity limits and execution-time validity belong to the stateful consumer.
    """
    if not isinstance(text, str) or not text or len(text) > 1024:
        raise ValueError('Reply must be a nonempty string of at most 1024 characters')
    if any(c in '\r\n\v\f\x85\u2028\u2029' or (ord(c) < 32 and c != '\t')
           or ord(c) == 127 for c in text):
        raise ValueError('Only one reply per message is supported')
    tokens = text.split()
    if len(tokens) < 3 or tokens[0] not in _SCHEMAS:
        raise ValueError('Unknown command or missing order/version')
    kind, required = _SCHEMAS[tokens[0]]
    order_id = _identifier(tokens[1])
    if not re.fullmatch(r'v[1-9][0-9]{0,8}', tokens[2], flags=re.ASCII):
        raise ValueError('Version must be v followed by a positive integer')
    fields: dict[str, str] = {}
    for token in tokens[3:]:
        if token.count('=') != 1:
            raise ValueError('Every field must use key=value without embedded whitespace')
        key, value = token.split('=', 1)
        if key not in required or key in fields or not value:
            raise ValueError('Unknown, duplicate or empty field')
        fields[key] = value
    if fields.keys() != required:
        raise ValueError('Missing required field')
    result: dict[str, Any] = {'kind': kind, 'order_id': order_id, 'version': int(tokens[2][1:])}
    for source, target in (('券商单号', 'broker_order_id'), ('成交号', 'broker_trade_id')):
        if source in fields:
            result[target] = _identifier(fields[source])
    for source in ('数量', '本次数量', '已撤剩余'):
        if source in fields:
            if not _INTEGER.fullmatch(fields[source]):
                raise ValueError('Quantity must be a positive ASCII integer of at most 12 digits')
            result['quantity'] = int(fields[source])
    for source in ('限价', '成交价'):
        if source in fields:
            result['price'] = _decimal(fields[source], zero_allowed=False)
    if '费用' in fields:
        result['fee'] = (None if kind == 'FILL' and fields['费用'] == '待核'
                         else _decimal(fields['费用'], zero_allowed=True))
    if '时间' in fields:
        if not _TIME.fullmatch(fields['时间']):
            raise ValueError('Execution time must be HH:mm:ss')
        result['execution_time'] = fields['时间']
    if kind == 'NOT_SUBMITTED':
        if fields['确认未委托'] != '是':
            raise ValueError('Not submitted requires explicit confirmation 确认未委托=是')
        if len(fields['原因']) > 120 or not all(c.isprintable() for c in fields['原因']):
            raise ValueError('Reason must be printable and at most 120 characters')
        result['reason'] = fields['原因']
    if kind == 'QUERY':
        if fields['状态'] != '已委托未确认成交':
            raise ValueError('Unsupported query status; use the corresponding explicit event command')
        result['status'] = fields['状态']
    return result
