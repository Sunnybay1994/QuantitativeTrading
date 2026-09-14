"""Cross-sectional WLS and strictly historical EWMA portfolio risk."""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt

import numpy as np
import polars as pl

STYLES = ['size', 'value', 'momentum', 'volatility', 'liquidity',
          'profitability', 'growth', 'leverage', 'beta', 'reversal']


def prepare_exposures(frame: pl.DataFrame) -> pl.DataFrame:
    """Disclose missing inputs, then use observable industry/market medians."""
    frame = frame.with_columns(pl.col('industry_l1').fill_null('UNKNOWN'))
    frame = frame.with_columns(pl.sum_horizontal([
        (~pl.col(c).is_finite().fill_null(False)).cast(pl.Int32) for c in STYLES
    ]).alias('imputed_styles'))
    for name in STYLES:
        frame = frame.with_columns(pl.when(pl.col(name).is_finite()).then(pl.col(name)).alias(name))
        medians = frame.filter(pl.col('eligible')).group_by('industry_l1').agg(
            pl.col(name).median().alias('_median'))
        market = frame.filter(pl.col('eligible'))[name].median()
        if market is None:
            raise ValueError(f'No observable cross-sectional median for {name}')
        frame = frame.join(medians, on='industry_l1', how='left').with_columns(
            pl.col(name).fill_null(pl.col('_median')).fill_null(market)).drop('_median')
    return frame


def design(frame: pl.DataFrame, industries: list[str]) -> np.ndarray:
    labels = frame['industry_l1'].to_numpy()
    return np.column_stack([frame.select(STYLES).to_numpy(),
                            *[(labels == name).astype(float) for name in industries]])


def fit_wls(x: np.ndarray, y: np.ndarray, market_value: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Minimize sum sqrt(cap) * residual squared; no redundant intercept."""
    weight = np.sqrt(market_value)
    weight /= np.mean(weight)
    root_weight = np.sqrt(weight)
    beta = np.linalg.lstsq(x*root_weight[:, None], y*root_weight, rcond=1e-10)[0]
    return beta, y-x@beta


@dataclass
class EWMARisk:
    dimensions: int
    factor_half_life: float = 126
    specific_half_life: float = 63
    minimum_history: int = 60
    shrinkage: float = .1
    observations: int = 0
    last_date: dt.date | None = None
    specific: dict[str, tuple[float, int]] = field(default_factory=dict)
    mean: np.ndarray = field(init=False)
    second: np.ndarray = field(init=False)
    active_industries: frozenset[str] | None = None

    def __post_init__(self) -> None:
        self.mean = np.zeros(self.dimensions)
        self.second = np.zeros((self.dimensions, self.dimensions))

    def begin_industry_regime(self, industries: set[str]) -> bool:
        """Restart factor history when effective taxonomy changes; preserve stock risk."""
        active = frozenset(industries)
        if self.active_industries == active:
            return False
        self.active_industries = active
        self.observations = 0
        self.mean.fill(0.)
        self.second.fill(0.)
        return True

    def covariance(self) -> np.ndarray | None:
        if self.observations < self.minimum_history:
            return None
        decay = 2**(-1/self.factor_half_life)
        normalizer = 1-decay**self.observations
        mean = self.mean/normalizer
        covariance = self.second/normalizer-np.outer(mean, mean)
        return (1-self.shrinkage)*covariance+self.shrinkage*np.diag(np.diag(covariance))

    def prior_specific(self, symbols: list[str]) -> tuple[np.ndarray, int]:
        seasoned = [value for value, count in self.specific.values() if count >= self.minimum_history]
        fallback = float(np.median(seasoned)) if seasoned else float('nan')
        values, proxy_count = [], 0
        for symbol in symbols:
            value, count = self.specific.get(symbol, (fallback, 0))
            if count < self.minimum_history:
                value = fallback
                proxy_count += 1
            values.append(value)
        return np.array(values), proxy_count

    def update(self, date: dt.date, factor_returns: np.ndarray, residuals: dict[str, float]) -> None:
        if self.last_date is not None and date <= self.last_date:
            raise ValueError('Risk updates must be strictly increasing in date')
        decay = 2**(-1/self.factor_half_life)
        self.mean = decay*self.mean+(1-decay)*factor_returns
        self.second = decay*self.second+(1-decay)*np.outer(factor_returns, factor_returns)
        decay_specific = 2**(-1/self.specific_half_life)
        for symbol, residual in residuals.items():
            prior, count = self.specific.get(symbol, (residual**2, 0))
            self.specific[symbol] = (decay_specific*prior+(1-decay_specific)*residual**2, count+1)
        self.observations += 1
        self.last_date = date


def tracking_error(active_weights: np.ndarray, x: np.ndarray,
                   covariance: np.ndarray, specific: np.ndarray) -> float:
    exposure = active_weights@x
    variance = exposure@covariance@exposure+np.sum(active_weights**2*specific)
    return float(np.sqrt(max(variance, 0.)*252))
