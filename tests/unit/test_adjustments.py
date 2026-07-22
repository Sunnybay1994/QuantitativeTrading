"""累计后复权因子 as-of 匹配与首日基线 fail-closed 测试。"""

import datetime as dt

import polars as pl
import pytest

from quant.data.adjustments import (
    AdjustmentFactorCoverageError,
    apply_adjustment_factors,
)


def _bars(
    rows: list[tuple[str, dt.date, float]],
    *,
    source: str = "fixture",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [r[0] for r in rows],
            "trade_date": [r[1] for r in rows],
            "open": [r[2] for r in rows],
            "high": [r[2] + 0.2 for r in rows],
            "low": [r[2] - 0.2 for r in rows],
            "close": [r[2] for r in rows],
            "volume": [1000.0] * len(rows),
            "amount": [r[2] * 1000.0 for r in rows],
            "adj_factor": [1.0] * len(rows),
            "source": [source] * len(rows),
        }
    )


def _factors(
    rows: list[tuple[str, dt.date, float]],
    *,
    source: str = "fixture",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [r[0] for r in rows],
            "effective_date": [r[1] for r in rows],
            "adj_factor": [r[2] for r in rows],
            "source": [source] * len(rows),
        }
    )


def test_adjustment_factor_applies_from_effective_date():
    bars = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "trade_date": [
                dt.date(2026, 6, 11),
                dt.date(2026, 6, 12),
                dt.date(2026, 6, 15),
            ],
            "open": [10.0, 9.0, 9.1],
            "high": [10.2, 9.2, 9.3],
            "low": [9.8, 8.8, 9.0],
            "close": [10.0, 9.1, 9.2],
            "volume": [1000.0, 1000.0, 1000.0],
            "amount": [10000.0, 9100.0, 9200.0],
            "adj_factor": [1.0, 1.0, 1.0],
            "source": ["baostock", "baostock", "baostock"],
        }
    )
    factors = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "effective_date": [dt.date(1991, 4, 3), dt.date(2026, 6, 12)],
            "adj_factor": [100.0, 125.0],
            "source": ["baostock", "baostock"],
        }
    )

    adjusted = apply_adjustment_factors(bars, factors)

    assert adjusted["adj_factor"].to_list() == [100.0, 125.0, 125.0]
    assert adjusted["close"].to_list() == [10.0, 9.1, 9.2]


def test_first_factor_on_first_bar_day_passes_and_change_day_return_is_hand_calculated():
    """首因子恰等于首 bar 日通过；变化日调整收益严格手算。"""
    bars = _bars(
        [
            ("00700.HK", dt.date(2026, 7, 9), 400.0),
            ("00700.HK", dt.date(2026, 7, 10), 402.0),
            ("00700.HK", dt.date(2026, 7, 11), 404.0),
        ]
    )
    factors = _factors(
        [
            ("00700.HK", dt.date(2026, 7, 9), 1.5),
            ("00700.HK", dt.date(2026, 7, 10), 2.0),
        ]
    )

    adjusted = apply_adjustment_factors(bars, factors)
    assert adjusted["adj_factor"].to_list() == [1.5, 2.0, 2.0]

    closes = adjusted["close"].to_list()
    factors_out = adjusted["adj_factor"].to_list()
    # day1→day2 变化日：(402*2.0)/(400*1.5)-1 = 804/600-1 = 0.34
    day2_ret = (closes[1] * factors_out[1]) / (closes[0] * factors_out[0]) - 1.0
    assert day2_ret == pytest.approx(0.34)
    # 证明不是常量 1，也不是错误方向（若误用旧因子会得到 402/400-1=0.005）
    assert day2_ret != pytest.approx((closes[1] / closes[0]) - 1.0)
    assert day2_ret > 0
    day3_ret = (closes[2] * factors_out[2]) / (closes[1] * factors_out[1]) - 1.0
    assert day3_ret == pytest.approx((404.0 * 2.0) / (402.0 * 2.0) - 1.0)


def test_empty_factors_fail_closed_not_silent_one():
    bars = _bars([("000001.SZ", dt.date(2026, 7, 9), 10.0)])
    factors = _factors([])

    with pytest.raises(AdjustmentFactorCoverageError) as err:
        apply_adjustment_factors(bars, factors)

    assert [i.reason for i in err.value.issues] == ["missing_symbol"]
    assert err.value.issues[0].symbol == "000001.SZ"
    assert err.value.issues[0].earliest_effective_date is None


def test_symbol_present_but_only_future_factor_fails():
    """factor frame 有该证券但只有未来 effective date：不能因 symbol 存在而通过。"""
    bars = _bars(
        [
            ("00700.HK", dt.date(2026, 7, 9), 400.0),
            ("00700.HK", dt.date(2026, 7, 10), 402.0),
        ]
    )
    factors = _factors([("00700.HK", dt.date(2026, 7, 10), 2.0)])

    with pytest.raises(AdjustmentFactorCoverageError) as err:
        apply_adjustment_factors(bars, factors)

    issue = err.value.issues[0]
    assert issue.symbol == "00700.HK"
    assert issue.reason == "no_baseline_on_or_before_first_bar"
    assert issue.first_trade_date == dt.date(2026, 7, 9)
    assert issue.earliest_effective_date == dt.date(2026, 7, 10)


def test_two_symbols_second_late_baseline_fails_entire_batch():
    bars = _bars(
        [
            ("000001.SZ", dt.date(2026, 7, 9), 10.0),
            ("000001.SZ", dt.date(2026, 7, 10), 10.2),
            ("00700.HK", dt.date(2026, 7, 9), 400.0),
            ("00700.HK", dt.date(2026, 7, 10), 402.0),
        ]
    )
    factors = _factors(
        [
            ("000001.SZ", dt.date(2026, 7, 9), 1.1),
            ("00700.HK", dt.date(2026, 7, 10), 2.0),  # 晚于首 bar
        ]
    )

    with pytest.raises(AdjustmentFactorCoverageError) as err:
        apply_adjustment_factors(bars, factors)

    assert [i.symbol for i in err.value.issues] == ["00700.HK"]
    assert err.value.issues[0].reason == "no_baseline_on_or_before_first_bar"


def test_missing_symbol_and_late_baseline_reasons_are_distinguished():
    bars = _bars(
        [
            ("000001.SZ", dt.date(2026, 7, 9), 10.0),
            ("00700.HK", dt.date(2026, 7, 9), 400.0),
        ]
    )
    factors = _factors([("00700.HK", dt.date(2026, 7, 10), 2.0)])

    with pytest.raises(AdjustmentFactorCoverageError) as err:
        apply_adjustment_factors(bars, factors)

    by_symbol = {i.symbol: i for i in err.value.issues}
    assert set(by_symbol) == {"000001.SZ", "00700.HK"}
    assert by_symbol["000001.SZ"].reason == "missing_symbol"
    assert by_symbol["00700.HK"].reason == "no_baseline_on_or_before_first_bar"


def test_row_order_does_not_change_result_or_error_symbols():
    bars = _bars(
        [
            ("00700.HK", dt.date(2026, 7, 10), 402.0),
            ("000001.SZ", dt.date(2026, 7, 9), 10.0),
            ("00700.HK", dt.date(2026, 7, 9), 400.0),
            ("000001.SZ", dt.date(2026, 7, 10), 10.2),
        ]
    )
    factors_ok = _factors(
        [
            ("000001.SZ", dt.date(2026, 7, 10), 1.2),
            ("000001.SZ", dt.date(2026, 7, 9), 1.1),
            ("00700.HK", dt.date(2026, 7, 9), 1.5),
        ]
    )
    adjusted = apply_adjustment_factors(bars, factors_ok)
    assert adjusted.sort(["symbol", "trade_date"])["adj_factor"].to_list() == [
        1.1,
        1.2,
        1.5,
        1.5,
    ]

    factors_bad = _factors(
        [
            ("00700.HK", dt.date(2026, 7, 10), 2.0),
            ("000001.SZ", dt.date(2026, 7, 9), 1.1),
        ]
    )
    bars_shuffled = bars.reverse()
    with pytest.raises(AdjustmentFactorCoverageError) as err:
        apply_adjustment_factors(bars_shuffled, factors_bad)
    assert [i.symbol for i in err.value.issues] == ["00700.HK"]


def test_empty_bars_return_empty_without_factor_requirement():
    bars = _bars([])
    factors = _factors([])
    out = apply_adjustment_factors(bars, factors)
    assert out.is_empty()
