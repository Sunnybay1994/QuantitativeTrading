"""Effective A-share actions must fail closed without unrelated-market failures."""

import datetime as dt

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA, map_day_dividends


DAY = dt.date(2026, 9, 29)


def action(**updates):
    row = {
        "ts_code": "600650.SH",
        "div_proc": "实施",
        "imp_ann_date": "20260918",
        "record_date": "20260928",
        "ex_date": "20260929",
        "pay_date": "20260929",
        "div_listdate": None,
        "cash_div_tax": 0.02,
        "stk_div": 0.0,
    }
    return row | updates


def test_b_shares_and_beijing_do_not_enter_sh_sz_a_share_account():
    raw = pl.DataFrame([
        action(),
        action(ts_code="900914.SH", record_date="20261008", pay_date="20261020"),
        action(ts_code="200002.SZ", imp_ann_date=None, record_date="20261008"),
        action(ts_code="920012.BJ", record_date="bad-date", imp_ann_date=None),
    ])
    before = raw.clone()
    mapped = map_day_dividends(raw, DAY)
    assert mapped["symbol"].to_list() == ["600650.SH"]
    assert mapped["div_cash"].to_list() == [0.02]
    assert_frame_equal(raw, before)


@pytest.mark.parametrize("symbol", ["600000.SH", "688808.SH", "000001.SZ", "001382.SZ", "301488.SZ"])
def test_supported_a_share_boards_are_preserved(symbol):
    assert map_day_dividends(pl.DataFrame([action(ts_code=symbol)]), DAY)["symbol"].item() == symbol


def test_future_effective_action_is_not_applied_or_validated_early():
    future = action(ex_date="20261009", record_date="20261008", imp_ann_date=None)
    raw = pl.DataFrame([action(), future])
    assert map_day_dividends(raw, DAY).height == 1
    with pytest.raises(ValueError, match="missing_implementation_announcement"):
        map_day_dividends(raw, dt.date(2026, 10, 9))


def test_proposal_row_does_not_mask_valid_implementation_or_duplicate_payment():
    raw = pl.DataFrame([
        action(ts_code="601825.SH", imp_ann_date="20260917"),
        action(ts_code="601825.SH", div_proc="预案", imp_ann_date=None),
    ])
    mapped = map_day_dividends(raw, DAY)
    assert mapped.height == 1
    assert mapped["ann_date"].item() == dt.date(2026, 9, 17)


@pytest.mark.parametrize(("updates", "reason"), [
    ({"imp_ann_date": None}, "missing_implementation_announcement"),
    ({"imp_ann_date": "20260930"}, "future_implementation_announcement"),
    ({"record_date": None}, "missing_record_date"),
    ({"record_date": "20261008"}, "record_date_not_before_ex_date"),
    ({"pay_date": None}, "missing_or_early_cash_payment"),
    ({"pay_date": "20260928"}, "missing_or_early_cash_payment"),
    ({"stk_div": 0.48}, "missing_or_early_share_listing"),
])
def test_effective_invalid_a_share_still_fails_with_record_and_reason(updates, reason):
    with pytest.raises(ValueError, match=reason) as caught:
        map_day_dividends(pl.DataFrame([action(**updates)]), DAY)
    assert "600650.SH" in str(caught.value)
    assert str(DAY) in str(caught.value)


def test_shares_only_action_needs_listing_date_but_not_cash_payment():
    raw = pl.DataFrame([action(
        ts_code="688808.SH", cash_div_tax=None, stk_div=0.48,
        pay_date=None, div_listdate="20260929",
    )])
    mapped = map_day_dividends(raw, DAY)
    assert mapped["div_cash"].item() == 0
    assert mapped["share_ratio"].item() == 0.48


def test_no_supported_effective_actions_returns_typed_empty():
    mapped = map_day_dividends(pl.DataFrame([action(ts_code="900914.SH")]), DAY)
    assert mapped.is_empty()
    assert mapped.schema == DIVIDEND_SCHEMA
