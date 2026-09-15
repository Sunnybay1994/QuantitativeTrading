"""Report API outcomes, conservative spending and support as distinct quantities."""
import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import statistics

import polars as pl

from quant.data.monthly_text_sample import request_snapshot


def summarize_requests(attempts: list[dict], *, allowed_keys: set[str]) -> dict:
    selected = [r for r in attempts if r['cache_key'] in allowed_keys]
    latest = {r['cache_key']:r for r in selected}
    states = Counter(r['state'] for r in latest.values())
    usage = [json.loads(r['usage_json']) for r in selected if r.get('usage_json')]
    started = sorted(dt.datetime.fromisoformat(r['created_at']) for r in selected)
    gaps = [(b-a).total_seconds() for a,b in zip(started,started[1:])]
    statuses: Counter[str] = Counter()
    for row in latest.values():
        if row['state'] == 'success':
            for dimension, score in json.loads(row['scores_json']).items():
                statuses[f"{dimension}:{score.get('status','unspecified')}"] += 1
    terminal = sum(count for state,count in states.items() if state != 'unknown')
    return {'selected_unique_texts':len(allowed_keys),'requested_unique_texts':len(latest),
        'unrequested_texts':len(allowed_keys)-len(latest),'attempts':len(selected),'states':dict(states),
        'successful_texts':states['success'],'success_fraction_all_selected':states['success']/len(allowed_keys) if allowed_keys else None,
        'success_fraction_terminal':states['success']/terminal if terminal else None,
        'dimension_statuses':dict(statuses),
        'errors':dict(Counter(r['error'] for r in selected if r.get('error'))),
        'batch_charged_or_reserved_usd':sum(r['charged_usd'] for r in selected),
        'shared_charged_or_reserved_usd':sum(r['charged_usd'] for r in attempts),
        'reported_prompt_tokens':sum(u['prompt_tokens'] for u in usage),
        'reported_completion_tokens':sum(u['completion_tokens'] for u in usage),
        'maximum_completion_tokens':max((u['completion_tokens'] for u in usage),default=None),
        'median_request_start_gap_seconds':statistics.median(gaps) if gaps else None,
        'request_start_span_seconds':(started[-1]-started[0]).total_seconds() if started else 0.,
        'selected_all_terminal':len(latest)==len(allowed_keys) and terminal==len(latest)}


def run(*, plan: Path, cache: Path, output: Path) -> dict:
    saved = json.loads((plan/'summary.json').read_text())
    result = summarize_requests(request_snapshot(cache),allowed_keys=set(saved['selected_request_keys']))
    members = pl.read_parquet(plan/'selected_members.parquet')
    batch_members = members.filter(pl.col('first_batch_selected'))
    monthly = batch_members.group_by('trade_date').len()
    result.update(snapshot_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        potential_stock_months=batch_members.height,max_potential_monthly_symbols=monthly['len'].max(),
        potential_months_at_100=monthly.filter(pl.col('len')>=100).height,
        cost_basis='Configured conservative accounting including outstanding reservations; not supplier invoice',
        semantic_accuracy='Not measured by success/schema/evidence validation; requires independent labels',
        api_calls=0)
    output.mkdir(parents=True,exist_ok=False)
    (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    monthly.sort('trade_date').write_csv(output/'potential_monthly_support.csv')
    gap=result['median_request_start_gap_seconds']
    report=(f"# P7评分批次快照\n\n成功{result['successful_texts']}/{result['selected_unique_texts']}段，"
        f"未请求{result['unrequested_texts']}段；状态{result['states']}。全部结束：{result['selected_all_terminal']}。\n\n"
        f"本批费用含预留${result['batch_charged_or_reserved_usd']:.4f}，共享累计${result['shared_charged_or_reserved_usd']:.4f}。"
        f"相邻请求启动间隔中位数{gap if gap is not None else 'NA'}秒；这是请求启动节奏，不是单次响应耗时。\n\n"
        f"批次最多支持{batch_members.height}股票月，单月最高{result['max_potential_monthly_symbols']}只，"
        f"潜在至少100只的月份{result['potential_months_at_100']}。维度状态及错误见summary.json。\n\n"
        "成功响应只表示通过当前格式及证据检查，不作为独立语义准确率或因子有效性证据。\n")
    (output/'report.md').write_text(report,encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(run(**vars(parser.parse_args()))))


if __name__=='__main__':
    main()
