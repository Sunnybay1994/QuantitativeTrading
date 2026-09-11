"""Common complete-case inputs and fixed annual multi-factor models."""
import datetime as dt
import math
from pathlib import Path

import numpy as np
import polars as pl


def common_features(*, statistics: Path, factors: list[str], variant: str,
                    start: dt.date, end: dt.date, minimum_symbols: int,
                    statistics_sources: dict[str, list[Path]] | None = None) -> pl.DataFrame:
    """Use the battery's already standardized scores, on one shared stock pool."""
    if not factors or len(factors) != len(set(factors)) or minimum_symbols < 1:
        raise ValueError('Require unique model factors and a positive stock minimum')
    frames = []
    keys = ['symbol', 'trade_date']
    for factor in factors:
        roots = (statistics_sources or {}).get(factor, [statistics])
        frame = pl.concat([pl.scan_parquet(root/'factors'/factor/'monthly_scores.parquet').filter(
            pl.col('trade_date').is_between(start, end) & pl.col(variant).is_finite()).select(
                *keys, pl.col(variant).alias(factor)).collect() for root in roots])
        if frame.select(keys).is_duplicated().any():
            raise ValueError('Duplicate monthly factor keys')
        frames.append(frame)
    panel = frames[0]
    for frame in frames[1:]:
        panel = panel.join(frame, on=keys, validate='1:1')
    return panel.filter(pl.len().over('trade_date') >= minimum_symbols).sort('trade_date', 'symbol')


def training_panel(*, features: pl.DataFrame, statistics: Path,
                   cutoff: dt.date, minimum_symbols: int) -> pl.DataFrame:
    labels = pl.concat([pl.scan_parquet(path).filter(pl.col('exit_date_rebalance') <= cutoff).select(
        'symbol', 'trade_date', 'exit_date_rebalance', 'label_rebalance').collect()
        for path in sorted((statistics/'inputs').glob('*/monthly_labels.parquet'))], how='vertical_relaxed')
    if labels.filter(pl.col('exit_date_rebalance') <= pl.col('trade_date')).height:
        raise ValueError('Training outcome must follow its signal')
    joined = features.join(labels, on=['symbol', 'trade_date'], validate='1:1').filter(
        pl.col('label_rebalance').is_finite())
    return joined.filter(pl.len().over('trade_date') >= minimum_symbols).sort('trade_date', 'symbol')


def fit_predict(*, training: pl.DataFrame, prediction: pl.DataFrame, factors: list[str],
                mean_ic: dict[str, float], cutoff: dt.date, settings: dict) -> tuple[pl.DataFrame, dict, object]:
    """Fit LightGBM on known labels; return all three predictions on identical rows."""
    from lightgbm import LGBMRegressor

    if not factors or len(factors) != len(set(factors)) or training.is_empty():
        raise ValueError('Model training requires nonempty known history and unique factors')
    for frame in (training, prediction):
        if (frame.select('symbol', 'trade_date').is_duplicated().any()
                or frame.filter(~pl.all_horizontal([pl.col(f).is_finite().fill_null(False) for f in factors])).height):
            raise ValueError('Models require unique complete finite feature rows')
    if (training.filter(pl.col('exit_date_rebalance').is_null()
            | (pl.col('exit_date_rebalance') > cutoff)
            | (pl.col('exit_date_rebalance') <= pl.col('trade_date'))
            | ~pl.col('label_rebalance').is_finite().fill_null(False)).height
            or prediction.filter(pl.col('trade_date') < cutoff).height):
        raise ValueError('Training or prediction crosses the annual information boundary')
    weights = np.array([mean_ic[f] for f in factors], dtype=float)
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError('Positive-IC weights require finite positive training means')
    weights /= weights.sum()
    regressor = LGBMRegressor(**settings['lightgbm'])
    regressor.fit(training.select(factors).to_numpy(), training['label_rebalance'].to_numpy())
    values = prediction.select(factors).to_numpy()
    forecast = regressor.booster_.predict(values) if prediction.height else np.array([], dtype=float)
    result = prediction.select('symbol', 'trade_date').with_columns(
        pl.Series('equal_z', values.mean(axis=1)), pl.Series('positive_mean_ic', values @ weights),
        pl.Series('lightgbm', forecast))
    metadata = {'factors': factors, 'training_rows': training.height,
        'training_months': training['trade_date'].n_unique(), 'last_known_exit': str(training['exit_date_rebalance'].max()),
        'refit_close': str(cutoff), 'prediction_rows': prediction.height,
        'positive_mean_ic_weights': dict(zip(factors, weights.tolist(), strict=True))}
    return result, metadata, regressor


def buffered_model_targets(scores: pl.DataFrame, *, method: str, sessions: tuple[dt.date, ...],
                           start: dt.date, end: dt.date, top_k: int,
                           minimum_symbols: int, retention_multiplier: float) -> pl.DataFrame:
    """Carry the target buffer across refits and explicitly liquidate empty pools."""
    if (top_k < 1 or minimum_symbols < top_k or not math.isfinite(retention_multiplier)
            or retention_multiplier < 1 or tuple(sorted(set(sessions))) != sessions
            or scores.select('symbol', 'trade_date').is_duplicated().any()):
        raise ValueError('Invalid monthly model target inputs')
    previous: set[str] = set()
    cash_anchor = None
    rows = []
    retention = math.floor(top_k*retention_multiplier)
    for signal, execution in zip(sessions, sessions[1:]):
        if not start <= execution <= end or (signal >= start and signal.month == execution.month):
            continue
        ranked = scores.filter((pl.col('trade_date') == signal) & pl.col(method).is_finite()).sort(
            [method, 'symbol'], descending=[True, False])
        selected: set[str] = set()
        if ranked.height >= minimum_symbols:
            retained = ranked.head(retention).filter(pl.col('symbol').is_in(sorted(previous)))['symbol'].to_list()
            entrants = ranked.filter(~pl.col('symbol').is_in(retained)).head(top_k-len(retained))['symbol'].to_list()
            selected = set(retained+entrants)
        changed = previous | selected
        if changed:
            cash_anchor = min(changed)
        elif cash_anchor is not None:
            changed = {cash_anchor}
        for symbol in sorted(changed):
            rows.append({'as_of': signal, 'execution_date': execution, 'symbol': symbol,
                'weight': 1/top_k if symbol in selected else 0.,
                'strategy': f'p4_{method}_top{top_k}', 'strategy_version': '1'})
        previous = selected
    return pl.DataFrame(rows, schema={'as_of': pl.Date, 'execution_date': pl.Date, 'symbol': pl.String,
        'weight': pl.Float64, 'strategy': pl.String, 'strategy_version': pl.String})
