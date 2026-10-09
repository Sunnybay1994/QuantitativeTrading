"""One preregistered admitted-family extension, using frozen historical evidence."""
import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
import tomllib

import polars as pl

from quant.research.personal_top5 import digest, write_json

DEFAULT = Path('configs/research/admitted_model_pair_20260930.toml')
EXPECTED = {'ngp_804a131ba8cb5a88', 'ngp_bbcc07585bc35fbe', 'ngp_c8f096c17cdb7e19'}


def validate_spec(spec):
    if (spec['auto_trade'] is not False or spec['capital'] != 100000 or spec['top_k'] != 5
            or spec['commission_min'] != 1 or spec['cost_multipliers'] != [.5, 1., 2.]
            or {r['factor'] for r in spec['candidates']} != EXPECTED or len(spec['candidates']) != 3):
        raise ValueError('Only the fixed admitted-family Top5/fee1 experiment is registered')


def freeze(config, output):
    spec = tomllib.loads(config.read_text(encoding='utf-8')); validate_spec(spec)
    control = Path(spec['control_selection'])
    model = tomllib.loads((control/'model.toml').read_text(encoding='utf-8'))
    battery = tomllib.loads((control/'battery.toml').read_text(encoding='utf-8'))
    if (model['selection']['minimum_known_months'] != 48 or model['walk_forward']['test_end'] != dt.date(2026, 8, 31)
            or model['execution']['auto_trade'] is not False):
        raise ValueError('The original causal48 control configuration changed')
    repair = tomllib.loads(Path(spec['control_model_repair']).read_text(encoding='utf-8'))
    if Path(repair['research']['source_selection']).resolve() != control.resolve():
        raise ValueError('Control predictions no longer reference the frozen selection')
    sources = {config, Path(spec['control_model_repair']), Path(spec['personal_config']),
               Path(spec['return_benchmark_config'])}
    for key in ('control_selection', 'control_costs', 'control_predictions'):
        root = Path(spec[key])
        sources.update(p for p in root.glob('*') if p.is_file())
    account = Path(spec['control_account'])
    account_manifest = json.loads((account/'manifest.json').read_text(encoding='utf-8'))
    for name, sha in account_manifest['code'].items():
        if ('backtest' in name or name.endswith(('personal_top5_construction.py', 'classic_monthly_baseline.py'))):
            if digest(Path(name)) != sha:
                raise ValueError('Control execution implementation changed; control replay is required: '+name)
    sources.update(account/name for name in ('summary.json', 'manifest.json', 'source_manifest.json'))
    sources.update(p for p in (account/'inputs').rglob('*') if p.is_file())
    for cost in spec['cost_multipliers']:
        sources.update(p for p in (account/f'top5_fee1_cost{cost:g}').glob('*.parquet'))
    statistics = Path(model['research']['statistics_source'])
    family = pl.read_parquet(Path(spec['control_costs'])/'annual_cost_screen.parquet')['factor'].unique().to_list()
    sources.update(statistics/'factors'/factor/'monthly_scores.parquet' for factor in family)
    sources.update((statistics/'inputs').glob('*/*.parquet'))
    from quant.research.run_calendar_annual_model import replacement_statistics_sources
    for factor, roots in replacement_statistics_sources(repair).items():
        sources.update(root/'factors'/factor/'monthly_scores.parquet' for root in roots)
    for candidate in spec['candidates']:
        factor, batch = candidate['factor'], Path(candidate['batch'])
        admission_path = Path(candidate['admission'])
        admission = json.loads(admission_path.read_text(encoding='utf-8'))
        if not any(r['factor'] == factor and r['factor_admitted'] for r in admission['admitted_factors']):
            raise ValueError('Registered candidate lacks its actual N4 admission')
        formal = Path('configs/factors/library/auto')/f'{factor}.toml'
        published = tomllib.loads(formal.read_text(encoding='utf-8'))
        frozen = tomllib.loads((batch/'library'/f'{factor}.toml').read_text(encoding='utf-8'))
        if any(published[k] != frozen[k] for k in ('id', 'expr', 'family', 'direction', 'source_ref')):
            raise ValueError('Admitted candidate definition changed')
        stats = batch/'evaluation/statistics'
        other = tomllib.loads((stats/'battery.toml').read_text(encoding='utf-8'))
        if any(other[k] != battery[k] for k in ('run', 'preprocessing', 'universe', 'portfolio', 'costs', 'variants')):
            raise ValueError('Candidate battery cannot share the frozen control measurement')
        sources.update({admission_path, formal, batch/'library'/f'{factor}.toml', stats/'battery.toml'})
        sources.update(p for p in (stats/'factors'/factor).glob('*') if p.is_file())
        sources.update((stats/'inputs').glob('*/monthly_labels.parquet'))
        sources.update(p for p in (batch/'evaluation/costs'/factor).rglob('*') if p.is_file())
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    write_json(output/'request.json', {'registered_at': dt.datetime.now().isoformat(),
        'auto_trade': False, 'candidate_family': len(family)+3, 'control_family': len(family),
        'evidence': spec['evidence'], 'status': 'freezing', 'production_data_writes': False})
    hashes = {str(p): digest(p) for p in sorted(sources)}
    code = [Path(__file__), *Path('src/quant/research').glob('admitted_model_pair_*.py')]
    code += [Path('src/quant/research')/(name+'.py') for name in (
        'model_training_selection', 'model_training_models', 'model_training_prefix', 'model_training_costs',
        'personal_top5_construction', 'classic_monthly_baseline', 'factor_cost_checkpoint')]
    code += list(Path('src/quant/backtest').glob('*.py'))
    write_json(output/'manifest.json', {'config_sha256': digest(output/'config.toml'),
        'sources': hashes, 'code': {str(p): digest(p) for p in code}})
    write_json(output/'freeze.json', {'completed': True, 'sources': len(hashes), 'auto_trade': False})
    return spec


def verify(output):
    manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    if digest(output/'config.toml') != manifest['config_sha256']:
        raise ValueError('Frozen experiment config changed')
    for kind in ('sources', 'code'):
        for name, sha in manifest[kind].items():
            if digest(Path(name)) != sha:
                raise ValueError(f'Frozen {kind} changed: {name}')
    spec = tomllib.loads((output/'config.toml').read_text(encoding='utf-8'))
    validate_spec(spec)
    return spec


def reuse_selection(output, source):
    """Carry completed selection across an unexecuted replay repair, with provenance."""
    old = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    new = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    if ((source/'config.toml').read_bytes() != (output/'config.toml').read_bytes()
            or old['sources'] != new['sources']):
        raise ValueError('Selection reuse requires identical preregistration and frozen source hashes')
    folder = source/'selection'
    summary = json.loads((folder/'summary.json').read_text())
    if not all(r['selection_complete'] for r in summary['annual_selection']):
        raise ValueError('Only complete causal selection can be reused')
    hashes = {str(p): digest(p) for p in folder.iterdir() if p.is_file()}
    shutil.copytree(folder, output/'selection')
    for name, sha in hashes.items():
        if digest(output/'selection'/Path(name).name) != sha:
            raise ValueError('Reused selection copy changed')
    new['sources'].update(hashes)
    write_json(output/'manifest.json', new)
    write_json(output/'selection_reuse.json', {'source': str(source), 'sha256': hashes,
        'scope': 'Selection reused; replay code repaired before first prediction or account evaluation.'})


def predict(spec, output, *, data_root):
    """Only changed ordered annual selections retrain; unchanged years reuse control."""
    from lightgbm import LGBMRegressor
    from quant.data.factor_panels import available_sessions
    from quant.research.model_training_models import common_features, training_panel
    from quant.research.run_calendar_annual_model import annual_windows, replacement_statistics_sources
    selection = json.loads((output/'selection/summary.json').read_text())
    original = Path(spec['control_predictions'])
    repair = tomllib.loads(Path(spec['control_model_repair']).read_text(encoding='utf-8'))
    model = tomllib.loads((original/'model.toml').read_text(encoding='utf-8'))
    stats = Path(model['research']['statistics_source'])
    fits = json.loads((original/'summary.json').read_text(encoding='utf-8'))['annual_fits']
    controls = {r['test_year']: r for r in fits}
    plan = [{'test_year': r['test_year'], 'factors': r['provisional_selected'],
             'refit_close': r['refit_close'], 'selection_only': True} for r in selection['annual_selection']]
    walk = model['walk_forward']; settings = repair['model']
    calendar = available_sessions(data_root, dt.date(walk['test_end'].year+1, 1, 31))
    windows = annual_windows(fits=plan, sessions=calendar, start=walk['test_start'], end=walk['test_end'])
    sources = replacement_statistics_sources(repair)
    sources.update({r['factor']: [Path(r['batch'])/'evaluation/statistics'] for r in spec['candidates']})
    predictions = pl.read_parquet(original/'monthly_predictions.parquet')
    folder = output/'predictions'; folder.mkdir(exist_ok=True)
    parts, records = [], []
    for annual in windows:
        year, cutoff = annual['test_year'], annual['cutoff']
        factors = [repair['replacements'].get(name, name) for name in annual['source_factors']]
        year_file = folder/f'year_{year}.parquet'; fit_file = folder/f'fit_{year}.json'
        if year_file.exists() and fit_file.exists():
            parts.append(pl.read_parquet(year_file)); records.append(json.loads(fit_file.read_text()))
            continue
        if factors == controls[year]['factors']:
            part = predictions.filter(pl.col('test_year') == year)
            record = {**controls[year], 'reused_control': True}
            if (original/f'lightgbm_{year}.txt').exists():
                shutil.copyfile(original/f'lightgbm_{year}.txt', folder/f'lightgbm_{year}.txt')
        elif not factors:
            part = predictions.head(0)
            record = {'test_year': year, 'factors': [], 'prediction_rows': 0, 'reason': 'no_admitted_factors'}
        else:
            coverage = []
            features = common_features(statistics=stats, factors=factors, variant=model['selection']['variant'],
                start=settings['training_start'], end=annual['end'], minimum_symbols=settings['minimum_signal_stocks'],
                statistics_sources=sources, missing_policy=settings['missing_features'],
                maximum_missing_fraction=settings['maximum_missing_fraction'], coverage=coverage)
            train = training_panel(features=features, statistics=stats, cutoff=cutoff,
                                   minimum_symbols=settings['minimum_signal_stocks'])
            if train['trade_date'].n_unique() < settings['minimum_training_months']:
                part = predictions.head(0)
                record = {'test_year': year, 'factors': factors, 'prediction_rows': 0,
                          'reason': 'insufficient_complete_training_history'}
            else:
                regressor = LGBMRegressor(**model['models']['lightgbm'])
                regressor.fit(train.select(factors).to_numpy(), train['label_rebalance'].to_numpy())
                future = features.filter(pl.col('trade_date') >= cutoff)
                values = regressor.booster_.predict(future.select(factors).to_numpy()) if future.height else []
                part = future.select('symbol', 'trade_date').with_columns(pl.Series('lightgbm', values, dtype=pl.Float64),
                                                                        pl.lit(year).alias('test_year'))
                regressor.booster_.save_model(str(folder/f'lightgbm_{year}.txt'))
                record = {'test_year': year, 'factors': factors, 'refit_close': str(cutoff),
                    'last_known_exit': str(train['exit_date_rebalance'].max()), 'training_rows': train.height,
                    'training_months': train['trade_date'].n_unique(), 'prediction_rows': part.height,
                    'reused_control': False}
            pl.from_dicts(coverage).write_parquet(folder/f'coverage_{year}.parquet')
        part.write_parquet(year_file); write_json(fit_file, record)
        parts.append(part); records.append(record)
        write_json(output/'prediction_progress.json', {'completed_years': records})
    combined = pl.concat(parts, how='vertical_relaxed')
    if combined.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Annual prediction windows overlap')
    combined.write_parquet(folder/'monthly_predictions.parquet')
    for name in ('model.toml', 'battery.toml'):
        shutil.copyfile(original/name, folder/name)
    write_json(folder/'summary.json', {'annual_fits': records, 'prediction_rows': combined.height,
        'source_selection': str(output/'selection'), 'factor_statistics_sources': {k: [str(p) for p in v] for k, v in sources.items()},
        'evidence': spec['evidence'], 'configuration_note': 'Source model settings retained; actual extended fit factors and sources are recorded here.'})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--stage', choices=['freeze', 'selection', 'predict', 'replay'], required=True)
    parser.add_argument('--reuse-selection-from', type=Path)
    args = parser.parse_args()
    if args.stage == 'freeze':
        freeze(args.config, args.output)
        if args.reuse_selection_from:
            reuse_selection(args.output, args.reuse_selection_from)
        return
    spec = verify(args.output)
    if args.stage == 'selection':
        from quant.research.admitted_model_pair_selection import select
        select(spec, args.output, data_root=args.data_root)
    elif args.stage == 'predict':
        predict(spec, args.output, data_root=args.data_root)
    else:
        from quant.research.admitted_model_pair_replay import run
        run(spec, args.output, data_root=args.data_root)


if __name__ == '__main__':
    main()
