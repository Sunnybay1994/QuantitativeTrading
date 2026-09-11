import datetime as dt
import copy

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.research.classic_monthly_baseline import replay
from tests.unit.test_paper_ledger import D1, D2, D3, SYMBOL, inputs


def cash_inputs():
    kwargs = replay_inputs()
    for key in ("bars", "instruments", "targets", "dividends"):
        kwargs[key] = kwargs[key].head(0)
    kwargs["market_states"] = {}
    return kwargs


@pytest.mark.parametrize("batched", [False, True])
def test_cash_span_matches_daily_reference_and_continues_account(batched):
    kwargs = cash_inputs()
    # An unused market-state entry selects the ordinary daily path.
    reference, fast = {}, {}
    expected = replay(**{**kwargs, "market_states": {(D1, SYMBOL): None}},
                      validate_once=batched, account_state=reference)
    actual = replay(**kwargs, validate_once=batched, account_state=fast)
    for left, right in zip(expected, actual):
        assert_frame_equal(left, right, check_exact=True)
    assert fast == reference
    carried = {}
    pieces = []
    for dates in ([D1], [D2, D3]):
        pieces.append(replay(**{**kwargs, "sessions": dates},
                             validate_once=batched, account_state=carried))
    assert carried == fast
    assert_frame_equal(pl.concat([piece[0] for piece in pieces]), actual[0], check_exact=True)


def test_cash_span_checks_later_calendar_and_initial_cash():
    kwargs = cash_inputs()
    kwargs["calendar"] = kwargs["calendar"].filter(pl.col("date") != D3)
    with pytest.raises(ValueError, match="CALENDAR_COVERAGE"):
        replay(**kwargs, validate_once=True)
    kwargs = cash_inputs()
    kwargs["config"]["portfolio"]["initial_cash"] = 0.
    with pytest.raises(ValueError, match="ACCOUNT_INVARIANT"):
        replay(**kwargs, validate_once=True)


def test_cash_chunk_can_continue_into_invested_chunk():
    cash = cash_inputs()
    account, reference = {}, {}
    replay(**{**cash, "sessions": [D1]}, validate_once=True, account_state=account)
    replay(**{**cash, "sessions": [D1], "market_states": {(D1, SYMBOL): None}},
           validate_once=True, account_state=reference)
    invested = replay_inputs()
    invested["sessions"] = [D2, D3]
    invested["targets"] = invested["targets"].filter(pl.col("execution_date") == D2).with_columns(
        pl.lit(1.).alias("weight"))
    invested["dividends"] = invested["dividends"].head(0)
    expected = replay(**invested, validate_once=True, account_state=reference)
    actual = replay(**invested, validate_once=True, account_state=account)
    for left, right in zip(expected, actual):
        assert_frame_equal(left, right, check_exact=True)
    assert account == reference and account["holdings"]


def test_cash_receivables_still_settle_on_pay_date(monkeypatch):
    from quant.research import classic_monthly_baseline as module

    kwargs = cash_inputs()
    state = {"date": str(D1), "holdings": {}, "cash": 1100., "pending": [], "nav": [],
             "receivables": [{"symbol": SYMBOL, "pay_date": str(D3), "amount": 100.}]}
    original = copy.deepcopy(state)
    calls = []
    advance = module.advance

    def counted(**kw):
        calls.append(kw["date"])
        return advance(**kw)

    monkeypatch.setattr(module, "advance", counted)
    result = replay(**{**kwargs, "sessions": [D2, D3]}, validate_once=True, account_state=state)
    assert calls == [D2, D3]
    assert result[0]["cash"].to_list() == [1100., 1200.]
    assert result[0]["receivable"].to_list() == [100., 0.]
    assert original["receivables"] and not state["receivables"]


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
