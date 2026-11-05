"""Bounded repair of three frozen GP expressions; never rewrite old N2 receipts."""
import ast
import argparse
import json
from pathlib import Path
import shutil
import tomllib

import polars as pl

from quant.data.gp_context_inputs import sha256,dump
from quant.factors.expressions import evaluate_expressions

VERSION='window_local_skew_v2'


def load(config):
    if config is None:
        return None
    spec=tomllib.loads(Path(config).read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['version']!=VERSION:
        raise ValueError('Invalid GP skew repair request')
    for name,digest in spec['sources'].items():
        if sha256(Path(name))!=digest:
            raise ValueError(f'Frozen skew-repair source changed: {name}')
    return spec


def archive_panels(spec,*,data_root):
    """Preserve all old derived bytes before the first versioned panel repair."""
    root=Path(spec['artifact_root'])/'original_panels'
    receipt=root/'backup.json'
    if receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf-8'))
        for name,digest in saved['archived_sha256'].items():
            if sha256(Path(name))!=digest:
                raise ValueError('Original GP panel backup changed')
        return saved
    records={}
    for factor in spec['candidates']:
        source=data_root/'factors'/factor
        for path in sorted(source.rglob('*')):
            if not path.is_file():continue
            target=root/factor/path.relative_to(source)
            digest=sha256(path)
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if sha256(target)!=digest:
                    raise ValueError('Partial original GP backup differs from its source')
            else:
                shutil.copyfile(path,target)
            if sha256(target)!=digest or sha256(path)!=digest:
                raise ValueError('GP panel changed during archival')
            records[str(target)]=digest
    saved={'archived_sha256':records,'auto_trade':False,'raw_modified':False}
    root.mkdir(parents=True,exist_ok=True)
    dump(receipt,saved)
    return saved


def repaired_training(spec,*,source,training,labels,plans):
    """Re-evaluate fixed terminal inputs, retaining original values and IC audit.

    This is a computational correction, not reproduction of the broken N2
    measurement. The original search score never becomes a corrected fitness.
    All candidate expressions, directions, labels and admission tests stay fixed.
    """
    from quant.research.gp_context_alignment import compare_values
    selected={name:p for name,p in plans.items() if name in spec['candidates'] and p['source']==source}
    if not selected:
        return training,None
    path=source.parent/'daily_sample.parquet'
    if str(path) not in spec['sources']:
        raise ValueError('Missing frozen terminal sample in skew repair request')
    fields=set()
    for plan in selected.values():
        tree=ast.parse(plan['terminal'],mode='eval')
        if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and
               n.func.id in {'rank','scale','ind_neutralize'} for n in ast.walk(tree)):
            raise ValueError('Skew repair does not approximate cross-section subtrees')
        fields.update(n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and n.id.startswith('gp_'))
    sample=pl.read_parquet(path,columns=['symbol','trade_date',*sorted(fields)])
    result=evaluate_expressions(sample,{name:p['terminal'] for name,p in selected.items()},window_skew=True)
    parts=[];audit=[]
    for name,plan in selected.items():
        original=training.filter(pl.col('factor')==name).drop('factor')
        corrected=original.select('symbol','trade_date').join(result.select('symbol','trade_date',
            pl.col(name).alias('candidate')),on=['symbol','trade_date'],how='left',validate='1:1')
        audit.append(compare_values(original,corrected,labels,factor=name,direction=spec['directions'][name]))
        parts.append(corrected.with_columns(pl.lit(name).alias('factor')).select(training.columns))
    merged=pl.concat([training.filter(~pl.col('factor').is_in(list(selected))),*parts],how='vertical_relaxed')
    folder=Path(spec['artifact_root'])/source.parent.parent.parent.name
    folder.mkdir(parents=True,exist_ok=True)
    values=folder/'corrected_training_values.parquet'
    record={'version':VERSION,'basis':'Corrected fixed N2 terminal inputs, not original N2 reproduction',
        'original_source':str(source),'original_training_sha256':sha256(source.parent/'training_candidate_values.parquet'),
        'original_vs_corrected':audit,'frozen_search_fitness_retained':True,
        'original_measurement_replaced_for_alignment_only':True,'candidate_reselection':False,'auto_trade':False}
    receipt=folder/'correction.json'
    if receipt.exists():
        existing=json.loads(receipt.read_text(encoding='utf-8'))
        if existing['original_training_sha256']!=record['original_training_sha256'] or sha256(values)!=existing['corrected_values_sha256']:
            raise ValueError('Saved skew repair receipt changed')
        if not merged.equals(pl.read_parquet(values)):
            raise ValueError('Corrected skew training values are not reproducible')
        return merged,existing
    merged.write_parquet(values)
    record['corrected_values_sha256']=sha256(values)
    dump(receipt,record)
    return merged,record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--batch',type=Path,required=True)
    args=parser.parse_args()
    spec=load(args.config)
    settings=json.loads((args.batch/'settings.json').read_text(encoding='utf-8'))
    from quant.factors.compute import run as compute
    from quant.factors.library import load_library
    from quant.research.gp_context_alignment import verify_new_gp_values
    import datetime as dt
    folder=Path(spec['artifact_root'])
    folder.mkdir(parents=True,exist_ok=True)
    compute(data_root=Path(settings['data_root']),refresh_config=Path(settings['refresh_config']),
        library=args.batch/'library',selected='all',start=dt.date.fromisoformat(settings['history_start']),
        end=dt.date.fromisoformat(settings['as_of']),artifact_root=folder/'compute',numeric_repair=args.config)
    result=verify_new_gp_values(load_library(args.batch/'library'),data_root=Path(settings['data_root']),
        output=folder/'alignment.json',numeric_repair=args.config)
    print(json.dumps({'factors_checked':result['factors_checked'],'corrected_alignment_passed':result['passed'],
        'original_n2_reproduction':result.get('original_n2_reproduction',True),'auto_trade':False}),flush=True)
