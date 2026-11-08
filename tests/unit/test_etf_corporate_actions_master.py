import datetime as dt
import hashlib
import json

import polars as pl
import pytest

from quant.data.etf_corporate_actions import publish,load,sha


def test_master_keeps_zero_cash_inventory_and_explicit_source_backed_split(tmp_path):
    capture=tmp_path/'capture';capture.mkdir()
    terms='''[[splits]]
symbol="512890.SH"
announcement_date=2021-10-18
record_date=2021-10-21
effective_date=2021-10-22
tradable_date=2021-10-25
ratio=2.0
notice="https://issuer/notice.pdf"
result="https://issuer/result.pdf"
'''
    (capture/'corporate_actions.toml').write_text(terms,encoding='utf-8')
    (capture/'config.toml').write_text('auto_trade=false\n',encoding='utf-8')
    empty=capture/'fund_div.parquet';pl.DataFrame(schema={'ts_code':pl.String}).write_parquet(empty)
    (capture/'summary.json').write_text(json.dumps({'events_sha256':sha(capture/'corporate_actions.toml'),
        'requests':{'512890.SH/fund_div/0':{'raw_path':str(empty),'sha256':sha(empty),'rows':0}}}),encoding='utf-8')
    notices={}
    for name in ['notice','result']:
        p=capture/f'{name}.pdf';p.write_bytes(b'%PDF-fixture')
        notices[name]={'url':f'https://issuer/{name}.pdf','path':str(p),'sha256':sha(p)}
    sources=capture/'sources.json';sources.write_text(json.dumps(notices),encoding='utf-8')
    master=tmp_path/'master';summary=publish(capture=capture,sources=sources,output=master)
    assert summary['symbols']==['512890.SH']
    inventory=json.loads((master/'sources.json').read_text(encoding='utf-8'))
    assert inventory[0]['rows']==0
    row=load(master,symbols=['512890.SH']).row(0,named=True)
    assert row['action_type']=='SHARE_SPLIT' and row['adjust_share_price'] is True
    assert row['share_ratio']==1. and row['source_sha256']==notices['notice']['sha256']
    assert load(master,end=dt.date(2021,10,21)).is_empty()
    with pytest.raises(ValueError,match='lacks a captured'):
        load(master,symbols=['511010.SH'])
    (master/'actions.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Invalid ETF action master'):
        load(master)
