import datetime as dt
import json
import tomllib
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import polars as pl
import pytest

from quant.research.export_annual_forecast import export_annual
from quant.research import run_fixed_model_forecast as fixed


FREEZE = dt.datetime(2026, 9, 12, 15, tzinfo=dt.timezone(dt.timedelta(hours=8)))


@pytest.fixture(scope='module')
def model_text():
    from lightgbm import LGBMRegressor

    model = LGBMRegressor(n_estimators=2, min_child_samples=1, verbosity=-1, n_jobs=1)
    model.fit(np.arange(16).reshape(8, 2), np.arange(8))
    return model.booster_.model_to_string()


@pytest.fixture
def source(tmp_path, model_text):
    run = tmp_path/'annual'
    predictions = run/'predictions'
    predictions.mkdir(parents=True)
    (run/'reports').mkdir()
    config = '''[research]
id = "annual-test"
auto_trade = false
[model]
method = "lightgbm"
minimum_training_months = 48
minimum_signal_stocks = 2
missing_features = "neutral_zero_with_monthly_factor_exclusion"
maximum_missing_fraction = 0.3
'''
    (run/'config.toml').write_text(config, encoding='utf-8')
    fit = {'test_year': 2026, 'factors': ['f2', 'f1'], 'refit_close': '2025-12-31',
        'last_known_exit': '2025-12-01', 'training_months': 142, 'training_rows': 2000,
        'prediction_rows': 2, 'missing_features': 'neutral_zero_with_monthly_factor_exclusion',
        'monthly_exclusion_encoding': 'excluded month values neutralized to zero'}
    saved = {'annual_fits': [fit], 'prediction_rows': 2}
    (predictions/'summary.json').write_text(json.dumps(saved), encoding='utf-8')
    complete = {**saved, 'research_id': 'annual-test', 'conclusions': {'lightgbm': 'REJECTED'}}
    (run/'summary.json').write_text(json.dumps(complete), encoding='utf-8')
    (run/'reports/summary.json').write_text(json.dumps({'conclusions': complete['conclusions']}), encoding='utf-8')
    statistics = tmp_path/'statistics'
    for factor, direction in [('f2', -1), ('f1', 1)]:
        folder = statistics/'factors'/factor
        folder.mkdir(parents=True)
        (folder/'statistics.json').write_text(json.dumps({'definition': {'direction': direction}}), encoding='utf-8')
    model = f'''[research]
id = "annual-test"
statistics_source = "{statistics.as_posix()}"
[walk_forward]
test_end = 2026-08-31
[selection]
variant = "size_industry_neutral"
[models]
methods = ["lightgbm"]
missing_features = "neutral_zero_with_monthly_factor_exclusion"
maximum_missing_fraction = 0.3
minimum_signal_stocks = 2
[models.lightgbm]
n_estimators = 2
min_child_samples = 1
n_jobs = 1
verbosity = -1
[execution]
auto_trade = false
'''
    (predictions/'model.toml').write_text(model, encoding='utf-8')
    (predictions/'battery.toml').write_text('[run]\nas_of = 2026-08-31\n', encoding='utf-8')
    # LightGBM stores byte offsets; Windows newline translation corrupts tree sizes.
    (predictions/'lightgbm_2026.txt').write_bytes(model_text.encode('utf-8'))
    pl.DataFrame({'symbol': ['A', 'B'], 'trade_date': [dt.date(2026, 8, 31)]*2,
        'test_year': [2026]*2, 'lightgbm': [.1, .2]}).write_parquet(predictions/'monthly_predictions.parquet')
    refresh = tmp_path/'refresh.toml'
    refresh.write_text('[quality]\nenabled = true\n', encoding='utf-8')
    return dict(run=run, output=tmp_path/'frozen', forward_start=dt.date(2026, 9, 14),
                refresh_config=refresh, now=FREEZE)


def test_export_copies_actual_fit_without_retraining_or_promoting(source):
    result = export_annual(**source)
    output = source['output']
    assert result['factors'] == ['f2', 'f1'] and result['factor_directions'] == {'f2': -1, 'f1': 1}
    assert result['conclusion'] == 'RESEARCH_ONLY' and result['source_conclusion'] == 'REJECTED'
    assert result['selection_rule'] == 'explicit_saved_annual_fit_no_method_selection'
    assert result['freeze_date'] == '2026-09-12' and result['requires_local_quality'] is True
    assert result['lightgbm_parameters']['n_estimators'] == 2
    for name in ('model.toml', 'battery.toml', 'lightgbm_2026.txt', 'summary.json'):
        if name != 'summary.json':
            assert (output/'predictions'/name).read_bytes() == (source['run']/'predictions'/name).read_bytes()
        else:
            assert json.loads((output/'predictions'/name).read_text()) == json.loads(
                (source['run']/'predictions'/name).read_text())
    config = tomllib.loads((output/'config.toml').read_text())
    assert Path(config['research']['predictions']) == (output/'predictions').resolve()
    assert config['selection']['minimum_training_months'] == 48
    with pytest.raises(FileExistsError):
        export_annual(**source)


@pytest.mark.parametrize('file', ['summary.json', 'reports/summary.json',
    'predictions/monthly_predictions.parquet', 'predictions/lightgbm_2026.txt'])
def test_incomplete_source_is_not_exported(source, file):
    (source['run']/file).unlink()
    with pytest.raises(Exception):
        export_annual(**source)
    assert not source['output'].exists()


@pytest.mark.parametrize('field,value', [('last_known_exit', '2026-01-01'),
    ('training_months', 47), ('factors', ['f1', 'f1']), ('factors', ['f1']),
    ('missing_features', 'other'), ('prediction_rows', 1)])
def test_inconsistent_annual_fit_rejected(source, field, value):
    for path in (source['run']/'summary.json', source['run']/'predictions/summary.json'):
        record = json.loads(path.read_text())
        record['annual_fits'][0][field] = value
        path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(ValueError):
        export_annual(**source)
    assert not source['output'].exists()


@pytest.mark.parametrize('day', [dt.date(2026, 8, 31), dt.date(2026, 9, 12), dt.date(2027, 1, 4)])
def test_backdated_or_untrained_forward_year_rejected(source, day):
    source['forward_start'] = day
    with pytest.raises(ValueError):
        export_annual(**source)
    assert not source['output'].exists()


def test_disabled_quality_rejected(source):
    source['refresh_config'].write_text('[quality]\nenabled = false\n', encoding='utf-8')
    with pytest.raises(ValueError, match='quality'):
        export_annual(**source)


@pytest.mark.parametrize('quality', [None, {}, {'as_of': '2026-09-10', 'errors': []},
    {'as_of': '2026-09-11', 'errors': ['bad SUE']}])
def test_exported_forecast_cannot_bypass_daily_quality(source, quality):
    export_annual(**source)
    with pytest.raises(ValueError, match='input quality'):
        fixed.run_forecast(selection=source['output'], as_of=dt.date(2026, 9, 11),
            output=source['output']/'forecast', data_root=source['run'], rehearsal=True, input_quality=quality)
    assert not (source['output']/'forecast').exists()


def test_historical_export_requires_rehearsal_even_after_good_quality(source):
    export_annual(**source)
    with pytest.raises(ValueError, match='rehearsal'):
        fixed.run_forecast(selection=source['output'], as_of=dt.date(2026, 9, 11),
            output=source['output']/'forecast', data_root=source['run'],
            input_quality={'as_of': '2026-09-11', 'errors': []})


@pytest.mark.parametrize('status', ['recorded', 'input_errors'])
def test_fixed_cli_exports_route_through_local_quality(source, monkeypatch, status):
    from quant.research import run_daily_model_forecast as daily

    export_annual(**source)
    runner = Mock(return_value={'status': status})
    monkeypatch.setattr(daily, 'run_daily', runner)
    monkeypatch.setattr('sys.argv', ['fixed', '--selection', str(source['output']),
        '--as-of', '2026-09-11', '--output', str(source['output']/'daily'), '--rehearsal'])
    if status == 'recorded':
        fixed.main()
    else:
        with pytest.raises(SystemExit, match='1'):
            fixed.main()
    assert runner.call_count == 1
    assert runner.call_args.kwargs['saved_data'] is True
    assert runner.call_args.kwargs['rehearsal'] is True
    assert runner.call_args.kwargs['refresh_config'] == source['refresh_config'].resolve()
