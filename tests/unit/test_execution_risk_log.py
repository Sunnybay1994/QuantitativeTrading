import copy
import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.execution.execution_risk_log import run, summarize_execution_risk

D0, D1 = dt.date(2026, 9, 9), dt.date(2026, 9, 10)


def case():
    orders = pl.DataFrame([
        {'as_of': str(D0), 'execution_date': str(D1), 'symbol': 'A', 'side': 'BUY',
         'quantity': 100, 'reference_price': 10.0, 'estimated_fill_price': 10.01},
        {'as_of': str(D0), 'execution_date': str(D1), 'symbol': 'B', 'side': 'SELL',
         'quantity': 200, 'reference_price': 20.0, 'estimated_fill_price': 19.98}])
    market = pl.DataFrame([
        {'symbol': 'A', 'trade_date': D0, 'price_date': D0, 'close': 10.0, 'average_amount': 100_000.0},
        {'symbol': 'B', 'trade_date': D0, 'price_date': D0, 'close': 20.0, 'average_amount': 200_000.0}])
    quotes = pl.DataFrame([
        {'symbol': 'A', 'trade_date': D1, 'open': 10.2, 'volume': 1000.0,
         'up_limit': 11.0, 'down_limit': 9.0, 'suspended': False},
        {'symbol': 'B', 'trade_date': D1, 'open': 19.8, 'volume': 1000.0,
         'up_limit': 22.0, 'down_limit': 18.0, 'suspended': False}])
    risk = {'risk': {'mode': 'diagnostic_only', 'auto_trade': False, 'as_of': str(D0),
                    'execution_date': str(D1), 'requires_review': False, 'issues': []},
            'withheld': False, 'halt': False, 'sell_only': False}
    return dict(orders=orders, market=market, risk=risk, execution_quotes=quotes, observed_through=D1)


def fills():
    return pl.DataFrame([
        {'date': D1, 'symbol': 'A', 'side': 'BUY', 'quantity': 40, 'price': 10.3, 'fee': 2.0},
        {'date': D1, 'symbol': 'A', 'side': 'BUY', 'quantity': 10, 'price': 10.4, 'fee': 1.0},
        {'date': D1, 'symbol': 'B', 'side': 'SELL', 'quantity': 200, 'price': 19.7, 'fee': 3.0}])


def rejections():
    return pl.DataFrame([{'date': D1, 'symbol': 'A', 'side': 'BUY', 'reason': 'INSUFFICIENT_CASH',
                          'requested_quantity': 100, 'rejected_quantity': 50}])


def test_participation_signs_and_partial_fills_use_actual_quantities():
    args = case()
    source_risk = copy.deepcopy(args['risk'])
    result = summarize_execution_risk(**args, fills=fills(), rejections=rejections())
    a, b = result['orders']
    assert a['order_participation_rate'] == .01
    assert b['order_participation_rate'] == .02
    assert a['filled_participation_rate'] == pytest.approx((40 * 10.3 + 10 * 10.4) / 100_000)
    assert a['filled_quantity'] == 50 and a['unfilled_quantity'] == 50
    assert a['average_fill_price'] == pytest.approx(10.32)
    assert a['adverse_fill_price_cost_cny'] == pytest.approx(16)
    assert b['adverse_fill_price_cost_cny'] == pytest.approx(60)
    assert result['fill_deviation']['adverse_price_cost'] == pytest.approx(76)
    assert result['fill_deviation']['fees'] == 6
    assert a['adverse_open_gap_bps'] == pytest.approx(200)
    assert b['adverse_open_gap_bps'] == pytest.approx(100)
    assert result['adverse_open_price_cost_cny'] == pytest.approx(60)
    assert result['notional_weighted_adverse_open_gap_bps'] == pytest.approx(120)
    assert result['execution_rejection_counts'] == {'INSUFFICIENT_CASH': 1}
    assert result['risk_decision_withheld'] is False and result['requires_review']
    assert args['risk'] == source_risk


def test_opposite_sides_are_grossed_at_symbol_level_before_participation_check():
    args = case()
    first = args['orders'].head(1).with_columns(pl.lit(300).alias('quantity'))
    second = first.with_columns(pl.lit('SELL').alias('side'))
    args['orders'] = pl.concat([first, second])
    result = summarize_execution_risk(**args)
    assert [r['order_participation_rate'] for r in result['orders']] == [.03, .03]
    assert [r['symbol_gross_participation_rate'] for r in result['orders']] == [.06, .06]
    assert result['participation_exceeded_symbols'] == ['A']


@pytest.mark.parametrize('missing', ['execution_quote', 'signal_quote', 'liquidity', 'nan_open'])
def test_missing_observations_are_unknown_and_never_zero_deviation(missing):
    args = case()
    args['orders'] = args['orders'].head(1)
    if missing == 'execution_quote':
        args['execution_quotes'] = args['execution_quotes'].clear()
    elif missing == 'signal_quote':
        args['market'] = args['market'].clear()
    elif missing == 'liquidity':
        args['market'] = args['market'].with_columns(pl.lit(None, dtype=pl.Float64).alias('average_amount'))
    else:
        args['execution_quotes'] = args['execution_quotes'].with_columns(pl.lit(float('nan')).alias('open'))
    result = summarize_execution_risk(**args)
    row = result['orders'][0]
    assert result['unknown_observation_orders'] == 1 and result['requires_review']
    if missing in ('signal_quote', 'liquidity'):
        assert row['order_participation_rate'] is None
    if missing != 'liquidity':
        assert row['adverse_open_gap_bps'] is None
    assert result['fill_deviation'] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(('column', 'value', 'status'), [
    ('suspended', True, 'official_suspension'),
    ('volume', 0.0, 'missing_execution_quote'),
    ('up_limit', None, 'missing_execution_price_band'),
    ('open', 11.0, 'buy_at_upper_limit'),
])
def test_market_restrictions_do_not_create_executable_prices(column, value, status):
    args = case()
    args['orders'] = args['orders'].head(1)
    args['execution_quotes'] = args['execution_quotes'].head(1).with_columns(pl.lit(value).alias(column))
    result = summarize_execution_risk(**args)
    assert result['orders'][0]['execution_quote_status'] == status
    assert result['orders'][0]['available_open_price'] is None
    assert result['orders'][0]['adverse_open_price_cost_cny'] is None


def test_unobserved_and_observed_empty_fills_are_distinct():
    args = case()
    args['execution_quotes'] = None
    args['observed_through'] = None
    result = summarize_execution_risk(**args)
    assert result['fill_observation_status'] == 'not_supplied'
    assert result['fill_deviation'] is None and result['orders'][0]['filled_quantity'] is None
    assert result['orders'][0]['execution_quote_status'] == 'not_observed'
    assert result['pending_execution_observation_orders'] == 2
    assert not result['requires_review']
    observed = summarize_execution_risk(**case(), fills=fills().clear())
    assert observed['fill_observation_status'] == 'observed_no_fills'
    assert observed['orders'][0]['filled_quantity'] == 0
    assert observed['orders'][0]['adverse_fill_price_cost_cny'] is None
    assert observed['fill_deviation']['adverse_price_cost'] is None
    assert observed['observation_issue_counts']['unexplained_unfilled_quantity'] == 2


def test_sell_limit_and_unpriced_fill_keep_price_comparisons_unknown():
    args = case()
    args['orders'] = args['orders'].tail(1)
    args['market'] = args['market'].with_columns(pl.lit(None, dtype=pl.Float64).alias('close'))
    args['execution_quotes'] = args['execution_quotes'].tail(1).with_columns(pl.lit(18.0).alias('open'))
    result = summarize_execution_risk(**args, fills=fills().tail(1))
    row = result['orders'][0]
    assert row['execution_quote_status'] == 'sell_at_lower_limit'
    assert row['adverse_fill_price_cost_cny'] is None
    assert result['fill_deviation']['adverse_price_cost'] is None
    assert result['fill_deviation']['unpriced_filled_orders'] == 1


def test_existing_withheld_reasons_preserved_separately_from_execution_rejections():
    args = case()
    args['risk']['withheld'] = True
    args['risk']['halt'] = True
    args['risk']['sell_only'] = True
    args['risk']['risk']['requires_review'] = True
    args['risk']['risk']['issues'] = [{'rule': 'single_stock_weight', 'symbol': 'A'},
                                    {'rule': 'industry_weight', 'industry': 'bank'}]
    result = summarize_execution_risk(**args, fills=fills().clear(), rejections=rejections().clear())
    assert result['risk_issue_counts'] == {'industry_weight': 1, 'single_stock_weight': 1}
    assert result['risk_decision_withheld'] and result['risk_halt'] and result['risk_sell_only']
    assert result['execution_rejection_counts'] == {}
    assert result['fill_deviation']['adverse_price_cost'] is None


@pytest.mark.parametrize('invalid', ['future_quote', 'wrong_execution_date', 'duplicate_order',
                                    'reference_mismatch', 'later_adv', 'future_evidence', 'unmatched_fill', 'overfill'])
def test_invalid_or_unmatched_observations_fail(invalid):
    args = case()
    if invalid == 'future_quote':
        args['market'] = args['market'].with_columns(pl.lit(D1).alias('price_date'))
    elif invalid == 'wrong_execution_date':
        args['execution_quotes'] = args['execution_quotes'].with_columns(pl.lit(D0).alias('trade_date'))
    elif invalid == 'duplicate_order':
        args['orders'] = pl.concat([args['orders'], args['orders'].head(1)])
    elif invalid == 'reference_mismatch':
        args['market'] = args['market'].with_columns(pl.lit(1.0).alias('close'))
    elif invalid == 'later_adv':
        args['market'] = args['market'].with_columns(pl.lit(D1).alias('adv_end'))
    elif invalid == 'future_evidence':
        args['observed_through'] = D0
    elif invalid == 'unmatched_fill':
        args['fills'] = fills().with_columns(pl.lit('X').alias('symbol'))
    else:
        args['fills'] = fills().with_columns(pl.lit(1000).alias('quantity'))
    with pytest.raises(ValueError):
        summarize_execution_risk(**args)


def test_empty_orders_remain_a_valid_daily_log():
    args = case()
    args['orders'] = args['orders'].clear()
    result = summarize_execution_risk(**args, fills=fills().clear(), rejections=rejections().clear())
    assert result['order_count'] == 0 and result['orders'] == []
    assert result['adverse_open_price_cost_cny'] is None
    assert not result['requires_review']


def test_saved_log_wrapper_freezes_inputs_and_uses_only_signal_adv(tmp_path, monkeypatch):
    from quant.data import factor_panels, manual_order_inputs, order_risk_inputs
    from quant.data.stock_paper_inputs import StockPaperInputs

    args = case()
    orders_path, risk_path = tmp_path/'orders.csv', tmp_path/'risk.json'
    args['orders'].write_csv(orders_path)
    risk_path.write_text(json.dumps(args['risk']), encoding='utf-8')
    config = Path('configs/paper/execution_risk_log_v1_20260912.toml')
    def signal(**kwargs):
        assert kwargs['as_of'] == D0 and kwargs['lookback'] == 20
        return args['market'], D1
    monkeypatch.setattr(order_risk_inputs, 'read_order_risk_inputs', signal)
    monkeypatch.setattr(factor_panels, 'available_sessions', lambda *_: tuple(D0-dt.timedelta(days=i) for i in reversed(range(20))))
    def observed(**kwargs):
        assert kwargs['as_of'] == D0 and kwargs['execution_date'] == D1
        quotes = args['execution_quotes']
        return StockPaperInputs(bars=quotes.select('symbol', 'trade_date', 'open', 'volume'),
            limits=quotes.select('symbol', 'trade_date', 'up_limit', 'down_limit'),
            suspensions=quotes.select('symbol', 'trade_date').clear(), instruments=pl.DataFrame(),
            calendar=pl.DataFrame(), daily_basic=pl.DataFrame(), names=pl.DataFrame(), dividends=pl.DataFrame())
    monkeypatch.setattr(manual_order_inputs, 'read_manual_replay_inputs', observed)
    output = tmp_path/'result'
    result = run(orders=orders_path, risk=risk_path, output=output, config=config, observed_through=D1)
    assert result['order_count'] == 2
    assert result['orders'][0]['adv_start'] == str(D0-dt.timedelta(days=19))
    assert (output/'orders_input.csv').read_bytes() == orders_path.read_bytes()
    assert (output/'order_risk_log.parquet').is_file()
    assert (output/'execution_quotes.parquet').is_file()
    assert result['quote_timestamp_basis'].endswith('not_vendor_capture_time')
    with pytest.raises(ValueError, match='new output'):
        run(orders=orders_path, risk=risk_path, output=output, config=config)
