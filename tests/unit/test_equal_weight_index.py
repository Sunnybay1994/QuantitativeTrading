import datetime as dt

import polars as pl
import pytest

from quant.data.equal_weight_index import index_day, load_return_benchmarks, monthly_selections

D = dt.date(2020, 2, 3)


def day(state, quotes, *, targets=None, actions=None, delisted=None, stopped=None):
    return index_day(date=D, state=state, quotes={s: {'open': p[0], 'close': p[1], 'volume': 1}
        for s, p in quotes.items()}, actions=actions or {}, delisted=delisted or {},
        stopped=stopped or set(), targets=targets)


def test_weights_drift_instead_of_daily_equal_rebalancing():
    target = {s: {'weight': .5, 'signal_close': 10.0} for s in ('A', 'B')}
    state, row, _ = day({}, {'A': (10., 20.), 'B': (10., 10.)}, targets=target)
    assert row['daily_return'] == pytest.approx(.5)
    assert state['weights']['A'] == pytest.approx(2/3)
    state, row, _ = day(state, {'A': (20., 20.), 'B': (10., 20.)})
    assert state['level'] == pytest.approx(2000.)
    assert row['daily_return'] == pytest.approx(1/3)


def test_rebalance_old_overnight_and_new_intraday():
    state = {'weights': {'A': 1.}, 'last': {'A': 10.}, 'level': 1000.}
    target = {'B': {'weight': 1., 'signal_close': 1.}}
    new, row, _ = day(state, {'A': (20., 200.), 'B': (10., 11.)}, targets=target)
    assert row['opening_index_level'] == pytest.approx(2000.)
    assert new['level'] == pytest.approx(2200.)


@pytest.mark.parametrize('close,cash,ratio', [(9., 1., 0.), (5., 0., 1.)])
def test_gross_dividends_and_shares_offset_ex_date_price_drop(close, cash, ratio):
    state = {'weights': {'A': 1.}, 'last': {'A': 10.}, 'level': 1000.}
    action = {'A': {'ann_date': D-dt.timedelta(days=1), 'div_cash': cash, 'share_ratio': ratio}}
    new, row, events = day(state, {'A': (close, close)}, actions=action)
    assert row['daily_return'] == pytest.approx(0.)
    assert new['level'] == pytest.approx(1000.)
    assert events[0]['kind'] == 'gross_ex_date_distribution'


def test_missing_mark_is_flagged_and_delisting_is_an_actual_loss():
    state = {'weights': {'A': .5, 'B': .5}, 'last': {'A': 10., 'B': 10.}, 'level': 1000.}
    new, row, events = day(state, {'B': (10., 10.)})
    assert row['daily_return'] == 0
    assert row['missing_quote_weight'] == .5
    assert events[0]['kind'] == 'missing_quote_last_mark'
    new, row, _ = day(new, {'B': (10., 10.)}, delisted={'A': D})
    assert new['level'] == 500.
    assert new['weights'] == {'B': 1.}


def test_month_end_membership_is_point_in_time_and_effective_next_session():
    signal = dt.date(2020, 1, 31)
    universe = pl.DataFrame({'trade_date': [signal, signal], 'symbol': ['A', 'B'],
                             'eligible': [True, True], 'close': [10., 10.]})
    members = pl.DataFrame({'snapshot_date': [signal, D], 'symbol': ['A', 'B']})
    result = monthly_selections(universe, members, (signal, D), D)
    assert result['symbol'].to_list() == ['A']
    assert result['effective_date'].to_list() == [D]
    with pytest.raises(ValueError, match='Missing PIT'):
        monthly_selections(universe, members.filter(pl.col('snapshot_date') == D), (signal, D), D)


def test_shared_loader_rebases_but_keeps_first_requested_daily_return(tmp_path, monkeypatch):
    import quant.data.equal_weight_index as module
    config = tmp_path / 'config.toml'
    config.write_text('[benchmarks]\nequal_weight_snapshot="test"\netf_total_return_snapshot="test"')
    dates = [D-dt.timedelta(days=3), D, D+dt.timedelta(days=1)]
    monkeypatch.setattr(module, 'available_sessions', lambda *_: tuple(dates))
    monkeypatch.setattr(module, 'read_etf_total_return', lambda **_: pl.DataFrame({
        'date': dates, 'unit_nav': [10., 11., 12.1]}))
    monkeypatch.setattr(module, 'read_equal_weight_index', lambda **_: pl.DataFrame({
        'date': dates[1:], 'daily_return': [.1, -.1], 'unit_nav': [50., 45.]}))
    result = load_return_benchmarks(config=config, data_root=tmp_path, start=D, end=dates[-1])
    assert result['510300']['unit_nav'].to_list() == pytest.approx([1.1, 1.21])
    assert result['all_market_equal_weight']['unit_nav'].to_list() == pytest.approx([1.1, .99])
    monkeypatch.setattr(module, 'read_equal_weight_index', lambda **_: pl.DataFrame({
        'date': dates[2:], 'daily_return': [.1], 'unit_nav': [50.]}))
    with pytest.raises(ValueError, match='Missing or duplicate'):
        load_return_benchmarks(config=config, data_root=tmp_path, start=D, end=dates[-1])


def test_selected_benchmarks_do_not_load_unavailable_etf(tmp_path, monkeypatch):
    import quant.data.equal_weight_index as module
    config = tmp_path / 'config.toml'
    config.write_text('[benchmarks]\nequal_weight_snapshot="test"')
    monkeypatch.setattr(module, 'available_sessions', lambda *_: (D,))
    monkeypatch.setattr(module, 'read_equal_weight_index', lambda **_: pl.DataFrame({
        'date': [D], 'daily_return': [.1]}))

    def unavailable(**_):
        raise AssertionError('Unrequested ETF must not be loaded')

    monkeypatch.setattr(module, 'read_etf_total_return', unavailable)
    result = load_return_benchmarks(config=config, data_root=tmp_path, start=D, end=D,
                                    names=['all_market_equal_weight'])
    assert list(result) == ['all_market_equal_weight']
    assert result['all_market_equal_weight']['unit_nav'][0] == pytest.approx(1.1)
    for names in ([], ['unknown'], ['510300', '510300']):
        with pytest.raises(ValueError, match='Invalid return benchmark names'):
            load_return_benchmarks(config=config, data_root=tmp_path, start=D, end=D, names=names)
