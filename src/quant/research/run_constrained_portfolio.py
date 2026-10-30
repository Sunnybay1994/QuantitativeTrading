"""Replay fixed R4 construction against the saved Q10 and Top50 accounts."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.backtest.share_exchanges import validate_exchanges
from quant.data.factor_battery_inputs import read_battery_universe_dates
from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.factor_panels import available_sessions
from quant.data.risk_model_inputs import standardize
from quant.portfolio.constrained_selection import constrained_targets
from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
from quant.reporting.multifactor_assessment import assess_model
from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
from quant.research.factor_battery_costs import run_cost_plans
from quant.research.run_multifactor_replay import model_target_plans, signal_sell_permission


def prepare_constrained_hook(*, scores: pl.DataFrame, targets: pl.DataFrame,
                             statistics: Path, policy: dict, score_column: str,
                             minimum_signal_stocks: int | None = None,
                             data_root: Path | None = None):
    """Prepare R4 once for a frozen score method, also consumed by nightly N5."""
    dates = sorted(set(targets['as_of']))
    universe = read_battery_universe_dates(statistics=statistics, as_of_dates=dates,
        data_root=data_root, include_tradeability=True)
    universe = standardize(universe.with_columns(pl.col('total_market_value').log().alias('size')), ['size'])
    universe = universe.with_columns(pl.col('industry_l1').fill_null('UNKNOWN'))
    markets = universe.select(pl.col('trade_date').alias('as_of'),
        pl.col('trade_date').alias('known_at'), 'symbol', 'eligible', 'industry_l1',
        'total_market_value', 'size', pl.col('amount20').alias('adv20'),
        pl.col('eligible').alias('can_buy'), signal_sell_permission().alias('can_sell'))
    market_days = {k[0]: frame for k, frame in markets.partition_by('as_of', as_dict=True).items()}
    score_days = {k[0]: frame.select(pl.col('trade_date').alias('as_of'), 'symbol',
        pl.col(score_column).alias('score')) for k, frame in scores.partition_by('trade_date', as_dict=True).items()}

    def transform(batch: pl.DataFrame, state: dict) -> tuple[pl.DataFrame, dict]:
        day = batch['as_of'][0]
        signal = score_days.get(day, pl.DataFrame(schema={'as_of': pl.Date, 'symbol': pl.String, 'score': pl.Float64}))
        minimum = minimum_signal_stocks if minimum_signal_stocks is not None else policy['top_k']
        if (batch['weight'] > 0).any() and signal.filter(pl.col('score').is_finite()).height < minimum:
            raise ValueError('Positive constrained targets require the registered minimum signal pool')
        return constrained_targets(targets=batch, state=state, market=market_days.get(day, markets.head(0)),
            scores=signal, policy=policy)

    extra = scores.select(pl.col('trade_date').alias('as_of'), 'symbol').join(
        targets.select('as_of', 'execution_date').unique(), on='as_of').select('execution_date', 'symbol')
    return transform, extra, markets


def window_metrics(nav: pl.DataFrame, start: dt.date, end: dt.date) -> dict:
    selected = nav.with_columns(pl.col('equity').shift(1).alias('prior')).filter(
        pl.col('date').is_between(start, end))
    if selected.is_empty() or not selected.filter(pl.col('market_value') > 0).height:
        return {'applicable': False, 'return': None, 'max_drawdown': None}
    initial = selected['prior'][0]
    values = [initial, *selected['equity'].to_list()]
    peak, drawdown = initial, 0.
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value/peak-1)
    return {'applicable': True, 'return': values[-1]/initial-1, 'max_drawdown': drawdown}


def verify_execution_caps(output: Path, sessions: tuple[dt.date, ...]) -> dict:
    """Compare each saved gross fill against its prior-signal ADV currency cap."""
    next_session = dict(zip(sessions, sessions[1:]))
    count, maximum = 0, 0.
    for path in sorted((output/'constrained').glob('cost_*/*/constraints.json')):
        diagnostics = json.loads(path.read_text(encoding='utf-8'))
        caps = {}
        for info in diagnostics:
            date = next_session[dt.date.fromisoformat(info['as_of'])]
            for symbol, cap in info.get('execution_notional_caps', {}).items():
                caps[date, symbol] = cap
        trades = pl.read_parquet(path.parent/'trades.parquet')
        grouped = trades.group_by('date', 'symbol').agg(pl.col('notional').sum())
        for row in grouped.to_dicts():
            cap = caps.get((row['date'], row['symbol']), 0.)
            if row['notional'] > cap+1e-6:
                raise ValueError(f"Executed fill exceeds signal ADV cap: {path} {row}")
            maximum = max(maximum, row['notional']/cap if cap else 0.)
            count += 1
    return {'checked_symbol_trade_days': count, 'maximum_cap_utilization': maximum, 'violations': 0}


def run(*, config: Path, output: Path, data_root: Path, resume: bool = False) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    research, policy = spec['research'], spec['policy']
    if policy['auto_trade'] is not False:
        raise ValueError('R4 is paper research only')
    source, control = Path(research['predictions']), Path(research['control'])
    model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    if settings != tomllib.loads((control/'battery.toml').read_text(encoding='utf-8')):
        raise ValueError('Q10 and R4 execution settings differ')
    if settings['portfolio']['cost_multipliers'] != policy['cost_multipliers']:
        raise ValueError('Registered costs must match frozen Q10')
    walk = model['walk_forward']
    sessions = available_sessions(data_root, walk['test_end']+dt.timedelta(days=40))
    scores = pl.read_parquet(source/'monthly_predictions.parquet')
    _, targets = model_target_plans(scores, model=model, sessions=sessions)['lightgbm_top50']
    targets = targets.with_columns(pl.lit('r4_constrained').alias('strategy'))
    transform, extra, markets = prepare_constrained_hook(scores=scores, targets=targets,
        statistics=Path(research['statistics']), policy=policy, score_column='lightgbm',
        minimum_signal_stocks=model['models']['minimum_signal_stocks'])
    if resume:
        if (output/'config.toml').read_bytes() != config.read_bytes():
            raise ValueError('Resume requires unchanged preregistration')
    else:
        output.mkdir(parents=True, exist_ok=False)
        (output/'config.toml').write_bytes(config.read_bytes())
        for file in ('model.toml', 'battery.toml'):
            (output/file).write_bytes((source/file).read_bytes())
        markets.write_parquet(output/'signal_controls.parquet')
    settings['target_constraints_config'] = config.read_text(encoding='utf-8')
    settings['share_exchanges'] = validate_exchanges(tomllib.loads(
        (control/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges'])
    snapshot = json.loads((control/'summary.json').read_text(encoding='utf-8'))['execution_snapshot']

    run_cost_plans(settings=settings, plans={'constrained': ('r4_constrained', targets)},
        sessions=sessions, output=output, data_root=data_root, execution_snapshot=snapshot,
        factor=research['id'], start=walk['test_start'], resume=resume,
        target_constraints=transform, constraint_execution_symbols=extra)
    execution_caps = verify_execution_caps(output, sessions)
    reports = [collect_cost_report(run=folder, benchmarks=Path(research['benchmarks']),
        data_root=data_root, return_benchmark_config=Path(research['return_benchmark_config']))
        for folder in (control, output)]
    rows = [row for report in reports for row in report['rows']]
    windows, monthly_windows, annual_turnover = [], [], {}
    for row in rows:
        folder = output if row['variant'] == 'constrained' else control
        nav, trades = load_cost_history(folder, row['variant'], row['cost_multiplier'], walk['test_end'])
        measured = calendar_turnover(nav, trades)
        annual_turnover[f"{row['variant']}/{row['cost_multiplier']:g}"] = measured
        row['legacy_252_turnover'] = row['annualized_one_way_turnover']
        row['annualized_one_way_turnover'] = measured['median']
        row['maximum_calendar_turnover'] = measured['maximum']
        windows.append({'variant': row['variant'], 'cost_multiplier': row['cost_multiplier'],
            **window_metrics(nav, spec['replacement']['stress_start'], spec['replacement']['stress_end'])})
        monthly_windows.append({'variant': row['variant'], 'cost_multiplier': row['cost_multiplier'],
            **window_metrics(nav, dt.date(2024, 1, 1), dt.date(2024, 1, 31))})
    diagnostics = [r for path in sorted((output/'constrained').glob('cost_*/*/constraints.json'))
                   for r in json.loads(path.read_text(encoding='utf-8'))]
    old = next(r for r in rows if r['variant'] == 'budgeted' and r['cost_multiplier'] == 1.)
    new = next(r for r in rows if r['variant'] == 'constrained' and r['cost_multiplier'] == 1.)
    checks = {'drawdown_improved': new['max_drawdown'] > old['max_drawdown'],
        'cagr_loss_at_most_2pp': new['cagr'] >= old['cagr']-spec['replacement']['maximum_cagr_loss'],
        'all_signal_constraints_satisfied': bool(diagnostics) and all(r['constraints_satisfied'] for r in diagnostics)}
    assessments = json.loads(Path(research['control_assessment']).read_text(encoding='utf-8'))['assessments']
    baselines = load_return_benchmarks(config=Path(research['return_benchmark_config']), data_root=data_root,
        start=walk['test_start'], end=walk['test_end'])
    baselines = {('510300_total_return_reference' if k == '510300' else k): v for k, v in baselines.items()}
    model['admission']['benchmarks'] = list(baselines)
    stress = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    nav, _ = load_cost_history(output, 'constrained', 1., walk['test_end'])
    two = next(r for r in rows if r['variant'] == 'constrained' and r['cost_multiplier'] == 2.)
    assessment = assess_model(nav=nav, one=new, two=two, benchmarks=baselines, model=model, windows=stress)
    benchmark_comparisons = [row for report in reports for row in report['benchmark_comparisons']]
    double_excess = min(r['net_cagr_excess'] for r in benchmark_comparisons
        if r['variant'] == 'constrained' and r['cost_multiplier'] == 2.)
    assessment['double_cost_excess'] = double_excess
    assessment['checks']['turnover'] = turnover_passes(new['annualized_one_way_turnover'], double_excess)
    checks['source_admission_conditions'] = all(assessment['checks'].values())
    assessment['conclusion'] = 'PAPER_CANDIDATE' if all(checks.values()) else 'REJECTED'
    assessments['constrained'] = assessment
    result = {'experiment_id': research['id'], 'assessments': assessments,
        'replacement_conclusion': assessments['constrained']['conclusion'],
        'rows': rows, 'stress_2024_01': windows, 'replacement_checks': checks,
        'natural_month_2024_01': monthly_windows,
        'calendar_turnover': annual_turnover,
        'benchmark_comparisons': benchmark_comparisons,
        'execution_caps': execution_caps,
        'replace_q10_construction': all(checks.values()), 'diagnostic_signals': len(diagnostics),
        'constrained_signals': sum(r['constraints_satisfied'] for r in diagnostics),
        'reference_accounts': str(control), 'evidence': research['evidence']}
    (output/'assessment.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    lines = ['# Q10 三种组合构建', '', '冻结预测；实际持股期统一费用，Top50与0.5预算复用原始逐日账户。', '',
        '|构建|成本|持股期年化|Sharpe|最大回撤|日历换手中位数|最大值|', '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"|{r['variant']}|{r['cost_multiplier']:g}|{r['cagr']:.2%}|{r['sharpe']:.3f}|{r['max_drawdown']:.2%}|"
                     f"{r['annualized_one_way_turnover']:.3f}|{r['maximum_calendar_turnover']:.3f}|")
    lines += ['', f"## 2024-01 压力窗口（{spec['replacement']['stress_start']}至{spec['replacement']['stress_end']}）",
        '', '|构建|成本|收益|回撤|', '|---|---:|---:|---:|']
    for r in windows:
        lines.append(f"|{r['variant']}|{r['cost_multiplier']:g}|{r['return']:.2%}|{r['max_drawdown']:.2%}|" if r['applicable']
                     else f"|{r['variant']}|{r['cost_multiplier']:g}|不适用|不适用|")
    lines += ['', '## 自然月 2024-01-01 至 2024-01-31', '',
        '|构建|成本|收益|回撤|', '|---|---:|---:|---:|']
    for r in monthly_windows:
        lines.append(f"|{r['variant']}|{r['cost_multiplier']:g}|{r['return']:.2%}|{r['max_drawdown']:.2%}|" if r['applicable']
                     else f"|{r['variant']}|{r['cost_multiplier']:g}|不适用|不适用|")
    lines += ['', f"结论：{result['replacement_conclusion']}；替换条件 {json.dumps(checks, ensure_ascii=False)}。",
        f"约束满足 {result['constrained_signals']}/{len(diagnostics)} 个成本场景信号，其余完整冻结实际股数。",
        f"逐笔ADV参与率核验：{execution_caps['checked_symbol_trade_days']}个标的成交日，"
        f"超限{execution_caps['violations']}，最大额度利用率{execution_caps['maximum_cap_utilization']:.2%}。",
        '', '关键限制：这是既有历史的回顾比较；信号目标约束与价格漂移后的实际暴露分别记录。', '']
    (output/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    from quant.reporting.experiment_registry import register_run
    register_run(output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), default=str))


if __name__ == '__main__':
    main()
