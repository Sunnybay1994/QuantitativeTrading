import json
from pathlib import Path

import polars as pl
import pytest

from quant.research import minute_pipeline as pipeline


def setup(monkeypatch,tmp_path):
    import datetime as dt
    calendar=tmp_path/'calendar.parquet'
    pl.DataFrame({'date':[dt.date(2026,9,21)],'is_open':[True]}).write_parquet(calendar)
    blobs={'config.toml':b'auto_trade=false','data/clean/trade_calendar/market=SH/data.parquet':calendar.read_bytes()}
    monkeypatch.setattr(pipeline,'inputs',lambda *args:blobs)
    calls=[]
    def replay(config,output,**kwargs):
        calls.append(output)
        output.mkdir()
        pl.DataFrame(dict(date=['2026-09-21'],one_minute_valid=[True],five_minute_valid=[True],cross_frequency_matched=[True])).write_csv(output/'daily_quality.csv')
        (output/'report.md').write_text('test',encoding='utf-8')
        return dict(missing_or_invalid_calendar_days=[],exit_capacity_unverified=0,valid_days=1,summaries=[dict(cost=2,observed_day_return=-.01)])
    monkeypatch.setattr(pipeline.intraday_afternoon,'run',replay)
    monkeypatch.setattr(pipeline.minute_failure_diagnostics,'diagnose',lambda *args: {})
    return blobs,calls


def test_reuse_and_changed_input_creates_new_frozen_run(monkeypatch,tmp_path):
    blobs,calls=setup(monkeypatch,tmp_path)
    a=pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)
    b=pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)
    assert len(calls)==1 and b['reused']
    assert b['consecutive_valid_sessions']==1
    assert 'nonpositive_stressed_return' in b['attention']
    blobs['config.toml']=b'auto_trade=false\n#new'
    c=pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)
    assert len(calls)==2 and c['fingerprint']!=a['fingerprint']
    assert Path(a['report']).exists()


def test_interrupted_or_corrupt_output_preserves_old_attempt(monkeypatch,tmp_path):
    _,calls=setup(monkeypatch,tmp_path)
    a=pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)
    Path(a['report']).write_text('damaged',encoding='utf-8')
    b=pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)
    assert len(calls)==2 and a['report']!=b['report']
    assert Path(a['report']).read_text()=='damaged'
    checkpoint=Path(b['report']).parent.parent/'checkpoint.json'
    checkpoint.write_text(json.dumps(dict(state='running')),encoding='utf-8')
    c=pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)
    assert len(calls)==3 and c['report']!=b['report']


def test_failed_strategy_does_not_hide_failure(monkeypatch,tmp_path):
    config=tmp_path/'pipeline.toml'
    config.write_text(f'auto_trade=false\noutput={json.dumps(tmp_path.as_posix())}\ndata_root="missing"\nstrategies=["missing.toml"]',encoding='utf-8')
    result=pipeline.run(config)
    assert result['state']=='failed'
    assert result['strategies'][0]['state']=='failed'


def test_snapshot_corruption_never_reused(monkeypatch,tmp_path):
    setup(monkeypatch,tmp_path)
    result=pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)
    frozen=Path(result['report']).parent.parent/'snapshot/config.toml'
    frozen.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Frozen input mismatch'):
        pipeline.research_one(Path('test.toml'),tmp_path,tmp_path)


def test_second_writer_cannot_enter(tmp_path):
    lock=tmp_path/'pipeline.lock'
    with pipeline.instance_lock(lock):
        with pytest.raises(OSError):
            with pipeline.instance_lock(lock):
                pytest.fail('second writer admitted')
