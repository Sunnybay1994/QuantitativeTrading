import datetime as dt
import json
from types import SimpleNamespace

import polars as pl
import pytest

from quant.data import nightly_genetic_inputs as inputs
from quant.research import nightly_steps as steps


def test_admission_resumes_completed_candidates_with_frozen_references(tmp_path, monkeypatch):
    run, batch, library = tmp_path/'run', tmp_path/'batch', tmp_path/'library'
    for path in [run/'N3', run/'N4', batch/'library', library,
                 tmp_path/'reference', tmp_path/'queue'/'processing']:
        path.mkdir(parents=True)
    day = dt.date(2026, 8, 31)
    card = batch/'scorecard.parquet'
    pl.DataFrame({'factor':['a','b'], 'variant':['raw','raw'],
                  'factor_admitted':[True,False]}).write_parquet(card)
    (run/'N3'/'result.json').write_text(json.dumps({'evaluated':2,'batch':str(batch),'scorecard':str(card)}))
    (tmp_path/'reference'/'battery.toml').write_text('[run]\nas_of=2026-08-31\n')
    keys = pl.DataFrame({'symbol':['x'], 'trade_date':[day]})
    for name in ['a','b']:
        folder = batch/'evaluation'/'statistics'/'factors'/name
        folder.mkdir(parents=True)
        keys.with_columns(pl.lit(1.).alias('raw')).write_parquet(folder/'monthly_scores.parquet')
        (batch/'library'/f'{name}.toml').write_text(f'id="{name}"\n')
    refs = ['r']
    monkeypatch.setattr(steps, 'load_library', lambda path: [SimpleNamespace(id=x)
        for x in (['a','b'] if path == batch/'library' else refs)])
    monkeypatch.setattr(inputs, 'admitted_controls', lambda *args: (keys, []))
    seen_refs = []

    def panel(**kwargs):
        seen_refs.append(list(kwargs['factors']))
        return keys.with_columns(pl.lit(day).alias('label_exit_date'))

    monkeypatch.setattr(inputs, 'read_raw_monthly', panel)
    calls = []

    def incremental(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('interruption on second candidate')
        return {'months':100, 'newey_west_t':3., 'complete_control_fraction':1.}

    monkeypatch.setattr(steps, 'incremental_statistics', incremental)
    monkeypatch.setattr(steps, 'maximum_correlation', lambda *args: .2)
    settings = {'library':str(library), 'reference_scorecard':str(card),
        'reference_statistics':str(tmp_path/'reference'), 'as_of':day,
        'history_start':dt.date(2010,1,1), 'data_root':str(tmp_path/'data'),
        'rejected_root':str(tmp_path/'rejected'), 'queue':str(tmp_path/'queue')}
    with pytest.raises(RuntimeError, match='interruption'):
        steps.admit(settings, run)
    saved = json.loads((run/'N4'/'admission_progress.json').read_text())
    assert [row['factor'] for row in saved['rows']] == ['a']
    assert (library/'auto'/'a.toml').exists()
    refs.append('new_reference')
    result = steps.admit(settings, run)
    assert len(calls) == 3  # First candidate is not evaluated again.
    assert seen_refs == [['r'], ['r']]
    assert result['admitted'] == 1 and result['rejected'] == 1
    assert pl.read_parquet(run/'N4'/'admission_scorecard.parquet')['factor'].to_list() == ['a','b']
