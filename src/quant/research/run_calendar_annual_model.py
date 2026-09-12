"""Full-period annual retraining and replay of the fixed calendar input repair."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.reporting.multifactor_models import report_models
from quant.research.model_training_models import common_features, training_panel
from quant.research.run_multifactor_replay import run_model_replay
from quant.research.run_multifactor_predictions import completed_fit_plan


def annual_windows(*, fits: list[dict], sessions: tuple[dt.date, ...], start: dt.date, end: dt.date) -> list[dict]:
    years = list(range(start.year, end.year+1))
    if sorted(row['test_year'] for row in fits) != years:
        raise ValueError('Require each source year exactly once')
    plan = []
    for fit in sorted(fits, key=lambda row: row['test_year']):
        year = fit['test_year']
        cutoff = max(day for day in sessions if day < dt.date(year, 1, 1))
        last = (end if year == end.year else
                max(day for day in sessions if day < dt.date(year+1, 1, 1))-dt.timedelta(days=1))
        if fit.get('refit_close') and (fit['refit_close'] != str(cutoff)
                or (not fit.get('selection_only', False) and fit['last_known_exit'] > str(cutoff))):
            raise ValueError('Source fit crosses its annual calendar cutoff')
        plan.append({'test_year': year, 'cutoff': cutoff, 'end': last, 'source_factors': fit['factors']})
    return plan


def source_annual_factors(*, source: Path, model: dict, from_selection: bool) -> list[dict]:
    """Use completed causal selections directly, without fitting an unused baseline."""
    if not from_selection:
        return json.loads((source/'summary.json').read_text(encoding='utf-8'))['annual_fits']
    plan = completed_fit_plan(source, model)
    return [{'test_year': row['test_year'], 'factors': row['provisional_selected'],
             'refit_close': row['refit_close'], 'selection_only': True}
            for row in plan]


def run_annual(*, config_path: Path, output: Path, data_root: Path, measurement_config: Path) -> dict:
    from lightgbm import LGBMRegressor

    config_bytes = config_path.read_bytes()
    config = tomllib.loads(config_bytes.decode('utf-8'))
    measurement_bytes = measurement_config.read_bytes()
    tomllib.loads(measurement_bytes.decode('utf-8'))
    research, settings = config['research'], config['model']
    missing_policy = settings.get('missing_features', 'common_complete_case_pool_for_all_three_methods')
    maximum_missing = settings.get('maximum_missing_fraction', .3)
    if missing_policy not in {'common_complete_case_pool_for_all_three_methods', 'neutral_zero_with_monthly_factor_exclusion'}:
        raise ValueError('Unknown monthly missing-feature policy')
    if research['auto_trade'] is not False or settings['method'] != 'lightgbm':
        raise ValueError('Require the registered research model')
    sources_present = [key for key in ('source_predictions', 'source_selection') if key in research]
    if len(sources_present) != 1:
        raise ValueError('Specify exactly one annual predictions or completed selection source')
    source = Path(research[sources_present[0]])
    model_text = (source/'model.toml').read_text(encoding='utf-8')
    original = tomllib.loads(model_text)
    if any(settings[key] != original['walk_forward'][key] for key in ('test_start', 'test_end')):
        raise ValueError('Full replay must retain the source period')
    battery = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    fits = source_annual_factors(source=source, model=original, from_selection='source_selection' in research)
    sessions = available_sessions(data_root, dt.date(settings['test_end'].year+1, 1, 31))
    plan = annual_windows(fits=fits, sessions=sessions, start=settings['test_start'], end=settings['test_end'])
    roots = [Path(path) for path in config['inputs']['calendar_statistics']]
    for root in roots:
        if (root/'battery.toml').exists():
            other = tomllib.loads((root/'battery.toml').read_text(encoding='utf-8'))
            if any(other[key] != battery[key] for key in ('preprocessing', 'universe', 'variants')):
                raise ValueError('Calendar score preprocessing differs from the source')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config_bytes)
    (output/'measurement.toml').write_bytes(measurement_bytes)
    predictions = output/'predictions'
    predictions.mkdir()
    sources = {factor: roots for factor in config['replacements'].values()}
    statistics = Path(original['research']['statistics_source'])
    completed, parts = [], []
    feature_coverage: list[dict] = []
    for annual in plan:
        year, cutoff = annual['test_year'], annual['cutoff']
        factors = [config['replacements'].get(f, f) for f in annual['source_factors']]
        if len(factors) != len(set(factors)):
            raise ValueError('Annual replacement created duplicate features')
        if not factors:
            completed.append({'test_year': year, 'factors': [], 'reason': 'no_admitted_factors', 'prediction_rows': 0})
            continue
        annual_coverage: list[dict] = []
        features = common_features(statistics=statistics, factors=factors, variant=original['selection']['variant'],
            start=settings['training_start'], end=annual['end'], minimum_symbols=settings['minimum_signal_stocks'],
            statistics_sources=sources, missing_policy=missing_policy, maximum_missing_fraction=maximum_missing,
            coverage=annual_coverage)
        feature_coverage.extend({'test_year': year, 'refit_close': cutoff, **row} for row in annual_coverage)
        train = training_panel(features=features, statistics=statistics, cutoff=cutoff,
                               minimum_symbols=settings['minimum_signal_stocks'])
        if train['trade_date'].n_unique() < settings['minimum_training_months']:
            completed.append({'test_year': year, 'factors': factors, 'reason': 'insufficient_complete_training_history',
                              'prediction_rows': 0})
            continue
        regressor = LGBMRegressor(**original['models']['lightgbm'])
        regressor.fit(train.select(factors).to_numpy(), train['label_rebalance'].to_numpy())
        future = features.filter(pl.col('trade_date') >= cutoff)
        forecast = regressor.booster_.predict(future.select(factors).to_numpy()) if future.height else []
        parts.append(future.select('symbol', 'trade_date').with_columns(
            pl.Series('lightgbm', forecast, dtype=pl.Float64), pl.lit(year).alias('test_year')))
        regressor.booster_.save_model(str(predictions/f'lightgbm_{year}.txt'))
        fit = {'test_year': year, 'factors': factors, 'refit_close': str(cutoff),
            'last_known_exit': str(train['exit_date_rebalance'].max()), 'training_rows': train.height,
            'training_months': train['trade_date'].n_unique(), 'prediction_rows': future.height,
            'missing_features': missing_policy,
            'monthly_exclusion_encoding': ('annual LightGBM feature columns retained; excluded month values neutralized to zero'
                if missing_policy == 'neutral_zero_with_monthly_factor_exclusion' else None)}
        completed.append(fit)
        print(json.dumps(fit), flush=True)
    combined = pl.concat(parts) if parts else pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date,
                                                                 'lightgbm': pl.Float64, 'test_year': pl.Int32})
    if combined.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Annual predictions overlap')
    combined.write_parquet(predictions/'monthly_predictions.parquet')
    if feature_coverage:
        pl.from_dicts(feature_coverage).write_parquet(predictions/'monthly_feature_coverage.parquet')
    (predictions/'summary.json').write_text(json.dumps({'annual_fits': completed, 'prediction_rows': combined.height}, indent=2), encoding='utf-8')
    model_text = model_text.replace(original['research']['id'], research['id']).replace(
        'methods = ["equal_z", "positive_mean_ic", "lightgbm"]', 'methods = ["lightgbm"]').replace(
        json.dumps(original['research']['hypothesis']), json.dumps(research['hypothesis'])).replace(
        json.dumps(original['selection']['candidate_library']), json.dumps(settings['factor_selection']))
    if missing_policy != original['models']['missing_features']:
        old = 'missing_features = '+json.dumps(original['models']['missing_features'])
        new = 'missing_features = '+json.dumps(missing_policy)+f'\nmaximum_missing_fraction = {maximum_missing}'
        if model_text.count(old) != 1:
            raise ValueError('Source missing-feature configuration format changed')
        model_text = model_text.replace(old, new)
    model_text += '\n[research.factor_statistics_sources]\n' + '\n'.join(
        f'{factor} = {json.dumps([str(root) for root in paths])}' for factor, paths in sources.items())+'\n'
    if tomllib.loads(model_text)['models']['methods'] != ['lightgbm']:
        raise ValueError('Source configuration format changed')
    (predictions/'model.toml').write_text(model_text, encoding='utf-8')
    (predictions/'battery.toml').write_bytes((source/'battery.toml').read_bytes())
    benchmarks = Path(original['research']['stock_benchmarks'])
    print('Replaying the complete source account period', flush=True)
    replay = run_model_replay(predictions=predictions, benchmarks=benchmarks, output=output/'replay', data_root=data_root)
    report = report_models(run=output/'replay', measurement_config=output/'measurement.toml',
                          output=output/'reports', data_root=data_root)
    result = {'research_id': research['id'], 'annual_fits': completed, 'prediction_rows': combined.height,
              'conclusions': report['conclusions'], 'cost_rows': replay['rows']}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--measurement-config', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_annual(config_path=args.config, output=args.output, data_root=args.data_root,
                               measurement_config=args.measurement_config)))


if __name__ == '__main__':
    main()
