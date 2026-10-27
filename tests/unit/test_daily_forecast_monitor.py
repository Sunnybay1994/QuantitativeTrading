import datetime as dt
import json
import shutil

import pytest

from quant.reporting import daily_forecast_monitor as monitor
from quant.research import score_model_forecasts
from tests.unit.test_model_forecast_scoring import DAY, EXIT, inputs


@pytest.fixture
def setup(tmp_path, monkeypatch):
    selection = tmp_path/'selection'
    selection.mkdir()
    (selection/'selection.json').write_text(json.dumps({'selected_method': 'lightgbm', 'forward_start': str(DAY)}))
    source = tmp_path/'source'
    source.mkdir()
    (source/'battery.toml').write_text('minimum_symbols=3\nminimum_paired_coverage=0.95\nmonthly_newey_west_lag=6\n[data]\nrefresh_config="fixture"')
    (selection/'config.toml').write_text('[research]\npredictions='+json.dumps(str(source)))
    forecasts = tmp_path/'forecasts'
    folder = forecasts/'a'
    folder.mkdir(parents=True)
    fixture = inputs()
    record = {**fixture['record'], 'source_selection': str(selection), 'auto_trade': False, 'method': 'lightgbm'}
    (folder/'summary.json').write_text(json.dumps(record))
    fixture['predictions'].write_parquet(folder/'predictions.parquet')
    config = tmp_path/'daily.toml'
    config.write_text('[forecast_monitor]\nauto_trade=false\nselection='+json.dumps(str(selection))
        +'\nroots=['+json.dumps(str(forecasts))+']\npatterns=["*/summary.json"]\n')
    monkeypatch.setattr(score_model_forecasts, 'read_forecast_labels', lambda **kwargs: (
        fixture['labels'] if kwargs['known_through'] >= EXIT else fixture['labels'].clear(), fixture['sessions']))
    return config, folder, tmp_path, record


def invoke(setup, cutoff=EXIT, name='out'):
    config, _, root, _ = setup
    return monitor.run(config=config, known_through=cutoff, output=root/name)


def test_pending_all_null_and_empty_labels_then_matures(setup):
    pending = invoke(setup, dt.date(2026, 2, 27))
    assert pending['status'] == 'pending' and pending['pending_records'] == 1
    assert pending['forward_scored_series_months'] == 0
    mature = invoke(setup, name='mature')
    assert mature['status'] == 'insufficient'
    assert mature['forward_scored_series_months'] == 1
    assert mature['series'][0]['historical_months'] == 0


@pytest.mark.parametrize('change', [{'rehearsal': True}, {'recorded_at': '2026-02-02T10:00:00+08:00'}])
def test_rehearsal_and_late_records_never_become_forward(setup, change):
    _, folder, _, record = setup
    (folder/'summary.json').write_text(json.dumps({**record, **change}))
    result = invoke(setup)
    assert result['forward_scored_series_months'] == 0
    assert result['series'][0]['historical_months'] == 1


def test_identical_late_copies_stay_one_unqualified_sample(setup):
    _, folder, _, record = setup
    other = folder.parent/'b'
    shutil.copytree(folder, other)
    (folder/'summary.json').write_text(json.dumps({**record, 'recorded_at': '2026-02-02T10:00:00+08:00'}))
    (other/'summary.json').write_text(json.dumps({**record, 'recorded_at': '2026-02-02T11:00:00+08:00'}))
    result = invoke(setup)
    assert not result['discovery']['conflicts']
    assert result['scoring']['records'] == 1 and len(result['discovery']['duplicates']) == 1
    assert result['forward_scored_series_months'] == 0
    assert result['series'][0]['historical_months'] == 1


def test_identical_duplicate_deduplicates_but_qualification_change_conflicts(setup):
    _, folder, _, record = setup
    other = folder.parent/'b'
    shutil.copytree(folder, other)
    result = invoke(setup)
    assert result['scoring']['records'] == 1 and len(result['discovery']['duplicates']) == 1
    (other/'summary.json').write_text(json.dumps({**record, 'rehearsal': True}))
    result = invoke(setup, name='conflict')
    assert result['status'] == 'conflict'
    assert not result['discovery']['forecasts']


@pytest.mark.parametrize('stamp,conflict', [
    ('2026-01-30T21:30:00+08:00', False),
    ('2026-01-30T14:30:00+08:00', True),
    ('2026-02-02T10:00:00+08:00', True),
])
def test_same_close_retry_preserves_timing_qualification(setup, stamp, conflict):
    _, folder, _, record = setup
    other = folder.parent/'b'
    shutil.copytree(folder, other)
    (other/'summary.json').write_text(json.dumps({**record, 'recorded_at': stamp}))
    result = invoke(setup)
    assert bool(result['discovery']['conflicts']) is conflict
    if not conflict:
        assert result['scoring']['records'] == 1
        assert len(result['discovery']['duplicates']) == 1


def test_empty_search_is_not_success_and_bad_prediction_is_failure(setup):
    _, folder, _, record = setup
    (folder/'summary.json').write_text(json.dumps({**record, 'source_selection': 'another-selection'}))
    assert invoke(setup)['status'] == 'no_forecasts'
    (folder/'summary.json').write_text(json.dumps(record))
    (folder/'predictions.parquet').unlink()
    assert invoke(setup, name='missing')['status'] == 'failed'


def test_non_monthly_is_not_monthly_sample(setup):
    import polars as pl
    _, folder, _, record = setup
    day = dt.date(2026, 2, 2)
    (folder/'summary.json').write_text(json.dumps({**record, 'as_of': str(day)}))
    table = pl.read_parquet(folder/'predictions.parquet').with_columns(pl.lit(day).alias('trade_date'))
    table.write_parquet(folder/'predictions.parquet')
    result = invoke(setup)
    assert result['non_monthly_records'] == 1
    assert result['forward_scored_series_months'] == 0
    assert result['series'][0]['historical_months'] == 0


def test_score_failure_is_saved_and_not_healthy(setup, monkeypatch):
    def fail(**kwargs):
        raise ValueError('missing source prices')
    monkeypatch.setattr(monitor, 'run_scores', fail)
    result = invoke(setup)
    assert result['status'] == 'failed' and result['requires_review']
    assert 'missing source prices' in result['error']


def test_pending_cannot_hide_monitor_failure(setup, monkeypatch):
    monkeypatch.setattr(monitor, 'run_monitor', lambda **kwargs: {
        'status': 'failed', 'forward_scored_series_months': 0, 'requires_review': True})
    assert invoke(setup, dt.date(2026, 2, 27))['status'] == 'failed'


def test_explicit_missing_current_is_not_ignored(setup):
    config, _, root, _ = setup
    result = monitor.run(config=config, known_through=EXIT, output=root/'missing_current', current=root/'absent')
    assert result['status'] == 'partial'
    assert result['discovery']['errors'][0]['error'] == 'missing_current_forecast'
