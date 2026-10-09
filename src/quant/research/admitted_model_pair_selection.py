"""Causal candidate-family extension using saved batteries, never a new battery."""
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.research.factor_battery_cost_report import load_cost_history, return_indexes
from quant.research.factor_battery_redundancy import monthly_rank_correlation, summarize_correlation
from quant.research.factor_battery_scorecard import assemble_scorecard
from quant.research.factor_battery_screen import screen_statistics
from quant.research.model_training_costs import prefix_cost_report
from quant.research.model_training_prefix import outcome_calendar, prefix_statistics, training_prefix_settings
from quant.research.model_training_selection import annual_selection
from quant.research.personal_top5 import write_json


def candidate_screens(spec, model, battery, old, *, data_root):
    """Only the three new definitions need additional annual prefix measurements."""
    cfg = training_prefix_settings(battery, model)
    tables, cache = [], {}
    factors = [row['factor'] for row in spec['candidates']]
    for candidate in spec['candidates']:
        factor, root = candidate['factor'], Path(candidate['batch'])
        stats = root/'evaluation/statistics'
        source = tomllib.loads((stats/'battery.toml').read_text(encoding='utf-8'))
        for field in ('preprocessing', 'universe', 'variants', 'portfolio', 'costs', 'run'):
            if source[field] != battery[field]:
                raise ValueError(f'Candidate/source battery mismatch: {factor}/{field}')
        labels = pl.concat([pl.read_parquet(p, columns=['trade_date', 'exit_date_rebalance']).unique()
                            for p in sorted((stats/'inputs').glob('*/monthly_labels.parquet'))])
        calendar = outcome_calendar(labels)
        folder = stats/'factors'/factor
        monthly = pl.read_parquet(folder/'monthly_ic.parquet')
        groups = pl.read_parquet(folder/'monthly_groups.parquet')
        costs = root/'evaluation/costs'/factor
        summary = json.loads((costs/'summary.json').read_text(encoding='utf-8'))
        histories = {(r['variant'], r['cost_multiplier']): load_cost_history(
            costs, r['variant'], r['cost_multiplier'], source['run']['as_of']) for r in summary['rows']}
        for (year,), base in old.partition_by('test_year', as_dict=True).items():
            cutoff = base['refit_close'][0]
            stats_rows = prefix_statistics(factor=factor, monthly=monthly, groups=groups,
                calendar=calendar, cutoff=cutoff, settings=cfg)
            # FDR is reporting-only in this unchanged protocol. The combined-family
            # screen below supplies the correct denominator before final decisions.
            screen = screen_statistics(pl.from_dicts(stats_rows, infer_schema_length=None),
                                       factors=[factor], settings=cfg)
            reports = []
            for key, history in histories.items():
                active = history[0].filter((pl.col('market_value') > 0) & (pl.col('date') <= cutoff))
                errors = {}
                indexes = return_indexes(config=Path(spec['return_benchmark_config']), data_root=data_root,
                    start=active['date'].min(), end=cutoff, cache=cache, errors=errors) if active.height else {}
                reports.append(prefix_cost_report(factor=factor, histories={key: history},
                    benchmarks={(name, None): frame for name, frame in indexes.items()}, cutoff=cutoff,
                    initial_cash=battery['portfolio']['initial_cash'], benchmark_errors=errors))
            table = assemble_scorecard(screen, cost_reports=[r for r in reports if r['rows']],
                correlations=None, settings=cfg).with_columns(pl.lit(year).alias('test_year'),
                                                              pl.lit(cutoff).alias('refit_close'))
            tables.append(table)
    if set(factors) & set(old['factor']):
        raise ValueError('An addition is already present in the frozen control family')
    return pl.concat(tables, how='diagonal_relaxed')


def recompute_family_screen(table, cfg):
    """Recompute reporting FDR for the combined family without relaxing any gate."""
    from quant.research.factor_battery_statistics import benjamini_hochberg
    table = table.sort('factor', 'variant')
    adjusted = benjamini_hochberg(table['p_value'].to_list())
    if cfg['multiple_testing']['admission_requires_fdr']:
        raise ValueError('This registered experiment requires the original reporting-only FDR policy')
    return table.with_columns(pl.Series('bh_adjusted_p', adjusted, dtype=pl.Float64),
        pl.Series('bh_discovery', [p is not None and p <= cfg['multiple_testing']['q'] for p in adjusted]))


def select(spec, output, *, data_root):
    source = Path(spec['control_selection'])
    model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    battery = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    cfg = training_prefix_settings(battery, model)
    original = Path(model['research']['statistics_source'])
    old = pl.read_parquet(Path(spec['control_costs'])/'annual_cost_screen.parquet')
    if (source/'battery.toml').read_bytes() != (Path(spec['control_costs'])/'battery.toml').read_bytes():
        raise ValueError('Frozen selection and cost battery settings differ')
    additions = candidate_screens(spec, model, battery, old, data_root=data_root)
    additions.write_parquet(output/'candidate_annual_cost_screen.parquet')
    expected = {r['test_year']: r for r in json.loads((source/'summary.json').read_text())['annual_selection']}
    pairs = pl.read_parquet(source/'annual_correlations.parquet').to_dicts()
    previous = {(r['test_year'], tuple(sorted((r['left'], r['right'])))): r for r in pairs}
    roots = {r['factor']: Path(r['batch'])/'evaluation/statistics' for r in spec['candidates']}
    correlation_dir = output/'monthly_correlations'; correlation_dir.mkdir(exist_ok=True)
    decisions, plans, checks, pair_rows = [], [], [], []
    variant = model['selection']['variant']
    for (year,), base in old.partition_by('test_year', as_dict=True).items():
        cutoff = base['refit_close'][0]
        def compare(left, right):
            key = tuple(sorted((left, right)))
            cached = previous.get((year, key))
            if cached is not None:
                if cached['refit_close'] != cutoff or cached['variant'] != variant:
                    raise ValueError('Cached annual correlation metadata differs')
                return {**cached, 'comparison_qualified': cached['months'] >= cfg['admission']['minimum_months']}
            path = correlation_dir/(key[0]+'__'+key[1]+'.parquet')
            if path.exists():
                monthly = pl.read_parquet(path)
            else:
                frames = [pl.read_parquet(roots.get(name, original)/'factors'/name/'monthly_scores.parquet',
                    columns=['symbol', 'trade_date', variant]) for name in key]
                monthly = monthly_rank_correlation(*frames, variant=variant, minimum_symbols=battery['minimum_symbols'])
                monthly.write_parquet(path)
            result = summarize_correlation(monthly.filter(pl.col('trade_date') <= cutoff),
                                           minimum_months=cfg['admission']['minimum_months'])
            previous[year, key] = {**result, 'refit_close': cutoff, 'variant': variant}
            pair_rows.append({'test_year': year, 'refit_close': cutoff, 'left': key[0], 'right': key[1], **result})
            return result
        _, baseline = annual_selection(base, settings=cfg, model=model, correlation=compare)
        if (not baseline['selection_complete'] or baseline['provisional_selected'] != expected[year]['provisional_selected']):
            raise ValueError(f'Original annual selection did not reproduce: {year}')
        combined = recompute_family_screen(pl.concat([base, additions.filter(pl.col('test_year') == year)],
                                                       how='diagonal_relaxed'), cfg)
        rows, plan = annual_selection(combined, settings=cfg, model=model, correlation=compare)
        if not plan['selection_complete']:
            raise ValueError(f'Extended annual causal selection remains incomplete: {year}')
        decisions.extend({'test_year': year, 'refit_close': cutoff, **row} for row in rows)
        plans.append({'test_year': year, 'refit_close': str(cutoff), **plan})
        checks.append({'test_year': year, 'control_selection_reproduced': True,
            'control': baseline['provisional_selected'], 'extended': plan['provisional_selected'],
            'changed': baseline['provisional_selected'] != plan['provisional_selected']})
        write_json(output/'selection_progress.json', {'completed_years': checks})
    folder = output/'selection'; folder.mkdir(exist_ok=True)
    pl.from_dicts(decisions, infer_schema_length=None).write_parquet(folder/'annual_selection.parquet')
    if pair_rows:
        pl.from_dicts(pair_rows, infer_schema_length=None).write_parquet(folder/'additional_correlations.parquet')
    for name in ('model.toml', 'battery.toml'):
        (folder/name).write_bytes((source/name).read_bytes())
    write_json(folder/'summary.json', {'annual_selection': plans, 'paired_selection': checks,
        'scope': 'Original family versus original family plus fixed additions; historical adaptive research'})
    return checks
