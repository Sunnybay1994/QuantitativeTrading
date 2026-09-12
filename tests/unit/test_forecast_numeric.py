import datetime as dt

import polars as pl
import pytest

from quant.data.forecast_numeric import (
    NAMES, attach_forecast_numeric, forecast_numeric_counts, forecast_numeric_input_names,
    read_forecast_numeric, read_forecast_numeric_config,
)
from quant.data.forecast_text_evaluation import attach_forecast_controls, read_forecast_controls

PUB = dt.date(2020, 1, 1)
PERIOD = dt.date(2020, 3, 31)


def event(**changes):
    return {'symbol': '600001.SH', 'publication_date': PUB, 'report_period': PERIOD,
            'same_day_conflict': False, 'p_change_min': 10.0, 'p_change_max': 30.0,
            'first_ann_date': '20191001', **changes}


def write(tmp_path, rows):
    path = tmp_path/'forecasts.parquet'
    pl.from_dicts(rows, schema_overrides={'p_change_min': pl.Float64, 'p_change_max': pl.Float64,
                                        'same_day_conflict': pl.Boolean}).write_parquet(path)
    return path


def grid(dates):
    return pl.DataFrame({'symbol': ['600001.SH'] * len(dates), 'trade_date': dates},
                        schema={'symbol': pl.String, 'trade_date': pl.Date})


def test_same_day_close_available_and_119_120_day_boundary(tmp_path):
    source = write(tmp_path, [event()])
    dates = [PUB-dt.timedelta(days=1), PUB, PUB+dt.timedelta(days=119), PUB+dt.timedelta(days=120)]
    result = attach_forecast_numeric(grid(dates), read_forecast_numeric(source))
    assert result[NAMES[0]].to_list() == [None, 20.0, 20.0, None]
    assert result[NAMES[1]].to_list() == [None, 20.0, 20.0, None]
    assert result['forecast_numeric_status'].to_list() == ['no_announcement', 'valid', 'valid', 'expired']
    assert result['forecast_publication_date'][1] == PUB


@pytest.mark.parametrize(('low', 'high', 'status'), [
    (None, 99.0, 'missing_range'), (1.0, None, 'missing_range'),
    (float('nan'), 3.0, 'non_finite_range'), (1.0, float('inf'), 'non_finite_range'),
    (-float('inf'), 1.0, 'non_finite_range'), (20.0, 10.0, 'inverted_range'),
    (-1e308, 1e308, 'non_finite_range'),
])
def test_latest_invalid_announcement_invalidates_old_midpoint_and_width(tmp_path, low, high, status):
    later = PUB + dt.timedelta(days=10)
    source = write(tmp_path, [event(), event(publication_date=later, p_change_min=low, p_change_max=high)])
    result = attach_forecast_numeric(grid([PUB, later, later+dt.timedelta(days=1)]), read_forecast_numeric(source))
    assert result[NAMES[0]].to_list() == [20.0, None, None]
    assert result[NAMES[1]].to_list() == [20.0, None, None]
    assert result['forecast_numeric_status'][1] == status


def test_conflicts_and_latest_report_period_follow_original_selection(tmp_path):
    source = write(tmp_path, [event(report_period=dt.date(2019,12,31), p_change_min=1.0, p_change_max=2.0),
        event(), event(p_change_min=40.0, p_change_max=50.0)])
    legacy = read_forecast_controls(source)
    numeric = read_forecast_numeric(source)
    assert numeric.select(legacy.columns).equals(legacy)
    assert numeric['report_period'][0] == PERIOD
    assert numeric[NAMES[0]][0] is None and numeric[NAMES[1]][0] is None
    assert numeric['forecast_numeric_event_status'][0] == 'same_day_conflict'


@pytest.mark.parametrize('conflict', [True, None])
def test_declared_or_unknown_conflict_invalidates_latest_event(tmp_path, conflict):
    later = PUB + dt.timedelta(days=5)
    source = write(tmp_path, [event(), event(publication_date=later, same_day_conflict=conflict)])
    result = attach_forecast_numeric(grid([later]), read_forecast_numeric(source))
    assert result[NAMES[0]][0] is None and result[NAMES[1]][0] is None


def test_exact_duplicates_are_one_event_and_width_is_not_absolute_or_fractional(tmp_path):
    row = event(p_change_min=-80.0, p_change_max=-20.0)
    source = write(tmp_path, [row, row])
    result = read_forecast_numeric(source)
    assert result.height == 1 and result[NAMES[0]][0] == -50.0 and result[NAMES[1]][0] == 60.0
    source = write(tmp_path, [event(p_change_min=0.0, p_change_max=0.0)])
    zeros = read_forecast_numeric(source)
    assert zeros[NAMES[0]][0] == zeros[NAMES[1]][0] == 0.0
    assert zeros['forecast_numeric_event_status'][0] == 'valid'


def test_valid_midpoints_and_timing_equal_existing_controls(tmp_path):
    source = write(tmp_path, [event(), event(publication_date=PUB+dt.timedelta(days=5),
        report_period=dt.date(2020,6,30), p_change_min=-10.0, p_change_max=20.0)])
    keys = grid([PUB-dt.timedelta(days=1), PUB, PUB+dt.timedelta(days=5), PUB+dt.timedelta(days=125)])
    original = attach_forecast_controls(keys, read_forecast_controls(source), max_age_days=120)
    new = attach_forecast_numeric(keys, read_forecast_numeric(source))
    assert new.select(original.columns).equals(original)


def test_future_announcement_cannot_change_previous_daily_values(tmp_path):
    source = write(tmp_path, [event()])
    keys = grid([PUB, PUB+dt.timedelta(days=2)])
    original = attach_forecast_numeric(keys, read_forecast_numeric(source))
    write(tmp_path, [event(), event(publication_date=PUB+dt.timedelta(days=3), p_change_min=999.0)])
    assert attach_forecast_numeric(keys, read_forecast_numeric(source)).equals(original)


def test_config_loader_resolves_data_relative_path_and_preserves_baseline_age(tmp_path):
    source = write(tmp_path, [event()])
    config = tmp_path/'refresh.toml'
    config.write_text(f'forecast_numeric_corpus = "{source.name}"\nforecast_numeric_max_age_days = 120\n')
    assert read_forecast_numeric_config(tmp_path, config).equals(read_forecast_numeric(source))
    config.write_text(f'forecast_numeric_corpus = "{source.name}"\nforecast_numeric_max_age_days = 119\n')
    with pytest.raises(ValueError, match='120-day'):
        read_forecast_numeric_config(tmp_path, config)


def test_input_names_are_ast_names_not_substring_matches():
    assert forecast_numeric_input_names(('rank(forecast_p_change_width)', 'forecast_p_change_midpoint + close')) == NAMES
    assert forecast_numeric_input_names(('"forecast_p_change_width"', 'forecast_p_change_width_extra')) == ()


def test_duplicate_grid_or_event_keys_fail_and_empty_grid_is_supported(tmp_path):
    events = read_forecast_numeric(write(tmp_path, [event()]))
    with pytest.raises(ValueError):
        attach_forecast_numeric(grid([PUB, PUB]), events)
    with pytest.raises(ValueError):
        attach_forecast_numeric(grid([PUB]), pl.concat([events, events]))
    assert attach_forecast_numeric(grid([]), events).is_empty()


def test_probe_counts_ranges_and_event_validity_without_text(tmp_path):
    source = write(tmp_path, [event(), event(p_change_min=50.0),
        event(symbol='600002.SH', p_change_min=None), event(symbol='600003.SH', same_day_conflict=True)])
    result = forecast_numeric_counts(source)
    assert result['source_rows'] == 4 and result['finite_range_rows'] == 3
    assert result['inverted_range_rows'] == 1 and result['same_day_conflict_rows'] == 1
    assert result['retained_events'] == 3 and result['valid_events'] == 0
    assert result['units'] == 'percentage_points'
