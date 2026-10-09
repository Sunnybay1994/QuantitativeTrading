import datetime as dt
from pathlib import Path
import tomllib

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.liquidity_comovement import CONTROLS, SIGNALS
from quant.research.liquidity_comovement_controls import (
    FIXED_CONTROLS, MINIMUM_MONTHS, MINIMUM_NW_T,
    check_liquidity_comovement_controls as check,
    prepare_liquidity_comovement_controls as prepare,
)


def frame():
    return pl.DataFrame({'symbol': ['x', 'y', 'z'], 'trade_date': [dt.date(2020, 1, 31)]*3,
        'candidate': [1., None, -2.], 'label': [2., 1., None],
        **{name: [1., None, 3.] for name in ['admitted', *FIXED_CONTROLS, *CONTROLS]}})


def test_registered_definition_and_exact_control_union():
    spec = tomllib.loads(Path('configs/research/liquidity_comovement_family_v1.toml').read_text())
    assert list(FIXED_CONTROLS) == spec['fixed_control_ids']
    assert list(CONTROLS) == spec['matched_controls']
    assert MINIMUM_MONTHS == spec['minimum_formal_months']
    assert MINIMUM_NW_T == spec['incremental_minimum_nw_t']
    panel = frame()
    result, names = prepare(panel, ['admitted', FIXED_CONTROLS[0], 'admitted'],
        identifier=SIGNALS[0], variant='raw')
    assert names == ['admitted', *FIXED_CONTROLS, *CONTROLS]
    assert_frame_equal(result, panel.head(1))
    assert_frame_equal(panel, frame())


@pytest.mark.parametrize('identifier', SIGNALS)
@pytest.mark.parametrize('variant', ['raw', 'size_industry_neutral'])
def test_selected_variant_is_preserved_and_direction_not_applied_twice(identifier, variant):
    panel = frame().with_columns(pl.col('candidate')*-1)
    def evaluate(actual, name, controls, direction):
        assert_frame_equal(actual, panel.head(1))
        assert name == 'candidate' and direction == 1
        assert controls == ['admitted', *FIXED_CONTROLS, *CONTROLS]
        return {'months': 96, 'newey_west_t': 2.5}
    result = check(panel, ['admitted'], evaluate, identifier=identifier, variant=variant)
    assert result['passed'] and result['candidate_variant'] == variant


@pytest.mark.parametrize(('months', 'statistic', 'passed', 'reason'), [
    (95, 40., False, 'insufficient_months'),
    (96, 2.4999, False, 'incremental_t_below_threshold'),
    (96, 2.5, True, 'incremental_t_pass'),
    (110, -20., False, 'incremental_t_below_threshold'),
    (110, None, False, 'undefined_incremental_statistic'),
    (110, float('nan'), False, 'undefined_incremental_statistic'),
    (110, float('inf'), False, 'undefined_incremental_statistic'),
])
def test_original_thresholds_and_undefined_statistics(months, statistic, passed, reason):
    result = check(frame(), [], lambda *a: {'months': months, 'newey_west_t': statistic},
        identifier=SIGNALS[0], variant='raw')
    assert result['passed'] == passed and result['reason'] == reason


@pytest.mark.parametrize('column', [*CONTROLS, FIXED_CONTROLS[0], 'admitted', 'candidate', 'label'])
def test_missing_columns_raise_before_evaluation(column):
    with pytest.raises(ValueError, match='columns missing'):
        check(frame().drop(column), ['admitted'], lambda *a: pytest.fail('Invalid input evaluated'),
            identifier=SIGNALS[0], variant='raw')


@pytest.mark.parametrize('value', [None, float('nan'), float('inf')])
def test_broken_matched_control_even_before_label_maturity_is_input_error(value):
    panel = frame().with_columns(pl.when(pl.col('symbol') == 'z').then(value)
        .otherwise(pl.col(CONTROLS[0])).alias(CONTROLS[0]))
    with pytest.raises(ValueError, match='cohort differs'):
        check(panel, [], lambda *a: pytest.fail('Invalid input evaluated'),
            identifier=SIGNALS[0], variant='raw')


def test_fixed_control_missingness_and_unknown_signal_remain_unfilled():
    panel = frame().with_columns(pl.lit(None, dtype=pl.Float64).alias(FIXED_CONTROLS[0]))
    cohort, _ = prepare(panel, [], identifier=SIGNALS[0], variant='raw')
    assert cohort.height == 1 and cohort[FIXED_CONTROLS[0]].null_count() == 1
    empty, _ = prepare(panel.with_columns(pl.lit(None, dtype=pl.Float64).alias('candidate')),
        [], identifier=SIGNALS[0], variant='raw')
    assert empty.is_empty()


def test_duplicate_keys_and_wrong_identity_are_input_errors():
    with pytest.raises(ValueError, match='keys'):
        prepare(pl.concat([frame(), frame().head(1)]), [], identifier=SIGNALS[0], variant='raw')
    with pytest.raises(ValueError, match='keys'):
        prepare(frame().with_columns(pl.lit(None, dtype=pl.String).alias('symbol')),
            [], identifier=SIGNALS[0], variant='raw')
    for identifier, variant in [('unknown', 'raw'), (SIGNALS[0], 'selected_after_return')]:
        with pytest.raises(ValueError, match='Unregistered'):
            prepare(frame(), [], identifier=identifier, variant=variant)
    with pytest.raises(ValueError, match='response or candidate'):
        prepare(frame(), ['candidate'], identifier=SIGNALS[0], variant='raw')


def test_original_evaluator_removes_known_exposure_and_keeps_corrected_direction():
    from quant.research.nightly_steps import incremental_statistics
    rng = np.random.default_rng(923)
    count, months = 130, 96
    controls = [*FIXED_CONTROLS, *CONTROLS]
    dates = [dt.date(2010+i//12, i % 12+1, 15) for i in range(months)]
    own = rng.normal(size=count*months)
    panel = pl.DataFrame({'symbol': [f's{k}' for _ in dates for k in range(count)],
        'trade_date': np.repeat(dates, count).tolist(), 'candidate': own,
        'label': own + rng.normal(size=count*months),
        **{name: rng.normal(size=count*months) for name in controls}},
        schema_overrides={'trade_date': pl.Date})
    result = check(panel, [], incremental_statistics, identifier=SIGNALS[1], variant='raw')
    assert result['months'] == 96 and result['passed']
    # The minus sign belongs in N3. Applying it twice destroys this known signal.
    reverse = check(panel.with_columns(-pl.col('candidate')), [], incremental_statistics,
        identifier=SIGNALS[1], variant='raw')
    assert reverse['newey_west_t'] < 0 and not reverse['passed']
    alias = check(panel.with_columns(pl.col(CONTROLS[0]).alias('candidate')), [],
        incremental_statistics, identifier=SIGNALS[0], variant='size_industry_neutral')
    assert alias['months'] == 0 and not alias['passed']
