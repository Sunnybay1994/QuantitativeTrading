"""Close a manual cash/share book with known prices and flow-adjusted returns."""
import argparse
import copy
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import polars as pl

from quant.backtest.daily_account import capture_record_date_entitlements, prepare_account_actions
from quant.execution.manual_fills import SHANGHAI, import_events, normalize_event, reconcile_book


def close_manual_day(*, opening: dict[str, Any], events: list[dict[str, Any]], date: dt.date,
                     bars: pl.DataFrame, calendar: pl.DataFrame, dividends: pl.DataFrame,
                     suspensions: pl.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    prior = dt.date.fromisoformat(opening['date'])
    normalized = [normalize_event(row) for row in events]
    saved = opening.get('imported_events', {})
    if date == prior:
        if all(saved.get(row['event_id']) == row for row in normalized) and opening.get('valuation'):
            return copy.deepcopy(opening), {'message': 'no-op', 'date': str(date)}
        raise ValueError('A closed date can only be repeated with already recorded events')
    sessions = tuple(calendar.filter(pl.col('is_open'))['date'].unique().sort().to_list())
    following = [day for day in sessions if day > prior]
    if not following or following[0] != date:
        raise ValueError('Close each exchange session in order; do not skip company actions')
    start = dt.datetime.combine(prior, dt.time(15), SHANGHAI)
    end = dt.datetime.combine(date, dt.time(15), SHANGHAI)
    fresh = [row for row in normalized if row['event_id'] not in saved]
    if any(not start < dt.datetime.fromisoformat(row['timestamp']) <= end for row in fresh):
        raise ValueError('New events must fall after the prior close and through this close')
    equity0 = float(opening['cash']) + sum(row['quantity'] * row['mark_price']
        for row in opening['holdings'].values()) + sum(row['amount'] for row in opening.get('receivables', []))
    if not math.isfinite(equity0) or equity0 <= 0:
        raise ValueError('Opening close equity must be positive')
    if opening.get('valuation'):
        unit0 = float(opening['valuation']['unit_nav'])
        if not math.isclose(equity0, opening['valuation']['equity'], abs_tol=1e-7):
            raise ValueError('Opening book differs from its closing valuation')
    elif opening.get('nav') and opening['nav'][-1]['date'] == str(prior):
        unit0 = float(opening['nav'][-1]['unit_nav'])
        if not math.isclose(equity0, opening['nav'][-1]['equity'], abs_tol=1e-7):
            raise ValueError('Opening paper quantities differ from the closing NAV')
    elif not opening['holdings'] and not opening.get('receivables') and not saved and not opening.get('nav'):
        unit0 = 1.0
    else:
        raise ValueError('Require a dated closing valuation for the opening book')
    prepared = prepare_account_actions(date=date, state=opening, calendar=calendar,
                                       dividends=dividends, settle_cash=False)
    source = {**copy.deepcopy(opening), **prepared}
    source['last_event_timestamp'] = start.isoformat()
    book, imported = import_events(state=source, events=normalized, sessions=sessions)
    book['date'] = str(date)
    for key in ('inception_date', 'started_with_cash'):
        if key in opening:
            book[key] = opening[key]
    for key in ('share_reduction_entitlements', 'share_distribution_entitlements'):
        if prepared[key]:
            book[key] = prepared[key]
    current = bars.filter(pl.col('trade_date') == date)
    if current['symbol'].is_duplicated().any():
        raise ValueError('Duplicate closing prices')
    marks = dict(current.select('symbol', 'close').iter_rows())
    suspended = set(suspensions.filter(pl.col('trade_date') == date)['symbol'])
    carried = []
    for symbol, holding in book['holdings'].items():
        if symbol not in marks:
            if symbol not in suspended or symbol not in prepared['holdings']:
                raise ValueError('Missing closing price without an official suspension')
            marks[symbol] = prepared['holdings'][symbol]['mark_price']
            carried.append(symbol)
        if not math.isfinite(marks[symbol]) or marks[symbol] <= 0:
            raise ValueError('Invalid closing price')
        holding['mark_price'] = marks[symbol]
    market_value = sum(row['quantity'] * row['mark_price'] for row in book['holdings'].values())
    receivable = sum(row['amount'] for row in book['receivables'])
    equity = book['cash'] + market_value + receivable
    cash_flows = [row for row in imported['new_events'] if row['kind'] in ('DEPOSIT', 'WITHDRAWAL')]
    weighted = sum((1 if row['kind'] == 'DEPOSIT' else -1) * row['amount']
        * (end-dt.datetime.fromisoformat(row['timestamp'])).total_seconds() / (end-start).total_seconds()
        for row in cash_flows)
    denominator = equity0 + weighted
    if not math.isfinite(denominator) or denominator <= 0 or not math.isfinite(equity) or equity < 0:
        raise ValueError('Flow-adjusted capital or ending equity is invalid')
    daily_return = (equity-equity0-imported['external_net_flow']) / denominator
    if daily_return < -1:
        raise ValueError('Flow-adjusted loss exceeds supported unlevered capital')
    valuation = {'date': str(date), 'cash': book['cash'], 'market_value': market_value,
                 'receivable': receivable, 'equity': equity, 'daily_return': daily_return,
                 'unit_nav': unit0 * (1+daily_return), 'external_net_flow': imported['external_net_flow'],
                 'weighted_external_flow': weighted, 'method': 'daily_modified_dietz',
                 'carried_suspended_symbols': sorted(carried)}
    book['valuation'] = valuation
    initial_nav = opening.get('nav') or [{'date': str(prior), 'equity': equity0, 'unit_nav': unit0}]
    book['nav'] = [*initial_nav, valuation]
    book['cumulative_fees'] = opening.get('cumulative_fees', 0.0) + imported['fees']
    capture_record_date_entitlements(date=date, state=book, dividends=dividends)
    return book, {'message': 'updated', 'valuation': valuation, 'imported_count': imported['imported_count']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opening', type=Path, required=True)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--to', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--observed', type=Path)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--paper-config', type=Path, default=Path('configs/paper/b32_stock_observation_20260909.toml'))
    parser.add_argument('--rehearsal', action='store_true')
    args = parser.parse_args()
    from quant.data.manual_nav_inputs import read_manual_nav_inputs

    opening = json.loads(args.opening.read_text(encoding='utf-8'))
    events = json.loads(args.events.read_text(encoding='utf-8'))
    symbols = sorted(set(opening['holdings']) | {row['symbol'] for row in events if row.get('symbol')})
    inputs = read_manual_nav_inputs(data_root=args.data_root, config=args.paper_config,
                                   symbols=symbols, date=args.to)
    book, result = close_manual_day(opening=opening, events=events, date=args.to, **inputs)
    if args.observed:
        result['reconciliation'] = reconcile_book(book, json.loads(args.observed.read_text(encoding='utf-8')))
    result['rehearsal'] = args.rehearsal
    if result['message'] == 'no-op':
        print(json.dumps(result))
        return
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (('state.json', book), ('summary.json', result)):
        (args.output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    pl.from_dicts(book['nav'], infer_schema_length=None).select(
        'date', 'cash', 'market_value', 'receivable', 'equity', 'unit_nav', 'daily_return',
        'external_net_flow', 'weighted_external_flow').write_csv(args.output/'nav.csv')
    v = result['valuation']
    text = f"# 手工账本收盘净值{'（演练）' if args.rehearsal else ''}\n\n"
    text += f"{v['date']}：权益{v['equity']:.2f}元，单位净值{v['unit_nav']:.8f}，当日收益{v['daily_return']:.4%}。\n"
    text += f"外部净入金{v['external_net_flow']:.2f}元；应收分红{v['receivable']:.2f}元。\n\n"
    text += '出入金按实际时点使用日度Modified Dietz近似；无出入金时为相邻收盘权益收益。\n'
    (args.output/'report.md').write_text(text, encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
