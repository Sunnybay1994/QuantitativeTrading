"""Continue the model pipeline as an existing cost batch publishes results."""
import argparse
import json
import time
import tomllib
from pathlib import Path

from quant.research.run_multifactor_pipeline import run_pipeline


def completed_costs(research: dict) -> frozenset[Path]:
    paths = [*Path(research['cost_root']).glob('*/summary.json'),
             *(Path(path)/'summary.json' for path in research.get('cost_runs', []))]
    return frozenset(path.resolve() for path in paths if path.is_file())


def cost_batch_finished(research: dict) -> bool:
    path = Path(research['cost_root'])/'batch_summary.json'
    if not path.is_file():
        return False
    batch = json.loads(path.read_text(encoding='utf-8'))
    return all((Path(folder)/'summary.json').is_file()
               for folder in batch.get('pending_external_runs', {}).values())


def follow(*, config: Path, output: Path, data_root: Path, measurement_config: Path,
           resume_from: Path | None = None,
           interval_seconds: float = 300, max_wait_hours: float = 24) -> dict:
    if interval_seconds < 300 or max_wait_hours <= 0:
        raise ValueError('Check no faster than every five minutes and use a positive waiting limit')
    model = config.read_bytes()
    measurement = measurement_config.read_bytes()
    tomllib.loads(measurement.decode('utf-8'))
    research = tomllib.loads(model.decode('utf-8'))['research']
    output.mkdir(parents=True, exist_ok=True)
    saved_config = output/'model.toml'
    if saved_config.exists() and saved_config.read_bytes() != model:
        raise ValueError('Continue with the same frozen model configuration')
    saved_config.write_bytes(model)
    saved_measurement = output/'measurement.toml'
    if saved_measurement.exists() and saved_measurement.read_bytes() != measurement:
        raise ValueError('Use a new follower directory when changing report measurement')
    saved_measurement.write_bytes(measurement)
    attempts = sorted(output.glob('attempt_[0-9][0-9][0-9][0-9]'))
    if attempts:
        resume_from = attempts[-1]
    index = int(attempts[-1].name.split('_')[1])+1 if attempts else 1
    deadline = time.monotonic()+max_wait_hours*3600
    observed = None
    result = {}
    if (resume_from is not None and (resume_from/'summary.json').is_file()
            and (resume_from/'costs'/'summary.json').is_file()):
        if (resume_from/'model.toml').read_bytes() != model:
            raise ValueError('Continue with the same frozen model configuration')
        prior = json.loads((resume_from/'summary.json').read_text(encoding='utf-8'))
        sources = json.loads((resume_from/'costs'/'summary.json').read_text(encoding='utf-8'))
        if not prior['model_results_ready'] and 'source_runs' in sources:
            result = prior
            observed = frozenset((Path(folder)/'summary.json').resolve()
                                 for folder in sources['source_runs'].values())
    print(f'Following cost results every {interval_seconds:g}s; resume from {resume_from}', flush=True)
    while True:
        if config.read_bytes() != model:
            raise ValueError('Model configuration changed while waiting for costs')
        if measurement_config.read_bytes() != measurement:
            raise ValueError('Report measurement changed while waiting for costs')
        current = completed_costs(research)
        if observed is None or current != observed:
            # Capture before running so results arriving during computation are seen next time.
            observed = current
            attempt = output/f'attempt_{index:04d}'
            result = run_pipeline(config=config, output=attempt, data_root=data_root,
                                  measurement_config=saved_measurement,
                                  resume_from=resume_from)
            resume_from = attempt
            index += 1
            if result['model_results_ready']:
                reason = 'Three model reports are ready'
                break
        # Refresh after computation before deciding whether the batch has no more work.
        if completed_costs(research) == observed and cost_batch_finished(research):
            reason = 'Cost batch finished but annual evidence remains incomplete; inspect cost failures and selection'
            break
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            reason = 'Waiting limit reached; preserve the latest attempt and resume after new cost results'
            break
        time.sleep(min(interval_seconds, remaining))
    result = {**result, 'latest_run': str(resume_from), 'continuation_note': reason}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--measurement-config', type=Path, required=True)
    parser.add_argument('--resume-from', type=Path)
    parser.add_argument('--interval-seconds', type=float, default=300)
    parser.add_argument('--max-wait-hours', type=float, default=24)
    args = parser.parse_args()
    result = follow(config=args.config, output=args.output, data_root=args.data_root,
                    measurement_config=args.measurement_config,
                    resume_from=args.resume_from, interval_seconds=args.interval_seconds,
                    max_wait_hours=args.max_wait_hours)
    print(json.dumps(result))
    if not result['model_results_ready']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
