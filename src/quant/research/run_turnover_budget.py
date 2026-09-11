"""Full-calendar paired turnover-budget replay using frozen source predictions."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

from quant.data.factor_benchmarks import read_etf_total_return
from quant.data.factor_panels import available_sessions
from quant.reporting.multifactor_assessment import assess_model
from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
from quant.research.factor_battery_costs import run_cost_plans
from quant.research.run_concentration_caps import write_report

import polars as pl

from quant.research.run_multifactor_replay import model_target_plans


def summarize_budget_history(output: Path, *, end: dt.date, budget: float) -> dict:
    rows, adjustments = [], []
    initial = tomllib.loads((output/'battery.toml').read_text(encoding='utf-8'))['portfolio']['initial_cash']
    for multiplier in (.5, 1., 2.):
        paths = sorted((output/'budgeted'/f'cost_{multiplier:g}').glob('*/budget_targets.parquet'))
        targets = pl.concat([pl.read_parquet(path) for path in paths])
        monthly = targets.group_by('as_of').agg(
            ((pl.col('weight')-pl.col('current_weight')).abs().sum()/2).alias('planned_turnover'),
            ((pl.col('desired_weight')-pl.col('current_weight')).abs().sum()/2).alias('desired_turnover'))
        if monthly.filter(pl.col('planned_turnover') > budget+1e-9).height:
            raise ValueError('Monthly target turnover exceeds registered budget')
        adjustments.append({'cost_multiplier': multiplier, 'signals': monthly.height,
            'binding_signals': monthly.filter(pl.col('desired_turnover') > budget+1e-9).height,
            'maximum_planned_turnover': monthly['planned_turnover'].max(),
            'mean_planned_turnover': monthly['planned_turnover'].mean()})
        for variant in ('control', 'budgeted'):
            nav, trades = load_cost_history(output, variant, multiplier, end)
            nav = nav.with_columns(pl.col('equity').shift(1).fill_null(initial).alias('prior'))
            active = nav.filter(pl.col('date') >= nav.filter(pl.col('market_value') > 0)['date'].min())
            daily = trades.group_by('date').agg(pl.col('notional').sum()).join(
                active.select('date', 'prior'), on='date')
            rows.append({'variant': variant, 'cost_multiplier': multiplier, 'active_sessions': active.height,
                'active_cagr': (active['equity'][-1]/active['prior'][0])**(252/active.height)-1,
                'active_turnover': daily.select((pl.col('notional')/pl.col('prior')/2).sum()).item()*252/active.height,
                'fills': trades.height, 'fills_under_5000': trades.filter(pl.col('notional') < 5000.).height,
                'mean_active_positions': active['position_count'].mean(),
                'maximum_positions': active['position_count'].max(),
                'fees': trades['fee'].sum(), 'slippage_cost': trades['slippage_cost'].sum()})
    result = {'active_results': rows, 'target_adjustments': adjustments}
    (output/'turnover_diagnostics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def run(*, config: Path, output: Path, data_root: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    research, policy = spec['research'], spec['policy']
    if policy['auto_trade'] is not False:
        raise ValueError('Research requires auto_trade=false')
    source, benchmarks = Path(research['predictions']), Path(research['benchmarks'])
    model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    reference = tomllib.loads((benchmarks/'battery.toml').read_text(encoding='utf-8'))
    for key in ('portfolio', 'costs', 'universe', 'run', 'data'):
        if settings[key] != reference[key]:
            raise ValueError(f'Benchmark mismatch: {key}')
    walk = model['walk_forward']
    sessions = available_sessions(data_root, walk['test_end']+dt.timedelta(days=40))
    scores = pl.read_parquet(source/'monthly_predictions.parquet')
    name, targets = model_target_plans(scores, model=model, sessions=sessions)[
        f"{research['method']}_top{research['top_k']}"]
    # Each execution month gets one budget; reject a source with extra signals.
    dates = targets.select('as_of', 'execution_date').unique()
    if dates.select(pl.col('execution_date').dt.strftime('%Y-%m')).is_duplicated().any():
        raise ValueError('Monthly budget requires at most one signal per execution month')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    for filename in ('battery.toml', 'model.toml'):
        (output/filename).write_bytes((source/filename).read_bytes())
    snapshot = json.loads((benchmarks/'summary.json').read_text())['execution_snapshot']
    run_cost_plans(settings=settings, plans={'control': (name, targets), 'budgeted': (name, targets)},
        sessions=sessions, output=output, data_root=data_root, execution_snapshot=snapshot,
        factor=research['id'], start=walk['test_start'],
        turnover_budgets={'budgeted': policy['monthly_one_way_budget']})
    report = collect_cost_report(run=output, benchmarks=benchmarks, etf_reference=True, data_root=data_root)
    baselines = {key: load_cost_history(benchmarks, key, 1., walk['test_end'])[0]
        for key in ('csi800_equal_weight', 'all_market_equal_weight')}
    baselines['510300_total_return_reference'] = read_etf_total_return(data_root=data_root,
        snapshot=settings['data']['etf_total_return_snapshot'], end=walk['test_end'])
    windows = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    assessments = {}
    for variant in ('control', 'budgeted'):
        rows = {row['cost_multiplier']: row for row in report['rows'] if row['variant'] == variant}
        nav, _ = load_cost_history(output, variant, 1., walk['test_end'])
        if nav['date'].to_list() != [d for d in sessions if walk['test_start'] <= d <= walk['test_end']]:
            raise ValueError('Incomplete replay calendar')
        assessments[variant] = assess_model(nav=nav, one=rows[1.], two=rows[2.],
            benchmarks=baselines, model=model, windows=windows)
    result = {'rows': report['rows'], 'assessments': assessments}
    summarize_budget_history(output, end=walk['test_end'], budget=policy['monthly_one_way_budget'])
    (output/'assessment.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    write_report(output, result, title='固定月度换手预算回放',
        description='2015—2026-08；日历LightGBM Top50固定预测，按实际信号日持仓限制月度目标调整。',
        caveat='复用已有历史，信号权重调整预算不保证实际成交额上限。')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    run(config=args.config, output=args.output, data_root=args.data_root)


if __name__ == '__main__':
    main()
