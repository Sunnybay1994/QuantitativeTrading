import polars as pl
import datetime as dt
import pytest

from quant.data.stock_execution_inputs import deduplicate_dividend_notices, resolve_same_day_dividends


def test_identical_plan_keeps_latest_notice_without_merging_other_periods_or_terms():
    row = {"ts_code":"300120.SZ", "end_date":"20131231", "ann_date":"20140328",
        "imp_ann_date":"20140604", "ex_date":"20140611", "div_proc":"实施",
        "cash_div_tax":.1001865, "stk_div":.2003731}
    frame = pl.DataFrame([row, {**row,"ann_date":"20140425","imp_ann_date":"20140605"},
        {**row,"end_date":"20130630"}, {**row,"cash_div_tax":.2}])
    result = deduplicate_dividend_notices(frame)
    assert result.height == 3
    same = result.filter((pl.col("end_date")=="20131231") & (pl.col("cash_div_tax")==.1001865))
    assert same["imp_ann_date"].item() == "20140605"
    # An unknown or post-ex implementation date must survive for validation.
    invalid = deduplicate_dividend_notices(pl.DataFrame([row,{**row,"imp_ann_date":None}]))
    assert invalid["imp_ann_date"].item() is None
    late = deduplicate_dividend_notices(pl.DataFrame([row,{**row,"imp_ann_date":"20140612"}]))
    assert late["imp_ann_date"].item() == "20140612"
    share_only = {**row,"cash_div_tax":0.0,"cash_div":0.0}
    assert deduplicate_dividend_notices(pl.DataFrame([share_only,
        {**share_only,"cash_div_tax":None,"cash_div":None,"imp_ann_date":"20140605"}])).height == 1


@pytest.mark.parametrize("symbol,date,amounts,shares,expected", [
    ("601088.SH","2017-07-10",[2.51,2.97],[0.,0.],2.97),
    ("601966.SH","2025-07-10",[.014,.07],[0.,0.],.084),
    ("601966.SH","2024-06-14",[.091,.286],[0.,0.],.377),
    ("600317.SH","2014-06-16",[.329,.529],[0.,2.],.529),
    ("002043.SZ","2026-06-01",[.132,.18],[0.,0.],.312),
    ("000738.SZ","2013-06-14",[.021,.041],[0.,0.],.062),
    ("600741.SH","2010-06-18",[.0491,.275],[0.,0.],.3241),
    ("301039.SZ","2026-07-06",[.14,.21],[0.,0.],.35),
    ("301308.SZ","2026-06-02",[.3467605,.6439837],[0.,0.],.9907442),
])
def test_verified_cash_totals_and_share_listing(symbol,date,amounts,shares,expected):
    ex = dt.date.fromisoformat(date)
    frame = pl.DataFrame({"symbol":[symbol]*2,"ex_date":[ex]*2,
        "ann_date":[ex-dt.timedelta(days=7)]*2,"record_date":[ex-dt.timedelta(days=3)]*2,
        "pay_date":[ex]*2,"div_cash":amounts,"share_ratio":shares,
        "share_list_date":[ex+dt.timedelta(days=1) if share else None for share in shares]})
    result = resolve_same_day_dividends(frame)
    assert result.height == 1 and result["div_cash"].item() == expected
    assert result["share_ratio"].item() == sum(shares)
    if sum(shares):
        assert result["share_list_date"].item() == ex+dt.timedelta(days=1)


@pytest.mark.parametrize("symbol,date,cash,shares,ann,expected_cash,expected_shares", [
    ("000818.SZ","2011-01-25",[0.,0.],[.4,1.],["2011-01-20"]*2,0.,.4),
    ("000615.SZ","2025-12-29",[0.,0.],[.1,1.34278],["2025-12-23"]*2,0.,.1),
    ("300325.SZ","2016-06-16",[.03937,.04],[0.,0.],["2016-06-07","2016-06-08"],.03937,0.),
])
def test_restructuring_and_revised_distribution_keep_only_ordinary_entitlement(
    symbol,date,cash,shares,ann,expected_cash,expected_shares,
):
    ex=dt.date.fromisoformat(date)
    frame=pl.DataFrame({"symbol":[symbol]*2,"ex_date":[ex]*2,
        "ann_date":[dt.date.fromisoformat(a) for a in ann],
        "record_date":[ex-dt.timedelta(days=1)]*2,"pay_date":[ex]*2,
        "share_list_date":[ex]*2,"div_cash":cash,"share_ratio":shares})
    result=resolve_same_day_dividends(frame)
    assert result.height==1
    assert result["div_cash"].item()==expected_cash and result["share_ratio"].item()==expected_shares
    with pytest.raises(ValueError):
        resolve_same_day_dividends(frame.with_columns((pl.col("share_ratio")+.01).alias("share_ratio")))


@pytest.mark.parametrize("symbol,ex,ann,shares,listing,expected_ann,expected_ratio", [
    ("600211.SH", "2010-09-07", ["2010-06-24", "2010-09-01"], [.1, .1],
     ["2010-09-07", "2010-09-08"], "2010-09-01", .1),
    ("000033.SZ", "2016-04-15", ["2016-04-09"] * 2, [.30454572, .3045457],
     ["2016-04-15", "2017-05-24"], "2016-04-09", .3045457),
])
def test_share_reform_preserves_final_notice_and_tradability(
    symbol, ex, ann, shares, listing, expected_ann, expected_ratio,
):
    date = dt.date.fromisoformat(ex)
    frame = pl.DataFrame({"symbol": [symbol] * 2, "ex_date": [date] * 2,
        "ann_date": [dt.date.fromisoformat(a) for a in ann],
        "record_date": [date - dt.timedelta(days=1)] * 2,
        "pay_date": [date] * 2, "div_cash": [0.] * 2, "share_ratio": shares,
        "share_list_date": [dt.date.fromisoformat(a) for a in listing]})
    result = resolve_same_day_dividends(frame)
    assert result.height == 1
    assert result["ann_date"].item() == dt.date.fromisoformat(expected_ann)
    assert result["share_list_date"].item() == dt.date.fromisoformat(listing[1])
    assert result["share_ratio"].item() == expected_ratio
    with pytest.raises(ValueError):
        resolve_same_day_dividends(frame.with_columns(
            pl.lit(date + dt.timedelta(days=1)).alias("share_list_date")))
