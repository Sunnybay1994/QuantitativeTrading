"""Read completed battery evidence for subsequent, frozen research requests."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import statistics as descriptive
from pathlib import Path
import tomllib

import polars as pl


def search_objective_components(candidate: dict) -> dict:
    """Describe saved selection evidence without inventing a scalar fitness."""
    def finite(value):
        return value if type(value) in (int, float) and math.isfinite(value) else None

    objective = candidate.get('search_objective', 'pooled_mean_ic_v1')
    correlation = finite(candidate.get('maximum_rank_correlation'))
    predictive = objective == 'predictive_priority_v2'
    stable = objective == 'stock_time_stability_v3'
    if stable:
        primary = finite(candidate.get('worst_stock_time_mean_ic'))
    elif predictive:
        primary = finite(candidate.get('selection_primary'))
    elif objective == 'cross_stock_min_ic_v1':
        primary = finite(candidate.get('worst_directional_mean_ic'))
    else:
        pooled = finite((candidate.get('train') or {}).get('mean_ic'))
        primary = abs(pooled) if pooled is not None else None
    fitness = None if predictive else finite(candidate.get('fitness'))
    penalty = (0. if stable else .5*correlation) if not predictive and correlation is not None else None
    return {'search_objective': objective,
            'primary_metric': ('worst_directional_stock_time_mean_ic' if stable else 'worst_directional_group_mean_ic' if predictive or objective == 'cross_stock_min_ic_v1'
                               else 'absolute_pooled_mean_ic'),
            'signal_component': primary, 'selection_primary': primary,
            'maximum_rank_correlation': correlation,
            'correlation_role': 'training_redundancy_ceiling' if stable else 'secondary_within_registered_ic_band' if predictive else 'scalar_fitness_penalty',
            'selection_eligible': candidate.get('selection_eligible') if predictive else None,
            'selection_reasons': candidate.get('selection_reasons') if predictive else None,
            'fitness': fitness, 'correlation_penalty': penalty,
            'nodes': candidate.get('complexity'),
            'residual_complexity_penalty': (primary-penalty-fitness
                if all(value is not None for value in (primary, penalty, fitness)) else None)}


def search_selection_summary(candidates: list[dict]) -> dict:
    """Keep objective-specific primary and secondary measures in compact feedback."""
    def measured(values):
        finite = [v for v in values if v is not None]
        return {'available': len(finite), 'missing': len(values)-len(finite),
                'median': descriptive.median(finite) if finite else None}

    components = [search_objective_components(row) for row in candidates]
    result = {}
    for objective in sorted({row['search_objective'] for row in components}):
        rows = [row for row in components if row['search_objective'] == objective]
        result[objective] = {'candidates': len(rows), 'primary_metric': rows[0]['primary_metric'],
                            'primary': measured([row['selection_primary'] for row in rows]),
                            'secondary_correlation': measured([row['maximum_rank_correlation'] for row in rows]),
                            'correlation_role': rows[0]['correlation_role'],
                            'eligible': sum(row['selection_eligible'] is True for row in rows),
                            'ineligible': sum(row['selection_eligible'] is False for row in rows),
                            'eligibility_unavailable': sum(row['selection_eligible'] is None for row in rows)}
    return result


def training_sample_description(inputs: dict) -> dict:
    result = {key: inputs.get(key) for key in ('sample_symbols', 'sample_months',
              'sample_first_signal', 'sample_last_signal', 'last_label_exit', 'training_end', 'cross_stock')}
    for key, alternate in [('sample_first_signal', 'first_signal'), ('sample_last_signal', 'last_signal')]:
        if result[key] is None:
            result[key] = inputs.get(alternate)
    return result


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
            'search_objective': candidate.get('search_objective', 'pooled_mean_ic_v1'),
            'search_selection': search_objective_components(candidate),
            'training_group_statistics': candidate.get('group_statistics'),
            'search_direction': direction, 'train_direction_adjusted': signed,
            'search_preprocessing': candidate.get('fitness_preprocessing'),
            'training_sample': training_sample_description(inputs),
            'full_history': {key: row.get(key) for key in ('months', 'first_valid_month', 'last_valid_month',
                'median_paired_stocks', 'mean_ic', 'icir', 'newey_west_t', 'decay', 'annual_ic',
                'yearly_positive_fraction', 'long_short_sharpe', 'statistical_failures')},
            'same_score_preprocessing': compatible, 'full_minus_training_mean_ic': delta,
            'training_comparison_basis': 'Direction-adjusted pooled training IC; not the worst-group selection primary.',
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


def sample_summary(diagnostics: list[dict]) -> dict:
    rows = [r for r in diagnostics if (r.get('sample_comparison') or {}).get('status') == 'complete']
    groups = {
        'reported_training': [r['train_direction_adjusted']['mean_ic'] for r in rows],
        'search_keys_battery_scores': [r['sample_comparison']['search_keys_with_battery_scores'][
            'battery_labels_battery_coverage']['mean_ic'] for r in rows],
        'full_pool_search_dates': [r['sample_comparison']['all_battery_stocks_by_window'][
            'search_dates']['mean_ic'] for r in rows],
        'full_pool_after_search': [r['sample_comparison']['all_battery_stocks_by_window'][
            'after_search']['mean_ic'] for r in rows],
    }
    distributions = {}
    for key, raw in groups.items():
        values = [v for v in raw if v is not None and math.isfinite(v)]
        distributions[key] = {'available': len(values), 'median': descriptive.median(values) if values else None,
                              'nonpositive': sum(v <= 0 for v in values)}
    return {'candidate_records': len(rows), 'independent_factors': False,
            'reported_training_basis': 'Direction-adjusted pooled training IC; search objectives are reported separately.',
            'label_disagreement_rows': sum(r['sample_comparison']['label_difference_over_1e_12_rows'] for r in rows),
            'mean_ic_distribution': distributions}


def build(config: Path, *, maximum_completed: int | None = None) -> dict:
    policy = tomllib.loads(config.read_text(encoding='utf-8'))
    batches, pending = [], []
    completed = []
    for path in sorted(Path(policy['continuous_root']).glob('batch_*/????-??-??/summary.json')):
        saved = json.loads(path.read_text(encoding='utf-8'))
        steps = saved.get('steps', {})
        scorecard = steps.get('N3', {}).get('result', {}).get('scorecard')
        # A timed-out or partial battery is never counted as a zero-pass batch.
        if not steps.get('N3', {}).get('ok') or not scorecard:
            pending.append({'run': str(path.parent), 'reason': 'Battery not completed'})
            continue
        completed.append((path, scorecard))
    if maximum_completed is not None:
        if maximum_completed < 1:
            raise ValueError('maximum_completed must be positive')
        completed = completed[-maximum_completed:]
    for path, scorecard in completed:
        rows = pl.read_parquet(scorecard).to_dicts()
        families = sorted({r.get('family', 'unknown') for r in rows})
        search_path = path.parent/'N2'/'search.json'
        search = json.loads(search_path.read_text(encoding='utf-8')) if search_path.exists() else {}
        trained = {r.get('factor_id'): r for r in search.get('candidates', [])}
        input_path = path.parent/'N2/input_summary.json'
        inputs = json.loads(input_path.read_text(encoding='utf-8')) if input_path.exists() else {}
        diagnostics = [candidate_diagnostic(row, trained.get(row['factor'], {}), inputs) for row in rows]
        from quant.research.search_sample_diagnostics import batch_diagnostics
        statistics = Path(scorecard).parent.parent/'statistics'
        try:
            samples = batch_diagnostics(path.parent, statistics)
            for diagnostic in diagnostics:
                if diagnostic.get('same_score_preprocessing'):
                    diagnostic['sample_comparison'] = samples.get(diagnostic['factor'])
        except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
            for diagnostic in diagnostics:
                diagnostic['sample_comparison'] = {'status': 'unavailable', 'error': str(exc)}
        comparable = [row for row in diagnostics if row['full_minus_training_mean_ic'] is not None]
        batches.append({'run': str(path.parent), 'source': scorecard, **summarize(rows),
                        'search_selection': search_selection_summary(search.get('candidates', [])),
                        'families': {f: summarize([r for r in rows if r.get('family', 'unknown') == f])
                                     for f in families},
                        'search_alignment': {'comparable_raw_candidates': len(comparable),
                            'comparison_basis': 'direction_adjusted_pooled_training_ic_not_worst_group_selection_primary',
                            'full_ic_below_training': sum(r['full_minus_training_mean_ic'] < 0 for r in comparable),
                            'full_directional_ic_nonpositive': sum(r['full_history']['mean_ic'] <= 0 for r in comparable),
                            'independent_validation': False},
                        'candidate_diagnostics': diagnostics})
    return {'policy': policy, 'completed_batteries': batches, 'pending_batteries': pending,
            'sample_comparison_summary': sample_summary([r for b in batches for r in b['candidate_diagnostics']]),
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


def open_priorities(policy: dict) -> list[dict]:
    """Return structured open priorities only (B5). Legacy string lists are rejected."""
    rows = policy.get('priority')
    if rows is None and 'priorities' in policy:
        raise ValueError('research_priorities.toml must use [[priority]] tables; legacy priorities= strings removed')
    if not isinstance(rows, list):
        raise ValueError('missing [[priority]] tables')
    required = ('id', 'status', 'mechanism', 'evidence_paths', 'stop_condition', 'next_action', 'updated')
    open_rows = []
    for row in rows:
        if not all(key in row for key in required):
            raise ValueError(f'priority missing fields: {row.get("id")}')
        if row['status'] not in ('open', 'closed'):
            raise ValueError(f'invalid priority status: {row.get("id")}')
        if row['status'] == 'open':
            open_rows.append({key: row[key] for key in required})
    return open_rows


def prompt_context(config: Path) -> dict:
    # A new request needs the recent batches, not a full report regeneration.
    result = build(config, maximum_completed=3)
    policy = result['policy']
    opens = open_priorities(policy)
    # Drop bulky closed narrative from the LLM-facing policy payload.
    compact_policy = {k: v for k, v in policy.items() if k != 'priority'}
    compact_policy['open_priorities'] = opens
    return {
        **result,
        'policy': compact_policy,
        'open_priorities': opens,
        'completed_comparison_scope': 'last_3_completed_batteries',
        'completed_batteries': [
            {k: v for k, v in batch.items() if k != 'candidate_diagnostics'}
            for batch in result['completed_batteries']
        ],
    }


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
