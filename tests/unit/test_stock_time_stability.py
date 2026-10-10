import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.cross_stock_search import group_fitness
from quant.research.nightly_search_recipe import freeze_recipe
from quant.research.research_feedback import search_objective_components


def fixture(reverse=False, missing=False):
    assignments = {f'{g}_{s}': g for g in range(3) for s in range(100)}
    rows = []
    for month in range(6):
        for symbol, group in assignments.items():
            score = float(symbol.split('_')[1])
            rows.append(dict(symbol=symbol, trade_date=dt.date(2020, month+1, 1),
                             candidate=None if missing and month < 3 else score,
                             label=score*(-1 if reverse and month < 3 else 1)))
    config = dict(version='stock_time_stability_v3', sample_groups=3,
                  minimum_symbols_per_month=100, minimum_paired_coverage=.8,
                  minimum_valid_months_per_group=3, training_months=6,
                  minimum_valid_months_per_block=2, maximum_control_correlation=.7,
                  complexity_penalty=.0005)
    return pl.from_dicts(rows, schema_overrides={'candidate': pl.Float64}), assignments, config


def evaluate(reverse=False, missing=False, corr=.2):
    frame, groups, config = fixture(reverse, missing)
    return group_fitness(frame, groups, config=config, complexity=2, maximum_correlation=corr)


def test_reversed_period_cannot_be_hidden_by_pooled_direction():
    with pytest.raises(ValueError, match='Nonpositive'):
        evaluate(reverse=True)


def test_missing_early_history_does_not_shift_the_split():
    with pytest.raises(ValueError, match='block 0 lacks'):
        evaluate(missing=True)


def test_no_reward_for_lower_correlation_below_ceiling():
    result = evaluate(corr=.6)
    assert result['fitness'] == evaluate(corr=.01)['fitness']
    assert len(result['stock_time_statistics']) == 6
    with pytest.raises(ValueError, match='correlation'):
        evaluate(corr=.7)
    feedback = search_objective_components({**result, 'search_objective': result['objective'],
                                            'maximum_rank_correlation': .6})
    assert feedback['primary_metric'] == 'worst_directional_stock_time_mean_ic'
    assert feedback['correlation_penalty'] == 0


def test_new_recipe_freezes_once_and_does_not_rewrite_prior_runs(tmp_path):
    source = Path('configs/research/nightly.toml').read_text(encoding='utf-8')
    run = tmp_path/'batch_1'/'2026-09-23'
    run.mkdir(parents=True)
    frozen = freeze_recipe(source, run, run, [])
    assert 'incremental_residual_config' in tomllib.loads(frozen)
    saved = (run/'incremental_residual.toml').read_bytes()
    next_run = tmp_path/'batch_2'/'2026-09-23'
    next_run.mkdir(parents=True)
    assert freeze_recipe(source, next_run, next_run, [run.parent]) == source
    assert (run/'incremental_residual.toml').read_bytes() == saved
    assert not (next_run/'incremental_residual.toml').exists()
