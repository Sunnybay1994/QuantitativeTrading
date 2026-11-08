"""R4 daily-fill stress veto; never changes signals, prices, fees or retry age."""
from decimal import Decimal

import polars as pl


def filter_orders(*,orders,limits,bars,date,strategy,tick_cny=.01,amount_multiple=20):
    if tick_cny!=.01 or amount_multiple!=20:
        raise ValueError('R4 freezes one A-share cent and twenty times attempted quote notional')
    schema={'strategy':pl.String,'date':pl.Date,'symbol':pl.String,'side':pl.String,'reason':pl.String,
        'requested_quantity':pl.Int64,'rejected_quantity':pl.Int64,'reference_price':pl.Float64}
    rejected=[];details=[];keep=[]
    quotes={r['symbol']:r for r in bars.iter_rows(named=True)}
    if len(quotes)!=bars.height:
        raise ValueError('Pessimistic matching requires unique same-session bars')
    if bars.height and set(bars['trade_date'])!={date}:
        raise ValueError('Do not use a stale bar to authorize execution')
    for row in orders.iter_rows(named=True):
        key=row['symbol'],row['side']
        if limits is None or key not in limits:
            raise ValueError('Pessimistic fill scenario requires the actual adjusted limit')
        bar=quotes.get(row['symbol']);quantity=row['quantity']
        limit=Decimal(str(limits[key]));tick=Decimal(str(tick_cny))
        notional=limit*quantity
        if not limit.is_finite() or limit<=0 or quantity<=0:
            raise ValueError('Invalid original remaining share order')
        if bar is None:
            keep.append(True)
            details.append({**row,'date':date,'limit':float(limit),'requested_notional':float(notional),
                'crossed_one_tick':None,'amount_sufficient':None,'allowed_by_diagnostic':None,
                'diagnostic_reason':'BASELINE_MISSING_CURRENT_BAR'})
            continue
        extreme=Decimal(str(bar['low'] if row['side']=='BUY' else bar['high']))
        amount=Decimal(str(bar['amount'])) if bar.get('amount') is not None else Decimal('NaN')
        crossed=extreme.is_finite() and (extreme<=limit-tick if row['side']=='BUY' else extreme>=limit+tick)
        liquid=amount.is_finite() and amount>=amount_multiple*notional
        permitted=bool(crossed and liquid);keep.append(permitted)
        reason='PASSED' if permitted else 'ONE_TICK_NOT_CROSSED' if not crossed else 'AMOUNT_BELOW_20X'
        details.append({**row,'date':date,'limit':float(limit),'requested_notional':float(notional),
            'crossed_one_tick':bool(crossed),'amount_sufficient':bool(liquid),
            'allowed_by_diagnostic':permitted,'diagnostic_reason':reason})
        if not permitted:
            rejected.append(dict(strategy=strategy,date=date,symbol=row['symbol'],side=row['side'],
                reason='LIMIT_NOT_REACHED' if not crossed else 'PARTICIPATION_CAP',
                requested_quantity=quantity,rejected_quantity=quantity,reference_price=bar['open']))
    frame=orders.filter(pl.Series(keep,dtype=pl.Boolean)) if orders.height else orders
    failures=pl.from_dicts(rejected,schema=schema) if rejected else pl.DataFrame(schema=schema)
    return frame,failures,details
