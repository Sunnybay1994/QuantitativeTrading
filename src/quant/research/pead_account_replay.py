"""Continuous personal PEAD40 account using the shared daily accounting engine.

Date-only announcements are assumed known by announcement-day close. Eligibility
and financial vintages are reconstructed history, not fresh out-of-sample data.
Hash order nominates slots; the unchanged engine executes sells then buys by code.
"""

from __future__ import annotations

import bisect
import copy
import datetime as dt
from dataclasses import asdict
import hashlib
import math
from typing import Any

import polars as pl

from quant.backtest import daily_account, daily_simulator
from quant.backtest.costs import AShareCostModel, EtfCostModel
from quant.backtest.rules import DailyMarketState
from quant.backtest.share_exchanges import capture_exchange_holdings
from quant.domain import InstrumentSchema, TradeCalendarSchema
from quant.research.pead_account_actions import (
    apply_actions, augment_positions, occupied_symbols, pending_value, validate_actions,
)
from quant.research.personal_top5_construction import _bind, affordable, reject, star

ORDER_SCHEMA = {'as_of': pl.Date, 'execution_date': pl.Date, 'symbol': pl.String,
                'side': pl.String, 'quantity': pl.Int64}
DECISION_SCHEMA = {
    'date': pl.Date, 'symbol': pl.String, 'side': pl.String, 'reason': pl.String,
    'event_key': pl.String, 'priority_hash': pl.String, 'announcement_date': pl.Date,
    'end_date': pl.Date, 'expiry_date': pl.Date, 'signal_price_date': pl.Date,
    'signal_price': pl.Float64, 'signal_equity': pl.Float64, 'order_as_of': pl.Date,
    'requested_quantity': pl.Int64, 'available_slots': pl.Int64,
    'amount20': pl.Float64, 'notional_cap': pl.Float64,
    'suspension_daily_covered': pl.Boolean,
}


def _finite(value: Any, *, positive: bool = False) -> bool:
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and (value > 0 if positive else True))


def event_key(row: dict) -> str:
    return f"{row['symbol']}|{row['announcement_date']}|{row['end_date']}"


def event_priority(row: dict, salt: str = 'pead40-personal-v1') -> str:
    return hashlib.sha256(f'{salt}|{event_key(row)}'.encode()).hexdigest()


def _check_unique(frame: pl.DataFrame, columns: list[str], label: str) -> None:
    if frame.select(columns).is_duplicated().any():
        raise ValueError(f'Duplicate {label} keys')


def _dates(frame: pl.DataFrame, column: str) -> dict[dt.date, pl.DataFrame]:
    return {key[0]: value for key, value in frame.partition_by(column, as_dict=True).items()}


def _controls(bars: pl.DataFrame, sessions: list[dt.date]) -> pl.DataFrame:
    """Exactly 20 exchange sessions ending at trade_date, including reported zeros."""
    grid = pl.DataFrame({'trade_date': sessions, '_session': range(len(sessions))})
    return (bars.select('symbol', 'trade_date', 'amount').join(grid, on='trade_date', how='inner')
        .sort(['symbol', 'trade_date'])
        .with_columns(pl.when(pl.col('amount').is_finite() & (pl.col('amount') >= 0))
                      .then(pl.col('amount')).otherwise(None).alias('_amount'))
        .with_columns(pl.col('_amount').rolling_mean(20, min_samples=20).over('symbol').alias('amount20'),
                      pl.col('_session').shift(19).over('symbol').alias('_start'))
        .with_columns(pl.when(pl.col('_session') - pl.col('_start') == 19)
                      .then(pl.col('amount20')).otherwise(None).alias('amount20'))
        .select('symbol', 'trade_date', 'amount20'))


def _bar_valid(row: dict | None) -> bool:
    return bool(row and all(_finite(row.get(c), positive=True) for c in ('open', 'high', 'low', 'close', 'adj_factor'))
                and _finite(row.get('volume')) and row['volume'] >= 0
                and _finite(row.get('amount')) and row['amount'] >= 0
                and row['low'] <= min(row['open'], row['close'])
                <= max(row['open'], row['close']) <= row['high'])


def _market(*, row: dict | None, band: dict | None, stopped: bool,
            covered: bool, policy: str, slippage: float) -> tuple[DailyMarketState, str | None]:
    if not _bar_valid(row) or row['volume'] <= 0 or row['amount'] <= 0:
        return DailyMarketState(suspended=True), 'MISSING_OR_INVALID_TRADED_BAR'
    if stopped:
        return DailyMarketState(suspended=True), 'KNOWN_SUSPENSION'
    if policy == 'require_daily_coverage' and not covered:
        return DailyMarketState(suspended=True), 'UNKNOWN_SUSPENSION_COVERAGE'
    if (not band or not _finite(band.get('up_limit'), positive=True)
            or not _finite(band.get('down_limit'), positive=True)
            or band['down_limit'] > band['up_limit']):
        return DailyMarketState(suspended=True), 'UNKNOWN_PRICE_BAND'
    upper = row['open'] * (1 + slippage) >= band['up_limit'] - 1e-9
    lower = row['open'] * (1 - slippage) <= band['down_limit'] + 1e-9
    if upper and lower:
        return DailyMarketState(suspended=True), 'SLIPPAGE_CROSSES_BOTH_LIMITS'
    return DailyMarketState(at_upper_limit=upper, at_lower_limit=lower), None


def _costs(config: dict, multiplier: float) -> dict:
    if multiplier not in (.5, 1., 2.) or isinstance(multiplier, bool):
        raise ValueError('Unregistered cost multiplier')
    costs = copy.deepcopy(config['costs'])
    for values in costs.values():
        if isinstance(values.get('effective_from'), str):
            values['effective_from'] = dt.date.fromisoformat(values['effective_from'])
    if costs['a_share']['commission_min'] != 1.:
        raise ValueError('Personal PEAD requires base minimum commission CNY1')
    return {'a_share': asdict(AShareCostModel(**costs['a_share']).with_execution_cost_multiplier(multiplier)),
            'etf': asdict(EtfCostModel(**costs['etf']).with_execution_cost_multiplier(multiplier))}


def _config(config: dict, case: str, multiplier: float) -> tuple[str, dict]:
    case = 'pead' if case == 'pead40' else case
    if case not in ('pead', 'all_events'):
        raise ValueError('Unknown PEAD/control case')
    if (config['paper']['initial_cash'] != 100000 or config['paper']['auto_trade'] is not False
            or any(config['portfolio'][k] != value for k, value in
                   [('slots', 5), ('cash_buffer', .02), ('max_participation', .05), ('holding_sessions', 40)])
            or config['execution']['priority_salt'] != 'pead40-personal-v1'):
        raise ValueError('Unregistered personal PEAD configuration')
    if config['execution']['suspension_policy'] not in (
        'require_daily_coverage', 'bar_present_known_suspensions_block'
    ):
        raise ValueError('Explicit suspension coverage policy required')
    return case, {'paper': {'name': f'pead40_{case}', 'auto_trade': False, 'initial_cash': 100000.},
                  'costs': _costs(config, multiplier)}


def replay(
    *, events: pl.DataFrame, bars: pl.DataFrame, calendar: pl.DataFrame,
    instruments: pl.DataFrame, limits: pl.DataFrame, suspensions: pl.DataFrame,
    dividends: pl.DataFrame, config: dict, case: str, cost_multiplier: float,
    account_state: dict | None = None, sessions: list[dt.date] | None = None,
    controls: pl.DataFrame | None = None, suspension_coverage: pl.DataFrame | None = None,
) -> dict:
    """Replay one contiguous chunk, committing caller state only on success.

Bars include at least the 20 sessions before the chunk; calendar includes all
announced event horizons. Output frames cover this chunk, state.nav is cumulative.
Missing coverage is logged; an explicit policy determines partial-suspension risk.
"""
    case, account_config = _config(config, case, cost_multiplier)
    calendar = TradeCalendarSchema.validate(calendar)
    all_sessions = sorted(set(calendar.filter(pl.col('is_open'))['date']))
    sessions = list(sessions) if sessions is not None else sorted(set(bars['trade_date']))
    if not sessions or sessions != sorted(set(sessions)):
        raise ValueError('Require ordered unique replay sessions')
    first = bisect.bisect_left(all_sessions, sessions[0])
    if all_sessions[first:first + len(sessions)] != sessions or first == 0:
        raise ValueError('Replay must be contiguous and include prior calendar session')
    if account_state and account_state.get('date') != str(all_sessions[first - 1]):
        raise ValueError('Checkpoint must end on previous exchange session')
    clean_instruments = InstrumentSchema.validate(instruments)
    instrument_rows = {r['symbol']: r for r in clean_instruments.to_dicts()}
    clean_instruments = clean_instruments.with_columns(pl.Series('board_lot', [
        1 if star(s) else instrument_rows[s]['board_lot'] for s in clean_instruments['symbol']], dtype=pl.Int64))
    for frame, keys, name in [(bars, ['symbol', 'trade_date'], 'bar'),
                               (limits, ['symbol', 'trade_date'], 'limit'),
                               (events, ['symbol', 'announcement_date'], 'financial-event')]:
        _check_unique(frame, keys, name)
    required = ['symbol', 'announcement_date', 'end_date', 'status', 'market_eligible',
                'threshold', 'selected', 'earliest_execution_date', 'reference_expiry_date']
    if not set(required) <= set(events.columns):
        raise ValueError('Missing financial/eligibility event columns')
    indexes = {date: i for i, date in enumerate(all_sessions)}
    event_batches: dict[dt.date, list[dict]] = {}
    for row in events.select(required).iter_rows(named=True):
        execution, expiry = row['earliest_execution_date'], row['reference_expiry_date']
        if execution < sessions[0] or execution > sessions[-1]:
            continue
        known_index = bisect.bisect_right(all_sessions, row['announcement_date'])
        if (known_index >= len(all_sessions) or all_sessions[known_index] != execution
                or row['end_date'] > row['announcement_date'] or expiry is None
                or expiry not in indexes or indexes[expiry] - indexes[execution] != 40
                or expiry <= execution):
            raise ValueError(f'Invalid first-execution/40-session event horizon: {event_key(row)}')
        event_batches.setdefault(execution, []).append(row)
    bar_batches, band_batches = _dates(bars, 'trade_date'), _dates(limits, 'trade_date')
    if controls is not None:
        _check_unique(controls, ['symbol', 'trade_date'], 'ADV control')
    control_batches = _dates(_controls(bars, all_sessions) if controls is None else controls, 'trade_date')
    stopped = set(suspensions.select('trade_date', 'symbol').iter_rows())
    coverage: dict[dt.date, bool] = {}
    if suspension_coverage is not None:
        field = 'trade_date' if 'trade_date' in suspension_coverage.columns else 'date'
        _check_unique(suspension_coverage, [field], 'suspension coverage')
        coverage = {row[field]: row['coverage_complete'] is True for row in suspension_coverage.to_dicts()}
    ordinary, same_day = validate_actions(config.get('share_exchanges', []))
    state = copy.deepcopy(account_state) if account_state else {
        'holdings': {}, 'cash': 100000., 'receivables': [], 'pending': [], 'nav': [],
        'inception_date': str(sessions[0]), 'started_with_cash': True,
        'pead_books': {}, 'pead_exchange_pending': [], 'pead_action_history': [],
    }
    identity = {'case': case, 'cost_multiplier': cost_multiplier,
                'priority_salt': config['execution']['priority_salt'],
                'suspension_policy': config['execution']['suspension_policy']}
    if state.get('pead_identity', identity) != identity:
        raise ValueError('Checkpoint belongs to a different experiment case/cost/policy')
    state['pead_identity'] = identity
    state.setdefault('pead_books', {})
    for symbol in occupied_symbols(state):
        if symbol not in state['pead_books']:
            raise ValueError(f'Missing carried PEAD event lineage: {symbol}')
    prior_nav_count = len(state['nav'])
    simulate = _bind(daily_simulator.simulate_daily_targets,
                     _affordable_quantity=affordable, _reject_reason=reject)
    advance = _bind(daily_account.advance, simulate_daily_targets=simulate)
    trades, rejections, positions, decisions, actions = [], [], [], [], []
    policy, salt = identity['suspension_policy'], identity['priority_salt']
    name = account_config['paper']['name']
    slippage = account_config['costs']['a_share']['slippage']

    for date in sessions:
        previous = all_sessions[indexes[date] - 1]
        daily_covered = coverage.get(date, False)
        before_occupied = occupied_symbols(state)
        slots = max(0, 5 - len(before_occupied))
        equity = state['nav'][-1]['equity'] if state['nav'] else 100000.
        today = bar_batches.get(date, bars.head(0))
        today_rows = {row['symbol']: row for row in today.to_dicts()}
        prior_rows = {row['symbol']: row for row in bar_batches.get(previous, bars.head(0)).to_dicts()}
        bands = {row['symbol']: row for row in band_batches.get(date, limits.head(0)).to_dicts()}
        adv = {row['symbol']: row.get('amount20') for row in
               control_batches.get(previous, pl.DataFrame()).to_dicts()}
        manual = []

        def decision(symbol: str, side: str, reason: str, event: dict | None = None, **extra: Any) -> None:
            row = {key: None for key in DECISION_SCHEMA}
            row.update(date=date, symbol=symbol, side=side, reason=reason,
                       signal_price_date=previous, signal_equity=equity, available_slots=slots,
                       order_as_of=max(previous, event['announcement_date']) if event else previous,
                       suspension_daily_covered=daily_covered)
            if event:
                row.update(event_key=event_key(event), priority_hash=event_priority(event, salt),
                           announcement_date=event['announcement_date'], end_date=event['end_date'],
                           expiry_date=event['reference_expiry_date'])
            row.update(extra)
            decisions.append(row)

        def reject_order(symbol: str, side: str, reason: str, quantity: int, price: float | None) -> None:
            manual.append(dict(strategy=name, date=date, symbol=symbol, side=side, reason=reason,
                requested_quantity=quantity, rejected_quantity=quantity, reference_price=price))

        # Collapse same-execution collisions before case filtering. A later
        # ineligible event cannot cause a fallback to an older favourable SUE.
        newest: dict[str, dict] = {}
        for row in sorted(event_batches.get(date, []), key=lambda r: (r['announcement_date'], r['end_date'])):
            old = newest.get(row['symbol'])
            if old is not None:
                decision(row['symbol'], 'BUY', 'SUPERSEDED_SAME_EXECUTION_EVENT', old)
            newest[row['symbol']] = row
        candidates = []
        for row in newest.values():
            eligible = (row['status'] == 'VALID' and row['market_eligible'] is True
                        and _finite(row['threshold']))
            if not eligible or (case == 'pead' and row['selected'] is not True):
                decision(row['symbol'], 'BUY', 'NOT_CASE_CANDIDATE', row)
            elif row['symbol'] in before_occupied:
                decision(row['symbol'], 'BUY', 'HELD_EVENT_IGNORED_NO_EXTENSION', row)
            else:
                candidates.append(row)
        candidates.sort(key=lambda row: event_priority(row, salt))
        nominees = candidates[:slots]
        for row in candidates[slots:]:
            decision(row['symbol'], 'BUY', 'NO_PRIOR_CLOSE_SLOT', row)

        rows = apply_actions(date=date, state=state, ordinary=ordinary, same_day=same_day,
            dividends=dividends, stopped=stopped,
            positive_bar_symbols={s for s, b in today_rows.items() if _bar_valid(b) and b['volume'] > 0})
        actions.extend(rows)
        # Preview dividend quantities for fixed exits; advance performs the same
        # action exactly once on the actual account, including cash receivables.
        prepared = daily_account.prepare_account_actions(date=date, state=state,
                                                          calendar=calendar, dividends=dividends)
        for symbol in prepared['holdings']:
            instrument = instrument_rows.get(symbol)
            if instrument is None or not daily_simulator._instrument_active(instrument, date):
                raise ValueError(f'UNCLASSIFIED_HELD_DELISTING_OR_INSTRUMENT: {symbol} {date}')
            if symbol not in state['pead_books']:
                raise ValueError(f'Missing action-generated holding lineage: {symbol} {date}')
        orders, caps, bought_events = [], {}, {}

        def order(symbol: str, side: str, quantity: int, event: dict | None = None) -> None:
            price = today_rows.get(symbol, {}).get('open')
            market, problem = _market(row=today_rows.get(symbol), band=bands.get(symbol),
                stopped=(date, symbol) in stopped, covered=daily_covered, policy=policy, slippage=slippage)
            del market
            amount20 = adv.get(symbol)
            if problem is None and not _finite(amount20, positive=True):
                problem = 'UNKNOWN_OR_ZERO_PRIOR_20_SESSION_ADV'
            cap = amount20 * .05 if _finite(amount20, positive=True) else None
            decision(symbol, side, problem or 'ORDER_SUBMITTED', event,
                signal_price=prior_rows.get(symbol, {}).get('close'), requested_quantity=quantity,
                amount20=amount20 if _finite(amount20) else None, notional_cap=cap)
            if problem:
                reject_order(symbol, side, problem, quantity, price if _finite(price, positive=True) else None)
                return
            orders.append(dict(as_of=max(previous, event['announcement_date']) if event else previous,
                               execution_date=date, symbol=symbol, side=side, quantity=quantity))
            caps[symbol] = cap

        for symbol, holding in prepared['holdings'].items():
            if state['pead_books'][symbol]['expiry_date'] <= str(date):
                restricted = sum(row['quantity'] for row in prepared['restricted_shares'] if row['symbol'] == symbol)
                sellable = holding['quantity'] - restricted
                if sellable > 0:
                    # An odd residual may sell in full; partially restricted
                    # shares require a normal order increment.
                    step = 1 if star(symbol) else instrument_rows[symbol]['board_lot']
                    if sellable < holding['quantity']:
                        sellable = sellable // step * step
                    if sellable:
                        order(symbol, 'SELL', sellable)
                if restricted or not sellable:
                    decision(symbol, 'SELL', 'WAIT_RESTRICTED_SHARES')
        for item in state.get('pead_exchange_pending', []):
            if state['pead_books'][item['to_symbol']]['expiry_date'] <= str(date):
                decision(item['to_symbol'], 'SELL', 'WAIT_EXCHANGE_SHARE_LISTING')

        for row in nominees:
            symbol = row['symbol']
            price = prior_rows.get(symbol, {}).get('close')
            if symbol in occupied_symbols(state):
                decision(symbol, 'BUY', 'CORPORATE_ACTION_OCCUPIES_NOMINATED_SYMBOL', row)
                continue
            instrument = instrument_rows.get(symbol)
            if instrument is None or not daily_simulator._instrument_active(instrument, date):
                decision(symbol, 'BUY', 'UNKNOWN_OR_INACTIVE_INSTRUMENT', row)
                reject_order(symbol, 'BUY', 'UNKNOWN_OR_INACTIVE_INSTRUMENT', 0, None)
                continue
            if not _bar_valid(prior_rows.get(symbol)):
                decision(symbol, 'BUY', 'MISSING_PREVIOUS_SESSION_CLOSE', row)
                reject_order(symbol, 'BUY', 'MISSING_PREVIOUS_SESSION_CLOSE', 0, None)
                continue
            step, minimum = (1, 200) if star(symbol) else (instrument['board_lot'], instrument['board_lot'])
            quantity = math.floor(equity * .98 / 5 / price / step) * step
            if quantity < minimum or (star(symbol) and quantity > 100000):
                decision(symbol, 'BUY', 'SIGNAL_CLOSE_LOT_CONSTRAINT', row, signal_price=price, requested_quantity=quantity)
                reject_order(symbol, 'BUY', 'SIGNAL_CLOSE_LOT_CONSTRAINT', quantity, price)
                continue
            order(symbol, 'BUY', quantity, row)
            bought_events[symbol] = row

        relevant = set(prepared['holdings']) | {row['symbol'] for row in orders}
        market_states = {(date, symbol): _market(row=today_rows.get(symbol), band=bands.get(symbol),
            stopped=(date, symbol) in stopped, covered=daily_covered, policy=policy, slippage=slippage)[0]
            for symbol in relevant}
        valid_symbols = [s for s in relevant if _bar_valid(today_rows.get(s))]
        engine_bars = today.filter(pl.col('symbol').is_in(valid_symbols))
        engine_instruments = clean_instruments.filter(pl.col('symbol').is_in(relevant))
        metadata = {key: copy.deepcopy(value) for key, value in state.items()
                    if key.startswith('pead_') or key.startswith('share_exchange_')}
        state['pending'] = []
        state, result = advance(date=date, state=state, bars=engine_bars, calendar=calendar,
            instruments=engine_instruments, market_states=market_states, dividends=dividends,
            config=account_config, scheduled_orders=pl.from_dicts(orders, schema=ORDER_SCHEMA),
            execution_notional_caps=caps)
        state.update(metadata)
        for fill in result.trades.filter(pl.col('side') == 'BUY').to_dicts():
            event = bought_events[fill['symbol']]
            state['pead_books'][fill['symbol']] = {
                'expiry_date': str(event['reference_expiry_date']),
                'event_keys': [event_key(event)], 'entry_date': str(date),
            }
        capture_exchange_holdings(date=date, state=state, events=ordinary)
        extra_value = pending_value(state)
        nav = state['nav'][-1]
        nav['market_value'] += extra_value
        nav['equity'] += extra_value
        nav['unit_nav'] = nav['equity'] / 100000.
        nav['exchange_pending_value'] = extra_value
        nav['position_count'] = len(occupied_symbols(state))
        nav['suspension_daily_covered'] = daily_covered
        nav['uncovered_fill_count'] = 0 if daily_covered else result.trades.height
        if nav['position_count'] > 5:
            raise ValueError(f'PEAD occupied-slot invariant exceeded at {date}')
        if not math.isclose(nav['equity'], nav['cash'] + nav['market_value'] + nav['receivable'], abs_tol=1e-7):
            raise ValueError('PEAD account including exchange entitlement does not reconcile')
        positions.append(augment_positions(positions=result.positions, state=state, date=date, strategy=name))
        trades.append(result.trades.with_columns(
            pl.lit(daily_covered).alias('suspension_daily_covered'),
            pl.lit(daily_covered).alias('suspension_coverage_complete')))
        rejected = result.rejections
        if manual:
            rejected = pl.concat([rejected, pl.from_dicts(manual, schema=rejected.schema)], how='vertical_relaxed')
        rejections.append(rejected.with_columns(pl.lit(daily_covered).alias('suspension_daily_covered')))
    nav_frame = pl.from_dicts(state['nav'][prior_nav_count:], infer_schema_length=None).with_columns(pl.col('date').str.to_date())
    output = dict(nav=nav_frame, trades=pl.concat(trades, how='vertical_relaxed'),
        rejections=pl.concat(rejections, how='vertical_relaxed'),
        positions=pl.concat(positions, how='vertical_relaxed'),
        decisions=pl.from_dicts(decisions, schema=DECISION_SCHEMA).with_columns(
            pl.col('suspension_daily_covered').alias('suspension_coverage_complete')),
        actions=pl.from_dicts(actions, infer_schema_length=None) if actions else pl.DataFrame(), state=state)
    if account_state is not None:
        account_state.clear()
        account_state.update(copy.deepcopy(state))
    return output
