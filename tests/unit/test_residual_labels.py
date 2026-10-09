"""B1: residual labels are orthogonal to controls within each cross-section."""
import datetime as dt

import numpy as np
import polars as pl

from quant.data.model_forecast_labels import residual_labels


def test_residual_labels_orthogonal_to_controls():
    dates = [dt.date(2024, 1, 31), dt.date(2024, 2, 29)]
    rows = []
    rng = np.random.default_rng(0)
    for day in dates:
        for i in range(80):
            q10 = float(rng.normal())
            size = float(rng.normal())
            noise = float(rng.normal())
            # label depends on q10/size plus noise
            label = 0.5 * q10 - 0.3 * size + noise
            rows.append({
                "symbol": f"{i:06d}.SZ",
                "trade_date": day,
                "label": label,
                "q10_score": q10,
                "log_size": size,
                "industry_l1": "A" if i % 2 == 0 else "B",
            })
    frame = pl.DataFrame(rows)
    labels = frame.select("symbol", "trade_date", "label")
    controls = frame.select("symbol", "trade_date", "q10_score", "log_size", "industry_l1")
    resid = residual_labels(
        labels,
        controls,
        control_columns=["q10_score", "log_size"],
        industry_column="industry_l1",
        minimum_symbols=20,
    )
    joined = resid.join(controls, on=["symbol", "trade_date"])
    for (day,), section in joined.partition_by("trade_date", as_dict=True).items():
        y = section["label"].to_numpy()
        for col in ("q10_score", "log_size"):
            x = section[col].to_numpy()
            # Correlation with residual should be near zero after OLS.
            corr = np.corrcoef(y, x)[0, 1]
            assert abs(corr) < 1e-6, (day, col, corr)
