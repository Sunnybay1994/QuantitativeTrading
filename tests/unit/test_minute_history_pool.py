import datetime as dt
import json

import polars as pl

from quant.data import minute_history as mod


def pool_config(tmp_path):
    watch = tmp_path / 'hk.toml'
    watch.write_text('consumer="hk_strategy"\n[[members]]\nsymbol="00700.HK"\n'
                     '[[members]]\nsymbol="00001.HK"\n[[members]]\nsymbol="600000.SH"\n')
    us = tmp_path / 'us.toml'
    us.write_text('consumer="us_strategy"\n[[members]]\nsymbol="SPY.US"\n'
                  '[[members]]\nsymbol="AAPL.US"\n')
    ah = tmp_path / 'ah.toml'
    ah.write_text('consumer="ah_strategy"\n[[pairs]]\na_symbol="601318.SH"\n'
                  'h_symbol="02318.HK"\n')
    snapshot = tmp_path / 'eligible.parquet'
    pl.DataFrame({'symbol': ['00700.HK', '00001.HK', '09999.HK'],
                  'buy_eligible': [True, True, True]}).write_parquet(snapshot)
    pools = tmp_path / 'pools.toml'
    pools.write_text('\n'.join(f'{key}="{value.as_posix()}"' for key, value in {
        'hk_connect_watch': watch, 'us_universe_path': us, 'ah_dual_list': ah,
        'hk_connect_snapshot': snapshot,
    }.items()))
    config = tmp_path / 'history.toml'
    config.write_text(f'auto_trade=false\ndata_root="{(tmp_path / "data").as_posix()}"\n'
                      f'output="{(tmp_path / "out").as_posix()}"\n'
                      f'post_close_config="{pools.as_posix()}"\n'
                      'consumer_priority=["us_strategy","hk_strategy","ah_strategy"]\n'
                      'start="2026-01-01"\nend="2026-10-28"\n'
                      'end_policy="latest_completed_session"\nmax_seconds=10\nmax_new_symbols=1\n')
    return config


def test_history_plan_is_bounded_prioritized_and_has_market_specific_end(tmp_path, monkeypatch):
    config = pool_config(tmp_path)

    def no_provider():
        raise AssertionError('Planning must not open OpenD or charge History KL quota')

    monkeypatch.setattr(mod, 'FutuRealtime', no_provider)
    monkeypatch.setattr('quant.data.post_close_k1m.latest_market_session',
                        lambda market, **_: dt.date(2026, 10, 27 if market == 'us' else 28))
    result = mod.run(config, check_only=True)
    plan = json.loads((tmp_path / 'out/plan.json').read_text())
    assert result['universe_symbols'] == result['pending_symbols'] == 5
    assert [row['symbol'] for row in plan['queue']] == [
        'AAPL.US', 'SPY.US', '00001.HK', '00700.HK', '02318.HK']
    assert all(row['end'] == ('2026-10-27' if row['symbol'].endswith('.US') else '2026-10-28')
               for row in plan['queue'])


def test_history_download_obeys_consumer_priority_and_new_symbol_cap(tmp_path, monkeypatch):
    config = pool_config(tmp_path)
    calls, closed = [], []

    class Client:
        context = object()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(mod, 'FutuRealtime', Client)
    monkeypatch.setattr(mod, 'history_quota', lambda _: (0, 100, set()))
    monkeypatch.setattr('quant.data.post_close_k1m.latest_market_session',
                        lambda market, **_: dt.date(2026, 10, 27 if market == 'us' else 28))

    def download(context, symbol, start, end, raw, clean):
        calls.append((symbol, start, end))
        return {'symbol': symbol}

    monkeypatch.setattr(mod, 'download_year', download)
    result = mod.run(config)
    assert calls == [('AAPL.US', '2026-01-01', '2026-10-27')]
    assert result['pause_reason'] == 'max_new_symbols'
    assert result['newly_charged_attempts'] == 1 and closed == [True]


def test_expired_consumer_cannot_reenter_history_pool(tmp_path):
    import tomllib

    config = pool_config(tmp_path)
    (tmp_path / 'us.toml').write_text('as_of=2026-01-01\n[[members]]\nsymbol="SPY.US"\n')
    settings = tomllib.loads(config.read_text())
    members = mod.history_universe(settings)
    assert {row['symbol'] for row in members} == {'00001.HK', '00700.HK', '02318.HK'}


def test_same_day_queue_is_bounded_and_does_not_include_open_us_session(tmp_path, monkeypatch):
    for symbol in ['00700.HK', 'SPY.US', 'AAPL.US']:
        p = tmp_path / f'clean/futu_minute/all_market/symbol={symbol}/year=2026/data.parquet'
        p.parent.mkdir(parents=True)
        pl.DataFrame({'trade_date': [dt.date(2026, 10, 27)]}).write_parquet(p)
    monkeypatch.setattr(mod, 'liquid_mid_large', lambda _: [])
    queue = mod.same_day_queue(tmp_path, '2026-10-28', {},
                               allowed_symbols={'00700.HK', 'SPY.US'},
                               market_ends={'hk': '2026-10-28', 'us': '2026-10-27'})
    assert [(r['symbol'], r['gap_end']) for r in queue] == [('00700.HK', '2026-10-28')]
