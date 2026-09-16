from pathlib import Path

import polars as pl
import pytest

from quant.reporting.dashboard_curves import compare, read_curve


def spec(tmp_path: Path, name, dates, values):
    path = tmp_path/(name+'.csv')
    pl.DataFrame({'date':dates,'unit_nav':values}).write_csv(path)
    return dict(id=name,label=name,kind='strategy',currency='CNY',basis='NAV',paths=[str(path)])


def test_common_anchor_preserves_missing_sessions_and_source_values(tmp_path):
    a=spec(tmp_path,'a',['2025-01-01','2025-01-02','2025-01-03','2025-01-04'],[10.,20.,30.,40.])
    b=spec(tmp_path,'b',['2025-01-02','2025-01-04','2025-01-05'],[2.,3.,4.])
    result=compare([a,b])
    assert (result['start'],result['end'])==('2025-01-02','2025-01-04')
    assert [p['value'] for p in result['series'][0]['points']]==[0.,.5,1.]
    assert result['series'][1]['points']==[{'date':'2025-01-02','value':0.},{'date':'2025-01-04','value':.5}]
    with pytest.raises(ValueError,match='共同交易日'):
        compare([a,b],start='2025-01-03')


def test_conflicting_duplicate_nav_is_not_silently_combined(tmp_path):
    a=spec(tmp_path,'a',['2025-01-01','2025-01-01'],[1.,2.])
    with pytest.raises(ValueError,match='日期重复'):
        read_curve(a)


def test_nonfinite_nav_is_rejected(tmp_path):
    a=spec(tmp_path,'a',['2025-01-01','2025-01-02'],[1.,float('nan')])
    with pytest.raises(ValueError,match='非有限值'):
        read_curve(a)
