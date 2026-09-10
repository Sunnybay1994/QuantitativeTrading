import datetime as dt
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.data.financial_repository import read_debt_ebitda_history
from quant.factors.debt_ebitda import compute_debt_ebitda
from quant.research.monthly_debt_ebitda import build_monthly_debt_ebitda, validate_debt_ebitda


def histories():
    indicator = pl.DataFrame({'symbol': ['000001.SZ'] * 2,
        'end_date': [dt.date(2021, 12, 31), dt.date(2022, 12, 31)],
        'ann_date': [dt.date(2022, 3, 31), dt.date(2023, 3, 31)],
        'interestdebt': [10., 30.], 'ebitda': [10., 20.]})
    indicator = indicator.with_columns(pl.col('ann_date').alias('available_date'))
    income = indicator.select('symbol', 'end_date', 'ann_date', 'available_date').with_columns(
        pl.col('ann_date').alias('f_ann_date'), pl.lit('1').alias('report_type'),
        pl.lit('1').alias('comp_type'), pl.lit('0').alias('update_flag'), pl.lit(5.).alias('n_income'))
    return income, indicator


def run(income, indicator, date=dt.date(2023, 4, 1)):
    return build_monthly_debt_ebitda(income_history=income, indicator_history=indicator,
        signal_dates=(date,), candidate_symbols=('000001.SZ',))


def test_ratio_zero_debt_and_nonpositive_earnings():
    f = pl.DataFrame({'interestdebt': [30., 0., 30., 30., -1., None, float('inf')],
                      'ebitda': [20., 20., 0., -20., 20., 20., 20.]})
    assert compute_debt_ebitda(f)['pit_annual_debt_ebitda'].to_list() == [1.5, 0., None, None, None, None, None]


def test_announcement_lag_both_tables_and_latest_period():
    inc, ind = histories()
    same = run(inc, ind, dt.date(2023, 3, 31)).factors
    assert same['financial_period_end'].item() == dt.date(2021, 12, 31)
    assert same['pit_annual_debt_ebitda'].item() == 1.
    assert run(inc, ind).factors['pit_annual_debt_ebitda'].item() == 1.5
    # New income report is known, but its matching indicator is not yet public.
    ind = ind.with_columns(*(pl.when(pl.col('end_date').dt.year() == 2022)
        .then(pl.lit(dt.date(2023, 4, 2))).otherwise(pl.col(c)).alias(c)
        for c in ['ann_date', 'available_date']))
    assert run(inc, ind).factors['pit_annual_debt_ebitda'].item() is None


def test_latest_missing_conflict_and_industrial_filter():
    inc, ind = histories()
    assert run(inc, ind.head(1)).factors['pit_annual_debt_ebitda'].item() is None
    conflict = pl.concat([ind, ind.tail(1).with_columns(pl.lit(99.).alias('interestdebt'))])
    result = run(inc, conflict)
    assert result.factors['pit_annual_debt_ebitda'].item() is None
    assert result.quarantined.height == 2
    inc = inc.with_columns(pl.lit('2').alias('comp_type'))
    assert run(inc, ind).factors['pit_annual_debt_ebitda'].item() is None


def test_expiry_and_later_restatement():
    inc, ind = histories()
    assert run(inc, ind, dt.date(2024, 6, 30)).factors['pit_annual_debt_ebitda'].item() == 1.5
    assert run(inc, ind, dt.date(2024, 7, 1)).factors['pit_annual_debt_ebitda'].item() is None
    future = ind.tail(1).with_columns(pl.lit(100.).alias('interestdebt'),
        *(pl.lit(dt.date(2023, 4, 2)).alias(c) for c in ['ann_date', 'available_date']))
    assert run(inc, pl.concat([ind, future])).factors['pit_annual_debt_ebitda'].item() == 1.5
    assert run(inc, pl.concat([ind, future]), dt.date(2023, 4, 3)).factors['pit_annual_debt_ebitda'].item() == 5.


def test_reader_preserves_indicator_revisions(tmp_path):
    _, ind = histories()
    folder = tmp_path / 'clean/tushare_financials/fixture'
    folder.mkdir(parents=True)
    ind.with_columns(pl.lit('tushare').alias('source')).write_parquet(folder / 'fina_indicator.parquet')
    result = read_debt_ebitda_history(data_root=tmp_path, snapshot_id='fixture', symbols=('000001.SZ',),
        start_period=dt.date(2022, 1, 1), end_period=dt.date(2022, 12, 31))
    assert result.height == 1 and result['interestdebt'].item() == 30.


def test_fixed_mapping_negative_direction():
    config = tomllib.loads((Path(__file__).resolve().parents[2]
        / 'configs/research/b59_annual_debt_ebitda_20260910.toml').read_text(encoding='utf-8'))
    validate_debt_ebitda(config)
    config['factors']['directions'] = [1]
    with pytest.raises(ValueError):
        validate_debt_ebitda(config)
    config['factors']['directions'] = [-1]
    config['debt_ebitda']['missing_component'] = 'zero'
    with pytest.raises(ValueError):
        validate_debt_ebitda(config)
