"""Paired full-calendar replay of a frozen monthly concentration policy."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_benchmarks import read_etf_total_return
from quant.data.factor_panels import available_sessions
from quant.portfolio.concentration_caps import cap_targets
from quant.reporting.multifactor_assessment import assess_model
from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
from quant.research.factor_battery_costs import run_cost_plans
from quant.research.run_multifactor_replay import model_target_plans


def write_report(output: Path, result: dict, *, title: str = '固定集中度约束回放',
                 description: str = '2015—2026-08；日历LightGBM Top50固定预测，超限目标缩减后保留现金。',
                 caveat: str = '复用已有历史，目标上限不保证实际成交后或月中持仓上限。') -> None:
    lines = [f'# {title}', '', description, '',
        '|组合|成本|年化|Sharpe|最大回撤|全期单边年换手|平均仓位|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for row in result['rows']:
        lines.append(f"|{row['variant']}|{row['cost_multiplier']:g}×|{row['cagr']:.2%}|"
            f"{row['sharpe']:.3f}|{row['max_drawdown']:.2%}|"
            f"{row['annualized_one_way_turnover']:.2f}|{row['mean_invested_fraction']:.2%}|")
    for variant, assessment in result['assessments'].items():
        failed = ', '.join(key for key, passed in assessment['checks'].items() if not passed)
        lines += ['', f"## {variant}：{assessment['conclusion']}", '',
            f"对最强基准{assessment['strongest_benchmark']}年化超额{assessment['net_cagr_excess']:.2%}；"
            f"年度胜率{assessment['annual_outperformance_fraction']:.1%}，极端窗口通过"
            f"{assessment['stress_windows_not_worse']}/4，最长水下{assessment['underwater']['years']:.2f}年。",
            f'未通过条件：{failed or "无"}。', '',
            '|年份|组合收益|固定最强基准收益|', '|---|---:|---:|']
        lines += [f"|{row['year']}|{row['model_return']:.2%}|{row['benchmark_return']:.2%}|"
                  for row in assessment['annual']]
        lines += ['', '|极端窗口|组合收益|组合回撤|基准收益|基准回撤|', '|---|---:|---:|---:|---:|']
        lines += [f"|{row['window']}|{row['model_return']:.2%}|{row['model_max_drawdown']:.2%}|"
                  f"{row['benchmark_return']:.2%}|{row['benchmark_max_drawdown']:.2%}|"
                  for row in assessment['stress']]
    lines += ['', f'关键限制：{caveat}', '']
    (output/'report.md').write_text('\n'.join(lines), encoding='utf-8')


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
    predictions = pl.read_parquet(source/'monthly_predictions.parquet')
    name, targets = model_target_plans(predictions, model=model, sessions=sessions)[
        f"{research['method']}_top{research['top_k']}"]
    industries = []
    for year in sorted(set(targets['as_of'].dt.year())):
        path = Path(research['statistics'])/'inputs'/str(year)/'universe.parquet'
        industries.append(pl.scan_parquet(path).select('trade_date', 'symbol', 'industry_l1')
            .filter(pl.col('trade_date').is_in(targets['as_of'].unique().implode()))
            .rename({'trade_date': 'as_of'}).collect())
    metadata = pl.concat(industries)
    capped = cap_targets(targets, metadata, **{key: policy[key] for key in (
        'cash_buffer', 'single_stock_weight', 'industry_weight')})
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    (output/'battery.toml').write_bytes((source/'battery.toml').read_bytes())
    (output/'model.toml').write_bytes((source/'model.toml').read_bytes())
    targets.join(metadata, on=['as_of', 'symbol'], how='left').join(
        capped.select('as_of', 'symbol', pl.col('weight').alias('capped_weight')),
        on=['as_of', 'symbol']).write_parquet(output/'allocation.parquet')
    snapshot = json.loads((benchmarks/'summary.json').read_text(encoding='utf-8'))['execution_snapshot']
    run_cost_plans(settings=settings, plans={'control': (name, targets), 'capped': (name, capped)},
        sessions=sessions, output=output, data_root=data_root, execution_snapshot=snapshot,
        factor=research['id'], start=walk['test_start'])
    report = collect_cost_report(run=output, benchmarks=benchmarks, etf_reference=True, data_root=data_root)
    baselines = {key: load_cost_history(benchmarks, key, 1., walk['test_end'])[0]
        for key in ('csi800_equal_weight', 'all_market_equal_weight')}
    baselines['510300_total_return_reference'] = read_etf_total_return(data_root=data_root,
        snapshot=settings['data']['etf_total_return_snapshot'], end=walk['test_end'])
    windows = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    assessments = {}
    for variant in ('control', 'capped'):
        rows = {row['cost_multiplier']: row for row in report['rows'] if row['variant'] == variant}
        nav, _ = load_cost_history(output, variant, 1., walk['test_end'])
        expected = [date for date in sessions if walk['test_start'] <= date <= walk['test_end']]
        if nav['date'].to_list() != expected:
            raise ValueError('Incomplete replay calendar')
        assessments[variant] = assess_model(nav=nav, one=rows[1.], two=rows[2.],
            benchmarks=baselines, model=model, windows=windows)
    result = {'rows': report['rows'], 'assessments': assessments}
    (output/'assessment.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    write_report(output, result)
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
