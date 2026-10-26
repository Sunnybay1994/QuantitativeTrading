import datetime as dt

import polars as pl

from quant.research.multi_mechanism_family import build_scores, load_config


def test_frozen_members_and_equal_z(tmp_path):
    spec = load_config()
    assert [row["id"] for row in spec["factors"]] == [
        "max_daily_return_20", "free_float_turnover_level_monthly", "daily_ep_ttm_positive",
    ]
    assert [row["id"] for row in spec["members"]] == ["M1", "M2", "M3", "M4"]
    day = dt.date(2020, 1, 31)
    stats = tmp_path / "statistics" / "factors"
    for name, values in (
        ("max_daily_return_20", [1.0, 3.0]),
        ("free_float_turnover_level_monthly", [10.0, 30.0]),
        ("daily_ep_ttm_positive", [0.1, 0.3]),
    ):
        folder = stats / name
        folder.mkdir(parents=True)
        pl.DataFrame({
            "symbol": ["A", "B"],
            "trade_date": [day, day],
            "size_industry_neutral": values,
        }).write_parquet(folder / "monthly_scores.parquet")
    pred = tmp_path / "predictions"
    pred.mkdir()
    pl.DataFrame({
        "symbol": ["A", "B"],
        "trade_date": [day, day],
        "lightgbm": [0.0, 2.0],
    }).write_parquet(pred / "monthly_predictions.parquet")
    tiny = dict(spec)
    tiny["statistics"] = str(tmp_path / "statistics")
    tiny["predictions"] = str(pred)
    scores = build_scores(tiny, include_sue=True, statistics=tmp_path / "statistics", predictions=pred)
    assert scores.columns == ["symbol", "trade_date", "lightgbm", "test_year"]
    # Each column is a two-point z of ±1, equal weight stays ±1.
    by_symbol = dict(zip(scores["symbol"].to_list(), scores["lightgbm"].to_list()))
    assert by_symbol["A"] < 0 < by_symbol["B"]
    without = build_scores(tiny, include_sue=False, statistics=tmp_path / "statistics", predictions=pred)
    assert without.height == 2
