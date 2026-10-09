import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.factors.industry_information import SIGNALS, CONTROL
from quant.factors.expressions import required_history
from quant.data.monthly_open_inputs import digest
from tests.unit.test_factor_expressions import prepared


def sources(tmp_path,monkeypatch):
    from quant.data import factor_industry_information_inputs as inputs
    first,last=dt.date(2019,1,1),dt.date(2022,3,2)
    calendar=tuple(first+dt.timedelta(days=i) for i in range((last-first).days+1)
        if (first+dt.timedelta(days=i)).weekday()<5)
    symbol=lambda g,k: f'6000{k:02}.SH' if g=='A' else f'0000{k:02}.SZ'
    bars=pl.from_dicts([{'symbol':symbol(g,k),'trade_date':day,'open':20.+i*(.01+.001*k),
        'high':21.+i*(.01+.001*k),'low':19.+i*(.01+.001*k),'close':20.+i*(.01+.001*k),
        'adj_factor':1.,'volume':1000.,'amount':20000.,'source':'fixture'}
        for g in ('A','B') for k in range(12) for i,day in enumerate(calendar)])
    basic=bars.select('symbol','trade_date').with_columns((20.-pl.col('symbol').str.slice(4,2).cast(pl.Float64)).alias('total_market_value'))
    spec=tomllib.loads(Path('configs/research/industry_information_family_v1.toml').read_text())
    folder=tmp_path/'clean/tushare_industry'/spec['initial_industry_snapshot']
    folder.mkdir(parents=True)
    pl.from_dicts([{'symbol':symbol(g,k),'valid_from':first,'valid_to':last+dt.timedelta(days=1),
        'industry_l1':g,'industry_l2':g,'industry_l3':g} for g in ('A','B') for k in range(12)]).write_parquet(folder/'intervals.parquet')
    reads=[]
    def read(**kw):
        reads.append(kw)
        frame=bars if kw['table']=='bar_1d' else basic
        result=frame.filter(pl.col('trade_date').is_between(kw['start'],kw['end']))
        return result.select(kw['columns']) if kw.get('columns') else result
    monkeypatch.setattr(inputs,'read_stock_data',read)
    return bars,basic,calendar,reads,read


def test_completed_month_reader_prefix_and_daily_invalid_replacement(tmp_path,monkeypatch):
    from quant.data import factor_industry_information_inputs as inputs
    from quant.research.factor_monthly import attach_monthly_factors
    bars,basic,calendar,reads,read=sources(tmp_path,monkeypatch)
    values,_,_=inputs.read_industry_information(data_root=tmp_path,refresh_config=Path('unused'),
        calendar=calendar,start=dt.date(2021,1,1),end=dt.date(2021,2,28))
    assert set(values['trade_date'])=={dt.date(2021,1,29),dt.date(2021,2,26)}
    assert min(r['start'] for r in reads)==dt.date(2020,7,31)
    prefix,_,_=inputs.read_industry_information(data_root=tmp_path,refresh_config=Path('unused'),
        calendar=calendar,start=dt.date(2021,1,1),end=dt.date(2021,2,15))
    assert_frame_equal(prefix,values.filter(pl.col('trade_date')==dt.date(2021,1,29)))
    invalid=values.with_columns(*[pl.when(pl.col('trade_date')==dt.date(2021,2,26)).then(None)
        .otherwise(pl.col(n)).alias(n) for n in (*SIGNALS,CONTROL)])
    panel=bars.filter(pl.col('trade_date').is_between(dt.date(2021,1,1),dt.date(2021,3,1)))
    result=attach_monthly_factors(panel,bars,basic,calendar,SIGNALS,industry_information_values=invalid)
    for name in (*SIGNALS,CONTROL):
        assert required_history(f'ts_mean({name},20)')==51
        assert result.filter(pl.col('trade_date')==dt.date(2021,2,25))[name].count()>0
        assert result.filter(pl.col('trade_date')==dt.date(2021,2,26))[name].count()==0
        assert result.filter(pl.col('trade_date')==dt.date(2021,3,1))[name].count()==0


def test_original_n4_thresholds_raw_controls_and_neutral_identity():
    from quant.research.industry_information_controls import FIXED_CONTROLS,check_industry_information_controls as check
    definition=tomllib.loads(Path('configs/research/industry_information_family_v1.toml').read_text())
    assert list(FIXED_CONTROLS)==definition['fixed_control_ids']
    panel=pl.DataFrame({n:[1.,2.] for n in ['candidate','label','admitted',CONTROL,*FIXED_CONTROLS]}).with_columns(
        pl.lit(None,dtype=pl.Float64).alias('industry_neutral'))
    seen=[]
    def evaluate(frame,candidate,controls,direction):
        seen.append(controls)
        assert candidate=='candidate' and direction==1 and frame.height==2
        return {'months':96,'newey_west_t':2.5}
    assert check(panel,['admitted'],evaluate,SIGNALS[1])['passed']
    assert seen==[['admitted',CONTROL,*FIXED_CONTROLS]]
    assert not check(panel,[],lambda *a:{'months':95,'newey_west_t':30.},SIGNALS[1])['passed']
    assert not check(panel,[],lambda *a:{'months':120,'newey_west_t':2.49},SIGNALS[1])['passed']
    assert not check(panel.with_columns(pl.lit(1.).alias('industry_neutral')),[],lambda *a:pytest.fail(),SIGNALS[1])['passed']
    assert not check(panel.drop(CONTROL),[],lambda *a:pytest.fail(),SIGNALS[1])['passed']
    check(panel,[],evaluate,SIGNALS[0])
    assert seen[-1]==list(FIXED_CONTROLS)


def test_n3_cached_factors_recover_control_receipts_without_rewrites(tmp_path,monkeypatch):
    from quant.factors import compute
    bars,basic,calendar,reads,source=sources(tmp_path/'data',monkeypatch)
    monkeypatch.setattr(compute,'available_sessions',lambda root,end:tuple(d for d in calendar if d<=end))
    def read(root,config,start,end,sessions):
        selected=bars.filter(pl.col('trade_date').is_between(start,end))
        return prepared(selected),selected
    monkeypatch.setattr(compute,'read_factor_inputs',read)
    monkeypatch.setattr(compute,'read_stock_data',source)
    library=tmp_path/'library';library.mkdir()
    for name in SIGNALS:
        (library/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\ndirection=1\nfamily="industry_return_information_v1"\nsource_ref="fixture"\n')
    args=dict(data_root=tmp_path/'data',refresh_config=Path('unused'),library=library,selected='all',
        start=dt.date(2020,1,1),end=dt.date(2021,2,15))
    compute.run(**args,artifact_root=tmp_path/'first')
    paths=list((tmp_path/'data').rglob('*'))
    before={str(p):(digest(p),p.stat().st_mtime_ns) for p in paths if p.is_file()}
    compute.run(**args,artifact_root=tmp_path/'second')
    for path in (tmp_path/'first/industry_information_controls').glob('*.parquet'):
        assert_frame_equal(pl.read_parquet(path),pl.read_parquet(tmp_path/'second/industry_information_controls'/path.name))
    assert before=={name:(digest(Path(name)),Path(name).stat().st_mtime_ns) for name in before}
    count=len(reads)
    compute.run(**args,artifact_root=tmp_path/'second')
    assert len(reads)==count
    damaged=tmp_path/'second/industry_information_controls/year=2021.parquet'
    damaged.write_bytes(b'interrupted')
    compute.run(**args,artifact_root=tmp_path/'second')
    assert_frame_equal(pl.read_parquet(damaged),pl.read_parquet(tmp_path/'first/industry_information_controls/year=2021.parquet'))
    assert before=={name:(digest(Path(name)),Path(name).stat().st_mtime_ns) for name in before}


def test_n4_dispatch_uses_raw_and_rejects_failed_family_control(tmp_path,monkeypatch):
    from quant.research import nightly_steps as steps,industry_information_controls as family
    from quant.data import nightly_genetic_inputs as data
    from quant.data.factor_control_receipts import write_control_receipt
    run,batch,library=tmp_path/'run',tmp_path/'batch',tmp_path/'library'
    name,day=SIGNALS[1],dt.date(2026,8,31)
    for path in (run/'N3',run/'N4',batch/'library',library,tmp_path/'reference',tmp_path/'queue/processing'):
        path.mkdir(parents=True)
    (batch/'library'/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\ndirection=1\nfamily="industry_return_information_v1"\nsource_ref="registered_battery:test"\n')
    (library/'ref.toml').write_text('id="ref"\nexpr="close"\ndirection=1\nfamily="other"\nsource_ref="test"\n')
    card=batch/'scorecard.parquet'
    pl.DataFrame({'factor':[name],'variant':['raw'],'factor_admitted':[True]}).write_parquet(card)
    (run/'N3/result.json').write_text(json.dumps({'evaluated':1,'batch':str(batch),'scorecard':str(card)}))
    (tmp_path/'reference/battery.toml').write_text('[run]\nas_of=2026-08-31\n')
    keys=pl.DataFrame({'symbol':['x'],'trade_date':[day]})
    folder=batch/'evaluation/statistics/factors'/name;folder.mkdir(parents=True)
    keys.with_columns(pl.lit(1.).alias('raw'),pl.lit(None,dtype=pl.Float64).alias('size_industry_neutral')).write_parquet(folder/'monthly_scores.parquet')
    write_control_receipt(batch/'compute/industry_information_controls/year=2026.parquet',
        keys.with_columns(pl.lit(.2).alias(CONTROL)),start=day,end=day,columns=(CONTROL,))
    monkeypatch.setattr(data,'admitted_controls',lambda *a:(keys,[]))
    monkeypatch.setattr(data,'read_raw_monthly',lambda **kw:keys.with_columns(pl.lit(day).alias('label_exit_date')))
    monkeypatch.setattr(steps,'incremental_statistics',lambda *a:{'months':120,'newey_west_t':4.,'complete_control_fraction':1.})
    monkeypatch.setattr(steps,'maximum_correlation',lambda *a:.1)
    seen=[]
    def reject(frame,admitted,evaluate,identifier):
        seen.append(frame['candidate'].item())
        assert frame['industry_neutral'].null_count()==1 and CONTROL in frame.columns and identifier==name
        return {'passed':False,'reason':'fixed_controls_failed'}
    monkeypatch.setattr(family,'check_industry_information_controls',reject)
    settings={'library':str(library),'reference_scorecard':str(card),'reference_statistics':str(tmp_path/'reference'),
        'as_of':day,'history_start':day,'data_root':str(tmp_path/'data'),'rejected_root':str(tmp_path/'rejected'),'queue':str(tmp_path/'queue')}
    result=steps.admit(settings,run)
    assert seen==[1.] and result['admitted']==0 and result['rejected']==1
    assert not (library/'auto'/f'{name}.toml').exists()
