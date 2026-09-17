"""Reassess saved model accounts on holding windows against official return indexes."""
import argparse
import copy
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.index_benchmarks import read_index_benchmark
from quant.reporting.cycle_stress import path_statistics
from quant.reporting.execution_burden import execution_burden, render_burden
from quant.reporting.multifactor_assessment import assess_model, holding_metrics
from quant.research.factor_battery_cost_report import load_cost_history


def _format(value, kind: str = '.2%') -> str:
    return '不适用' if value is None else format(value, kind)


def apply_constraint_coverage(assessment: dict, *, run: Path, variant: str,
                              costs: list[float]) -> None:
    """Keep an explicit no-trade continuation distinct from verified constraints."""
    scenarios = []
    for cost in costs:
        years = sorted((run/variant/f'cost_{cost:g}').glob('*/account.json'))
        if not years:
            raise ValueError('Missing saved accounts for constraint coverage')
        events: list[dict] = []
        for account in years:
            path = account.parent/'constraints.json'
            if not path.is_file():
                raise ValueError('Missing constraint diagnostics for completed account')
            events.extend(event for event in json.loads(path.read_text(encoding='utf-8'))
                          if event.get('applied', True))
        unverified = [event for event in events if event.get('feasible') is not True]
        if any(event.get('action') not in ('hold_actual_quantities', 'isolate_actual_quantities')
               or event.get('constraints_verified') is not False for event in unverified):
            raise ValueError('Completed constrained replay contains an unsupported failure')
        scenarios.append({'cost_multiplier': cost, 'signal_count': len(events),
            'verified_count': len(events)-len(unverified),
            'unverified_count': len(unverified),
            'hold_dates': [event['as_of'] for event in unverified],
            'isolated_dates': [e['as_of'] for e in unverified if e['action'] == 'isolate_actual_quantities'],
            'isolation_fallback_count': sum('isolation_failure' in e for e in unverified),
            'maximum_unmodeled_held_weight': max(
                (event['unmodeled_held_weight'] for event in unverified), default=0.)})
    verified = all(row['unverified_count'] == 0 for row in scenarios)
    assessment['constraint_coverage'] = {'all_verified': verified, 'scenarios': scenarios}
    assessment['checks']['portfolio_constraints_verified'] = verified
    if not verified:
        assessment['conclusion'] = 'REJECTED'


def render_model_report(method: str, *, rows: list[dict], assessment: dict, model: dict,
                        coverage: list[dict] | None = None) -> str:
    one = assessment['primary']
    failed = ', '.join(k for k, passed in one['checks'].items() if not passed) or '全部通过'
    lines = [f'# {method}：{one["conclusion"]}', '',
        f"原回放：{model['walk_forward']['test_start']}—{model['walk_forward']['test_end']}；"
        f"判定期：{one['active_start'] or '无股票持仓'}—{model['walk_forward']['test_end']}。",
        f"主组合Top{model['portfolio']['primary_top_k']}，同期最强收益指数：{one['strongest_benchmark'] or '不适用'}；"
        f"年化超额：{_format(one['net_cagr_excess'])}。", '',
        '各成本档从自身首次股票持仓至截止日，首日成本及随后现金日均计入。', '',
        '|持仓数|成本|首次持股|观察日数|后续现金日|年化|Sharpe|最大回撤|单边年换手|平均仓位|',
        '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"|{row['variant'].rsplit('top', 1)[1]}|{row['cost_multiplier']:g}×|"
            f"{row['active_start'] or '无'}|{row['sessions']}|{row['cash_sessions_after_entry']}|"
            f"{_format(row['cagr'])}|{_format(row['sharpe'], '.2f')}|{_format(row['max_drawdown'])}|"
            f"{_format(row['annualized_one_way_turnover'], '.2f')}|{_format(row['mean_invested_fraction'])}|")
    lines += ['', '|组合/成本|初始现金期|日数|现金期收益|', '|---|---|---:|---:|']
    for row in rows:
        cash = row['initial_cash_period']
        lines.append(f"|{row['variant']}/{row['cost_multiplier']:g}×|{cash['start']}—{cash['end']}|"
                     f"{cash['sessions']}|{_format(cash['total_return'])}|")
    lines += ['', f"Top{model['portfolio']['sensitivity_top_k']}仅作敏感性报告，不能替代失败的Top{model['portfolio']['primary_top_k']}。",
              '基准为含分红收益序列，名称区分官方指数、ETF参考与自建等权指数，不含整手或现金账户约束。', '',
              '|1×同期收益指数|年化|最大回撤|', '|---|---:|---:|']
    for row in one['benchmarks']:
        lines.append(f"|{row['benchmark']}|{_format(row['cagr'])}|{_format(row['max_drawdown'])}|")
    lines += ['', f"实际观察跨度{one['active_years']:.2f}年；"
              f"最长水下期{_format(one['underwater']['years'] if one['underwater'] else None, '.2f')}日历年。",
              '', '|年份|模型收益|固定最强基准收益|跑赢|', '|---|---:|---:|---|']
    for row in one['annual']:
        lines.append(f"|{row['year']}|{row['model_return']:.2%}|{row['benchmark_return']:.2%}|{row['outperformed']}|")
    lines += ['', '|极端窗口|模型收益|基准收益|模型回撤|基准回撤|判定|', '|---|---:|---:|---:|---:|---|']
    for row in one['stress']:
        verdict = str(row['not_worse']) if row['applicable'] else '不适用：'+row['reason']
        lines.append(f"|{row['window']}|{_format(row.get('model_return'))}|{_format(row.get('benchmark_return'))}|"
            f"{_format(row.get('model_max_drawdown'))}|{_format(row.get('benchmark_max_drawdown'))}|{verdict}|")
    if one.get('constraint_coverage'):
        lines += ['', '风险字段缺失时保留实际股数，估值与公司行动继续；该次约束未验证，不能计为通过。', '',
            '|成本|调仓信号|约束已验证|未验证次数|其中隔离调仓|隔离失败回退|缺风险字段持仓最大权重|', '|---|---:|---:|---:|---:|---:|---:|']
        for row in one['constraint_coverage']['scenarios']:
            lines.append(f"|{row['cost_multiplier']:g}×|{row['signal_count']}|{row['verified_count']}|"
                         f"{row['unverified_count']}|{len(row['isolated_dates'])}|{row['isolation_fallback_count']}|"
                         f"{row['maximum_unmodeled_held_weight']:.3%}|")
    if coverage is not None:
        lines += ['', '|执行年份|月度信号数|有足够预测股票|缺失原因与次数|', '|---|---:|---:|---|']
        for year in sorted({row['test_year'] for row in coverage}):
            annual = [row for row in coverage if row['test_year'] == year]
            reasons: dict[str, int] = {}
            for entry in annual:
                if not entry['signal_available']:
                    reasons[entry['reason']] = reasons.get(entry['reason'], 0)+1
            labels = {'no_admitted_factors': '历史合格因子不足',
                      'no_complete_training_history': '共同训练样本不足',
                      'insufficient_complete_feature_rows': '共同预测截面不足'}
            details = '、'.join(f'{labels.get(reason, reason)}={count}' for reason, count in sorted(reasons.items())) or '无'
            lines.append(f"|{year}|{len(annual)}|{sum(row['signal_available'] for row in annual)}|{details}|")
    lines += ['', f"年度胜率{_format(one['annual_outperformance_fraction'], '.1%')}；极端窗口通过"
        f"{one['stress_windows_not_worse']}/{one['stress_windows_total']}，适用{one['stress_windows_applicable']}。"
        f"未满足条件：{failed}。",
        '无股票持仓时为研究观察不足。阈值保持冻结，不因不适用窗口减少要求。', '',
        '下一步：按既有冻结条件和前向观察推进。', '关键限制：本报告复用已研究历史，后续仍需真实事前记录。', '']
    return '\n'.join(lines)


def report_models(*, run: Path, output: Path, data_root: Path,
                  measurement_config: Path | None = None, benchmarks: Path | None = None,
                  resume: bool = False) -> dict:
    if measurement_config is None or benchmarks is not None:
        raise ValueError('Supply --measurement-config with return indexes; account benchmarks are unsupported')
    if output.exists() and not resume:
        raise FileExistsError('Use a new report directory; retain old results')
    measurement_bytes = measurement_config.read_bytes()
    measurement = tomllib.loads(measurement_bytes.decode('utf-8'))
    use_equal_weight = 'benchmarks' in measurement
    if use_equal_weight and ('index_codes' in measurement or 'index_version' in measurement):
        raise ValueError('Choose either registered equal-weight references or official index diagnostics')
    codes = [] if use_equal_weight else measurement['index_codes']
    if not use_equal_weight and (len(codes) != 3 or len(set(codes)) != 3 or not set(codes) <= {
            'H00300.CSI', 'H00905.CSI', 'H00852.CSI', 'H00906.CSI', 'H00985.CSI'}):
        raise ValueError('Select three distinct official total-return index codes')
    model_bytes = (run/'model.toml').read_bytes()
    model = tomllib.loads(model_bytes.decode('utf-8'))
    if resume and output.exists():
        expected_inputs = {'model.toml': model_bytes, 'measurement.toml': measurement_bytes}
        for name, content in expected_inputs.items():
            if (output/name).exists() and (output/name).read_bytes() != content:
                raise ValueError('Resume report inputs changed; use a new directory')
    constraint_path = run/'constraints_config.toml'
    constraint_bytes = constraint_path.read_bytes() if constraint_path.exists() else None
    constraint_settings = tomllib.loads(constraint_bytes.decode('utf-8')) if constraint_bytes else {}
    if resume and (output/'constraints_config.toml').exists():
        if constraint_bytes is None or (output/'constraints_config.toml').read_bytes() != constraint_bytes:
            raise ValueError('Resume report constraints changed')
    elif resume and constraint_bytes is not None and any(
            (output/name).exists() for name in ('summary.json', 'cost_metrics.parquet')):
        raise ValueError('Resume report constraints changed; use a new directory')
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
    navs, report_rows = {}, []
    burden_rows = []
    for variant, multiplier in observed:
        nav, trades = load_cost_history(run, variant, multiplier, walk['test_end'])
        if nav['date'].to_list() != grid:
            raise ValueError('Every cost scenario must retain every registered session, including cash years')
        navs[variant, multiplier] = nav
        burden_rows.append({'variant': variant, 'cost_multiplier': multiplier, **execution_burden(nav, trades)})
        report_rows.append({'variant': variant, 'cost_multiplier': multiplier,
            **holding_metrics(nav, trades, initial_cash=settings['portfolio']['initial_cash'])})
    baselines, index_details = {}, []
    if use_equal_weight:
        baselines = load_return_benchmarks(config=measurement_config, data_root=data_root,
                                         start=walk['test_start'], end=walk['test_end'])
        baselines = {('510300_total_return_reference' if name == '510300' else name): frame
                     for name, frame in baselines.items()}
        if set(baselines) != {'510300_total_return_reference', 'csi800_equal_weight', 'all_market_equal_weight'}:
            raise ValueError('Require the three registered dividend and equal-weight references')
        for name, baseline in baselines.items():
            if (baseline.columns != ['date', 'unit_nav'] or baseline['date'].to_list() != grid
                    or baseline['unit_nav'].null_count() or not baseline['unit_nav'].is_finite().all()
                    or (baseline['unit_nav'] <= 0).any()):
                raise ValueError('Return benchmarks require the complete model session grid')
            index_details.append({'name': name, 'return_type': 'total_return',
                                  'source': 'etf_reference' if name.startswith('510300') else 'monthly_equal_weight'})
    for code in codes:
        frame = read_index_benchmark(data_root=data_root, version=measurement['index_version'],
            index_code=code, start=walk['test_start'], end=walk['test_end'], required_return_type='total_return')
        if (frame['trade_date'].to_list() != grid or frame['daily_return'].null_count()
                or not frame['daily_return'].is_finite().all() or (frame['daily_return'] <= -1).any()
                or frame['index_name'].n_unique() != 1 or set(frame['return_type']) != {'total_return'}):
            raise ValueError('Official return index requires the complete model session grid')
        name = f"{frame['index_name'][0]} ({code})"
        baselines[name] = frame.select(pl.col('trade_date').alias('date'),
            (1+pl.col('daily_return')).cum_prod().alias('unit_nav'))
        index_details.append({'code': code, 'name': frame['index_name'][0], 'return_type': 'total_return'})
    window_path = Path(measurement.get('stress_windows_config', model['admission']['stress_windows_config']))
    window_bytes = window_path.read_bytes()
    windows = tomllib.loads(window_bytes.decode('utf-8'))['cycle_validation']['stress_windows']
    if resume and (output/'stress_windows.toml').exists() and (output/'stress_windows.toml').read_bytes() != window_bytes:
        raise ValueError('Resume report stress windows changed')
    measured_model = copy.deepcopy(model)
    measured_model['admission']['benchmarks'] = list(baselines)
    comparisons = []
    for row in report_rows:
        if row['active_start'] is not None:
            for name, baseline in baselines.items():
                risk = path_statistics(baseline, start=row['active_start'], end=walk['test_end'])
                comparisons.append({'variant': row['variant'], 'cost_multiplier': row['cost_multiplier'],
                    'benchmark': name, 'start': row['active_start'], 'end': walk['test_end'],
                    'benchmark_cagr': risk['cagr'], 'strategy_cagr': row['cagr'],
                    'net_cagr_excess': row['cagr']-risk['cagr'],
                    'benchmark_total_return': risk['total_return'], 'sessions': risk['sessions']})
    assessments = {}
    for method in model['models']['methods']:
        assessment = {}
        for top in tops:
            variant = f'{method}_top{top}'
            rows = {row['cost_multiplier']: row for row in report_rows if row['variant'] == variant}
            measured = assess_model(
                nav=navs[variant, 1.], one=rows[1.], two=rows[2.], benchmarks=baselines,
                model=measured_model, windows=windows)
            if (constraint_settings.get('missing_held_controls_policy') in ('hold_actual_quantities', 'isolate_actual_quantities')
                    and f'p4_{variant}' in constraint_settings.get('strategy_names', [])):
                apply_constraint_coverage(measured, run=run, variant=variant,
                    costs=model['portfolio']['cost_multipliers'])
            assessment['primary' if top == tops[0] else 'sensitivity'] = measured
        assessments[method] = assessment
    result = {'source_run': str(run.resolve()), 'models': assessments,
              'measurement': {**measurement, 'indexes': index_details,
                  'original_benchmarks': model['admission']['benchmarks'],
                  'window': 'first_stock_holding_through_end_including_later_cash',
                  'turnover': 'sum(notional / previous_equity / 2) * 252 / holding_window_sessions',
                  'initial_cash_period': 'reported_separately', 'admission_thresholds_changed': False},
              'conclusions': {name: value['primary']['conclusion'] for name, value in assessments.items()}}
    coverage_path = run/'model_signal_coverage.parquet'
    coverage = pl.read_parquet(coverage_path) if coverage_path.is_file() else None
    output.mkdir(parents=True, exist_ok=resume)
    (output/'model.toml').write_bytes(model_bytes)
    (output/'measurement.toml').write_bytes(measurement_bytes)
    (output/'stress_windows.toml').write_bytes(window_bytes)
    if constraint_bytes is not None:
        (output/'constraints_config.toml').write_bytes(constraint_bytes)
        result['constraints_config'] = str(constraint_path)
    pl.from_dicts(report_rows, infer_schema_length=None).write_parquet(output/'cost_metrics.parquet')
    pl.from_dicts(burden_rows, infer_schema_length=None).write_csv(output/'execution_burden.csv')
    comparison_frame = (pl.from_dicts(comparisons, infer_schema_length=None) if comparisons else
        pl.DataFrame(schema={'variant': pl.String, 'cost_multiplier': pl.Float64, 'benchmark': pl.String,
            'start': pl.Date, 'end': pl.Date, 'benchmark_cagr': pl.Float64, 'strategy_cagr': pl.Float64,
            'net_cagr_excess': pl.Float64, 'benchmark_total_return': pl.Float64, 'sessions': pl.Int64}))
    comparison_frame.write_parquet(output/'benchmark_comparisons.parquet')
    if coverage is not None:
        coverage.write_parquet(output/'model_signal_coverage.parquet')
    for method, assessment in assessments.items():
        folder = output/method
        folder.mkdir(exist_ok=resume)
        method_rows = [row for row in report_rows if row['variant'].startswith(f'{method}_top')]
        rendered = render_model_report(method, rows=method_rows, assessment=assessment, model=model,
                                       coverage=coverage.to_dicts() if coverage is not None else None)
        rendered += render_burden([row for row in burden_rows if row['variant'].startswith(f'{method}_top')])
        from quant.reporting.period_metrics import period_metrics, write_period_reports
        from quant.reporting.strategy_description import describe
        description = describe(output/'model.toml', method)
        rendered += '\n策略简述：'+description+'\n\n年度 / 月度明细（1x成本）：\n\n'
        for row in method_rows:
            variant, multiplier = row['variant'], row['cost_multiplier']
            if multiplier != 1.:
                continue
            relative = f"periods/{variant}_cost_{multiplier:g}"
            periods = period_metrics(navs[variant, multiplier], baselines)
            write_period_reports(folder/relative, periods, description)
            rendered += f'- [{variant} · {multiplier:g}×]({relative}/report.md)\n'

        if constraint_bytes is not None:
            scope = tomllib.loads(constraint_bytes.decode('utf-8')).get('strategy_names', [])
            rendered += f'\n本次独立组合约束仅应用于{scope}；其余场景保持原规则。配置见上级目录constraints_config.toml。\n'
        (folder/'report.md').write_text(rendered, encoding='utf-8')
        (folder/'assessment.json').write_text(json.dumps(assessment, indent=2, default=str), encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    from quant.reporting.experiment_registry import register_run
    register_run(output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--measurement-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--resume', action='store_true', help='Rebuild an interrupted report with unchanged inputs')
    args = parser.parse_args()
    print(json.dumps(report_models(run=args.run, measurement_config=args.measurement_config,
                                   output=args.output, data_root=args.data_root, resume=args.resume)['conclusions']))


if __name__ == '__main__':
    main()
