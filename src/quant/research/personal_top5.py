"""Run the single registered Top5/Top50 x fee1/fee5 paired experiment."""
import argparse
import bisect
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tomllib
import uuid

import polars as pl

from quant.data.factor_battery_inputs import read_battery_execution, read_frozen_battery_universe
from quant.data.factor_panels import available_sessions
from quant.data.stock_execution_inputs import stock_session_states
from quant.research.factor_cost_checkpoint import read_year, save_year
from quant.research.personal_top5_construction import fixed_orders, personal_replay, rank_targets

DEFAULT = Path('configs/research/personal_top5_fee1_v1.toml')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with tmp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            sha.update(block)
    return sha.hexdigest()


def progress(output, **state):
    write_json(output/'progress.json', dict(pid=os.getpid(), updated_at=dt.datetime.now().isoformat(),
        auto_trade=False, **state))
    print(json.dumps(state, default=str), flush=True)


def freeze(config, output, data_root):
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if (spec['auto_trade'] is not False or spec['capital'] != 100000
            or spec['cost_multipliers'] != [.5, 1., 2.] or spec['primary_top_k'] != 5
            or spec['control_top_k'] != 50 or spec['primary_commission_min'] != 1.
            or spec['control_commission_min'] != 5.):
        raise ValueError('Only the registered personal account experiment is supported')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    predictions = Path(spec['inputs']['predictions'])
    account = Path(spec['inputs']['source_account'])
    model = tomllib.loads((predictions/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((account/'battery.toml').read_text(encoding='utf-8'))
    from quant.backtest.share_exchanges import validate_exchanges
    settings['share_exchanges'] = validate_exchanges(tomllib.loads(
        (account/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges'])
    settings['portfolio']['initial_cash'] = spec['capital']
    settings['portfolio']['cost_multipliers'] = spec['cost_multipliers']
    snapshot = json.loads((account/'summary.json').read_text(encoding='utf-8'))['execution_snapshot']
    end = settings['run']['as_of']
    pred = pl.read_parquet(predictions/'monthly_predictions.parquet')
    sessions = available_sessions(data_root, end)
    universe = read_frozen_battery_universe(statistics=Path(model['research']['statistics_source']),
        as_of_dates=pred['trade_date'].unique().to_list(), include_tradeability=True)
    inputs = output/'inputs'; inputs.mkdir()
    universe.write_parquet(inputs/'signal_controls.parquet')
    pred.write_parquet(inputs/'predictions.parquet')
    plans = {}
    for k in (5, 50):
        targets, ranking = rank_targets(pred, universe, sessions, end, k, spec['construction']['cash_buffer'])
        targets.write_parquet(inputs/f'targets_{k}.parquet')
        ranking.write_parquet(inputs/f'ranking_{k}.parquet')
        plans[str(k)] = (f'personal_top{k}', targets)
    first = min(frame['as_of'].min() for _, frame in plans.values())
    sessions = [day for day in sessions if first <= day <= end]
    symbols = set(plans['50'][1]['symbol'])
    for event in settings['share_exchanges']:
        if event['from_symbol'] in symbols:
            symbols.add(event['to_symbol'])
    source_files = [config, predictions/'monthly_predictions.parquet', predictions/'model.toml',
        predictions/'summary.json', account/'battery.toml', account/'share_exchanges.toml', account/'summary.json']
    source_files += sorted(predictions.glob('lightgbm_*.txt'))
    source_files += [Path(model['research']['statistics_source'])/f'inputs/{year}/universe.parquet'
                    for year in sorted(set(pred['trade_date'].dt.year()))]
    # Hash source data before and after copying the bounded execution inputs.
    from quant.research.benchmark_reuse import context
    before = context(settings=settings, plans=plans, sessions=tuple(sessions), data_root=data_root, snapshot=snapshot)
    for year in sorted(set(day.year for day in sessions)):
        progress(output, status='freezing_inputs', year=year, replay_started=False)
        folder = inputs/str(year); folder.mkdir()
        low, high = max(first, dt.date(year,1,1)), min(end,dt.date(year,12,31))
        frames = read_battery_execution(data_root=data_root, refresh_config=Path(settings['data']['refresh_config']),
            snapshot=snapshot, start=low, end=high, symbols=sorted(symbols), include_all_dividends=True)
        for name, frame in frames.items():
            frame.write_parquet(folder/f'{name}.parquet')
    after = context(settings=settings, plans=plans, sessions=tuple(sessions), data_root=data_root, snapshot=snapshot)
    if before != after:
        raise ValueError('Source changed during freeze; retain incomplete freeze and create a new run')
    from quant.data.equal_weight_index import load_return_benchmarks
    benchmarks = load_return_benchmarks(config=Path(spec['inputs']['return_benchmark_config']),
        data_root=data_root, start=first, end=end)
    for name, frame in benchmarks.items():
        frame.write_parquet(inputs/f'benchmark_{name}.parquet')
    stress = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))['cycle_validation']['stress_windows']
    write_json(inputs/'settings.json', settings)
    write_json(inputs/'model.json', model)
    write_json(inputs/'stress.json', stress)
    write_json(inputs/'sessions.json', sessions)
    write_json(output/'source_manifest.json', dict(execution=before,
        additional={str(p): digest(p) for p in source_files},
        prediction_period=dict(first=str(pred['trade_date'].min()), last=str(pred['trade_date'].max()),
            signals=pred['trade_date'].n_unique()),
        execution_period=dict(first=str(first),last=str(end),sessions=len(sessions)),
        history_role='previously_observed_development_evidence_not_unseen_holdout',
        quantity_rules='STAR minimum200 increment1; other frozen board lots; no change to existing accounts',
        rule_reference='https://edu.sse.com.cn/tib/qa/c/4866268.shtml'))
    code = [Path(__file__), Path('src/quant/research/personal_top5_construction.py'),
            Path('src/quant/research/personal_top5_report.py')]
    code += sorted(Path('src/quant/backtest').glob('*.py'))
    code += [Path('src/quant/research')/f'{name}.py' for name in ('classic_monthly_baseline','factor_cost_checkpoint')]
    code += [Path('src/quant/reporting')/f'{name}.py' for name in ('period_metrics','multifactor_assessment','calendar_turnover','cycle_stress')]
    write_json(output/'manifest.json', dict(version=1, frozen_at=dt.datetime.now().isoformat(),
        code={str(p):digest(p) for p in code},
        inputs={str(p.relative_to(output)):digest(p) for p in sorted(inputs.rglob('*')) if p.is_file()},
        config_sha256=digest(output/'config.toml'), source_manifest_sha256=digest(output/'source_manifest.json')))
    progress(output, status='frozen', planned_accounts=12, replay_started=False)


def restore_dates(value):
    if isinstance(value, dict):
        return {key:restore_dates(item) for key,item in value.items()}
    if isinstance(value, list):
        return [restore_dates(item) for item in value]
    if isinstance(value, str) and len(value)==10 and value[4]==value[7]=='-':
        try: return dt.date.fromisoformat(value)
        except ValueError: pass
    return value


def execute(output):
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    for name, sha in manifest['code'].items():
        if digest(Path(name)) != sha:
            raise ValueError('Frozen execution code changed: '+name)
    for name, sha in manifest['inputs'].items():
        if digest(output/name) != sha:
            raise ValueError('Frozen input changed: '+name)
    if digest(output/'config.toml') != manifest['config_sha256']:
        raise ValueError('Frozen config changed')
    spec = tomllib.loads((output/'config.toml').read_text(encoding='utf-8'))
    settings = restore_dates(json.loads((output/'inputs/settings.json').read_text()))
    sessions = restore_dates(json.loads((output/'inputs/sessions.json').read_text()))
    plans = {k:pl.read_parquet(output/f'inputs/targets_{k}.parquet') for k in (5,50)}
    controls = {(r['trade_date'],r['symbol']):r for r in pl.read_parquet(output/'inputs/signal_controls.parquet').to_dicts()}
    signal_days = sorted(set(key[0] for key in controls))
    cases = [(k,floor,cost) for k in (50,5) for floor in (5,1) for cost in spec['cost_multipliers']]
    accounts = {key:{} for key in cases}
    completed = 0
    for year in sorted(set(d.year for d in sessions)):
        dates = [day for day in sessions if day.year==year]
        frames = {p.stem:pl.read_parquet(p) for p in (output/f'inputs/{year}').glob('*.parquet')}
        instruments = {r['symbol']:r for r in frames['instruments'].to_dicts()}
        dividends = frames['dividends'].with_columns((pl.col('div_cash')*(1-settings['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
        for key in cases:
            k,floor,cost = key
            name = f'top{k}_fee{floor}_cost{cost:g}'
            folder = output/name/str(year)
            if folder.exists():
                for required in ('orders.parquet','holdings.parquet','exposure.parquet'):
                    if not (folder/required).exists():
                        raise ValueError('Incomplete annual checkpoint: '+str(folder))
                accounts[key], _ = read_year(folder, dates=dates, previous=accounts[key])
                completed += 1
                continue
            progress(output, status='running', account=name, year=year, completed_year_accounts=completed,
                     planned_year_accounts=len(cases)*len(set(d.year for d in sessions)))
            scenario = copy.deepcopy(settings)
            scenario['costs']['a_share']['commission_min'] = floor
            scenario['costs']['a_share']['commission_rate'] = spec['costs']['commission_rate']
            for model in scenario['costs'].values():
                for field in ('commission_rate','commission_min','slippage'):
                    model[field] *= cost
            targets = plans[k].filter(pl.col('execution_date').dt.year()==year)
            states = stock_session_states(bars=frames['bars'], limits=frames['limits'], suspensions=frames['suspensions'],
                sessions=dates, symbols=sorted(instruments), execution_dates=[],
                slippage=scenario['costs']['a_share']['slippage'])
            trace, holdings, exposure = [], [], []
            def transform(batch, state):
                orders,info = fixed_orders(batch,state,controls,instruments,trace)
                day=batch['execution_date'][0]
                # Only actual holdings/targets can trade today. Future annual
                # nominees must not require bands before listing or a code change.
                states.update(stock_session_states(bars=frames['bars'].filter(pl.col('trade_date')==day),
                    limits=frames['limits'].filter(pl.col('trade_date')==day),
                    suspensions=frames['suspensions'].filter(pl.col('trade_date')==day),
                    sessions=[day], symbols=orders['symbol'].to_list(), execution_dates=[day],
                    slippage=scenario['costs']['a_share']['slippage']))
                return orders,info
            def observe(day,state):
                eq = state['nav'][-1]['equity']
                as_of = signal_days[bisect.bisect_right(signal_days,day)-1]
                industries, maximum, unknown = {}, 0., 0.
                for symbol, item in state['holdings'].items():
                    weight = item['quantity']*item['mark_price']/eq
                    meta = controls.get((as_of,symbol),{})
                    industry = meta.get('industry_l1')
                    industries[industry] = industries.get(industry,0.)+weight
                    maximum=max(maximum,weight)
                    if industry is None: unknown += weight
                    holdings.append(dict(date=day,symbol=symbol,quantity=item['quantity'],mark_price=item['mark_price'],
                        weight=weight,industry=industry,total_market_value=meta.get('total_market_value'),
                        metadata_as_of=as_of))
                exposure.append(dict(date=day,cash=state['cash'],equity=eq,holdings=len(state['holdings']),
                    above_target_count=len(state['holdings'])>k,max_name_weight=maximum,
                    max_industry_weight=max(industries.values(),default=0.),unknown_industry_weight=unknown))
            chunk = personal_replay(bars=frames['bars'],calendar=frames['calendar'], instruments=frames['instruments'],
                targets=targets,dividends=dividends,market_states=states,config=scenario,sessions=dates,
                name=f'personal_top{k}',validate_once=True,account_state=accounts[key],
                target_constraints=transform,daily_observer=observe)
            stage = folder.parent/f'.{year}-{uuid.uuid4().hex}'
            save_year(stage,account=accounts[key],chunks=chunk,target_records=[])
            for label,rows in [('orders',trace),('holdings',holdings),('exposure',exposure)]:
                pl.from_dicts(rows,infer_schema_length=None).write_parquet(stage/f'{label}.parquet') if rows else pl.DataFrame().write_parquet(stage/f'{label}.parquet')
            stage.rename(folder)
            completed+=1
    from quant.research.personal_top5_report import report
    report(output)
    progress(output,status='complete',completed_accounts=12,completed_year_accounts=completed)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=DEFAULT)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('data'))
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--freeze-only',action='store_true')
    args=parser.parse_args()
    try:
        if not args.resume: freeze(args.config,args.output,args.data_root)
        if not args.freeze_only: execute(args.output)
    except Exception as exc:
        if args.output.exists(): progress(args.output,status='incomplete',error=type(exc).__name__+': '+str(exc))
        raise


if __name__=='__main__': main()
