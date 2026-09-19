"""Queue provenance survives real admission record and published-definition writes."""
import datetime as dt
import json
import tomllib

import polars as pl
import pytest

from quant.data import nightly_genetic_inputs as inputs
from quant.research import nightly_steps as steps


BATTERY_REF = (
    'registered_battery:configs/research/pressure_reversal_v1.toml; role=candidate; '
    'evidence=artifacts/research/pressure_reversal_v1/equivalence/summary.json'
)


@pytest.mark.parametrize(('identifier', 'source_ref', 'expected'), [
    ('llm_dsl_abc', 'weekly generation', 'weekly_llm'),
    ('ngp_abc', 'frozen old GP', 'nightly_gp'),
    ('gp_abc', 'frozen old GP', 'nightly_gp'),
    ('pressure_candidate', BATTERY_REF, 'registered_battery'),
    ('pressure_control', BATTERY_REF.replace('role=candidate', 'role=control'),
     'registered_battery'),
    ('manual_factor', 'manual research', 'factor_queue'),
    ('xngp_abc', 'nightly_gp', 'factor_queue'),
    ('manual_factor', 'reference mentions registered_battery:later', 'factor_queue'),
    ('llm_dsl_abc', BATTERY_REF, 'weekly_llm'),
    ('ngp_abc', BATTERY_REF, 'nightly_gp'),
])
def test_explicit_prefixes_and_provenance_classify_all_four_sources(identifier, source_ref, expected):
    assert steps.candidate_source(identifier, source_ref) == expected


def test_admit_persists_helper_source_for_every_origin(tmp_path, monkeypatch):
    run, batch, library = tmp_path/'run', tmp_path/'batch', tmp_path/'library'
    for path in [run/'N3', run/'N4', batch/'library', library,
                 tmp_path/'reference', tmp_path/'queue'/'processing']:
        path.mkdir(parents=True)
    day = dt.date(2026, 8, 31)
    definitions = {
        'llm_dsl_fixture': ('weekly generation', 'weekly_llm'),
        'ngp_fixture': ('frozen GP run', 'nightly_gp'),
        'gp_fixture': ('frozen GP run', 'nightly_gp'),
        'pressure_candidate': (BATTERY_REF, 'registered_battery'),
        'manual_candidate': ('manual experiment', 'factor_queue'),
    }

    def definition_text(identifier, source_ref):
        return (f'id="{identifier}"\nexpr="adj_close"\nfamily="fixture"\ndirection=1\n'
                f'source_ref={json.dumps(source_ref)}\n')

    (library/'reference.toml').write_text(definition_text('reference', 'fixture'), encoding='utf-8')
    card = batch/'scorecard.parquet'
    pl.DataFrame({'factor': list(definitions), 'variant': ['raw']*len(definitions),
                  'factor_admitted': [True]*len(definitions)}).write_parquet(card)
    (run/'N3'/'result.json').write_text(json.dumps(
        {'evaluated': len(definitions), 'batch': str(batch), 'scorecard': str(card)}))
    (tmp_path/'reference'/'battery.toml').write_text('[run]\nas_of=2026-08-31\n')
    keys = pl.DataFrame({'symbol': ['x'], 'trade_date': [day]})
    for identifier, (source_ref, _) in definitions.items():
        folder = batch/'evaluation'/'statistics'/'factors'/identifier
        folder.mkdir(parents=True)
        keys.with_columns(pl.lit(1.).alias('raw')).write_parquet(folder/'monthly_scores.parquet')
        (batch/'library'/f'{identifier}.toml').write_text(
            definition_text(identifier, source_ref), encoding='utf-8')
    monkeypatch.setattr(inputs, 'admitted_controls', lambda *args: (keys, ['reference']))
    monkeypatch.setattr(inputs, 'read_raw_monthly', lambda **kwargs:
                        keys.with_columns(pl.lit(day).alias('label_exit_date')))
    monkeypatch.setattr(steps, 'incremental_statistics', lambda *args:
                        {'months': 100, 'newey_west_t': 3., 'complete_control_fraction': 1.})
    monkeypatch.setattr(steps, 'maximum_correlation', lambda *args: .2)
    actual_helper = steps.candidate_source
    calls = []

    def record_source(identifier, source_ref):
        calls.append((identifier, source_ref))
        return actual_helper(identifier, source_ref)

    monkeypatch.setattr(steps, 'candidate_source', record_source)
    settings = {'library': str(library), 'reference_scorecard': str(card),
                'reference_statistics': str(tmp_path/'reference'), 'as_of': day,
                'history_start': dt.date(2010, 1, 1), 'data_root': str(tmp_path/'data'),
                'rejected_root': str(tmp_path/'rejected'), 'queue': str(tmp_path/'queue')}
    result = steps.admit(settings, run)
    expected = {identifier: source for identifier, (_, source) in definitions.items()}
    assert dict(calls) == {identifier: ref for identifier, (ref, _) in definitions.items()}
    assert result['admitted'] == len(definitions) and result['rejected'] == 0
    for path in (run/'N4'/'admission_scorecard.parquet', batch/'admission_scorecard.parquet'):
        assert dict(pl.read_parquet(path).select('factor', 'source').iter_rows()) == expected
    progress = json.loads((run/'N4'/'admission_progress.json').read_text())
    assert {row['factor']: row['source'] for row in progress['rows']} == expected
    for identifier, source in expected.items():
        definition = tomllib.loads((library/'auto'/f'{identifier}.toml').read_text())
        assert definition['source'] == source
        assert definition['source_ref'] == definitions[identifier][0]
