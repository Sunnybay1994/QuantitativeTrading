import datetime as dt

import polars as pl
import pytest

from quant.factors.calendar_liquidity import CALENDAR_LIQUIDITY_NAMES
from quant.factors.expressions import required_history
from quant.factors.liquidity import LIQUIDITY_FACTOR_NAMES
from quant.research.factor_monthly import attach_monthly_factors, monthly_input_names
from tests.unit.test_factor_expressions import prepared
from tests.unit.test_factor_monthly import sample


def test_short_exchange_month_is_valid_but_missing_stock_observations_are_not():
    bars, basic, calendar = sample()
    month = [day for day in calendar if (day.year, day.month) == (2020, 2)]
    removed = set(month[14:])
    calendar = tuple(day for day in calendar if day not in removed)
    bars = bars.filter(~pl.col('trade_date').is_in(removed))
    basic = basic.filter(~pl.col('trade_date').is_in(removed))
    # A second stock has only eleven of the fourteen observations: below ceil(80%*14)=12.
    basic = basic.filter(~((pl.col('symbol') == '600001.SH') & pl.col('trade_date').is_in(month[:3])))
    names = (*LIQUIDITY_FACTOR_NAMES, *CALENDAR_LIQUIDITY_NAMES)
    result = attach_monthly_factors(prepared(bars), bars, basic, calendar, names)
    end = month[13]
    row = result.filter((pl.col('trade_date') == end) & (pl.col('symbol') == '600000.SH')).row(0, named=True)
    assert row[LIQUIDITY_FACTOR_NAMES[1]] is None
    assert row[CALENDAR_LIQUIDITY_NAMES[1]] is not None
    assert row[CALENDAR_LIQUIDITY_NAMES[0]] is not None
    assert row[CALENDAR_LIQUIDITY_NAMES[2]] is not None
    missing = result.filter((pl.col('trade_date') == end) & (pl.col('symbol') == '600001.SH')).row(0, named=True)
    assert missing[CALENDAR_LIQUIDITY_NAMES[1]] is None
    assert missing[CALENDAR_LIQUIDITY_NAMES[2]] is None
    # Valid February no longer poisons the following twelve complete months.
    march = result.filter((pl.col('trade_date') == dt.date(2020, 3, 31)) &
                           (pl.col('symbol') == '600000.SH')).row(0, named=True)
    assert march[LIQUIDITY_FACTOR_NAMES[2]] is None
    assert march[CALENDAR_LIQUIDITY_NAMES[2]] is not None
    before = result.filter((pl.col('trade_date') == month[12]) & (pl.col('symbol') == '600000.SH'))
    january = result.filter((pl.col('trade_date') == dt.date(2020, 1, 31)) & (pl.col('symbol') == '600000.SH'))
    assert before[CALENDAR_LIQUIDITY_NAMES[1]].item() == pytest.approx(january[CALENDAR_LIQUIDITY_NAMES[1]].item())


def test_new_monthly_names_keep_intrinsic_lookback():
    for original, new in zip(LIQUIDITY_FACTOR_NAMES, CALENDAR_LIQUIDITY_NAMES, strict=True):
        assert required_history(new) == required_history(original)
        assert required_history(f'ts_mean({new},20)') == required_history(new)+19
        assert monthly_input_names((f'ts_mean({new},20)',)) == (new,)


def test_calendar_only_batch_ignores_basic_rows_outside_its_bar_universe():
    bars, basic, calendar = sample()
    extra = basic.head(1).with_columns(pl.lit('600002.SH').alias('symbol'))
    expected = attach_monthly_factors(prepared(bars), bars, basic, calendar, CALENDAR_LIQUIDITY_NAMES)
    result = attach_monthly_factors(prepared(bars), bars, pl.concat([basic, extra]), calendar, CALENDAR_LIQUIDITY_NAMES)
    from polars.testing import assert_frame_equal
    assert_frame_equal(result, expected)
