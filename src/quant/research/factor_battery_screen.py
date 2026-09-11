"""Apply the frozen statistical thresholds to the complete registered family."""
import argparse
import json
import math
import tomllib
from pathlib import Path

import polars as pl

from quant.factors.library import load_library
from quant.research.factor_battery_statistics import benjamini_hochberg


def screen_statistics(statistics: pl.DataFrame, *, factors: list[str], settings: dict) -> pl.DataFrame:
    """Keep both variants and missing p-values in the BH family denominator."""
    expected = {(factor, variant) for factor in factors for variant in settings['variants']}
    keys = statistics.select('factor', 'variant').rows()
    if len(factors) != len(set(factors)) or len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError('Statistical screening requires the complete unique factor/variant family')
    table = statistics.sort('factor', 'variant').with_columns(
        pl.col('group_statistics').struct.field('long_short_sharpe').alias('long_short_sharpe'))
    adjusted = benjamini_hochberg(table['p_value'].to_list())
    admission = settings['admission']
    rows = []
    for row, p_adjusted in zip(table.iter_rows(named=True), adjusted, strict=True):
        def enough(field: str, threshold: float, *, absolute: bool = False) -> bool:
            value = row[field]
            return value is not None and math.isfinite(value) and (abs(value) if absolute else value) >= threshold

        checks = {
            'history': enough('months', admission['minimum_months']),
            'hac_t': enough('newey_west_t', admission['minimum_absolute_newey_west_t'], absolute=True),
            'directional_icir': enough('icir', admission['minimum_directional_icir']),
            'annual_consistency': enough('yearly_positive_fraction', admission['minimum_yearly_positive_fraction']),
            'long_short': enough('long_short_sharpe', admission['minimum_long_short_sharpe']),
        }
        fdr = p_adjusted is not None and p_adjusted <= settings['multiple_testing']['q']
        if settings['multiple_testing']['admission_requires_fdr']:
            checks['fdr'] = fdr
        rows.append({**row, 'bh_adjusted_p': p_adjusted, 'bh_discovery': fdr,
                     'statistical_pass': all(checks.values()),
                     'statistical_failures': [name for name, passed in checks.items() if not passed]})
    return pl.from_dicts(rows, infer_schema_length=None)


def run_screen(*, statistics: Path, output: Path, library: Path) -> dict:
    settings = tomllib.loads((statistics/'battery.toml').read_text(encoding='utf-8'))
    if settings['run']['selected'] != 'all':
        raise ValueError('Use the registered all-factor run for the BH family')
    definitions = load_library(library, 'all')
    table = screen_statistics(pl.read_parquet(statistics/'statistics.parquet'),
                              factors=[d.id for d in definitions], settings=settings)
    discoveries = table['bh_discovery'].sum()
    summary = {'factors': len(definitions), 'tests': table.height,
               'bh_discoveries': discoveries,
               'nominal_q_times_discoveries': settings['multiple_testing']['q']*discoveries,
               'statistical_pass_rows': table['statistical_pass'].sum(),
               'primary_statistical_pass': table.filter(
                   (pl.col('variant') == settings['primary_variant']) & pl.col('statistical_pass'))['factor'].to_list(),
               'scope': 'statistical screen; executable excess returns and redundancy still required',
               'fdr_interpretation': 'q times discoveries is a nominal report, not an observed false count or guaranteed bound'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'battery.toml').write_bytes((statistics/'battery.toml').read_bytes())
    table.write_parquet(output/'statistical_screen.parquet')
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--statistics', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--library', type=Path, default=Path('configs/factors/library'))
    args = parser.parse_args()
    print(json.dumps(run_screen(statistics=args.statistics, output=args.output, library=args.library)))


if __name__ == '__main__':
    main()
