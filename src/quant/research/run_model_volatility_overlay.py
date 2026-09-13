"""Paired frozen-model monthly benchmark risk experiments."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.backtest.share_exchanges import validate_exchanges
from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.factor_panels import available_sessions
from quant.portfolio.selection import scale_target_weights_to_volatility
from quant.reporting.multifactor_assessment import assess_model
from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
from quant.research.factor_battery_costs import run_cost_plans
from quant.research.run_multifactor_replay import model_target_plans


def threshold_scale(benchmark: pl.DataFrame, *, as_of: dt.date, policy: dict) -> float:
    kind = policy['kind']
    lookback, reduced = policy['lookback_observations'], policy['reduced_weight']
    if (kind not in ('moving_average', 'drawdown') or type(lookback) is not int or lookback < 2
            or type(reduced) not in (float, int) or not 0 < reduced < 1):
        raise ValueError('Invalid fixed threshold policy')
    if kind == 'drawdown' and not 0 < policy['drawdown_threshold'] < 1:
        raise ValueError('Invalid drawdown threshold')
    if (not benchmark['date'].is_sorted() or benchmark['date'].n_unique() != benchmark.height
            or benchmark['unit_nav'].null_count() or not benchmark['unit_nav'].is_finite().all()
            or (benchmark['unit_nav'] <= 0).any()):
        raise ValueError('Require ordered unique finite reference prices')
    known = benchmark.filter(pl.col('date') <= as_of).tail(lookback)
    if known.height < lookback or known['date'][-1] != as_of:
        return 0.
    values = known['unit_nav']
    triggered = (values[-1] < values.mean() if kind == 'moving_average' else
                 values[-1] <= values.max() * (1 - policy['drawdown_threshold']))
    return float(reduced if triggered else 1.)


def scale_targets(targets: pl.DataFrame, benchmark: pl.DataFrame, policy: dict) -> tuple[pl.DataFrame, pl.DataFrame]:
    kind = policy.get('kind', 'volatility')
    if kind not in ('volatility', 'moving_average', 'drawdown'):
        raise ValueError('Unknown benchmark risk policy')
    prices = benchmark.select(pl.lit('510300.SH').alias('symbol'),
        pl.col('date').alias('trade_date'), pl.col('unit_nav').alias('adjusted_close'),
        pl.lit('CUMULATIVE_FACTOR').alias('adjustment_method'), pl.lit('saved_total_return_index').alias('source'))
    rows, scales = [], []
    for part in targets.sort('as_of', 'symbol').partition_by('as_of'):
        day = part['as_of'][0]
        if kind == 'volatility':
            risk = pl.DataFrame({'as_of': [day], 'strategy': ['benchmark_risk'],
                'strategy_version': ['v1'], 'symbol': ['510300.SH'], 'weight': [1.]})
            scaled = scale_target_weights_to_volatility(targets=risk, prices=prices,
                lookback_observations=policy['lookback_observations'],
                annualized_target_volatility=policy['annualized_target_volatility'],
                annualization_sessions=policy['annualization_sessions'])
            multiplier = scaled['weight'][0]
        else:
            multiplier = threshold_scale(benchmark, as_of=day, policy=policy)
        rows.append(part.with_columns((pl.col('weight') * multiplier).alias('weight')))
        scales.append({'as_of': day, 'scale': multiplier})
    return pl.concat(rows), pl.from_dicts(scales)


def write_report(output: Path, result: dict) -> None:
    policy = tomllib.loads((output/'config.toml').read_text(encoding='utf-8'))['policy']
    lines = ['# SUE v2 基准风险仓位控制', '',
        f"冻结选股与月度信号，规则为{policy.get('kind', 'volatility')}，"
        f"回看{policy['lookback_observations']}日；完整参数见config.toml，实际持仓期计量。", '',
        '|方案|成本|年化收益|Sharpe|最大回撤|单边年换手|',
        '|---|---:|---:|---:|---:|---:|']
    for row in result['rows']:
        lines.append(f"|{row['variant']}|{row['cost_multiplier']}|{row['cagr']:.2%}|"
            f"{row['sharpe']:.3f}|{row['max_drawdown']:.2%}|{row['annualized_one_way_turnover']:.2f}|")
    lines += ['', f"结论：{result['conclusion']}；回撤降低且Sharpe不下降：{result['risk_improvement']}。"]
    for label, assessment in result['assessments'].items():
        failed = ', '.join(k for k, passed in assessment['checks'].items() if not passed)
        lines.append(f"{label} 未通过项：{failed or '无'}。")
    lines += ['', '此前已查看历史，结果用于回顾性比较；下一步由原准入条件和事前记录共同决定。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def run(*, config: Path, output: Path, data_root: Path = Path('data')) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['policy']['reference'] != '510300':
        raise ValueError('Research-only fixed benchmark required')
    source, benchmark_runs = Path(spec['predictions']), Path(spec['benchmarks'])
    model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    walk = model['walk_forward']
    sessions = available_sessions(data_root, walk['test_end'] + dt.timedelta(days=40))
    variant = f"{spec['method']}_top{spec['top_k']}"
    name, targets = model_target_plans(pl.read_parquet(source/'monthly_predictions.parquet'),
        model=model, sessions=sessions)[variant]
    baselines = load_return_benchmarks(config=Path(spec['return_benchmark_config']), data_root=data_root,
        start=walk['test_start'], end=walk['test_end'])
    overlaid, scales = scale_targets(targets, baselines['510300'], spec['policy'])
    event_path = Path(spec['share_exchanges_config'])
    settings['share_exchanges'] = validate_exchanges(tomllib.loads(event_path.read_text())['share_exchanges'])
    output.mkdir(parents=True, exist_ok=False)
    for target, path in {'config.toml': config, 'model.toml': source/'model.toml',
        'battery.toml': source/'battery.toml', 'measurement.toml': Path(spec['return_benchmark_config']),
        'share_exchanges.toml': event_path}.items():
        (output/target).write_bytes(path.read_bytes())
    scales.write_parquet(output/'scales.parquet')
    snapshot = json.loads((benchmark_runs/'summary.json').read_text())['execution_snapshot']
    run_cost_plans(settings=settings, plans={'control': (name, targets), 'overlay': (name, overlaid)},
        sessions=sessions, output=output, data_root=data_root, execution_snapshot=snapshot,
        factor=spec['id'], start=walk['test_start'])
    report = collect_cost_report(run=output, benchmarks=benchmark_runs, data_root=data_root,
        return_benchmark_config=output/'measurement.toml')
    if len({r['active_start'] for r in report['rows']}) != 1:
        raise ValueError('Risk comparison requires identical actual holding windows')
    measured = copy.deepcopy(model)
    measured['admission']['benchmarks'] = list(baselines)
    windows = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text())[
        'cycle_validation']['stress_windows']
    assessments, comparisons = {}, []
    expected_dates = [day for day in sessions if walk['test_start'] <= day <= walk['test_end']]
    for cost in (.5, 1., 2.):
        old_nav, old_trades = load_cost_history(Path(spec['control_replay']), variant, cost, walk['test_end'])
        nav, trades = load_cost_history(output, 'control', cost, walk['test_end'])
        if not old_nav.equals(nav.select(old_nav.columns)) or not old_trades.equals(trades):
            raise ValueError('Paired control NAV or trades differs from frozen source')
        comparisons.append({'cost': cost, 'nav_exact': True, 'trades_exact': True})
    for label in ('control', 'overlay'):
        metrics = {r['cost_multiplier']: r for r in report['rows'] if r['variant'] == label}
        nav, _ = load_cost_history(output, label, 1., walk['test_end'])
        if nav['date'].to_list() != expected_dates:
            raise ValueError('Incomplete replay calendar')
        assessments[label] = assess_model(nav=nav, one=metrics[1.], two=metrics[2.],
            benchmarks=baselines, model=measured, windows=windows)
    one = {r['variant']: r for r in report['rows'] if r['cost_multiplier'] == 1.}
    improves = (abs(one['overlay']['max_drawdown']) < abs(one['control']['max_drawdown']) and
                one['overlay']['sharpe'] >= one['control']['sharpe'])
    result = {'scope': spec['scope'], 'rows': report['rows'], 'assessments': assessments,
        'risk_improvement': improves, 'control_comparison': comparisons,
        'conclusion': 'PAPER_CANDIDATE' if improves and
            assessments['overlay']['conclusion'] == 'PAPER_CANDIDATE' else 'REJECTED'}
    (output/'assessment.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    write_report(output, result)
    from quant.reporting.experiment_registry import register_run
    register_run(output)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps({'conclusion': run(**vars(parser.parse_args()))['conclusion']}))
