"""Compare a completed candidate batch with the older library on training dates."""
import argparse
import datetime as dt
import json
import os
import tomllib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import polars as pl

from quant.research.factor_battery_redundancy import monthly_rank_correlation, summarize_correlation


def overlap_summary(pairs: pl.DataFrame, threshold: float) -> pl.DataFrame:
    """Keep missing comparisons visible; high overlap alone does not rank factors."""
    rows = []
    for (factor, variant), group in pairs.partition_by(['factor', 'variant'], as_dict=True).items():
        qualified = group.filter(pl.col('comparison_qualified')).sort(
            ['mean_absolute_rank_correlation', 'peer'], descending=[True, False])
        best = qualified.row(0, named=True) if qualified.height else None
        rows.append({'factor': factor, 'variant': variant, 'library_peer_count': group.height,
            'qualified_peer_count': qualified.height, 'insufficient_history_peer_count': group.height-qualified.height,
            'overlapping_peer_count': qualified.filter(pl.col('mean_absolute_rank_correlation') >= threshold).height,
            'maximum_mean_absolute_rank_correlation': best['mean_absolute_rank_correlation'] if best else None,
            'closest_factor': best['peer'] if best else None, 'comparison_months': best['months'] if best else None,
            'median_common_symbols': best['median_common_symbols'] if best else None})
    return pl.from_dicts(rows, infer_schema_length=None).sort('factor', 'variant')


def compare_candidate(candidate: Path, reference: Path, factor: str, variants: list[str], peers: list[str],
                      cutoff: dt.date, minimum_symbols: int, minimum_months: int) -> list[dict]:
    def read(root: Path, name: str) -> pl.DataFrame:
        return pl.scan_parquet(root/'factors'/name/'monthly_scores.parquet').filter(
            pl.col('trade_date') <= cutoff).collect()
    left = read(candidate, factor)
    rows = []
    for peer in peers:
        right = read(reference, peer)
        for variant in variants:
            monthly = monthly_rank_correlation(left, right, variant=variant, minimum_symbols=minimum_symbols)
            rows.append({'factor': factor, 'peer': peer, 'variant': variant,
                         **summarize_correlation(monthly, minimum_months=minimum_months)})
    return rows


def run(*, batch: Path, reference: Path, output: Path, workers: int) -> dict:
    completed = json.loads((batch/'summary.json').read_text(encoding='utf-8'))
    if completed['message'] != 'completed' or workers < 1:
        raise ValueError('Require a completed batch and positive worker count')
    candidate = batch/'training'
    settings = tomllib.loads((candidate/'battery.toml').read_text(encoding='utf-8'))
    reference_settings = tomllib.loads((reference/'battery.toml').read_text(encoding='utf-8'))
    for key in ('preprocessing', 'primary_variant', 'minimum_symbols', 'universe'):
        if settings[key] != reference_settings[key]:
            raise ValueError(f'Incompatible score preprocessing or universe: {key}')
    cutoff = dt.date.fromisoformat(completed['training_end'])
    if settings['run']['as_of'] != cutoff or reference_settings['run']['as_of'] < cutoff:
        raise ValueError('Candidate cutoff must match training and reference must cover it')
    selected = pl.read_parquet(batch/'scorecard/factor_scorecard.parquet').filter(pl.col('factor_admitted'))
    peers = sorted(pl.read_parquet(reference/'statistics.parquet')['factor'].unique().to_list())
    if selected.is_empty() or not peers or set(selected['factor']) & set(peers):
        raise ValueError('Require new candidate names and a nonempty reference library')
    output.mkdir(parents=True, exist_ok=False)
    (output/'battery.toml').write_bytes((candidate/'battery.toml').read_bytes())
    plan = {'batch': str(batch), 'reference': str(reference), 'training_cutoff': str(cutoff),
        'candidate_versions': selected.height, 'reference_factors': len(peers),
        'scope': 'All earlier-library peers; descriptive overlap, no higher-score ordering or admission change'}
    (output/'config.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    os.environ['POLARS_MAX_THREADS'] = '2'
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(compare_candidate, candidate, reference, factor,
            selected.filter(pl.col('factor') == factor)['variant'].to_list(), peers, cutoff,
            settings['minimum_symbols'], settings['admission']['minimum_months']): factor
            for factor in sorted(selected['factor'].unique().to_list())}
        for future in as_completed(futures):
            part = future.result()
            pl.from_dicts(part, infer_schema_length=None).write_parquet(output/f'{futures[future]}.parquet')
            rows.extend(part)
            print(json.dumps({'completed_factor': futures[future], 'pair_versions_completed': len(rows)}), flush=True)
    pairs = pl.from_dicts(rows, infer_schema_length=None).sort('factor', 'variant', 'peer')
    pairs.write_parquet(output/'pairs.parquet')
    summary = overlap_summary(pairs, settings['admission']['maximum_absolute_rank_correlation_with_better'])
    summary.write_csv(output/'overlap.csv')
    result = {**plan, 'pair_versions': pairs.height,
        'candidate_versions_with_high_overlap': summary.filter(pl.col('overlapping_peer_count') > 0).height,
        'qualified_pair_versions': pairs.filter(pl.col('comparison_qualified')).height}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(run(batch=args.batch, reference=args.reference, output=args.output, workers=args.workers)))


if __name__ == '__main__':
    main()
