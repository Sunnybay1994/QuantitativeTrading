import datetime as dt
import json
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.price_delay import PRICE_DELAY_NAMES
from quant.factors.expressions import required_history
from quant.research.factor_monthly import attach_monthly_factors
from tests.unit.test_factor_monthly import sample
from tests.unit.test_factor_expressions import prepared


def fixture():
    bars, basic, calendar = sample()
    dates = sorted(set(bars['trade_date']))
    rng = np.random.default_rng(57)
    market = pl.DataFrame({'trade_date': dates, 'index_level': 100*np.exp(np.cumsum(rng.normal(0,.01,len(dates))))})
    return bars, basic, calendar, market


def test_price_delay_month_end_carry_no_future_and_new_null_replaces_old():
    bars, basic, calendar, market = fixture()
    def attach(b, m):
        return attach_monthly_factors(prepared(b), b, basic, calendar, PRICE_DELAY_NAMES, price_delay_market=m)
    result = attach(bars, market)
    cut = dt.date(2021, 8, 13)
    short = attach(bars.filter(pl.col('trade_date') <= cut), market.filter(pl.col('trade_date') <= cut))
    assert_frame_equal(short, result.filter(pl.col('trade_date') <= cut))
    invalid = market.with_columns(pl.when(pl.col('trade_date') >= dt.date(2021,7,1)).then(None)
                                 .otherwise(pl.col('index_level')).alias('index_level'))
    changed = attach(bars, invalid)
    def val(day):
        return changed.filter((pl.col('symbol') == '600000.SH') & (pl.col('trade_date') == day))[PRICE_DELAY_NAMES[0]].item()
    assert val(dt.date(2021, 7, 30)) is not None
    assert val(dt.date(2022, 1, 31)) is None
    assert val(dt.date(2022, 2, 1)) is None
    assert result[PRICE_DELAY_NAMES[0]].count() > 100
    for name in PRICE_DELAY_NAMES:
        assert required_history(f'ts_mean({name},20)') == 419


def test_price_delay_compute_year_split_and_increment_match_full(tmp_path, monkeypatch):
    from quant.factors import compute
    bars, basic, calendar, market = fixture()
    monkeypatch.setattr(compute, 'available_sessions', lambda root,end: tuple(d for d in calendar if dt.date(2019,1,1)<=d<=end))
    def read(root,config,start,end,sessions):
        selected=bars.filter(pl.col('trade_date').is_between(start,end))
        return prepared(selected), selected
    monkeypatch.setattr(compute,'read_factor_inputs',read)
    monkeypatch.setattr(compute,'read_stock_data',lambda **kw: basic.filter(pl.col('trade_date').is_between(kw['start'],kw['end'])))
    monkeypatch.setattr(compute,'read_price_delay_market',lambda root,config,start,end: market.filter(pl.col('trade_date').is_between(start,end)))
    library=tmp_path/'library'
    library.mkdir()
    for name in PRICE_DELAY_NAMES:
        (library/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\nfamily="price_delay"\ndirection=1\nsource_ref="fixture"\n')
    args=dict(refresh_config=Path('unused'),library=library,selected='all',start=dt.date(2019,1,1),artifact_root=tmp_path/'artifacts')
    compute.run(**args,data_root=tmp_path/'increment',end=dt.date(2022,1,14))
    compute.run(**args,data_root=tmp_path/'increment',end=dt.date(2022,2,15))
    compute.run(**args,data_root=tmp_path/'full',end=dt.date(2022,2,15))
    for file in (tmp_path/'full/factors').glob('*/year=*/data.parquet'):
        assert_frame_equal(pl.read_parquet(file),pl.read_parquet(tmp_path/'increment'/file.relative_to(tmp_path/'full')))


def test_price_delay_index_version_type_and_precoverage(tmp_path):
    from quant.data.factor_benchmark import read_price_delay_market
    folder=tmp_path/'clean/index_benchmarks/pinned'
    folder.mkdir(parents=True)
    summary={'start':'2020-01-01','end':'2020-01-31','series':[{'index_code':'H00985.CSI','return_type':'total_return'}]}
    (folder/'summary.json').write_text(json.dumps(summary))
    pl.DataFrame({'index_code':['H00985.CSI'],'trade_date':[dt.date(2020,1,2)],'index_level':[100.]}).write_parquet(folder/'data.parquet')
    config=tmp_path/'refresh.toml'
    config.write_text('price_delay_index_version="pinned"\n')
    assert read_price_delay_market(tmp_path,config,dt.date(2018,1,1),dt.date(2019,1,1)).is_empty()
    assert read_price_delay_market(tmp_path,config,dt.date(2018,1,1),dt.date(2020,1,3)).height==1
    with pytest.raises(ValueError,match='coverage'):
        read_price_delay_market(tmp_path,config,dt.date(2020,1,1),dt.date(2020,2,1))
    summary['series'][0]['return_type']='price'
    (folder/'summary.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError,match='total_return'):
        read_price_delay_market(tmp_path,config,dt.date(2018,1,1),dt.date(2019,1,1))


def test_price_delay_n4_requires_fixed_controls_and_full_original_history():
    from quant.research.price_delay_controls import CONTROLS, check_price_delay_controls
    spec=tomllib.loads(Path('configs/research/price_delay_family_v1.toml').read_text())
    assert list(CONTROLS)==spec['additional_controls']
    assert not check_price_delay_controls(pl.DataFrame({'candidate':[1.]}),[],lambda *a: pytest.fail('missing controls'))['passed']
    panel=pl.DataFrame({name:[1.] for name in [*CONTROLS,'candidate','admitted_x']})
    def evaluate(frame,candidate,names,direction):
        assert names==['admitted_x',*CONTROLS]
        assert candidate=='candidate' and direction==1
        return {'months':96,'newey_west_t':2.5}
    assert check_price_delay_controls(panel,['admitted_x'],evaluate)['passed']
    assert not check_price_delay_controls(panel,[],lambda *a: {'months':95,'newey_west_t':10.})['passed']
