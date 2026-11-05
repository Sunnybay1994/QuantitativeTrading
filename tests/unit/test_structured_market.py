import datetime as dt
import json

import polars as pl

from quant.reporting.structured_market import fund_share_facts,render_fund_shares

UTC=dt.timezone.utc
NOW=dt.datetime(2026,11,5,tzinfo=UTC)


def fixture(tmp_path,rows):
    folder=tmp_path/'data/clean/fund_share/snapshot=test/year=2026'
    folder.mkdir(parents=True)
    (folder.parent/'summary.json').write_text('{}')
    pl.from_dicts(rows).write_parquet(folder/'data.parquet')
    days=pl.date_range(dt.date(2026,9,1),dt.date(2026,10,31),eager=True)
    for market in ('SH','SZ'):
        path=tmp_path/f'data/clean/trade_calendar/market={market}/data.parquet'
        path.parent.mkdir(parents=True)
        pl.DataFrame({'date':days,'is_open':days.dt.weekday()<=5}).write_parquet(path)


def row(date,value,*,seen=NOW,identifier=None):
    return {'ts_code':'510300.SH','trade_date':date,'fd_share':value,'available_at':seen,
        'source_row_id':identifier or date,'source_raw_path':'raw/'+(identifier or date)}


def select(facts):return next(r for r in facts['rows'] if r['symbol']=='510300.SH')


def test_panel_needs_exact_endpoints_and_keeps_native_fund_units(tmp_path):
    fixture(tmp_path,[row('20260930',100.),row('20261030',110.)])
    facts=fund_share_facts('2026-10',root=tmp_path,known_at=NOW)
    value=select(facts)
    assert value['status']=='complete_endpoints' and abs(value['month_change']-.1)<1e-12
    assert value['latest_fd_share']==110. and value['expected_month_end']=='2026-10-30'
    assert not facts['historical_vintage_verified'] and facts['status']=='partial'
    assert '10.00%' in render_fund_shares(facts)
    before=fund_share_facts('2026-10',root=tmp_path,known_at=NOW-dt.timedelta(days=1))
    assert select(before)['status']=='no_visible_observation'


def test_missing_month_end_is_partial_and_never_forward_filled(tmp_path):
    fixture(tmp_path,[row('20260930',100.),row('20261029',105.)])
    value=select(fund_share_facts('2026-10',root=tmp_path,known_at=NOW))
    assert value['status']=='missing_month_endpoint' and value['month_change'] is None
    assert value['month_end_fd_share'] is None and value['latest_date']=='2026-10-29'


def test_later_supplier_revision_only_enters_after_its_available_time(tmp_path):
    fixture(tmp_path,[row('20260930',100.),row('20261030',110.,identifier='old'),
        row('20261030',150.,seen=NOW+dt.timedelta(days=1),identifier='later')])
    early=select(fund_share_facts('2026-10',root=tmp_path,known_at=NOW))
    late=select(fund_share_facts('2026-10',root=tmp_path,known_at=NOW+dt.timedelta(days=2)))
    assert abs(early['month_change']-.1)<1e-12 and late['month_change']==.5


def test_same_timestamp_conflicting_endpoint_stays_unknown(tmp_path):
    fixture(tmp_path,[row('20260930',100.),row('20261030',110.,identifier='a'),row('20261030',150.,identifier='b')])
    value=select(fund_share_facts('2026-10',root=tmp_path,known_at=NOW))
    assert value['status']=='ambiguous_endpoint' and value['month_change'] is None
    assert value['latest_fd_share'] is None and value['month_end_fd_share'] is None


def test_incomplete_calendar_and_current_month_cannot_claim_monthly_change(tmp_path):
    fixture(tmp_path,[row('20260930',100.),row('20261030',110.)])
    for market in ('SH','SZ'):
        p=tmp_path/f'data/clean/trade_calendar/market={market}/data.parquet'
        pl.read_parquet(p).filter(pl.col('date')<dt.date(2026,10,31)).write_parquet(p)
    assert select(fund_share_facts('2026-10',root=tmp_path,known_at=NOW))['status']=='calendar_unavailable'
    assert select(fund_share_facts('2026-10',root=tmp_path,known_at=dt.datetime(2026,10,20,tzinfo=UTC)))['month_change'] is None


def test_no_published_snapshot_does_not_trigger_a_fetch(tmp_path):
    facts=fund_share_facts('2026-10',root=tmp_path,known_at=NOW)
    assert facts['status']=='table_not_captured' and facts['sources']==[]
    json.dumps(facts)


def test_closed_day_share_change_is_retained_but_not_latest_exchange_observation(tmp_path):
    fixture(tmp_path,[row('20260930',100.),row('20261030',110.),row('20261031',999.)])
    value=select(fund_share_facts('2026-10',root=tmp_path,known_at=NOW))
    assert value['latest_date']=='2026-10-30' and value['latest_fd_share']==110.
    assert abs(value['month_change']-.1)<1e-12 and value['nontrading_native_observations']==1
