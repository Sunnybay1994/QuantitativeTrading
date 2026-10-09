"""Daily execution rejections, including partially affordable fixed share orders."""
import pandera.polars as pa
import polars as pl


class BacktestRejectionSchema(pa.DataFrameModel):
    strategy: str  # type: ignore[assignment]
    date: pl.Date
    symbol: str = pa.Field(str_matches=r'^\d{5,6}\.(SH|SZ|HK)$')
    side: str = pa.Field(isin=['BUY', 'SELL'])
    # OPEN_UNKNOWN: the session has no observed tradable bar and no suspension
    # record, so the simulator declines both sides rather than inventing a fill.
    reason: str = pa.Field(isin=['SUSPENDED', 'OPEN_UNKNOWN', 'BUY_AT_UPPER_LIMIT', 'SELL_AT_LOWER_LIMIT',
                               'T_PLUS_ONE', 'CASH_CONSTRAINT', 'LOT_CONSTRAINT', 'INSUFFICIENT_SELLABLE',
                               'PARTICIPATION_CAP'])
    requested_quantity: int = pa.Field(gt=0)
    rejected_quantity: int = pa.Field(gt=0)
    reference_price: float = pa.Field(gt=0)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def rejection_valid(cls, data: pa.PolarsData) -> pl.LazyFrame:  # type: ignore[misc]
        side_matches = (
            pl.col('reason').is_in(['SUSPENDED', 'OPEN_UNKNOWN', 'LOT_CONSTRAINT', 'PARTICIPATION_CAP'])
            | (pl.col('reason').is_in(['BUY_AT_UPPER_LIMIT', 'CASH_CONSTRAINT']) & (pl.col('side') == 'BUY'))
            | (pl.col('reason').is_in(['SELL_AT_LOWER_LIMIT', 'T_PLUS_ONE', 'INSUFFICIENT_SELLABLE'])
               & (pl.col('side') == 'SELL')))
        quantity_valid = pl.when(pl.col('reason').is_in(['CASH_CONSTRAINT', 'PARTICIPATION_CAP'])).then(
            pl.col('requested_quantity') >= pl.col('rejected_quantity')).otherwise(
                pl.col('requested_quantity') == pl.col('rejected_quantity'))
        return data.lazyframe.select((quantity_valid.all() & side_matches.all()
            & pl.col('reference_price').is_finite().all()
            & ~pl.struct(['strategy', 'date', 'symbol', 'side', 'reason']).is_duplicated().any()).alias('rejection_valid'))
