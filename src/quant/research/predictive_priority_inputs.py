"""Freeze real training inputs for the registered predictive-priority search."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import tomllib
from pathlib import Path

import polars as pl

from quant.data.cross_stock_sampling import stock_groups
from quant.data.nightly_genetic_inputs import admitted_controls, latest_month_end, read_training_sample
from quant.factors.library import load_library
from quant.research.gp_predictive_priority import MechanismManifest, MechanismTerminal, SelectionRules


def digest(path: Path) -> str:
    before = path.stat()
    with path.open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'Input changed during hashing: {path}')
    return value


def dump(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp.json')
    temporary.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def recipe_contract(recipe: dict) -> dict:
    operational = {'stage', 'enqueue', 'prepared_inputs', 'mechanism_manifest_file'}
    return json.loads(json.dumps({k: v for k, v in recipe.items() if k not in operational}, default=str))


def manifest_files(path: Path) -> list[Path]:
    document = json.loads(path.read_text(encoding='utf-8'))
    files = [path]
    for shard in document.get('source_shards', []):
        name = shard['path']
        if Path(name).name != name or not name.startswith('sources_') or not name.endswith('.json'):
            raise ValueError('Invalid mechanism source shard name')
        source = path.parent / name
        if digest(source) != shard['sha256']:
            raise ValueError('Mechanism source shard changed')
        files.append(source)
    return files


def validate_manifest(manifest: dict, mapping: dict[str, str], *, source_files: bool) -> MechanismManifest:
    frozen = MechanismManifest(tuple(MechanismTerminal(**row) for row in manifest['terminals']))
    if frozen.sha256 != manifest['manifest_sha256']:
        raise ValueError('Mechanism manifest checksum differs')
    for terminal in frozen.terminals:
        if terminal.terminal_id not in mapping:
            raise ValueError(f'Missing mechanism terminal: {terminal.terminal_id}')
        source = manifest['terminal_sources'][terminal.terminal_id]
        if mapping[terminal.terminal_id] != source['expression']:
            raise ValueError('Mechanism expression differs from the frozen library')
        if source_files:
            for partition in source['partitions']:
                if partition.get('missing') or digest(Path(partition['path'])) != partition['sha256']:
                    raise ValueError(f'Frozen mechanism partition unavailable or changed: {partition["path"]}')
    return frozen


def validate_training(panel: pl.DataFrame, labels: pl.DataFrame, recipe: dict,
                      control_ids: list[str]) -> dict:
    end = recipe['training_end']
    if isinstance(end, str):
        end = dt.date.fromisoformat(end)
    if (labels['label_exit_date'].null_count() or labels['trade_date'].null_count()
            or panel['trade_date'].null_count()):
        raise ValueError('Training dates must be explicit')
    if (labels.is_empty() or panel.is_empty() or labels['trade_date'].max() > end
            or labels['label_exit_date'].max() > end or panel['trade_date'].max() > end):
        raise ValueError('Training observations exceed the frozen training end')
    if labels['trade_date'].n_unique() != recipe['training_months']:
        raise ValueError('Training sample lacks the registered number of months')
    keys = ['symbol', 'trade_date']
    if any(frame.select(pl.struct(keys).is_duplicated().any()).item() for frame in (panel, labels)):
        raise ValueError('Duplicate training keys')
    assignments = stock_groups(labels['symbol'].unique().to_list(), groups=recipe['sample_groups'],
                               per_group=recipe['symbols_per_group'], seed=recipe['sample_seed'])
    if len(assignments) != recipe['sample_groups'] * recipe['symbols_per_group']:
        raise ValueError('Training sample lacks registered stock groups')
    if not control_ids or set(control_ids) - set(panel.columns):
        raise ValueError('Frozen admitted controls are missing')
    return {'training_end': str(end), 'first_signal': str(labels['trade_date'].min()),
            'last_signal': str(labels['trade_date'].max()), 'last_label_exit': str(labels['label_exit_date'].max()),
            'sample_symbols': labels['symbol'].n_unique(), 'sample_months': labels['trade_date'].n_unique(),
            'daily_rows': panel.height, 'monthly_rows': labels.height, 'stock_groups': assignments,
            'control_ids': control_ids, 'historical_validation': 'development_only_all_three_groups_train'}


def _load_prepared(output: Path, expected: dict) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    receipt = json.loads((output / 'prepared_inputs.json').read_text(encoding='utf-8'))
    if receipt['contract'] != expected:
        raise ValueError('Prepared predictive inputs differ from the frozen request')
    required = {'daily_sample.parquet', 'monthly_sample.parquet', 'mechanism_manifest.json',
                'terminal_mapping.json', 'frozen_controls.json'}
    required.update(p.name for p in manifest_files(output / 'mechanism_manifest.json')[1:])
    for name, checksum in receipt['files'].items():
        if name not in required:
            raise ValueError('Unknown prepared input file')
        if digest(output / name) != checksum:
            raise ValueError(f'Prepared predictive input changed: {name}')
    if set(receipt['files']) != required:
        raise ValueError('Incomplete prepared input receipt')
    return pl.read_parquet(output / 'daily_sample.parquet'), pl.read_parquet(output / 'monthly_sample.parquet'), receipt


def prepare_training(settings: dict, output: Path) -> tuple[pl.DataFrame, pl.DataFrame, dict, dict]:
    """Read outcomes only through training_end; resume saved data without source drift."""
    recipe = dict(settings['predictive_priority'])
    if isinstance(recipe['training_end'], str):
        recipe['training_end'] = dt.date.fromisoformat(recipe['training_end'])
    SelectionRules.from_config(recipe)
    manifest_path = Path(settings['predictive_priority_manifest'])
    from quant.research.gp_mechanism_inputs import load_mechanism_manifest, read_mechanism_document
    manifest = read_mechanism_document(manifest_path)
    load_mechanism_manifest(manifest_path, verify_sources=False, library=Path(settings['library']))
    definitions = load_library(Path(settings['library']))
    available_mapping = {f'gp_{d.id}': d.expr for d in definitions}
    donor = Path(recipe['prepared_inputs']) if recipe.get('prepared_inputs') else None
    local_receipt = output / 'prepared_inputs.json'
    source = output if local_receipt.exists() else donor
    if source and (source / 'prepared_inputs.json').is_file():
        previous = json.loads((source / 'prepared_inputs.json').read_text(encoding='utf-8'))
        mapping = previous['contract']['mapping']
        if any(available_mapping.get(name) != expression for name, expression in mapping.items()):
            raise ValueError('Frozen predictive terminal definition changed or disappeared')
    else:
        mapping = available_mapping
    mechanism = validate_manifest(manifest, mapping, source_files=False)
    contract = {'recipe': recipe_contract(recipe), 'manifest_sha256': digest(manifest_path),
                'mechanism_sha256': mechanism.sha256, 'mapping': mapping,
                'as_of': str(settings['as_of']), 'reference_statistics': str(settings['reference_statistics']),
                'reference_scorecard': str(settings['reference_scorecard'])}
    output.mkdir(parents=True, exist_ok=True)
    if source and (source / 'prepared_inputs.json').is_file():
        panel, labels, receipt = _load_prepared(source, contract)
        if source.resolve() != output.resolve():
            for name in receipt['files']:
                target = output / name
                if target.exists() and digest(target) != receipt['files'][name]:
                    raise ValueError('Existing partial input differs from prepared input')
                if not target.exists():
                    temporary = target.with_suffix('.partial')
                    shutil.copyfile(source / name, temporary)
                    temporary.replace(target)
            dump(local_receipt, receipt)
        control_ids = json.loads((output / 'frozen_controls.json').read_text())['ids']
    else:
        validate_manifest(manifest, mapping, source_files=True)
        refresh = output / 'refresh_config.toml'
        refresh.write_bytes(Path(settings['refresh_config']).read_bytes())
        panel, labels = read_training_sample(data_root=Path(settings['data_root']), refresh_config=refresh,
            statistics=[Path(p) for p in settings['statistics']], factors=[name[3:] for name in mapping],
            end=recipe['training_end'], symbols=recipe['sample_groups'] * recipe['symbols_per_group'],
            months=recipe['training_months'], cross_stock=recipe)
        reference = Path(settings['reference_statistics'])
        scorecard_path = Path(settings['reference_scorecard'])
        scorecard_hash = digest(scorecard_path)
        scorecard = pl.read_parquet(scorecard_path)
        control_rows = scorecard.filter(pl.col('factor_admitted')).select('factor').unique()['factor'].to_list()
        control_sources = [scorecard_path, *[reference / 'factors' / factor / name
                          for factor in control_rows for name in ('statistics.json', 'monthly_scores.parquet')]]
        control_hashes = {str(p): digest(p) for p in control_sources}
        controls, control_ids = admitted_controls(reference, scorecard)
        controls = controls.filter(pl.col('trade_date').is_in(labels['trade_date'].unique().implode()))
        panel = panel.join(controls, on=['symbol', 'trade_date'], how='left', validate='1:1')
        summary = validate_training(panel, labels, recipe, control_ids)
        validate_manifest(manifest, mapping, source_files=True)
        if digest(scorecard_path) != scorecard_hash or any(digest(Path(p)) != v for p, v in control_hashes.items()):
            raise ValueError('Frozen control inputs changed during preparation')
        for name, frame in (('daily_sample.parquet', panel), ('monthly_sample.parquet', labels)):
            temporary = output / (name + '.partial')
            frame.write_parquet(temporary)
            temporary.replace(output / name)
        (output / 'mechanism_manifest.json').write_bytes(manifest_path.read_bytes())
        shards = manifest_files(manifest_path)[1:]
        for source_path in shards:
            shutil.copyfile(source_path, output / source_path.name)
        dump(output / 'terminal_mapping.json', mapping)
        dump(output / 'frozen_controls.json', {'ids': control_ids, 'sources': control_hashes,
             'correlation': 'mean_absolute_monthly_spearman_then_max_control'})
        names = ('daily_sample.parquet', 'monthly_sample.parquet', 'mechanism_manifest.json',
                 'terminal_mapping.json', 'frozen_controls.json', *[p.name for p in shards])
        receipt = {'contract': contract, 'files': {name: digest(output / name) for name in names},
                   'summary': summary, 'refresh_config_sha256': digest(refresh), 'activated': False}
        dump(local_receipt, receipt)
    summary = validate_training(panel, labels, recipe, control_ids)
    dump(output / 'input_summary.json', {**summary, 'mechanism_terminal_count': len(mechanism.terminals),
                                      'mechanism_sha256': mechanism.sha256, 'terminal_count': len(mapping)})
    search_settings = {key: recipe[key] for key in ('seed', 'population_size', 'generations', 'max_depth')}
    search_settings.update(predictive_priority=recipe, mechanism_manifest={'terminals': manifest['terminals']},
                           frozen_control_ids=control_ids)
    return panel, labels, mapping, search_settings


def run_predictive(settings: dict, output: Path) -> dict:
    from quant.research.predictive_priority_search import search_predictive
    recipe = settings['predictive_priority']
    if recipe.get('stage') != 'scheduled_one_shot' or not recipe.get('enqueue') or recipe.get('auto_trade'):
        raise ValueError('Predictive search is not activated in its frozen recipe')
    panel, labels, mapping, search_settings = prepare_training(settings, output)
    winners = search_predictive(panel, labels, mapping, search_settings, output, family='predictive_priority_v2')
    return {'candidates': len(winners), 'terminal_count': len(mapping), 'family': 'predictive_priority_v2',
            'sample_symbols': labels['symbol'].n_unique(), 'sample_months': labels['trade_date'].n_unique(),
            'search_objective': recipe['version'], 'historical_validation': 'development_only'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/nightly.toml'))
    parser.add_argument('--recipe', type=Path, default=Path('configs/research/gp_predictive_priority_v2.toml'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    settings = tomllib.loads(args.config.read_text(encoding='utf-8'))
    settings['predictive_priority'] = tomllib.loads(args.recipe.read_text(encoding='utf-8'))
    settings['predictive_priority_manifest'] = str(args.manifest)
    settings['as_of'] = latest_month_end(Path(settings['data_root']), dt.date.today())
    panel, labels, mapping, _ = prepare_training(settings, args.output)
    print(json.dumps({'output': str(args.output), 'daily_rows': panel.height, 'monthly_rows': labels.height,
                      'terminal_count': len(mapping), 'search_started': False}))


if __name__ == '__main__':
    main()
