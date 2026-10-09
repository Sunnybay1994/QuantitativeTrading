"""One CNY100k treatment with the original three-cost personal account as control."""
import bisect
import copy
import datetime as dt
import json
from pathlib import Path
import uuid
import tomllib

import polars as pl

from quant.research.personal_top5 import digest, restore_dates, write_json
from quant.research.personal_top5_construction import fixed_orders, personal_replay, rank_targets
from quant.research.admitted_model_pair_publication import publish_completed_year


def matched_account_schedule(targets, frozen_sessions, end):
    """Both accounts start in cash on the control grid; never inherit an earlier holding."""
    if not frozen_sessions or frozen_sessions != sorted(set(frozen_sessions)) or frozen_sessions[-1] != end:
        raise ValueError('Control account must have a complete ordered execution grid')
    first = frozen_sessions[0]
    before = targets.filter(pl.col('as_of') < first)
    selected = targets.filter((pl.col('as_of') >= first) & (pl.col('execution_date') <= end))
    if set(selected['execution_date']) - set(frozen_sessions):
        raise ValueError('Treatment execution date is absent from the frozen control grid')
    return selected, before


def freeze_inputs(spec, output, data_root):
    from quant.data.factor_battery_inputs import read_battery_execution, read_frozen_battery_universe
    from quant.data.factor_panels import available_sessions
    from quant.data.equal_weight_index import load_return_benchmarks
    from quant.research.benchmark_reuse import context
    old = Path(spec['control_account'])
    settings = restore_dates(json.loads((old/'inputs/settings.json').read_text()))
    model = restore_dates(json.loads((old/'inputs/model.json').read_text()))
    end = settings['run']['as_of']
    pred = pl.read_parquet(output/'predictions/monthly_predictions.parquet')
    universe = read_frozen_battery_universe(statistics=Path(model['research']['statistics_source']),
        as_of_dates=pred['trade_date'].unique().to_list(), include_tradeability=True)
    sessions = available_sessions(data_root, end)
    targets, ranking = rank_targets(pred, universe, sessions, end, 5, .02)
    sessions = restore_dates(json.loads((old/'inputs/sessions.json').read_text()))
    targets, excluded = matched_account_schedule(targets, sessions, end)
    reference = pl.read_parquet(old/'inputs/targets_5.parquet')
    if set(targets['as_of']) != set(reference['as_of']):
        raise ValueError('Treatment signal schedule differs from control; missing post-entry signals cannot silently carry holdings')
    first = sessions[0]
    symbols = set(targets['symbol'])
    for event in settings['share_exchanges']:
        if event['from_symbol'] in symbols:
            symbols.add(event['to_symbol'])
    personal = tomllib.loads(Path(spec['personal_config']).read_text(encoding='utf-8'))
    snapshot = json.loads((Path(personal['inputs']['source_account'])/'summary.json').read_text())['execution_snapshot']
    plans = {'5': ('personal_top5', targets)}
    before = context(settings=settings, plans=plans, sessions=tuple(sessions), data_root=data_root, snapshot=snapshot)
    inputs = output/'account_inputs'; inputs.mkdir(exist_ok=False)
    targets.write_parquet(inputs/'targets.parquet'); ranking.write_parquet(inputs/'ranking.parquet')
    excluded.write_parquet(inputs/'excluded_before_control_window.parquet')
    universe.write_parquet(inputs/'signal_controls.parquet')
    for year in sorted(set(day.year for day in sessions)):
        folder = inputs/str(year); folder.mkdir()
        frames = read_battery_execution(data_root=data_root, refresh_config=Path(settings['data']['refresh_config']),
            snapshot=snapshot, start=max(first, dt.date(year, 1, 1)), end=min(end, dt.date(year, 12, 31)),
            symbols=sorted(symbols), include_all_dividends=True)
        for name, frame in frames.items():
            frame.write_parquet(folder/f'{name}.parquet')
    after = context(settings=settings, plans=plans, sessions=tuple(sessions), data_root=data_root, snapshot=snapshot)
    if before != after:
        raise ValueError('Execution source changed during freeze; preserve partial inputs and use a new run')
    for name, frame in load_return_benchmarks(config=Path(spec['return_benchmark_config']), data_root=data_root,
                                            start=first, end=end).items():
        frame.write_parquet(inputs/f'benchmark_{name}.parquet')
    for name in ('settings.json', 'model.json', 'stress.json'):
        (inputs/name).write_bytes((old/'inputs'/name).read_bytes())
    write_json(inputs/'sessions.json', sessions)
    write_json(inputs/'manifest.json', {'sources': before,
        'inputs': {str(p.relative_to(inputs)): digest(p) for p in inputs.rglob('*') if p.is_file()},
        'predictions_sha256': digest(output/'predictions/monthly_predictions.parquet')})


def run(spec, output, *, data_root):
    from quant.data.stock_execution_inputs import stock_session_states
    from quant.research.factor_cost_checkpoint import read_year, save_year
    inputs = output/'account_inputs'
    if not inputs.exists():
        freeze_inputs(spec, output, data_root)
    manifest = json.loads((inputs/'manifest.json').read_text())
    for path, sha in manifest['inputs'].items():
        if digest(inputs/path) != sha:
            raise ValueError('Frozen account input changed: '+path)
    if digest(output/'predictions/monthly_predictions.parquet') != manifest['predictions_sha256']:
        raise ValueError('Account predictions changed')
    settings = restore_dates(json.loads((inputs/'settings.json').read_text()))
    sessions = restore_dates(json.loads((inputs/'sessions.json').read_text()))
    targets = pl.read_parquet(inputs/'targets.parquet')
    controls = {(r['trade_date'], r['symbol']): r for r in pl.read_parquet(inputs/'signal_controls.parquet').to_dicts()}
    signal_days = sorted({k[0] for k in controls})
    accounts = {cost: {} for cost in spec['cost_multipliers']}
    for year in sorted({day.year for day in sessions}):
        dates = [day for day in sessions if day.year == year]
        frames = {p.stem: pl.read_parquet(p) for p in (inputs/str(year)).glob('*.parquet')}
        instruments = {r['symbol']: r for r in frames['instruments'].to_dicts()}
        dividends = frames['dividends'].with_columns((pl.col('div_cash') *
            (1-settings['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
        for cost in spec['cost_multipliers']:
            folder = output/f'extended_cost{cost:g}'/str(year)
            if folder.exists():
                if not all((folder/name).exists() for name in ('orders.parquet', 'holdings.parquet', 'exposure.parquet')):
                    raise ValueError('Incomplete treatment year checkpoint')
                accounts[cost], _ = read_year(folder, dates=dates, previous=accounts[cost]); continue
            scenario = copy.deepcopy(settings)
            scenario['portfolio']['initial_cash'] = 100000.
            scenario['costs']['a_share']['commission_min'] = 1.
            scenario['costs']['a_share']['commission_rate'] = .00025
            for model in scenario['costs'].values():
                for key in ('commission_rate', 'commission_min', 'slippage'):
                    model[key] *= cost
            states = stock_session_states(bars=frames['bars'], limits=frames['limits'], suspensions=frames['suspensions'],
                sessions=dates, symbols=sorted(instruments), execution_dates=[], slippage=scenario['costs']['a_share']['slippage'])
            orders, holdings, exposure = [], [], []
            def transform(batch, state):
                planned, info = fixed_orders(batch, state, controls, instruments, orders)
                day = batch['execution_date'][0]
                states.update(stock_session_states(bars=frames['bars'].filter(pl.col('trade_date') == day),
                    limits=frames['limits'].filter(pl.col('trade_date') == day),
                    suspensions=frames['suspensions'].filter(pl.col('trade_date') == day), sessions=[day],
                    symbols=planned['symbol'].to_list(), execution_dates=[day], slippage=scenario['costs']['a_share']['slippage']))
                return planned, info
            def observe(day, state):
                equity = state['nav'][-1]['equity']
                as_of = signal_days[bisect.bisect_right(signal_days, day)-1]
                industries, maximum, unknown = {}, 0., 0.
                for symbol, item in state['holdings'].items():
                    weight = item['quantity']*item['mark_price']/equity
                    meta = controls.get((as_of, symbol), {}); industry = meta.get('industry_l1')
                    industries[industry] = industries.get(industry, 0.)+weight
                    maximum = max(maximum, weight)
                    if industry is None: unknown += weight
                    holdings.append({'date': day, 'symbol': symbol, **item, 'weight': weight,
                        'industry': industry, 'total_market_value': meta.get('total_market_value'), 'metadata_as_of': as_of})
                exposure.append({'date': day, 'cash': state['cash'], 'equity': equity, 'holdings': len(state['holdings']),
                    'max_name_weight': maximum, 'max_industry_weight': max(industries.values(), default=0.),
                    'unknown_industry_weight': unknown})
            chunk = personal_replay(bars=frames['bars'], calendar=frames['calendar'], instruments=frames['instruments'],
                targets=targets.filter(pl.col('execution_date').dt.year() == year), dividends=dividends,
                market_states=states, config=scenario, sessions=dates, name='personal_top5', validate_once=True,
                account_state=accounts[cost], target_constraints=transform, daily_observer=observe)
            stage = folder.parent/f'.{year}-{uuid.uuid4().hex}'
            save_year(stage, account=accounts[cost], chunks=chunk, target_records=[])
            for name, rows in (('orders', orders), ('holdings', holdings), ('exposure', exposure)):
                (pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()).write_parquet(stage/f'{name}.parquet')
            publish_completed_year(stage, folder)
            write_json(output/'account_progress.json', {'year': year, 'cost': cost, 'auto_trade': False})
    from quant.research.admitted_model_pair_report import report
    return report(spec, output)
