"""Read-only repeatable latency probe; isolated output, no production feed writes."""
import datetime as dt
import argparse
from collections import defaultdict
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from quant.data.connectors.public_market import PublicMarket

TZ = dt.timezone(dt.timedelta(hours=8))


def summarize(output):
    report = json.loads((output/'report.json').read_text(encoding='utf-8'))
    groups = defaultdict(list)
    for row in report['results']:
        groups[row['source'],row['operation']].append(row)
        if row['operation']=='bars' and 'rows' in row:
            raw = json.loads((output/f"{row['source']}_{row['operation']}_{row['symbol']}_{row['attempt']}.json").read_text(encoding='utf-8'))
            received=dt.datetime.fromisoformat(row['received_at'])
            stamps=[dt.datetime.fromisoformat(r['time_key']).replace(tzinfo=TZ) for r in raw]
            eligible=[t for t in stamps if t+dt.timedelta(seconds=63)<=received]
            row['conservative_confirmed_label_age_seconds']=(received-max(eligible)).total_seconds() if eligible else None
            row['future_label_rows']=sum(t>received for t in stamps)
    lines=['# 行情接口实测','', '热调用不含首次 SDK 初始化；报价年龄是供应商时间戳至本机接收的差，未独立校准本机时钟。小样本不代表全天 SLA。分钟线剔除当前未结束行，并沿用生产 63 秒确认等待。','', '|接口|操作|成功/尝试|热调用秒范围|报价年龄秒范围|','|---|---|---|---|---|']
    for (source,operation),rows in groups.items():
        good=[r for r in rows if 'rows' in r and r['rows']>0]
        warm=[r['elapsed_seconds'] for r in good if r['attempt']>0]
        ages=[r['provider_age_seconds'] for r in good] if operation=='quotes' else []
        def span(xs):
            return f'{min(xs):.3f}–{max(xs):.3f}' if xs else '不适用'
        lines.append(f'|{source}|{operation}|{len(good)}/{len(rows)}|{span(warm)}|{span(ages)}|')
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def probe(source, operation, symbol, output):
    client = None
    results = []
    try:
        if source == 'futu':
            from quant.data.connectors.futu_realtime import FutuRealtime
            client = FutuRealtime()
            client.subscribe([symbol], 10)
        else:
            client = PublicMarket(timeout=20)
        for attempt in range(3):
            start = time.perf_counter()
            row = dict(source=source, operation=operation, symbol=symbol, attempt=attempt,
                       requested_at=dt.datetime.now(TZ).isoformat())
            try:
                rows = (client.quotes([symbol]) if operation == 'quotes' else client.bars(symbol)) if source == 'futu' else client.fetch(operation, [symbol], source)
                received = dt.datetime.now(TZ)
                stamps = [dt.datetime.fromisoformat(r['data_date']+'T'+r['data_time'] if operation == 'quotes' else r['time_key']).replace(tzinfo=TZ) for r in rows]
                latest = max(stamps) if stamps else None
                row.update(rows=len(rows), latest_provider_time=latest.isoformat() if latest else None,
                           provider_age_seconds=(received-latest).total_seconds() if latest else None)
                (output/f'{source}_{operation}_{symbol}_{attempt}.json').write_text(json.dumps(rows,ensure_ascii=False,default=str),encoding='utf-8')
            except Exception as exc:
                row['error_type'] = type(exc).__name__
            row['elapsed_seconds'] = time.perf_counter()-start
            row['received_at'] = dt.datetime.now(TZ).isoformat()
            results.append(row)
            time.sleep(2)
    except Exception as exc:
        results.append(dict(source=source, operation=operation, symbol=symbol,error_type=type(exc).__name__,stage='connection_or_subscription'))
    finally:
        if client:
            client.close()
    return results


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--summarize',type=Path,help='Rebuild report from an existing probe, without network calls')
    args=parser.parse_args()
    if args.summarize:
        summarize(args.summarize)
        return
    output = Path('artifacts/realtime')/('latency_'+dt.datetime.now().strftime('%Y%m%dT%H%M%S'))
    output.mkdir(parents=True,exist_ok=False)
    jobs = [(s,o,c) for s,o in [('tushare_sina','quotes'),('akshare_eastmoney','quotes'),('akshare_eastmoney','bars'),('akshare_sina','bars')] for c in ['000001.SZ','518880.SH']]
    jobs += [('futu','quotes','518880.SH'),('futu','bars','518880.SH')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(probe,*job,output) for job in jobs]
        results = [r for f in futures for r in f.result()]
    report = dict(auto_trade=False, results=results, notes=['Elapsed includes local SDK/IPC overhead. Public attempt 0 includes cold worker startup; Futu connection/subscription setup is excluded.', 'Provider timestamp age is not exchange-to-client latency.', 'Minute timestamp age includes bar period; incomplete bars are not signals.', 'Only current market-session samples establish active-session freshness.'])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    summarize(output)
    print(output)
    for r in results:
        print(json.dumps(r,ensure_ascii=False))


if __name__ == '__main__':
    main()
