import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.overnight_decomposition import compute_overnight_decomposition


def sample():
    days = tuple(dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(6))
    bars = pl.DataFrame({"symbol": ["A"] * 6, "trade_date": days,
        "open": [10., 11., 6., 6., 6., 6.], "close": [10., 12., 6., 6., 6., 6.],
        "adj_factor": [1., 1., 2., 2., 2., 2.]})
    return days, bars


def test_split_adjustment_and_multiplicative_identity():
    days, bars = sample()
    result = compute_overnight_decomposition(bars, sessions=days, window=2)
    row = result.row(2, named=True)
    assert row["overnight_return_20"] == pytest.approx(.1)
    assert row["intraday_return_20"] == pytest.approx(12 / 11 - 1)
    assert row["total_return_20"] == pytest.approx(.2)
    assert (1 + row["overnight_return_20"]) * (1 + row["intraday_return_20"]) == pytest.approx(1.2)


def test_missing_session_invalidates_and_recovers():
    days, bars = sample()
    result = compute_overnight_decomposition(
        bars.filter(pl.col("trade_date") != days[2]), sessions=days, window=2)
    assert result["total_return_20"].to_list()[2:5] == [None, None, None]
    assert result["total_return_20"][5] == pytest.approx(0)


def test_future_append_does_not_change_history():
    days, bars = sample()
    first = compute_overnight_decomposition(bars.head(4), sessions=days[:4], window=2)
    full = compute_overnight_decomposition(bars, sessions=days, window=2)
    assert_frame_equal(first, full.head(4))


@pytest.mark.parametrize("bad", [0., -1., float("nan"), float("inf"), None])
def test_invalid_prices_never_create_a_signal(bad):
    days, bars = sample()
    bars = bars.with_columns(pl.when(pl.col("trade_date") == days[2])
                             .then(pl.lit(bad, dtype=pl.Float64)).otherwise(pl.col("open")).alias("open"))
    result = compute_overnight_decomposition(bars, sessions=days, window=2)
    assert result["total_return_20"].to_list()[2:5] == [None, None, None]


def test_duplicate_input_rejected():
    days, bars = sample()
    with pytest.raises(ValueError, match="Duplicate"):
        compute_overnight_decomposition(pl.concat([bars, bars.head(1)]), sessions=days)


def test_twenty_session_intraday_matches_scalar_product_and_shared_gap_rule():
    import math

    days=tuple(dt.date(2024,1,1)+dt.timedelta(days=i) for i in range(23))
    bars=pl.DataFrame([dict(symbol='A',trade_date=d,open=10.+i%3,
        close=(10.+i%3)*(1.+((i%5)-2)*.01),adj_factor=1.+(i>=10)) for i,d in enumerate(days)])
    result=compute_overnight_decomposition(bars,sessions=days)
    expected=math.prod(row['close']/row['open'] for row in bars.slice(1,20).to_dicts())-1
    assert result['intraday_return_20'][20]==pytest.approx(expected,abs=1e-12)
    gap=compute_overnight_decomposition(bars.filter(pl.col('trade_date')!=days[10]),sessions=days)
    assert all(gap[c][20] is None for c in ('overnight_return_20','intraday_return_20','total_return_20'))


def test_intraday_config_preserves_control_and_rejects_scope_changes():
    import copy
    from pathlib import Path
    import tomllib

    from quant.research.classic_monthly_baseline import validate_overnight_comparison

    config=tomllib.loads(Path('configs/research/b88_intraday_reversal_20260910.toml').read_text())
    prior=tomllib.loads(Path('configs/research/b36_overnight_reversal_20260909.toml').read_text())
    for section in ('data','universe','costs','walk_forward','portfolio','composite','eligibility'):
        assert config[section]==prior[section]
    assert validate_overnight_comparison(prior)=='overnight'
    assert validate_overnight_comparison(config)=='intraday'
    assert prior['admission']['maximum_conclusion']=='RESEARCH_ONLY'
    assert config['admission']['maximum_conclusion']=='PAPER_CANDIDATE'
    assert config['admission']['maximum_annual_one_way_turnover']==6.
    for section,key,value in [('overnight_decomposition','component','both'),
        ('overnight_decomposition','parameter_grid',[10,20]),('overnight_decomposition','window_sessions',10),
        ('factors','names',['overnight_return_20']),('factors','directions',[1]),
        ('overnight_decomposition','paired_pool','available_only'),('portfolio','retention_rank',75),
        ('admission','comparison','510300'),('admission','positive_paired_compound_increment_1x',False)]:
        changed=copy.deepcopy(config)
        changed[section][key]=value
        with pytest.raises(ValueError):
            validate_overnight_comparison(changed)


def test_intraday_composition_preserves_frozen_inputs_and_direction():
    import copy
    from pathlib import Path
    import tomllib

    from quant.research.classic_monthly_baseline import validate_overnight_comparison

    config = tomllib.loads(Path('configs/research/b89_intraday_reversal_composite_20260910.toml').read_text())
    prior = tomllib.loads(Path('configs/research/b88_intraday_reversal_20260910.toml').read_text())
    for section in ('data', 'universe', 'costs', 'walk_forward', 'portfolio', 'composite',
                    'eligibility', 'overnight_decomposition'):
        assert config[section] == prior[section]
    assert validate_overnight_comparison(config) == 'intraday'
    for section, key, value in [
        ('factors', 'directions', [-1, 1, -1, 1]),
        ('overnight_decomposition', 'component', 'overnight'),
        ('intraday_reversal_composition', 'eligibility', 'available_only'),
        ('intraday_reversal_composition', 'paired_baseline', 'total_reversal'),
        ('admission', 'comparison', 'total_reversal'),
    ]:
        changed = copy.deepcopy(config)
        changed[section][key] = value
        with pytest.raises(ValueError):
            validate_overnight_comparison(changed)


def test_intraday_buffer_preserves_b89_scores_and_rejects_changed_controls():
    import copy
    from pathlib import Path
    import tomllib

    from quant.research.classic_monthly_baseline import validate_overnight_comparison

    config = tomllib.loads(Path('configs/research/b90_intraday_reversal_buffer75_20260910.toml').read_text())
    prior = tomllib.loads(Path('configs/research/b89_intraday_reversal_composite_20260910.toml').read_text())
    for section in ('data', 'universe', 'costs', 'walk_forward', 'factors', 'composite',
                    'eligibility', 'overnight_decomposition'):
        assert config[section] == prior[section]
    assert validate_overnight_comparison(config) == 'intraday'
    assert {k: v for k, v in config['portfolio'].items() if k != 'retention_rank'} == prior['portfolio']
    for section, key, value in [
        ('portfolio', 'retention_rank', 100),
        ('portfolio', 'execution_months', [1, 3, 5, 7, 9, 11]),
        ('intraday_reversal_buffer', 'retention_rule', 'prior_actual_holdings'),
        ('admission', 'require_lower_turnover_every_fold', False),
        ('admission', 'comparison', 'three_factor'),
    ]:
        changed = copy.deepcopy(config)
        changed[section][key] = value
        with pytest.raises(ValueError):
            validate_overnight_comparison(changed)
    changed = copy.deepcopy(config)
    changed['intraday_reversal_composition'] = prior['intraday_reversal_composition']
    with pytest.raises(ValueError):
        validate_overnight_comparison(changed)


def test_intraday_bimonthly_keeps_buffer_and_fixed_monthly_comparison():
    import copy
    from pathlib import Path
    import tomllib

    from quant.research.classic_monthly_baseline import validate_overnight_comparison

    config = tomllib.loads(Path('configs/research/b91_intraday_reversal_bimonthly_20260910.toml').read_text())
    prior = tomllib.loads(Path('configs/research/b90_intraday_reversal_buffer75_20260910.toml').read_text())
    for section in ('data', 'universe', 'costs', 'walk_forward', 'factors', 'composite',
                    'eligibility', 'overnight_decomposition'):
        assert config[section] == prior[section]
    assert {k: v for k, v in config['portfolio'].items() if k != 'execution_months'} == prior['portfolio']
    assert validate_overnight_comparison(config) == 'intraday'
    for section, key, value in [
        ('portfolio', 'execution_months', [2, 4, 6, 8, 10, 12]),
        ('portfolio', 'execution_months', None),
        ('portfolio', 'retention_rank', 50),
        ('intraday_reversal_buffer', 'paired_baseline', 'intraday_reversal_unbuffered'),
        ('admission', 'comparison', 'intraday_reversal_unbuffered'),
        ('admission', 'require_lower_turnover_every_fold', False),
    ]:
        changed = copy.deepcopy(config)
        changed[section][key] = value
        with pytest.raises(ValueError):
            validate_overnight_comparison(changed)
