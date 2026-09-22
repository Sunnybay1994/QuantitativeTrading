"""Conservative depth-limited research fills from saved post-submission quotes only."""
import copy
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from quant.execution.manual_fills import import_events


def stamp(value):
    result = dt.datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Quote/order timestamps require timezone')
    return result.astimezone(dt.timezone(dt.timedelta(hours=8)))


def simulate(opening, orders, quotes, sessions, *, as_of, cost=1.0, participation=.01):
    completed_at=stamp(as_of)
    if cost not in (.5,1.,2.) or not 0 < participation <= .01:
        raise ValueError('Unsupported simulation cost/capacity')
    if len({r['order_id'] for r in orders}) != len(orders):
        raise ValueError('Duplicate order IDs')
    book=copy.deepcopy(opening)
    book['t_plus_zero_symbols']=['518880.SH','511010.SH']
    states=[]
    for order in orders:
        submitted,deadline=stamp(order['submitted_at']),stamp(order['deadline'])
        if completed_at<deadline:
            raise ValueError('Finalize only after the cancellation deadline')
        if (order['symbol'] not in {'510300.SH','518880.SH','511010.SH'} or
                order['side'] not in {'BUY','SELL'} or type(order['quantity']) is not int or
                order['quantity']<=0 or order['quantity']%100 or
                not math.isfinite(order['limit']) or order['limit']<=0 or
                submitted.date()!=deadline.date() or not submitted<deadline):
            raise ValueError('Invalid ETF research order')
        if not dt.time(9,31)<=submitted.time().replace(tzinfo=None)<deadline.time().replace(tzinfo=None)<=dt.time(9,40):
            raise ValueError('Require frozen opening-window execution bounds')
        states.append(dict(order=order,remaining=order['quantity'],notional=0.,fees=0.))
    events=[]
    seen={}
    for quote in sorted(quotes,key=lambda q:stamp(q['received_at'])):
        identity=quote['quote_id']
        if identity in seen:
            if seen[identity]!=quote:
                raise ValueError('Conflicting quote ID')
            continue
        seen[identity]=quote
        received,provider=stamp(quote['received_at']),stamp(quote['provider_time'])
        if received>completed_at:
            continue
        numeric=('bid','ask','bid_size','ask_size','up_limit','down_limit')
        if any(not math.isfinite(quote[k]) or quote[k]<=0 for k in numeric):
            continue
        if (not quote['down_limit']<=quote['bid']<=quote['ask']<=quote['up_limit'] or
                quote['suspended'] or not 0<=(received-provider).total_seconds()<=10):
            continue
        capacity={side:int(quote[key]*participation/100)*100
                  for side,key in [('BUY','ask_size'),('SELL','bid_size')]}
        for state in sorted(states,key=lambda s:(stamp(s['order']['submitted_at']),s['order']['side']!='SELL')):
            order=state['order']
            side=order['side']
            if (not state['remaining'] or order['symbol']!=quote['symbol'] or
                    not stamp(order['submitted_at'])<=provider<=received<stamp(order['deadline'])):
                continue
            # Bid/ask already contains the spread; residual one-tick slippage only.
            price=quote['ask']+.001*cost if side=='BUY' else quote['bid']-.001*cost
            if ((side=='BUY' and (price>order['limit'] or price>=quote['up_limit'])) or
                    (side=='SELL' and (price<order['limit'] or price<=quote['down_limit']))):
                continue
            quantity=min(state['remaining'],capacity[side])
            if side=='SELL':
                available=book['holdings'].get(order['symbol'],{}).get('quantity',0)-sum(
                    r['quantity'] for r in book.get('restricted_shares',[])
                    if r['symbol']==order['symbol'] and r['list_date']>str(provider.date()))
                quantity=min(quantity,max(0,available)//100*100)
            def fee(qty):
                return max(5.,(state['notional']+qty*price)*.00025)*cost-state['fees']
            while quantity and side=='BUY' and quantity*price+fee(quantity)>book['cash']:
                quantity-=100
            if not quantity:
                continue
            event=dict(event_id=order['order_id']+':'+str(identity),timestamp=received.isoformat(),
                       symbol=order['symbol'],kind=side,quantity=quantity,price=price,fee=fee(quantity))
            book,_=import_events(state=book,events=[event],sessions=sessions)
            events.append(event)
            capacity[side]-=quantity
            state['remaining']-=quantity
            state['notional']+=quantity*price
            state['fees']+=event['fee']
    return book,events,[dict(order_id=s['order']['order_id'],remaining=s['remaining'],fees=s['fees'],
                            status='FILLED' if not s['remaining'] else 'CANCELLED_REMAINDER') for s in states]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    raw=args.input.read_bytes()
    payload=json.loads(raw)
    if payload.get('auto_trade') is not False or payload.get('classification')!='RESEARCH_ONLY':
        raise ValueError('Require explicit research-only input')
    book,events,orders=simulate(payload['opening'],payload['orders'],payload['quotes'],
        tuple(dt.date.fromisoformat(d) for d in payload['sessions']),as_of=payload['as_of'],cost=payload.get('cost',1.))
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'input.json').write_bytes(raw)
    for name,value in [('book',book),('events',events),('orders',orders),('summary',dict(
            auto_trade=False,classification='RESEARCH_ONLY',source_sha256=hashlib.sha256(raw).hexdigest(),
            fills=len(events),cash=book['cash'],fees=sum(e['fee'] for e in events),
            limitation='Depth-limited model fills, not exchange executions; closing NAV requires verified marks and corporate actions.'))]:
        (args.output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(fills=len(events),cash=book['cash'],output=str(args.output))))


if __name__=='__main__':
    main()
