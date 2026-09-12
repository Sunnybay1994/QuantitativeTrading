import datetime as dt
import json

import polars as pl
import pytest

from quant.research import run_daily_model_forecast as daily


def arguments(tmp_path, monkeypatch):
    selection = tmp_path/'selection'
    selection.mkdir()
    (selection/'selection.json').write_text(json.dumps({'forward_start':'2026-09-14',
        'conclusion':'RESEARCH_ONLY','auto_trade':False}))
    source = tmp_path/'predictions'
    source.mkdir()
    (source/'summary.json').write_text(json.dumps({'annual_fits': [{
        'refit_close': '2025-12-31', 'test_year': 2026, 'last_known_exit': '2025-11-28',
        'training_months': 24, 'factors': ['pit_sue8', 'other_factor']}]}))
    (selection/'config.toml').write_text(f'[research]\npredictions = "{source.as_posix()}"\n'
        '[selection]\nminimum_training_months = 24\n', encoding='utf-8')
    library = tmp_path/'library'
    library.mkdir()
    for name in ('pit_sue8', 'pit_sue8_context_v2', 'other_factor'):
        (library/f'{name}.toml').write_text(f'id = "{name}"\nexpr = "close"\nfamily = "fixture"\n'
            'direction = 1\nsource_ref = "fixture"\n', encoding='utf-8')
    battery = tmp_path/'battery.toml'
    battery.write_text('minimum_symbols = 137\n', encoding='utf-8')
    (tmp_path/'refresh.toml').write_text('financial_snapshot = "fixture_financials"\n'
        f'[quality]\nenabled = true\nbattery_config = "{battery.as_posix()}"\nlookback_sessions = 7\n'
        f'[factors]\nlibrary = "{library.as_posix()}"\n'
        'selected = "all"\n', encoding='utf-8')
    monkeypatch.setattr(daily, 'run_quality', lambda **kwargs: {'errors': [], 'as_of': str(kwargs['end'])})
    monkeypatch.setattr(daily,'latest_session',lambda **kwargs: dt.date(2026,9,14))
    monkeypatch.setattr(daily, 'panel_complete', lambda *args: True)
    monkeypatch.setattr(daily, 'read_coverage', lambda *args: {'start': '2026-01-01', 'end': '2026-09-14'})
    monkeypatch.setattr(daily, 'read_forward_values', lambda *, data_root, factors, as_of:
        {name: pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [as_of], 'value': [1.0]}) for name in factors})
    return dict(to='today',selection=selection,output=tmp_path/'record',data_root=tmp_path,
        refresh_config=tmp_path/'refresh.toml',artifact_root=tmp_path,
        now=dt.datetime(2026,9,14,18,tzinfo=daily.SHANGHAI))


@pytest.mark.parametrize('errors,count', [([],2393),(['missing bars'],0),([],0)])
def test_refresh_then_forecast_and_failures_remain_visible(tmp_path,monkeypatch,errors,count):
    args=arguments(tmp_path,monkeypatch)
    calls=[]
    def refresh(**kwargs):
        calls.append('refresh')
        return {'latest_session':'2026-09-14','intraday_errors':[], 'input_quality':{'errors':errors}}
    def forecast(**kwargs):
        assert calls==['refresh'] and kwargs['as_of']==dt.date(2026,9,14)
        calls.append('forecast')
        return {'prediction_stocks':count}
    monkeypatch.setattr(daily,'run_refresh',refresh)
    monkeypatch.setattr(daily,'run_forecast',forecast)
    result=daily.run_daily(**args)
    assert calls==(['refresh'] if errors else ['refresh','forecast'])
    assert result['status']==('input_errors' if errors else 'recorded' if count else 'missing_model_inputs')
    assert result['auto_trade'] is False
    with pytest.raises(FileExistsError):
        daily.run_daily(**args)


def test_saved_input_rehearsal_does_not_refresh(tmp_path,monkeypatch):
    args=arguments(tmp_path,monkeypatch)
    monkeypatch.setattr(daily,'latest_session',lambda **kwargs:dt.date(2026,9,11))
    monkeypatch.setattr(daily,'run_refresh',lambda **kwargs:pytest.fail('no provider refresh'))
    with pytest.raises(ValueError,match='rehearsal'):
        daily.run_daily(**args,saved_data=True)
    assert not args['output'].exists()
    def forecast(**kwargs):
        assert kwargs['rehearsal'] is True and kwargs['as_of']==dt.date(2026,9,11)
        return {'prediction_stocks':2393}
    monkeypatch.setattr(daily,'run_forecast',forecast)
    result=daily.run_daily(**args,saved_data=True,rehearsal=True)
    assert result['status']=='recorded' and result['saved_data'] is True


def test_saved_input_mode_does_not_fetch_a_missing_calendar(tmp_path,monkeypatch):
    from quant.data import refresh
    monkeypatch.setattr(refresh,'TushareConnector',lambda **kwargs:pytest.fail('no network in saved mode'))
    with pytest.raises(ValueError,match='Saved calendar'):
        refresh.latest_session(data_root=tmp_path,through=dt.date(2026,9,11),refresh_calendar=False)


def test_requirements_use_latest_known_fit_and_preserve_required_factor_order(tmp_path, monkeypatch):
    args = arguments(tmp_path, monkeypatch)
    source = tmp_path/'predictions'/'summary.json'
    base = json.loads(source.read_text())['annual_fits'][0]
    source.write_text(json.dumps({'annual_fits': [
        {**base, 'refit_close': '2024-12-31', 'factors': ['old_factor']},
        {**base, 'refit_close': '2026-09-15', 'factors': ['future_factor']},
        {**base, 'factors': ['other_factor', 'pit_sue8']},
        {'refit_close': None, 'factors': ['untrained_factor']}]}))
    result = daily.model_factor_requirements(selection=args['selection'], refresh_config=args['refresh_config'],
                                            as_of=dt.date(2026, 9, 14))
    assert result['required_factors'] == ['other_factor', 'pit_sue8']
    assert result['refit_close'] == '2025-12-31'
    assert result['required_outside_refresh_selection'] == []


@pytest.mark.parametrize('saved', [False, True])
def test_explicit_exclusion_of_frozen_required_factor_stops_refresh_and_prediction(tmp_path, monkeypatch, saved):
    args = arguments(tmp_path, monkeypatch)
    with args['refresh_config'].open('a', encoding='utf-8') as stream:
        stream.write('excluded_factors = ["pit_sue8"]\n')
    monkeypatch.setattr(daily, 'run_refresh', lambda **_: pytest.fail('known incompatible refresh'))
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: pytest.fail('excluded frozen factor'))
    monkeypatch.setattr(daily, 'read_forward_values', lambda **_: pytest.fail('do not read excluded old cache'))
    result = daily.run_daily(**args, saved_data=saved)
    assert result['status'] == 'input_errors' and result['forecast_path'] is None
    assert result['model_factor_requirements']['required_excluded'] == ['pit_sue8']
    assert any('explicitly excluded' in error for error in result['input_errors'])
    assert json.loads((args['output']/'summary.json').read_text())['status'] == 'input_errors'


def test_selected_subset_missing_required_factor_is_reported(tmp_path, monkeypatch):
    args = arguments(tmp_path, monkeypatch)
    config = args['refresh_config']
    config.write_text(config.read_text().replace('selected = "all"', 'selected = "other_factor"'))
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: pytest.fail('out of selected scope'))
    result = daily.run_daily(**args, saved_data=True)
    assert result['model_factor_requirements']['required_outside_refresh_selection'] == ['pit_sue8']
    assert result['status'] == 'input_errors'


def test_excluding_nonrequired_new_id_keeps_frozen_old_default_prediction(tmp_path, monkeypatch):
    args = arguments(tmp_path, monkeypatch)
    with args['refresh_config'].open('a', encoding='utf-8') as stream:
        stream.write('excluded_factors = ["pit_sue8_context_v2"]\n')
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: {'prediction_stocks': 1})
    result = daily.run_daily(**args, saved_data=True)
    assert result['status'] == 'recorded'
    assert result['model_factor_requirements']['required_factors'] == ['pit_sue8', 'other_factor']
    assert result['model_factor_requirements']['required_excluded'] == []


def test_saved_quality_uses_full_refresh_scope_and_configured_thresholds(tmp_path, monkeypatch):
    args = arguments(tmp_path, monkeypatch)
    source = tmp_path/'predictions'/'summary.json'
    metadata = json.loads(source.read_text())
    metadata['annual_fits'][0]['factors'] = ['other_factor']
    source.write_text(json.dumps(metadata))
    calls = []
    error = 'pit_sue8: 2 finite values lack compatible latest PIT report context'
    def quality(**kwargs):
        calls.append(kwargs)
        assert kwargs['end'] == dt.date(2026, 9, 14)
        assert kwargs['data_root'] == args['data_root'] and kwargs['config'] == args['refresh_config']
        assert kwargs['lookback_sessions'] == 7 and kwargs['minimum_symbols'] == 137
        assert kwargs['financials'] == {}  # Public checker resolves the configured financial snapshot.
        assert kwargs['output'] == args['output']/'input_quality'
        assert {row['id'] for row in kwargs['factors']} == {'pit_sue8', 'pit_sue8_context_v2', 'other_factor'}
        assert all(row['family'] == 'fixture' for row in kwargs['factors'])
        return {'errors': [error], 'sue_report_context_checks': [
            {'factor': 'pit_sue8', 'unexpected_factor_values': 2}]}
    monkeypatch.setattr(daily, 'run_quality', quality)
    monkeypatch.setattr(daily, 'run_refresh', lambda **_: pytest.fail('saved mode is local only'))
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: pytest.fail('quality error blocks prediction'))
    result = daily.run_daily(**args, saved_data=True)
    assert len(calls) == 1 and result['input_errors'] == [error]
    assert result['status'] == 'input_errors' and result['prediction_stocks'] == 0
    assert result['forecast_path'] is None and not (args['output']/'forecast').exists()
    assert json.loads((args['output']/'summary.json').read_text())['input_errors'] == [error]
    assert json.loads((args['output']/'refresh.json').read_text())['input_quality']['errors'] == [error]


def test_saved_quality_honors_nonrequired_exclusion_and_runs_before_forecast(tmp_path, monkeypatch):
    args = arguments(tmp_path, monkeypatch)
    with args['refresh_config'].open('a', encoding='utf-8') as stream:
        stream.write('excluded_factors = ["pit_sue8_context_v2"]\n')
    calls = []
    def quality(**kwargs):
        calls.append('quality')
        assert {row['id'] for row in kwargs['factors']} == {'pit_sue8', 'other_factor'}
        return {'errors': []}
    def forecast(**kwargs):
        assert calls == ['quality']
        calls.append('forecast')
        return {'prediction_stocks': 1}
    monkeypatch.setattr(daily, 'run_quality', quality)
    monkeypatch.setattr(daily, 'run_forecast', forecast)
    result = daily.run_daily(**args, saved_data=True)
    assert calls == ['quality', 'forecast'] and result['status'] == 'recorded'


@pytest.mark.parametrize('health_status', ['recorded', 'unavailable'])
def test_daily_forwards_health_without_rerun_or_changing_quality_errors(tmp_path, monkeypatch, health_status):
    args = arguments(tmp_path, monkeypatch)
    health = {'enabled': True, 'status': health_status, 'as_of': '2026-09-14',
        'output': 'record/input_quality/factor_health', 'diagnostics_only': True}
    calls = []
    def quality(**kwargs):
        calls.append(kwargs)
        return {'errors': [], 'factor_health': health}
    monkeypatch.setattr(daily, 'run_quality', quality)
    monkeypatch.setattr(daily, 'run_forecast', lambda **kwargs: {'prediction_stocks': 1})
    result = daily.run_daily(**args, saved_data=True)
    assert len(calls) == 1
    assert result['factor_health'] == health and result['status'] == 'recorded'
    assert result['input_errors'] == []
    assert json.loads((args['output']/'summary.json').read_text(encoding='utf-8'))['factor_health'] == health


@pytest.mark.parametrize('failure', ['disabled', 'missing_settings', 'missing_battery', 'missing_input', 'invalid_input'])
def test_saved_quality_cannot_be_disabled_or_silently_skipped(tmp_path, monkeypatch, failure):
    args = arguments(tmp_path, monkeypatch)
    config = args['refresh_config']
    if failure == 'disabled':
        config.write_text(config.read_text().replace('enabled = true', 'enabled = false'))
    elif failure == 'missing_settings':
        config.write_text(config.read_text().replace('[quality]', '[unused_quality]'))
    elif failure == 'missing_battery':
        (tmp_path/'battery.toml').unlink()
    else:
        def quality(**kwargs):
            if failure == 'missing_input':
                raise FileNotFoundError('local input parquet missing')
            raise pl.exceptions.ComputeError('invalid local input parquet')
        monkeypatch.setattr(daily, 'run_quality', quality)
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: pytest.fail('quality was not completed'))
    result = daily.run_daily(**args, saved_data=True)
    assert result['status'] == 'input_errors' and result['prediction_stocks'] == 0
    assert 'Cannot complete saved-data input quality checks' in result['input_errors'][0]
    assert result['forecast_path'] is None and not (args['output']/'forecast').exists()
    assert json.loads((args['output']/'summary.json').read_text())['status'] == 'input_errors'


@pytest.mark.parametrize('missing', ['coverage', 'actual_rows', 'file', 'wrong_day'])
def test_freshness_needs_same_date_rows_as_well_as_coverage(tmp_path, monkeypatch, missing):
    args = arguments(tmp_path, monkeypatch)
    calls = []
    def values(*, data_root, factors, as_of):
        calls.append((factors, as_of))
        if missing == 'file':
            raise FileNotFoundError('factor parquet missing')
        frame = pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [as_of], 'value': [None]},
                             schema_overrides={'value': pl.Float64})
        if missing == 'actual_rows':
            frame = frame.clear()
        if missing == 'wrong_day':
            frame = frame.with_columns(pl.lit(as_of - dt.timedelta(days=1)).alias('trade_date'))
        return {factors[0]: frame}
    monkeypatch.setattr(daily, 'read_forward_values', values)
    if missing == 'coverage':
        monkeypatch.setattr(daily, 'panel_complete', lambda *_: False)
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: pytest.fail('incomplete same-date inputs'))
    result = daily.run_daily(**args, saved_data=True)
    assert result['status'] == 'input_errors' and result['prediction_stocks'] == 0
    assert len(result['input_errors']) == 2
    assert calls == ([] if missing == 'coverage' else [(['pit_sue8'], dt.date(2026,9,14)), (['other_factor'], dt.date(2026,9,14))])


def test_actual_computed_nulls_are_reported_and_left_to_model_missing_policy(tmp_path, monkeypatch):
    args = arguments(tmp_path, monkeypatch)
    monkeypatch.setattr(daily, 'read_forward_values', lambda *, data_root, factors, as_of: {
        factors[0]: pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [as_of], 'value': [None]})})
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: {'prediction_stocks': 0})
    result = daily.run_daily(**args, saved_data=True)
    assert result['status'] == 'missing_model_inputs' and result['input_errors'] == []
    assert all(row['status'] == 'computed_without_finite_values' for row in result['model_factor_inputs'])
    assert all(row['actual_rows'] == row['null_rows'] == 1 for row in result['model_factor_inputs'])


@pytest.mark.parametrize('invalid', ['missing_config', 'missing_summary', 'no_known_fit', 'stale_fit',
                                    'future_label', 'short_training', 'duplicate_factors'])
def test_invalid_model_metadata_is_saved_as_input_errors(tmp_path, monkeypatch, invalid):
    args = arguments(tmp_path, monkeypatch)
    summary = tmp_path/'predictions'/'summary.json'
    data = json.loads(summary.read_text())
    fit = data['annual_fits'][0]
    if invalid == 'missing_config':
        (args['selection']/'config.toml').unlink()
    elif invalid == 'missing_summary':
        summary.unlink()
    elif invalid == 'no_known_fit':
        fit['refit_close'] = '2026-12-31'
    elif invalid == 'stale_fit':
        fit['test_year'] = 2025
    elif invalid == 'future_label':
        fit['last_known_exit'] = '2026-01-01'
    elif invalid == 'short_training':
        fit['training_months'] = 23
    else:
        fit['factors'] = ['pit_sue8', 'pit_sue8']
    if invalid not in ('missing_config', 'missing_summary'):
        summary.write_text(json.dumps(data))
    monkeypatch.setattr(daily, 'run_forecast', lambda **_: pytest.fail('invalid frozen fit metadata'))
    result = daily.run_daily(**args, saved_data=True)
    assert result['status'] == 'input_errors'
    assert 'Cannot resolve frozen model factor requirements' in result['input_errors'][0]
    assert (args['output']/'summary.json').is_file()
