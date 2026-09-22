"""Import manually supplied fills and cash events without submitting any orders."""
import argparse
import copy
import csv
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

SHANGHAI = dt.timezone(dt.timedelta(hours=8))
KINDS = {'BUY', 'SELL', 'DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'FEE'}


def normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row.get('event_id'), str) or not row['event_id'].strip() or row.get('kind') not in KINDS:
        raise ValueError('Each event requires an external ID and a supported kind')
    timestamp = dt.datetime.fromisoformat(row['timestamp'])
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=SHANGHAI)
    stamp = timestamp.astimezone(SHANGHAI).isoformat()
    kind = row['kind']
    result = {'event_id': row['event_id'], 'timestamp': stamp, 'kind': kind}
    if kind in ('BUY', 'SELL', 'DIVIDEND'):
        if not isinstance(row.get('symbol'), str) or not row['symbol']:
            raise ValueError('A trade or dividend requires a symbol')
        result['symbol'] = row['symbol']
    keys = ('price', 'fee') if kind in ('BUY', 'SELL') else ('amount', 'fee')
    for key in keys:
        value = float(row.get(key, 0.0) if key == 'fee' else row[key])
        if not math.isfinite(value) or value < 0 or (key != 'fee' and value == 0):
            raise ValueError('Event amounts and prices must be finite and positive; fees nonnegative')
        result[key] = value
    if kind in ('BUY', 'SELL'):
        if type(row.get('quantity')) is not int or row['quantity'] <= 0:
            raise ValueError('Actual fill shares must be a positive integer')
        result['quantity'] = row['quantity']
    return result


def import_events(*, state: dict[str, Any], events: list[dict[str, Any]],
                  sessions: tuple[dt.date, ...]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a new cash/share book; repeated IDs are no-op, conflicting IDs fail."""
    if tuple(sorted(set(sessions))) != sessions:
        raise ValueError('Require a sorted unique exchange calendar')
    t0 = state.get('t_plus_zero_symbols', [])
    if not isinstance(t0, list) or not set(t0) <= {'518880.SH', '511010.SH'}:
        raise ValueError('Unverified T+0 instrument')
    book: dict[str, Any] = {key: copy.deepcopy(state.get(key, default)) for key, default in (
        ('date', None), ('cash', 0.0), ('holdings', {}), ('receivables', []),
        ('restricted_shares', []), ('imported_events', {}), ('last_event_timestamp', None))}
    if t0:
        book['t_plus_zero_symbols'] = list(t0)
    opening_date = dt.date.fromisoformat(book['date'])
    if not math.isfinite(book['cash']) or book['cash'] < 0:
        raise ValueError('Invalid opening cash')
    if any(type(row['quantity']) is not int or row['quantity'] < 0 for row in book['holdings'].values()):
        raise ValueError('Invalid opening share quantities')
    normalized = [normalize_event(row) for row in events]
    normalized.sort(key=lambda row: row['timestamp'])
    new, duplicate, fees, external, dividends = [], 0, 0.0, 0.0, 0.0
    for event in normalized:
        identifier = event['event_id']
        if identifier in book['imported_events']:
            if book['imported_events'][identifier] != event:
                raise ValueError(f'External event ID has conflicting content: {identifier}')
            duplicate += 1
            continue
        timestamp = event['timestamp']
        day = dt.datetime.fromisoformat(timestamp).date()
        if ((book['last_event_timestamp'] is None and day <= opening_date)
                or (book['last_event_timestamp'] is not None and timestamp < book['last_event_timestamp'])):
            raise ValueError('New events precede the opening close or last imported event; rebuild from an earlier book')
        kind, fee = event['kind'], event['fee']
        if kind in ('BUY', 'SELL'):
            if day not in sessions:
                raise ValueError('A stock fill must occur on an exchange session')
            symbol, quantity = event['symbol'], event['quantity']
            held = book['holdings'].get(symbol, {}).get('quantity', 0)
            available = held - sum(row['quantity'] for row in book['restricted_shares']
                if row['symbol'] == symbol and row['list_date'] > str(day))
            notional = quantity * event['price']
            if kind == 'SELL':
                if quantity > available:
                    raise ValueError('Actual sell exceeds available T+1 stock shares')
                book['cash'] += notional - fee
                remaining = held - quantity
            else:
                index = sessions.index(day)
                if symbol not in t0 and index + 1 >= len(sessions):
                    raise ValueError('Missing next session for T+1 availability')
                book['cash'] -= notional + fee
                remaining = held + quantity
                if symbol not in t0:
                    book['restricted_shares'].append({'symbol': symbol, 'quantity': quantity,
                                                     'list_date': str(sessions[index+1])})
            if remaining:
                book['holdings'][symbol] = {'quantity': remaining, 'mark_price': event['price']}
            else:
                book['holdings'].pop(symbol, None)
        else:
            amount = event['amount']
            sign = -1 if kind in ('WITHDRAWAL', 'FEE') else 1
            book['cash'] += sign * amount - fee
            if kind in ('DEPOSIT', 'WITHDRAWAL'):
                external += sign * amount
            elif kind == 'DIVIDEND':
                dividends += amount - fee
                unpaid = amount
                for row in book['receivables']:
                    if row['symbol'] == event['symbol'] and row['pay_date'] <= str(day):
                        settled = min(row['amount'], unpaid)
                        row['amount'] -= settled
                        unpaid -= settled
                book['receivables'] = [row for row in book['receivables'] if row['amount'] > 1e-8]
            elif kind == 'FEE':
                fees += amount
        fees += fee
        if not math.isfinite(book['cash']) or book['cash'] < -1e-8:
            raise ValueError('Imported events produce negative or invalid cash')
        book['date'] = str(day)
        book['last_event_timestamp'] = timestamp
        book['imported_events'][identifier] = event
        new.append(event)
    book['restricted_shares'] = [row for row in book['restricted_shares'] if row['list_date'] > book['date']]
    return book, {'message': 'updated' if new else 'no-op', 'imported_count': len(new),
                  'duplicate_count': duplicate, 'fees': fees, 'external_net_flow': external,
                  'cash_dividends': dividends, 'cash': book['cash'], 'positions': len(book['holdings']),
                  'new_events': new, 'scope': 'Cash and share quantities; closing NAV requires current market marks'}


def reconcile_book(book: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    if book['date'] != observed['date']:
        raise ValueError('Reconciliation dates must match')
    difference = book['cash'] - float(observed['cash'])
    if not math.isfinite(difference):
        raise ValueError('Invalid observed cash')
    rows = []
    for symbol in sorted(set(book['holdings']) | set(observed['holdings'])):
        actual = observed['holdings'].get(symbol, {}).get('quantity', 0)
        if type(actual) is not int or actual < 0:
            raise ValueError('Invalid observed share quantities')
        expected = book['holdings'].get(symbol, {}).get('quantity', 0)
        if actual != expected:
            rows.append({'symbol': symbol, 'book_quantity': expected, 'observed_quantity': actual})
    return {'date': book['date'], 'cash_difference': difference,
            'position_differences': rows, 'matched': abs(difference) <= 1e-7 and not rows}


def execution_deviation(events: list[dict[str, Any]], references: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare actual partial fills with signal-close reference prices, by side."""
    planned = {}
    for row in references:
        key = (row['execution_date'], row['symbol'], row['side'])
        price, quantity = float(row['reference_price']), int(row['quantity'])
        if key in planned or not math.isfinite(price) or price <= 0 or quantity <= 0:
            raise ValueError('Require unique, valid reference orders')
        planned[key] = {'price': price, 'quantity': quantity}
    fills: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source in events:
        event = normalize_event(source)
        if event['kind'] not in ('BUY', 'SELL'):
            continue
        key = (event['timestamp'][:10], event['symbol'], event['kind'])
        row = fills.setdefault(key, {'quantity': 0, 'notional': 0.0, 'fees': 0.0})
        row['quantity'] += event['quantity']
        row['notional'] += event['quantity'] * event['price']
        row['fees'] += event['fee']
    rows, adverse, unmatched = [], 0.0, 0
    for key in sorted(set(planned) | set(fills)):
        actual = fills.get(key, {'quantity': 0, 'notional': 0.0, 'fees': 0.0})
        reference = planned.get(key)
        average_price = actual['notional'] / actual['quantity'] if actual['quantity'] else None
        cost = None
        if reference is not None:
            cost = (actual['notional'] - actual['quantity'] * reference['price']) * (1 if key[2] == 'BUY' else -1)
            adverse += cost
        elif actual['quantity']:
            unmatched += 1
        rows.append({'date': key[0], 'symbol': key[1], 'side': key[2], **actual,
                     'average_fill_price': average_price, 'planned_quantity': reference['quantity'] if reference else None,
                     'quantity_difference': actual['quantity'] - reference['quantity'] if reference else None,
                     'adverse_price_cost': cost})
    return {'orders': rows, 'adverse_price_cost': adverse, 'unmatched_fill_groups': unmatched,
            'fees': sum(row['fees'] for row in fills.values()),
            'scope': 'Positive price cost means worse than the signal-close reference; fees separate'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--events', type=Path, required=True, help='JSON list; timestamps use Shanghai time')
    parser.add_argument('--observed', type=Path)
    parser.add_argument('--reference-orders', type=Path, help='Original order reference CSV for fill deviations')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--rehearsal', action='store_true')
    args = parser.parse_args()
    from quant.data.factor_panels import available_sessions

    state = json.loads(args.state.read_text(encoding='utf-8'))
    events = json.loads(args.events.read_text(encoding='utf-8'))
    dates = [dt.datetime.fromisoformat(normalize_event(row)['timestamp']).date() for row in events]
    through = max(dates, default=dt.date.fromisoformat(state['date'])) + dt.timedelta(days=40)
    book, summary = import_events(state=state, events=events, sessions=available_sessions(args.data_root, through))
    if args.observed:
        summary['reconciliation'] = reconcile_book(book, json.loads(args.observed.read_text(encoding='utf-8')))
    if args.reference_orders:
        event_dates = {str(day) for day in dates}
        with args.reference_orders.open(encoding='utf-8-sig', newline='') as stream:
            summary['execution_deviation'] = execution_deviation(
                [row for row in book['imported_events'].values() if row['timestamp'][:10] in event_dates],
                list(csv.DictReader(stream)))
    summary['rehearsal'] = args.rehearsal
    args.output.mkdir(parents=True, exist_ok=False)
    for filename, value in (('book.json', book), ('summary.json', summary)):
        (args.output/filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 手工成交导入与对账' + ('（演练）' if args.rehearsal else ''), '',
        f"新增事件{summary['imported_count']}条；重复跳过{summary['duplicate_count']}条。",
        f"现金{summary['cash']:.2f}元；持仓{summary['positions']}只；本批新增费用{summary['fees']:.2f}元。",
        f"外部净入金{summary['external_net_flow']:.2f}元；现金分红{summary['cash_dividends']:.2f}元。"]
    if args.observed:
        check = summary['reconciliation']
        lines.append(f"对账{'一致' if check['matched'] else '存在差异'}：现金差额{check['cash_difference']:.8f}元，"
                     f"持仓差异{len(check['position_differences'])}项。")
    if args.reference_orders:
        deviation = summary['execution_deviation']
        lines.append(f"相对信号收盘价的不利成交价差{deviation['adverse_price_cost']:.2f}元；"
                     f"成交费用{deviation['fees']:.2f}元；缺少参考的成交组{deviation['unmatched_fill_groups']}项。")
    lines += ['', '本表核对现金与股数；净值需另接当日收盘估值。']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key != 'new_events'}))


if __name__ == '__main__':
    main()
