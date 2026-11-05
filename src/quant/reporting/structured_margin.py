"""D1 descriptive margin panel; native currency, visible observations only."""
import datetime as dt
from pathlib import Path

import polars as pl

BALANCES=('rzye','rqye','rzrqye')
AMOUNTS=(*BALANCES,'rzmre','rzche')
MARKETS=('SH','SZ','BJ')


def margin_facts(month,*,root=Path('.'),known_at=None):
    known_at=known_at or dt.datetime.now(dt.timezone.utc)
    if known_at.tzinfo is None:
        raise ValueError('Require timezone-aware report observation time')
    known_at=known_at.astimezone(dt.timezone.utc)
    start=dt.date.fromisoformat(month+'-01')
    end=(start.replace(day=28)+dt.timedelta(days=4)).replace(day=1)-dt.timedelta(days=1)
    folders=sorted(p.parent for p in (root/'data/clean/margin_detail').glob('snapshot=*/summary.json'))
    files=[p for folder in folders for p in sorted(folder.glob('year=*/data.parquet'))]
    fact={'status':'table_not_captured','month':month,'observed_at':known_at.isoformat(),
        'units':'CNY; quantity fields are not aggregated','historical_vintage_verified':False,
        'exchange_coverage_verified':False,'source_document':'https://tushare.pro/document/2?doc_id=59',
        'scope':'Observed supplier securities, including funds/bonds where returned; not exchange-wide totals or a timing signal',
        'sources':[str(p) for p in files],'rows':[]}
    if not files:return fact
    scan=pl.scan_parquet(files,missing_columns='insert',extra_columns='ignore')
    required={'ts_code','trade_date','available_at','source_raw_path','source_row_id',*AMOUNTS}
    if not required.issubset(scan.collect_schema().names()):
        raise ValueError('Published margin table lacks amounts or provenance')
    data=scan.select(sorted(required))
    if data.collect_schema()['trade_date']==pl.String:
        data=data.with_columns(pl.col('trade_date').str.to_date('%Y%m%d'))
    data=data.filter((pl.col('trade_date')<=end)&(pl.col('available_at')<=known_at))
    data=data.with_columns(*(pl.col(c).cast(pl.Float64) for c in AMOUNTS)).collect()
    data=data.sort('available_at').unique('source_row_id',keep='first',maintain_order=True)
    keys=['ts_code','trade_date']
    winners=data.filter(pl.col('available_at')==pl.col('available_at').max().over(keys))
    conflicts=set(winners.group_by(keys).agg(pl.struct(AMOUNTS).n_unique().alias('n'))
        .filter(pl.col('n')>1).select(keys).iter_rows())
    data=data.sort([*keys,'available_at','source_row_id']).unique(keys,keep='last',maintain_order=True)
    data=data.with_columns(pl.col('ts_code').str.slice(-2).alias('_market'))

    def aggregate(frame):
        values={c:None for c in AMOUNTS}
        if frame.is_empty():return values
        for c in AMOUNTS:
            valid=frame[c].is_finite()&(frame[c]>=0)
            if valid.fill_null(False).all() and not any((r[0],r[1]) in conflicts for r in frame.select(keys).iter_rows()):
                values[c]=float(frame[c].sum())
        return values

    for market in MARKETS:
        selected=data.filter(pl.col('_market')==market)
        latest_date=selected['trade_date'].max()
        latest=selected.filter(pl.col('trade_date')==latest_date) if latest_date else selected.head(0)
        pair=None
        calendar_path=root/f'data/clean/trade_calendar/market={market}/data.parquet'
        if calendar_path.is_file():
            calendar=pl.read_parquet(calendar_path)
            dates=calendar.filter(pl.col('is_open'))['date']
            previous=dates.filter(dates<start)
            current=dates.filter((dates>=start)&(dates<=end))
            if calendar['date'].max()>=end and len(previous) and len(current):
                pair=(previous.max(),current.max())
        baseline=selected.filter(pl.col('trade_date')==pair[0]) if pair else selected.head(0)
        closing=selected.filter(pl.col('trade_date')==pair[1]) if pair else selected.head(0)
        before,after=aggregate(baseline),aggregate(closing)
        status='observed_endpoints' if baseline.height and closing.height else 'missing_month_endpoint'
        if not pair:status='calendar_unavailable'
        elif baseline.height and closing.height:
            if set(baseline['ts_code'])!=set(closing['ts_code']):status='endpoint_universe_changed'
            elif any(before[c] is None or after[c] is None for c in BALANCES):status='invalid_or_ambiguous_endpoint'
        if not latest.height:status='no_visible_observation'
        elif latest_date<start:status='stale_before_month'
        if known_at.astimezone(dt.timezone(dt.timedelta(hours=8))).date()<=end:status='month_in_progress'
        changes={c:(after[c]/before[c]-1 if status=='observed_endpoints' and before[c]>0 else None)
            for c in BALANCES}
        used=pl.concat([baseline,closing,latest]).unique('source_row_id')
        fact['rows'].append({'market':market,'status':status,'latest_date':str(latest_date) if latest_date else None,
            'latest_security_count':latest.height,'latest_cny':aggregate(latest),
            'expected_baseline':str(pair[0]) if pair else None,'expected_month_end':str(pair[1]) if pair else None,
            'baseline_security_count':baseline.height,'month_end_security_count':closing.height,
            'baseline_cny':before,'month_end_cny':after,'balance_month_change':changes,
            'source_raw_paths':sorted(set(used['source_raw_path'])),
            'visible_since':str(used['available_at'].max()) if used.height else None})
    fact['status']='observed_supplier_subset'
    return fact


def render_margin(fact):
    lines=['## 两融明细（结构化）','',f"状态：{fact['status']}；金额单位：元；仅汇总已观测证券，未证明交易所全量覆盖。",
        '流量为所示日期的当日值；月变化要求月末端点齐全且证券集合相同。数量字段不混合求和；当前下载不证明历史PIT。','',
        '| 市场 | 最新日期 | 证券数 | 融资余额 | 融券余额 | 两融余额 | 当日融资买入 | 当日融资偿还 | 两融余额月变化 | 状态 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in fact['rows']:
        amounts=['—' if row['latest_cny'][c] is None else f"{row['latest_cny'][c]:,.2f}" for c in AMOUNTS]
        change=row['balance_month_change']['rzrqye']
        percent='—' if change is None else f'{change:.2%}'
        lines.append(f"| {row['market']} | {row['latest_date'] or '—'} | {row['latest_security_count']} | "+
            ' | '.join(amounts)+f" | {percent} | {row['status']} |")
    return '\n'.join(lines)
