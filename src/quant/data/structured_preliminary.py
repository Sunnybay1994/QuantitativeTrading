"""Published D1 forecast/express observations for the existing SUE S4 consumer."""
import datetime as dt
from pathlib import Path

import polars as pl

NUMERIC={
    'forecast':{'net_profit_min':'forecast_profit_min_10000cny',
        'net_profit_max':'forecast_profit_max_10000cny',
        'p_change_min':'forecast_change_min_pct','p_change_max':'forecast_change_max_pct'},
    'express':{'n_income':'express_net_income_cny','revenue':'express_revenue_cny'},
}
SCHEMA={'symbol':pl.String,'announcement_date':pl.Date,'report_period_end':pl.Date,
    'available_at':pl.Datetime('us','UTC'),'observed_at':pl.Datetime('us','UTC'),
    'available_date':pl.Date,'source_table':pl.String,'source_row_id':pl.String,
    'source_raw_path':pl.String,'update_flag':pl.String,
    **{name:pl.Float64 for fields in NUMERIC.values() for name in fields.values()}}


def empty_preliminary():return pl.DataFrame(schema=SCHEMA)


def read_preliminary_history(data_root,*,known_at=None):
    """Keep ranges and distinct profit definitions; never invent a point surprise.

    Historical supplier downloads remain unavailable before their observed time.
    Only atomically published table snapshots enter the consumer.
    """
    known_at=known_at or dt.datetime.now(dt.timezone.utc)
    if known_at.tzinfo is None:raise ValueError('Require timezone-aware preliminary observation cutoff')
    known_at=known_at.astimezone(dt.timezone.utc)
    sections=[]
    for table,fields in NUMERIC.items():
        for summary in sorted((Path(data_root)/'clean'/table).glob('snapshot=*/summary.json')):
            for path in sorted(summary.parent.glob('year=*/data.parquet')):
                frame=pl.read_parquet(path)
                required={'ts_code','ann_date','end_date','available_at','observed_at','source_row_id','source_raw_path'}
                if not required<=set(frame.columns):
                    raise ValueError('Published preliminary table lacks date or provenance fields')
                invalid=(pl.col('available_at').is_null()|pl.col('observed_at').is_null()
                    |(pl.col('available_at')<pl.col('observed_at')))
                if frame.filter(invalid).height:raise ValueError('Preliminary availability precedes observation')
                frame=frame.filter(pl.col('available_at')<=known_at)
                def date_column(name):
                    column=pl.col(name)
                    return column.str.strip_chars().str.to_date('%Y%m%d',strict=False) if frame.schema[name]==pl.String else column.cast(pl.Date)
                numeric=[]
                for source,target in fields.items():
                    value=pl.col(source).cast(pl.Float64,strict=False) if source in frame.columns else pl.lit(None,dtype=pl.Float64)
                    numeric.append(pl.when(value.is_finite()).then(value).otherwise(None).alias(target))
                part=frame.select(pl.col('ts_code').alias('symbol'),date_column('ann_date').alias('announcement_date'),
                    date_column('end_date').alias('report_period_end'),
                    pl.col('available_at').cast(SCHEMA['available_at']),pl.col('observed_at').cast(SCHEMA['observed_at']),
                    pl.col('available_at').dt.convert_time_zone('Asia/Shanghai').dt.date().alias('available_date'),
                    pl.lit(table).alias('source_table'),'source_row_id','source_raw_path',
                    (pl.col('update_flag').cast(pl.String) if 'update_flag' in frame.columns else pl.lit(None,dtype=pl.String)).alias('update_flag'),
                    *numeric)
                sections.append(part)
    if not sections:return empty_preliminary()
    return pl.concat([empty_preliminary(),*sections],how='diagonal_relaxed').sort('available_at').unique(
        ['source_table','source_row_id'],keep='first',maintain_order=True).select(list(SCHEMA))


def preliminary_as_of(history,date,symbols):
    """Prior-local-day information for the registered daily financial convention."""
    cutoff=dt.datetime.combine(date,dt.time(),tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return history.filter(pl.col('symbol').is_in(symbols)&(pl.col('available_at')<cutoff)
        &(pl.col('announcement_date')<date))
