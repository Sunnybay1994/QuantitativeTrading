import datetime as dt
import json

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.backtest.account_reconciliation import validate_nav
from quant.research.cost_history_schema import concat_nav_history


def annual(day, *, diagnostics=False):
    frame=pl.DataFrame(dict(date=[day],equity=[100.],unit_nav=[1.],cash=[100.],receivable=[0.]))
    if diagnostics:
        frame=frame.with_columns(pl.lit(100.).alias('reconciliation_expected_equity'),
            pl.lit(100.).alias('reconciliation_previous_equity'),
            pl.lit(0.).alias('reconciliation_unexplained_return'))
    return frame


@pytest.fixture
def actions(tmp_path):
    path=tmp_path/'actions.parquet'
    pl.DataFrame(dict(share_ratio=[.1],adjust_share_price=[True])).write_parquet(path)
    return path


def test_mixed_years_keep_exact_economic_values_without_fabricating_diagnostics(actions):
    old=annual(dt.date(2025,12,31))
    new=annual(dt.date(2026,1,5),diagnostics=True).with_columns(pl.col('receivable').cast(pl.Int64))
    before_old,before_new=old.clone(),new.clone()
    value,coverage=concat_nav_history([old,new],execution_dividends=actions)
    assert_frame_equal(value,pl.concat([old,new.select(old.columns)],how='vertical_relaxed'))
    assert_frame_equal(old,before_old);assert_frame_equal(new,before_new)
    assert coverage['legacy_rows']==coverage['diagnostic_rows']==1
    assert not coverage['full_reconciliation_evidence']
    assert coverage['action_compatibility']['changed_action_semantics_present'] is False
    with pytest.raises(ValueError,match='Missing independent'):
        validate_nav(value)


@pytest.mark.parametrize('diagnostics',[False,True])
def test_uniform_histories_keep_their_original_schema(diagnostics):
    frames=[annual(dt.date(2025,12,31),diagnostics=diagnostics),annual(dt.date(2026,1,5),diagnostics=diagnostics)]
    value,coverage=concat_nav_history(frames)
    assert_frame_equal(value,pl.concat(frames))
    assert coverage['full_reconciliation_evidence'] is diagnostics


@pytest.mark.parametrize('change',['missing','extra','partial','invalid','null'])
def test_unknown_or_invalid_schema_never_silently_aligns(actions,change):
    old=annual(dt.date(2025,12,31));new=annual(dt.date(2026,1,5),diagnostics=True)
    if change=='missing':new=new.drop('cash')
    elif change=='extra':new=new.with_columns(pl.lit(1.).alias('new_economic_field'))
    elif change=='partial':new=new.drop('reconciliation_expected_equity')
    elif change=='invalid':new=new.with_columns(pl.lit(0.).alias('reconciliation_expected_equity'))
    else:new=new.with_columns(pl.lit(None,dtype=pl.Float64).alias('reconciliation_unexplained_return'))
    with pytest.raises(ValueError):concat_nav_history([old,new],execution_dividends=actions)


@pytest.mark.parametrize('semantic',['missing_snapshot','missing_flag','nullable_price','consolidation','conversion','nonboolean'])
def test_mixed_history_rejects_unverified_or_changed_action_semantics(actions,semantic):
    path=actions
    if semantic=='missing_snapshot':path=None
    elif semantic=='missing_flag':
        pl.DataFrame(dict(share_ratio=[.1])).write_parquet(path)
    elif semantic=='nullable_price':
        pl.DataFrame({'share_ratio':[.1],'adjust_share_price':pl.Series([None],dtype=pl.Boolean)}).write_parquet(path)
    elif semantic=='nonboolean':
        pl.DataFrame(dict(share_ratio=[.1],adjust_share_price=[0])).write_parquet(path)
    else:
        kind='SHARE_CONSOLIDATION' if semantic=='consolidation' else 'SHARE_CONVERSION'
        pl.DataFrame(dict(share_ratio=[-.5],adjust_share_price=[True],action_type=[kind])).write_parquet(path)
    with pytest.raises(ValueError):
        concat_nav_history([annual(dt.date(2025,12,31)),annual(dt.date(2026,1,5),diagnostics=True)],execution_dividends=path)


def test_no_positive_share_action_needs_no_invented_price_flag(actions):
    pl.DataFrame(dict(share_ratio=[0.,-.1])).write_parquet(actions)
    _,coverage=concat_nav_history([annual(dt.date(2025,12,31)),annual(dt.date(2026,1,5),diagnostics=True)],
                                 execution_dividends=actions)
    assert coverage['action_compatibility']['changed_action_semantics_present'] is False


def test_report_uses_original_action_snapshot_for_mixed_cached_years(tmp_path,actions):
    from quant.research.factor_battery_cost_report import load_cost_history
    data=tmp_path/'data';capture=data/'clean/stock_execution/captured';capture.mkdir(parents=True)
    (capture/'dividends.parquet').write_bytes(actions.read_bytes())
    run=tmp_path/'run';run.mkdir()
    (run/'summary.json').write_text('{}')
    (run/'replay_config.json').write_text(json.dumps(dict(data_root=str(data),snapshot='captured')))
    frames=[annual(dt.date(2025,12,31)),annual(dt.date(2026,1,5),diagnostics=True)]
    for year,frame in zip((2025,2026),frames):
        folder=run/'raw/cost_1'/str(year);folder.mkdir(parents=True)
        frame.write_parquet(folder/'nav.parquet')
        frame.select('date').write_parquet(folder/'trades.parquet')
    nav,trades=load_cost_history(run,'raw',1,dt.date(2026,1,5))
    assert_frame_equal(nav,pl.concat([frame.select(frames[0].columns) for frame in frames]))
    assert trades.height==2
