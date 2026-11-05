"""Extend frozen Q10 return benchmarks from native daily facts, without account writes."""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import tomllib
import uuid

import polars as pl

from quant.data.equal_weight_index import index_day, monthly_selections, publish_etf_extension, load_return_benchmarks
from quant.data.factor_battery_inputs import read_battery_universe_dates
from quant.data.factor_panels import available_sessions
from quant.data.refresh import completed_date
from quant.data.refresh_stocks import read_stock_data


def recover_terminal(*, name, plan, history, sessions, quotes, actions, stopped, delisted):
    """A rebalance cancels prior-basket scale from normalized terminal holdings.

    The first day's return includes an unknown prior-basket overnight return;
    compare all subsequent frozen returns, then retain the published end level.
    """
    first = plan['effective_date'].min()
    saved = {row['trade_date']: row for row in history.iter_rows(named=True)}
    targets = {row['symbol']: row for row in plan.iter_rows(named=True)}
    state, differences = {}, []
    for day in sessions:
        if day < first:
            continue
        state, row, _ = index_day(date=day, state=state, quotes=quotes.get(day, {}),
            actions=actions.get(day, {}), stopped=stopped.get(day, set()), delisted=delisted,
            targets=targets if day == first else None)
        if day != first:
            differences.append(abs(row['daily_return'] - saved[day]['daily_return']))
    if not differences or any(not math.isfinite(value) for value in differences) or max(differences) > 1e-12:
        raise ValueError(f'Frozen return seam mismatch: {name}')
    terminal = saved[sessions[-1]]
    if len(state['weights']) != terminal['constituents']:
        raise ValueError(f'Frozen terminal constituents mismatch: {name}')
    state['level'] = terminal['index_level']
    return state, {'first_rebalance': str(first), 'compared_returns': len(differences),
        'maximum_return_difference': max(differences), 'constituents': len(state['weights'])}


def _groups(frame, date):
    return {key[0]: {row['symbol']: row for row in part.iter_rows(named=True)}
            for key, part in frame.partition_by(date, as_dict=True).items()}


def _members(root, base_summary, spec, signals):
    from quant.data.factor_benchmarks import capture_csi800
    original = root / 'clean/factor_benchmarks' / base_summary['csi800_snapshot'] / 'members.parquet'
    members = pl.read_parquet(original)
    sources = [original]
    folders = [root / 'clean/factor_benchmarks' / spec['historical_members'],
               *(root / 'clean/factor_benchmarks').glob('q10_forward_members_*')]
    candidates = []
    for folder in folders:
        if (folder / 'summary.json').is_file() and (folder / 'members.parquet').is_file():
            frame = pl.read_parquet(folder / 'members.parquet')
            if not frame.is_empty():
                candidates.append((frame['snapshot_date'].max(), folder / 'members.parquet', frame))
    for _, path, frame in sorted(candidates, key=lambda row: (row[0], str(row[1]))):
        fresh = frame.filter(pl.col('snapshot_date') > members['snapshot_date'].max())
        if fresh.height:
            members = pl.concat([members, fresh]); sources.append(path)
    last = max(signals)
    if members['snapshot_date'].max() < last:
        name = f'q10_forward_members_{last:%Y%m%d}_{uuid.uuid4().hex[:8]}'
        capture_csi800(data_root=root, name=name,
            start=members['snapshot_date'].max()+dt.timedelta(days=1), end=last)
        path = root / 'clean/factor_benchmarks' / name / 'members.parquet'
        members = pl.concat([members, pl.read_parquet(path)]); sources.append(path)
    return members, sources


def prepare(*, config, end, output, data_root=Path('data'), now=None):
    if end > completed_date('today', now or dt.datetime.now(dt.timezone.utc)):
        raise ValueError('Forward benchmark close is not observable yet')
    if output.exists():
        raise FileExistsError('Use a new forward benchmark run directory')
    output.mkdir(parents=True)
    payload = config.read_bytes()
    spec = tomllib.loads(payload.decode('utf-8'))
    if spec['id'] != 'q10_forward_return_benchmarks_v1' or spec['auto_trade'] is not False:
        raise ValueError('Require registered forward benchmark input policy')
    (output / 'config.toml').write_bytes(payload)
    refs = tomllib.loads(Path(spec['base_benchmarks']).read_text(encoding='utf-8'))['benchmarks']
    base = data_root / 'clean/equal_weight_indexes' / refs['equal_weight_snapshot']
    base_summary = json.loads((base / 'summary.json').read_bytes())
    through = dt.date.fromisoformat(base_summary['end'])
    if end <= through:
        raise ValueError('This path only extends the frozen benchmark period')
    original = pl.read_parquet(base / 'data.parquet')
    frozen_hash = hashlib.sha256((base / 'data.parquet').read_bytes()).hexdigest()
    names = ('all_market_equal_weight', 'csi800_equal_weight')
    old_plans = {name: pl.read_parquet(base / f'{name}_selections.parquet') for name in names}
    tails = {name: plan.filter(pl.col('effective_date') == plan.filter(
        pl.col('effective_date') <= through)['effective_date'].max()) for name, plan in old_plans.items()}
    first = min(plan['effective_date'].min() for plan in tails.values())
    sessions = available_sessions(data_root, end+dt.timedelta(days=40))
    recovery_days = [day for day in sessions if first <= day <= through]
    days = [day for day in sessions if through < day <= end]
    if not days or days[-1] != end or not recovery_days or recovery_days[-1] != through:
        raise ValueError('Missing benchmark session calendar endpoints')
    sources = [config, Path(spec['base_benchmarks']), Path(spec['base_index_config']),
               base / 'summary.json', base / 'data.parquet', *(base / f'{name}_selections.parquet' for name in names)]
    symbols = sorted(set().union(*(set(plan['symbol']) for plan in tails.values())))
    bars = read_stock_data(data_root=data_root, config=Path(spec['base_index_config']), table='bar_1d',
        start=first, end=through, symbols=symbols, columns=('symbol','trade_date','open','close','volume'))
    bars.write_parquet(output / 'recovery_quotes.parquet')
    execution = data_root / 'clean/stock_execution' / base_summary['execution_snapshot']
    sources.extend(execution / f'{name}.parquet' for name in ('instruments','dividends','suspensions'))
    dividends = pl.read_parquet(execution / 'dividends.parquet').filter(pl.col('ex_date').is_between(first,through))
    suspended = pl.read_parquet(execution / 'suspensions.parquet').filter(pl.col('trade_date').is_between(first,through))
    delisted = dict(pl.read_parquet(execution / 'instruments.parquet').select('symbol','delist_date').iter_rows())
    quotes, actions = _groups(bars,'trade_date'), _groups(dividends,'ex_date')
    stopped = {key[0]:set(part['symbol']) for key,part in suspended.partition_by('trade_date',as_dict=True).items()}
    states, recovery = {}, {}
    for name in names:
        states[name], recovery[name] = recover_terminal(name=name, plan=tails[name],
            history=original.filter(pl.col('index_name')==name), sessions=recovery_days,
            quotes=quotes, actions=actions, stopped=stopped, delisted=delisted)
    signals = [a for a,b in zip(sessions,sessions[1:]) if (a.year,a.month)!=(b.year,b.month) and through <= a < b <= end]
    universe = read_battery_universe_dates(statistics=Path(spec['statistics']), as_of_dates=signals,
        data_root=data_root, include_tradeability=True).select('symbol','trade_date','eligible','close')
    universe.write_parquet(output / 'signal_universe.parquet')
    members, member_sources = _members(data_root,base_summary,spec,signals)
    sources.extend(member_sources)
    members.write_parquet(output / 'members.parquet')
    plans = {name:monthly_selections(universe,members if name=='csi800_equal_weight' else None,sessions,end) for name in names}
    symbols = sorted(set().union(*(set(state['weights']) for state in states.values()),*(set(plan['symbol']) for plan in plans.values())))
    bars = read_stock_data(data_root=data_root,config=Path(spec['refresh_config']),table='bar_1d',start=days[0],end=end,
        symbols=symbols,columns=('symbol','trade_date','open','close','volume'))
    bars.write_parquet(output / 'extension_quotes.parquet')
    quotes = _groups(bars,'trade_date')
    scheduled = {name:_groups(plan,'effective_date') for name,plan in plans.items()}
    new_rows, new_events = [], []
    for day in days:
        daily = data_root / 'clean/stock_paper_inputs' / f'date={day}'
        paths = [daily / name for name in ('sources.json','instruments.parquet','dividends.parquet','suspensions.parquet')]
        if not all(path.is_file() for path in paths):
            raise ValueError(f'Missing native daily execution facts: {day}')
        sources.extend(paths)
        instruments = pl.read_parquet(daily / 'instruments.parquet')
        delisted.update(dict(instruments.select('symbol','delist_date').iter_rows()))
        dividends = pl.read_parquet(daily / 'dividends.parquet')
        suspended = pl.read_parquet(daily / 'suspensions.parquet')
        if dividends.height and (dividends['ex_date'].unique().to_list()!=[day]
                or dividends.select('symbol','ex_date').is_duplicated().any()):
            raise ValueError('Daily corporate action date/identity mismatch')
        if suspended.height and suspended['trade_date'].unique().to_list()!=[day]:
            raise ValueError('Daily suspension date mismatch')
        if day not in quotes:
            raise ValueError(f'Whole benchmark quote session missing: {day}')
        actions = {r['symbol']:{**r,'adjust_share_price':True} for r in dividends.iter_rows(named=True)}
        for name in names:
            states[name],row,events = index_day(date=day,state=states[name],quotes=quotes[day],actions=actions,
                delisted=delisted,stopped=set(suspended['symbol']),targets=scheduled[name].get(day))
            new_rows.append({'index_name':name,**row});new_events.extend({'index_name':name,**e} for e in events)
    new, events = pl.DataFrame(new_rows), pl.DataFrame(new_events,infer_schema_length=None)
    new.write_parquet(output / 'new_index_days.parquet');events.write_parquet(output / 'new_index_events.parquet')
    unknown = events.filter(pl.col('kind')=='missing_quote_last_mark') if events.height else events
    if unknown.height:
        unknown.write_csv(output / 'unexplained_quote_gaps.csv')
        raise ValueError('Unexplained forward benchmark quote gaps; original histories retained')
    full = pl.concat([original,new.select(original.columns)],how='vertical_relaxed')
    if not full.head(original.height).equals(original) or any(new.filter(pl.col('index_name')==name)['trade_date'].to_list()!=days for name in names):
        raise ValueError('Frozen benchmark prefix or new session grid changed')
    version = f'q10_forward_{end:%Y%m%d}_{uuid.uuid4().hex[:8]}'
    staging = output / 'index_staging';staging.mkdir()
    full.write_parquet(staging / 'data.parquet')
    old_events = pl.read_parquet(base / 'events.parquet')
    (pl.concat([old_events,events],how='diagonal_relaxed') if events.height else old_events).write_parquet(staging / 'events.parquet')
    for name,plan in plans.items():
        pl.concat([old_plans[name],plan],how='diagonal_relaxed').write_parquet(staging/f'{name}_selections.parquet')
    for name in ('recovery_quotes.parquet','extension_quotes.parquet','signal_universe.parquet','members.parquet'):
        sources.append(output / name)
    if hashlib.sha256((base / 'data.parquet').read_bytes()).hexdigest()!=frozen_hash:
        raise ValueError('Frozen source changed during forward extension')
    summary = {**base_summary,'version':version,'previous':refs['equal_weight_snapshot'],'end':str(end),
        'rows':full.height,'old_prefix_exact':True,'original_rows':original.height,'new_rows':new.height,
        'extension_sessions':len(days),'new_unexplained_quote_gaps':0,'historical_vintage_verified':False,
        'recovery':recovery,'request_sha256':hashlib.sha256(payload).hexdigest(),
        'source_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        'series':full.group_by('index_name').agg(pl.len().alias('rows'),pl.col('constituents').min().alias('minimum_constituents'),pl.col('constituents').max().alias('maximum_constituents')).to_dicts()}
    (staging/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    destination = data_root / 'clean/equal_weight_indexes' / version
    if destination.resolve().parent!=(data_root/'clean/equal_weight_indexes').resolve() or destination.exists():
        raise ValueError('Unsafe or existing forward benchmark destination')
    staging.rename(destination)
    etf_version = version+'_etf'
    etf = publish_etf_extension(data_root=data_root,previous=refs['etf_total_return_snapshot'],version=etf_version,end=end)
    references = output / 'return_benchmarks.toml'
    references.write_text(f'[benchmarks]\nequal_weight_snapshot="{version}"\netf_total_return_snapshot="{etf_version}"\n',encoding='utf-8')
    histories = load_return_benchmarks(config=references,data_root=data_root,start=through,end=end)
    result = {'status':'complete','auto_trade':False,'as_of':str(end),'old_prefix_exact':True,
        'return_benchmarks':str(references),'recovery':recovery,'new_rows':new.height,'etf_extension':etf,
        'benchmarks':{name:{'rows':frame.height,'first':str(frame['date'].min()),'last':str(frame['date'].max())} for name,frame in histories.items()},
        'historical_vintage_verified':False,'account_writes':0,'notifications':0}
    (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('configs/data/q10_forward_return_benchmarks_v1.toml'))
    parser.add_argument('--end',type=dt.date.fromisoformat,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('data'))
    args = vars(parser.parse_args())
    print(json.dumps(prepare(**args)))


if __name__ == '__main__':
    main()
