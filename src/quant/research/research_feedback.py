"""Read completed battery evidence for subsequent, frozen research requests."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import tomllib

import polars as pl


def candidate_diagnostic(row: dict, candidate: dict, inputs: dict) -> dict:
    """Align signed search statistics; full history remains descriptive evidence."""
    train = candidate.get('train')
    direction = candidate.get('direction')
    signed = {key: train.get(key)*direction if train and direction in (-1, 1)
              and isinstance(train.get(key), (int, float)) and math.isfinite(train[key]) else None
              for key in ('mean_ic', 'icir', 'newey_west_t')}
    compatible = (row.get('variant') == 'raw'
                  and candidate.get('fitness_preprocessing') == 'battery_raw_mad3_scale1.4826_v1'
                  and direction in (-1, 1) and direction == row.get('direction'))
    full_ic = row.get('mean_ic')
    delta = (full_ic-signed['mean_ic'] if compatible and signed['mean_ic'] is not None
             and isinstance(full_ic, (int, float)) and math.isfinite(full_ic) else None)
    return {'factor': row['factor'], 'variant': row.get('variant'), 'train': train,
            'search_direction': direction, 'train_direction_adjusted': signed,
            'search_preprocessing': candidate.get('fitness_preprocessing'),
            'training_sample': {key: inputs.get(key) for key in ('sample_symbols', 'sample_months',
                'sample_first_signal', 'sample_last_signal', 'last_label_exit', 'training_end')},
            'full_history': {key: row.get(key) for key in ('months', 'first_valid_month', 'last_valid_month',
                'median_paired_stocks', 'mean_ic', 'icir', 'newey_west_t', 'decay', 'annual_ic',
                'yearly_positive_fraction', 'long_short_sharpe', 'statistical_failures')},
            'same_score_preprocessing': compatible, 'full_minus_training_mean_ic': delta,
            'comparison_note': 'Different date windows and stock samples; difference is not causal attribution or independent validation.',
            'costs': {key: value for key, value in row.items() if key.startswith('cost_')},
            'validation': None, 'validation_note': 'Full-history battery is not independent validation'}


def summarize(rows: list[dict]) -> dict:
    failures = Counter(failure for row in rows for failure in (row.get('statistical_failures') or []))
    missing = [{'factor': row['factor'], 'variant': row.get('variant')}
               for row in rows if row.get('return_benchmarks_complete') is not True]
    return {'variants': len(rows), 'candidates': len({r['factor'] for r in rows}),
            'statistical_pass': sum(r.get('statistical_pass') is True for r in rows),
            'statistical_failure_counts': dict(failures),
            'cost_excess_pass': sum(r.get('cost_excess_pass') is True for r in rows),
            'benchmark_incomplete': missing,
            'benchmark_complete': len(rows)-len(missing)}


def build(config: Path) -> dict:
    policy = tomllib.loads(config.read_text(encoding='utf-8'))
    batches, pending = [], []
    for path in sorted(Path(policy['continuous_root']).glob('batch_*/????-??-??/summary.json')):
        saved = json.loads(path.read_text(encoding='utf-8'))
        steps = saved.get('steps', {})
        scorecard = steps.get('N3', {}).get('result', {}).get('scorecard')
        # A timed-out or partial battery is never counted as a zero-pass batch.
        if not steps.get('N3', {}).get('ok') or not scorecard:
            pending.append({'run': str(path.parent), 'reason': 'Battery not completed'})
            continue
        rows = pl.read_parquet(scorecard).to_dicts()
        families = sorted({r.get('family', 'unknown') for r in rows})
        search_path = path.parent/'N2'/'search.json'
        search = json.loads(search_path.read_text(encoding='utf-8')) if search_path.exists() else {}
        trained = {r.get('factor_id'): r for r in search.get('candidates', [])}
        input_path = path.parent/'N2/input_summary.json'
        inputs = json.loads(input_path.read_text(encoding='utf-8')) if input_path.exists() else {}
        diagnostics = [candidate_diagnostic(row, trained.get(row['factor'], {}), inputs) for row in rows]
        comparable = [row for row in diagnostics if row['full_minus_training_mean_ic'] is not None]
        batches.append({'run': str(path.parent), 'source': scorecard, **summarize(rows),
                        'families': {f: summarize([r for r in rows if r.get('family', 'unknown') == f])
                                     for f in families},
                        'search_alignment': {'comparable_raw_candidates': len(comparable),
                            'full_ic_below_training': sum(r['full_minus_training_mean_ic'] < 0 for r in comparable),
                            'full_directional_ic_nonpositive': sum(r['full_history']['mean_ic'] <= 0 for r in comparable),
                            'independent_validation': False},
                        'candidate_diagnostics': diagnostics})
    return {'policy': policy, 'completed_batteries': batches, 'pending_batteries': pending,
            'interpretation': 'Data gaps and statistical failures are independent. Missing benchmark is not prediction failure. Objectives do not replace admission rules.'}


def update(config: Path) -> dict:
    result = build(config)
    root = Path(result['policy']['output_root'])
    root.mkdir(parents=True, exist_ok=True)
    target = root/'feedback.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')
    temporary.replace(target)
    return result


def prompt_context(config: Path) -> dict:
    result = update(config)
    return {**result, 'completed_batteries': [
        {k: v for k, v in batch.items() if k != 'candidate_diagnostics'}
        for batch in result['completed_batteries'][-3:]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/research_priorities.toml'))
    args = parser.parse_args()
    result = update(args.config)
    print(json.dumps({'output': result['policy']['output_root'],
                      'completed_batteries': len(result['completed_batteries']),
                      'pending_batteries': len(result['pending_batteries'])}))


if __name__ == '__main__':
    main()
