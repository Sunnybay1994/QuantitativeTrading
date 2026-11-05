"""Window-local moments: expired extremes cannot contaminate later windows."""
from __future__ import annotations

import numpy as np
import polars as pl


def rolling_moment(x: pl.Expr, n: int, kind: str, y: pl.Expr | None = None) -> pl.Expr:
    """Evaluate complete windows, centering before computing second moments.

    Bounded vectorized chunks avoid both history-dependent running accumulators
    and an unbounded windows-by-history temporary allocation.
    """
    def calculate(series: list[pl.Series]) -> pl.Series:
        # The expression engine supplies a symbol-sorted panel. Evaluate all
        # symbols in one batch, masking windows that cross a symbol boundary;
        # one Python callback per symbol makes full-market evaluation costly.
        groups = series[-1].to_numpy()
        arrays = [s.cast(pl.Float64).to_numpy() for s in series[:-1]]
        result = np.full(len(arrays[0]), np.nan)
        if len(result) < n:
            return pl.Series(result, nan_to_null=True)
        windows = [np.lib.stride_tricks.sliding_window_view(a, n) for a in arrays]
        chunk = max(1, 262144 // n)
        time = np.arange(n, dtype=float) - (n - 1) / 2
        time_ss = n * (n * n - 1) / 12
        for start in range(0, len(windows[0]), chunk):
            stop = min(start + chunk, len(windows[0]))
            blocks = [w[start:stop] for w in windows]
            complete = np.logical_and.reduce([np.isfinite(b).all(axis=1) for b in blocks])
            complete &= groups[start:stop] == groups[start+n-1:stop+n-1]
            if not complete.any():
                continue
            a = blocks[0][complete]
            delta = a - a[:, :1]
            mean_delta = delta.mean(axis=1)
            if kind in {"ts_mean", "ts_sum"}:
                value = a[:, 0] + mean_delta
                result[np.flatnonzero(complete) + start + n - 1] = value * n if kind == "ts_sum" else value
                continue
            centered = delta - mean_delta[:, None]
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                if kind == 'ts_skew':
                    # Fisher-Pearson sample skew, computed from this window only.
                    # Scaling cancels algebraically and prevents cube underflow.
                    scaled=centered/np.max(np.abs(centered),axis=1)[:,None]
                    ss=np.sum(scaled*scaled,axis=1)
                    value=n*np.sqrt(n-1)/(n-2)*np.sum(scaled**3,axis=1)/ss**1.5
                    result[np.flatnonzero(complete)+start+n-1]=value
                    continue
                if kind in {"ts_std", "ts_std0", "ts_corr", "ts_rsquare"}:
                    ss = np.sum(centered * centered, axis=1)
                if kind in {"ts_std", "ts_std0"}:
                    value = np.sqrt(ss / (n - (kind == "ts_std")))
                elif kind in {"ts_cov", "ts_corr"}:
                    b = blocks[1][complete]
                    dy = b - b[:, :1]
                    cy = dy - dy.mean(axis=1)[:, None]
                    cross = np.sum(centered * cy, axis=1)
                    value = cross / (n - 1) if kind == "ts_cov" else (
                        cross / np.sqrt(ss) / np.sqrt(np.sum(cy * cy, axis=1))
                    )
                else:
                    slope = np.sum(centered * time, axis=1) / time_ss
                    if kind == "ts_slope":
                        value = slope
                    elif kind == "ts_resi":
                        value = centered[:, -1] - slope * (n - 1) / 2
                    elif kind == "ts_rsquare":
                        value = np.where(ss / (n - 1) > 2e-5 ** 2,
                                         np.clip(slope * slope * time_ss / ss, 0, 1), np.nan)
                    else:
                        raise ValueError(f"Unsupported moment: {kind}")
            indices = np.flatnonzero(complete) + start + n - 1
            result[indices] = value
        return pl.Series(result, nan_to_null=True)

    inputs = [x] if y is None else [x, y]
    return pl.map_batches([*inputs, pl.col("symbol").rle_id()], calculate,
                          return_dtype=pl.Float64)
