import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.monthly_open_inputs import daily_open_facts, digest, policy_of, extension_version, evaluation_source_identity, validate_binding
from quant.data.stock_open_suspensions import POLICY
from quant.data import nightly_month_inputs as inputs

DAY = dt.date(2026,9,30)


def fixture(tmp_path, *, raw=True, timing='13:00-15:00'):
    folder = tmp_path/'daily'
    folder.mkdir()
    keys = pl.DataFrame({'symbol':['000001.SZ'], 'trade_date':[DAY]})
    keys.write_parquet(folder/'suspensions.parquet')
    pl.DataFrame({'symbol':['000001.SZ','000002.SZ']}).write_parquet(folder/'instruments.parquet')
    paths=[]
    if raw:
        source = tmp_path/'raw/tushare/suspend_d/date=2026-09-30/data.parquet'
        source.parent.mkdir(parents=True)
        pl.DataFrame({'ts_code':['000001.SZ'], 'trade_date':['20260930'],
            'suspend_type':['S'], 'suspend_timing':[timing]}, schema_overrides={'suspend_timing':pl.String}).write_parquet(source)
        source.with_suffix('.json').write_text(json.dumps({'source':'tushare','table':'suspend_d',
            'rows':1,'parameters':{'trade_date':'20260930'}, 'checksum_sha256':digest(source)}))
        paths=[str(source)]
    (folder/'sources.json').write_text(json.dumps({'as_of':str(DAY),'raw':paths}))
    bars=keys.with_columns(pl.lit(100.).alias('volume'))
    return folder,bars


def test_raw_intervals_restore_information_lost_by_two_column_clean(tmp_path):
    folder,bars=fixture(tmp_path)
    original=(folder/'suspensions.parquet').read_bytes()
    facts, receipt=daily_open_facts(folder, DAY, bars)
    assert facts['open_status'].to_list()==['clear_at_open']
    assert facts['suspension_policy'].to_list()==[POLICY]
    assert receipt['negative_coverage_verified']
    assert (folder/'suspensions.parquet').read_bytes()==original


def test_missing_raw_blocks_unknown_universe_instead_of_clearing(tmp_path):
    folder,bars=fixture(tmp_path,raw=False)
    facts,receipt=daily_open_facts(folder,DAY,bars)
    assert facts.height==2 and set(facts['open_status'])=={'unknown'}
    assert not receipt['negative_coverage_verified']


def test_positive_volume_unspecified_timing_remains_unknown(tmp_path):
    folder,bars=fixture(tmp_path,timing=None)
    facts,_=daily_open_facts(folder,DAY,bars)
    assert facts['open_status'].item()=='unknown'


def test_receipt_corruption_rejected(tmp_path):
    folder,bars=fixture(tmp_path)
    raw=Path(json.loads((folder/'sources.json').read_text())['raw'][0])
    meta=json.loads(raw.with_suffix('.json').read_text())
    meta['checksum_sha256']='bad'
    raw.with_suffix('.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='Invalid daily'):
        daily_open_facts(folder,DAY,bars)


def test_mixed_policy_cannot_be_reused(tmp_path):
    pl.DataFrame({'symbol':['000001.SZ','000002.SZ'],'trade_date':[DAY,DAY],
        'suspension_policy':[POLICY,None],'open_status':['unknown',None]}).write_parquet(tmp_path/'suspensions.parquet')
    with pytest.raises(ValueError,match='Mixed'):
        policy_of(tmp_path)


def test_existing_target_rejected_before_capture_or_mutation(tmp_path,monkeypatch):
    target=tmp_path/'clean/stock_execution/existing'
    target.mkdir(parents=True)
    original=target/'suspensions.parquet'
    original.write_bytes(b'frozen')
    monkeypatch.setattr(inputs,'_capture_day',lambda *a: pytest.fail('capture called'))
    with pytest.raises(ValueError,match='cannot be overwritten'):
        inputs._daily_extensions({'data_root':str(tmp_path),'execution_snapshot':'old'},DAY,tmp_path/'out','existing')
    assert original.read_bytes()==b'frozen'


def test_sources_generate_separate_versions(tmp_path):
    settings={'data_root':str(tmp_path),'execution_snapshot':'old','battery_config':'b.toml'}
    assert extension_version(settings,DAY)==extension_version(settings,DAY)
    assert extension_version(settings,DAY)!=extension_version({**settings,'execution_snapshot':'new'},DAY)


def test_resume_rejects_changed_source_before_reusing_saved_settings(tmp_path,monkeypatch):
    out=tmp_path/'run'
    out.mkdir()
    identity={'execution_snapshot':'old','battery_config':'b','return_benchmark_config':'r','measurement_config':'m'}
    (out/'request.json').write_text(json.dumps({'as_of':str(DAY),'sources':identity}))
    (out/'settings.json').write_text(json.dumps(identity))
    monkeypatch.setattr(inputs,'inspect_month_inputs',lambda **kw:pytest.fail('wrong source reused'))
    with pytest.raises(ValueError,match='another source/policy'):
        inputs.ensure_nightly_month_inputs(settings={**identity,'execution_snapshot':'new'},as_of=DAY,output=out)


def test_opening_battery_identity_separates_legacy_and_return_sources(tmp_path):
    folder,bars=fixture(tmp_path)
    facts,_=daily_open_facts(folder,DAY,bars)
    execution=tmp_path/'clean/stock_execution'
    old=execution/'old'
    new=execution/'new'
    old.mkdir(parents=True)
    new.mkdir()
    facts.select('symbol','trade_date').write_parquet(old/'suspensions.parquet')
    facts.filter(pl.col('open_status')!='clear_at_open').write_parquet(new/'suspensions.parquet')
    battery=tmp_path/'battery.toml'
    returns=tmp_path/'returns.toml'
    battery.write_text('start=2010-01-01\n')
    returns.write_text('[benchmarks]\nequal_weight_snapshot="old"\n')
    settings={'data_root':str(tmp_path),'execution_snapshot':'old','as_of':DAY,
        'battery_config':str(battery),'return_benchmark_config':str(returns)}
    assert evaluation_source_identity(settings)==b''
    settings['execution_snapshot']='new'
    token=evaluation_source_identity(settings)
    assert token and token==evaluation_source_identity(settings)
    returns.write_text('[benchmarks]\nequal_weight_snapshot="other"\n')
    assert token!=evaluation_source_identity(settings)
    index=tmp_path/'clean/equal_weight_indexes/other'
    index.mkdir(parents=True)
    (index/'summary.json').write_text(json.dumps({'execution_snapshot':'old'}))
    with pytest.raises(ValueError,match='not bound'):
        validate_binding(settings,tmp_path)
