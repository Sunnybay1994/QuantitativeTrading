"""Common complete-case inputs and fixed annual multi-factor models."""
import datetime as dt
import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

if TYPE_CHECKING:
    from lightgbm import LGBMRegressor

def common_features(*, statistics: Path, factors: list[str], variant: str,
                    start: dt.date, end: dt.date, minimum_symbols: int,
                    statistics_sources: dict[str, list[Path]] | None = None,
                    missing_policy: str = 'common_complete_case_pool_for_all_three_methods',
                    maximum_missing_fraction: float = .3,
                    coverage: list[dict] | None = None) -> pl.DataFrame:
    """Use the battery's already standardized scores, on one shared stock pool."""
    if not factors or len(factors) != len(set(factors)) or minimum_symbols < 1:
        raise ValueError('Require unique model factors and a positive stock minimum')
    impute = missing_policy == 'neutral_zero_with_monthly_factor_exclusion'
    if missing_policy not in {'common_complete_case_pool_for_all_three_methods',
                              'neutral_zero_with_monthly_factor_exclusion'}:
        raise ValueError('Unknown model missing-feature policy')
    if impute and (variant != 'size_industry_neutral' or not 0 <= maximum_missing_fraction < 1):
        raise ValueError('Neutral-zero filling requires neutral scores and a valid missing fraction')
    frames = []
    keys = ['symbol', 'trade_date']
    for factor in factors:
        roots = (statistics_sources or {}).get(factor, [statistics])
        frame = pl.concat([pl.scan_parquet(root/'factors'/factor/'monthly_scores.parquet').filter(
            pl.col('trade_date').is_between(start, end)).select(
                *keys, pl.col(variant).alias(factor)).collect() for root in roots])
        if frame.select(keys).is_duplicated().any():
            raise ValueError('Duplicate monthly factor keys')
        frames.append(frame if impute else frame.filter(pl.col(factor).is_finite()))
    if impute:
        dates = sorted({day for frame in frames for day in frame['trade_date']})
        pool = pl.concat([pl.scan_parquet(path).filter(pl.col('eligible') &
            pl.col('trade_date').is_in(dates)).select(keys).collect()
            for path in sorted((statistics/'inputs').glob('*/universe.parquet'))])
        return neutral_missing_features(pool=pool, frames=frames, factors=factors,
            maximum_missing_fraction=maximum_missing_fraction, minimum_symbols=minimum_symbols, coverage=coverage)
    panel = frames[0]
    for frame in frames[1:]:
        panel = panel.join(frame, on=keys, validate='1:1')
    return panel.filter(pl.len().over('trade_date') >= minimum_symbols).sort('trade_date', 'symbol')


def neutral_missing_features(*, pool: pl.DataFrame, frames: list[pl.DataFrame],
                             factors: list[str], maximum_missing_fraction: float,
                             minimum_symbols: int, coverage: list[dict] | None = None) -> pl.DataFrame:
    """Apply the same eligible-pool missing policy to training and frozen forecasts."""
    if not 0 <= maximum_missing_fraction < 1 or minimum_symbols < 1:
        raise ValueError('Invalid missing fraction or stock minimum')
    keys = ['symbol', 'trade_date']
    if pool.select(keys).is_duplicated().any():
        raise ValueError('Duplicate eligible model universe keys')
    panel = pool
    for factor, frame in zip(factors, frames, strict=True):
        panel = panel.join(frame, on=keys, how='left', validate='1:1')
        finite = pl.col(factor).is_finite().fill_null(False)
        active = finite.sum().over('trade_date') >= (
            pl.len().over('trade_date')*(1-maximum_missing_fraction))
        if coverage is not None:
            monthly = panel.group_by('trade_date').agg(pl.len().alias('eligible_stocks'),
                finite.sum().alias('observed_stocks')).with_columns(
                    (1-pl.col('observed_stocks')/pl.col('eligible_stocks')).alias('missing_fraction'),
                    (pl.col('observed_stocks') >= pl.col('eligible_stocks')*(1-maximum_missing_fraction)).alias('active'))
            coverage.extend({'factor': factor, **row} for row in monthly.sort('trade_date').to_dicts())
        panel = panel.with_columns(active.alias(f'__active_{factor}')).with_columns(
            pl.when(finite & pl.col(f'__active_{factor}')).then(pl.col(factor)).otherwise(0.).alias(factor))
    return panel.filter(pl.any_horizontal([pl.col(f'__active_{f}') for f in factors]) &
        (pl.len().over('trade_date') >= minimum_symbols)).sort('trade_date', 'symbol')


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


def validate_active_features(frame: pl.DataFrame, factors: list[str], *, required: bool = False) -> None:
    """Validate the saved monthly exclusions before fitting or predicting."""
    flags = [f'__active_{f}' for f in factors]
    if (required
            and not all(name in frame.columns for name in flags)):
        raise ValueError('Monthly exclusion policy requires its saved factor flags')
    if any(name in frame.columns for name in flags):
        if not all(name in frame.columns for name in flags):
            raise ValueError('Require all monthly factor exclusion flags')
        if (any(frame.schema[name] != pl.Boolean or frame[name].null_count() for name in flags)
                or frame.filter(~pl.any_horizontal(flags)).height
                or any(frame.filter((pl.col(flag).n_unique().over('trade_date') != 1)
                    | (~pl.col(flag) & (pl.col(factor) != 0))).height
                    for factor, flag in zip(factors, flags, strict=True))):
            raise ValueError('Invalid monthly factor exclusion flags or nonzero excluded scores')


def fit_predict(*, training: pl.DataFrame, prediction: pl.DataFrame, factors: list[str],
                mean_ic: dict[str, float], cutoff: dt.date, settings: dict) -> tuple[pl.DataFrame, dict, 'LGBMRegressor']:
    """Fit LightGBM on known labels; return all three predictions on identical rows."""
    from lightgbm import LGBMRegressor

    if not factors or len(factors) != len(set(factors)) or training.is_empty():
        raise ValueError('Model training requires nonempty known history and unique factors')
    for frame in (training, prediction):
        if (frame.select('symbol', 'trade_date').is_duplicated().any()
                or frame.filter(~pl.all_horizontal([pl.col(f).is_finite().fill_null(False) for f in factors])).height):
            raise ValueError('Models require unique complete finite feature rows')
        validate_active_features(frame, factors,
            required=settings.get('missing_features') == 'neutral_zero_with_monthly_factor_exclusion')
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
    active_columns = [f'__active_{f}' for f in factors]
    if all(name in prediction.columns for name in active_columns):
        mask = prediction.select(active_columns).to_numpy().astype(float)
        equal = values.sum(axis=1)/mask.sum(axis=1)
        ic = (values @ weights)/(mask @ weights)
    else:
        equal, ic = values.mean(axis=1), values @ weights
    result = prediction.select('symbol', 'trade_date').with_columns(
        pl.Series('equal_z', equal), pl.Series('positive_mean_ic', ic),
        pl.Series('lightgbm', forecast))
    metadata = {'factors': factors, 'training_rows': training.height,
        'training_months': training['trade_date'].n_unique(), 'last_known_exit': str(training['exit_date_rebalance'].max()),
        'refit_close': str(cutoff), 'prediction_rows': prediction.height,
        'positive_mean_ic_weights': dict(zip(factors, weights.tolist(), strict=True)),
        'missing_features': settings.get('missing_features', 'common_complete_case_pool_for_all_three_methods'),
        'monthly_exclusion_encoding': ('Linear weights renormalized over active factors; annual LightGBM schema retained with inactive columns neutralized to zero'
            if all(name in prediction.columns for name in active_columns) else None)}
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
