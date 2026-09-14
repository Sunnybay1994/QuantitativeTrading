"""Published point-in-time risk descriptors; all data/ reads stay here."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

STYLE_FACTORS = {
    'value': 'book_to_price', 'momentum': 'pret_12m_skip1m',
    'volatility': 'realized_volatility_60',
    'liquidity': 'free_float_turnover_level_monthly_calendar80_v1',
    'profitability': 'pit_roe_ttm', 'growth': 'pit_revenue_growth_ttm',
    'leverage': 'pit_liabilities_to_assets', 'beta': 'market_beta_60_vs_510300',
    'reversal': 'reversal_20',
}


def standardize(frame: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    """Eligible cross-section 1/99 winsorized population z; gaps remain null."""
    for name in columns:
        sample = pl.col(name).filter(pl.col('eligible') & pl.col(name).is_finite())
        bounds = frame.group_by('trade_date').agg(sample.quantile(.01).alias('_lo'),
                                                    sample.quantile(.99).alias('_hi'))
        frame = frame.join(bounds, on='trade_date', validate='m:1').with_columns(
            pl.when(pl.col(name).is_finite()).then(pl.col(name).clip(pl.col('_lo'), pl.col('_hi'))).alias(name)
        ).drop('_lo', '_hi')
        stats = frame.group_by('trade_date').agg(sample.mean().alias('_mean'), sample.std(ddof=0).alias('_std'))
        frame = frame.join(stats, on='trade_date', validate='m:1').with_columns(
            pl.when(pl.col('_std') > 1e-12).then((pl.col(name)-pl.col('_mean'))/pl.col('_std')).alias(name)
        ).drop('_mean', '_std')
    return frame


def load_risk_controls(*, data_root: Path, statistics: Path, start: dt.date, end: dt.date) -> pl.DataFrame:
    """Signal-close size z, historical SW L1 and ADV20 in CNY, without imputation."""
    del data_root  # Frozen published universe contains these clean-derived controls.
    frames = []
    for year in range(start.year, end.year+1):
        frame = pl.scan_parquet(statistics/f'inputs/{year}/universe.parquet').filter(
            pl.col('trade_date').is_between(start, end)).select('symbol', 'trade_date', 'eligible',
            'industry_l1', 'total_market_value', pl.col('amount20').alias('adv20')).collect()
        frames.append(frame)
    frame = pl.concat(frames, how='vertical_relaxed').with_columns(
        pl.when(pl.col('total_market_value') > 0).then(pl.col('total_market_value').log()).alias('size'))
    return standardize(frame, ['size']).sort('trade_date', 'symbol')


def load_risk_year(*, data_root: Path, statistics: Path, year: int) -> pl.DataFrame:
    """Daily exposures and adjusted closes, using existing PIT factor publication."""
    frame = load_risk_controls(data_root=data_root, statistics=statistics,
                              start=dt.date(year, 1, 1), end=dt.date(year, 12, 31))
    for style, factor in STYLE_FACTORS.items():
        values = pl.scan_parquet(data_root/f'factors/{factor}/year={year}/data.parquet').select(
            pl.col('ts_code').alias('symbol'), 'trade_date', pl.col('value').alias(style)).collect()
        frame = frame.join(values, on=['symbol', 'trade_date'], how='left', validate='1:1')
    prices = pl.scan_parquet(statistics/f'inputs/{year}/universe.parquet').select('symbol', 'trade_date',
        (pl.col('close')*pl.col('adj_factor')).alias('adjusted_close')).collect()
    return standardize(frame, list(STYLE_FACTORS)).join(prices, on=['symbol', 'trade_date'], validate='1:1')
