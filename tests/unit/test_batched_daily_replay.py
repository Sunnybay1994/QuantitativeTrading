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


@pytest.mark.parametrize("reduction", [False, True])
def test_chunked_replay_preserves_corporate_actions_and_matches_single_run(reduction):
    kwargs = replay_inputs()
    if reduction:
        kwargs["targets"] = kwargs["targets"].head(1)
        kwargs["dividends"] = kwargs["dividends"].with_columns(
            pl.lit(-.2).alias("share_ratio"), pl.lit(D3).alias("ex_date"))
    else:
        kwargs["dividends"] = kwargs["dividends"].with_columns(pl.lit(1.).alias("div_cash"))
    expected = replay(**kwargs, validate_once=True)
    account = {}
    chunks = []
    for day in (D1, D2, D3):
        part = {**kwargs, "sessions": [day],
                "targets": kwargs["targets"].filter(pl.col("execution_date") == day)}
        chunks.append(replay(**part, validate_once=True, account_state=account))
        if day == D1 and reduction:
            assert account["share_reduction_entitlements"][f"{SYMBOL}|{D3}"] == 100
        if day == D2 and not reduction:
            assert account["receivables"][0]["amount"] == 100.
            assert account["restricted_shares"][0]["quantity"] == 50
    for index, full in enumerate(expected):
        assert_frame_equal(full, pl.concat([part[index] for part in chunks], how="vertical_relaxed"), check_exact=True)
    with pytest.raises(ValueError, match="previous exchange session"):
        replay(**kwargs, account_state=account)


@pytest.mark.parametrize("held_on_record_date", [False, True])
def test_delayed_bonus_belongs_to_record_holder_even_after_sale(held_on_record_date):
    kwargs = replay_inputs()
    kwargs["bars"] = kwargs["bars"].with_columns([
        pl.when(pl.col("trade_date") < D3).then(10.).otherwise(20/3).alias(column)
        for column in ("open", "high", "low", "close")])
    kwargs["dividends"] = kwargs["dividends"].with_columns(pl.lit(D3).alias("ex_date"))
    kwargs["targets"] = kwargs["targets"].head(2).with_columns(
        pl.Series("weight", [1., 0.] if held_on_record_date else [0., 1.]))
    account = {}
    replay(**kwargs, validate_once=True, account_state=account)
    assert account["holdings"][SYMBOL]["quantity"] == (50 if held_on_record_date else 100)
    assert account["cash"] == (1100. if held_on_record_date else 100.)
    assert not account.get("share_distribution_entitlements")
