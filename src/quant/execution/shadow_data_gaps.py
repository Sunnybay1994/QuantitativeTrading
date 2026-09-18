"""Group missing shadow observations and distinguish source limitations from gaps."""
import polars as pl


def summarize_gaps(detail: pl.DataFrame, *, etf_minute_source: str = 'yahoo') -> tuple[pl.DataFrame, dict]:
    missing = detail.filter(pl.col('status') == 'missing')
    keys = ['asset_type', 'symbol', 'execution_date', 'horizon', 'reason']
    gaps = missing.group_by(keys).agg(pl.len().alias('affected_observations'),
        pl.col('account').n_unique().alias('affected_accounts')).sort(keys)
    # Yahoo lacks turnover; a TDX missing value is a different data-quality issue.
    unavailable = (pl.lit(etf_minute_source == 'yahoo') & (pl.col('asset_type') == 'etf')
                   & (pl.col('reason') == 'missing_or_invalid_minute_turnover'))
    gaps = gaps.with_columns(
        pl.when(unavailable).then(pl.lit('source_amount_unavailable'))
        .when(pl.col('reason').str.contains('minute_window')).then(pl.lit('minute_coverage'))
        .when(pl.col('reason') == 'no_traded_volume').then(pl.lit('no_trade_observed'))
        .when(pl.col('reason').str.contains('daily_open|signal_price')).then(pl.lit('price_input'))
        .otherwise(pl.lit('invalid_turnover_or_price')).alias('gap_class'),
        pl.when(unavailable).then(pl.lit('Use a source with actual turnover; do not synthesize amount'))
        .otherwise(pl.lit('Inspect local coverage and source evidence before a bounded targeted recovery')).alias('next_action'),
        pl.when(unavailable).then(pl.lit(False)).otherwise(pl.lit(None, dtype=pl.Boolean)).alias('same_source_retry_useful'))
    counts = gaps.group_by('gap_class').agg(pl.len().alias('unique_windows'),
        pl.col('affected_observations').sum()).sort('gap_class').to_dicts()
    return gaps, {'missing_observations': missing.height, 'unique_windows': gaps.height,
        'by_class': counts,
        'automatic_fetch_attempts': 0,
        'policy': 'Classify first. Known source field limitations do not trigger retries. Recovery must use a bounded explicit source/date list.',
        'resolved': missing.is_empty()}
