"""Recompute annual factor screens using only outcomes known at each refit."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.research.factor_battery_groups import summarize_groups
from quant.research.factor_battery_screen import screen_statistics
from quant.research.factor_battery_statistics import monthly_ic_summary


def training_prefix_settings(settings: dict, model: dict) -> dict:
    """Use the registered training prefix without altering the final battery."""
    if 'minimum_known_months' not in model['selection']:
        return {**settings, 'admission': dict(settings['admission'])}
    months = model['selection']['minimum_known_months']
    if type(months) is not int or not 48 <= months <= settings['admission']['minimum_months']:
        raise ValueError('Training prefix must cover at least 48 months and not exceed the final battery minimum')
    return {**settings, 'admission': {**settings['admission'], 'minimum_months': months}}


def outcome_calendar(labels: pl.DataFrame) -> pl.DataFrame:
    """One scheduled exit per signal, including explicitly unavailable outcomes."""
    calendar = labels.select('trade_date', 'exit_date_rebalance').unique().sort('trade_date')
    if (calendar['trade_date'].null_count()
            or calendar['trade_date'].n_unique() != calendar.height
            or calendar.filter(pl.col('exit_date_rebalance') <= pl.col('trade_date')).height):
        raise ValueError('Monthly outcomes require a unique later exit per signal date')
    return calendar


def known_outcomes(frame: pl.DataFrame, calendar: pl.DataFrame, cutoff: dt.date) -> pl.DataFrame:
    """Never use signal date alone to decide whether a monthly return is known."""
    if frame.join(calendar, on='trade_date', how='anti').height:
        raise ValueError('Outcome calendar is missing signal dates')
    return frame.join(calendar, on='trade_date', validate='m:1').filter(
        pl.col('exit_date_rebalance') <= cutoff)


def prefix_statistics(*, factor: str, monthly: pl.DataFrame, groups: pl.DataFrame,
                      calendar: pl.DataFrame, cutoff: dt.date, settings: dict) -> list[dict]:
    monthly = known_outcomes(monthly, calendar, cutoff)
    groups = known_outcomes(groups, calendar, cutoff)
    rows = []
    for variant in settings['variants']:
        observed = monthly.filter(pl.col('variant') == variant).sort('trade_date')
        summary = monthly_ic_summary(observed['trade_date'].to_list(), observed['rank_ic'].to_list(),
            lag=settings['monthly_newey_west_lag'],
            minimum_months_per_year=settings['minimum_months_per_year'])
        rows.append({'factor': factor, 'variant': variant, **summary,
            'last_known_exit': observed['exit_date_rebalance'].max(),
            'group_statistics': summarize_groups(groups.filter(pl.col('variant') == variant),
                                                  groups=settings['groups'])})
    return rows


def run_prefixes(*, config: Path, output: Path) -> dict:
    """Read cached battery observations once per factor; retain the complete family."""
    config_bytes = config.read_bytes()
    model = tomllib.loads(config_bytes.decode('utf-8'))
    root = Path(model['research']['statistics_source'])
    battery_bytes = (root/'battery.toml').read_bytes()
    settings = tomllib.loads(battery_bytes.decode('utf-8'))
    if settings['run']['selected'] != 'all':
        raise ValueError('Annual screens require the all-factor statistical run')
    settings = training_prefix_settings(settings, model)
    family = pl.read_parquet(root/'statistics.parquet', columns=['factor', 'variant'])
    factors = sorted(family['factor'].unique().to_list())
    if set(family.rows()) != {(f, v) for f in factors for v in settings['variants']}:
        raise ValueError('Incomplete source factor family')
    inputs = sorted((root/'inputs').glob('*/monthly_labels.parquet'))
    calendar = outcome_calendar(pl.concat([
        pl.read_parquet(p, columns=['trade_date', 'exit_date_rebalance']).unique() for p in inputs]))
    walk = model['walk_forward']
    cutoffs = {}
    for test_year in range(walk['test_start'].year, walk['test_end'].year+1):
        dates = pl.scan_parquet(root/'inputs'/str(test_year-1)/'universe.parquet').select(
            pl.col('trade_date').max()).collect().item()
        if dates is None or dates.year != test_year-1:
            raise ValueError('Missing prior-year exchange sessions')
        cutoffs[test_year] = dates
    annual: dict[int, list[dict]] = {year: [] for year in cutoffs}
    for factor in factors:
        folder = root/'factors'/factor
        monthly = pl.read_parquet(folder/'monthly_ic.parquet')
        groups = pl.read_parquet(folder/'monthly_groups.parquet')
        for year, cutoff in cutoffs.items():
            annual[year].extend(prefix_statistics(factor=factor, monthly=monthly, groups=groups,
                                                  calendar=calendar, cutoff=cutoff, settings=settings))
    tables, counts = [], []
    for year, rows in annual.items():
        table = screen_statistics(pl.from_dicts(rows, infer_schema_length=None),
                                  factors=factors, settings=settings).with_columns(
            pl.lit(year).alias('test_year'), pl.lit(cutoffs[year]).alias('refit_close'))
        tables.append(table)
        primary = table.filter(pl.col('variant') == model['selection']['variant'])
        counts.append({'test_year': year, 'refit_close': str(cutoffs[year]),
            'primary_with_required_history': primary.filter(
                pl.col('months') >= settings['admission']['minimum_months']).height,
            'primary_statistical_pass': primary['statistical_pass'].sum(),
            'maximum_known_months': primary['months'].max()})
    summary = {'factors': len(factors), 'annual_screens': counts,
               'training_minimum_months': settings['admission']['minimum_months'],
               'final_battery_minimum_months': tomllib.loads(battery_bytes.decode('utf-8'))['admission']['minimum_months'],
               'scope': 'training statistics only; prefix costs and correlations still required'}
    output.mkdir(parents=True, exist_ok=False)
    pl.concat(tables, how='diagonal_relaxed').write_parquet(output/'annual_statistical_screen.parquet')
    (output/'model.toml').write_bytes(config_bytes)
    (output/'battery.toml').write_bytes(battery_bytes)
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_prefixes(config=args.config, output=args.output)))


if __name__ == '__main__':
    main()
