import copy
import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.run_strategy_template_selection import select_method


def case():
    config = tomllib.loads(Path('configs/models/p6c_method_selection_20260911.toml').read_text(encoding='utf-8'))
    config['selection'].update(minimum_validation_months=2, minimum_symbols=3)
    scores, labels = [], []
    for month in (1, 2, 3):
        for n in range(4):
            day = dt.date(2024, month, 28)
            scores.append(dict(symbol=str(n), trade_date=day, test_year=2024,
                               equal_z=float(n), positive_mean_ic=float(n), lightgbm=float(-n)))
            labels.append(dict(symbol=str(n), trade_date=day, exit_date_rebalance=dt.date(2024, month+1, 28),
                               label_rebalance=float(n)))
    fits = [dict(test_year=2024, refit_close='2023-12-29', last_known_exit='2023-12-01', training_months=110)]
    return dict(scores=pl.DataFrame(scores), labels=pl.DataFrame(labels), fits=fits, config=config)


def test_finite_grid_tie_uses_registered_order_and_never_promotes_to_paper():
    args = case()
    result, ic = select_method(**args)
    assert result['selected_method'] == 'equal_z' and result['conclusion'] == 'RESEARCH_ONLY'
    assert len(result['attempts']) == 3 and ic.height == 9
    assert not result['attempts'][2]['eligible_for_forward_research']


def test_future_labels_and_predictions_do_not_change_selection():
    args = case()
    expected, _ = select_method(**args)
    args['scores'] = pl.concat([args['scores'], args['scores'].with_columns(
        pl.lit(dt.date(2026, 1, 28)).alias('trade_date'), pl.lit(float('nan')).alias('equal_z'))])
    args['labels'] = pl.concat([args['labels'], args['labels'].with_columns(
        pl.lit(dt.date(2026, 1, 28)).alias('trade_date'), pl.lit(dt.date(2026, 2, 28)).alias('exit_date_rebalance'),
        pl.lit(-100.0).alias('label_rebalance'))])
    assert select_method(**args)[0] == expected


def test_unrealized_validation_labels_are_not_counted():
    args = case()
    args['labels'] = args['labels'].with_columns(pl.lit(dt.date(2026, 1, 1)).alias('exit_date_rebalance'))
    result, _ = select_method(**args)
    assert result['selected_method'] is None and result['conclusion'] == 'REJECTED'
    assert all(row['months'] == 0 for row in result['attempts'])


@pytest.mark.parametrize('mutation', ['future_fit', 'short_fit', 'duplicate_scores', 'duplicate_labels', 'nonfinite'])
def test_bad_inputs_fail(mutation):
    args = case()
    if mutation == 'future_fit':
        args['fits'][0]['last_known_exit'] = '2024-01-02'
    elif mutation == 'short_fit':
        args['fits'][0]['training_months'] = 95
    elif mutation == 'duplicate_scores':
        args['scores'] = pl.concat([args['scores']] * 2)
    elif mutation == 'duplicate_labels':
        args['labels'] = pl.concat([args['labels']] * 2)
    else:
        args['scores'] = args['scores'].with_columns(pl.lit(float('nan')).alias('equal_z'))
    with pytest.raises(ValueError):
        select_method(**args)


def test_selection_does_not_mutate_registered_configuration():
    args = case()
    original = copy.deepcopy(args['config'])
    select_method(**args)
    assert args['config'] == original
