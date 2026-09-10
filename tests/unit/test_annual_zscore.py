import copy
import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.factors.annual_zscore import compute_annual_zscore
from quant.research.monthly_annual_zscore import build_monthly_annual_zscore, validate_annual_zscore


def statements():
    keys = {'symbol': ['000001.SZ'] * 2,
            'end_date': [dt.date(2021, 12, 31), dt.date(2022, 12, 31)]}
    income = pl.DataFrame(keys | {'ebit': [10., 10.], 'revenue': [80., 80.]})
    balance = pl.DataFrame(keys | {'total_assets': [100., 100.], 'total_cur_assets': [50., 50.],
        'total_cur_liab': [20., 20.], 'surplus_rese': [5., 5.], 'undistr_porfit': [15., 15.]})
    def dated(frame):
        return frame.with_columns(pl.col('end_date').dt.offset_by('3mo').alias('available_date')).with_columns(
            pl.col('available_date').alias('ann_date'), pl.col('available_date').alias('f_ann_date'),
            pl.lit('1').alias('report_type'), pl.lit('1').alias('comp_type'), pl.lit('0').alias('update_flag'))
    return dated(income), dated(balance)


def run(income, balance, date=dt.date(2023, 4, 1), basic=None):
    if basic is None:
        basic = pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [date], 'total_market_value': [200.]})
    return build_monthly_annual_zscore(income_history=income, balance_history=balance, daily_basic=basic,
        signal_dates=(date,), candidate_symbols=('000001.SZ',))


def test_formula_yuan_and_signed_distress_inputs():
    income, balance = statements()
    values = run(income, balance).factors
    assert values['pit_annual_zscore'].item() == pytest.approx(2.97)
    assert values['working_capital'].item() == 30.
    assert values['retained_earnings'].item() == 20.
    # All negative distress components are valid; no zero-clipping.
    income = income.with_columns(pl.lit(-10.).alias('ebit'))
    balance = balance.with_columns(pl.lit(60.).alias('total_cur_liab'), pl.lit(-15.).alias('undistr_porfit'))
    assert run(income, balance).factors['pit_annual_zscore'].item() == pytest.approx(1.41)


@pytest.mark.parametrize('field,value', [('total_assets', 0.), ('total_assets', -1.),
    ('surplus_rese', None), ('undistr_porfit', float('nan')), ('ebit', float('inf')),
    ('total_market_value', 0.), ('total_cur_liab', -1.), ('revenue', -1.)])
def test_missing_or_invalid_component_excludes(field, value):
    income, balance = statements()
    values = run(income, balance).factors.with_columns(pl.lit(value, dtype=pl.Float64).alias(field))
    basic = values.select('symbol', 'trade_date', 'total_market_value')
    assert compute_annual_zscore(values.drop('total_market_value'), basic)['pit_annual_zscore'].item() is None


def test_exact_market_date_no_fill_and_duplicate_rejected():
    income, balance = statements()
    basic = pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [dt.date(2023, 3, 31)],
                          'total_market_value': [200.]})
    assert run(income, balance, basic=basic).factors['pit_annual_zscore'].item() is None
    with pytest.raises(pl.exceptions.ComputeError):
        run(income, balance, date=dt.date(2023, 3, 31), basic=pl.concat([basic, basic]))


def test_announcement_lag_latest_conflict_and_no_old_period_fallback():
    income, balance = statements()
    same = run(income, balance, date=dt.date(2023, 3, 31)).factors
    assert same['financial_period_end'].item() == dt.date(2021, 12, 31)
    income = pl.concat([income, income.tail(1).with_columns(pl.lit(11.).alias('ebit'))])
    conflict = run(income, balance)
    assert conflict.factors['financial_period_end'].item() == dt.date(2022, 12, 31)
    assert conflict.factors['pit_annual_zscore'].item() is None
    assert conflict.quarantined.height == 2
    income, balance = statements()
    assert run(income, balance.head(1)).factors['pit_annual_zscore'].item() is None
    assert run(income.with_columns(pl.when(pl.col('end_date').dt.year() == 2022)
        .then(None).otherwise(pl.col('ebit')).alias('ebit')), balance).factors['pit_annual_zscore'].item() is None


def test_expiry_boundary_and_future_restatement():
    income, balance = statements()
    assert run(income, balance, date=dt.date(2024, 6, 30)).factors['pit_annual_zscore'].item() == pytest.approx(2.97)
    assert run(income, balance, date=dt.date(2024, 7, 1)).factors['pit_annual_zscore'].item() is None
    future = income.tail(1).with_columns(pl.lit(999.).alias('ebit'),
        *(pl.lit(dt.date(2023, 4, 2)).alias(c) for c in ['ann_date', 'f_ann_date', 'available_date']))
    assert run(pl.concat([income, future]), balance).factors['pit_annual_zscore'].item() == pytest.approx(2.97)


def test_preregistered_mapping_and_direction():
    path = Path(__file__).resolve().parents[2] / 'configs/research/b58_annual_zscore_20260910.toml'
    config = tomllib.loads(path.read_text(encoding='utf-8'))
    validate_annual_zscore(config)
    for key, value in [('maximum_age_months', 24), ('retained_earnings', 'cap_rese'),
                       ('market_value', 'forward_fill')]:
        changed = copy.deepcopy(config)
        changed['annual_zscore'][key] = value
        with pytest.raises(ValueError):
            validate_annual_zscore(changed)
    config['factors']['directions'] = [-1]
    with pytest.raises(ValueError):
        validate_annual_zscore(config)


def test_reader_requests_required_fields_and_uses_clean_capitalization(monkeypatch):
    from quant.research.monthly_financial_factors import read_monthly_financial_factors

    income, balance = statements()
    calls = []
    def read(*, data_root, query):
        calls.append(query)
        return income if query.dataset == 'income' else balance
    monkeypatch.setattr('quant.research.monthly_financial_factors.read_tushare_financial_history', read)
    config = tomllib.loads((Path(__file__).resolve().parents[2]
        / 'configs/research/b58_annual_zscore_20260910.toml').read_text(encoding='utf-8'))
    signal = dt.date(2023, 4, 28)
    basic = pl.DataFrame({'symbol': ['000001.SZ'], 'trade_date': [signal], 'total_market_value': [200.]})
    result, histories = read_monthly_financial_factors(data_root=Path('unused'), settings=config['financials'],
        candidates=('000001.SZ',), sessions=(signal, dt.date(2023, 5, 4)), start=signal,
        end=dt.date(2023, 5, 4), daily_basic=basic)
    assert set(histories) == {'income', 'balancesheet'}
    assert calls[0].extra_fields == ('ebit', 'revenue')
    assert calls[1].extra_fields == ('total_cur_assets', 'total_cur_liab', 'surplus_rese', 'undistr_porfit')
    assert result.factors['pit_annual_zscore'].item() == pytest.approx(2.97)
