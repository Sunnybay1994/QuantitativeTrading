import datetime as dt
import hashlib
import json

import polars as pl

from quant.reporting.result_groups import annotate


def test_groups_require_all_cost_histories_and_preserve_conclusions(tmp_path):
    rows=[]
    for name,values in [('a',[1.1,1.0]),('b',[1.1,1.0]),('c',[1.2,1.0])]:
        run=tmp_path/'artifacts'/name
        for cost in ['0.5','1','2']:
            folder=run/'control'/('cost_'+cost)/'2025'
            folder.mkdir(parents=True)
            pl.DataFrame({'date':[dt.date(2025,1,2),dt.date(2025,1,3)],'unit_nav':values,
                'equity':[v*100 for v in values],'cash':[0.,0.],'market_value':[v*100 for v in values]}).write_parquet(folder/'nav.parquet')
        key=hashlib.sha256(b'control').hexdigest()[:16]
        evidence=run/'periods_1x'/key
        evidence.mkdir(parents=True)
        (evidence/'sources.json').write_text(json.dumps({'nav':[str(run/'control/cost_1/2025/nav.parquet')]}))
        rows.append(dict(variant='control',report_path=str(run/'report.md'),conclusion=name))
    rows.append(dict(variant='unknown',report_path=str(tmp_path/'missing/report.md'),conclusion='REJECTED'))
    for row in rows:
        row.update(cagr_1x=0.,sharpe_1x=0.,mdd_1x=-.1,turnover_1x=1.)
    result=annotate(rows,tmp_path)
    assert result[0]['result_group']==result[1]['result_group']
    assert result[2]['result_group']!=result[0]['result_group']
    assert result[3]['result_group'] is None
    assert [r['conclusion'] for r in result]==['a','b','c','REJECTED']
    assert result[0]['group_kind']=='公共对照／相同净值'
    (tmp_path/'artifacts/b/control/cost_2/2025/nav.parquet').unlink()
    assert annotate(rows,tmp_path)[1]['result_group'] is None
