import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.research.etf_history_extension import total_return_prices


def sample():
    days = [dt.date(2020, 1, d) for d in (2, 3, 6, 7)]
    bars = pl.DataFrame({'symbol': ['A'] * 4 + ['B'] * 4, 'trade_date': days * 2,
        'close': [100., 90., 99., 100., 50., 51., 52., 53.]})
    dividends = pl.DataFrame({'symbol': ['A'], 'ex_date': [days[1]], 'div_cash': [10.]})
    return bars, dividends, days


def test_cash_dividend_is_not_a_loss_and_history_is_causal():
    bars, dividends, days = sample()
    result = total_return_prices(bars, dividends)
    assert result.filter(pl.col('symbol') == 'A')['adjusted_close'].to_list()[:3] == pytest.approx([100., 100., 110.])
    assert result.filter(pl.col('symbol') == 'B')['adjusted_close'].to_list() == pytest.approx([50., 51., 52., 53.])
    early = total_return_prices(bars.filter(pl.col('trade_date') <= days[2]), dividends)
    assert_frame_equal(early, result.filter(pl.col('trade_date') <= days[2]))


def test_duplicate_dividends_and_nonpositive_prices_are_rejected():
    bars, dividends, _ = sample()
    with pytest.raises(ValueError, match='Duplicate'):
        total_return_prices(bars, pl.concat([dividends, dividends]))
    with pytest.raises(ValueError, match='closing'):
        total_return_prices(bars.with_columns(pl.lit(0.).alias('close')), dividends)
