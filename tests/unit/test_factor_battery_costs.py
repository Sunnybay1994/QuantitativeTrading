import datetime as dt
from pathlib import Path
import pytest

import polars as pl

from quant.research.factor_battery_costs import cost_metrics, top_group_targets


def test_factor_costs_preserve_exchange_book_and_reject_changed_resume(tmp_path, monkeypatch):
    from quant.research import factor_battery_costs as module
    statistics = tmp_path/'statistics'
    folder = statistics/'factors'/'example'
    folder.mkdir(parents=True)
    (statistics/'battery.toml').write_text('variants=["raw"]\n[run]\nas_of=2020-02-03\n')
    (folder/'statistics.json').write_text('{}')
    pl.DataFrame({'symbol':['000418.SZ']}).write_parquet(folder/'monthly_scores.parquet')
    targets = pl.DataFrame({'as_of':[dt.date(2020,1,31)],
        'execution_date':[dt.date(2020,2,3)],'symbol':['000418.SZ'],'weight':[1.]})
    monkeypatch.setattr(module,'available_sessions',lambda *args:(dt.date(2020,1,31),dt.date(2020,2,3)))
    monkeypatch.setattr(module,'top_group_targets',lambda *args,**kwargs:targets)
    captured=[]
    def replay(**kwargs):
        captured.append(kwargs['settings']['share_exchanges'])
        return {'fixture':True}
    monkeypatch.setattr(module,'run_cost_plans',replay)
    output=tmp_path/'output'
    module.run_factor_costs(statistics=statistics,output=output,data_root=tmp_path,
                           execution_snapshot='fixture',factor='example')
    assert captured[0][0]['from_symbol']=='000418.SZ'
    assert captured[0][0]['to_symbol']=='000333.SZ'
    assert (output/'share_exchanges.toml').read_text()==Path(
        'configs/data/share_exchanges_20260912.toml').read_text()
    changed=tmp_path/'changed.toml'
    changed.write_text((output/'share_exchanges.toml').read_text().replace('1.15144821','1.2'))
    with pytest.raises(ValueError,match='Resume share exchanges'):
        module.run_factor_costs(statistics=statistics,output=output,data_root=tmp_path,
            execution_snapshot='fixture',factor='example',resume=True,share_exchanges_config=changed)
    assert len(captured)==1


def test_top_targets_use_next_open_and_cash_when_scores_disappear():
    january, february, march = dt.date(2020, 1, 31), dt.date(2020, 2, 28), dt.date(2020, 3, 31)
    scores = pl.DataFrame({"trade_date": [january]*4+[february]*4+[march]*4,
        "symbol": ["A", "B", "C", "D"]*3, "raw": [1., 2., 3., 4.]+[None]*4+[4., 3., 2., 1.]})
    sessions = (january, dt.date(2020, 2, 3), february, dt.date(2020, 3, 2), march, dt.date(2020, 4, 1))
    targets = top_group_targets(scores, variant="raw", sessions=sessions, end=march,
        settings={"groups": 2, "minimum_symbols": 4}, name="fixture")
    assert targets["symbol"].to_list() == ["C", "D", "A"]
    assert targets["weight"].to_list() == [.5, .5, 0.]
    assert targets["execution_date"].to_list() == [dt.date(2020, 2, 3)]*2+[dt.date(2020, 3, 2)]
    assert targets.filter(pl.col("as_of") >= pl.col("execution_date")).is_empty()


def test_constant_factor_has_no_executable_portfolio():
    day = dt.date(2020, 1, 31)
    scores = pl.DataFrame({"trade_date": [day]*4, "symbol": ["A", "B", "C", "D"], "raw": [1.]*4})
    assert top_group_targets(scores, variant="raw", sessions=(day, dt.date(2020, 2, 3)),
        end=dt.date(2020, 2, 3), settings={"groups": 2, "minimum_symbols": 4}, name="fixture").is_empty()


def test_turnover_uses_previous_equity_after_account_growth():
    dates = [dt.date(2020, 1, day) for day in (2, 3, 6)]
    nav = pl.DataFrame({'date': dates, 'equity': [100., 200., 200.], 'unit_nav': [1., 2., 2.],
                        'market_value': [50., 100., 100.], 'cumulative_fees': [0., 0., 0.]})
    trades = pl.DataFrame({'date': [dates[-1]], 'notional': [200.]})
    result = cost_metrics(nav, trades, initial_cash=100.)
    assert result['annualized_one_way_turnover'] == 42.
    assert result['annualized_turnover_on_initial_cash'] == 84.
    assert result['mean_invested_fraction'] == .5
