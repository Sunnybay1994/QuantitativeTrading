"""Export frozen monthly text scores for the existing statistical screen and cost replay."""
import json
from dataclasses import asdict
from pathlib import Path
import tomllib

import polars as pl

from quant.factors.forecast_text_score import DIMENSIONS
from quant.factors.library import load_library
from quant.research.factor_battery_screen import screen_statistics


def export(*, statistics: Path, battery: Path, output: Path) -> dict:
    summary = json.loads((statistics / 'summary.json').read_text(encoding='utf-8'))
    if summary['scope'] != 'frozen_monthly_sample_statistics':
        raise ValueError('Require frozen monthly sample statistics')
    settings = tomllib.loads(battery.read_text(encoding='utf-8'))
    factors = [f'text_{name}' for name in DIMENSIONS]
    definitions = {d.id: d for d in load_library(Path('configs/factors/p7_text_library'), 'all')}
    scores = pl.read_parquet(statistics / 'monthly_scores.parquet')
    if set(scores['factor'].unique()) != set(factors):
        raise ValueError('Require all registered text factors')
    if scores.select('factor', 'symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate monthly factor scores')
    if (summary['minimum_symbols'] != settings['minimum_symbols'] or
            summary['minimum_months'] != settings['admission']['minimum_months']):
        raise ValueError('Do not change the frozen statistical thresholds')
    table = pl.from_dicts(summary['summary'], infer_schema_length=None).with_columns(
        pl.col('mean_ic', 'icir', 'newey_west_t', 'p_value', 'yearly_positive_fraction').cast(pl.Float64))
    screen = screen_statistics(table, factors=factors, settings=settings)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'battery.toml').write_bytes(battery.read_bytes())
    table.write_parquet(output / 'statistics.parquet')
    for factor in factors:
        folder = output / 'factors' / factor
        folder.mkdir(parents=True)
        scores.filter(pl.col('factor') == factor).drop('factor').write_parquet(folder / 'monthly_scores.parquet')
        (folder / 'statistics.json').write_text(json.dumps({
            'scope': 'monthly_only_cost_input', 'factor': factor,
            'definition': asdict(definitions[factor]),
            'statistics': [r for r in summary['summary'] if r['factor'] == factor]}, indent=2),
            encoding='utf-8')
    screen_folder = output / 'screen'
    screen_folder.mkdir()
    (screen_folder / 'battery.toml').write_bytes(battery.read_bytes())
    screen.write_parquet(screen_folder / 'statistical_screen.parquet')
    result = {'scope': 'frozen_P7_three_factor_six_variant_family',
        'statistical_pass_rows': screen['statistical_pass'].sum(),
        'primary_statistical_pass': screen.filter(pl.col('statistical_pass') &
            (pl.col('variant') == settings['primary_variant']))['factor'].to_list(),
        'source': str(statistics), 'costs_executed': False,
        'next_step': 'Existing run_cost_batch with only_statistical_pass=True; then cost, benchmark and redundancy evidence'}
    (screen_folder / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
