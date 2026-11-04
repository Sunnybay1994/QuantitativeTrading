import datetime as dt
import json

import polars as pl

from quant.data.probe_tushare import TABLES,run
from quant.data.storage import RawStore


def test_nine_permission_calls_are_bounded_and_not_repeated_on_resume(tmp_path,monkeypatch):
    monkeypatch.setattr('quant.data.probe_tushare.read_stock_paper_calendar',lambda _:pl.DataFrame(
        {'date':[dt.date(2026,11,4)],'is_open':[True]}))
    monkeypatch.setattr('quant.data.probe_tushare.RawStore',lambda _:RawStore(tmp_path/'raw'))
    calls=[]
    class Client:
        def query_raw(self,table,**params):
            calls.append(table)
            assert params['limit']=='5'
            if table=='report_rc':
                raise RuntimeError('接口权限不足 token_should_never_be_saved')
            return pl.DataFrame(schema={'ts_code':pl.String}) if table=='margin_detail' else pl.DataFrame({'ts_code':['000001.SZ']})
    output=tmp_path/'permissions.json'
    result=run(output=output,as_of=dt.date(2026,11,5),connector=Client(),pause=0)
    assert calls==list(TABLES)
    assert result['tables']['report_rc']['status']=='permission_denied'
    assert result['tables']['margin_detail']['status']=='available_empty'
    assert 'token_should_never_be_saved' not in output.read_text()
    run(output=output,as_of=dt.date(2026,11,5),connector=Client(),pause=0)
    assert len(calls)==9
    assert json.loads(output.read_text())['status']=='probed'
