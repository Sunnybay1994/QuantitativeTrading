"""Unit tests for B2 q10_plus_admitted score combination (no full replay)."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.research.q10_plus_admitted import build_combined_scores, trailing_incremental_weights


def _panel(n_dates: int = 3, n_sym: int = 120) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    dates = [dt.date(2020, m, 28) for m in range(1, n_dates + 1)]
    symbols = [f"{i:06d}.SZ" for i in range(n_sym)]
    rows_q, rows_f, rows_l = [], [], []
    for d in dates:
        for i, s in enumerate(symbols):
            rows_q.append({"symbol": s, "trade_date": d, "q10_score": float(i)})
            rows_f.append({"symbol": s, "trade_date": d, "ngp_a": float(i + (1 if d.month == 1 else 0))})
            rows_l.append({"symbol": s, "trade_date": d, "label": float(i) * 0.01})
    return pl.DataFrame(rows_q), pl.DataFrame(rows_f), pl.DataFrame(rows_l)


def test_trailing_weights_sign_and_magnitude():
    q10, factors, labels = _panel()
    weights = trailing_incremental_weights(
        q10=q10, factors=factors, labels=labels, factor_ids=["ngp_a"],
        as_of=dt.date(2020, 3, 28), lookback_months=48,
    )
    assert set(weights) == {"ngp_a"}
    assert abs(weights["ngp_a"]) in {0.0, 1.0}


def test_build_combined_scores(tmp_path: Path):
    dates = [dt.date(2020, 1, 31), dt.date(2020, 2, 28)]
    symbols = [f"{i:06d}.SZ" for i in range(10)]
    pred = pl.DataFrame([
        {"symbol": s, "trade_date": d, "lightgbm": float(i)}
        for d in dates for i, s in enumerate(symbols)
    ])
    pred_dir = tmp_path / "pred"
    pred_dir.mkdir()
    pred.write_parquet(pred_dir / "monthly_predictions.parquet")
    stats = tmp_path / "statistics" / "factors" / "ngp_a"
    stats.mkdir(parents=True)
    pl.DataFrame([
        {"symbol": s, "trade_date": d, "raw": float(i), "size_industry_neutral": float(i)}
        for d in dates for i, s in enumerate(symbols)
    ]).write_parquet(stats / "monthly_scores.parquet")
    scores = build_combined_scores(
        q10_predictions=pred_dir,
        q10_score_column="lightgbm",
        statistics=tmp_path / "statistics",
        factor_ids=["ngp_a"],
        weights={"ngp_a": 1.0},
        score_variant="size_industry_neutral",
    )
    assert "q10_plus_admitted" in scores.columns
    assert "q10_control" in scores.columns
    assert scores.height == 20
    # With weight 1 and identical ranking, combined equals 2 * q10_z on complete sample.
    day = scores.filter(pl.col("trade_date") == dates[0]).sort("symbol")
    assert abs(day["q10_plus_admitted"][0] - 2 * day["q10_control"][0]) < 1e-9
