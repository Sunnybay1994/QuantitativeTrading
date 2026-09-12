"""One command from causal annual factor screens to model reports."""
import argparse
import json
import shutil
import tomllib
from pathlib import Path

from quant.reporting.multifactor_models import report_models
from quant.research.model_training_costs import run_cost_prefixes
from quant.research.model_training_prefix import run_prefixes
from quant.research.model_training_selection import run_selection
from quant.research.run_multifactor_predictions import run_predictions
from quant.research.run_multifactor_replay import run_model_replay


def run_pipeline(*, config: Path, output: Path, data_root: Path, measurement_config: Path,
                 correlations_from: Path | None = None, resume_from: Path | None = None) -> dict:
    model_bytes = config.read_bytes()
    model = tomllib.loads(model_bytes.decode('utf-8'))
    measurement_bytes = measurement_config.read_bytes()
    measurement = tomllib.loads(measurement_bytes.decode('utf-8'))
    return_benchmarks = 'benchmarks' in measurement
    research = model['research']
    benchmarks = Path(research['stock_benchmarks'])
    if resume_from is not None and (resume_from/'model.toml').read_bytes() != model_bytes:
        raise ValueError('Resume requires the same frozen model configuration')
    if (resume_from is not None and correlations_from is None
            and (resume_from/'selection'/'annual_correlations.parquet').is_file()):
        correlations_from = resume_from/'selection'
    output.mkdir(parents=True, exist_ok=False)
    (output/'model.toml').write_bytes(model_bytes)
    (output/'measurement.toml').write_bytes(measurement_bytes)

    def reuse(stage: str, files: tuple[str, ...]) -> dict | None:
        if resume_from is None:
            return None
        previous = resume_from/stage
        if not all((previous/name).is_file() for name in ('summary.json', *files)):
            return None
        if (previous/'model.toml').read_bytes() != model_bytes:
            raise ValueError(f'Resume {stage} has a different model configuration')
        result = json.loads((previous/'summary.json').read_text(encoding='utf-8'))
        shutil.copytree(previous, output/stage)
        print(f'Reusing completed {stage}', flush=True)
        return result

    print('Preparing annual training statistics', flush=True)
    statistics_reused = reuse('statistics', ('annual_statistical_screen.parquet', 'model.toml', 'battery.toml'))
    if statistics_reused is None:
        run_prefixes(config=config, output=output/'statistics')
    prior_complete = False
    if resume_from is not None and statistics_reused is not None:
        saved_selection = resume_from/'selection'/'summary.json'
        if saved_selection.is_file():
            previous = json.loads(saved_selection.read_text(encoding='utf-8'))
            prior_complete = bool(previous['annual_selection']) and all(
                row['selection_complete'] for row in previous['annual_selection'])
            if return_benchmarks:
                prior_measurement = resume_from/'costs'/'return_benchmarks.toml'
                prior_complete = (prior_complete and prior_measurement.is_file()
                                  and prior_measurement.read_bytes() == measurement_bytes)
    print('Adding completed cost histories', flush=True)
    costs = reuse('costs', ('annual_cost_screen.parquet', 'model.toml', 'battery.toml')) if prior_complete else None
    if costs is None:
        costs = run_cost_prefixes(prefix=output/'statistics', output=output/'costs',
            cost_runs=[Path(path) for path in research.get('cost_runs', [])],
            cost_root=Path(research['cost_root']), benchmarks=benchmarks, data_root=data_root,
            return_benchmark_config=output/'measurement.toml' if return_benchmarks else None)
        prior_complete = False
    print('Selecting factors using historical correlations', flush=True)
    selection = reuse('selection', ('annual_selection.parquet', 'model.toml', 'battery.toml')) if prior_complete else None
    if selection is None:
        selection = run_selection(costs=output/'costs', output=output/'selection',
                                  correlations_from=correlations_from)
        prior_complete = False
    incomplete = [row for row in selection['annual_selection'] if not row['selection_complete']]
    result = {'model_results_ready': False, 'completed_cost_factors': costs['complete_cost_factors'],
              'annual_selection': selection['annual_selection'], 'conclusions': None}
    if not incomplete:
        print('Training the three fixed models', flush=True)
        predictions = reuse('predictions', ('monthly_predictions.parquet', 'model.toml', 'battery.toml')) if prior_complete else None
        if predictions is None:
            run_predictions(selection=output/'selection', output=output/'predictions')
        print('Replaying the full account calendar', flush=True)
        replay = reuse('replay', ('model.toml', 'battery.toml')) if predictions is not None else None
        if replay is None:
            run_model_replay(predictions=output/'predictions', benchmarks=benchmarks,
                             output=output/'replay', data_root=data_root)
        print('Writing model reports', flush=True)
        reports = report_models(run=output/'replay', measurement_config=output/'measurement.toml',
                                output=output/'reports', data_root=data_root)
        result.update(model_results_ready=True, conclusions=reports['conclusions'])
    lines = ['# 多因子流水线结果', '',
        f"已完成成本的因子数：{costs['complete_cost_factors']}。模型结果齐全：{result['model_results_ready']}。", '',
        '|年度|选择完整|待补因子|已确定前缀|', '|---|---|---:|---|']
    for row in selection['annual_selection']:
        lines.append(f"|{row['test_year']}|{row['selection_complete']}|{row['unresolved_factors']}|"
                     f"{', '.join(row['confirmed_selected_prefix']) or '空'}|")
    lines += ['', ('下一步：依据reports目录中三个模型的结论执行模拟盘决策。' if not incomplete else
        '下一步：继续既有成本批处理，证据补齐后以新输出目录和--resume-from本目录继续；保留年度筛选并复用完成步骤。'), '']
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output/'report.md').write_text('\n'.join(lines), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--measurement-config', type=Path, required=True)
    parser.add_argument('--correlations-from', type=Path, help='Reuse matching annual historical comparisons')
    parser.add_argument('--resume-from', type=Path, help='Reuse completed stages in a new output directory')
    args = parser.parse_args()
    print(json.dumps(run_pipeline(config=args.config, output=args.output, data_root=args.data_root,
                                  measurement_config=args.measurement_config,
                                  correlations_from=args.correlations_from, resume_from=args.resume_from)))


if __name__ == '__main__':
    main()
