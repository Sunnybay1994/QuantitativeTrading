"""Run the registered factor evaluation pipeline and write its final scorecard."""
import argparse
import datetime as dt
import json
import math
import tomllib
import uuid
from pathlib import Path

import polars as pl

from quant.factors.library import load_library
from quant.research.factor_battery_batch import run_statistics
from quant.research.factor_battery_benchmarks import run_benchmarks
from quant.research.factor_battery_cost_batch import run_cost_batch
from quant.research.factor_battery_redundancy import run_redundancy
from quant.research.factor_battery_scorecard import run_scorecard
from quant.research.factor_battery_screen import run_screen


def _statistical_cost_plan(*, statistics: Path, screen: Path, library: Path) -> tuple[list[str], list[str]]:
    """Skip work only after a complete, non-null registered-family screen."""
    config = (statistics/'battery.toml').read_bytes()
    if config != (screen/'battery.toml').read_bytes():
        raise ValueError('Statistical cost gate requires identical statistics and screen settings')
    settings = tomllib.loads(config.decode('utf-8'))
    variants = settings.get('variants', [])
    if (settings.get('run', {}).get('selected') != 'all' or not variants
            or any(not isinstance(variant, str) or not variant for variant in variants)
            or len(set(variants)) != len(variants)):
        raise ValueError('Statistical cost gate requires the complete registered variant family')
    factors = [definition.id for definition in load_library(library, 'all')]
    expected = {(factor, variant) for factor in factors for variant in variants}
    tables = [pl.read_parquet(statistics/'statistics.parquet'),
              pl.read_parquet(screen/'statistical_screen.parquet')]
    for table in tables:
        if not {'factor', 'variant'}.issubset(table.columns):
            raise ValueError('Statistical cost gate requires factor/variant columns')
        keys = table.select('factor', 'variant').rows()
        if not expected or len(keys) != len(set(keys)) or set(keys) != expected:
            raise ValueError('Statistical cost gate requires the complete unique factor/variant family')
    table = tables[1]
    if ('statistical_pass' not in table.columns or table.schema['statistical_pass'] != pl.Boolean
            or table['statistical_pass'].null_count()):
        raise ValueError('Statistical cost gate requires non-null Boolean statistical_pass for every version')
    statistics_summary = json.loads((statistics/'summary.json').read_text(encoding='utf-8'))
    screen_summary = json.loads((screen/'summary.json').read_text(encoding='utf-8'))
    if (statistics_summary.get('factors') != len(factors)
            or statistics_summary.get('variant_rows') != len(expected)
            or screen_summary.get('factors') != len(factors)
            or screen_summary.get('tests') != len(expected)
            or screen_summary.get('statistical_pass_rows') != table['statistical_pass'].sum()):
        raise ValueError('Statistical cost gate requires consistent completed statistics and screen summaries')
    passing = set(table.filter(pl.col('statistical_pass'))['factor'])
    return sorted(passing), sorted(set(factors) - passing)


def run_pipeline(*, config: Path, library: Path, as_of: dt.date, output: Path,
                 data_root: Path, execution_snapshot: str, workers: int,
                 existing_runs: list[Path] | None = None, resume: bool = False,
                 return_benchmark_config: Path | None = None) -> dict:
    """Use a new directory or explicitly resume the same frozen inputs.

    The factor panels and dated execution inputs must already be published.
    Stages run sequentially, with worker parallelism inside the heavy stages.
    Existing cost runs are validated by the cost batch against the current inputs.
    """
    if workers < 1:
        raise ValueError('Workers must be positive')
    config_text = config.read_text(encoding='utf-8')
    refresh = tomllib.loads(config_text).get('data', {}).get('refresh_config')
    configuration = {'battery': config_text, 'as_of': str(as_of),
        'library': {path.relative_to(library).as_posix(): path.read_text(encoding='utf-8')
                    for path in sorted([*library.glob('*.toml'), *(library/'auto').rglob('*.toml')])},
        'data_root': str(data_root.resolve()), 'execution_snapshot': execution_snapshot,
        'refresh_config': Path(refresh).read_text(encoding='utf-8') if refresh else None,
        'existing_runs': sorted(str(path.resolve()) for path in existing_runs or [])}
    saved_config = output/'pipeline_config.json'
    # Existing frozen pipelines retain their original execution mode on resume.
    saved = json.loads(saved_config.read_text(encoding='utf-8')) if resume and saved_config.is_file() else None
    deduplicate = saved.get('cost_deduplication', False) if saved is not None else True
    reuse_benchmarks = saved.get('benchmark_reuse', False) if saved is not None else True
    cost_statistical_gate = saved.get('cost_statistical_gate', False) if saved is not None else not bool(existing_runs)
    if type(cost_statistical_gate) is not bool:
        raise ValueError('cost_statistical_gate must be Boolean')
    if saved is None or 'cost_statistical_gate' in saved:
        configuration['cost_statistical_gate'] = cost_statistical_gate
    if reuse_benchmarks:
        configuration['benchmark_reuse'] = True
    if deduplicate:
        configuration['cost_deduplication'] = True
    return_text = return_benchmark_config.read_text(encoding='utf-8') if return_benchmark_config is not None else None
    if return_text is not None:
        configuration['return_benchmarks'] = return_text
        tomllib.loads(return_text)['benchmarks']
    if resume:
        if saved != configuration:
            raise ValueError('Resume requires unchanged pipeline settings, library and input locations')
        if cost_statistical_gate and existing_runs:
            raise ValueError('Statistical cost gating cannot discard explicit existing cost runs')
        if (output/'summary.json').is_file():
            previous = json.loads((output/'summary.json').read_text(encoding='utf-8'))
            if not previous['cost_failures'] and not previous['pending_external_runs']:
                return previous
    else:
        output.mkdir(parents=True, exist_ok=False)
        saved_config.write_text(json.dumps(configuration, indent=2), encoding='utf-8')
    if return_text is not None:
        return_benchmark_config = output/'return_benchmarks.toml'
        return_benchmark_config.write_text(return_text, encoding='utf-8')

    def stage(folder: Path, action, *, resumable: bool = False, required: tuple[str, ...] = ()):
        if resume and (folder/'summary.json').is_file() and all((folder/name).is_file() for name in required):
            return json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        from quant.research.slice_budget import checkpoint
        checkpoint()
        if folder.exists() and not resumable:
            preserved = folder.with_name(f'{folder.name}_partial_{uuid.uuid4().hex[:8]}')
            if not folder.resolve().is_relative_to(output.resolve()) or not preserved.resolve().is_relative_to(output.resolve()):
                raise ValueError('Partial output must stay inside the pipeline directory')
            folder.rename(preserved)
        return action()

    statistics, screen = output/'statistics', output/'screen'
    benchmarks, redundancy, costs = output/'benchmarks', output/'redundancy', output/'costs'
    print('Computing full-library statistics', flush=True)
    stage(statistics, lambda: run_statistics(data_root=data_root, config=config, library=library, as_of=as_of,
                   output=statistics, selected='all', workers=workers), resumable=True)
    print('Screening the complete multiple-testing family', flush=True)
    stage(screen, lambda: run_screen(statistics=statistics, output=screen, library=library))
    passing, rejected = _statistical_cost_plan(statistics=statistics, screen=screen, library=library) if cost_statistical_gate else ([], [])
    skip_costs = cost_statistical_gate and not passing
    skipped_work = ['factor_cost_replays', 'stock_account_benchmarks', 'historical_correlations'] if skip_costs else []
    if skip_costs:
        print('Complete statistical family rejected; costs remain not evaluated', flush=True)
        batch = {'status': 'skipped_not_evaluated', 'factors': 0, 'completed_runs': {},
                 'failures': {}, 'pending_external_runs': {}, 'statistically_rejected_factors': rejected}
        costs.mkdir(parents=True, exist_ok=True)
        (costs/'batch_summary.json').write_text(json.dumps(batch, indent=2), encoding='utf-8')
    else:
        print('Replaying both stock benchmarks at all cost levels', flush=True)
        benchmark_options = ({'reuse_root': output.parent.parent/'benchmark_cache',
                              'resume': (benchmarks/'replay_config.json').is_file()} if reuse_benchmarks else {})
        stage(benchmarks, lambda: run_benchmarks(statistics=statistics, output=benchmarks, data_root=data_root,
                       execution_snapshot=execution_snapshot, **benchmark_options),
              resumable=reuse_benchmarks and (benchmarks/'replay_config.json').is_file(),
              required=('benchmark_reuse.json',) if reuse_benchmarks else ())
        print('Computing full-library historical correlations', flush=True)
        stage(redundancy, lambda: run_redundancy(statistics=statistics, output=redundancy, library=library,
                                               workers=workers), resumable=True)
        print('Replaying selected factor portfolios at all cost levels', flush=True)
        batch = run_cost_batch(statistics=statistics, screen=screen, output=costs, data_root=data_root,
                              execution_snapshot=execution_snapshot, existing_runs=existing_runs or [], workers=workers,
                              resume=resume, deduplicate=deduplicate, only_statistical_pass=cost_statistical_gate)
    print('Writing scorecard and outstanding cost failures', flush=True)
    scorecard_output = output/'scorecard'
    number = 2
    while scorecard_output.exists():
        scorecard_output = output/f'scorecard_{number:03d}'
        number += 1
    scorecard = run_scorecard(screen=screen, output=scorecard_output,
                             cost_runs=[Path(path) for path in batch['completed_runs'].values()], cost_root=None,
                             benchmarks=None if skip_costs else benchmarks,
                             redundancy=None if skip_costs else redundancy, data_root=data_root,
                             return_benchmark_config=return_benchmark_config)
    result = {'as_of': str(as_of), 'scorecard': scorecard, 'cost_failures': batch['failures'],
              'cost_statistical_gate': cost_statistical_gate,
              'cost_evaluation_status': 'skipped_not_evaluated' if skip_costs else 'evaluated',
              'statistically_rejected_factors': batch.get('statistically_rejected_factors', rejected),
              'skipped_work': skipped_work,
              'reused_factors': batch.get('reused_factors', {}),
              'saved_variant_cost_replays': batch.get('saved_variant_cost_replays', 0),
              'non_executable_rejections': batch.get('non_executable_rejections', {}),
              'pending_external_runs': batch['pending_external_runs'],
              'scorecard_path': str(scorecard_output/'factor_scorecard.parquet')}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    failures = '\n'.join(f'- {factor}: {reason}' for factor, reason in sorted(batch['failures'].items()))
    pending = '\n'.join(f'- {factor}: {path}' for factor, path in sorted(batch['pending_external_runs'].items()))
    (output/'report.md').write_text(
        f"# 因子评估流水线：{as_of}\n\n"
        f"评分表{scorecard['rows']}行，完整成本{scorecard['cost_complete_rows']}行，"
        f"通过准入{scorecard['admitted_rows']}行，待补准入证据{scorecard['admission_unresolved_rows']}行。\n\n"
        f"评分表：`{scorecard_output.name}/factor_scorecard.parquet`。\n\n"
        + f"等价信号复用{len(batch.get('reused_factors', {}))}个因子，节省{batch.get('saved_variant_cost_replays', 0)}组版本×成本回放；独立统计检验保留。\n\n"
        + f"统计未通过且无可执行组合的终态拒绝：{len(batch.get('non_executable_rejections', {}))}项；原因保留于summary.json。\n\n"
        + ('完整统计族全部拒绝；成本账户、股票账户基准和历史相关性未评估，成本指标保持未知。\n' if skip_costs
           else ('成本回放失败明细：\n\n'+failures+'\n' if failures else '成本批处理无失败项。\n'))
        + ('\n外部成本回放尚未完成：\n\n'+pending+'\n' if pending else ''),
        encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/factors/battery.toml'))
    parser.add_argument('--library', type=Path, default=Path('configs/factors/library'))
    parser.add_argument('--as-of', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--execution-snapshot', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--return-benchmark-config', type=Path, help='Explicit dividend/equal-weight references for cost admission')
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--resume', action='store_true', help='Resume the same pipeline after its prior process has stopped')
    parser.add_argument('--existing-run', type=Path, action='append', default=[],
                        help='Reuse or reserve an existing factor cost run; repeat for multiple factors')
    parser.add_argument('--diagnosis-config', type=Path, help='Append DeepSeek diagnosis; defaults to an offline plan')
    parser.add_argument('--assessment', type=Path, action='append', default=[],
                        help='Include a completed model assessment in diagnosis; repeat for each model')
    parser.add_argument('--diagnosis-execute', action='store_true')
    parser.add_argument('--diagnosis-max-requests', type=int, default=0)
    parser.add_argument('--diagnosis-max-usd', type=float, default=0)
    parser.add_argument('--diagnosis-cache', type=Path, default=Path('artifacts/research/p7_deepseek_cache.sqlite'))
    args = parser.parse_args()
    if (args.diagnosis_execute or args.assessment) and args.diagnosis_config is None:
        parser.error('Diagnosis execution and assessments require --diagnosis-config')
    if (args.diagnosis_max_requests < 0 or not math.isfinite(args.diagnosis_max_usd)
            or args.diagnosis_max_usd < 0 or (args.diagnosis_execute and
                (args.diagnosis_max_requests < 1 or args.diagnosis_max_usd <= 0))):
        parser.error('Live diagnosis requires positive finite request and USD caps')
    if args.diagnosis_config:
        from quant.research.score_forecast_text import load_settings
        load_settings(args.diagnosis_config)
    result = run_pipeline(config=args.config, library=args.library, as_of=args.as_of,
                          output=args.output, data_root=args.data_root,
                          execution_snapshot=args.execution_snapshot, workers=args.workers,
                          existing_runs=args.existing_run, resume=args.resume,
                          return_benchmark_config=args.return_benchmark_config)
    if args.diagnosis_config:
        from quant.research.deepseek_diagnostics import run_diagnosis
        diagnosis_output = args.output/'diagnosis'
        number = 2
        while diagnosis_output.exists():
            diagnosis_output = args.output/f'diagnosis_{number:03d}'
            number += 1
        diagnosis = run_diagnosis(inputs=[], scorecard=Path(result['scorecard_path']),
            assessments=args.assessment, config=args.diagnosis_config, output=diagnosis_output,
            cache_path=args.diagnosis_cache, artifact_root=Path('artifacts'), execute=args.diagnosis_execute,
            max_requests=args.diagnosis_max_requests, max_usd=args.diagnosis_max_usd)
        result['diagnosis'] = {'output': str(diagnosis_output), 'result': diagnosis['result'],
            'dry_run': diagnosis['dry_run'], 'deferred_until': diagnosis['deferred_until'],
            'usd_bound_including_retries': diagnosis['usd_bound_including_retries']}
        (args.output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    if (result['cost_failures'] or result['pending_external_runs'] or
            (args.diagnosis_execute and result['diagnosis']['result'] != 'success')):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
