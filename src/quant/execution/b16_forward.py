"""Frozen B16 local paper lifecycle; no broker or messaging transport."""
import copy
import datetime as dt
import hashlib
import json
import math
import tomllib
from pathlib import Path

import polars as pl

from quant.backtest.daily_account import prepare_account_actions
from quant.data.realtime_inputs import TZ
from quant.data.realtime_store import atomic_json
from quant.execution.etf_quote_paper import simulate, stamp
from quant.execution.manual_nav import close_manual_day
from quant.execution.manual_fills import import_events
from quant.execution.manual_session_service import instance_lock
from quant.strategies.inverse_volatility import InverseVolatilityStrategy

ROOT = Path('artifacts/paper/b16_manual_v1')
CONFIG = Path('configs/research/b16_manual_forward_v1.toml')
SYMBOLS = ['510300.SH', '511010.SH', '518880.SH']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def settings(root):
    cfg = tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    if ((root/'config.toml').read_bytes() != CONFIG.read_bytes()
            or digest(root/'config.toml') != read(root/'bootstrap.json')['config_sha256']
            or cfg['auto_trade'] is not False or cfg['capital'] != 100000
            or cfg['symbols'] != SYMBOLS or cfg['cost_multipliers'] != [.5, 1., 2.]
            or (cfg['main_delay_seconds'], cfg['shadow_delay_seconds']) != (120, 60)):
        raise ValueError('Frozen B16 controls changed')
    return cfg


def scenarios(root):
    return [(root/f'delay_{delay}/cost_{cost:g}', delay, cost)
            for delay in (120, 60) for cost in (.5, 1., 2.)]


def clock(day, time):
    return dt.datetime.combine(day, dt.time.fromisoformat(time), TZ)


def load_frames(data_root, day):
    from quant.data.publish_cross_asset_etfs import read_cross_asset_etfs
    name = f'b20_forward_{day:%Y%m%d}'
    frames = read_cross_asset_etfs(data_root, name)
    if frames['bars']['trade_date'].max() != day:
        raise ValueError('B16 needs completed same-day ETF inputs')
    return frames, {str(p): digest(p) for p in (data_root/'clean/etf_cross_asset'/name).glob('*') if p.is_file()}


def freeze_signal(book, prices, bars, sessions, day, now, cfg):
    """All sizes depend on this account's actual close and 61 completed TR marks."""
    following = next(d for d in sessions if d > day)
    if following.month == day.month or day < cfg['first_signal_date']:
        raise ValueError('Not a registered month-end signal')
    if now < clock(day, '15:00') or str(day) != book['date']:
        raise ValueError('Signal requires a completed account close')
    expected = [d for d in sessions if d <= day][-61:]
    panel = prices.filter(pl.col('trade_date').is_in(expected)).sort('trade_date')
    for symbol in SYMBOLS:
        if panel.filter(pl.col('symbol') == symbol)['trade_date'].to_list() != expected or len(expected) != 61:
            raise ValueError('Incomplete 61-session total-return signal panel')
    targets = InverseVolatilityStrategy(tuple(SYMBOLS), 60).target_weights(day, panel)
    close = bars.filter(pl.col('trade_date') == day)
    if close.height != 3 or set(close['symbol']) != set(SYMBOLS):
        raise ValueError('Missing or duplicate signal closes')
    marks = dict(close.select('symbol', 'close').iter_rows())
    if any(not math.isfinite(p) or p <= 0 for p in marks.values()):
        raise ValueError('Invalid signal-close mark')
    equity = book['cash'] + sum(h['quantity']*marks[s] for s, h in book['holdings'].items()) + sum(r['amount'] for r in book.get('receivables', []))
    if not math.isclose(equity, book['valuation']['equity'], abs_tol=1e-7):
        raise ValueError('Signal equity does not reconcile')
    orders = []
    for row in targets.to_dicts():
        symbol = row['symbol']
        target = math.floor(row['weight']*equity/marks[symbol]/100)*100
        held = book['holdings'].get(symbol, {}).get('quantity', 0)
        delta = target-held
        if delta:
            orders.append(dict(order_id=f'{following}:{symbol}', symbol=symbol,
                               side='BUY' if delta > 0 else 'SELL', quantity=abs(delta)))
    return dict(signal_date=str(day), execution_date=str(following), ready_at=now.isoformat(),
                signal_equity=equity, close_prices=marks, holdings=copy.deepcopy(book['holdings']),
                targets=targets.select('symbol', 'weight').to_dicts(), orders=orders,
                classification='RESEARCH_ONLY', auto_trade=False)


def submit(plan, day, now, delay, limits):
    """Use the actual submission time, never fabricate an earlier post-reboot time."""
    deadline = clock(day, '09:40')
    if now.date() != day:
        raise ValueError('Submission must be recorded on the actual session')
    due = max(clock(day, '09:30'), stamp(plan['ready_at'])) + dt.timedelta(seconds=delay)
    if now < due:
        return None
    if now >= deadline:
        return dict(submitted_at=None, orders=[], reason='missed_window', ready_at=plan['ready_at'])
    if plan['execution_date'] != str(day):
        raise ValueError('Wrong execution session')
    if any(o['symbol'] not in limits for o in plan['orders']):
        return None
    orders = []
    for order in sorted(plan['orders'], key=lambda o: (o['side'] != 'SELL', o['symbol'])):
        band = limits[order['symbol']]
        if not 0 < band['down_limit'] < band['up_limit']:
            raise ValueError('Invalid official execution-day limits')
        orders.append(dict(order, submitted_at=now.isoformat(), deadline=deadline.isoformat(),
                           limit=band['up_limit'] if order['side'] == 'BUY' else band['down_limit']))
    return dict(submitted_at=now.isoformat(), ready_at=plan['ready_at'], due_at=due.isoformat(),
                orders=orders, limits=limits, reason='local_model_submission')


def finalize(folder, day, sessions, dividends, calendar):
    """Atomic result replay from frozen inputs makes crash/restart duplication impossible."""
    directory = folder/str(day)
    receipt = directory/'execution.json'
    if receipt.exists():
        return read(receipt)
    state = read(folder/'state.json') if (folder/'state.json').exists() else read(folder/'opening.json')
    if state['date'] >= str(day):
        raise ValueError('Execution opening is not a prior close')
    submission = read(directory/'submission.json') if (directory/'submission.json').exists() else {'orders': [], 'reason': 'no_submission_record'}
    quotes = [r for p in sorted((folder.parents[1]/'quotes'/str(day)).glob('*.json')) for r in read(p)['quotes']]
    prepared = {**copy.deepcopy(state), **prepare_account_actions(date=day, state=state,
                calendar=calendar, dividends=dividends, settle_cash=False)}
    payments = [dict(event_id=f'dividend:{day}:{i}:{r["symbol"]}', timestamp=clock(day, '09:30').isoformat(),
                     kind='DIVIDEND', symbol=r['symbol'], amount=r['amount'], fee=0.)
                for i, r in enumerate(prepared['receivables']) if r['pay_date'] <= str(day)]
    if payments:
        prepared, _ = import_events(state=prepared, events=payments, sessions=tuple(sessions))
    book, events, orders = simulate(prepared, submission['orders'], quotes, tuple(sessions),
                                    as_of=clock(day, '09:40').isoformat(), cost=float(folder.name[5:]))
    result = dict(opening=state, book=book, events=payments+events, orders=orders, submission=submission,
                  quote_packets=len(list((folder.parents[1]/'quotes'/str(day)).glob('*.json'))),
                  auto_trade=False, classification='RESEARCH_ONLY', model_only=True)
    if not submission.get('submitted_at') and (directory/'signal.json').exists():
        result['unsubmitted'] = [dict(o, remaining=o['quantity'], status='CANCELLED_NOT_SUBMITTED')
                                for o in read(directory/'signal.json')['orders']]
    atomic_json(receipt, result)
    return result


def daily(*, end, now=None, root=ROOT, data_root=Path('data'), rehearsal=False):
    actual_clock = now is None
    now = now or dt.datetime.now(TZ)
    if rehearsal:
        return dict(status='rehearsal_skipped')
    cfg = settings(root)
    if now < clock(end, '15:00'):
        raise ValueError('Cannot close future or unfinished session')
    if end < cfg['first_signal_date']:
        result = dict(status='pending_first_signal', first_signal=str(cfg['first_signal_date']),
                      first_execution=str(cfg['first_execution_date']), performance=None, auto_trade=False)
        atomic_json(root/'daily_status.json', result)
        return result
    frames, hashes = load_frames(data_root, end)
    sessions = sorted(set(frames['calendar'].filter(pl.col('is_open'))['date'].to_list()))
    results = []
    with instance_lock(root/'forward.lock'):
        for folder, delay, cost in scenarios(root):
            book = read(folder/'state.json') if (folder/'state.json').exists() else read(folder/'opening.json')
            if book['date'] > str(end):
                raise ValueError('Cannot rewind a forward account')
            book['t_plus_zero_symbols'] = ['511010.SH', '518880.SH']
            for day in [d for d in sessions if book['date'] < str(d) <= str(end)]:
                directory = folder/str(day)
                receipt = directory/'close.json'
                if receipt.exists():
                    book = read(receipt)['book']
                else:
                    execution = finalize(folder, day, sessions, frames['dividends'], frames['calendar']) if day >= cfg['first_execution_date'] else None
                    events = execution['events'] if execution else []
                    book, result = close_manual_day(opening=book, events=events, date=day,
                        bars=frames['bars'], calendar=frames['calendar'], dividends=frames['dividends'],
                        suspensions=pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date}))
                    if execution:
                        if abs(book['cash']-execution['book']['cash']) > 1e-7 or {
                            s: h['quantity'] for s, h in book['holdings'].items()} != {
                            s: h['quantity'] for s, h in execution['book']['holdings'].items()}:
                            raise ValueError('Execution and closing ledger differ')
                    atomic_json(receipt, dict(book=book, result=result, inputs=hashes, captured_at=now.isoformat()))
                atomic_json(folder/'state.json', book)
            following = next(d for d in sessions if d > end)
            signal_path = folder/str(following)/'signal.json'
            registered = [a for a,b in zip(sessions,sessions[1:]) if a >= cfg['first_signal_date']
                          and a.month != b.month][:cfg['observation_rebalances']]
            if end in registered and not signal_path.exists():
                plan = freeze_signal(book, frames['prices'], frames['bars'], sessions, end, now, cfg)
                plan['inputs'] = hashes
                plan['signal_prices'] = [{**r, 'trade_date': str(r['trade_date'])} for r in
                    frames['prices'].filter(pl.col('trade_date') <= end).sort('trade_date','symbol').tail(183).to_dicts()]
                if actual_clock:
                    plan['ready_at'] = dt.datetime.now(TZ).isoformat()
                atomic_json(signal_path, plan)
            submitted = [read(p) for p in sorted(folder.glob('????-??-??/submission.json'))]
            inception = next((stamp(s['submitted_at']).date() for s in submitted if s.get('submitted_at')), None)
            performance = [r for r in book['nav'] if inception is not None and r['date'] >= str(inception)]
            atomic_json(folder/'performance.json', dict(inception=str(inception) if inception else None,
                nav=performance, excludes_initial_cash_period=True, classification='RESEARCH_ONLY', model_only=True))
            results.append(dict(delay=delay, cost=cost, as_of=book['date'], equity=book['valuation']['equity'],
                                performance_sessions=len(performance)))
        result = dict(status='complete', as_of=str(end), accounts=results, auto_trade=False)
        atomic_json(root/'daily_status.json', result)
        return result
