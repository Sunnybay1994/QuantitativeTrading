import datetime as dt

import polars as pl
from polars.testing import assert_frame_equal

from quant.research.factor_battery_universe import prepare_battery_universe


def test_universe_respects_known_names_limits_age_gaps_and_liquidity():
    dates = tuple(dt.date(2020,1,1)+dt.timedelta(days=i) for i in range(30))
    symbols = [f"{600000+i}.SH" for i in range(20)]
    rows = []
    for index,symbol in enumerate(symbols):
        for offset,date in enumerate(dates):
            if index==2 and offset==5:
                continue
            rows.append(dict(symbol=symbol,trade_date=date,close=11.0 if index==4 else 10.0,
                volume=0.0 if index==3 else 100.0,amount=float((index+1)*10000)))
    bars = pl.DataFrame(rows)
    instruments = pl.DataFrame({"symbol":symbols,
        "list_date":[dates[0] if i==1 else dt.date(2010,1,1) for i in range(20)],
        "delist_date":[dates[19] if i==5 else None for i in range(20)],
        "instrument_type":["STOCK"]*20})
    names = pl.DataFrame({"symbol":[s for s in symbols if s!=symbols[6]],
        "name":["normal"]*19,"start_date":[dt.date(2010,1,1)]*19,
        "ann_date":[dt.date(2010,1,1)]*19})
    change = pl.DataFrame({"symbol":[symbols[7]],"name":["*ST sample"],
        "start_date":[dates[19]],"ann_date":[dates[21]]})
    names = pl.concat([names,change])
    limits = bars.select("symbol","trade_date").with_columns(pl.lit(11.).alias("up_limit"),
        pl.lit(9.).alias("down_limit")).filter(pl.col("symbol")!=symbols[8])
    result = prepare_battery_universe(bars,instruments,names,limits,sessions=dates)
    last = result.filter(pl.col("trade_date")==dates[23])
    for index,flag in [(1,"listing_age_ok"),(3,"traded"),(4,"away_from_limits"),(5,"active_stock"),
                       (6,"name_known"),(7,"not_risk_name"),(8,"limits_known"),(0,"liquidity_ok")]:
        assert not last.filter(pl.col("symbol")==symbols[index])[flag].item()
    assert last.filter(pl.col("symbol")==symbols[2])["amount20"].item() is None
    assert last.filter(pl.col("symbol")==symbols[19])["eligible"].item()
    assert result.filter((pl.col("symbol")==symbols[7]) & (pl.col("trade_date")==dates[20]))["not_risk_name"].item()
    # A later announcement must not change any earlier classification.
    earlier = prepare_battery_universe(bars.filter(pl.col("trade_date")<=dates[20]),instruments,
        names.filter(pl.col("ann_date")<=dates[20]),limits.filter(pl.col("trade_date")<=dates[20]),
        sessions=dates)
    assert_frame_equal(earlier,result.filter(pl.col("trade_date")<=dates[20]))
