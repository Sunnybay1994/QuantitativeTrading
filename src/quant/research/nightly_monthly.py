"""Calendar-triggered, resumable monthly causal models and two constructions."""
import datetime as dt
import json
import shutil
import time
import tomllib
from collections.abc import Callable
from pathlib import Path

import polars as pl

from quant.research.follow_factor_models import _bind_template


def due_period(settings: dict, day: dt.date) -> str | None:
    first = dt.date.fromisoformat(settings['monthly_first_period']+'-01')
    month = day.replace(day=1)
    if month < first:
        return None
    saturday = month+dt.timedelta(days=(5-month.weekday()) % 7)
    return month.strftime('%Y-%m') if day >= saturday else None


def pending_month(settings: dict, run: Path, *, day: dt.date | None = None) -> str | None:
    """Cheap scheduler hint: an eligible missing/unfinished month takes priority."""
    if 'monthly_first_period' not in settings:
        return None
    day = day or dt.date.fromisoformat(settings.get('scheduler_day', run.name))
    root = Path(settings['output_root'])/'monthly'
    # Finish an earlier interrupted month before opening a newer one.
    pending = sorted(p for p in root.glob('????-??') if p.is_dir()
                     and p.name <= day.strftime('%Y-%m') and (p/'request.json').exists()
                     and not (p/'summary.json').exists())
    if pending:
        return pending[0].name
    candidate = dt.date.fromisoformat(settings['monthly_first_period']+'-01')
    while candidate <= day.replace(day=1):
        key = candidate.strftime('%Y-%m')
        saturday = candidate+dt.timedelta(days=(5-candidate.weekday()) % 7)
        if day >= saturday and not (root/key/'summary.json').exists():
            return key
        candidate = (candidate.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
    return None


def monthly_models(settings: dict, run: Path) -> dict:
    day = dt.date.fromisoformat(settings.get('scheduler_day', run.name))
    period = pending_month(settings, run)
    root = Path(settings['output_root'])/'monthly'
    if period is None:
        current = root/day.strftime('%Y-%m')/'summary.json'
        if current.exists():
            return json.loads(current.read_text(encoding='utf-8'))
        return {'skipped': True, 'reason': 'No eligible unfinished monthly model run',
                'monthly_first_period': settings['monthly_first_period']}
    output = root/period
    if (output/'summary.json').is_file():
        return json.loads((output/'summary.json').read_text(encoding='utf-8'))
    cutoff = dt.date.fromisoformat(period+'-01')-dt.timedelta(days=1)
    # A resumed September batch must not train October with its August cutoff.
    # _freeze retains any already published monthly request and inputs.
    from quant.data.refresh import latest_session
    as_of = latest_session(data_root=Path(settings['data_root']), through=cutoff,
                           refresh_calendar=False)
    return _run_month({**settings, 'as_of': as_of}, output)


def run_monthly(settings: dict, run: Path) -> dict:
    """Entry consumed by nightly_steps; deployment month intentionally skips."""
    return monthly_models(settings, run)


def _run_month(settings: dict, output: Path) -> dict:
    frozen = _freeze(settings, output)
    as_of = dt.date.fromisoformat(frozen['as_of'])
    data_root = Path(frozen['data_root'])
    from quant.data.nightly_genetic_inputs import require_execution_coverage
    from quant.factors.compute import run as compute
    from quant.research.run_factor_pipeline import run_pipeline as battery
    require_execution_coverage(data_root, frozen['execution_snapshot'], as_of)
    # Idempotent publication only computes missing factor/year panels.
    compute(data_root=data_root, refresh_config=output/'refresh.toml', library=output/'library',
        selected='all', start=dt.date.fromisoformat(frozen['history_start']), end=as_of,
        artifact_root=output/'compute')
    evaluation = output/'evaluation'
    result = battery(config=output/'battery.toml', library=output/'library', as_of=as_of,
        output=evaluation, data_root=data_root, execution_snapshot=frozen['execution_snapshot'],
        workers=frozen['workers'], resume=(evaluation/'pipeline_config.json').exists(),
        return_benchmark_config=output/'return_benchmarks.toml')
    if result['cost_failures'] or result['pending_external_runs']:
        raise ValueError('Monthly full-family costs incomplete; resume this same month after battery recovery')
    from quant.reporting.experiment_registry import register_run
    register_run(evaluation)
    models_enabled=settings.get('compute_allocation',{}).get('monthly_three_models',True)
    if models_enabled:
        _predict(output, data_root)
    reports = {}
    for method in (('equal_z', 'positive_mean_ic', 'lightgbm') if models_enabled else ()):
        reports[method] = _constructions(output, method, data_root)
    from quant.research.q10_plus_admitted import DEFAULT_CONFIG, run_for_month
    reports['q10_plus_admitted'] = run_for_month(
        month_output=output, data_root=data_root, config=DEFAULT_CONFIG)
    result = {'skipped': False, 'period': output.name, 'completed': True,
        'as_of': str(as_of),
        'output': str(output), 'methods': reports,
        'disabled_methods':[] if models_enabled else ['equal_z','positive_mean_ic','lightgbm'],
        'reference_statistics': str(evaluation/'statistics'),
        'reference_scorecard': result['scorecard_path'],
        'selection_basis': 'entire_frozen_family_annual_known_outcomes_and_prefix_costs',
        'evidence': 'retrospective_adaptive_family_not_new_holdout'}
    lines = [f'# 月度模型 {output.name}', '',
        ('整库候选按每次年度拟合前已知结果重新准入；三个权重模型比较0.5预算与R4约束；另含 Q10+准入因子增量模型。' if models_enabled else
         'C1已关闭equal_z、positive_mean_ic、lightgbm三类月度模型；保留同截止日准入控制与已注册Q10增量回放。关闭不是模型检验通过。'), '',
        '|模型|0.5预算结论|R4结论|报告|', '|---|---|---|---|']
    for method, item in reports.items():
        constrained = item['conclusions'].get('constrained', 'n/a')
        lines.append(f"|{method}|{item['conclusions']['budgeted']}|{constrained}|"
                     f"[{method}]({method}/report.md)|")
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    _dump(output/'summary.json', result)
    return result


def _dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, default=str, ensure_ascii=False), encoding='utf-8')


def _freeze(settings: dict, output: Path) -> dict:
    """Snapshot candidate definitions and configuration before inspecting results."""
    marker = output/'frozen_settings.json'
    if marker.exists():
        return json.loads(marker.read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    files = {'model_template.toml': 'model_config', 'constraints.toml': 'constrained_config',
        'measurement.toml': 'measurement_config', 'return_benchmarks.toml': 'return_benchmark_config',
        'battery.toml': 'battery_config', 'refresh.toml': 'refresh_config'}
    request = output/'request.json'
    if not request.exists():
        from quant.factors.library import load_library
        definitions = {d.id: d for d in load_library(Path(settings['library']))}
        # Formal library includes N4-admitted auto entries. Today's full-sample
        # scorecard cannot remove original factors before causal annual screens.
        library = output/'library'
        library.mkdir(exist_ok=True)
        for name, definition in sorted(definitions.items()):
            values = {key: getattr(definition, key) for key in ('id', 'expr', 'family', 'direction', 'source_ref')}
            (library/f'{name}.toml').write_text(''.join(f'{k} = {json.dumps(v, ensure_ascii=False)}\n'
                for k, v in values.items()), encoding='utf-8')
        saved = {**settings, 'candidate_count': len(definitions)}
        for name, key in files.items():
            target = output/('source_'+name)
            shutil.copyfile(settings[key], target)
            saved[key] = str(target.resolve())
        model = tomllib.loads(Path(saved['model_config']).read_text(encoding='utf-8'))
        shutil.copyfile(model['admission']['stress_windows_config'], output/'stress_windows.toml')
        shutil.copyfile('configs/data/share_exchanges_20260912.toml', output/'share_exchanges.toml')
        _dump(request, saved)
    settings = json.loads(request.read_text(encoding='utf-8'))
    as_of = dt.date.fromisoformat(settings['as_of'])
    from quant.data.nightly_month_inputs import ensure_nightly_month_inputs
    settings = ensure_nightly_month_inputs(settings=settings, as_of=as_of, output=output/'inputs')
    for name, key in files.items():
        shutil.copyfile(settings[key], output/name)
    model = tomllib.loads((output/'model_template.toml').read_text(encoding='utf-8'))
    if model['execution']['auto_trade'] is not False:
        raise ValueError('Monthly models cannot enable live trading')
    constraints = tomllib.loads((output/'constraints.toml').read_text(encoding='utf-8'))
    if constraints['policy']['top_k'] != model['portfolio']['primary_top_k']:
        raise ValueError('Monthly model and frozen R4 target counts differ')
    if model['walk_forward']['test_start'] > as_of:
        raise ValueError('Monthly data ends before the registered test start')
    config = _bind_template((output/'model_template.toml').read_text(encoding='utf-8'), {
        'research': {'id': f'nightly-monthly-{output.name}',
            'statistics_source': str((output/'evaluation/statistics').resolve()),
            'battery_config': str((output/'battery.toml').resolve()),
            'cost_root': str((output/'evaluation/costs').resolve()), 'cost_runs': [],
            'stock_benchmarks': str((output/'evaluation/benchmarks').resolve()),
            'historical_evidence': 'retrospective_adaptive_family_not_an_unseen_holdout'},
        'walk_forward': {'test_end': as_of},
        'admission': {'stress_windows_config': str((output/'stress_windows.toml').resolve())},
        'models': {'methods': ['equal_z', 'positive_mean_ic', 'lightgbm']}})
    (output/'model.toml').write_text(config, encoding='utf-8')
    frozen = {**settings, 'as_of': str(as_of)}
    _dump(marker, frozen)
    return json.loads(marker.read_text(encoding='utf-8'))


def _stage(folder: Path, action: Callable[[], dict], required: tuple[str, ...]) -> dict:
    if all((folder/name).is_file() for name in ('summary.json', *required)):
        return json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    if folder.exists():
        # Preserve only the interrupted stage; complete earlier stages stay put.
        parent = folder.parent.resolve()
        old = folder.with_name(folder.name+f'_partial_{time.time_ns()}')
        if not folder.resolve().is_relative_to(parent) or not old.resolve().is_relative_to(parent):
            raise ValueError('Partial stage is outside the monthly output')
        folder.rename(old)
    return action()


def _predict(output: Path, data_root: Path) -> None:
    from quant.research.model_training_prefix import run_prefixes
    from quant.research.model_training_costs import run_cost_prefixes
    from quant.research.model_training_selection import run_selection
    from quant.research.run_multifactor_predictions import run_predictions
    prefix, costs, selection = output/'prefix', output/'prefix_costs', output/'selection'
    _stage(prefix, lambda: run_prefixes(config=output/'model.toml', output=prefix),
           ('annual_statistical_screen.parquet',))
    completed = json.loads((output/'evaluation/costs/batch_summary.json').read_text(encoding='utf-8'))
    from quant.research.monthly_prefix_costs import prepare_costs, refresh_cached_stages
    cost_runs = prepare_costs(output, data_root, completed['completed_runs'])
    empty_root = output/'additional_costs'
    empty_root.mkdir(exist_ok=True)
    sources = {**completed['completed_runs'], **{
        path.parent.name: str(path.parent) for path in empty_root.glob('*/summary.json')}}
    previous = refresh_cached_stages(output, sources)
    _stage(costs, lambda: run_cost_prefixes(prefix=prefix, output=costs, cost_runs=cost_runs,
        cost_root=empty_root, benchmarks=output/'evaluation/benchmarks', data_root=data_root,
        return_benchmark_config=output/'return_benchmarks.toml',
        previous_costs=previous.get('prefix_costs')), ('annual_cost_screen.parquet',))
    result = _stage(selection, lambda: run_selection(costs=costs, output=selection,
        correlations_from=previous.get('selection')), ('annual_selection.parquet',))
    if any(not row['selection_complete'] for row in result['annual_selection']):
        raise ValueError('Annual causal selection is incomplete; no monthly model can be reported ready')
    _stage(output/'predictions', lambda: run_predictions(selection=selection, output=output/'predictions'),
           ('monthly_predictions.parquet',))


def construction_dispatch(transform: Callable, name: str) -> Callable:
    """Apply R4 only to its named plan; the original budget is already applied upstream."""
    def dispatch(batch, state):
        if batch['strategy'][0] == name+'_r4':
            return transform(batch, state)
        if batch['strategy'][0] != name:
            raise ValueError('Unknown monthly construction strategy')
        return batch, {'feasible': True, 'applied': False}
    return dispatch


def _constructions(output: Path, method: str, data_root: Path) -> dict:
    from quant.backtest.share_exchanges import validate_exchanges
    from quant.data.factor_panels import available_sessions
    from quant.data.equal_weight_index import load_return_benchmarks
    from quant.research.run_multifactor_replay import model_target_plans
    from quant.research.run_constrained_portfolio import prepare_constrained_hook, verify_execution_caps
    from quant.research.factor_battery_costs import run_cost_plans
    from quant.research.factor_battery_cost_report import collect_cost_report, load_cost_history
    from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
    from quant.reporting.multifactor_assessment import assess_model
    from quant.reporting.experiment_registry import register_run
    folder = output/method
    if (folder/'monthly_result.json').is_file():
        return json.loads((folder/'monthly_result.json').read_text(encoding='utf-8'))
    predictions = output/'predictions'
    model = tomllib.loads((predictions/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((predictions/'battery.toml').read_text(encoding='utf-8'))
    policy = tomllib.loads((output/'constraints.toml').read_text(encoding='utf-8'))['policy']
    if policy['auto_trade'] is not False:
        raise ValueError('Monthly constrained construction cannot enable live trading')
    end = model['walk_forward']['test_end']
    sessions = available_sessions(data_root, end+dt.timedelta(days=40))
    scores = pl.read_parquet(predictions/'monthly_predictions.parquet')
    name, targets = model_target_plans(scores, model=model, sessions=sessions)[
        f"{method}_top{model['portfolio']['primary_top_k']}"]
    if targets.height:
        transform, extra, markets = prepare_constrained_hook(scores=scores, targets=targets,
            statistics=output/'evaluation/statistics', policy=policy, score_column=method,
            minimum_signal_stocks=model['models']['minimum_signal_stocks'])
    else:
        def transform(batch, state):
            raise ValueError('Unexpected signal for a cash-only monthly model')
        extra = pl.DataFrame(schema={'execution_date': pl.Date, 'symbol': pl.String})
        markets = pl.DataFrame()
    folder.mkdir(exist_ok=True)
    for file in ('model.toml', 'battery.toml'):
        if not (folder/file).exists():
            shutil.copyfile(predictions/file, folder/file)
    if not (folder/'config.toml').exists():
        (folder/'config.toml').write_text(f'[research]\nid = "nightly-{output.name}-{method}"\n', encoding='utf-8')
    settings['target_constraints_config'] = (output/'constraints.toml').read_text(encoding='utf-8')
    settings['share_exchanges'] = validate_exchanges(tomllib.loads(
        (output/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges'])
    constrained = targets.with_columns(pl.lit(name+'_r4').alias('strategy'))

    snapshot = json.loads((output/'evaluation/benchmarks/summary.json').read_text(encoding='utf-8'))['execution_snapshot']
    run_cost_plans(settings=settings, plans={'budgeted': (name, targets), 'constrained': (name+'_r4', constrained)},
        sessions=sessions, output=folder, data_root=data_root, execution_snapshot=snapshot,
        factor=f'nightly-{output.name}-{method}', start=model['walk_forward']['test_start'],
        turnover_budgets={'budgeted': .5}, resume=(folder/'replay_config.json').exists(),
        target_constraints=construction_dispatch(transform, name), constraint_execution_symbols=extra)
    markets.write_parquet(folder/'signal_controls.parquet') if markets.width else None
    execution = verify_execution_caps(folder, sessions)
    report = collect_cost_report(run=folder, benchmarks=output/'evaluation/benchmarks', data_root=data_root,
        return_benchmark_config=output/'return_benchmarks.toml')
    baselines = load_return_benchmarks(config=output/'return_benchmarks.toml', data_root=data_root,
        start=model['walk_forward']['test_start'], end=end)
    baselines = {('510300_total_return_reference' if k == '510300' else k): v for k, v in baselines.items()}
    model['admission']['benchmarks'] = list(baselines)
    windows = tomllib.loads(Path(model['admission']['stress_windows_config']).read_text(encoding='utf-8'))[
        'cycle_validation']['stress_windows']
    assessments = {}
    for variant in ('budgeted', 'constrained'):
        rows = {r['cost_multiplier']: r for r in report['rows'] if r['variant'] == variant}
        for multiplier, row in rows.items():
            nav, trades = load_cost_history(folder, variant, multiplier, end)
            if nav.filter(pl.col('market_value') > 0).height:
                turnover = calendar_turnover(nav, trades)
                row['legacy_252_turnover'] = row['annualized_one_way_turnover']
                row['annualized_one_way_turnover'] = turnover['median']
                row['maximum_calendar_turnover'] = turnover['maximum']
        nav, _ = load_cost_history(folder, variant, 1., end)
        assessment = assess_model(nav=nav, one=rows[1.], two=rows[2.], benchmarks=baselines, model=model, windows=windows)
        excess = [r['net_cagr_excess'] for r in report['benchmark_comparisons']
                  if r['variant'] == variant and r['cost_multiplier'] == 2. and r['net_cagr_excess'] is not None]
        if excess:
            assessment['double_cost_excess'] = min(excess)
            assessment['checks']['turnover'] = turnover_passes(rows[1.]['annualized_one_way_turnover'], min(excess))
        if variant == 'constrained':
            diagnostics = [r for p in (folder/variant).glob('cost_*/*/constraints.json')
                           for r in json.loads(p.read_text(encoding='utf-8'))]
            assessment['checks']['signal_constraints'] = bool(diagnostics) and all(
                r.get('constraints_satisfied', False) for r in diagnostics)
        assessment['conclusion'] = 'PAPER_CANDIDATE' if all(assessment['checks'].values()) else 'REJECTED'
        assessments[variant] = assessment
    report.update(assessments=assessments, execution_caps=execution)
    _dump(folder/'assessment.json', report)
    lines = [f'# {output.name} {method}', '', '|构建|成本|持股期年化|Sharpe|最大回撤|日历换手中位数|最大值|结论|',
        '|---|---:|---:|---:|---:|---:|---:|---|']
    def fmt(value, pattern):
        return format(value, pattern) if value is not None else 'NA'
    for row in report['rows']:
        lines.append(f"|{row['variant']}|{row['cost_multiplier']}|{fmt(row['cagr'], '.2%')}|"
            f"{fmt(row['sharpe'], '.3f')}|{fmt(row['max_drawdown'], '.2%')}|"
            f"{fmt(row['annualized_one_way_turnover'], '.3f')}|{fmt(row.get('maximum_calendar_turnover'), '.3f')}|"
            f"{assessments[row['variant']]['conclusion']}|")
    lines += ['', '关键限制：新候选采用回顾性年度已知前缀；实际前向表现由模拟盘记录。', '']
    (folder/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    register_run(folder)
    result = {'report': str(folder/'report.md'), 'conclusions': {v: a['conclusion'] for v, a in assessments.items()}}
    _dump(folder/'monthly_result.json', result)
    return result
