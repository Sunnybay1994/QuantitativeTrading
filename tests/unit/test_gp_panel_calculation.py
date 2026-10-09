import datetime as dt

import polars as pl

from quant.data.factor_panels import panel_ready, write_panel
from quant.research.gp_full_context import VERSION


def test_versioned_gp_panel_without_stamp_is_recomputed(tmp_path):
    frame = pl.DataFrame({
        "trade_date": [dt.date(2019, 12, 31)],
        "ts_code": ["002481.SZ"],
        "value": [None],
    })
    write_panel(tmp_path, "ngp_example", 2019, frame, dt.date(2019, 1, 1), dt.date(2019, 12, 31))
    assert panel_ready(tmp_path, "ngp_example", 2019, dt.date(2019, 1, 1), dt.date(2019, 12, 31))
    assert not panel_ready(
        tmp_path, "ngp_example", 2019, dt.date(2019, 1, 1), dt.date(2019, 12, 31),
        calculation=VERSION,
    )
    write_panel(
        tmp_path, "ngp_example", 2019, frame.with_columns(pl.lit(0.1).alias("value")),
        dt.date(2019, 1, 1), dt.date(2019, 12, 31), calculation=VERSION,
    )
    assert panel_ready(
        tmp_path, "ngp_example", 2019, dt.date(2019, 1, 1), dt.date(2019, 12, 31),
        calculation=VERSION,
    )
