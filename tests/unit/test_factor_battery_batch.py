"""Run metadata must remain valid when a monthly config already contains it."""
import datetime as dt
import json
import tomllib

import pytest

from quant.research import factor_battery_batch as batch
from quant.research.factor_battery_screen import run_screen


@pytest.mark.parametrize('run_metadata', ['', '\n[run]\nas_of=2026-09-30\n',
    '\n[run]\nas_of=2026-08-31\nselected="previous"\nnote="retain"\n'])
def test_statistics_snapshot_with_existing_metadata_can_be_screened(tmp_path, monkeypatch, run_metadata):
    text = '''start=2026-01-01
variants=["raw", "size_industry_neutral"]
primary_variant="size_industry_neutral"
[admission]
minimum_months=96
minimum_absolute_newey_west_t=3.0
minimum_directional_icir=0.3
minimum_yearly_positive_fraction=0.7
minimum_long_short_sharpe=0.5
[multiple_testing]
q=0.05
admission_requires_fdr=false
''' + run_metadata
    config = tmp_path / 'input.toml'
    config.write_text(text)
    original = config.read_bytes()
    library = tmp_path / 'library'
    library.mkdir()
    (library / 'sample.toml').write_text(
        'id="sample"\nexpr="adj_close"\nfamily="fixture"\ndirection=1\nsource_ref="fixture"\n')
    cutoff = dt.date(2026, 9, 30)
    monkeypatch.setattr(batch, 'available_sessions', lambda *_: [cutoff, dt.date(2026, 10, 8)])
    monkeypatch.setattr(batch, 'prepare_inputs', lambda **_: [2026])
    def factor(*_):
        return {'definition': {'id': 'sample', 'family': 'fixture', 'direction': 1},
            'seconds': 0., 'statistics': [dict(variant=v, months=120, newey_west_t=4.,
                icir=.5, yearly_positive_fraction=.8, p_value=.001,
                group_statistics={'long_short_sharpe': 1.}) for v in ['raw', 'size_industry_neutral']]}
    monkeypatch.setattr(batch, '_factor_worker', factor)
    output = tmp_path / 'statistics'
    batch.run_statistics(data_root=tmp_path / 'data', config=config, library=library,
                         as_of=cutoff, output=output, workers=1)
    screened = run_screen(statistics=output, output=tmp_path / 'screen', library=library)
    assert screened['tests'] == 2 and screened['statistical_pass_rows'] == 2
    snapshot = tomllib.loads((output / 'battery.toml').read_text())
    source = tomllib.loads(text)
    assert snapshot.pop('run') == {**source.pop('run', {}), 'as_of': cutoff, 'selected': 'all'}
    assert snapshot == source and config.read_bytes() == original
    if not run_metadata:
        # Existing frozen base-config runs must keep their byte identity on resume.
        expected = original + f'\n[run]\nas_of = {cutoff}\nselected = {json.dumps("all")}\n'.encode()
        assert (output / 'battery.toml').read_bytes() == expected
