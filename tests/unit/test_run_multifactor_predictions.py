import datetime as dt
import json

import polars as pl
import pytest

from quant.research.run_multifactor_predictions import completed_fit_plan, run_predictions


def test_incomplete_evidence_is_not_substituted_with_cash(tmp_path):
    (tmp_path/'summary.json').write_text(json.dumps({'annual_selection': [
        {'test_year': 2023, 'selection_complete': False}]}))
    model = {'walk_forward': {'test_start': dt.date(2023, 1, 1), 'test_end': dt.date(2023, 12, 31)}}
    with pytest.raises(ValueError, match='Finish annual factor evidence'):
        completed_fit_plan(tmp_path, model)


def test_driver_predicts_refit_close_for_next_year_without_future_labels(tmp_path):
    root, selection = tmp_path/'statistics', tmp_path/'selection'
    folder = root/'factors'/'a'
    folder.mkdir(parents=True)
    selection.mkdir()
    dates = [dt.date(2022, 10, 31), dt.date(2022, 12, 30)]
    keys = {'symbol': ['A', 'B', 'C']*2, 'trade_date': [dates[0]]*3+[dates[1]]*3}
    pl.DataFrame({**keys, 'neutral': [1., 2., 3.]*2}).write_parquet(folder/'monthly_scores.parquet')
    inputs = root/'inputs'/'2022'
    inputs.mkdir(parents=True)
    pl.DataFrame({**keys, 'exit_date_rebalance': [dt.date(2022, 12, 1)]*3+[dt.date(2023, 2, 1)]*3,
        'label_rebalance': [.1, .2, .3, 999., 999., 999.]}).write_parquet(inputs/'monthly_labels.parquet')
    (selection/'model.toml').write_text(f'''[research]
statistics_source = '{root.as_posix()}'
[walk_forward]
test_start = 2023-01-01
test_end = 2023-12-31
history_start = 2022-01-01
[selection]
variant = 'neutral'
[models]
minimum_signal_stocks = 2
[models.lightgbm]
n_estimators = 3
min_child_samples = 1
n_jobs = 1
verbosity = -1
''')
    (selection/'battery.toml').write_text('')
    (selection/'summary.json').write_text(json.dumps({'annual_selection': [{
        'test_year': 2023, 'refit_close': '2022-12-30', 'selection_complete': True,
        'provisional_selected': ['a']}]}))
    pl.DataFrame({'test_year': [2023], 'factor': ['a'], 'training_mean_ic': [.1]}).write_parquet(
        selection/'annual_selection.parquet')
    result = run_predictions(selection=selection, output=tmp_path/'result')
    assert result['annual_fits'][0]['training_rows'] == 3
    assert result['annual_fits'][0]['last_known_exit'] == '2022-12-01'
    prediction = pl.read_parquet(tmp_path/'result'/'monthly_predictions.parquet')
    assert prediction['trade_date'].unique().to_list() == [dt.date(2022, 12, 30)]
    assert prediction['test_year'].to_list() == [2023]*3
    assert (tmp_path/'result'/'lightgbm_2023.txt').is_file()
