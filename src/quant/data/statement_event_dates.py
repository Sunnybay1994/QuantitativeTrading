"""Independent first-statement date checks; SUE validity is not event validity."""
import polars as pl


def validate_statement_dates(history: pl.DataFrame, legacy_events: pl.DataFrame) -> pl.DataFrame:
    required={'symbol','ann_date','f_ann_date','available_date','end_date','report_type','comp_type',
              'n_income','n_income_attr_p'}
    if not required<=set(history.columns):
        raise ValueError('Statement date inputs missing')
    first=history.filter(pl.col('report_type')=='1')
    if first.select(pl.any_horizontal(pl.col(c).is_null() for c in ['symbol','end_date','available_date']).any()).item():
        raise ValueError('Statement event identity missing')
    minimum=first.group_by('symbol','end_date').agg(pl.col('available_date').min())
    first=first.join(minimum,on=['symbol','end_date','available_date'],how='inner')
    first=first.group_by('symbol','end_date','available_date').agg(
        (pl.col('ann_date').is_not_null() & pl.col('f_ann_date').is_not_null()
         & (pl.col('ann_date')==pl.col('f_ann_date')) & (pl.col('ann_date')==pl.col('available_date'))).all().alias('dates_agree'),
        pl.col('comp_type').n_unique().alias('company_types'),
        pl.struct('n_income','n_income_attr_p').n_unique().alias('first_value_versions'))
    # A later first disclosure of an older period does not become fresh earnings.
    first=first.sort('symbol','available_date','end_date').with_columns(
        pl.col('end_date').cum_max().over('symbol').alias('latest_period'))
    first=first.with_columns(pl.col('end_date').max().over('symbol','available_date').alias('same_day_latest'))
    first=first.filter(pl.col('end_date')==pl.col('same_day_latest')).rename({'available_date':'announcement_date'})
    if legacy_events.select('symbol','announcement_date').is_duplicated().any():
        raise ValueError('Legacy event identities duplicated')
    old=legacy_events.select('symbol','announcement_date',pl.col('status').alias('legacy_sue_status'))
    first=first.join(old,on=['symbol','announcement_date'],how='left',validate='1:1')
    quarter=(pl.col('end_date').dt.month().is_in([3,6,9,12]) &
             (pl.col('end_date')==pl.col('end_date').dt.month_end()))
    delay=(pl.col('announcement_date')-pl.col('end_date')).dt.total_days()
    return first.with_columns(
        pl.when(pl.col('legacy_sue_status')=='QUARANTINED').then(pl.lit('legacy_quarantine_retained'))
        .when(~pl.col('dates_agree')).then(pl.lit('announcement_date_disagreement'))
        .when(~quarter | ~delay.is_between(0,180)).then(pl.lit('invalid_period_or_disclosure_delay'))
        .when(pl.col('end_date')!=pl.col('latest_period')).then(pl.lit('older_than_latest_disclosed_period'))
        .when((pl.col('company_types')!=1)|(pl.col('first_value_versions')!=1)).then(pl.lit('ambiguous_first_disclosure'))
        .otherwise(pl.lit('date_checks_passed')).alias('event_date_status')
    ).with_columns((pl.col('event_date_status')=='date_checks_passed').alias('event_date_valid')).sort('symbol','announcement_date')
