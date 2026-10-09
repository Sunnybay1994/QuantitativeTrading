import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.expressions import required_history
from quant.factors.statement_event_reaction import NAMES
from tests.unit.test_statement_event_reaction import inputs


def test_shared_compute_attachment_prefix_year_and_warmup(monkeypatch):
    from quant.factors import compute
    events, bars, market, sessions = inputs()
    monkeypatch.setattr(compute, 'available_sessions', lambda root, end: tuple(d for d in sessions if d <= end))
    monkeypatch.setattr(compute, 'read_statement_events', lambda root, config, start, end:
        events.filter(pl.col('announcement_date').is_between(start, end)))
    monkeypatch.setattr(compute, 'read_statement_market', lambda root, config, start, end:
        market.filter(pl.col('trade_date').is_between(start, end)))
    def attach(frame):
        return compute.attach_expression_inputs(frame, frame, expressions=NAMES, data_root=Path('unused'),
            refresh_config=Path('unused'), read_start=frame['trade_date'].min(),
            read_end=frame['trade_date'].max(), sessions=sessions)
    full = attach(bars.filter(pl.col('trade_date') <= dt.date(2020, 7, 1)))
    prefix = attach(bars.filter(pl.col('trade_date') <= dt.date(2020, 1, 31)))
    assert_frame_equal(prefix, full.filter(pl.col('trade_date') <= dt.date(2020, 1, 31)))
    complete = attach(bars.filter(pl.col('trade_date') <= dt.date(2020, 2, 3)))
    assert_frame_equal(complete, full.filter(pl.col('trade_date') <= dt.date(2020, 2, 3)))
    assert complete[NAMES[0]][-1] is not None
    for name in NAMES:
        assert required_history(name) == 200
        assert required_history(f'delay({name},10)') == 210


def test_statement_market_requires_pinned_total_return_and_keeps_precoverage_missing(tmp_path):
    from quant.data.statement_event_inputs import read_statement_market
    folder = tmp_path/'clean/index_benchmarks/pinned'
    folder.mkdir(parents=True)
    summary = {'start': '2020-01-01', 'end': '2020-01-31',
        'series': [{'index_code': 'H00985.CSI', 'return_type': 'total_return'}]}
    (folder/'summary.json').write_text(json.dumps(summary))
    pl.DataFrame({'index_code': ['H00985.CSI'], 'trade_date': [dt.date(2020, 1, 2)],
        'index_level': [100.]}).write_parquet(folder/'data.parquet')
    config = tmp_path/'refresh.toml'
    config.write_text('statement_event_index_version="pinned"\n')
    assert read_statement_market(tmp_path, config, dt.date(2010, 1, 1), dt.date(2011, 1, 1)).is_empty()
    assert read_statement_market(tmp_path, config, dt.date(2010, 1, 1), dt.date(2020, 1, 2)).height == 1
    with pytest.raises(ValueError, match='coverage'):
        read_statement_market(tmp_path, config, dt.date(2020, 1, 1), dt.date(2020, 2, 1))
    summary['series'][0]['return_type'] = 'price'
    (folder/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='total_return'):
        read_statement_market(tmp_path, config, dt.date(2010, 1, 1), dt.date(2011, 1, 1))


def test_original_n4_requires_all_registered_controls_and_96_months():
    from quant.research.statement_event_controls import CONTROLS, check_statement_controls
    spec = tomllib.loads(Path('configs/research/statement_event_family_v1.toml').read_text())
    assert list(CONTROLS) == spec['additional_controls']
    assert not check_statement_controls(pl.DataFrame({'candidate': [1.]}), [],
        lambda *a: pytest.fail('Missing controls must not run regression'))['passed']
    panel = pl.DataFrame({n: [1.] for n in (*CONTROLS, 'candidate', 'admitted')})
    def evaluate(frame, candidate, names, direction):
        assert names == ['admitted', *CONTROLS] and direction == 1 and candidate == 'candidate'
        return {'months': 96, 'newey_west_t': 2.5}
    assert check_statement_controls(panel, ['admitted'], evaluate)['passed']
    assert not check_statement_controls(panel, [], lambda *a: {'months': 95, 'newey_west_t': 20.})['passed']


def test_monthly_binding_keeps_both_explicit_index_versions_together(tmp_path):
    from quant.data.nightly_month_inputs import _bind_price_delay_index
    config = tmp_path/'refresh.toml'
    config.write_text('price_delay_index_version="old"\nstatement_event_index_version="old"\n')
    measurement = tmp_path/'measurement.toml'
    measurement.write_text('index_version="new"\n')
    settings = {'refresh_config': str(config), 'measurement_config': str(measurement)}
    result = _bind_price_delay_index(settings, tmp_path)
    saved = tomllib.loads(Path(result['refresh_config']).read_text())
    assert saved['price_delay_index_version'] == saved['statement_event_index_version'] == 'new'
    assert tomllib.loads(config.read_text())['statement_event_index_version'] == 'old'


def test_n4_dispatch_cannot_admit_when_fixed_family_controls_fail(tmp_path, monkeypatch):
    from quant.research import nightly_steps as steps, statement_event_controls as family
    from quant.data import nightly_genetic_inputs as data
    run, batch, library = tmp_path/'run', tmp_path/'batch', tmp_path/'library'
    name, day = NAMES[0], dt.date(2026, 8, 31)
    for path in (run/'N3', run/'N4', batch/'library', library, tmp_path/'reference', tmp_path/'queue/processing'):
        path.mkdir(parents=True)
    text = f'id="{name}"\nexpr="{name}"\ndirection=1\nfamily="statement_event_reaction_v1"\nsource_ref="registered_battery:test"\n'
    (batch/'library'/f'{name}.toml').write_text(text)
    (library/'ref.toml').write_text('id="ref"\nexpr="close"\ndirection=1\nfamily="other"\nsource_ref="test"\n')
    card = batch/'scorecard.parquet'
    pl.DataFrame({'factor': [name], 'variant': ['raw'], 'factor_admitted': [True]}).write_parquet(card)
    (run/'N3/result.json').write_text(json.dumps({'evaluated': 1, 'batch': str(batch), 'scorecard': str(card)}))
    (tmp_path/'reference/battery.toml').write_text('[run]\nas_of=2026-08-31\n')
    keys = pl.DataFrame({'symbol': ['x'], 'trade_date': [day]})
    folder = batch/'evaluation/statistics/factors'/name
    folder.mkdir(parents=True)
    keys.with_columns(pl.lit(1.).alias('raw'), pl.lit(9.).alias('size_industry_neutral')).write_parquet(folder/'monthly_scores.parquet')
    monkeypatch.setattr(data, 'admitted_controls', lambda *a: (keys, []))
    monkeypatch.setattr(data, 'read_raw_monthly', lambda **kw: keys.with_columns(pl.lit(day).alias('label_exit_date')))
    monkeypatch.setattr(steps, 'incremental_statistics', lambda *a: {'months': 120, 'newey_west_t': 4., 'complete_control_fraction': 1.})
    monkeypatch.setattr(steps, 'maximum_correlation', lambda *a: .1)
    seen = []
    def reject(frame, admitted, evaluate):
        seen.append(frame['candidate'].item())
        return {'passed': False, 'reason': 'fixed_controls_failed'}
    monkeypatch.setattr(family, 'check_statement_controls', reject)
    settings = {'library': str(library), 'reference_scorecard': str(card), 'reference_statistics': str(tmp_path/'reference'),
        'as_of': day, 'history_start': dt.date(2010, 1, 1), 'data_root': str(tmp_path/'data'),
        'rejected_root': str(tmp_path/'rejected'), 'queue': str(tmp_path/'queue')}
    result = steps.admit(settings, run)
    assert seen == [9.] and result['admitted'] == 0 and result['rejected'] == 1
    assert not (library/'auto'/f'{name}.toml').exists()
