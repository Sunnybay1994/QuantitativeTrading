import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.return_seasonality import SEASONALITY_NAMES, CONTROL_NAMES
from quant.factors.expressions import required_history
from quant.data.factor_seasonality_inputs import seasonality_price_start, read_seasonality_returns
from quant.research.factor_monthly import attach_monthly_factors
from tests.unit.test_factor_expressions import prepared


def fixture():
    first,last=dt.date(2010,1,1),dt.date(2022,3,1)
    calendar=tuple(first+dt.timedelta(days=i) for i in range((last-first).days+1)
                   if (first+dt.timedelta(days=i)).weekday()<5)
    dates=tuple(d for d in calendar if d<=dt.date(2022,2,15))
    rng=np.random.default_rng(662)
    rows=[]
    for j in range(2):
        prices=10*np.exp(np.cumsum(rng.normal(0,.01,len(dates))))
        rows.extend({'symbol':f'60000{j}.SH','trade_date':d,'close':float(p),'open':float(p),
            'high':float(p*1.01),'low':float(p*.99),'adj_factor':1.,'volume':10000.,'amount':float(p*10000),
            'source':'fixture'} for d,p in zip(dates,prices))
    return pl.from_dicts(rows),calendar


def test_endpoint_reader_uses_calendar_months_and_no_price_fill(monkeypatch):
    from quant.data import factor_seasonality_inputs as inputs
    bars,calendar=fixture()
    bars=bars.filter(~((pl.col('symbol')=='600000.SH') & (pl.col('trade_date')==dt.date(2016,1,29))))
    calls=[]
    def read(**kw):
        calls.append((kw['start'],kw['end']))
        return bars.filter(pl.col('trade_date').is_between(kw['start'],kw['end']))
    monkeypatch.setattr(inputs,'read_stock_data',read)
    assert seasonality_price_start(dt.date(2021,1,4))==dt.date(2016,1,1)
    monthly=read_seasonality_returns(data_root=Path('unused'),refresh_config=Path('unused'),
        calendar=calendar,start=dt.date(2021,1,4),end=dt.date(2021,2,15))
    assert calls[0][0]==dt.date(2016,1,1)
    assert monthly.filter((pl.col('symbol')=='600000.SH') & (pl.col('trade_date')==dt.date(2016,2,29)))['monthly_return'].item() is None
    assert monthly['trade_date'].max()==dt.date(2021,1,29)
    for name in SEASONALITY_NAMES:
        assert required_history(f'delay({name},20)')==52


def test_seasonality_compute_increment_and_year_split_preserve_signals_and_controls(tmp_path,monkeypatch):
    from quant.factors import compute
    from quant.data import factor_seasonality_inputs as inputs
    bars,calendar=fixture()
    monkeypatch.setattr(compute,'available_sessions',lambda root,end:tuple(d for d in calendar if d<=end))
    def read(root,config,start,end,sessions):
        b=bars.filter(pl.col('trade_date').is_between(start,end))
        return prepared(b),b
    monkeypatch.setattr(compute,'read_factor_inputs',read)
    monkeypatch.setattr(compute,'read_stock_data',lambda **kw:pl.DataFrame())
    monkeypatch.setattr(inputs,'read_stock_data',lambda **kw:bars.filter(pl.col('trade_date').is_between(kw['start'],kw['end'])))
    library=tmp_path/'library';library.mkdir()
    for name,direction in zip(SEASONALITY_NAMES,[1,-1,1]):
        (library/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\ndirection={direction}\nfamily="return_seasonality_calendar_y2_5_v1"\nsource_ref="fixture"\n')
    args=dict(refresh_config=Path('unused'),library=library,selected='all',start=dt.date(2020,1,1))
    compute.run(**args,data_root=tmp_path/'increment',artifact_root=tmp_path/'increment_receipts',end=dt.date(2022,1,14))
    compute.run(**args,data_root=tmp_path/'increment',artifact_root=tmp_path/'increment_receipts',end=dt.date(2022,2,15))
    compute.run(**args,data_root=tmp_path/'full',artifact_root=tmp_path/'full_receipts',end=dt.date(2022,2,15))
    for file in (tmp_path/'full/factors').glob('*/year=*/data.parquet'):
        assert_frame_equal(pl.read_parquet(file),pl.read_parquet(tmp_path/'increment'/file.relative_to(tmp_path/'full')))
    for file in (tmp_path/'full_receipts/seasonality_controls').glob('*.parquet'):
        expected=pl.read_parquet(file).sort('symbol','trade_date')
        actual=pl.read_parquet(tmp_path/'increment_receipts/seasonality_controls'/file.name).sort('symbol','trade_date')
        assert_frame_equal(actual,expected)
        assert expected[CONTROL_NAMES[0]].count()>0


def test_long_term_controls_are_required_for_seasonality_incremental():
    from quant.research.seasonality_controls import check_seasonality_controls,RISK_CONTROLS
    panel=pl.DataFrame({c:[1.] for c in [*CONTROL_NAMES,*RISK_CONTROLS,'candidate','admitted']})
    def evaluate(frame,candidate,controls,direction):
        assert set(CONTROL_NAMES)<=set(controls) and 'admitted' in controls and direction==1
        return {'months':96,'newey_west_t':2.5}
    assert check_seasonality_controls(panel,['admitted'],evaluate)['passed']
    assert not check_seasonality_controls(panel.drop(CONTROL_NAMES[0]),[],lambda *a:pytest.fail('missing control'))['passed']
    assert not check_seasonality_controls(panel,[],lambda *a:{'months':95,'newey_west_t':9.})['passed']


def test_new_incomplete_seasonality_month_clears_previous_signal():
    from tests.unit.test_return_seasonality import fixture as monthly_fixture
    monthly,calendar,_=monthly_fixture()
    monthly=monthly.with_columns(pl.when((pl.col('symbol')=='0') & (pl.col('trade_date')==dt.date(2020,2,28)))
        .then(None).otherwise(pl.col('monthly_return')).alias('monthly_return'))
    days=[d for d in calendar if dt.date(2020,12,1)<=d<=dt.date(2021,3,10)]
    panel=pl.DataFrame({'symbol':['0']*len(days),'trade_date':days,'close':[10.]*len(days)})
    result=attach_monthly_factors(panel,pl.DataFrame(),pl.DataFrame(),calendar,SEASONALITY_NAMES,
        seasonality_returns=monthly)
    def value(date):
        return result.filter(pl.col('trade_date')==date)[SEASONALITY_NAMES[0]].item()
    assert value(dt.date(2021,1,29)) is not None
    assert value(dt.date(2021,2,25)) is not None
    assert value(dt.date(2021,2,26)) is None
    assert value(dt.date(2021,3,1)) is None


def test_cached_factor_panels_still_publish_controls_for_a_new_run(tmp_path, monkeypatch):
    """N4 reads run-local controls even when all shared factor panels are cached."""
    from quant.factors import compute
    from quant.data import factor_seasonality_inputs as inputs
    import hashlib

    bars, calendar = fixture()
    monkeypatch.setattr(compute, 'available_sessions',
        lambda root, end: tuple(d for d in calendar if d <= end))
    def read(root, config, start, end, sessions):
        selected = bars.filter(pl.col('trade_date').is_between(start, end))
        return prepared(selected), selected
    monkeypatch.setattr(compute, 'read_factor_inputs', read)
    monkeypatch.setattr(compute, 'read_stock_data', lambda **kw: pl.DataFrame())
    monkeypatch.setattr(inputs, 'read_stock_data', lambda **kw:
        bars.filter(pl.col('trade_date').is_between(kw['start'], kw['end'])))
    library = tmp_path/'library'
    library.mkdir()
    for name, direction in zip(SEASONALITY_NAMES, [1, -1, 1]):
        (library/f'{name}.toml').write_text(
            f'id="{name}"\nexpr="{name}"\ndirection={direction}\n'
            'family="return_seasonality_calendar_y2_5_v1"\nsource_ref="fixture"\n')
    args = dict(data_root=tmp_path/'data', refresh_config=Path('unused'),
        library=library, selected='all', start=dt.date(2020,1,1), end=dt.date(2022,2,15))
    compute.run(**args, artifact_root=tmp_path/'first_run')
    def panels():
        return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in (tmp_path/'data').rglob('*') if p.is_file()}
    before = panels()
    compute.run(**args, artifact_root=tmp_path/'second_run')
    first = sorted((tmp_path/'first_run/seasonality_controls').glob('*.parquet'))
    assert len(first) == 3
    for path in first:
        recovered = tmp_path/'second_run/seasonality_controls'/path.name
        assert recovered.exists(), 'Cached factors must not suppress run-local N4 controls'
        assert_frame_equal(pl.read_parquet(recovered), pl.read_parquet(path))
    assert panels() == before, 'Recovering controls must not rewrite shared factors or labels'
    recovered_root = tmp_path/'second_run/seasonality_controls'
    # A valid middle-year receipt must be enough to resume even after a partial write.
    damaged = recovered_root/'year=2021.parquet'
    damaged.write_bytes(b'interrupted parquet write')
    compute.run(**args, artifact_root=tmp_path/'second_run')
    assert_frame_equal(pl.read_parquet(damaged), pl.read_parquet(first[1]))
    assert panels() == before
    control_files = {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in recovered_root.iterdir() if p.is_file()}
    monkeypatch.setattr(compute, 'read_factor_inputs',
        lambda *a, **kw: pytest.fail('Complete cached factors and controls must skip input computation'))
    compute.run(**args, artifact_root=tmp_path/'second_run')
    assert control_files == {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in recovered_root.iterdir() if p.is_file()}
    assert panels() == before
