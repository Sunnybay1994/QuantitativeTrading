import polars as pl
import pytest

from quant.data.futu_minute_backfill import normalize


def sample() -> pl.DataFrame:
    return pl.DataFrame({"code": ["SH.600000"] * 2,
                         "time_key": ["2025-02-05 09:30:00", "2025-02-05 09:31:00"],
                         "open": [10., 10.], "high": [10., 11.], "low": [10., 9.],
                         "close": [10., 10.5], "volume": [100., 200.],
                         "turnover": [1000., 2050.]})


def test_retains_opening_row_and_supplier_timestamp() -> None:
    result = normalize(sample(), "600000.SH", "2025-02-05", "2025-02-05")
    assert result.height == 2
    assert result["is_opening_row"].to_list() == [True, False]
    assert result["bar_time"][1].minute == 31
    assert str(result.schema["bar_time"].time_zone) == "Asia/Shanghai"
    assert result["amount"].sum() == 3050


@pytest.mark.parametrize("case", ["symbol", "duplicate", "ohlc", "nonfinite"])
def test_rejects_invalid_source(case: str) -> None:
    frame = sample()
    if case == "symbol":
        frame = frame.with_columns(pl.lit("SZ.000001").alias("code"))
    elif case == "duplicate":
        frame = pl.concat([frame, frame.head(1)])
    elif case == "ohlc":
        frame = frame.with_columns(pl.lit(1.).alias("high"))
    else:
        frame = frame.with_columns(pl.lit(float("nan")).alias("amount"),
                                   pl.lit(float("nan")).alias("turnover"))
    with pytest.raises(ValueError):
        normalize(frame, "600000.SH", "2025-02-05", "2025-02-05")
