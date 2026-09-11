"""Local signal-date inputs for the fixed research model; never read labels."""
import datetime as dt
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_industry, read_factor_inputs
from quant.research.factor_battery_universe import prepare_battery_universe


def read_forward_values(*, data_root: Path, factors: list[str], as_of: dt.date) -> dict[str, pl.DataFrame]:
    return {factor: pl.scan_parquet(data_root/'factors'/factor/f'year={as_of.year}'/'data.parquet')
        .filter(pl.col('trade_date') == as_of).select(pl.col('ts_code').alias('symbol'), 'trade_date', 'value')
        .collect() for factor in factors}


def read_model_monthly_values(*, data_root: Path, factor: str, dates: list[dt.date]) -> pl.DataFrame:
    if not dates or len({day.year for day in dates}) != 1:
        raise ValueError('Require signal dates within one year')
    return pl.scan_parquet(data_root/'factors'/factor/f'year={dates[0].year}'/'data.parquet').filter(
        pl.col('trade_date').is_in(dates)).select(pl.col('ts_code').alias('symbol'), 'trade_date', 'value').collect()


def read_forward_universe(*, data_root: Path, settings: dict, as_of: dt.date) -> pl.DataFrame:
    sessions = available_sessions(data_root, as_of)
    window = settings['universe']['amount_window_sessions']
    if not sessions or sessions[-1] != as_of or len(sessions) < window:
        raise ValueError('Require a completed signal session and liquidity history')
    panel, bars = read_factor_inputs(data_root, Path(settings['data']['refresh_config']),
                                    sessions[-window], as_of, sessions)
    folder = data_root/'clean/stock_paper_inputs'/f'date={as_of}'
    universe = prepare_battery_universe(bars, pl.read_parquet(folder/'instruments.parquet'),
        pl.read_parquet(data_root/'clean/stock_name_history/data.parquet'),
        pl.read_parquet(folder/'limits.parquet'), sessions=sessions,
        **{key: settings['universe'][key] for key in ('minimum_listing_days',
            'amount_window_sessions', 'amount_exclude_bottom_fraction')})
    controls = read_factor_industry(data_root, panel.filter(pl.col('trade_date') == as_of))
    return universe.filter(pl.col('trade_date') == as_of).join(
        controls.select('symbol', 'trade_date', 'total_market_value', 'industry_l1'),
        on=['symbol', 'trade_date'], how='left', validate='1:1')
