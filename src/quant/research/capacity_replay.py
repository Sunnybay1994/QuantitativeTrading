"""Resume yearly Q10 account replays at registered capital sizes with ADV caps."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import re
import tomllib

import polars as pl

from quant.backtest.share_exchanges import validate_exchanges
from quant.data.factor_battery_inputs import read_frozen_battery_universe
from quant.data.factor_panels import available_sessions
from quant.portfolio.capacity_limits import cap_targets
from quant.research.factor_battery_cost_report import collect_cost_report
from quant.research.factor_battery_costs import run_cost_plans
from quant.research.run_multifactor_replay import model_target_plans


def run(config: Path, output: Path, data_root: Path = Path('data')) -> None:
    payload = config.read_bytes()
    spec = tomllib.loads(payload.decode('utf-8'))
    if spec['auto_trade'] is not False or spec['monthly_turnover_budget'] != .5:
        raise ValueError('Require frozen Q10 budget and paper-only research')
    source, predictions = Path(spec['source']), Path(spec['predictions'])
    model_bytes = (predictions/'model.toml').read_bytes()
    battery_bytes = (source/'battery.toml').read_bytes()
    model = tomllib.loads(model_bytes.decode('utf-8'))
    base = tomllib.loads(battery_bytes.decode('utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    for name, content in [('config.toml', payload), ('model.toml', model_bytes), ('battery.toml', battery_bytes),
                          ('share_exchanges.toml', (source/'share_exchanges.toml').read_bytes())]:
        path = output/name
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f'Resume input changed: {name}')
        path.write_bytes(content)
    base['share_exchanges'] = validate_exchanges(tomllib.loads((output/'share_exchanges.toml').read_text())['share_exchanges'])
    base['target_constraints_config'] = payload.decode('utf-8')
    walk = model['walk_forward']
    sessions = available_sessions(data_root, walk['test_end']+dt.timedelta(days=40))
    scores = pl.read_parquet(predictions/'monthly_predictions.parquet')
    name, targets = model_target_plans(scores, model=model, sessions=sessions)['lightgbm_top50']
    controls_path = output/'signal_controls.parquet'
    if not controls_path.exists():
        controls = read_frozen_battery_universe(statistics=Path(spec['statistics']),
            as_of_dates=sorted(set(targets['as_of']))).select('symbol', pl.col('trade_date').alias('as_of'), 'amount20')
        temporary = output/'signal_controls.tmp.parquet'
        controls.write_parquet(temporary)
        temporary.replace(controls_path)
    controls = pl.read_parquet(controls_path)
    days = {k[0]: frame for k, frame in controls.partition_by('as_of', as_dict=True).items()}
    def cap(batch: pl.DataFrame, state: dict) -> tuple[pl.DataFrame, dict]:
        return cap_targets(batch, state, days[batch['as_of'][0]], spec['participation_limit'])
    snapshot = json.loads((source/'summary.json').read_text())['execution_snapshot']
    reports: list[dict] = []
    for capital in spec['initial_capitals']:
        folder = output/f'capital_{capital}'
        resume = folder.exists()
        folder.mkdir(exist_ok=True)
        settings = copy.deepcopy(base)
        settings['portfolio']['initial_cash'] = capital
        battery = re.sub(r'(?m)^initial_cash\s*=.*$', f'initial_cash = {capital}', battery_bytes.decode('utf-8'))
        if tomllib.loads(battery)['portfolio']['initial_cash'] != capital:
            raise ValueError('Failed to set capital')
        (folder/'battery.toml').write_text(battery, encoding='utf-8')
        run_cost_plans(settings=settings, plans={'budgeted': (name, targets)}, sessions=sessions,
            output=folder, data_root=data_root, execution_snapshot=snapshot, factor=spec['id'],
            start=walk['test_start'], turnover_budgets={'budgeted': .5}, resume=resume,
            target_constraints=cap)
        report = collect_cost_report(run=folder, benchmarks=Path(spec['benchmarks']),
            data_root=data_root, return_benchmark_config=Path(spec['return_benchmark_config']))
        reports.extend({**r, 'initial_capital': capital} for r in report['rows'])
        (output/'progress.json').write_text(json.dumps({'completed_capital': capital, 'rows': reports}, default=str), encoding='utf-8')
    (output/'summary.json').write_text(json.dumps({'rows': reports, 'auto_trade': False,
        'interpretation': spec['interpretation']}, default=str, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.output)
