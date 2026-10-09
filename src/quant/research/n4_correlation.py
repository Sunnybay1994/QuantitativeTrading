"""Exact common-stock rank correlation with one candidate sort per month."""
import numpy as np
import polars as pl
from scipy.stats import rankdata


def common_support_score_ranks(score, mask):
    """Average ranks on EACH common support, including ties and missing rows.

    Sort the finite candidate once. For each tie group and reference support,
    count observations below and within the group. Its rank is below+(count+1)/2.
    This is the original pairwise re-ranking, not a rank of the full universe.
    """
    result = np.full(mask.shape, np.nan, order='F')
    if not len(score) or not mask.shape[1]:
        return result
    order = np.argsort(score, kind='stable')
    sorted_score, sorted_mask = score[order], mask[order]
    starts = np.r_[0, np.flatnonzero(sorted_score[1:] != sorted_score[:-1]) + 1]
    ends = np.r_[starts[1:] - 1, len(score) - 1]
    cumulative = np.cumsum(sorted_mask, axis=0, dtype=np.int64)
    through = cumulative[ends]
    below = np.concatenate([np.zeros((1, mask.shape[1]), dtype=np.int64), through[:-1]])
    average = (through + below + 1) / 2
    del cumulative, through, below
    repeated = np.repeat(average, np.diff(np.r_[starts, len(score)]), axis=0)
    result[order] = np.where(sorted_mask, repeated, np.nan)
    return result


def maximum_correlation(frame: pl.DataFrame, score: str, controls: list[str], minimum: int = 100) -> float:
    totals = np.zeros(len(controls))
    counts = np.zeros(len(controls))
    for section in frame.partition_by('trade_date'):
        values = section.select(score, *controls).to_numpy()
        values = values[np.isfinite(values[:, 0])]
        if len(values) < minimum:
            continue
        x = values[:, 1:]
        mask = np.isfinite(x)
        x = np.where(mask, x, np.nan)
        xr = rankdata(x, axis=0, nan_policy='omit')
        yr = common_support_score_ranks(values[:, 0], mask)
        n = mask.sum(axis=0)
        xc = np.where(mask, xr - np.nansum(xr, axis=0) / np.maximum(n, 1), 0.)
        yc = np.where(mask, yr - np.nansum(yr, axis=0) / np.maximum(n, 1), 0.)
        denominator = np.sqrt(np.sum(xc * xc, axis=0) * np.sum(yc * yc, axis=0))
        valid = (n >= minimum) & (denominator > 1e-12)
        rho = np.divide(np.sum(xc * yc, axis=0), denominator, out=np.zeros(len(controls)), where=valid)
        totals += np.where(valid, np.abs(rho), 0.)
        counts += valid
    qualified = counts > 0
    return float(np.max(totals[qualified] / counts[qualified])) if qualified.any() else 1.


def admission_correlation(frame, score, controls, *, engine, legacy):
    """A missing engine remains legacy; only newly frozen N4 runs opt in."""
    if engine == 'legacy':
        return legacy(frame, score, controls)
    if engine != 'pairwise_sorted_counts_v1':
        raise ValueError('Unknown N4 correlation engine')
    return maximum_correlation(frame, score, controls)
