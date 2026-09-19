import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.research import predictive_priority_inputs as module
from quant.research.gp_predictive_priority import MechanismManifest, MechanismTerminal
from quant.research.gp_mechanism_inputs import file_record, input_version
from quant.research.nightly_search_recipe import freeze_recipe


def recipe():
    spec = tomllib.loads(Path('configs/research/gp_predictive_priority_v2.toml').read_text())
    spec.pop('prepared_inputs', None)
    return {**spec, 'training_end': dt.date(2020, 3, 1), 'training_months': 2, 'symbols_per_group': 100}


def frames():
    labels = pl.DataFrame([{'symbol': symbol, 'trade_date': day, 'label_exit_date': day + dt.timedelta(days=1), 'label': .01}
                          for symbol in (f's{i:03}' for i in range(300))
                          for day in (dt.date(2020, 1, 30), dt.date(2020, 2, 27))])
    panel = labels.select('symbol', 'trade_date').with_columns(pl.lit(1.).alias('gp_financial'), pl.lit(2.).alias('control_f_raw'))
    return panel, labels


@pytest.mark.parametrize('field', ['signal', 'exit', 'panel'])
def test_training_rejects_future_observation_boundaries(field):
    panel, labels = frames()
    future = dt.date(2020, 3, 2)
    if field == 'signal':
        labels = labels.with_columns(pl.lit(future).alias('trade_date'))
    elif field == 'exit':
        labels = labels.with_columns(pl.lit(future).alias('label_exit_date'))
    else:
        panel = panel.with_columns(pl.lit(future).alias('trade_date'))
    with pytest.raises(ValueError, match='exceed'):
        module.validate_training(panel, labels, recipe(), ['control_f_raw'])


def test_training_requires_explicit_exit_months_and_controls():
    panel, labels = frames()
    with pytest.raises(ValueError, match='explicit'):
        module.validate_training(panel, labels.with_columns(pl.lit(None, dtype=pl.Date).alias('label_exit_date')),
                                 recipe(), ['control_f_raw'])
    with pytest.raises(ValueError, match='number of months'):
        module.validate_training(panel, labels.filter(pl.col('trade_date').dt.month() == 1), recipe(), ['control_f_raw'])
    with pytest.raises(ValueError, match='controls'):
        module.validate_training(panel, labels, recipe(), ['missing'])


def fixture(tmp_path):
    library = tmp_path / 'library'
    library.mkdir()
    (library / 'financial.toml').write_text('id="financial"\nexpr="amount"\nfamily="pit_financial"\ndirection=1\nsource_ref="fixture"\n')
    source = tmp_path / 'source.parquet'
    pl.DataFrame({'value': [1.]}).write_parquet(source)
    evidence = {'factor_id': 'financial', 'family': 'pit_financial', 'expression': 'amount', 'direction': 1,
                'partitions': [{**file_record(source), 'year': 2020}]}
    terminal = MechanismTerminal('gp_financial', 'financial', input_version(evidence), 'fixture announcement date rule')
    manifest = {'schema_version': 'gp_mechanism_inputs_v1', 'terminals': [vars(terminal)],
                'manifest_sha256': MechanismManifest((terminal,)).sha256,
                'terminal_sources': {'gp_financial': evidence}}
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    refresh = tmp_path / 'refresh.toml'
    refresh.write_text('snapshot="test"\n')
    reference = tmp_path / 'reference'
    folder = reference / 'factors' / 'f'
    folder.mkdir(parents=True)
    (folder / 'statistics.json').write_text('{}')
    pl.DataFrame({'value': [1.]}).write_parquet(folder / 'monthly_scores.parquet')
    scorecard = tmp_path / 'scorecard.parquet'
    pl.DataFrame({'factor': ['f'], 'factor_admitted': [True]}).write_parquet(scorecard)
    settings = {'predictive_priority': recipe(), 'predictive_priority_manifest': str(manifest_path),
                'library': str(library), 'data_root': str(tmp_path), 'refresh_config': str(refresh),
                'reference_statistics': str(reference), 'reference_scorecard': str(scorecard),
                'statistics': [str(reference)], 'as_of': dt.date(2020, 3, 31)}
    return settings, source


def test_prepare_resume_and_copy_preserve_frozen_inputs_after_live_source_changes(tmp_path, monkeypatch):
    settings, source = fixture(tmp_path)
    panel, labels = frames()
    calls = []

    def read(**kwargs):
        calls.append(kwargs)
        return panel.drop('control_f_raw'), labels

    monkeypatch.setattr(module, 'read_training_sample', read)
    monkeypatch.setattr(module, 'admitted_controls', lambda *a: (panel.select('symbol', 'trade_date', 'control_f_raw'), ['control_f_raw']))
    root = tmp_path / 'prepared'
    first = module.prepare_training(settings, root)
    assert len(calls) == 1 and first[3]['seed'] == recipe()['seed']
    assert first[3]['frozen_control_ids'] == ['control_f_raw']
    source.write_bytes(b'live source updated after freezing')
    resumed = module.prepare_training(settings, root)
    assert len(calls) == 1 and first[0].equals(resumed[0])
    settings['predictive_priority']['stage'] = 'scheduled_one_shot'
    settings['predictive_priority']['enqueue'] = True
    settings['predictive_priority']['prepared_inputs'] = str(root)
    copied = module.prepare_training(settings, tmp_path / 'scheduled')
    assert copied[0].equals(first[0]) and len(calls) == 1
    (root / 'daily_sample.parquet').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='Prepared predictive input changed'):
        module.prepare_training(settings, tmp_path / 'other')


def test_mechanism_changes_during_read_do_not_get_a_completion_receipt(tmp_path, monkeypatch):
    settings, source = fixture(tmp_path)
    panel, labels = frames()

    def read(**kwargs):
        source.write_bytes(b'changed during preparation')
        return panel.drop('control_f_raw'), labels

    monkeypatch.setattr(module, 'read_training_sample', read)
    monkeypatch.setattr(module, 'admitted_controls', lambda *a: (panel.select('symbol', 'trade_date', 'control_f_raw'), ['control_f_raw']))
    with pytest.raises(ValueError, match='partition unavailable or changed'):
        module.prepare_training(settings, tmp_path / 'prepared')
    assert not (tmp_path / 'prepared/prepared_inputs.json').exists()


def test_frozen_recipe_copied_once_and_respects_disabled_registration(tmp_path):
    settings, _ = fixture(tmp_path)
    original = Path('configs/research/gp_predictive_priority_v2.toml').read_text()
    original = '\n'.join(line for line in original.splitlines()
                         if not line.startswith(('mechanism_manifest_file =', 'prepared_inputs ='))) + '\n'
    # The fixture is independent of production activation state.
    original = original.replace('stage = "scheduled_one_shot"', 'stage = "preregistered_design"').replace('enqueue = true', 'enqueue = false')
    path = tmp_path / 'recipe.toml'
    path.write_text(original)
    source = f'one_shot_search_config={json.dumps(str(path))}\n'
    staging = tmp_path / 'staging'
    staging.mkdir()
    final = tmp_path / 'batch_000001/2026-09-19'
    with pytest.raises(ValueError, match='explicitly activated'):
        freeze_recipe(source, staging, final, [])
    active = original.replace('stage = "preregistered_design"', 'stage = "scheduled_one_shot"').replace('enqueue = false', 'enqueue = true')
    # Add a top-level field before any TOML table.
    active = 'mechanism_manifest_file=' + json.dumps(settings['predictive_priority_manifest']) + '\n' + active
    path.write_text(active)
    frozen = freeze_recipe(source, staging, final, [])
    assert tomllib.loads(frozen)['predictive_priority_manifest'] == str(final / 'predictive_manifest.json')
    final.mkdir(parents=True)
    (final / 'predictive_priority.toml').write_text(active)
    assert freeze_recipe(source, staging, tmp_path / 'batch_000002/2026-09-20', [final.parent]) == source
