import datetime as dt

import polars as pl
import pytest

from quant.data import factor_execution


def test_limits_capture_resumes_complete_year_without_requery(tmp_path,monkeypatch):
    dates = (dt.date(2025,12,31),dt.date(2026,1,2))
    calls = []

    class Client:
        def __init__(self,**kwargs):
            pass

        def query_raw(self,endpoint,**params):
            calls.append((endpoint,params))
            return pl.DataFrame({'trade_date':[params['trade_date']]*2,
                'ts_code':['600000.SH','000001.SZ'],'up_limit':[11.,22.],'down_limit':[9.,18.]})

    monkeypatch.setattr(factor_execution,'TushareConnector',Client)
    monkeypatch.setattr(factor_execution,'available_sessions',lambda root,end:tuple(d for d in dates if d<=end))
    monkeypatch.setattr(factor_execution.time,'sleep',lambda seconds:None)
    args=dict(data_root=tmp_path,name='fixture',start=dates[0],end=dates[-1])
    summary=factor_execution.capture_limits(**args)
    assert summary['sessions']==2 and summary['rows']==4 and len(calls)==2
    assert factor_execution.capture_limits(**args)==summary and len(calls)==2
    file=tmp_path/'clean/factor_execution/fixture/year=2025/limits.parquet'
    assert pl.read_parquet(file)['trade_date'].unique().to_list()==[dates[0]]
    file.unlink()
    with pytest.raises(FileExistsError):
        factor_execution.capture_limits(**args)
