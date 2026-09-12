import datetime as dt
import polars as pl
import pytest

from quant.data.monthly_text_sample import membership_panel, cache_snapshot
from quant.data.forecast_text_scores import ScoreCache
from quant.factors.forecast_text_score import DIMENSIONS, score_key
from quant.research.score_forecast_text import load_settings
from pathlib import Path


def test_new_unscored_publication_invalidates_old_score_and_membership_is_exact():
    dates = [dt.date(2020,1,1),dt.date(2020,1,20),dt.date(2020,1,1)]
    scores = pl.DataFrame({'symbol':['000001.SZ','000001.SZ','000002.SZ'],
        'publication_date':dates,'report_period':[dt.date(2019,12,31)]*3,
        'input_id':['old','new','other'],'same_day_conflict':[False]*3,
        **{f'text_{d}':[2.,None,3.] for d in DIMENSIONS}})
    members = pl.DataFrame({'symbol':['000001.SZ'],'trade_date':[dt.date(2020,1,31)],'input_id':['new']})
    panel = membership_panel(scores,members,max_age_days=120)
    assert panel.height == 1 and panel['text_operating_improvement'].item() is None
    with pytest.raises(ValueError,match='latest publication'):
        membership_panel(scores,members.with_columns(pl.lit('old').alias('input_id')),max_age_days=120)


def test_snapshot_reads_only_allowed_successes_and_does_not_mutate_cache(tmp_path):
    settings = load_settings(Path('configs/research/deepseek_p7_thinking_8192_20260912.toml'))
    source = tmp_path/'source.parquet'
    pl.DataFrame({'symbol':['000001.SZ','000002.SZ'],
        'publication_date':[dt.date(2020,1,1)]*2,'report_period':[dt.date(2019,12,31)]*2,
        'reason_text':['销售增长','成本上涨']}).write_parquet(source)
    cache = tmp_path/'cache.sqlite'
    db = ScoreCache(cache)
    for text in ['销售增长','成本上涨']:
        key = score_key(text,settings)
        attempt = db.reserve(key,.01,max_requests=3,max_usd=1.,max_attempts=1)
        db.finish(attempt,state='success',scores={d:{'score':2} for d in DIMENSIONS},cost=.001)
    before = db.totals()
    rows,status = cache_snapshot(source=source,cache=cache,settings=settings,
        allowed_keys={score_key('销售增长',settings)})
    assert rows['text_operating_improvement'].to_list() == [2.,None]
    assert status['selected_successes'] == 1 and status['api_calls'] == 0
    assert db.totals() == before
    db.close()
