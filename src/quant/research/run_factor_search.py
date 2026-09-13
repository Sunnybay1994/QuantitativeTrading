"""Run a preregistered finite factor search with resumable existing battery stages."""
import argparse
import json
import re
import time
import tomllib
from pathlib import Path

from quant.factors.compute import run as compute
from quant.factors.search import prepare
from quant.research.factor_battery_batch import run_statistics
from quant.research.factor_battery_benchmarks import run_benchmarks
from quant.research.factor_battery_cost_batch import run_cost_batch
from quant.research.factor_battery_redundancy import run_redundancy
from quant.research.factor_battery_scorecard import run_scorecard
from quant.research.factor_battery_screen import run_screen


def run(*, config: Path, output: Path, data_root: Path = Path('data'), prepare_only: bool = False,
        return_benchmark_config: Path | None = None, model_config: Path | None = None,
        measurement_config: Path | None = None) -> dict:
    if (model_config is None) != (measurement_config is None):
        raise ValueError('Supply model_config and measurement_config together')
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    search, dates = settings['search'], settings['dates']
    if not (dates['start'] < dates['training_end'] < dates['validation_start'] <= dates['validation_end']
            <= dates['panel_end'] < dates['forward_start']):
        raise ValueError('Search dates must preserve training, validation and future separation')
    if search['workers'] < 1 or search['maximum_hours'] <= 0 or not 1 <= search['maximum_cost_attempts'] <= 3:
        raise ValueError('Worker and time budgets must be positive')
    registered = prepare(config=config, library=Path(search['library']), output=output)
    if not registered['registered_count']:
        raise ValueError('No valid, distinct candidate expressions')
    if prepare_only:
        return registered
    frozen_returns = output/'return_benchmarks.toml'
    return_bytes = return_benchmark_config.read_bytes() if return_benchmark_config is not None else None
    if return_bytes is not None:
        tomllib.loads(return_bytes.decode('utf-8'))['benchmarks']
    if ((frozen_returns.exists() and frozen_returns.read_bytes() != return_bytes)
            or (return_bytes is not None and not frozen_returns.exists() and (output/'battery_source.toml').exists())):
        raise ValueError('Changed return benchmarks require a new search run')
    if return_bytes is not None:
        frozen_returns.write_bytes(return_bytes)
        return_benchmark_config = frozen_returns
    started = time.monotonic()
    batch_library = output/'library'
    battery = Path(search['battery_config']).read_bytes()
    source_battery = output/'battery_source.toml'
    if source_battery.is_file() and source_battery.read_bytes() != battery:
        raise ValueError('Changed battery settings require a new search run')
    source_battery.write_bytes(battery)
    frozen_refresh = output/'refresh.toml'
    if not frozen_refresh.is_file():
        frozen_refresh.write_bytes(Path(search['refresh_config']).read_bytes())
    text, replaced = re.subn(r'(?m)^refresh_config = .*$',
        lambda match: f'refresh_config = {json.dumps(str(frozen_refresh.resolve()))}',
        battery.decode('utf-8'), count=1)
    if replaced != 1:
        raise ValueError('Battery must specify one data refresh configuration')
    saved = output/'battery.toml'
    saved.write_text(text, encoding='utf-8')
    validation_battery = output/'validation_battery.toml'
    validation_text, replaced = re.subn(r'(?m)^start = \d{4}-\d{2}-\d{2}$',
        f"start = {dates['validation_start']}", text, count=1)
    if replaced != 1 or tomllib.loads(text)['start'] != dates['start']:
        raise ValueError('Battery start must match the search start')
    validation_battery.write_text(validation_text, encoding='utf-8')
    completed = []

    def stage(name, action, final='summary.json'):
        folder = output/name
        if (folder/final).is_file():
            completed.append(name)
            return json.loads((folder/final).read_text(encoding='utf-8'))
        if time.monotonic()-started >= search['maximum_hours']*3600:
            raise TimeoutError('Time budget reached between stages; rerun the same command to resume')
        if folder.exists() and name in ('screen', 'initial_scorecard', 'benchmarks', 'scorecard'):
            # These short writers require a fresh directory; preserve interrupted output.
            attempt = 1
            while (output/f'{name}_partial_{attempt:03d}').exists():
                attempt += 1
            folder.rename(output/f'{name}_partial_{attempt:03d}')
        print(f'Factor search: {name}', flush=True)
        result = action(folder)
        completed.append(name)
        return result

    try:
        def panels(folder):
            result = compute(data_root=data_root, refresh_config=frozen_refresh,
                library=batch_library, selected='all', start=dates['start'], end=dates['panel_end'],
                artifact_root=folder)
            folder.mkdir(parents=True, exist_ok=True)
            (folder/'summary.json').write_text(json.dumps(result), encoding='utf-8')
            return result
        stage('panels', panels)
        stage('training', lambda folder: run_statistics(data_root=data_root, config=saved, library=batch_library,
            as_of=dates['training_end'], output=folder, workers=search['workers']))
        screen = stage('screen', lambda folder: run_screen(statistics=output/'training', output=folder, library=batch_library))
        # Every candidate is retained in validation, including failed training candidates.
        # Validation is diagnostic only and never changes the frozen training direction or grid.
        stage('validation', lambda folder: run_statistics(data_root=data_root, config=validation_battery,
            library=batch_library, as_of=dates['validation_end'], output=folder, workers=search['workers']))
        stage('initial_scorecard', lambda folder: run_scorecard(screen=output/'screen', output=folder,
            cost_runs=[], cost_root=None, benchmarks=None, redundancy=None, data_root=data_root))
        if screen['statistical_pass_rows'] == 0:
            result = {'message': 'completed', 'attempt_count': registered['attempt_count'],
                      'registered_count': registered['registered_count'], 'completed_stages': completed,
                      'reason': 'All candidates failed the frozen training statistical thresholds',
                      'scope': 'Factor rejection; no model or portfolio conclusion'}
            (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            return result
        stage('redundancy', lambda folder: run_redundancy(statistics=output/'training', output=folder,
            library=batch_library, workers=search['workers']))
        stage('benchmarks', lambda folder: run_benchmarks(statistics=output/'training', output=folder,
            data_root=data_root, execution_snapshot=search['execution_snapshot']))
        cost_root = output/'costs'
        cost_root.mkdir(exist_ok=True)
        completed_costs: dict[str, str] = {}
        costs: dict = {'failures': {}, 'pending_external_runs': {}}
        for number in range(1, search['maximum_cost_attempts']+1):
            folder = cost_root/f'attempt_{number:03d}'
            summary = folder/'batch_summary.json'
            if summary.is_file():
                costs = json.loads(summary.read_text(encoding='utf-8'))
            else:
                if time.monotonic()-started >= search['maximum_hours']*3600:
                    raise TimeoutError('Time budget reached before a cost attempt; rerun to resume')
                # Reuse finished factors even if the previous parent stopped before its summary.
                for path in sorted(cost_root.glob('attempt_*/*/summary.json')):
                    completed_costs[path.parent.name] = str(path.parent)
                costs = run_cost_batch(statistics=output/'training', screen=output/'screen',
                    output=folder, data_root=data_root, execution_snapshot=search['execution_snapshot'],
                    existing_runs=[Path(path) for path in completed_costs.values()], workers=search['workers'],
                    only_statistical_pass=True, resume=True)
            completed_costs.update(costs['completed_runs'])
            if not costs['failures'] and not costs['pending_external_runs']:
                break
        if costs['failures'] or costs['pending_external_runs']:
            raise RuntimeError('Cost retry budget exhausted; see costs/attempt_*/batch_summary.json')
        completed.append('costs')
        scorecard = stage('scorecard', lambda folder: run_scorecard(screen=output/'screen', output=folder,
            cost_runs=[Path(path) for path in completed_costs.values()], cost_root=None, benchmarks=output/'benchmarks',
            redundancy=output/'redundancy', data_root=data_root, return_benchmark_config=return_benchmark_config))
        result = {'message': 'completed', 'attempt_count': registered['attempt_count'],
            'registered_count': registered['registered_count'], 'training_scorecard': scorecard,
            'training_end': str(dates['training_end']), 'validation_end': str(dates['validation_end']),
            'forward_start': str(dates['forward_start']), 'completed_stages': completed,
            'scope': 'Finite factor search; model and portfolio conclusions require their registered replay'}
        if model_config is not None:
            from quant.research.follow_factor_models import follow_factor_models, next_model_output
            assert measurement_config is not None
            result['models'] = follow_factor_models(evaluation=output, model_config=model_config,
                measurement_config=measurement_config, output=next_model_output(output), data_root=data_root)
        (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    except Exception as exc:
        result = {'message': 'incomplete', 'completed_stages': completed,
                  'reason': str(exc), 'attempt_count': registered['attempt_count']}
        (output/'progress.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--return-benchmark-config', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--measurement-config', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output, data_root=args.data_root,
                         prepare_only=args.prepare_only, return_benchmark_config=args.return_benchmark_config,
                         model_config=args.model_config, measurement_config=args.measurement_config)))


if __name__ == '__main__':
    main()
