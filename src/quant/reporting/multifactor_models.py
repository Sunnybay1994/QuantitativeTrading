"""Three-benchmark reports and automatic conclusions for complete model replays."""
import argparse
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_benchmarks import read_etf_total_return
from quant.data.factor_panels import available_sessions
from quant.reporting.multifactor_assessment import assess_model
from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history


def render_model_report(method: str, *, rows: list[dict], assessment: dict, model: dict,
                        coverage: list[dict] | None = None) -> str:
    one = assessment['primary']
    rules = ', '.join(name for name, passed in one['checks'].items() if not passed) or '全部通过'
    lines = [f'# {method}：{one["conclusion"]}', '',
        f"区间：{model['walk_forward']['test_start']}—{model['walk_forward']['test_end']}；"
        f"主组合Top{model['portfolio']['primary_top_k']}，最强基准为{one['strongest_benchmark']}，"
        f"1×年化超额{one['net_cagr_excess']*100:.2f}个百分点。", '',
        '|持仓数|成本|年化|Sharpe|最大回撤|单边年换手|平均仓位|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        top_k = row['variant'].rsplit('top', 1)[1]
        lines.append(f"|{top_k}|{row['cost_multiplier']:g}×|{row['cagr']:.2%}|{row['sharpe']:.2f}|"
            f"{row['max_drawdown']:.2%}|{row['annualized_one_way_turnover']:.2f}|{row['mean_invested_fraction']:.2%}|")
    lines += ['', 'Top100仅作敏感性报告，不能替代失败的Top50。', '',
              '510300采用不扣交易成本的分红总回报参考；股票等权基准报告实际仓位。', '',
              '|1×基准|年化|最大回撤|平均股票仓位|', '|---|---:|---:|---:|']
    for row in one['benchmarks']:
        invested = f"{row['mean_invested_fraction']:.2%}" if row['mean_invested_fraction'] is not None else '总回报参考'
        lines.append(f"|{row['benchmark']}|{row['cagr']:.2%}|{row['max_drawdown']:.2%}|{invested}|")
    lines += ['', f"首次股票持仓：{one['active_start']}；实际观察跨度{one['active_years']:.2f}年；"
        f"最长水下期{one['underwater']['years']:.2f}日历年（{one['underwater']['peak_date']}至"
        f"{one['underwater']['end_date']}）。", '',
        '|年份（末年截至回放日）|模型收益|固定最强基准收益|跑赢|', '|---|---:|---:|---|']
    for row in one['annual']:
        lines.append(f"|{row['year']}|{row['model_return']:.2%}|{row['benchmark_return']:.2%}|{row['outperformed']}|")
    lines += ['', '|极端窗口|模型收益|基准收益|模型回撤|基准回撤|收益与回撤均不劣|', '|---|---:|---:|---:|---:|---|']
    for row in one['stress']:
        lines.append(f"|{row['window']}|{row['model_return']:.2%}|{row['benchmark_return']:.2%}|"
            f"{row['model_max_drawdown']:.2%}|{row['benchmark_max_drawdown']:.2%}|{row['not_worse']}|")
    if coverage is not None:
        lines += ['', '|执行年份|月度信号数|有足够预测股票|缺失原因与次数|', '|---|---:|---:|---|']
        for year in sorted({row['test_year'] for row in coverage}):
            annual = [row for row in coverage if row['test_year'] == year]
            reasons = {}
            for row in annual:
                if not row['signal_available']:
                    reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
            labels = {'no_admitted_factors': '历史合格因子不足',
                      'no_complete_training_history': '共同训练样本不足',
                      'insufficient_complete_feature_rows': '共同预测截面不足'}
            details = '、'.join(f'{labels.get(reason, reason)}={count}'
                              for reason, count in sorted(reasons.items())) or '无'
            lines.append(f"|{year}|{len(annual)}|{sum(row['signal_available'] for row in annual)}|{details}|")
        lines += ['', '信号缺失与实际仓位分别报告；按预注册规则处理缺失，不把空仓收益解释成有效预测。']
    lines += ['', f"年度胜率{one['annual_outperformance_fraction']:.1%}；极端窗口通过"
        f"{one['stress_windows_not_worse']}/4。未满足条件：{rules}。", '',
        '下一步：进入模拟盘第二账户并记录前向收益。' if one['conclusion'] == 'PAPER_CANDIDATE' else
        '下一步：保留本次结果，结合未通过条件决定后续模型研究；观察跨度不足时继续积累前向数据。', '',
        '关键限制：这是一轮复用历史数据的年度滚动研究。', '']
    return '\n'.join(lines)


def report_models(*, run: Path, benchmarks: Path, output: Path, data_root: Path) -> dict:
    model_bytes = (run/'model.toml').read_bytes()
    model = tomllib.loads(model_bytes.decode('utf-8'))
    settings = tomllib.loads((run/'battery.toml').read_text(encoding='utf-8'))
    source = json.loads((run/'summary.json').read_text(encoding='utf-8'))
    if source['factor'] != model['research']['id']:
        raise ValueError('Model config differs from replay')
    tops = (model['portfolio']['primary_top_k'], model['portfolio']['sensitivity_top_k'])
    expected = {(f'{method}_top{top}', cost) for method in model['models']['methods']
                for top in tops for cost in model['portfolio']['cost_multipliers']}
    observed = [(row['variant'], row['cost_multiplier']) for row in source['rows']]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError('Require every registered model, portfolio size and cost scenario')
    walk = model['walk_forward']
    if walk['test_end'] != settings['run']['as_of']:
        raise ValueError('Model and battery end dates differ')
    grid = [date for date in available_sessions(data_root, walk['test_end'])
            if walk['test_start'] <= date <= walk['test_end']]
    navs = {}
    for variant, multiplier in observed:
        nav, _ = load_cost_history(run, variant, multiplier, walk['test_end'])
        if nav['date'].to_list() != grid:
            raise ValueError('Every cost scenario must retain every registered session, including cash years')
        if multiplier == 1.:
            navs[variant] = nav
    report = collect_cost_report(run=run, benchmarks=benchmarks, etf_reference=True, data_root=data_root)
    baselines = {name: load_cost_history(benchmarks, name, 1., walk['test_end'])[0]
                 for name in ('csi800_equal_weight', 'all_market_equal_weight')}
    baselines['510300_total_return_reference'] = read_etf_total_return(data_root=data_root,
        snapshot=settings['data']['etf_total_return_snapshot'], end=walk['test_end'])
    windows = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    assessments = {}
    for method in model['models']['methods']:
        assessment = {}
        for top in tops:
            variant = f'{method}_top{top}'
            rows = {row['cost_multiplier']: row for row in report['rows'] if row['variant'] == variant}
            nav = navs[variant]
            assessment['primary' if top == tops[0] else 'sensitivity'] = assess_model(
                nav=nav, one=rows[1.], two=rows[2.], benchmarks=baselines, model=model, windows=windows)
        assessments[method] = assessment
    result = {'source_run': str(run.resolve()), 'models': assessments,
              'conclusions': {name: value['primary']['conclusion'] for name, value in assessments.items()}}
    coverage_path = run/'model_signal_coverage.parquet'
    coverage = pl.read_parquet(coverage_path) if coverage_path.is_file() else None
    output.mkdir(parents=True, exist_ok=False)
    (output/'model.toml').write_bytes(model_bytes)
    (output/'summary.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    pl.from_dicts(report['rows'], infer_schema_length=None).write_parquet(output/'cost_metrics.parquet')
    pl.from_dicts(report['benchmark_comparisons'], infer_schema_length=None).write_parquet(output/'benchmark_comparisons.parquet')
    if coverage is not None:
        coverage.write_parquet(output/'model_signal_coverage.parquet')
    for method, assessment in assessments.items():
        folder = output/method
        folder.mkdir()
        rows = [row for row in report['rows'] if row['variant'].startswith(f'{method}_top')]
        (folder/'report.md').write_text(render_model_report(method, rows=rows, assessment=assessment, model=model,
                                       coverage=coverage.to_dicts() if coverage is not None else None),
                                       encoding='utf-8')
        (folder/'assessment.json').write_text(json.dumps(assessment, indent=2, default=str), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--benchmarks', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(report_models(run=args.run, benchmarks=args.benchmarks, output=args.output,
                                   data_root=args.data_root)['conclusions']))


if __name__ == '__main__':
    main()
