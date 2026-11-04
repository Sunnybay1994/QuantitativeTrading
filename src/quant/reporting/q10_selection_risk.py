"""Frozen trial-count DSR sensitivities and return-matrix CSCV diagnostics."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats


def dsr(returns,*,trials,trial_sharpe_std):
    values=np.asarray(returns,dtype=float)
    if values.ndim!=1 or len(values)<30 or not np.isfinite(values).all() or trials<2:
        raise ValueError('Require finite daily returns and at least two trial attempts')
    sr=float(values.mean()/values.std(ddof=1))
    skew=float(stats.skew(values,bias=False))
    kurtosis=float(stats.kurtosis(values,fisher=False,bias=False))
    variance=(1-skew*sr+(kurtosis-1)*sr**2/4)/(len(values)-1)
    if variance<=0 or not np.isfinite(trial_sharpe_std) or trial_sharpe_std<=0:
        raise ValueError('Invalid Sharpe uncertainty')
    gamma=.5772156649015329
    maximum=(1-gamma)*stats.norm.ppf(1-1/trials)+gamma*stats.norm.ppf(1-1/(trials*np.e))
    reference=float(trial_sharpe_std*maximum)
    return {'daily_sharpe':sr,'annualized_sharpe':sr*np.sqrt(252),
        'samples':len(values),'skew':skew,'pearson_kurtosis':kurtosis,'declared_trials':trials,
        'trial_daily_sharpe_std':trial_sharpe_std,'expected_maximum_daily_sharpe':reference,
        'dsr':float(stats.norm.cdf((sr-reference)/np.sqrt(variance))),
        'null_variance_sensitivity_dsr':float(stats.norm.cdf(sr/np.sqrt(variance)-maximum)),
        'assumption':'declared attempts treated as independent sensitivity; empirical dispersion uses available complete common-window paths'}


def pbo(matrix,*,blocks=10):
    values=np.asarray(matrix,dtype=float)
    if (values.ndim!=2 or values.shape[1]<2 or len(values)<blocks*2 or blocks%2
            or not np.isfinite(values).all()):
        raise ValueError('Require complete returns of multiple strategies and even contiguous blocks')
    chunks=np.array_split(np.arange(len(values)),blocks)
    rows=[]
    for subset in itertools.combinations(range(blocks),blocks//2):
        train=values[np.concatenate([chunks[k] for k in subset])]
        test=values[np.concatenate([chunks[k] for k in range(blocks) if k not in subset])]
        def sharpe(part):
            std=part.std(axis=0,ddof=1)
            return np.divide(part.mean(axis=0),std,out=np.zeros_like(std),where=std>0)
        inside,outside=sharpe(train),sharpe(test)
        winners=np.flatnonzero(np.isclose(inside,inside.max(),rtol=1e-12,atol=1e-14))
        ranks=stats.rankdata(outside,method='average')
        relative=ranks[winners]/(values.shape[1]+1)
        logits=np.log(relative/(1-relative))
        probability=float(np.mean((logits<0)+.5*np.isclose(logits,0,atol=1e-14)))
        rows.append({'training_blocks':list(subset),'winner_count':len(winners),
            'mean_selected_test_rank':float(ranks[winners].mean()),'overfit_fraction':probability})
    return {'pbo':float(np.mean([r['overfit_fraction'] for r in rows])),
        'matrix_trials':values.shape[1],'sessions':len(values),'blocks':blocks,'combinations':len(rows),
        'ties':'average ranks; average over IS tied winners; exact OOS median contributes one half',
        'folds':rows}


def read_returns(record,dates):
    run=Path(record['run_path'])
    variant=record['variant']
    method=variant.rsplit('_top',1)[0]
    candidates=[run/variant/'cost_1',run/method/'cost_1',run/'cost_1',
        run.parent/'replay'/variant/'cost_1',run.parent.parent/'replay'/variant/'cost_1']
    for folder in dict.fromkeys(candidates):
        paths=[folder/'nav.parquet'] if (folder/'nav.parquet').is_file() else sorted(folder.glob('*/nav.parquet'))
        if not paths:
            continue
        frames=[]
        for path in paths:
            frame=pl.read_parquet(path)
            column='unit_nav' if 'unit_nav' in frame.columns else 'equity'
            frames.append(frame.select('date',pl.col(column).alias('value')))
        nav=pl.concat(frames).sort('date')
        if nav['date'].n_unique()!=nav.height:
            return None,{'reason':'duplicate_saved_nav_dates','paths':list(map(str,paths))}
        nav=nav.with_columns((pl.col('value')/pl.col('value').shift(1)-1).alias('return')).filter(
            pl.col('date').is_in(dates.implode()))
        if not nav['date'].equals(dates) or nav['return'].null_count() or not nav['return'].is_finite().all():
            return None,{'reason':'incomplete_fixed_common_window','paths':list(map(str,paths))}
        result=nav['return'].to_numpy()
        if result.std(ddof=1)==0:
            return None,{'reason':'no_varying_returns','paths':list(map(str,paths))}
        return result,{'reason':'included','paths':list(map(str,paths)),
            'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    return None,{'reason':'saved_daily_return_path_not_resolved'}


def run(*,output):
    import datetime as dt
    output.mkdir(exist_ok=False,parents=True)
    registry=Path('artifacts/registry/experiments.parquet')
    (output/'registry.parquet').write_bytes(registry.read_bytes())
    rows=pl.read_parquet(output/'registry.parquet').filter(pl.col('level')=='strategy')
    qmask=pl.col('experiment_id').str.contains(r'(?i)^q(?:[1-9]|10)(?:[^0-9]|$)')
    qids=set(rows.filter(qmask).select('run_path','variant').iter_rows())
    primary=Path('artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01')
    paths=sorted((primary/'budgeted/cost_1').glob('*/nav.parquet'))
    calendar=pl.concat([pl.read_parquet(p).select('date') for p in paths]).sort('date')
    dates=calendar.filter(pl.col('date').is_between(dt.date(2019,1,2),dt.date(2026,8,31)))['date']
    target,target_evidence=read_returns({'run_path':str(primary),'variant':'budgeted'},dates)
    if target is None:
        raise ValueError('Missing complete primary Q10 returns')
    arrays,records={},[]
    for index,record in enumerate(rows.sort('run_path','variant').iter_rows(named=True)):
        values,evidence=read_returns(record,dates)
        name=f'trial_{index:04d}'
        item={'trial':name,'run_path':record['run_path'],'variant':record['variant'],
            'q1_q10_scope':(record['run_path'],record['variant']) in qids,**evidence}
        if values is not None:
            arrays[name]=values
        records.append(item)
    (output/'coverage.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    pl.DataFrame({'date':dates,**arrays}).write_parquet(output/'daily_returns.parquet')
    result={'window':{'start':str(dates[0]),'end':str(dates[-1]),'sessions':len(dates)},
        'registry_sha256':hashlib.sha256(registry.read_bytes()).hexdigest(),
        'primary_source':target_evidence,'auto_trade':False,'scopes':{}}
    for scope,count,names in [('registry_strategy_rows',rows.height,list(arrays)),
            ('q1_q10_variants',len(qids),[r['trial'] for r in records if r['q1_q10_scope'] and r['trial'] in arrays])]:
        unique={}
        for name in names:
            unique.setdefault(hashlib.sha256(arrays[name].tobytes()).hexdigest(),name)
        selected=list(unique.values())
        matrix=np.column_stack([arrays[name] for name in selected])
        sharpe=matrix.mean(axis=0)/matrix.std(axis=0,ddof=1)
        risk=dsr(target,trials=count,trial_sharpe_std=float(sharpe.std(ddof=1)))
        cross=pbo(matrix)
        pl.from_dicts(cross.pop('folds')).write_parquet(output/f'{scope}_pbo_folds.parquet')
        result['scopes'][scope]={'declared_attempts':count,'complete_paths':len(names),
            'unique_complete_return_paths':len(selected),'included_trials':selected,'dsr':risk,'pbo':cross,
            'limitation':'PBO applies only to the disclosed available full-window matrix, not all declared attempts; no synthetic missing columns or invented independence'}
    (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(output=args.output)
    print(json.dumps({k:{'declared_attempts':v['declared_attempts'],'complete_paths':v['complete_paths'],
        'dsr':v['dsr']['dsr'],'pbo':v['pbo']['pbo']} for k,v in result['scopes'].items()}))
