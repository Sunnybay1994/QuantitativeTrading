import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.research.classic_monthly_baseline import replay
from tests.unit.test_paper_ledger import D1, D2, D3, SYMBOL, inputs


def replay_inputs():
    kwargs, _ = inputs()
    kwargs["instruments"] = kwargs["instruments"].with_columns(pl.lit("STOCK").alias("instrument_type"))
    kwargs["config"] = {"portfolio": {"initial_cash": 1100.0}, "costs": kwargs["config"]["costs"]}
    kwargs["dividends"] = kwargs["dividends"].with_columns(
        pl.lit(0.0).alias("div_cash"), pl.lit(.5).alias("share_ratio"),
        pl.lit(D3).alias("share_list_date"))
    kwargs["bars"] = kwargs["bars"].with_columns([
        pl.when(pl.col("trade_date") >= D2).then(20/3).otherwise(pl.col(c)).alias(c)
        for c in ("open", "high", "low", "close")])
    kwargs["targets"] = pl.DataFrame({"symbol": [SYMBOL]*3,
        "as_of": [D1-dt.timedelta(days=1), D1, D2], "execution_date": [D1, D2, D3],
        "strategy": ["probe"]*3, "strategy_version": ["1"]*3, "weight": [1., 0., 0.]})
    return {**kwargs, "sessions": [D1, D2, D3], "name": "probe"}


def test_batched_validation_preserves_settlement_trades_and_rejections():
    kwargs = replay_inputs()
    original = replay(**kwargs)
    batched = replay(**kwargs, validate_once=True)
    for left, right in zip(original, batched):
        assert_frame_equal(left, right, check_exact=True)
    assert batched[1]["quantity"].to_list() == [100, 150]
    assert batched[2]["reason"].to_list() == ["T_PLUS_ONE"]


@pytest.mark.parametrize("batched", [False, True])
def test_batched_validation_still_rejects_invalid_prices(batched):
    kwargs = replay_inputs()
    kwargs["bars"] = kwargs["bars"].with_columns(pl.lit(-1.).alias("close"))
    with pytest.raises(Exception):
        replay(**kwargs, validate_once=batched)
