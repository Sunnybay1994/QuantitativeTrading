"""Run one resumable research batch per scheduler invocation, including across reboots."""

import argparse
import datetime as dt
import json
import os
import re
import tomllib
from pathlib import Path

from quant.research import nightly


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def completed(summary: dict) -> bool:
    return all(summary.get('steps', {}).get(step, {}).get('ok')
               for step in ('N1', 'N2', 'N3', 'N4', 'N5'))


def dispatch(config: Path, root: Path, *, now: dt.datetime | None = None,
             slice_hours: float = 2, retry_hours: float = 1,
             max_failures: int = 3) -> dict:
    """Resume oldest unfinished batch; never advance past a repeatedly broken batch.

    The Windows launcher serializes invocations and shared data writers. This entry
    Optional weekly candidate generation obeys its own off-peak and budget gates.
    Completed steps and GP population/RNG checkpoints stay in place.
    """
    if slice_hours <= 0 or retry_hours <= 0 or max_failures < 1:
        raise ValueError('Positive timeboxes and retry limit required')
    supplied_now = now is not None
    now = now or dt.datetime.now()
    root.mkdir(parents=True, exist_ok=True)
    weekly: dict = {'state': 'disabled'}
    weekly_config = tomllib.loads(config.read_text(encoding='utf-8')).get('weekly_candidates_config')
    if weekly_config:
        from quant.research.weekly_factor_candidates import run as weekly_run
        try:
            weekly = weekly_run(Path(weekly_config), execute=True)
        except (OSError, ValueError, RuntimeError) as exc:
            # A text-generation failure must not stop local factor research.
            weekly = {'state': 'needs_attention', 'error': f'{type(exc).__name__}: {exc}'}
    batches = sorted(p for p in root.glob('batch_*') if re.fullmatch(r'batch_\d+', p.name))
    batch = next((p for p in batches if not completed(read(next(p.glob('????-??-??'))/'summary.json'))), None)
    if batch is None:
        index = max((int(p.name.split('_')[1]) for p in batches), default=0)+1
        batch = root/f'batch_{index:06d}'
        staging = root/f'{batch.name}.{now.date().isoformat()}.pending'
        run = staging/now.date().isoformat()
        source = config.read_text(encoding='utf-8')
        base_seed = tomllib.loads(source)['genetic']['seed']
        # Keep the shared monthly output root and all original admission thresholds.
        source, count = re.subn(r'(?m)^(seed\s*=\s*)\d+\s*$',
                                lambda match: f'{match[1]}{base_seed+index}', source)
        if count != 1:
            raise ValueError('Expected exactly one genetic seed in config')
        run.mkdir(parents=True, exist_ok=True)
        from quant.research.nightly_search_recipe import freeze_recipe
        source = freeze_recipe(source, run, batch / now.date().isoformat(), batches)
        temporary = run/'config.tmp'
        temporary.write_text(source, encoding='utf-8')
        temporary.replace(run/'config.toml')
        staging.rename(batch)
        run = batch/now.date().isoformat()
    else:
        run = next(batch.glob('????-??-??'))
    previous = read(batch/'attempt.json')
    status = {'batch': batch.name, 'run': str(run), 'updated_at': now.isoformat(),
              'weekly_candidates': weekly,
              'steps': read(run/'summary.json').get('steps', {}),
              'pid': os.getpid(), 'seed': tomllib.loads((run/'config.toml').read_text(encoding='utf-8'))['genetic']['seed']}
    from quant.research.nightly_monthly import pending_month
    monthly_due = pending_month(tomllib.loads((run/'config.toml').read_text(encoding='utf-8')),
                                run, day=now.date())
    new_month = monthly_due is not None and monthly_due != previous.get('monthly_period')
    if previous.get('consecutive_failures', 0) >= max_failures and not new_month:
        status.update(state='needs_attention', reason='Repeated batch failure; inspect process logs before retry',
                      error=previous.get('error'))
    elif previous.get('retry_after') and now < dt.datetime.fromisoformat(previous['retry_after']) and not new_month:
        status.update(state='cooldown', retry_after=previous['retry_after'], error=previous.get('error'))
    else:
        status['state'] = 'running'
        save(root/'status.json', status)
        try:
            summary = nightly.execute(run/'config.toml', now=now, run_path=run, session_hours=slice_hours)
            errors = {key: row.get('error', 'incomplete') for key, row in summary.get('steps', {}).items()
                      if not row.get('ok')}
            success = completed(summary)
            status['steps'] = summary.get('steps', {})
        except (OSError, RuntimeError, ValueError) as exc:
            errors, success = {'runner': str(exc)}, False
        # Exhausting a slice is normal resumable work, unlike a failed worker.
        primary_errors = [error for error in errors.values() if not error.endswith(' did not complete')]
        resumable = bool(primary_errors) and all(
            bool(re.search(r'Time/disk guard: -?\d+s,', error))
            and float(error.split('Time/disk guard: ')[1].split('s,')[0]) <= 0
            or 'Worker exceeded ' in error or error.startswith('Time slice yielded') for error in primary_errors)
        failures = 0 if success or resumable else previous.get('consecutive_failures', 0)+1
        finished = now if supplied_now else dt.datetime.now()
        attempt = {'monthly_period': monthly_due, 'finished_at': finished.isoformat(), 'consecutive_failures': failures,
                   'error': errors, 'retry_after': (finished+dt.timedelta(hours=retry_hours)).isoformat()
                   if failures else None}
        save(batch/'attempt.json', attempt)
        status.update(state='completed' if success else 'resumable' if resumable else
                      'needs_attention' if failures >= max_failures else 'cooldown',
                      error=errors, retry_after=attempt['retry_after'], updated_at=finished.isoformat())
    save(root/'status.json', status)
    policy = tomllib.loads(config.read_text(encoding='utf-8')).get('research_policy')
    if policy:
        from quant.research.research_feedback import update as update_research_feedback
        try:
            feedback = update_research_feedback(Path(policy))
            status['research_feedback'] = feedback['policy']['output_root']
        except (OSError, ValueError, RuntimeError) as exc:
            status['research_feedback_error'] = f'{type(exc).__name__}: {exc}'
        save(root/'status.json', status)
    if weekly_config:
        from quant.research.weekly_factor_feedback import update
        try:
            update(Path(weekly_config), root)
        except (OSError, ValueError, RuntimeError) as exc:
            status['weekly_feedback_error'] = f'{type(exc).__name__}: {exc}'
            save(root/'status.json', status)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/nightly.toml'))
    parser.add_argument('--output-root', type=Path, default=Path('artifacts/research/continuous'))
    parser.add_argument('--slice-hours', type=float, default=2)
    args = parser.parse_args()
    status = dispatch(args.config, args.output_root, slice_hours=args.slice_hours)
    print(json.dumps(status, ensure_ascii=False))
    if status['state'] == 'needs_attention':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
