"""Independent daily P&L reconciliation against holdings, marks, actions and fills."""
import datetime as dt
import math
from pathlib import Path

import polars as pl

MAX_UNEXPLAINED_RETURN = .02
SHARE_ACTIONS = {'SHARE_SPLIT', 'SHARE_CONSOLIDATION', 'SHARE_CONVERSION'}


def check_transition(*, date, previous, actual_equity, bars, dividends, trades,
                     external_cash_flow=0., maximum_difference=MAX_UNEXPLAINED_RETURN):
    """Do not reuse prepare_account_actions or the simulator's resulting marks.

    End equity is reconstructed independently from the previous economic book,
    actual daily closes (or action-adjusted carried marks on suspension), action
    entitlements, recorded execution cash flows and fees. None means the default
    economic price adjustment; only explicit False means an uncompensated issue.
    """
    holdings = {s:dict(h) for s,h in previous['holdings'].items()}
    starting_book = float(previous['cash']) + sum(
        h['quantity']*h['mark_price'] for h in holdings.values()) + sum(
        r['amount'] for r in previous['receivables'])
    prior_equity = previous['nav'][-1]['equity'] if previous.get('nav') else starting_book
    if not math.isfinite(prior_equity) or prior_equity <= 0:
        raise ValueError('Invalid prior equity for return reconciliation')
    cash_and_claims = float(previous['cash']) + sum(r['amount'] for r in previous['receivables'])
    cash_and_claims += external_cash_flow
    action_count = 0
    for event in dividends.filter(pl.col('ex_date')==date).iter_rows(named=True):
        symbol=event['symbol'];ratio=event.get('share_ratio') or 0.
        holding=holdings.get(symbol,{'quantity':0,'mark_price':0.})
        quantity=holding['quantity']
        distribution=previous.get('share_distribution_entitlements',{}).get(f'{symbol}|{date}')
        entitled=distribution['quantity'] if ratio>0 and distribution is not None else quantity
        cash_and_claims += entitled*event['div_cash']
        if quantity or entitled:
            action_count += 1
        if ratio:
            if ratio <= -1 or not math.isfinite(ratio):
                raise ValueError('Invalid share action ratio for return reconciliation')
            if ratio<0:
                new_quantity=math.floor(quantity*(1+ratio)+1e-9)
            else:
                new_quantity=quantity+math.floor(entitled*ratio+1e-9)
            mark=holding['mark_price'] or (distribution or {}).get('mark_price',0.)
            economic=(event.get('action_type') in SHARE_ACTIONS or
                      ratio>0 and event.get('adjust_share_price') is not False)
            if economic:
                mark /= 1+ratio
            if new_quantity:
                holdings[symbol]={'quantity':new_quantity,'mark_price':mark}
            else:
                holdings.pop(symbol,None)
    today=bars.filter(pl.col('trade_date')==date)
    marks=dict(today.select('symbol','close').iter_rows())
    expected_equity=cash_and_claims
    for symbol,holding in holdings.items():
        mark=marks.get(symbol,holding['mark_price'])
        if not math.isfinite(mark) or mark<=0:
            raise ValueError(f'Invalid expected closing mark: {symbol} {date}')
        marks[symbol]=mark
        expected_equity += holding['quantity']*mark
    for trade in trades.iter_rows(named=True):
        symbol=trade['symbol']
        if symbol not in marks:
            raise ValueError(f'Execution without independently observable close: {symbol} {date}')
        direction=1 if trade['side']=='BUY' else -1
        expected_equity += direction*trade['quantity']*(marks[symbol]-trade['price'])-trade['fee']
    difference=(float(actual_equity)-expected_equity)/prior_equity
    result={'date':str(date),'previous_equity':prior_equity,'expected_equity':expected_equity,
        'actual_equity':float(actual_equity),'account_return':float(actual_equity)/prior_equity-1,
        'market_expected_return':expected_equity/prior_equity-1,
        'unexplained_return':difference,'maximum_difference':maximum_difference,
        'corporate_actions':action_count,'external_cash_flow':external_cash_flow,
        'fees':float(trades['fee'].sum()),'passed':abs(difference)<=maximum_difference}
    if not all(math.isfinite(result[k]) for k in
               ['expected_equity','actual_equity','unexplained_return']):
        raise ValueError('Nonfinite daily return reconciliation')
    if not result['passed']:
        raise ValueError(f'UNEXPLAINED_NAV_JUMP date={date} '
                         f'actual_return={result["account_return"]:.8f} '
                         f'expected_return={result["market_expected_return"]:.8f} '
                         f'unexplained={difference:.8f}')
    return result


def validate_nav(nav, *, label='replay'):
    """Registration rechecks numerical evidence, not a producer's pass label."""
    required={'reconciliation_expected_equity','reconciliation_previous_equity',
              'reconciliation_unexplained_return'}
    if not required<=set(nav.columns) or nav.is_empty():
        raise ValueError(f'Missing independent account reconciliation: {label}')
    values=nav.select('equity',*sorted(required))
    if values.null_count().sum_horizontal().item() or not values.select(pl.all().is_finite().all()).row(0)==(True,)*4:
        raise ValueError(f'Invalid account reconciliation evidence: {label}')
    errors=nav.with_columns(((pl.col('equity')-pl.col('reconciliation_expected_equity'))/
        pl.col('reconciliation_previous_equity')).alias('_difference'))
    if errors.filter((pl.col('_difference').abs()>MAX_UNEXPLAINED_RETURN) |
        ((pl.col('_difference')-pl.col('reconciliation_unexplained_return')).abs()>1e-10)).height:
        raise ValueError(f'UNEXPLAINED_NAV_JUMP in {label}')
    return {'rows':nav.height,'maximum_unexplained_return':float(errors['_difference'].abs().max()),
            'maximum_difference':MAX_UNEXPLAINED_RETURN,'passed':True}


def validate_registered_account(root, receipt):
    checked=[]
    for entry in receipt['completed']:
        path=Path(entry['path'])/'nav.parquet'
        checked.append({'path':str(path),**validate_nav(pl.read_parquet(path),label=str(path))})
    if not checked:
        raise ValueError('No completed account ledgers to reconcile')
    return checked
