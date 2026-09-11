"""Monthly cross-sectional Spearman comparisons on common observed stocks."""
import argparse
import json
import math
import os
import tomllib
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import polars as pl

from quant.factors.library import load_library


def monthly_rank_correlation(left: pl.DataFrame, right: pl.DataFrame, *, variant: str,
                             minimum_symbols: int) -> pl.DataFrame:
    """Rank the intersection afresh; existing ranks need not survive missing stocks."""
    if minimum_symbols < 2:
        raise ValueError('Rank correlation requires at least two common stocks')
    keys = ['trade_date', 'symbol']
    for frame in (left, right):
        if frame.select(keys).is_duplicated().any():
            raise ValueError('Duplicate factor score keys')
    def observed(frame: pl.DataFrame, name: str) -> pl.DataFrame:
        return frame.select(*keys, pl.col(variant).alias(name)).filter(pl.col(name).is_finite())

    paired = observed(left, 'left').join(observed(right, 'right'), on=keys, validate='1:1')
    dates = pl.concat([left.select('trade_date'), right.select('trade_date')]).unique()
    ranks = paired.with_columns(pl.col('left', 'right').rank('average').over('trade_date'))
    correlations = ranks.group_by('trade_date').agg(
        pl.len().alias('common_symbols'), pl.corr('left', 'right').alias('rank_correlation'))
    return dates.join(correlations, on='trade_date', how='left').with_columns(
        pl.col('common_symbols').fill_null(0),
        pl.when((pl.col('common_symbols') >= minimum_symbols) & pl.col('rank_correlation').is_finite())
        .then(pl.col('rank_correlation')).otherwise(None).alias('rank_correlation'),
    ).sort('trade_date')


def summarize_correlation(monthly: pl.DataFrame, *, minimum_months: int) -> dict:
    """Mean absolute monthly correlation avoids cancellation after sign changes."""
    if minimum_months < 1 or monthly['trade_date'].n_unique() != monthly.height:
        raise ValueError('Invalid correlation month coverage')
    values = monthly['rank_correlation'].drop_nulls()
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Nonfinite monthly correlation')
    return {'months': len(values), 'comparison_qualified': len(values) >= minimum_months,
            'mean_rank_correlation': values.mean(),
            'mean_absolute_rank_correlation': values.abs().mean(),
            'median_common_symbols': monthly.filter(pl.col('rank_correlation').is_not_null())['common_symbols'].median()}


def _compare_factor(statistics: Path, output: Path, left: str, others: list[str], settings: dict) -> list[dict]:
    part = output/'pairs'/f'{left}.json'
    if part.is_file():
        return json.loads(part.read_text(encoding='utf-8'))
    first = pl.read_parquet(statistics/'factors'/left/'monthly_scores.parquet')
    rows = []
    for right in others:
        second = pl.read_parquet(statistics/'factors'/right/'monthly_scores.parquet')
        for variant in settings['variants']:
            monthly = monthly_rank_correlation(first, second, variant=variant,
                                               minimum_symbols=settings['minimum_symbols'])
            rows.append({'left': left, 'right': right, 'variant': variant,
                         **summarize_correlation(monthly, minimum_months=settings['admission']['minimum_months'])})
    part.write_text(json.dumps(rows), encoding='utf-8')
    return rows


def correlation_maxima(pairs: pl.DataFrame, statistics: pl.DataFrame, *, settings: dict) -> pl.DataFrame:
    """Report all-peer maxima and higher-primary-ICIR maxima separately."""
    primary = statistics.filter(pl.col('variant') == settings['primary_variant']).select('factor', 'icir')
    if primary['factor'].n_unique() != primary.height:
        raise ValueError('Duplicate primary factor scores')
    ordered = primary.with_columns(pl.col('icir').fill_nan(None)).sort(
        ['icir', 'factor'], descending=[True, False], nulls_last=True)['factor'].to_list()
    ordering = {factor: index for index, factor in enumerate(ordered)}
    peers: dict[tuple, list] = {}
    for row in pairs.filter(pl.col('comparison_qualified')).iter_rows(named=True):
        for factor, other in ((row['left'], row['right']), (row['right'], row['left'])):
            peers.setdefault((factor, row['variant']), []).append(
                (row['mean_absolute_rank_correlation'], other, row['months']))
    rows = []
    for factor in ordered:
        for variant in settings['variants']:
            comparisons = peers.get((factor, variant), [])
            higher = [item for item in comparisons if ordering[item[1]] < ordering[factor]]
            row = {'factor': factor, 'variant': variant, 'qualified_peer_count': len(comparisons),
                   'qualified_higher_peer_count': len(higher)}
            for label, values in (('all', comparisons), ('higher', higher)):
                best = sorted(values, key=lambda value: (-value[0], value[1]))[0] if values else None
                row.update({f'{label}_max_absolute_rank_correlation': best[0] if best else None,
                            f'{label}_most_correlated_factor': best[1] if best else None,
                            f'{label}_comparison_months': best[2] if best else None})
            row['redundant_with_higher'] = bool(higher) and max(value[0] for value in higher) >= settings[
                'admission']['maximum_absolute_rank_correlation_with_better']
            rows.append(row)
    return pl.from_dicts(rows, infer_schema_length=None)


def run_redundancy(*, statistics: Path, output: Path, library: Path, workers: int) -> dict:
    settings_bytes = (statistics/'battery.toml').read_bytes()
    settings = tomllib.loads(settings_bytes.decode('utf-8'))
    definitions = load_library(library, 'all')
    factors = sorted(d.id for d in definitions)
    table = pl.read_parquet(statistics/'statistics.parquet')
    expected = {(factor, variant) for factor in factors for variant in settings['variants']}
    if (workers < 1 or settings['run']['selected'] != 'all' or table.height != len(expected)
            or set(table.select('factor', 'variant').rows()) != expected):
        raise ValueError('Redundancy requires the complete registered statistical run')
    source = str(statistics.resolve())
    configuration = {'statistics': source, 'factors': factors,
                     'aggregation': 'mean_absolute_monthly_common_stock_spearman',
                     'minimum_symbols': settings['minimum_symbols'],
                     'minimum_months': settings['admission']['minimum_months']}
    output.mkdir(parents=True, exist_ok=True)
    saved = output/'comparison.json'
    if saved.is_file():
        if json.loads(saved.read_text(encoding='utf-8')) != configuration or (output/'battery.toml').read_bytes() != settings_bytes:
            raise ValueError('Choose a new correlation output for changed inputs or settings')
    else:
        saved.write_text(json.dumps(configuration, indent=2), encoding='utf-8')
        (output/'battery.toml').write_bytes(settings_bytes)
    (output/'pairs').mkdir(exist_ok=True)
    os.environ['POLARS_MAX_THREADS'] = '4'
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_compare_factor, statistics, output, factor, factors[index+1:], settings): factor
                   for index, factor in enumerate(factors[:-1])}
        for count, future in enumerate(as_completed(futures), 1):
            rows.extend(future.result())
            print(json.dumps({'factor': futures[future], 'completed': count, 'total': len(futures)}), flush=True)
    pairs = pl.from_dicts(rows, infer_schema_length=None).sort('left', 'right', 'variant')
    pairs.write_parquet(output/'pairwise_correlations.parquet')
    maxima = correlation_maxima(pairs, table, settings=settings)
    maxima.write_parquet(output/'correlation_maxima.parquet')
    result = {'factors': len(factors), 'pair_variant_rows': pairs.height,
              'qualified_pair_variant_rows': pairs['comparison_qualified'].sum(),
              'redundant_variant_rows': maxima['redundant_with_higher'].sum()}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--statistics', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--library', type=Path, default=Path('configs/factors/library'))
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(run_redundancy(statistics=args.statistics, output=args.output,
                                  library=args.library, workers=args.workers)))


if __name__ == '__main__':
    main()
