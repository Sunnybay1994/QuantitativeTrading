"""D1 machine coverage report; partial capture never becomes full acceptance."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

from quant.data.events_v0 import _task_spend
from quant.data.events_v0_budget import pending,task_budget_usd
from quant.data.event_family_inputs import event_family_source_facts
from quant.reporting.structured_coverage import describe_table


def build(*,root,permissions):
    capture=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    probe=json.loads(permissions.read_text(encoding='utf-8'))
    expected=tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    ledger=Path('artifacts/research/llm_ledger')
    balance={'cap_usd':task_budget_usd(),'charged_usd':_task_spend(ledger),'reserved':pending(ledger)}
    complete=capture['status']=='captured' and set(capture['tables'])==set(expected['tables'])
    sources={name:row['status'] for name,row in probe['tables'].items()}
    result={'status':'captured_needs_consumer_acceptance' if complete else 'partial',
        'auto_trade':False,'published_tables':capture['tables'],'missing_tables':sorted(set(expected['tables'])-set(capture['tables'])),
        'permission_probes':sources,'budget':balance,'capture_status':capture['status'],
        'as_of':str(expected['end']),'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'historical_vintage_verified':False,'new_factor_backtests':0,'raw_overwrites':0,
        'daily_schedule_attached':False,'pending':'Finish missing supplier shards and verify actual date coverage; this capture is not two natural daily runs'}
    result['event_family_inputs']=event_family_source_facts(Path('data'))
    result['actual_table_observations']={name:describe_table(name,record,expected['tables'][name],
        start=expected['start'],end=expected['end']) for name,record in capture['tables'].items()}
    result['published_metadata_matches_actual']=all(item['declared_metadata_matches'] for item in result['actual_table_observations'].values())
    if not result['published_metadata_matches_actual']:result['status']='partial'
    lines=['# D1 结构化表接入','',f"当前：{result['status']}；原请求截止{expected['end']}；auto_trade=false。",'',
        '| 表 | 状态 | 行数 | 口径日期 | 最早 | 最新 | 股票/基金数 |','|---|---|---:|---|---|---|---:|']
    for table in expected['tables']:
        record=capture['tables'].get(table)
        if record:
            actual=result['actual_table_observations'][table]
            status='已发布；摘要一致' if actual['declared_metadata_matches'] else '摘要与实表待核对'
            lines.append(f"| {table} | {status} | {actual.get('rows','—')} | {actual.get('date_field',expected['tables'][table]['date_field'])} | {actual.get('first_date','—')} | {actual.get('last_date','—')} | {actual.get('symbols','—')} |")
        else:
            lines.append(f'| {table} | 尚未完成 | — | — | — | — | — |')
    lines+=['','## 权限与空结果','',
        '各接口只作一次限定探测，返回字段及原始快照在权限JSON；available_empty仅表示这次样本为空，不能当作权限拒绝。']
    lines += [f'- {name}: {status}。' for name,status in sources.items()]
    lines+=['','## 实表时间覆盖','',
        '行数和日期来自已发布Parquet，按年列示。事件表不要求每天发生事件；出现过每一年本身不证明原始历史版本或请求已经跑完。']
    for table,actual in result['actual_table_observations'].items():
        lines.append(f"- {table}：逐年行数{actual.get('yearly_rows',{})}；缺少年份{actual.get('missing_requested_years','未知')}；摘要一致{actual['declared_metadata_matches']}。")
        lines.append(f"  无效日期{actual.get('invalid_dates','未知')}，请求范围外日期{actual.get('dates_outside_request','未知')}，可用时间早于观察{actual.get('availability_before_observation','未知')}。")
        if 'daily_grid' in actual:lines.append(f"  ETF交易日网格：{actual['daily_grid']}。")
    lines+=['','## 事件族结构化输入','',
        '以下为按首见时点可见的原生记录数；解禁分持有人、股东户数分报告期，不混合求和，也未生成新因子。',
        '| 来源 | 消费类型 | 可见记录 | 状态 |','|---|---|---:|---|']
    for table,item in result['event_family_inputs']['sources'].items():
        lines.append(f"| {table} | {item['family']} | {item.get('visible_native_records','—')} | {item['status']} |")
    lines+=['','## 来源、可用时间与消费者','',
        '当前供应商历史不证明原历史版本；available_at不早于本次首见快照。公告日期与首次观察时间分别保存，不能把本轮下载倒填为历史PIT。',
        '股东变动数量、解禁份额均保留原生股数，无万股乘数；单位更正及原请求配置见units_erratum.json、recovery.json，不修改raw数值。',
        '[股东增减持字段](https://tushare.pro/document/2?doc_id=175)、[解禁字段](https://tushare.pro/document/2?doc_id=160)。',
        '回购/增减持/解禁供event_family_v1；宽基ETF份额仅五只固定基金供月报面板，不称全市场基金覆盖。',
        'S4先核对结构化字段与原公告正文，金额/方向齐全则不调用LLM；只补缺失关键字段。来源收据与已见时点保留；后续因子聚合须用公布日算事件年龄、known_at作资格，并去重同一结构化来源及累计进度。',
        f"当前月S4上限${balance['cap_usd']:g}，已记账${balance['charged_usd']:.6f}、未结保留${balance['reserved']['usd']:.6f}；11月上限在请求锁内按真实计费月重新约束。",
        '保留10月正文预取；本次未调用真实LLM、未做新因子回测、未接入日更。尚未完成四表和消费者实际核验时不得记D1通过。']
    (root/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (root/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--permissions',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(build(root=args.root,permissions=args.permissions),ensure_ascii=False))
