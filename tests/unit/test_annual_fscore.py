import copy
import datetime as dt
from pathlib import Path
import tomllib

import polars as pl
import pytest

from quant.factors.annual_fscore import COMPONENTS, annual_fscore_components
from quant.research.monthly_annual_fscore import build_monthly_annual_fscore, validate_annual_fscore


def histories():
    periods = [dt.date(year, 12, 31) for year in (2021, 2022, 2023)]
    balance = pl.DataFrame({'symbol': ['000001.SZ'] * 3, 'end_date': periods, 'total_assets': [100., 100., 120.],
        'total_cur_assets': [45., 45., 60.], 'total_cur_liab': [30., 30., 30.],
        'lt_borr': [15., 15., 8.], 'bond_payable': [5., 5., 2.]})
    income = pl.DataFrame({'symbol': ['000001.SZ', '000001.SZ'], 'end_date': periods[1:],
        'n_income': [10., 12.], 'revenue': [100., 150.], 'oper_cost': [70., 90.]})
    cash = pl.DataFrame({'symbol': ['000001.SZ'], 'end_date': [periods[-1]], 'n_cashflow_act': [15.]})
    anchors = income.tail(1).select('symbol', 'end_date')
    issue = pl.DataFrame({'symbol': ['000001.SZ'], 'no_common_equity_issue': [1.]})
    return income, cash, balance, anchors, issue


def test_all_nine_and_beginning_asset_denominators():
    income, cash, balance, anchors, issue = histories()
    result = annual_fscore_components(income, cash, balance, anchors, issue)
    assert result['pit_annual_fscore'].item() == 9
    assert result.select(*COMPONENTS).row(0) == (1,) * 9
    assert result['roa'].item() == pytest.approx(.12)
    assert result['leverage'].item() == pytest.approx(10 / 110)
    result = annual_fscore_components(income, cash.with_columns(pl.lit(11.).alias('n_cashflow_act')), balance, anchors, issue)
    assert result['cash_above_income'].item() == 0
    assert result['pit_annual_fscore'].item() == 8


def test_missing_debt_or_issuance_is_not_an_eight_signal_score():
    income, cash, balance, anchors, issue = histories()
    missing = balance.with_columns(pl.when(pl.col('end_date').dt.year() == 2023).then(None)
        .otherwise(pl.col('bond_payable')).alias('bond_payable'))
    result = annual_fscore_components(income, cash, missing, anchors, issue)
    assert result['valid_components'].item() == 8
    assert result['pit_annual_fscore'].item() is None
    result = annual_fscore_components(income, cash, balance, anchors,
        issue.with_columns(pl.lit(None).cast(pl.Float64).alias('no_common_equity_issue')))
    assert result['pit_annual_fscore'].item() is None


def test_independent_annual_pit_and_conflict_does_not_fall_back():
    income, cash, balance, _, _ = histories()

    def published(frame):
        return frame.with_columns((pl.col('end_date') + pl.duration(days=80)).alias('ann_date'),
            (pl.col('end_date') + pl.duration(days=80)).alias('f_ann_date'),
            (pl.col('end_date') + pl.duration(days=80)).alias('available_date'),
            pl.lit('1').alias('report_type'), pl.lit('1').alias('comp_type'), pl.lit('0').alias('update_flag'))

    income, cash, balance = [published(f) for f in (income, cash, balance)]
    events = pl.DataFrame({'symbol': ['000001.SZ'], 'event_date': [dt.date(2023, 3, 31)],
        'ann_date': [dt.date(2023, 4, 1)], 'change_type_codes': ['015019']})
    coverage = pl.DataFrame({'symbol': ['000001.SZ'], 'start': [dt.date(2019, 1, 1)],
        'end': [dt.date(2026, 9, 10)], 'empty_response': [False]})
    kwargs = dict(cash_history=cash, balance_history=balance, events=events, event_coverage=coverage,
        signal_dates=(dt.date(2024, 4, 1),), candidate_symbols=('000001.SZ',))
    result = build_monthly_annual_fscore(income_history=income, **kwargs)
    assert result.factors['pit_annual_fscore'].item() == 9
    conflict = pl.concat([income, income.tail(1).with_columns(pl.lit(13.).alias('n_income'))])
    result = build_monthly_annual_fscore(income_history=conflict, **kwargs)
    assert result.factors['financial_period_end'].item() == dt.date(2023, 12, 31)
    assert result.factors['pit_annual_fscore'].item() is None
    assert result.quarantined.height > 0


def test_configuration_retains_frozen_baseline_and_all_nine():
    config = tomllib.loads(Path('configs/research/b92_annual_fscore_nine_20260910.toml').read_text())
    prior = tomllib.loads(Path('configs/research/b57_annual_profitability_six_20260910.toml').read_text())
    for section in ('data', 'universe', 'portfolio', 'costs', 'walk_forward', 'eligibility', 'composite'):
        assert config[section] == prior[section]
    validate_annual_fscore(config)
    for key, value in [('minimum_components', 8), ('issuance_codes', ['015004']),
                       ('missing_component', 'zero'), ('change_rule', 'nondecreasing')]:
        changed = copy.deepcopy(config)
        changed['annual_fscore'][key] = value
        with pytest.raises(ValueError):
            validate_annual_fscore(changed)
