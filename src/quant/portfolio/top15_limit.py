"""Fixed Top15/30 membership with the preregistered price-per-lot affordability rule."""
import math

import polars as pl


def targets(*, scores, previous, closes, equity, execution_date, maximum_new_names=None):
    if maximum_new_names not in (None, 7) or isinstance(maximum_new_names,bool):
        raise ValueError('R4 fixes seven new selected names; the default remains unrestricted')
    if (scores.is_empty() or scores['trade_date'].n_unique()!=1 or scores['symbol'].is_duplicated().any()
            or not scores['prediction'].is_finite().all() or not math.isfinite(equity) or equity<=0):
        raise ValueError('Require unique finite same-date forecasts and positive equity')
    ranked=scores.sort(['prediction','symbol'],descending=[True,False])
    rank={symbol:index+1 for index,symbol in enumerate(ranked['symbol'])}
    retained=[s for s in ranked['symbol'] if s in previous and rank[s]<=30]
    candidates=retained+[s for s in ranked.head(15)['symbol'] if s not in retained]
    if any(s not in closes or not math.isfinite(closes[s]) or closes[s]<=0 for s in candidates):
        raise ValueError('Missing signal-close lot eligibility price')
    selected=[]
    weight=0.
    # Maximize valid membership without raising the 8% cap or widening ranks.
    # Recompute the intended equal budget for each possible cardinality; this
    # avoids circular price eligibility when fewer than 15 names are affordable.
    for count in range(min(15,len(candidates)),0,-1):
        proposed=min(1/count,.08)
        eligible=[s for s in candidates if 100*closes[s]<=equity*proposed*.5]
        if maximum_new_names is not None:
            old=[s for s in eligible if s in previous]
            new=[s for s in eligible if s not in previous][:maximum_new_names]
            eligible=old+new
        if len(eligible)>=count:
            selected,weight=eligible[:count],proposed
            break
    day=scores['trade_date'][0]
    symbols=sorted(set(previous)|set(selected))
    schema={'as_of':pl.Date,'execution_date':pl.Date,'symbol':pl.String,
            'weight':pl.Float64,'strategy':pl.String,'strategy_version':pl.String}
    result=pl.from_dicts([{'as_of':day,'execution_date':execution_date,'symbol':symbol,
        'weight':weight if symbol in selected else 0.,'strategy':'top15_limit_v1','strategy_version':'1'}
        for symbol in symbols],schema=schema) if symbols else pl.DataFrame(schema=schema)
    return result,selected
