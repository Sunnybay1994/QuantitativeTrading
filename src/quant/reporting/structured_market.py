"""D1 descriptive ETF-share panel from published, first-observed snapshots."""
import datetime as dt
from pathlib import Path

import polars as pl

SYMBOLS=('510050.SH','510300.SH','510500.SH','512100.SH','159915.SZ')


def fund_share_facts(month,*,root=Path('.'),known_at=None):
    known_at=known_at or dt.datetime.now(dt.timezone.utc)
    if known_at.tzinfo is None:
        raise ValueError('Require timezone-aware report observation time')
    known_at=known_at.astimezone(dt.timezone.utc)
    start=dt.date.fromisoformat(month+'-01')
    end=(start.replace(day=28)+dt.timedelta(days=4)).replace(day=1)-dt.timedelta(days=1)
    snapshots=[p.parent for p in (root/'data/clean/fund_share').glob('snapshot=*/summary.json')]
    files=[p for folder in sorted(snapshots) for p in sorted(folder.glob('year=*/data.parquet'))]
    fact={'status':'table_not_captured','month':month,'observed_at':known_at.isoformat(),
        'units':'native fd_share: 10000 fund units','historical_vintage_verified':False,
        'scope':'five preregistered broad ETFs; descriptive observations, not a timing signal',
        'sources':[str(p) for p in files],'rows':[]}
    if not files:return fact
    data=pl.concat([pl.read_parquet(p) for p in files],how='diagonal_relaxed')
    required={'ts_code','trade_date','fd_share','available_at','source_raw_path','source_row_id'}
    if not required.issubset(data.columns):
        raise ValueError('Published fund-share table lacks required provenance')
    if data.schema['trade_date']==pl.String:
        data=data.with_columns(pl.col('trade_date').str.to_date('%Y%m%d'))
    data=data.with_columns(pl.col('fd_share').cast(pl.Float64))
    data=data.filter(pl.col('ts_code').is_in(SYMBOLS)&(pl.col('trade_date')<=end)
        &(pl.col('available_at')<=known_at)&pl.col('fd_share').is_finite()&(pl.col('fd_share')>0))
    # Identical observations retain earliest availability; visible later source
    # corrections at the same native symbol/day supersede only at report time.
    data=data.sort('available_at').unique('source_row_id',keep='first',maintain_order=True)
    winners=data.filter(pl.col('available_at')==pl.col('available_at').max().over(['ts_code','trade_date']))
    conflicts=set(winners.group_by('ts_code','trade_date').agg(pl.col('fd_share').n_unique().alias('n'))
        .filter(pl.col('n')>1).select('ts_code','trade_date').iter_rows())
    data=data.sort(['ts_code','trade_date','available_at','source_row_id']).unique(
        ['ts_code','trade_date'],keep='last',maintain_order=True)
    calendars=[root/f'data/clean/trade_calendar/market={market}/data.parquet' for market in ('SH','SZ')]
    expected={}
    open_dates={}
    for market,path in zip(('SH','SZ'),calendars):
        if not path.is_file():continue
        calendar=pl.read_parquet(path)
        dates=calendar.filter(pl.col('is_open'))['date']
        open_dates[market]=dates
        previous=dates.filter(dates<start)
        current=dates.filter((dates>=start)&(dates<=end))
        # A calendar ending midmonth does not prove the final exchange session.
        if calendar['date'].max()>=end and len(previous) and len(current):
            expected[market]=(previous.max(),current.max())
    for symbol in SYMBOLS:
        selected=data.filter(pl.col('ts_code')==symbol).sort('trade_date')
        dates=open_dates.get(symbol[-2:])
        nontrading=selected.filter(~pl.col('trade_date').is_in(dates.implode())) if dates is not None else selected.head(0)
        selected=selected.filter(pl.col('trade_date').is_in(dates.implode())) if dates is not None else selected.head(0)
        pair=expected.get(symbol[-2:])
        baseline=selected.filter(pl.col('trade_date')==pair[0]) if pair else selected.head(0)
        closing=selected.filter(pl.col('trade_date')==pair[1]) if pair else selected.head(0)
        latest=selected.tail(1).to_dicts()
        baseline_row=baseline.row(0,named=True) if baseline.height else None
        closing_row=closing.row(0,named=True) if closing.height else None
        status=('complete_endpoints' if baseline_row and closing_row else 'missing_month_endpoint') if pair else 'calendar_unavailable'
        if not latest:status='no_visible_observation'
        elif latest[0]['trade_date']<start:status='stale_before_month'
        if pair and any((symbol,day) in conflicts for day in pair):status='ambiguous_endpoint'
        if known_at.astimezone(dt.timezone(dt.timedelta(hours=8))).date()<=end:
            status='month_in_progress'
        change=(closing_row['fd_share']/baseline_row['fd_share']-1
            if status=='complete_endpoints' else None)
        fact['rows'].append({'symbol':symbol,'status':status,
            'nontrading_native_observations':nontrading.height,
            'expected_baseline':str(pair[0]) if pair else None,'expected_month_end':str(pair[1]) if pair else None,
            'latest_date':str(latest[0]['trade_date']) if latest else None,
            'latest_fd_share':latest[0]['fd_share'] if latest and (symbol,latest[0]['trade_date']) not in conflicts else None,
            'baseline_fd_share':baseline_row['fd_share'] if baseline_row and (symbol,pair[0]) not in conflicts else None,
            'month_end_fd_share':closing_row['fd_share'] if closing_row and (symbol,pair[1]) not in conflicts else None,'month_change':change,
            'source_raw_paths':sorted({r['source_raw_path'] for r in (baseline_row,closing_row) if r}),
            'visible_since':str(max(r['available_at'] for r in (baseline_row,closing_row) if r))
                if baseline_row or closing_row else None})
    fact['status']='complete_endpoints' if all(r['status']=='complete_endpoints' for r in fact['rows']) else 'partial'
    return fact


def render_fund_shares(fact):
    lines=['## 宽基ETF份额（结构化）','',f"状态：{fact['status']}；单位：万份；仅描述已观测数据，不作为交易信号。",
        '当前下载不证明历史时点已知；只有前月末与当月末两个交易日都齐全时，才计算月变化。','',
        '| ETF | 最新日期 | 最新万份 | 月变化 | 状态 |','|---|---|---:|---:|---|']
    for row in fact['rows']:
        amount='—' if row['latest_fd_share'] is None else f"{row['latest_fd_share']:,.2f}"
        change='—' if row['month_change'] is None else f"{row['month_change']:.2%}"
        lines.append(f"| {row['symbol']} | {row['latest_date'] or '—'} | {amount} | {change} | {row['status']} |")
    return '\n'.join(lines)
