import datetime as dt

import numpy as np
import pandas as pd
import polars as pl
import pytest

from quant.research.market_indicators import (
    aggregate_daily, conditional_returns, prior_percentiles, realtime_snapshot,
    score_states, stock_features,
)

SETTINGS = dict(minimum_stocks=2, minimum_coverage=.8, normalization_window=20,
                minimum_history=10, low_percentile=20., high_percentile=80.,
                quote_max_age_seconds=120)


def inputs():
    days = pd.bdate_range('2024-01-01', periods=240).date.tolist()
    rows = []
    for symbol in ['600001.SH', '000001.SZ', '300001.SZ']:
        for i, day in enumerate(days):
            close = 10 + .01 * i + .1 * np.sin(i)
            rows.append(dict(symbol=symbol, trade_date=day, open=close, close=close,
                             high=close+.2, low=close-.2, volume=1000.,
                             amount=10000.+i, adj_factor=1.))
    bars = pl.DataFrame(rows)
    basic = bars.select('symbol', 'trade_date').with_columns(
        pl.lit(2.).alias('turnover_rate'), pl.lit(1e8).alias('circulating_market_value'))
    return days, bars, basic


def test_gaps_splits_and_duplicate_detection():
    days, bars, basic = inputs()
    bars = bars.filter(~((pl.col('symbol') == '600001.SH') & (pl.col('trade_date') == days[30])))
    p = stock_features(bars, basic, days)
    row = p.filter((pl.col('symbol') == '600001.SH') & (pl.col('trade_date') == days[31])).row(0, named=True)
    assert row['return'] is None and row['above_ma20'] is None and row['amihud20'] is None
    split = bars.with_columns(
        *[pl.when(pl.col('trade_date') >= days[50]).then(pl.col(c)/2).otherwise(pl.col(c)).alias(c)
          for c in ['open', 'high', 'low', 'close']],
        pl.when(pl.col('trade_date') >= days[50]).then(2.).otherwise(1.).alias('adj_factor'))
    p2 = stock_features(split, basic, days)
    assert p2['return'].to_list() == p['return'].to_list()
    with pytest.raises(ValueError, match='Duplicate'):
        stock_features(pl.concat([bars, bars.head(1)]), basic, days)


def test_coverage_missing_names_and_negative_breadth():
    days, bars, basic = inputs()
    bars = bars.filter(~((pl.col('symbol') == '600001.SH') & (pl.col('trade_date') == days[-1])))
    bars = bars.with_columns(*[pl.when(pl.col('trade_date') == days[-1]).then(pl.col(c)*.9)
                              .otherwise(pl.col(c)).alias(c) for c in ['open', 'close', 'high', 'low']])
    p = stock_features(bars, basic, days)
    last = aggregate_daily(p, 2, .8).tail(1).row(0, named=True)
    assert last['reference_stocks'] == 3 and last['coverage'] == pytest.approx(2/3)
    assert last['advance_decline_balance'] is None and not last['coverage_ok']
    last2 = aggregate_daily(p, 2, .6).tail(1).row(0, named=True)
    assert last2['advance_decline_balance'] == -1


def test_past_only_normalization_and_state_timing():
    values = pd.Series([1., 1., 1., 2., np.nan, 1000.])
    assert prior_percentiles(values, 3, 2).iloc[2] == 50.
    assert prior_percentiles(values, 3, 2).iloc[3] == 100.
    pd.testing.assert_series_equal(prior_percentiles(values[:4], 3, 2), prior_percentiles(values, 3, 2)[:4])
    days, bars, basic = inputs()
    daily = aggregate_daily(stock_features(bars, basic, days), 2, .8)
    benchmark = pl.DataFrame({'date': days, 'unit_nav': np.exp(np.arange(len(days))*.001)})
    full = score_states(daily, benchmark, days, SETTINGS)
    prefix = score_states(daily.head(225), benchmark.head(225), days[:226], SETTINGS)
    assert full.head(225).equals(prefix.head(225))
    assert full['effective_date'][4] == days[5]
    missing = score_states(daily.filter(pl.col('trade_date') != days[-2]), benchmark, days, SETTINGS)
    assert missing['market_state'][-2] == 'unknown'
    assert missing['liquidity_score'][-2] is None


def test_conditional_returns_uses_next_session():
    states = pl.DataFrame({'effective_date': [dt.date(2024, 1, 3), dt.date(2024, 1, 4)],
                           'market_state': ['stress', 'trend_up']})
    returns = pd.DataFrame({'s': [.99, -.01, .02]}, index=pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04']))
    result = conditional_returns(states, returns).set_index('state')
    assert result.loc['stress', 'mean_daily_bps'] == -100
    assert result.loc['trend_up', 'mean_daily_bps'] == 200


def test_realtime_population_time_and_exrights_reference():
    now = dt.datetime.fromisoformat('2026-09-22T10:00:00+08:00')
    ref = pl.DataFrame({'symbol': ['600001.SH', '000001.SZ', '300001.SZ'],
                        'ma20': [9., 9., 9.], 'adj_close': [10., 10., 10.]})
    def quote(symbol, **kw):
        return dict(symbol=symbol, provider_time=now-dt.timedelta(seconds=1),
                    received_at=now, last_price=5.1, amount=100., volume=10., **kw)
    quotes = [quote(s, prev_close=5., bid=5., ask=5.2,
                    past_same_time_amount=50., baseline_end_date='2026-09-21', baseline_clock='09:59')
              for s in ref['symbol']]
    result = realtime_snapshot(quotes, ref, now=now, settings=SETTINGS)
    assert result['coverage_ok'] and result['advance_decline_balance'] == 1
    assert result['above_prior_ma20_fraction'] == 1
    assert result['same_time_amount_ratio'] == 2
    assert result['liquidity_score'] is None and result['market_state'] == 'unknown'
    assert realtime_snapshot(quotes[:1], ref, now=now, settings=SETTINGS)['advance_decline_balance'] is None
    quotes[0]['provider_time'] = now-dt.timedelta(seconds=121)
    quotes[1]['received_at'] = now+dt.timedelta(seconds=1)
    quotes[2].pop('prev_close')
    quotes[2]['baseline_end_date'] = '2026-09-22'
    result = realtime_snapshot(quotes, ref, now=now, settings=SETTINGS)
    assert result['fresh_stocks'] == 1 and not result['coverage_ok']
    assert result['advance_decline_balance'] is None and result['same_time_amount_stocks'] == 0
    assert result['rejected'] == {'stale': 1, 'future_or_inconsistent_time': 1}


def test_live_runner_serializes_dates_and_rejects_stale_reference(tmp_path, monkeypatch):
    from quant.research.market_indicators_run import live
    config = tmp_path / 'config.toml'
    config.write_text('auto_trade=false\n' + '\n'.join(f'{k}={v}' for k, v in SETTINGS.items()))
    root = tmp_path / 'history'
    root.mkdir()
    prior = dt.date(2026, 9, 21)
    now = dt.datetime.fromisoformat('2026-09-22T10:00:00+08:00')
    reference = pl.DataFrame({'symbol': ['600001.SH'], 'trade_date': [prior]})
    reference.write_parquet(root / 'latest_reference.parquet')
    pl.DataFrame({'trade_date': [prior], 'market_state': ['mixed']}).write_parquet(root / 'market_states.parquet')
    (root / 'source_manifest.json').write_text('{}')
    calendar = tmp_path / 'data/clean/trade_calendar/market=SH/data.parquet'
    calendar.parent.mkdir(parents=True)
    pl.DataFrame({'date': [prior, now.date()], 'is_open': [True, True]}).write_parquet(calendar)
    quotes = tmp_path / 'quotes.json'
    quotes.write_text('[]')
    monkeypatch.chdir(tmp_path)
    result = live(config, root, tmp_path / 'out', now=now, quotes_path=quotes)
    assert result['previous_close_state'][0]['market_state'] == 'mixed'
    assert not result['coverage_ok'] and (tmp_path / 'out/report.md').is_file()
    with pytest.raises(ValueError, match='preceding exchange session'):
        live(config, root, tmp_path / 'out2', now=now+dt.timedelta(days=1), quotes_path=quotes)
