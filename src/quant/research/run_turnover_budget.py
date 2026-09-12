"""Full-calendar paired turnover-budget replay using frozen source predictions."""
import argparse
import copy
import datetime as dt
import json
import tomllib
from pathlib import Path

from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.factor_panels import available_sessions
from quant.reporting.multifactor_assessment import assess_model
from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
from quant.research.factor_battery_costs import run_cost_plans

import polars as pl

from quant.research.run_multifactor_replay import model_target_plans


def residual_target_summary(targets: pl.DataFrame) -> dict:
    """Describe retained planned positions outside the original monthly selection."""
    residual = (pl.col('desired_weight') == 0) & (pl.col('weight') > 0)
    monthly = targets.group_by('as_of').agg(
        residual.sum().alias('residual_names'),
        pl.when(residual).then(pl.col('weight')).otherwise(0.).sum().alias('residual_weight'),
        (residual & (pl.col('weight') < .001)).sum().alias('residual_names_below_10bp'))
    return {'signals':monthly.height,'mean_residual_names':monthly['residual_names'].mean(),
        'maximum_residual_names':monthly['residual_names'].max(),
        'mean_residual_weight':monthly['residual_weight'].mean(),
        'maximum_residual_weight':monthly['residual_weight'].max(),
        'mean_residual_names_below_10bp':monthly['residual_names_below_10bp'].mean(),
        'basis':'Budget-adjusted target weights; not realized close holdings'}


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
            'residual_targets': residual_target_summary(targets),
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
                'median_fills_per_trade_day': trades.group_by('date').len()['len'].median(),
                'small_fill_fraction': trades.filter(pl.col('notional') < 5000.).height/trades.height if trades.height else None,
                'fills': trades.height, 'fills_under_5000': trades.filter(pl.col('notional') < 5000.).height,
                'mean_active_positions': active['position_count'].mean(),
                'maximum_positions': active['position_count'].max(),
                'fees': trades['fee'].sum(), 'slippage_cost': trades['slippage_cost'].sum()})
    result = {'active_results': rows, 'target_adjustments': adjustments}
    (output/'turnover_diagnostics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def assess_budget_variants(*, histories: dict, rows: list[dict], baselines: dict,
                           model: dict, windows: list[dict]) -> dict:
    expected = {(variant, cost) for variant in ('control', 'budgeted') for cost in (.5, 1., 2.)}
    if {(r['variant'], r['cost_multiplier']) for r in rows} != expected or len(rows) != len(expected):
        raise ValueError('Require six paired cost scenarios')
    if len({r['active_start'] for r in rows}) != 1:
        raise ValueError('Paired comparisons require identical holding windows')
    measured_model = copy.deepcopy(model)
    measured_model['admission']['benchmarks'] = list(baselines)
    assessments = {}
    for variant in ('control', 'budgeted'):
        measured = {r['cost_multiplier']: r for r in rows if r['variant'] == variant}
        assessments[variant] = assess_model(nav=histories[variant], one=measured[1.], two=measured[2.],
            benchmarks=baselines, model=measured_model, windows=windows)
    return assessments


def write_budget_report(output: Path, result: dict) -> None:
    lines = ['# 固定月度换手预算回放', '', '冻结预测、统一成本；从首次实际持股起连续计量，保留其后现金期。', '',
        '|组合|成本|持股期年化|Sharpe|最大回撤|单边年换手|', '|---|---:|---:|---:|---:|---:|']
    def fmt(value, style='.2%'):
        return format(value, style) if value is not None else 'NA'
    for r in result['rows']:
        lines.append(f"|{r['variant']}|{r['cost_multiplier']}|{fmt(r['cagr'])}|{fmt(r['sharpe'], '.3f')}|"
            f"{fmt(r['max_drawdown'])}|{fmt(r['annualized_one_way_turnover'], '.2f')}|")
    for variant, assessment in result['assessments'].items():
        failed = ', '.join(k for k, v in assessment['checks'].items() if not v)
        lines += ['', f"{variant}：{assessment['conclusion']}；未通过：{failed or '无'}。",
            f"最强收益指数：{assessment['strongest_benchmark']}；年化超额：{fmt(assessment['net_cagr_excess'])}；"
            f"压力通过 {assessment['stress_windows_not_worse']}/{assessment['stress_windows_total']}。", '',
            '|窗口|策略收益|基准收益|判定|', '|---|---:|---:|---|']
        for s in assessment['stress']:
            status = ('通过' if s['not_worse'] else '未通过') if s['applicable'] else f"不适用：{s['reason']}"
            lines.append(f"|{s['window']}|{fmt(s.get('model_return'))}|{fmt(s.get('benchmark_return'))}|{status}|")
    lines += ['', '固定0.5预算约束目标调整距离，实际成交换手仍受价格、现金和整手影响；已研究历史只作回顾性对照。']
    if result.get('execution_improvement'):
        lines += ['', '## 小额调仓暂缓：相对原Q10预算组合', '',
            '执行改善条件：'+json.dumps(result['execution_improvement'], ensure_ascii=False), '',
            '|组合|成本|成交日中位笔数|平均持仓|最大持仓|成交笔数|小于5000占比|费用|滑点成本|',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for row in result['actual_execution']['active_results']:
            lines.append(f"|{row['variant']}|{row['cost_multiplier']}|{row['median_fills_per_trade_day']}|"
                f"{row['mean_active_positions']:.2f}|{row['maximum_positions']}|{row['fills']}|"
                f"{row['small_fill_fraction']:.2%}|{row['fees']:.2f}|{row['slippage_cost']:.2f}|")
        lines += ['', '|组合|成本|收益基准|同窗基准年化|年化超额|', '|---|---:|---|---:|---:|']
        for row in result['benchmark_comparisons']:
            lines.append(f"|{row['variant']}|{row['cost_multiplier']}|{row['benchmark']}|"
                f"{fmt(row['benchmark_cagr'])}|{fmt(row['net_cagr_excess'])}|")
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def run(*, config: Path, output: Path, data_root: Path, resume: bool = False,
        share_exchanges_config: Path = Path('configs/data/share_exchanges_20260912.toml')) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    research, policy = spec['research'], spec['policy']
    allocations = {'linear_blend_current_holdings_toward_original_targets': 'linear_blend',
                   'complete_adjustments': 'complete_adjustments'}
    if policy['auto_trade'] is not False:
        raise ValueError('Research requires auto_trade=false')
    if 'return_benchmark_config' not in research:
        raise ValueError('Require return_benchmark_config; account benchmarks cannot supply performance comparisons')
    if policy.get('allocation') not in allocations:
        raise ValueError('Unknown registered budget allocation')
    measurement_path = Path(research['return_benchmark_config'])
    measurement_bytes = measurement_path.read_bytes()
    source, benchmarks = Path(research['predictions']), Path(research['benchmarks'])
    model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    if spec.get('small_adjustment') and model['admission']['maximum_annualized_one_way_turnover'] != 6.:
        raise ValueError('Q12 must retain original 6x turnover admission')
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
    if resume:
        for filename, expected in [('config.toml', config.read_bytes()), ('measurement.toml', measurement_bytes),
            ('model.toml', (source/'model.toml').read_bytes()), ('battery.toml', (source/'battery.toml').read_bytes())]:
            if (output/filename).read_bytes() != expected:
                raise ValueError('Resume requires unchanged saved inputs')
    else:
        output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    (output/'measurement.toml').write_bytes(measurement_bytes)
    for filename in ('battery.toml', 'model.toml'):
        (output/filename).write_bytes((source/filename).read_bytes())
    snapshot = json.loads((benchmarks/'summary.json').read_text())['execution_snapshot']
    from quant.backtest.share_exchanges import validate_exchanges
    event_content = share_exchanges_config.read_text(encoding='utf-8')
    settings['share_exchanges'] = validate_exchanges(tomllib.loads(event_content)['share_exchanges'])
    saved_events = output/'share_exchanges.toml'
    if resume:
        if not saved_events.is_file() or saved_events.read_text(encoding='utf-8') != event_content:
            raise ValueError('Resume requires unchanged share exchanges')
    else:
        saved_events.write_text(event_content,encoding='utf-8')
    if allocations[policy['allocation']] != 'linear_blend':
        settings['turnover_allocations'] = {'budgeted': allocations[policy['allocation']]}
    budgets = {'budgeted': policy['monthly_one_way_budget']}
    if spec.get('small_adjustment'):
        if policy['monthly_one_way_budget'] != .5 or policy['allocation'] != 'linear_blend_current_holdings_toward_original_targets':
            raise ValueError('Small-adjustment experiment requires unchanged Q10 budget')
        settings['small_adjustment_floors'] = {'budgeted': spec['small_adjustment']['floor_cny']}
        budgets['control'] = policy['monthly_one_way_budget']
    run_cost_plans(settings=settings, plans={'control': (name, targets), 'budgeted': (name, targets)},
        sessions=sessions, output=output, data_root=data_root, execution_snapshot=snapshot,
        factor=research['id'], start=walk['test_start'],
        turnover_budgets=budgets, resume=resume)
    report = collect_cost_report(run=output, benchmarks=benchmarks, data_root=data_root,
                                 return_benchmark_config=output/'measurement.toml')
    baselines = load_return_benchmarks(config=output/'measurement.toml', data_root=data_root,
        start=walk['test_start'], end=walk['test_end'])
    baselines = {('510300_total_return_reference' if key == '510300' else key): frame for key, frame in baselines.items()}
    windows = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    histories = {}
    for variant in ('control', 'budgeted'):
        nav, _ = load_cost_history(output, variant, 1., walk['test_end'])
        if nav['date'].to_list() != [d for d in sessions if walk['test_start'] <= d <= walk['test_end']]:
            raise ValueError('Incomplete replay calendar')
        histories[variant] = nav
    assessments = assess_budget_variants(histories=histories, rows=report['rows'], baselines=baselines,
        model=model, windows=windows)
    result = {'rows': report['rows'], 'assessments': assessments, 'measurement': report['measurement'],
              'benchmark_comparisons': report['benchmark_comparisons']}
    original_replay = Path(research.get('control_replay', str(source.parent/'replay')))
    comparisons = []
    for multiplier in (.5, 1., 2.):
        original, original_trades = load_cost_history(original_replay, research.get('control_variant', f"{research['method']}_top{research['top_k']}"), multiplier, walk['test_end'])
        control, control_trades = load_cost_history(output, 'control', multiplier, walk['test_end'])
        columns = ['date', 'equity', 'market_value', 'cash', 'unit_nav']
        if not original.select(columns).equals(control.select(columns)):
            raise ValueError('Replayed control differs from frozen original NAV')
        if not original_trades.equals(control_trades):
            raise ValueError('Replayed control trades differ from frozen Q10 reference')
        comparisons.append({'cost_multiplier': multiplier, 'sessions': control.height,
                            'nav_exact_equal': True, 'trades_exact_equal': True})
    (output/'control_comparison.json').write_text(json.dumps(comparisons, indent=2), encoding='utf-8')
    diagnostics = summarize_budget_history(output, end=walk['test_end'], budget=policy['monthly_one_way_budget'])
    if spec.get('small_adjustment'):
        result['actual_execution'] = diagnostics
        result['execution_improvement'] = assess_small_adjustments(result, diagnostics, spec['execution_improvement'])
    (output/'assessment.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    write_budget_report(output, result)
    return result


def assess_small_adjustments(result: dict, diagnostics: dict, policy: dict) -> dict:
    actual = {(r['variant'], r['cost_multiplier']): r for r in diagnostics['active_results']}
    rows = {(r['variant'], r['cost_multiplier']): r for r in result['rows']}
    old, new = actual['control', 1.], actual['budgeted', 1.]
    reduction = 1-new['median_fills_per_trade_day']/old['median_fills_per_trade_day']
    checks = {'median_trade_day_fills': reduction >= policy['minimum_median_trade_day_fills_reduction'],
        'mean_actual_positions': new['mean_active_positions'] <= old['mean_active_positions']}
    for cost in policy['sharpe_not_lower_costs']:
        checks[f'sharpe_{cost:g}'] = rows['budgeted', cost]['sharpe'] >= rows['control', cost]['sharpe']
    for cost in policy['max_drawdown_not_worse_costs']:
        checks[f'drawdown_{cost:g}'] = rows['budgeted', cost]['max_drawdown'] >= rows['control', cost]['max_drawdown']
    sensitivity = dict(result['assessments']['budgeted']['checks'])
    sensitivity['turnover'] = rows['budgeted', 1.]['annualized_one_way_turnover'] <= policy['retrospective_sensitivity_only']
    return {'checks': checks, 'median_trade_day_fills_reduction': reduction,
        'promote_execution_rule': all(checks.values()), 'evidence': 'retrospective',
        'original_admission_unchanged': True,
        'turnover_6_5_retrospective_only': {'checks': sensitivity, 'all_pass': all(sensitivity.values()),
            'does_not_replace_original_admission': True}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--share-exchanges-config',type=Path,default=Path('configs/data/share_exchanges_20260912.toml'))
    args = parser.parse_args()
    run(config=args.config, output=args.output, data_root=args.data_root, resume=args.resume,
        share_exchanges_config=args.share_exchanges_config)


if __name__ == '__main__':
    main()
