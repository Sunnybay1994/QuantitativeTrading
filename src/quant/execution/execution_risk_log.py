"""Summarize saved order risk, ADV participation and later execution observations."""
import argparse
import datetime as dt
import json
import math
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.stock_execution_inputs import stock_session_states
from quant.execution.manual_fills import execution_deviation
from quant.execution.order_risk import RULE_LABELS


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        raise ValueError('Use exchange dates, not implicit timestamp truncation')
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(value)


def _rows_by_symbol(frame: pl.DataFrame, date: dt.date) -> dict[str, dict[str, Any]]:
    if frame['symbol'].is_duplicated().any():
        raise ValueError('Require unique market observations per symbol')
    rows = frame.to_dicts()
    if any(_date(row['trade_date']) != date for row in rows):
        raise ValueError('Market observations differ from the required exchange date')
    for row in rows:
        row['trade_date'] = date
    return {row['symbol']: row for row in rows}


def _opening_quote(row: dict[str, Any] | None, side: str, date: dt.date) -> tuple[str, float | None]:
    if row is None:
        return 'missing_execution_quote', None
    if row.get('suspended') is True:
        return 'official_suspension', None
    if row.get('suspended') is not False or not _positive(row.get('open')) or not _positive(row.get('volume')):
        return 'missing_execution_quote', None
    if (not _positive(row.get('up_limit')) or not _positive(row.get('down_limit'))
            or row['down_limit'] >= row['up_limit']):
        return 'missing_execution_price_band', None
    # Reuse the account's opening-price limit rules, with no assumed fill slippage.
    states = stock_session_states(bars=pl.from_dicts([row]), limits=pl.from_dicts([row]),
        suspensions=pl.DataFrame(schema={'trade_date': pl.Date, 'symbol': pl.String}),
        sessions=[date], symbols=[row['symbol']], execution_dates=[date], slippage=0.0)
    state = states[date, row['symbol']]
    if side == 'BUY' and state.at_upper_limit:
        return 'buy_at_upper_limit', None
    if side == 'SELL' and state.at_lower_limit:
        return 'sell_at_lower_limit', None
    return 'available_daily_open', float(row['open'])


def _execution_observations(*, orders: list[dict[str, Any]], fills: pl.DataFrame | None,
                            rejections: pl.DataFrame | None, date: dt.date) -> tuple[dict | None, list[dict]]:
    planned = {(r['symbol'], r['side']): r for r in orders}
    events: list[dict[str, Any]] = []
    filled: Counter = Counter()
    if fills is not None:
        for index, row in enumerate(fills.iter_rows(named=True)):
            key = row['symbol'], row['side']
            if (_date(row['date']) != date or key not in planned
                    or type(row['quantity']) is not int or row['quantity'] <= 0
                    or not _positive(row['price']) or not math.isfinite(row['fee']) or row['fee'] < 0):
                raise ValueError('Invalid or unmatched saved fill')
            if 'notional' in row and not math.isclose(row['notional'], row['quantity'] * row['price'], rel_tol=1e-9, abs_tol=1e-7):
                raise ValueError('Fill notional differs from shares times price')
            filled[key] += row['quantity']
            if filled[key] > planned[key]['quantity']:
                raise ValueError('Saved fills exceed the planned quantity')
            # The shared helper groups by exchange date; this is not a claimed fill time.
            events.append({'event_id': f'saved-fill-row-{index}', 'timestamp': f'{date}T00:00:00+08:00',
                'kind': row['side'], 'symbol': row['symbol'], 'quantity': row['quantity'],
                'price': row['price'], 'fee': row['fee']})
    rejected: Counter = Counter()
    rejection_rows = []
    if rejections is not None:
        for row in rejections.iter_rows(named=True):
            key = row['symbol'], row['side']
            if (_date(row['date']) != date or key not in planned or not row['reason']
                    or type(row['rejected_quantity']) is not int or row['rejected_quantity'] <= 0
                    or row['requested_quantity'] != planned[key]['quantity']):
                raise ValueError('Invalid or unmatched saved rejection')
            rejected[key] += row['rejected_quantity']
            if rejected[key] + filled[key] > planned[key]['quantity']:
                raise ValueError('Filled and rejected shares exceed the planned quantity')
            rejection_rows.append({**row, 'date': str(date)})
    deviation = execution_deviation(events, orders) if fills is not None else None
    if deviation is not None:
        for row in deviation['orders']:
            if not row['quantity']:
                row['adverse_price_cost'] = None
        if not events:
            deviation['adverse_price_cost'] = None
        deviation['status'] = 'observed_fills' if events else 'observed_no_fills'
    return deviation, rejection_rows


def summarize_execution_risk(*, orders: pl.DataFrame, market: pl.DataFrame, risk: dict[str, Any],
                             liquidity_sessions: int = 20, maximum_participation_rate: float = .05,
                             execution_quotes: pl.DataFrame | None = None, fills: pl.DataFrame | None = None,
                             rejections: pl.DataFrame | None = None,
                             observed_through: dt.date | None = None) -> dict[str, Any]:
    """Keep unavailable observations null; consume existing risk decisions without changing them."""
    decision = risk
    risk = decision.get('risk', decision)
    if risk.get('auto_trade') is not False or risk.get('mode') != 'diagnostic_only':
        raise ValueError('Require an existing diagnostic-only order risk result')
    as_of, execution_date = _date(risk['as_of']), _date(risk['execution_date'])
    if execution_date <= as_of or type(liquidity_sessions) is not int or liquidity_sessions < 1:
        raise ValueError('Invalid execution date or liquidity window')
    if not _positive(maximum_participation_rate) or maximum_participation_rate > 1:
        raise ValueError('Invalid participation limit')
    observed = observed_through is not None and observed_through >= execution_date
    if observed_through is not None and observed_through < as_of:
        raise ValueError('Observation cutoff precedes the signal close')
    if not observed and any(frame is not None for frame in (execution_quotes, fills, rejections)):
        raise ValueError('Later quotes and fills require observed_through >= execution_date')
    planned = orders.to_dicts()
    keys = [(r['symbol'], r['side']) for r in planned]
    if len(keys) != len(set(keys)):
        raise ValueError('Require one planned order per symbol and side')
    for row in planned:
        if (_date(row['as_of']) != as_of or _date(row['execution_date']) != execution_date
                or row['side'] not in ('BUY', 'SELL') or not row['symbol']
                or type(row['quantity']) is not int or row['quantity'] <= 0
                or not _positive(row['reference_price'])):
            raise ValueError('Invalid planned order')
        row['as_of'], row['execution_date'] = str(as_of), str(execution_date)
    data = _rows_by_symbol(market, as_of)
    quotes = _rows_by_symbol(execution_quotes, execution_date) if execution_quotes is not None else {}
    deviation, rejection_rows = _execution_observations(
        orders=planned, fills=fills, rejections=rejections, date=execution_date)
    actual = {(r['symbol'], r['side']): r for r in deviation['orders']} if deviation is not None else {}
    rejected_by_order: dict[tuple, list[str]] = {}
    rejected_quantities: Counter = Counter()
    for rejection in rejection_rows:
        rejected_by_order.setdefault((rejection['symbol'], rejection['side']), []).append(rejection['reason'])
        rejected_quantities[rejection['symbol'], rejection['side']] += rejection['rejected_quantity']
    symbol_notionals: Counter = Counter()
    for order in planned:
        symbol_notionals[order['symbol']] += order['quantity'] * order['reference_price']
    rows: list[dict[str, Any]] = []
    for order in planned:
        symbol, side = order['symbol'], order['side']
        quote = data.get(symbol, {})
        price_date = quote.get('price_date', quote.get('trade_date'))
        if price_date is not None and _date(price_date) > as_of:
            raise ValueError('Signal quote comes from a future date')
        if quote.get('adv_end') is not None and _date(quote['adv_end']) != as_of:
            raise ValueError('ADV must end on the signal date')
        signal_known = _positive(quote.get('close')) and price_date is not None and _date(price_date) == as_of
        if signal_known and not math.isclose(quote['close'], order['reference_price'], rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError('Saved reference price differs from the signal close')
        raw_amount = quote.get('average_amount')
        amount = float(raw_amount) if _positive(raw_amount) and raw_amount is not None else None
        liquid = signal_known and amount is not None
        notional = order['quantity'] * order['reference_price']
        participation = notional / amount if liquid and amount is not None else None
        combined = symbol_notionals[symbol] / amount if liquid and amount is not None else None
        status, opening = _opening_quote(quotes.get(symbol), side, execution_date) if observed else ('not_observed', None)
        signed_gap = (opening / order['reference_price'] - 1) * (1 if side == 'BUY' else -1) if opening is not None and signal_known else None
        fill = actual.get((symbol, side))
        reasons = sorted(set(rejected_by_order.get((symbol, side), [])))
        row_issues = []
        if not signal_known:
            row_issues.append('missing_or_stale_signal_quote')
        if not liquid:
            row_issues.append('missing_liquidity')
        if combined is not None and combined > maximum_participation_rate:
            row_issues.append('order_participation')
        if observed and status != 'available_daily_open':
            row_issues.append(status)
        if (fill is not None and order['quantity'] - fill['quantity'] > rejected_quantities[symbol, side]
                and decision.get('withheld') is not True and decision.get('halt') is not True):
            row_issues.append('unexplained_unfilled_quantity')
        rows.append({'symbol': symbol, 'side': side, 'quantity': order['quantity'],
            'as_of': str(as_of), 'execution_date': str(execution_date),
            'reference_price': order['reference_price'], 'signal_quote_date': str(price_date) if price_date else None,
            'signal_quote_timestamp': f'{price_date}T15:00:00+08:00' if price_date else None,
            'signal_quote_status': 'available_daily_close' if signal_known else 'unknown',
            'planned_notional_cny': notional, 'adv_amount_cny': amount,
            'adv_start': str(quote['adv_start']) if quote.get('adv_start') else None,
            'adv_end': str(as_of), 'adv_sessions': liquidity_sessions,
            'order_participation_rate': participation, 'symbol_gross_participation_rate': combined,
            'filled_participation_rate': fill['notional'] / amount if fill is not None and fill['quantity'] and liquid and amount is not None else None,
            'participation_status': 'unknown' if combined is None else ('exceeded' if combined > maximum_participation_rate else 'within_limit'),
            'execution_quote_status': status,
            'execution_open_price': float(quotes[symbol]['open']) if symbol in quotes and _positive(quotes[symbol].get('open')) else None,
            'execution_quote_timestamp': f'{execution_date}T09:30:00+08:00' if quotes.get(symbol) else None,
            'available_open_price': opening, 'adverse_open_gap_bps': signed_gap * 10000 if signed_gap is not None else None,
            'adverse_open_price_cost_cny': signed_gap * notional if signed_gap is not None else None,
            'filled_quantity': fill['quantity'] if fill is not None else None,
            'unfilled_quantity': order['quantity'] - fill['quantity'] if fill is not None else None,
            'average_fill_price': fill['average_fill_price'] if fill is not None else None,
            'adverse_fill_price_cost_cny': fill['adverse_price_cost'] if fill is not None and fill['quantity'] and signal_known else None,
            'fill_fees_cny': fill['fees'] if fill is not None else None,
            'execution_rejected_quantity': rejected_quantities[symbol, side] if rejections is not None else None,
            'execution_rejection_reasons': reasons, 'issues': row_issues})
    if deviation is not None:
        known_fills = [row for row in rows if row['adverse_fill_price_cost_cny'] is not None]
        for row in rows:
            actual[row['symbol'], row['side']]['adverse_price_cost'] = row['adverse_fill_price_cost_cny']
        deviation['adverse_price_cost'] = sum(row['adverse_fill_price_cost_cny'] for row in known_fills) if known_fills else None
        deviation['comparable_filled_orders'] = len(known_fills)
        deviation['unpriced_filled_orders'] = sum(bool(row['filled_quantity']) and row['adverse_fill_price_cost_cny'] is None for row in rows)
    risk_counts = Counter(item['rule'] for item in risk['issues'])
    rejection_counts = Counter(row['reason'] for row in rejection_rows)
    issues = Counter(issue for row in rows for issue in row['issues'])
    comparable = [row for row in rows if row['adverse_open_gap_bps'] is not None]
    weight = sum(row['planned_notional_cny'] for row in comparable)
    unknown = sum(row['participation_status'] == 'unknown' or (observed and row['execution_quote_status'].startswith('missing_')) for row in rows)
    return {'mode': 'diagnostic_only', 'auto_trade': False, 'as_of': str(as_of),
        'execution_date': str(execution_date), 'observed_through': str(observed_through) if observed_through else None,
        'observation_cutoff_timestamp': f'{observed_through}T15:00:00+08:00' if observed_through else None,
        'observation_cutoff_basis': 'provided_completed_exchange_date_close',
        'adv_definition': {'metric': 'arithmetic_mean_daily_amount_cny', 'sessions': liquidity_sessions,
            'through_signal_close_inclusive': True, 'complete_positive_amount_window_required': True,
            'order_basis': 'gross_planned_shares_times_signal_close_without_netting_sides',
            'maximum_participation_rate': maximum_participation_rate},
        'quote_timestamp_basis': 'exchange_daily_bar_open_or_close_convention_not_vendor_capture_time',
        'fill_timestamp_precision': 'trade_date_only',
        'order_count': len(rows), 'orders': rows, 'unknown_observation_orders': unknown,
        'pending_execution_observation_orders': 0 if observed else len(rows),
        'participation_exceeded_symbols': sorted({r['symbol'] for r in rows if r['participation_status'] == 'exceeded'}),
        'risk_requires_review': risk['requires_review'], 'risk_decision_withheld': decision.get('withheld'),
        'risk_halt': decision.get('halt'), 'risk_sell_only': decision.get('sell_only'),
        'risk_issue_counts': dict(sorted(risk_counts.items())),
        'risk_issue_labels': {key: RULE_LABELS.get(key, key) for key in risk_counts},
        'execution_rejection_counts': dict(sorted(rejection_counts.items())) if rejections is not None else None,
        'execution_rejections': rejection_rows if rejections is not None else None,
        'observation_issue_counts': dict(sorted(issues.items())),
        'comparable_open_orders': len(comparable),
        'adverse_open_price_cost_cny': sum(r['adverse_open_price_cost_cny'] for r in comparable) if comparable else None,
        'notional_weighted_adverse_open_gap_bps': sum(r['adverse_open_gap_bps'] * r['planned_notional_cny'] for r in comparable) / weight if weight else None,
        'fill_deviation': deviation,
        'fill_observation_status': deviation['status'] if deviation is not None else 'not_supplied',
        'requires_review': bool(risk['requires_review'] or issues or rejection_rows),
        'caveat': 'Daily open is a market-price proxy; signal-to-open/fill gaps include overnight moves and are not pure slippage.'}


def run(*, orders: Path, risk: Path, output: Path, config: Path,
        data_root: Path = Path('data'), fills: Path | None = None, rejections: Path | None = None,
        observed_through: dt.date | None = None) -> dict[str, Any]:
    """Read existing local snapshots; save an independent log for daily integration."""
    if output.exists():
        raise ValueError('Use a new output directory')
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings['mode'] != 'diagnostic_only' or settings['auto_trade'] is not False:
        raise ValueError('Execution logging requires auto_trade=false')
    decision = json.loads(risk.read_text(encoding='utf-8'))
    risk_result = decision.get('risk', decision)
    as_of, date = _date(risk_result['as_of']), _date(risk_result['execution_date'])
    planned = pl.read_csv(orders, schema_overrides={'as_of': pl.String, 'execution_date': pl.String})
    symbols = sorted(set(planned['symbol']))
    from quant.data.factor_panels import available_sessions
    from quant.data.manual_order_inputs import read_manual_replay_inputs
    from quant.data.order_risk_inputs import read_order_risk_inputs

    market, next_session = read_order_risk_inputs(data_root=data_root, refresh_config=Path(settings['refresh_config']),
        symbols=symbols, as_of=as_of, lookback=settings['liquidity_sessions'])
    if next_session != date:
        raise ValueError('Saved execution date is not the next exchange session')
    sessions = available_sessions(data_root, as_of)
    history = sessions[-settings['liquidity_sessions']:]
    market = market.with_columns(pl.lit(history[0]).alias('adv_start'), pl.lit(as_of).alias('adv_end'))
    quotes = None
    if observed_through is not None and observed_through >= date:
        inputs = read_manual_replay_inputs(data_root=data_root, settings=settings, symbols=symbols,
            as_of=as_of, execution_date=date)
        quotes = inputs.bars.filter(pl.col('trade_date') == date).join(
            inputs.limits.filter(pl.col('trade_date') == date).select('symbol', 'up_limit', 'down_limit'),
            on='symbol', how='left', validate='1:1').with_columns(
                pl.col('symbol').is_in(inputs.suspensions.filter(pl.col('trade_date') == date)['symbol'].to_list()).alias('suspended'))
    actual = pl.read_csv(fills, try_parse_dates=True) if fills is not None else None
    rejected = pl.read_csv(rejections, try_parse_dates=True) if rejections is not None else None
    result = summarize_execution_risk(orders=planned, market=market, risk=decision,
        liquidity_sessions=settings['liquidity_sessions'], maximum_participation_rate=settings['maximum_participation_rate'],
        execution_quotes=quotes, fills=actual, rejections=rejected, observed_through=observed_through)
    result['sources'] = {'orders': str(orders), 'risk': str(risk), 'config': str(config),
        'fills': str(fills) if fills else None, 'rejections': str(rejections) if rejections else None,
        'data_root': str(data_root), 'refresh_config': settings['refresh_config']}
    result['recorded_at'] = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
    output.mkdir(parents=True, exist_ok=False)
    for name, path in (('config.toml', config), ('risk_input.json', risk), ('orders_input.csv', orders),
                       ('fills_input.csv', fills), ('rejections_input.csv', rejections)):
        if path is not None:
            (output/name).write_bytes(path.read_bytes())
    market.write_parquet(output/'signal_market.parquet')
    if quotes is not None:
        quotes.write_parquet(output/'execution_quotes.parquet')
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    if result['orders']:
        pl.from_dicts(result['orders'], infer_schema_length=None).write_parquet(output/'order_risk_log.parquet')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--orders', type=Path, required=True)
    parser.add_argument('--risk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/paper/execution_risk_log_v1_20260912.toml'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--fills', type=Path)
    parser.add_argument('--rejections', type=Path)
    parser.add_argument('--observed-through', type=dt.date.fromisoformat)
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps({'output': str(args.output), 'order_count': result['order_count'],
        'requires_review': result['requires_review'], 'unknown_observation_orders': result['unknown_observation_orders']}))


if __name__ == '__main__':
    main()
