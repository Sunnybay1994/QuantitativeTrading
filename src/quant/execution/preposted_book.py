"""R2 original-share retry state; no provider, broker or order transmission."""
import math

import polars as pl


class PrepostedBook:
    def __init__(self, maximum_attempt_sessions=3):
        if type(maximum_attempt_sessions) is not int or maximum_attempt_sessions!=3:
            raise ValueError('R2 fixes exactly three attempt sessions')
        self.maximum=maximum_attempt_sessions
        self.orders=[]
        self.history=[]
        self.serial=0
        self.last_date=None
        self.awaiting=False

    def replace(self, *, signal, targets, holdings, equity, closes, offset):
        if self.awaiting or not math.isfinite(equity) or equity<=0:
            raise ValueError('Require settled previous attempt and positive equity')
        if offset not in (None,.01,.03):
            raise ValueError('Only preregistered 1%, 3% or opening control')
        weights=dict(targets.select('symbol','weight').iter_rows())
        if (len(weights)!=targets.height or any(not math.isfinite(v) or not 0<=v<=.08 for v in weights.values())
                or sum(weights.values())>1+1e-9):
            raise ValueError('Invalid Top15 target weights')
        planned=[]
        serial=self.serial
        for symbol in sorted(set(weights)|set(holdings)):
            close=closes[symbol]
            if not math.isfinite(close) or close<=0:
                raise ValueError('Require exact signal-close price')
            held=holdings.get(symbol,{}).get('quantity',0)
            desired=math.floor(weights.get(symbol,0.)*equity/close/100)*100
            delta=desired-held
            if not delta:
                continue
            side='BUY' if delta>0 else 'SELL'
            serial+=1
            planned.append({'id':serial,'signal':str(signal),'symbol':symbol,'side':side,
                'original_quantity':abs(delta),'remaining':abs(delta),'attempts':0,
                'signal_close':close,'limit':None if offset is None else close*(1+offset if side=='BUY' else 1-offset),
                'status':'pending'})
        for row in self.orders:
            if row['status']=='pending':
                row['status']='cancelled_new_signal'
        self.history.extend(self.orders)
        self.orders,self.serial=planned,serial

    def attempt(self, date):
        day=str(date)
        if self.awaiting or (self.last_date is not None and day<=self.last_date):
            raise ValueError('Retry requires a new session after settling the previous attempt')
        self.last_date,self.awaiting=day,True
        rows=[]
        limits={}
        for order in self.orders:
            if order['status']!='pending':
                continue
            order['attempts']+=1
            rows.append({'as_of':order['signal'],'execution_date':str(date),'symbol':order['symbol'],
                         'side':order['side'],'quantity':order['remaining']})
            if order['limit'] is not None:
                limits[order['symbol'],order['side']]=order['limit']
        schema={'as_of':pl.String,'execution_date':pl.String,'symbol':pl.String,'side':pl.String,'quantity':pl.Int64}
        return pl.from_dicts(rows,schema=schema) if rows else pl.DataFrame(schema=schema),limits or None

    def settle(self, trades):
        if not self.awaiting:
            raise ValueError('No unsettled attempt')
        fills={(row['symbol'],row['side']):row['quantity'] for row in trades.iter_rows(named=True)}
        if len(fills)!=trades.height:
            raise ValueError('Duplicate fills in one attempt')
        for order in self.orders:
            if order['status']!='pending':
                continue
            filled=fills.pop((order['symbol'],order['side']),0)
            if not 0<=filled<=order['remaining']:
                raise ValueError('Filled shares exceed original remaining order')
            order['remaining']-=filled
            if not order['remaining']:
                order['status']='filled'
            elif order['attempts']>=self.maximum:
                order['status']='expired'
        if fills:
            raise ValueError('Fill has no pending order')
        self.awaiting=False

    def corporate_action_guard(self, events):
        if any(row['symbol'] in set(events['symbol']) and row['status']=='pending' for row in self.orders):
            raise ValueError('Corporate action during pending limit retry needs explicit quantity/price adjustment')
