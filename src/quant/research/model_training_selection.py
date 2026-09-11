"""Training-only factor admission and greedy selection with explicit incomplete evidence."""
import argparse
import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import polars as pl

from quant.research.factor_battery_redundancy import monthly_rank_correlation, summarize_correlation


def annual_selection(screen: pl.DataFrame, *, settings: dict, model: dict,
                     correlation: Callable[[str, str], dict]) -> tuple[list[dict], dict]:
    variant = model['selection']['variant']
    ranked = screen.filter(pl.col('variant') == variant).with_columns(pl.col('icir').fill_nan(None)).sort(
        ['icir', 'factor'], descending=[True, False], nulls_last=True)
    if not ranked.height or ranked['factor'].n_unique() != ranked.height:
        raise ValueError('Selection requires a unique primary factor family')
    higher, selected, confirmed, decisions = [], [], [], []
    uncertain = 0
    for row in ranked.iter_rows(named=True):
        factor = row['factor']
        admitted, chosen, maximum = False, False, None
        excluded_without_costs = False
        reason = 'statistical_threshold'
        if row['statistical_pass']:
            if row['cost_excess_pass'] is False:
                reason = 'cost_threshold'
            elif not row['costs_complete'] or row['cost_excess_pass'] is None:
                admitted, reason = None, 'cost_evidence_missing'
                if len(confirmed) >= model['selection']['maximum_factors']:
                    excluded_without_costs, reason = True, 'maximum_factors'
                else:
                    # A confirmed earlier pick cannot be displaced by a lower
                    # ranked factor. A qualified redundancy witness excludes
                    # this candidate regardless of its still-unknown costs.
                    for peer in confirmed:
                        pair = correlation(factor, peer)
                        if (pair['comparison_qualified'] and pair['mean_absolute_rank_correlation']
                                >= model['selection']['maximum_absolute_rank_correlation']):
                            excluded_without_costs, reason = True, 'greedy_redundancy_with_confirmed'
                            break
            else:
                comparisons = [correlation(factor, peer) for peer in higher]
                qualified = [pair['mean_absolute_rank_correlation'] for pair in comparisons
                             if pair['comparison_qualified']]
                maximum = max(qualified) if qualified else None
                if higher and maximum is None:
                    admitted, reason = None, 'higher_peer_history_insufficient'
                else:
                    admitted = maximum is None or maximum < settings['admission'][
                        'maximum_absolute_rank_correlation_with_better']
                    reason = 'admitted' if admitted else 'higher_peer_redundancy'
        if admitted is True and len(selected) < model['selection']['maximum_factors']:
            comparisons = [correlation(factor, peer) for peer in selected]
            if any(not pair['comparison_qualified'] for pair in comparisons):
                chosen, reason = None, 'selected_peer_history_insufficient'
            elif any(pair['mean_absolute_rank_correlation'] >= model['selection'][
                    'maximum_absolute_rank_correlation'] for pair in comparisons):
                reason = 'greedy_redundancy'
            else:
                chosen = True
                selected.append(factor)
                if uncertain == 0:
                    confirmed.append(factor)
        elif admitted is True:
            reason = 'maximum_factors'
        if not chosen and len(confirmed) >= model['selection']['maximum_factors']:
            excluded_without_costs, reason = True, 'maximum_factors'
        if (admitted is None and not excluded_without_costs) or chosen is None:
            uncertain += 1
        decisions.append({'factor': factor, 'variant': variant, 'training_icir': row['icir'],
            'training_mean_ic': row['mean_ic'], 'factor_admitted': admitted,
            'provisional_selected': chosen, 'selection_reason': reason,
            'higher_max_absolute_rank_correlation': maximum})
        higher.append(factor)
    return decisions, {'selection_complete': uncertain == 0, 'unresolved_factors': uncertain,
                       'provisional_selected': selected, 'confirmed_selected_prefix': confirmed}


def run_selection(*, costs: Path, output: Path, correlations_from: Path | None = None) -> dict:
    model = tomllib.loads((costs/'model.toml').read_text(encoding='utf-8'))
    settings = tomllib.loads((costs/'battery.toml').read_text(encoding='utf-8'))
    root = Path(model['research']['statistics_source'])
    if (root/'battery.toml').read_bytes() != (costs/'battery.toml').read_bytes():
        raise ValueError('Correlation source differs from annual cost settings')
    screens = pl.read_parquet(costs/'annual_cost_screen.parquet')
    all_decisions, summaries, pair_rows = [], [], []
    variant = model['selection']['variant']
    previous_pairs = {}
    if correlations_from is not None:
        previous_model = tomllib.loads((correlations_from/'model.toml').read_text(encoding='utf-8'))
        if ((correlations_from/'battery.toml').read_bytes() != (costs/'battery.toml').read_bytes()
                or previous_model['research']['statistics_source'] != model['research']['statistics_source']
                or previous_model['selection']['variant'] != variant):
            raise ValueError('Cached correlations require the same statistics, battery settings and variant')
        path = correlations_from/'annual_correlations.parquet'
        if path.is_file():
            for row in pl.read_parquet(path).iter_rows(named=True):
                pair = tuple(sorted((row['left'], row['right'])))
                key = (row['test_year'], row['refit_close'], pair)
                if row['variant'] != variant or key in previous_pairs:
                    raise ValueError('Invalid cached correlation keys')
                previous_pairs[key] = row
    for key, table in screens.partition_by('test_year', as_dict=True).items():
        year = key[0]
        cutoffs = table['refit_close'].unique().to_list()
        if len(cutoffs) != 1:
            raise ValueError('One refit close required per year')
        cutoff = cutoffs[0]
        cache: dict[tuple[str, str], dict] = {}

        def compare(left: str, right: str) -> dict:
            pair = tuple(sorted((left, right)))
            if pair not in cache:
                previous = previous_pairs.get((year, cutoff, pair))
                if previous is not None:
                    result = {key: value for key, value in previous.items()
                              if key not in ('test_year', 'refit_close', 'left', 'right', 'variant')}
                    cache[pair] = result
                    pair_rows.append(previous)
                    return result
                frames = [pl.scan_parquet(root/'factors'/name/'monthly_scores.parquet').filter(
                    pl.col('trade_date') <= cutoff).select('trade_date', 'symbol', variant).collect()
                    for name in pair]
                monthly = monthly_rank_correlation(*frames, variant=variant,
                                                   minimum_symbols=settings['minimum_symbols'])
                result = summarize_correlation(monthly, minimum_months=settings['admission']['minimum_months'])
                cache[pair] = result
                pair_rows.append({'test_year': year, 'refit_close': cutoff, 'left': pair[0],
                    'right': pair[1], 'variant': variant, **result})
            return cache[pair]

        decisions, summary = annual_selection(table, settings=settings, model=model, correlation=compare)
        all_decisions.extend({**row, 'test_year': year, 'refit_close': cutoff} for row in decisions)
        summaries.append({'test_year': year, 'refit_close': str(cutoff), **summary})
    result = {'annual_selection': summaries,
              'scope': 'Only selection_complete years can drive final model training; other lists are diagnostic'}
    output.mkdir(parents=True, exist_ok=False)
    for name in ('model.toml', 'battery.toml'):
        (output/name).write_bytes((costs/name).read_bytes())
    pl.from_dicts(all_decisions, infer_schema_length=None).write_parquet(output/'annual_selection.parquet')
    if pair_rows:
        pl.from_dicts(pair_rows, infer_schema_length=None).write_parquet(output/'annual_correlations.parquet')
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--costs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--correlations-from', type=Path, help='Previous selection from the same frozen statistics')
    args = parser.parse_args()
    print(json.dumps(run_selection(costs=args.costs, output=args.output, correlations_from=args.correlations_from)))


if __name__ == '__main__':
    main()
