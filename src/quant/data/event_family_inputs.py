"""D1 native structured sources for event_family_v1; no factor evaluation."""
import datetime as dt
from pathlib import Path

import polars as pl

SOURCES={
    'repurchase':{'family':'repurchase','units':'amount CNY; vol native shares'},
    'stk_holdertrade':{'family':'insider_trading','units':'change_vol native shares; avg_price CNY/share; change_ratio percent'},
    'share_float':{'family':'share_unlock','units':'float_share native shares; float_ratio percent; float_date is scheduled unlock date'},
    'stk_holdernumber':{'family':'holder_count','units':'holder_num households; end_date is report cutoff'},
}


def read_event_source(data_root,table,*,known_at=None):
    """Return a lazy native observation stream and its published source files.

    Announcement eligibility is separate from a planned unlock/report-cutoff date.
    Individual holders and cumulative progress are not aggregated into new signals.
    """
    if table not in SOURCES:raise ValueError('Unregistered event-family source')
    known_at=known_at or dt.datetime.now(dt.timezone.utc)
    if known_at.tzinfo is None:raise ValueError('Require timezone-aware event observation cutoff')
    paths=[p for summary in sorted((Path(data_root)/'clean'/table).glob('snapshot=*/summary.json'))
        for p in sorted(summary.parent.glob('year=*/data.parquet'))]
    if not paths:return None,[]
    sections=[pl.scan_parquet(p) for p in paths]
    required={'ts_code','source_announcement_date','source_row_id','source_raw_path','available_at','observed_at'}
    if any(not required<=set(section.collect_schema().names()) for section in sections):
        raise ValueError('Published event-family source lacks provenance')
    frame=pl.concat(sections,how='diagonal_relaxed').filter(
        (pl.col('available_at')<=known_at)&(pl.col('observed_at')<=known_at))
    frame=frame.sort('observed_at').unique('source_row_id',keep='first',maintain_order=True)
    return frame,paths


def event_family_source_facts(data_root,*,known_at=None):
    known_at=known_at or dt.datetime.now(dt.timezone.utc)
    facts={'observed_at':known_at.isoformat(),'family':'event_family_v1','evaluate_this_round':False,
        'historical_vintage_verified':False,'quantity_aggregation_performed':False,'sources':{}}
    for table,spec in SOURCES.items():
        frame,paths=read_event_source(data_root,table,known_at=known_at)
        value={**spec,'status':'table_not_captured','paths':[str(p) for p in paths]}
        if frame is not None:
            values=frame.select(pl.len().alias('visible_native_records'),
                pl.col('ts_code').n_unique().alias('symbols'),
                pl.col('source_announcement_date').min().alias('first_announcement'),
                pl.col('source_announcement_date').max().alias('last_announcement')).collect().row(0,named=True)
            value.update(status='observed_native_records' if values['visible_native_records'] else 'no_visible_observation',
                **{key:str(item) if isinstance(item,dt.date) else item for key,item in values.items()})
        facts['sources'][table]=value
    return facts
