"""Fixed first-statement reaction signals, usable only after the full window."""
import bisect
import datetime as dt

import polars as pl

NAMES=('statement_ear3_market_proxy_120d','statement_abvol3_stable_shares_120d')
EXPIRY_DAYS=120


def compute_statement_reactions(events: pl.DataFrame, observations: pl.DataFrame,
                                market: pl.DataFrame, *, sessions: tuple[dt.date,...]) -> pl.DataFrame:
    if not sessions or sessions!=tuple(sorted(set(sessions))):
        raise ValueError('Require ordered exchange calendar')
    if events.select('symbol','announcement_date').is_duplicated().any():
        raise ValueError('Duplicate statement event keys')
    keys=['symbol','trade_date']
    if observations.select(keys).is_duplicated().any() or market['trade_date'].is_duplicated().any():
        raise ValueError('Duplicate daily input keys')
    if events.is_empty():
        return events.with_columns(pl.lit(None,dtype=pl.Date).alias('reaction_end'),
            pl.lit(None,dtype=pl.Date).alias('earliest_execution'),
            *[pl.lit(None,dtype=pl.Float64).alias(n) for n in NAMES],
            pl.lit('no_event').alias('price_status'),pl.lit('no_event').alias('volume_status'))
    anchors=[bisect.bisect_left(sessions,d) for d in events['announcement_date']]
    if any(i+2>=len(sessions) for i in anchors):
        raise ValueError('Calendar must include reaction end and following execution session')
    events=events.with_row_index('_event_id').with_columns(
        pl.Series('_anchor',anchors,dtype=pl.Int64),
        pl.Series('reaction_end',[sessions[i+1] for i in anchors],dtype=pl.Date),
        pl.Series('earliest_execution',[sessions[i+2] for i in anchors],dtype=pl.Date))
    calendar=pl.DataFrame({'trade_date':sessions}).with_row_index('_session').with_columns(pl.col('_session').cast(pl.Int64))
    requested=events.select('_event_id','symbol','_anchor').join(pl.DataFrame({'offset':range(-63,2)}),how='cross')
    requested=requested.with_columns((pl.col('_anchor')+pl.col('offset')).alias('_session')).join(calendar,on='_session',how='left',validate='m:1')
    columns=['close','adj_factor','volume','total_shares','float_shares']
    paired=requested.join(observations.select(*keys,*columns),on=keys,how='left',validate='m:1').join(
        market.select('trade_date','index_level'),on='trade_date',how='left',validate='m:1')
    paired=paired.with_columns((pl.col('close')*pl.col('adj_factor')).alias('_price'))
    positive=lambda c: (pl.col(c).is_finite() & (pl.col(c)>0)).fill_null(False)
    event=pl.col('offset').is_between(-1,1);baseline=pl.col('offset').is_between(-63,-8)
    price=pl.col('offset').is_between(-2,1)
    price_valid=positive('close') & positive('adj_factor') & positive('_price') & positive('volume')
    nonnegative=(pl.col('volume').is_finite() & (pl.col('volume')>=0)).fill_null(False)
    grouped=paired.group_by('_event_id').agg(
        (price & price_valid).sum().alias('price_points'),
        (price & positive('index_level')).sum().alias('market_points'),
        (event & positive('volume')).sum().alias('event_volume_points'),
        (baseline & nonnegative).sum().alias('baseline_volume_points'),
        pl.col('volume').filter(baseline).mean().alias('baseline_volume_mean'),
        pl.col('volume').filter(event).mean().alias('event_volume_mean'),
        pl.col('_price').filter(pl.col('offset')==-2).first().alias('start_price'),
        pl.col('_price').filter(pl.col('offset')==1).first().alias('end_price'),
        pl.col('index_level').filter(pl.col('offset')==-2).first().alias('start_market'),
        pl.col('index_level').filter(pl.col('offset')==1).first().alias('end_market'),
        *[positive(c).sum().alias(c+'_points') for c in ['total_shares','float_shares']],
        *[(pl.col(c).max()-pl.col(c).min()).alias(c+'_range') for c in ['total_shares','float_shares']])
    result=events.join(grouped,on='_event_id',how='left',validate='1:1').with_columns(
        (pl.col('end_price')/pl.col('start_price')-pl.col('end_market')/pl.col('start_market')).alias('_ear'),
        (pl.col('event_volume_mean')/pl.col('baseline_volume_mean')-1).alias('_abvol'))
    result=result.with_columns(
        pl.when(~pl.col('event_date_valid')).then(pl.col('event_date_status'))
        .when(pl.col('price_points')!=4).then(pl.lit('price_window_incomplete'))
        .when(pl.col('market_points')!=4).then(pl.lit('market_window_incomplete'))
        .when(~pl.col('_ear').is_finite().fill_null(False)).then(pl.lit('nonfinite_result'))
        .otherwise(pl.lit('valid')).alias('price_status'),
        pl.when(~pl.col('event_date_valid')).then(pl.col('event_date_status'))
        .when((pl.col('baseline_volume_points')!=56)|~positive('baseline_volume_mean')).then(pl.lit('baseline_volume_incomplete_or_zero'))
        .when(pl.col('event_volume_points')!=3).then(pl.lit('event_volume_incomplete'))
        .when((pl.col('total_shares_points')!=65)|(pl.col('float_shares_points')!=65)).then(pl.lit('capital_window_incomplete'))
        .when((pl.col('total_shares_range')>1)|(pl.col('float_shares_range')>1)).then(pl.lit('capital_changed'))
        .when(~pl.col('_abvol').is_finite().fill_null(False)).then(pl.lit('nonfinite_result'))
        .otherwise(pl.lit('valid')).alias('volume_status'))
    return result.with_columns(
        pl.when(pl.col('price_status')=='valid').then(pl.col('_ear')).otherwise(None).alias(NAMES[0]),
        pl.when(pl.col('volume_status')=='valid').then(pl.col('_abvol')).otherwise(None).alias(NAMES[1])
    ).drop('_event_id','_anchor','_ear','_abvol').sort('symbol','reaction_end','announcement_date')


def attach_statement_reactions(keys: pl.DataFrame, reactions: pl.DataFrame) -> pl.DataFrame:
    """Latest completed event wins even if invalid; age 120 is already expired."""
    if reactions.is_empty():
        return keys.with_columns(*[pl.lit(None,dtype=pl.Float64).alias(n) for n in NAMES],
            pl.lit(None,dtype=pl.Date).alias('statement_reaction_end'))
    events=reactions.sort('symbol','reaction_end','announcement_date','end_date').unique(
        ['symbol','reaction_end'],keep='last',maintain_order=True).select('symbol',
        pl.col('reaction_end').alias('statement_reaction_end'),*NAMES)
    result=keys.sort('symbol','trade_date').join_asof(events.sort('symbol','statement_reaction_end'),
        left_on='trade_date',right_on='statement_reaction_end',by='symbol',strategy='backward',check_sortedness=False)
    age=(pl.col('trade_date')-pl.col('statement_reaction_end')).dt.total_days()
    return result.with_columns(*[pl.when(age.is_between(0,EXPIRY_DAYS-1)).then(pl.col(n)).otherwise(None).alias(n) for n in NAMES])
