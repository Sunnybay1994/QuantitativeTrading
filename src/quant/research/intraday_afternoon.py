"""Fixed minute-signal development replay; incomplete histories never imply admission."""
import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
import tomllib
from collections import Counter
from pathlib import Path

import polars as pl


def signal(bars, at):
    known = [r for r in bars if r['bar_end'] <= at]
    if not known or known[-1]['bar_end'] != at:
        return False
    volume = sum(r['volume'] for r in known)
    return volume > 0 and known[-1]['close'] > max(known[0]['open'], sum(r['amount'] for r in known)/volume)


def execution_bar(rows, at, delay, confirmation):
    ready = at + dt.timedelta(seconds=delay+confirmation)
    return next((r for r in rows if r['bar_start'] >= ready), None)


def conservative_window(rows, at, delay, confirmation):
    """Worst full 5m bar containing readiness; extrema are pricing stress only."""
    ready = at + dt.timedelta(seconds=delay+confirmation)
    start = at + dt.timedelta(minutes=5*int((ready-at).total_seconds()//300))
    matches = [r for r in rows if r['bar_start'] == start
               and r['bar_end'] == start+dt.timedelta(minutes=5)]
    return matches[0] if len(matches) == 1 and matches[0]['volume'] > 0 else None


def sellable_quantity(held, bought_today, *, t_plus_one):
    if not 0 <= bought_today <= held:
        raise ValueError('Invalid share inventory')
    return held-bought_today if t_plus_one else held


def valid_day(rows, minutes):
    expected = [(h,m) for h in (9,10,11,13,14) for m in range(0,60,minutes)
                if (h != 9 or m >= 30) and (h != 11 or m < 30)]
    if [(r['bar_start'].hour,r['bar_start'].minute) for r in rows] != expected:
        return False
    for r in rows:
        if r['bar_end']-r['bar_start'] != dt.timedelta(minutes=minutes):
            return False
        if not all(r[k] is not None and math.isfinite(r[k]) for k in ('open','high','low','close','volume','amount')):
            return False
        if not (0 < r['low'] <= min(r['open'],r['close']) <= max(r['open'],r['close']) <= r['high']) or r['volume'] <= 0:
            return False
        if not r['low']-.0011 <= r['amount']/r['volume'] <= r['high']+.0011:
            return False
    return True


def matched(five, one):
    for r in five:
        group = [m for m in one if r['bar_start'] <= m['bar_start'] < r['bar_end']]
        if len(group) != 5 or abs(group[-1]['close']-r['close']) > .0011:
            return False
        if abs(sum(m['volume'] for m in group)-r['volume']) > max(100,r['volume']*.001):
            return False
    return True


def quality_issues(rows, minutes, date):
    """Explain the existing rejection rules without relaxing any threshold."""
    issues=[]
    expected = [(h,m) for h in (9,10,11,13,14) for m in range(0,60,minutes)
                if (h != 9 or m >= 30) and (h != 11 or m < 30)]
    if [(r['bar_start'].hour,r['bar_start'].minute) for r in rows]!=expected:
        issues.append(dict(date=str(date),frequency=f'{minutes}m',time='',reason='missing_duplicate_or_off_session',value=len(rows)))
    for r in rows:
        reasons=[]
        if r['bar_end']-r['bar_start']!=dt.timedelta(minutes=minutes):
            reasons.append(('bar_duration',None))
        finite=all(r[k] is not None and math.isfinite(r[k]) for k in ('open','high','low','close','volume','amount'))
        if not finite:
            reasons.append(('nonfinite',None))
        else:
            if not 0<r['low']<=min(r['open'],r['close'])<=max(r['open'],r['close'])<=r['high']:
                reasons.append(('ohlc_invalid',None))
            if r['volume']<=0:
                reasons.append(('nonpositive_volume',r['volume']))
            elif not r['low']-.0011<=r['amount']/r['volume']<=r['high']+.0011:
                reasons.append(('amount_implied_price_outside_bar',r['amount']/r['volume']))
        issues.extend(dict(date=str(date),frequency=f'{minutes}m',time=str(r['bar_start']),reason=reason,value=value) for reason,value in reasons)
    return issues


def run(config, output, *, data_root=Path('data')):
    cfg = tomllib.loads(config.read_text(encoding='utf-8'))
    if cfg['auto_trade'] is not False or cfg['capital'] not in (100000,1000000):
        raise ValueError('Invalid safety or capital configuration')
    stress = cfg.get('execution_model') == 'next_5m_worst'
    if stress:
        # Explicitly verified secondary-market ETFs only. Never infer T+0 from ETF suffix.
        rules = {'510300.SH': True, '511010.SH': False, '518880.SH': False}
        if cfg['symbol'] not in rules:
            raise ValueError('Instrument-specific trading rule has not been verified')
        if rules[cfg['symbol']]:
            raise ValueError('This same-day round-trip strategy cannot trade newly bought T+1 shares')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(config,output/'config.toml')
    sources, by_frequency = {}, {}
    for freq in ('1m','5m'):
        path = data_root / f"clean/bar_intraday/freq={freq}/source={cfg['source']}/symbol={cfg['symbol']}/data.parquet"
        raw = path.read_bytes()
        sources[freq] = dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())
        import io
        frame = pl.read_parquet(io.BytesIO(raw)).sort('bar_start')
        by_frequency[freq] = {key[0]:f.to_dicts() for key,f in frame.partition_by('trade_date',as_dict=True).items()}
    (output/'freeze.json').write_text(json.dumps(dict(created_at=dt.datetime.now().astimezone().isoformat(),sources=sources,config_sha256=hashlib.sha256(config.read_bytes()).hexdigest()),indent=2),encoding='utf-8')
    all_dates = sorted(set(by_frequency['1m'])|set(by_frequency['5m']))
    if not all_dates:
        raise ValueError('No minute history available')
    valid, rejected, quality, issues = [], [], [], []
    for date in all_dates:
        one,five = by_frequency['1m'].get(date,[]),by_frequency['5m'].get(date,[])
        checks = dict(one_minute_valid=valid_day(one,1),five_minute_valid=valid_day(five,5),cross_frequency_matched=matched(five,one))
        quality.append(dict(date=str(date),**checks))
        issues.extend(quality_issues(one,1,date))
        issues.extend(quality_issues(five,5,date))
        if not checks['cross_frequency_matched']:
            issues.append(dict(date=str(date),frequency='1m_vs_5m',time='',reason='cross_frequency_price_volume_mismatch',value=None))
        if all(checks.values()):
            valid.append(date)
        else:
            rejected.append(str(date))
    calendar = pl.read_parquet(data_root/'clean/trade_calendar/market=SH/data.parquet')
    expected = calendar.filter(pl.col('is_open') & pl.col('date').is_between(all_dates[0],all_dates[-1]))['date'].to_list()
    missing = [str(d) for d in expected if d not in valid]
    records, summaries = [], []
    for delay in cfg['manual_delays_seconds']:
        for cost in cfg['cost_multipliers']:
            cash = float(cfg['capital'])
            local = []
            for date in valid:
                one,five = by_frequency['1m'][date],by_frequency['5m'][date]
                at = dt.datetime.combine(date,dt.time.fromisoformat(cfg['signal_time']),one[0]['bar_start'].tzinfo)
                exit_at = at.replace(hour=int(cfg['exit_signal_time'][:2]),minute=int(cfg['exit_signal_time'][3:]))
                before = cash
                trade = dict(date=str(date),manual_delay_seconds=delay,cost=cost,signal=signal(five,at),quantity=0,reason='no_signal')
                if trade['signal']:
                    choose = conservative_window if stress else execution_bar
                    rows = five if stress else one
                    buy = choose(rows,at,delay,cfg['confirmation_seconds'])
                    sell = choose(rows,exit_at,delay,cfg['confirmation_seconds'])
                    if buy and sell and sell['bar_start']-buy['bar_start'] >= dt.timedelta(minutes=5):
                        slip = cfg['tick']*(cfg['slippage_ticks']+cfg['half_spread_ticks'])*cost
                        bp,sp = (buy['high'] if stress else buy['open'])+slip,(sell['low'] if stress else sell['open'])-slip
                        sizing_price = next(r['close'] for r in five if r['bar_end'] == at) if stress else bp
                        qty = int(cash/sizing_price/100)*100
                        def fee(n):
                            return max(cfg['commission_min'],n*cfg['commission_rate'])*cost
                        while qty>0 and qty*bp+fee(qty*bp)>cash:
                            qty -= 100
                        # Entry participation is a fill model. Never cancel an earlier
                        # entry by looking ahead at the future exit's volume.
                        qty = min(qty,int(buy['volume']*cfg['maximum_participation']/100)*100)
                        if qty>0:
                            cash += qty*(sp-bp)-fee(qty*bp)-fee(qty*sp)
                            trade.update(quantity=qty,entry=str(buy['bar_start']),exit=str(sell['bar_start']),reason='filled',buy_price=bp,sell_price=sp,exit_capacity_unverified=qty>sell['volume']*cfg['maximum_participation'])
                            if stress:
                                trade.update(timestamp_meaning='stress_window_start_not_exact_fill',
                                             entry_window_end=str(buy['bar_end']), exit_window_end=str(sell['bar_end']))
                        else:
                            trade['reason']='participation_or_cash'
                    else:
                        trade['reason']='missing_execution'
                trade.update(pnl=cash-before,return_value=cash/before-1,nav=cash/cfg['capital'],split='design' if str(date)<=cfg['design_end'] else 'later_seen_history')
                local.append(trade)
            records.extend(local)
            summaries.append(dict(delay=delay,cost=cost,observed_days=len(local),trades=sum(r['quantity']>0 for r in local),observed_day_return=cash/cfg['capital']-1))
    if records:
        pl.DataFrame(records,infer_schema_length=None).write_csv(output/'daily_replay.csv')
    pl.DataFrame(quality).write_csv(output/'daily_quality.csv')
    if issues:
        pl.DataFrame(issues,infer_schema_length=None).write_csv(output/'quality_issues.csv')
    diagnosis=dict(
        input_days=len(all_dates),valid_days=len(valid),
        issue_counts=dict(Counter(r['reason'] for r in issues)),
        affected_days={reason:len({r['date'] for r in issues if r['reason']==reason}) for reason in sorted({r['reason'] for r in issues})},
        execution=[dict(delay=delay,signals=sum(r['signal'] for r in records if r['cost']==1 and r['manual_delay_seconds']==delay),
                        trades=sum(r['quantity']>0 for r in records if r['cost']==1 and r['manual_delay_seconds']==delay),
                        exit_capacity_flags=sum(bool(r.get('exit_capacity_unverified')) for r in records if r['cost']==1 and r['manual_delay_seconds']==delay)) for delay in cfg['manual_delays_seconds']],
        interpretation='Counts may overlap. Failed bars remain excluded. Suspected rounding or no-trade bars are not automatically repaired.')
    (output/'diagnosis.json').write_text(json.dumps(diagnosis,ensure_ascii=False,indent=2),encoding='utf-8')
    result = dict(classification='RESEARCH_ONLY',auto_trade=False,description=cfg['description'],valid_days=len(valid),excluded_present_days=rejected,missing_or_invalid_calendar_days=missing,summaries=summaries,exit_capacity_unverified=sum(bool(r.get('exit_capacity_unverified')) for r in records),limitations=['Observed valid sessions only; gaps are not zero-return days.', 'Historical development replay, not independent out-of-sample evidence.', 'No total-return benchmark validated; excess/annualized Sharpe/admission not asserted.', 'Entry participation checked ex post; exit capacity flags invalidate executability, never retroactively cancel entries.'])
    result['diagnosis']=diagnosis
    result['execution_model'] = cfg.get('execution_model', 'delayed_1m_open')
    if stress:
        result['limitations'].extend([
            'Full next 5m high/low is ex-post adverse pricing, never signal information or an exact fill timestamp.',
            'Readiness inside a bar uses its entire range; readiness at/after its end moves to the next exact window. Missing windows never jump forward.',
            'T+0 verified only for this gold ETF secondary-market trade. T+1 same-day round-trip configurations rejected.',
            'Worst bar price is not a guaranteed loss bound: later fills, unfilled orders and price-limit queues can be worse.'])
    (output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'report.md').write_text('# 分钟策略开发回放\n\n'+cfg['description']+'\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=Path('configs/research/intraday_afternoon_v1.toml'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.config,args.output)


if __name__ == '__main__':
    main()
