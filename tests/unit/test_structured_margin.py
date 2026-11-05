import datetime as dt
import json

import polars as pl
import pytest

from quant.reporting.structured_margin import margin_facts,render_margin
from quant.reporting.research_brief import collect_facts,render_template

NOW=dt.datetime(2026,11,5,tzinfo=dt.timezone.utc)


def observation(date,amount,*,symbol='600000.SH',seen=NOW,identifier=None):
    return {'ts_code':symbol,'trade_date':date,'rzye':amount,'rqye':amount/10,
        'rzrqye':amount*1.1,'rzmre':amount/2,'rzche':amount/4,
        'rqyl':999999,'rqmcl':888888,'available_at':seen,
        'source_row_id':identifier or symbol+date,'source_raw_path':'raw/'+(identifier or symbol+date)}


def publish(tmp_path,rows):
    folder=tmp_path/'data/clean/margin_detail/snapshot=test/year=2026'
    folder.mkdir(parents=True)
    (folder.parent/'summary.json').write_text('{}')
    pl.from_dicts(rows).write_parquet(folder/'data.parquet')
    days=pl.date_range(dt.date(2026,9,1),dt.date(2026,10,31),eager=True)
    for market in ('SH','SZ'):
        path=tmp_path/f'data/clean/trade_calendar/market={market}/data.parquet'
        path.parent.mkdir(parents=True)
        pl.DataFrame({'date':days,'is_open':days.dt.weekday()<=5}).write_parquet(path)


def sh(facts):return next(r for r in facts['rows'] if r['market']=='SH')


def test_native_amounts_month_end_and_brief_wiring(tmp_path):
    publish(tmp_path,[observation('20260930',100),observation('20261030',110),
        observation('20260930',200,symbol='510300.SH'),observation('20261030',220,symbol='510300.SH')])
    facts=margin_facts('2026-10',root=tmp_path,known_at=NOW)
    value=sh(facts)
    assert value['status']=='observed_endpoints' and value['latest_security_count']==2
    assert value['latest_cny']['rzye']==330 and value['latest_cny']['rzmre']==165
    assert value['balance_month_change']['rzrqye']==pytest.approx(.1)
    assert not facts['exchange_coverage_verified'] and not facts['historical_vintage_verified']
    assert 'rqmcl' not in value['latest_cny'] and '10.00%' in render_margin(facts)
    brief=collect_facts('2026-10',root=tmp_path)
    assert sh(brief['margin'])['latest_cny']['rzye']==330
    assert '两融明细' in render_template(brief)
    json.dumps(facts)


def test_first_seen_and_revisions_do_not_retroactively_enter(tmp_path):
    publish(tmp_path,[observation('20260930',100),observation('20261030',110,identifier='old'),
        observation('20261030',150,seen=NOW+dt.timedelta(days=1),identifier='new')])
    assert sh(margin_facts('2026-10',root=tmp_path,known_at=NOW))['balance_month_change']['rzye']==pytest.approx(.1)
    assert sh(margin_facts('2026-10',root=tmp_path,known_at=NOW+dt.timedelta(days=2)))['balance_month_change']['rzye']==.5
    before=sh(margin_facts('2026-10',root=tmp_path,known_at=NOW-dt.timedelta(days=1)))
    assert before['status']=='no_visible_observation' and before['latest_cny']['rzye'] is None


def test_equal_count_different_endpoint_securities_cannot_be_compared(tmp_path):
    publish(tmp_path,[observation('20260930',100),observation('20261030',110,symbol='600001.SH')])
    value=sh(margin_facts('2026-10',root=tmp_path,known_at=NOW))
    assert value['status']=='endpoint_universe_changed' and value['balance_month_change']['rzrqye'] is None
    assert value['latest_cny']['rzye']==110


@pytest.mark.parametrize('bad',[None,float('nan'),-1.])
def test_invalid_latest_revision_does_not_restore_older_valid_amount(tmp_path,bad):
    latest=observation('20261030',150,seen=NOW+dt.timedelta(hours=1),identifier='new')
    latest['rzye']=bad
    publish(tmp_path,[observation('20260930',100),observation('20261030',110,identifier='old'),latest])
    value=sh(margin_facts('2026-10',root=tmp_path,known_at=NOW+dt.timedelta(hours=2)))
    assert value['status']=='invalid_or_ambiguous_endpoint'
    assert value['latest_cny']['rzye'] is None and value['balance_month_change']['rzye'] is None


def test_conflicting_same_time_amounts_are_not_arbitrarily_selected(tmp_path):
    publish(tmp_path,[observation('20260930',100),observation('20261030',110,identifier='a'),
        observation('20261030',120,identifier='b')])
    value=sh(margin_facts('2026-10',root=tmp_path,known_at=NOW))
    assert value['status']=='invalid_or_ambiguous_endpoint' and value['latest_cny']['rzrqye'] is None


def test_missing_exact_endpoint_incomplete_calendar_and_current_month(tmp_path):
    publish(tmp_path,[observation('20260930',100),observation('20261029',110)])
    assert sh(margin_facts('2026-10',root=tmp_path,known_at=NOW))['status']=='missing_month_endpoint'
    calendar=tmp_path/'data/clean/trade_calendar/market=SH/data.parquet'
    pl.read_parquet(calendar).filter(pl.col('date')<dt.date(2026,10,31)).write_parquet(calendar)
    assert sh(margin_facts('2026-10',root=tmp_path,known_at=NOW))['status']=='calendar_unavailable'
    current=sh(margin_facts('2026-10',root=tmp_path,known_at=dt.datetime(2026,10,31,tzinfo=dt.timezone.utc)))
    assert current['status']=='month_in_progress' and all(v is None for v in current['balance_month_change'].values())


def test_bj_does_not_borrow_sh_calendar_and_unpublished_pages_are_ignored(tmp_path):
    publish(tmp_path,[observation('20260930',100,symbol='830001.BJ'),observation('20261030',110,symbol='830001.BJ')])
    facts=margin_facts('2026-10',root=tmp_path,known_at=NOW)
    bj=next(r for r in facts['rows'] if r['market']=='BJ')
    assert bj['status']=='calendar_unavailable' and bj['latest_cny']['rzye']==110
    (tmp_path/'data/clean/margin_detail/snapshot=test/summary.json').unlink()
    assert margin_facts('2026-10',root=tmp_path,known_at=NOW)['status']=='table_not_captured'


def test_missing_provenance_and_naive_time_are_rejected(tmp_path):
    with pytest.raises(ValueError,match='timezone-aware'):
        margin_facts('2026-10',root=tmp_path,known_at=NOW.replace(tzinfo=None))
    rows=[observation('20260930',100)]
    rows[0].pop('source_raw_path')
    publish(tmp_path,rows)
    with pytest.raises(ValueError,match='provenance'):
        margin_facts('2026-10',root=tmp_path,known_at=NOW)
