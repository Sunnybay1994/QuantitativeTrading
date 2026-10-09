"""Frozen, continuous personal-account evaluation of the fixed PEAD40 hypothesis."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import shutil
import time
import tomllib
import uuid

import polars as pl

from quant.research.residual_momentum_inputs import digest, write_json


DEFAULT = Path('configs/research/pead_account_v1_20260930.toml')
FRAME_NAMES = ('nav', 'trades', 'rejections', 'positions', 'decisions')


def code_files():
    package = Path(__file__).resolve().parents[1]
    names = ['research/pead_account.py', 'research/pead_account_inputs.py',
             'research/pead_account_replay.py', 'research/pead_account_actions.py',
             'research/pead_account_report.py', 'research/personal_top5_construction.py',
             'research/residual_momentum_inputs.py', 'backtest/daily_account.py',
             'backtest/daily_simulator.py', 'backtest/costs.py', 'backtest/rules.py',
             'backtest/share_exchanges.py', 'reporting/multifactor_assessment.py',
             'reporting/calendar_turnover.py', 'reporting/period_metrics.py',
             'reporting/cycle_stress.py', 'research/factor_battery_cost_report.py']
    paths = [package/name for name in names]
    paths.extend(sorted((package/'domain').rglob('*.py')))
    return {str(p.relative_to(package)).replace('\\', '/'): p for p in paths}


def freeze_benchmarks(*, spec, output, data_root):
    from quant.data.equal_weight_index import load_return_benchmarks
    settings = tomllib.loads(Path(spec['inputs']['return_benchmark_config']).read_text(encoding='utf8'))
    sources = [data_root/'clean/equal_weight_indexes'/settings['benchmarks']['equal_weight_snapshot']/n
               for n in ('data.parquet', 'events.parquet', 'summary.json')]
    sources.append(data_root/'clean/factor_benchmarks'/settings['benchmarks']['etf_total_return_snapshot']/'prices.parquet')
    before = {str(p): digest(p) for p in sources}
    folder = output/'benchmarks'
    folder.mkdir()
    starts = {'510300': dt.date(2012, 5, 29), 'all_market_equal_weight': dt.date(2010, 2, 1),
              'csi800_equal_weight': dt.date(2010, 2, 1)}
    for name, first in starts.items():
        frame = load_return_benchmarks(config=Path(spec['inputs']['return_benchmark_config']),
            data_root=data_root, start=first, end=spec['inputs']['end'], names=[name])[name]
        frame.write_parquet(folder/f'{name}.parquet')
    if any(digest(Path(p)) != sha for p, sha in before.items()):
        raise ValueError('Return-index source changed during freeze')
    (folder/'config.toml').write_bytes(Path(spec['inputs']['return_benchmark_config']).read_bytes())
    write_json(folder/'manifest.json', {'sources_sha256': before,
        'files': {p.name: digest(p) for p in folder.iterdir() if p.is_file()},
        'corporate_consideration_review_pending': True})


def input_identity(spec):
    return {**{key: spec['inputs'][key] for key in ('event_root', 'execution_snapshot',
            'limits_snapshot', 'start', 'end')}, 'share_exchanges': spec['share_exchanges']}


def freeze(*, config, output, data_root, reuse_inputs=None):
    from quant.research.pead_account_inputs import freeze_account_inputs, verify_frozen_inputs
    spec = tomllib.loads(config.read_text(encoding='utf8'))
    if (spec['auto_trade'] is not False or spec['paper']['auto_trade'] is not False
            or spec['paper']['initial_cash'] != 100000
            or spec['cases'] != ['pead40', 'all_events']
            or spec['cost_multipliers'] != [.5, 1., 2.]
            or spec['portfolio']['slots'] != 5
            or spec['costs']['a_share']['commission_min'] != 1):
        raise ValueError('Unsupported account experiment')
    sources = code_files()
    hashes = {name: digest(p) for name, p in sources.items()}
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    for name, source in (('model_rules.toml', spec['inputs']['model_rules']),
                         ('stress.toml', spec['inputs']['stress_config'])):
        (output/name).write_bytes(Path(source).read_bytes())
    code = output/'code_snapshot'
    code.mkdir()
    for name, path in sources.items():
        target = code/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    write_json(output/'registration.json', {'registered_at': dt.datetime.now(dt.timezone.utc),
        'auto_trade': False, 'code_sha256': hashes,
        'config_sha256': digest(output/'config.toml'), 'account_replays': 0})
    if reuse_inputs is None:
        freeze_account_inputs(source=Path(spec['inputs']['event_root']), output=output,
            data_root=data_root, start=spec['inputs']['start'], end=spec['inputs']['end'],
            share_exchange_config=output/'config.toml')
    else:
        original = tomllib.loads((reuse_inputs/'config.toml').read_text(encoding='utf8'))
        manifest = verify_frozen_inputs(output=reuse_inputs)
        if (input_identity(spec) != input_identity(original)
                or manifest.get('calendar_end', '') < str(spec['inputs']['end'])):
            raise ValueError('Reusable inputs differ from the frozen account specification')
        manifest_sha = digest(reuse_inputs/'inputs/manifest.json')
        shutil.copytree(reuse_inputs/'inputs', output/'inputs')
        verify_frozen_inputs(output=output)
        if digest(output/'inputs/manifest.json') != manifest_sha:
            raise ValueError('Reusable input receipt changed during copy')
        write_json(output/'input_reuse.json', {'source': str(reuse_inputs),
            'manifest_sha256': manifest_sha, 'identity': input_identity(spec),
            'account_results_reused': False})
    freeze_benchmarks(spec=spec, output=output, data_root=data_root)
    if any(digest(p) != hashes[name] for name, p in sources.items()):
        raise ValueError('Account implementation changed during input freeze')
    write_json(output/'plan.json', {'frozen_at': dt.datetime.now(dt.timezone.utc),
        'auto_trade': False, 'code_sha256': hashes,
        'files': {name: digest(output/name) for name in ('config.toml', 'model_rules.toml',
                  'stress.toml', 'registration.json', 'inputs/manifest.json', 'benchmarks/manifest.json')},
        'cases': spec['cases'], 'cost_multipliers': spec['cost_multipliers']})
    return {'stage': 'account_inputs_frozen', 'output': str(output), 'auto_trade': False}


def verify_plan(output):
    plan = json.loads((output/'plan.json').read_text(encoding='utf8'))
    for path, sha in plan['files'].items():
        if digest(output/path) != sha:
            raise ValueError('Frozen account file changed: '+path)
    for path, sha in plan['code_sha256'].items():
        source = Path(__file__).resolve().parents[1]/path
        if digest(source) != sha or digest(output/'code_snapshot'/path) != sha:
            raise ValueError('Account code changed: '+path)
    return plan


def read_checkpoint(folder, *, dates, previous, plan_sha):
    receipt = json.loads((folder/'receipt.json').read_text(encoding='utf8'))
    if receipt['plan_sha256'] != plan_sha or receipt['previous_state'] != previous:
        raise ValueError('Annual checkpoint context changed')
    for name, sha in receipt['files'].items():
        if digest(folder/name) != sha:
            raise ValueError('Annual checkpoint changed: '+name)
    state = json.loads((folder/'account.json').read_text(encoding='utf8'))
    nav = pl.read_parquet(folder/'nav.parquet')
    if (nav['date'].to_list() != dates or state['date'] != str(dates[-1])
            or state['nav'][:-len(dates)] != previous.get('nav', [])
            or state['cash'] != nav['cash'][-1]):
        raise ValueError('Annual checkpoint does not continue the actual account')
    saved_nav = pl.from_dicts(state['nav'][-len(dates):], infer_schema_length=None).with_columns(
        pl.col('date').str.to_date())
    if not saved_nav.equals(nav):
        raise ValueError('Account checkpoint and saved NAV disagree')
    return state


def save_checkpoint(folder, result, *, previous, plan_sha):
    folder.parent.mkdir(parents=True, exist_ok=True)
    stage = folder.parent/f'.{folder.name}-unfinished-{uuid.uuid4().hex}'
    stage.mkdir()
    for name in FRAME_NAMES:
        result[name].write_parquet(stage/f'{name}.parquet')
    write_json(stage/'account.json', result['state'])
    write_json(stage/'receipt.json', {'plan_sha256': plan_sha, 'previous_state': previous,
        'files': {p.name: digest(p) for p in stage.iterdir() if p.is_file()}})
    for attempt in range(4):
        try:
            stage.rename(folder)
            return
        except PermissionError:
            if attempt == 3 or folder.exists():
                raise
            time.sleep(.1*(attempt+1))


def run(*, output):
    from quant.research.pead_account_replay import _controls, replay
    from quant.research.pead_account_inputs import verify_frozen_inputs
    plan = verify_plan(output)
    verify_frozen_inputs(output=output)
    spec = tomllib.loads((output/'config.toml').read_text(encoding='utf8'))
    inputs = output/'inputs'
    calendar = pl.read_parquet(inputs/'calendar.parquet')
    all_sessions = sorted(set(calendar.filter(pl.col('is_open'))['date']))
    sessions = [d for d in all_sessions if spec['inputs']['start'] <= d <= spec['inputs']['end']]
    events = pl.read_parquet(inputs/'eligibility_events.parquet')
    instruments = pl.read_parquet(inputs/'instruments.parquet')
    dividends = pl.read_parquet(inputs/'dividends.parquet').with_columns(
        (pl.col('div_cash')*(1-spec['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
    coverage = pl.read_parquet(inputs/'suspension_coverage.parquet')
    plan_sha = digest(output/'plan.json')
    accounts = {(case, cost): {} for case in plan['cases'] for cost in plan['cost_multipliers']}
    for year in sorted({d.year for d in sessions}):
        dates = [d for d in sessions if d.year == year]
        warmup = all_sessions[max(0, all_sessions.index(dates[0])-20)]
        frames = {name: pl.scan_parquet(inputs/f'{name}.parquet').filter(
            pl.col('trade_date').is_between(warmup, dates[-1])).collect()
            for name in ('bars', 'limits', 'suspensions')}
        controls = _controls(frames['bars'], all_sessions)
        for case, cost in accounts:
            folder = output/f'{case}_cost{cost:g}'/str(year)
            previous = accounts[case, cost]
            if folder.exists():
                accounts[case, cost] = read_checkpoint(folder, dates=dates, previous=previous, plan_sha=plan_sha)
                continue
            verify_plan(output)
            result = replay(events=events, calendar=calendar, instruments=instruments,
                dividends=dividends, config=spec, case=case, cost_multiplier=cost,
                account_state=copy.deepcopy(previous) if previous else None, sessions=dates,
                suspension_coverage=coverage, controls=controls, **frames)
            verify_plan(output)
            save_checkpoint(folder, result, previous=previous, plan_sha=plan_sha)
            accounts[case, cost] = read_checkpoint(folder, dates=dates, previous=previous, plan_sha=plan_sha)
            print(json.dumps({'completed_year': year, 'case': case, 'cost': cost,
                              'auto_trade': False}), flush=True)
    return report(output=output)


def report(*, output):
    from quant.research.pead_account_report import write_report
    plan = verify_plan(output)
    spec = tomllib.loads((output/'config.toml').read_text(encoding='utf8'))
    data = {}
    expected_sessions = sorted(set(pl.read_parquet(output/'inputs/calendar.parquet')
        .filter(pl.col('is_open') & pl.col('date').is_between(spec['inputs']['start'], spec['inputs']['end']))['date']))
    for case in plan['cases']:
        for cost in plan['cost_multipliers']:
            folder = output/f'{case}_cost{cost:g}'
            frames = {}
            for name in FRAME_NAMES:
                chunks = [pl.read_parquet(p/f'{name}.parquet') for p in sorted(folder.iterdir())
                          if p.is_dir() and p.name.isdigit()]
                frames[name] = pl.concat(chunks, how='diagonal_relaxed')
                frames[name].write_parquet(folder/f'{name}.parquet')
            if frames['nav']['date'].to_list() != expected_sessions:
                raise ValueError('Account report requires the complete registered timeline')
            data[case, cost] = frames
    benchmarks = {p.stem: pl.read_parquet(p) for p in (output/'benchmarks').glob('*.parquet')}
    benchmarks['510300_total_return_reference'] = benchmarks.pop('510300')
    result = write_report(output/'evaluation', accounts=data, benchmarks=benchmarks,
        initial_cash=spec['paper']['initial_cash'], treatment='pead40', control='all_events',
        stress_windows=tomllib.loads((output/'stress.toml').read_text(encoding='utf8'))['windows'],
        admission_rules=tomllib.loads((output/'model_rules.toml').read_text(encoding='utf8'))['admission'],
        expected_sessions=expected_sessions)
    (output/'summary.json').write_bytes((output/'evaluation/summary.json').read_bytes())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('freeze', 'run', 'report'), required=True)
    parser.add_argument('--config', type=Path, default=DEFAULT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--reuse-inputs', type=Path)
    args = parser.parse_args()
    if args.stage == 'freeze':
        result = freeze(config=args.config, output=args.output, data_root=args.data_root,
                        reuse_inputs=args.reuse_inputs)
    elif args.stage == 'run':
        result = run(output=args.output)
    else:
        result = report(output=args.output)
    print(json.dumps({'stage': args.stage, 'output': str(args.output), 'auto_trade': False,
        'result': result.get('development_decision', result.get('stage', result.get('status')))},
        ensure_ascii=False, default=str), flush=True)


if __name__ == '__main__':
    main()
