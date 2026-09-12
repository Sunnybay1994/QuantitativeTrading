"""Field recovery preserves independent evidence without legitimizing bad shares."""
import datetime as dt

import polars as pl
import pytest

from quant.data.daily_basic_field_recovery import (
    DAILY_BASIC_COLUMNS,
    recover_daily_basic_fields,
)
from quant.domain import DailyBasic1dSchema

DATE = dt.date(2026, 9, 8)


def frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    daily = pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260908"],
        "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
        "vol": [100.0], "amount": [105.0]})
    adjustment = pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260908"],
                               "adj_factor": [2.5]})
    basic = pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260908"],
        "close": [10.5], "turnover_rate": [1.0], "turnover_rate_f": [2.0],
        "volume_ratio": [1.1], "pe": [-3.0], "pe_ttm": [None], "pb": [1.2],
        "ps": [1.0], "ps_ttm": [1.0], "dv_ratio": [None], "dv_ttm": [0.0],
        "total_share": [100.0], "float_share": [80.0], "free_share": [90.0],
        "total_mv": [1050.0], "circ_mv": [840.0]})
    return daily, adjustment, basic


def recover(parts: tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]) -> pl.DataFrame:
    return recover_daily_basic_fields(daily=parts[0], adjustment=parts[1], basic=parts[2], date=DATE)


def test_free_share_conflict_clears_only_dependencies_and_preserves_source_null_and_zero():
    parts = frames()
    originals = tuple(frame.clone() for frame in parts)
    result = recover(parts)
    clean = DailyBasic1dSchema.validate(result.select(DAILY_BASIC_COLUMNS))
    row = clean.row(0, named=True)
    assert row["total_market_value"] == 10_500_000
    assert row["total_shares"] == 1_000_000 and row["float_shares"] == 800_000
    assert row["free_float_shares"] is None and row["turnover_rate_free"] is None
    assert row["turnover_rate"] == 1.0 and row["circulating_market_value"] == 8_400_000
    assert row["pe"] == -3 and row["pe_ttm"] is None
    assert row["dividend_yield_ttm"] == 0 and row["dividend_yield"] is None
    assert result["daily_basic_schema_valid"].to_list() == [True]
    assert result["cleared_fields"].to_list() == ["free_float_shares,turnover_rate_free"]
    assert all(original.equals(current) for original, current in zip(originals, parts, strict=True))


def test_valid_free_shares_remain_observed():
    daily, adjustment, basic = frames()
    result = recover((daily, adjustment, basic.with_columns(pl.lit(50.0).alias("free_share"))))
    assert result["free_float_shares"].to_list() == [500_000]
    assert result["turnover_rate_free"].to_list() == [2.0]
    assert result["quality_reason"].to_list() == ["unchanged_valid_row"]
    assert result["cleared_fields"].to_list() == [""]


def test_mixed_batch_keeps_float_conflict_as_explicit_supplement():
    daily, adjustment, basic = frames()
    more_daily = daily.with_columns(pl.lit("000002.SZ").alias("ts_code"))
    more_adjustment = adjustment.with_columns(pl.lit("000002.SZ").alias("ts_code"))
    more_basic = basic.with_columns(pl.lit("000002.SZ").alias("ts_code"),
                                    pl.lit(120.0).alias("float_share"),
                                    pl.lit(1260.0).alias("circ_mv"))
    result = recover((pl.concat([more_daily, daily]), pl.concat([adjustment, more_adjustment]),
                      pl.concat([basic, more_basic])))
    assert result["symbol"].to_list() == ["000001.SZ", "000002.SZ"]
    assert result["daily_basic_schema_valid"].to_list() == [True, False]
    DailyBasic1dSchema.validate(result.filter(pl.col("daily_basic_schema_valid")).select(DAILY_BASIC_COLUMNS))
    supplement = result.filter(~pl.col("daily_basic_schema_valid")).row(0, named=True)
    assert supplement["close"] == 10.5 and supplement["total_market_value"] == 10_500_000
    assert supplement["total_shares"] == 1_000_000
    for name in ("float_shares", "free_float_shares", "circulating_market_value", "turnover_rate",
                 "turnover_rate_free", "pe", "dividend_yield_ttm"):
        assert supplement[name] is None
        assert name in supplement["cleared_fields"].split(",")
    assert "independent_fields_only" in supplement["quality_reason"]


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("problem", ["wrong_date", "duplicate", "different_key", "extra_key"])
def test_all_three_tables_require_exact_requested_dates_and_unique_same_keys(position, problem):
    parts = list(frames())
    frame = parts[position]
    if problem == "wrong_date":
        frame = frame.with_columns(pl.lit("20260909").alias("trade_date"))
    elif problem == "duplicate":
        frame = pl.concat([frame, frame])
    elif problem == "different_key":
        frame = frame.with_columns(pl.lit("000002.SZ").alias("ts_code"))
    else:
        frame = pl.concat([frame, frame.with_columns(pl.lit("000002.SZ").alias("ts_code"))])
    parts[position] = frame
    with pytest.raises(ValueError):
        recover(tuple(parts))


@pytest.mark.parametrize("column", ["close", "total_share", "total_mv"])
@pytest.mark.parametrize("value", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_invalid_independent_price_share_or_value_is_rejected(column, value):
    daily, adjustment, basic = frames()
    with pytest.raises(ValueError):
        recover((daily, adjustment, basic.with_columns(pl.lit(value).alias(column))))


def test_one_ppm_boundary_keeps_raw_value_but_rejects_material_mismatch():
    daily, adjustment, basic = frames()
    raw_value = 1050 * (1 + .35e-6)
    result = recover((daily, adjustment, basic.with_columns(pl.lit(raw_value).alias("total_mv"))))
    assert result["total_market_value"][0] == raw_value * 10000
    assert 0 < result["market_value_relative_difference"][0] < 1e-6
    for float_share in (80.0, 120.0):
        invalid = basic.with_columns(pl.lit(1050 * (1 + 2e-6)).alias("total_mv"),
                                     pl.lit(float_share).alias("float_share"))
        with pytest.raises(ValueError, match="one-ppm"):
            recover((daily, adjustment, invalid))


def test_close_matches_across_available_tables_and_positive_adjustment():
    daily, adjustment, basic = frames()
    with pytest.raises(ValueError, match="Daily close differs"):
        recover((daily.with_columns(pl.lit(10.6).alias("close")), adjustment, basic))
    with pytest.raises(ValueError, match="Adjustment close differs"):
        recover((daily, adjustment.with_columns(pl.lit(10.6).alias("close")), basic))
    with pytest.raises(ValueError, match="must be positive"):
        recover((daily, adjustment.with_columns(pl.lit(0.0).alias("adj_factor")), basic))
    assert recover((daily, adjustment.with_columns(pl.lit(10.5).alias("close")), basic)).height == 1


def test_unsafe_unrelated_market_value_or_price_fields_are_not_hidden_by_repair():
    daily, adjustment, basic = frames()
    with pytest.raises(ValueError, match="Circulating market value"):
        recover((daily, adjustment, basic.with_columns(pl.lit(2000.0).alias("circ_mv"))))
    with pytest.raises(ValueError, match="price/volume/adjustment"):
        recover((daily.with_columns(pl.lit(10.0).alias("high")), adjustment, basic))
    with pytest.raises(ValueError, match="nonfinite"):
        recover((daily, adjustment, basic.with_columns(pl.lit(float("inf")).alias("pe_ttm"))))


def test_scaled_overflow_and_unrequested_market_keys_are_rejected():
    daily, adjustment, basic = frames()
    with pytest.raises(ValueError, match="one-ppm"):
        recover((daily, adjustment, basic.with_columns(pl.lit(1e308).alias("total_mv"),
                                                       pl.lit(1e307).alias("total_share"))))
    with pytest.raises(ValueError, match="invalid or duplicate"):
        recover(tuple(frame.with_columns(pl.lit("000001.BJ").alias("ts_code")) for frame in frames()))
