import threading
import time
import datetime as dt
import polars as pl

import pytest

from quant.data.forecast_text_scores import ScoreCache
from quant.factors.forecast_text_score import score_key
from quant.research.parallel_text_scoring import score_parallel
from quant.research.score_forecast_text import load_settings
from tests.unit.test_deepseek_forecast_scoring import CONFIG, REASON, response


def test_parallel_requests_overlap_and_share_request_cap_without_resubmission(tmp_path):
    settings=load_settings(CONFIG)
    selected={score_key(REASON+str(i),settings):REASON+str(i) for i in range(8)}
    path=tmp_path/'cache.sqlite'
    cache=ScoreCache(path)
    cache.close()
    lock=threading.Lock()
    calls=[]
    active=0
    maximum=0
    class Client:
        def complete(self,reason,settings):
            nonlocal active,maximum
            with lock:
                calls.append(reason)
                active+=1
                maximum=max(maximum,active)
            time.sleep(.1)
            with lock:
                active-=1
            return response()
        def close(self):
            pass
    result=score_parallel(selected,settings=settings,cache_path=path,max_requests=2,
        max_usd=1.,workers=4,client_factory=Client,development_test=True)
    assert len(calls)==len(set(calls))==2 and maximum==2
    assert sum(r['state']=='success' for r in result.values())==2
    cache=ScoreCache(path)
    before=cache.totals()
    cache.close()
    score_parallel(selected,settings=settings,cache_path=path,max_requests=2,
        max_usd=1.,workers=4,client_factory=Client,development_test=True)
    cache=ScoreCache(path)
    assert cache.totals()==before and len(calls)==2
    cache.close()


def test_invalid_concurrency_rejected_before_resources(tmp_path):
    with pytest.raises(ValueError,match='2-4'):
        score_parallel({},settings={},cache_path=tmp_path/'absent.sqlite',max_requests=5,
            max_usd=1.,workers=5,client_factory=lambda:None)
    assert not (tmp_path/'absent.sqlite').exists()


def test_unexpected_failure_stops_new_work_and_preserves_unknown_reservation(tmp_path):
    settings=load_settings(CONFIG)
    reasons=[REASON+str(i) for i in range(12)]
    selected={score_key(r,settings):r for r in reasons}
    path=tmp_path/'cache.sqlite'
    cache=ScoreCache(path)
    cache.close()
    barrier=threading.Barrier(4)
    calls=[]
    class Client:
        def complete(self,reason,settings):
            calls.append(reason)
            barrier.wait(timeout=5)
            if reason==reasons[0]:
                raise RuntimeError('synthetic fatal failure')
            time.sleep(.1)
            return response()
        def close(self):
            pass
    with pytest.raises(RuntimeError,match='synthetic fatal'):
        score_parallel(selected,settings=settings,cache_path=path,max_requests=20,
            max_usd=1.,workers=4,client_factory=Client,development_test=True)
    assert len(calls)==4
    cache=ScoreCache(path)
    assert cache.latest(score_key(reasons[0],settings))['state']=='unknown'
    assert cache.totals()['requests']==4
    cache.close()


def test_live_batch_wiring_and_dollar_reservation_stop_before_requests(tmp_path,monkeypatch):
    from quant.research import score_forecast_text as module
    from tests.unit.test_deepseek_forecast_scoring import DESIGN, FakeClient
    calls=[]
    class Client(FakeClient):
        def __init__(self,*args,**kwargs):
            super().__init__()
        def complete(self,reason,settings):
            calls.append(reason)
            return super().complete(reason,settings)
        def close(self):
            pass
    monkeypatch.setattr(module,'DeepSeekClient',Client)
    monkeypatch.setattr(module,'load_key',lambda path:'synthetic-key')
    source=tmp_path/'source.parquet'
    pl.DataFrame({'symbol':['000001.SZ','000002.SZ'],'publication_date':[dt.date(2020,1,1)]*2,
        'report_period':[dt.date(2019,12,31)]*2,'reason_text':[REASON+'甲',REASON+'乙']}).write_parquet(source)
    result=module.run_batch(source=source,config=CONFIG,design_path=DESIGN,output=tmp_path/'run',
        cache_path=tmp_path/'cache.sqlite',execute=True,max_requests=2,max_usd=1.,workers=2,development_test=True)
    assert result['workers']==2 and result['summary']=={'success':2} and len(calls)==2
    result=module.run_batch(source=source,config=CONFIG,design_path=DESIGN,output=tmp_path/'low',
        cache_path=tmp_path/'low.sqlite',execute=True,max_requests=20,max_usd=1e-9,workers=4,development_test=True)
    assert result['requests_this_run']==0 and len(calls)==2
    assert result['summary']=={'budget_exhausted':2}
