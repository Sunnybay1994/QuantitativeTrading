"""B16 saved-order opening-window stress; incomplete coverage is never portfolio NAV."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    source=Path('artifacts/research/etf_allocation_attribution_20260922_03/dynamic_1/trades.parquet')
    sources={str(source):hashlib.sha256(source.read_bytes()).hexdigest()}
    trades=pl.read_parquet(source)
    rows=[]
    for symbol in trades['symbol'].unique().sort():
        path=Path(f'data/clean/bar_intraday/freq=5m/source=tdx/symbol={symbol}/data.parquet')
        sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        bars=pl.read_parquet(path).filter((pl.col('bar_start').dt.hour()==9)&(pl.col('bar_start').dt.minute()==30))
        for order in trades.filter(pl.col('symbol')==symbol).iter_rows(named=True):
            window=bars.filter(pl.col('trade_date')==order['date'])
            row=dict(date=str(order['date']),symbol=symbol,side=order['side'],quantity=order['quantity'],covered=False)
            if window.height==1:
                b=window.row(0,named=True)
                good=(b['volume']>0 and b['bar_end']-b['bar_start'] == dt.timedelta(minutes=5)
                      and 0<b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']
                      and b['low']-.0011<=b['amount']/b['volume']<=b['high']+.0011)
                if good:
                    sign=1 if order['side']=='BUY' else -1
                    # Original account uses 1 tick adverse slippage; retain it here.
                    stressed=(b['high'] if sign==1 else b['low'])+sign*.001
                    row.update(covered=True,baseline_price=order['price'],stressed_price=stressed,
                               adverse_cash_delta=order['quantity']*sign*(stressed-order['price']),
                               capacity_unverified=order['quantity']>b['volume']*.01)
            rows.append(row)
    pl.DataFrame(rows,infer_schema_length=None).write_csv(output/'orders.csv')
    covered=[r for r in rows if r['covered']]
    result=dict(classification='RESEARCH_ONLY',auto_trade=False,orders=len(rows),covered_orders=len(covered),
                covered_dates=len({r['date'] for r in covered}),
                adverse_cash_delta=sum(r['adverse_cash_delta'] for r in covered),
                capacity_flags=sum(r['capacity_unverified'] for r in covered),
                limitations=['Saved 1x account quantities held fixed; no re-sizing, sequential cash or portfolio NAV.',
                             '60/120 seconds both inside 09:30-09:35; full-window worst price used, no exact fill claim.',
                             'Missing orders stay missing. No extrapolation to all months or formal admission.',
                             'Baseline and minute prices may differ by source; delta includes source discrepancy.'])
    (output/'sources.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
    (output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (output/'report.md').write_text('# B16调仓窗口压力诊断\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    print(json.dumps(result))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)


if __name__=='__main__':
    main()
