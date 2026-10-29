import datetime as dt

from quant.reporting.sample_scope import first_oos_month, months_between, q10_oos_defaults
from quant.reporting.sample_scope import attach_sample_fields, refresh_sample_fields


def test_q10_oos_start_is_2026_10():
    defaults = q10_oos_defaults()
    assert defaults["oos_start"] == "2026-10"
    assert first_oos_month(dt.date(2026, 9, 12)) == "2026-10"


def test_oos_months_grow():
    assert months_between("2026-10", dt.date(2026, 10, 9)) == 1
    assert months_between("2026-10", dt.date(2026, 12, 1)) == 3


def test_retrospective_combo_cannot_gain_oos_from_wall_clock_or_q10_name(tmp_path):
    config=tmp_path/'q10_plus_admitted.toml'; config.touch()
    row=dict(experiment_id='q10_plus_admitted_v1',end='2026-08-31')
    attach_sample_fields(row,settings=dict(registered_on='2026-10-10'),config=config,
                         data_end=dt.date(2026,8,31),as_of=dt.date(2030,1,1))
    assert row['design_date']=='2026-10-10' and row['data_end']=='2026-08-31'
    assert row['oos_start']=='2026-11' and row['oos_months']==0 and row['sample_scope']=='IS_ONLY'


def test_inherited_anchor_is_repaired_and_actual_return_months_are_counted():
    row=dict(design_date='2026-10-10',data_end='2027-01-31',oos_start='2026-10',oos_months=99,sample_scope='HAS_OOS')
    dates=[dt.date(2026,10,30),dt.date(2026,11,4),dt.date(2026,11,20),dt.date(2027,1,5),dt.date(2027,2,1)]
    refresh_sample_fields(row,return_dates=dates)
    assert row['oos_start']=='2026-11' and row['oos_months']==2
    assert row['sample_scope']=='HAS_OOS'
    refresh_sample_fields(row,return_dates=dates,as_of=dt.date(2026,11,1))
    assert row['oos_months']==0 and row['sample_scope']=='IS_ONLY'


def test_later_data_end_without_return_evidence_remains_unverified(tmp_path):
    row=dict(run_path=str(tmp_path),variant='budgeted',design_date='2026-10-10',data_end='2026-12-31')
    refresh_sample_fields(row)
    assert row['oos_months'] is None and row['sample_scope']=='OOS_UNVERIFIED'


def test_only_saved_dated_returns_after_freeze_count_and_first_level_is_not_a_return(tmp_path):
    import polars as pl
    folder=tmp_path/'budgeted/cost_1/2026'; folder.mkdir(parents=True)
    pl.DataFrame({'date':[dt.date(2026,9,30),dt.date(2026,10,5),dt.date(2026,10,20),dt.date(2026,12,1)],
                  'unit_nav':[1.,1.01,1.02,1.03]}).write_parquet(folder/'nav.parquet')
    row=dict(run_path=str(tmp_path),variant='budgeted',design_date='2026-09-12',data_end='2026-12-31')
    refresh_sample_fields(row)
    assert row['sample_scope']=='HAS_OOS' and row['oos_months']==2
    pl.DataFrame({'date':[dt.date(2026,10,5)],'unit_nav':[1.]}).write_parquet(folder/'nav.parquet')
    refresh_sample_fields(row)
    assert row['oos_months']==0 and row['sample_scope']=='IS_ONLY'
