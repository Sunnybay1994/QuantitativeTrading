"""Optional batch-schema wrapper for a *newly frozen* PEAD experiment.

This module is not connected to the active runner. Canonical immutable inputs are
validated once; the unchanged replay retains every ordinary Python execution and
account check, including _validate_orders, lot/T+1/cash/participation checks and
corporate actions. Published outputs receive equivalent whole-chunk validation.
The temporary Pandera setting must be ContextVar-backed, never a global patch.
"""

from __future__ import annotations

from contextvars import ContextVar
import copy
import datetime as dt
from typing import Any

import pandera.config as pa_config
import pandera.polars as pa
import polars as pl

from quant.domain import (
    BacktestNavSchema, BacktestPositionSchema, BacktestRejectionSchema,
    BacktestTradeSchema, Bar1dSchema, InstrumentSchema, TradeCalendarSchema,
)
from quant.research.pead_account_replay import DECISION_SCHEMA, replay as _reference_replay

ENGINE_REASONS = ('SUSPENDED', 'BUY_AT_UPPER_LIMIT', 'SELL_AT_LOWER_LIMIT',
                  'T_PLUS_ONE', 'CASH_CONSTRAINT', 'LOT_CONSTRAINT',
                  'INSUFFICIENT_SELLABLE', 'PARTICIPATION_CAP')
MANUAL_REASONS = (
    'MISSING_OR_INVALID_TRADED_BAR', 'KNOWN_SUSPENSION', 'UNKNOWN_SUSPENSION_COVERAGE',
    'UNKNOWN_PRICE_BAND', 'SLIPPAGE_CROSSES_BOTH_LIMITS',
    'UNKNOWN_OR_ZERO_PRIOR_20_SESSION_ADV', 'UNKNOWN_OR_INACTIVE_INSTRUMENT',
    'MISSING_PREVIOUS_SESSION_CLOSE', 'SIGNAL_CLOSE_LOT_CONSTRAINT',
)
ZERO_QUANTITY_REASONS = (
    'UNKNOWN_OR_INACTIVE_INSTRUMENT', 'MISSING_PREVIOUS_SESSION_CLOSE',
    'SIGNAL_CLOSE_LOT_CONSTRAINT',
)


class ManualRejectionSchema(pa.DataFrameModel):
    """Adapter rejection evidence; distinct from an executable engine order.

Unknown instrument/price or a sub-lot signal can legitimately have quantity zero.
A missing observation can have no reference price. All other fields and reason
semantics remain explicit; unrecognized reasons cannot bypass engine validation.
"""

    strategy: str
    date: pl.Date
    symbol: str = pa.Field(str_matches=r'^\d{5,6}\.(SH|SZ|HK)$')
    side: str = pa.Field(isin=['BUY', 'SELL'])
    reason: str = pa.Field(isin=list(MANUAL_REASONS))
    requested_quantity: int = pa.Field(ge=0)
    rejected_quantity: int = pa.Field(ge=0)
    reference_price: float = pa.Field(gt=0, nullable=True)

    class Config:
        strict = True
        coerce = True

    @pa.dataframe_check
    def valid(cls, data: pa.PolarsData) -> pl.LazyFrame:
        zero_allowed = pl.col('reason').is_in(ZERO_QUANTITY_REASONS) & (pl.col('side') == 'BUY')
        return data.lazyframe.select(
            ((pl.col('requested_quantity') == pl.col('rejected_quantity')).all()
             & ((pl.col('requested_quantity') > 0) | zero_allowed).all()
             & (pl.col('reference_price').is_null() | pl.col('reference_price').is_finite()).all()
             & (~pl.col('reason').is_in(ZERO_QUANTITY_REASONS) | (pl.col('side') == 'BUY')).all()
             & ~pl.struct('strategy', 'date', 'symbol', 'side', 'reason').is_duplicated().any()
             ).alias('manual_rejection_valid'))


def _columns(schema: type[pa.DataFrameModel]) -> list[str]:
    return list(schema.to_schema().columns)


def _canonical(frame: pl.DataFrame, schema: type[pa.DataFrameModel], name: str) -> pl.DataFrame:
    validated = schema.validate(frame)
    if validated.schema != frame.schema or not validated.equals(frame):
        raise ValueError(f'Batch validation requires canonical {name}; do not change coercion mid-experiment')
    return frame


def _finite(frame: pl.DataFrame, columns: list[str], label: str, *, nonnegative: bool = True) -> None:
    if any(not frame.schema.get(c, pl.Null).is_numeric() for c in columns):
        raise ValueError(f'Invalid numeric schema: {label}')
    predicates = [pl.col(c).is_finite() & pl.col(c).is_not_null()
                  & ((pl.col(c) >= 0) if nonnegative else pl.lit(True)) for c in columns]
    if frame.filter(~pl.all_horizontal(predicates).fill_null(False)).height:
        raise ValueError(f'Nonfinite/negative published values: {label}')


def _validate_outputs(result: dict, *, initial_cash: float, sessions: list[dt.date]) -> None:
    nav, positions = result['nav'], result['positions']
    if nav['date'].to_list() != sessions:
        raise ValueError('Batch NAV must cover every requested session once')
    _finite(nav, ['equity', 'unit_nav', 'cash', 'market_value', 'receivable',
                  'cumulative_fees', 'exchange_pending_value'], 'NAV')
    # The shared schema describes the simulator before cash receivables are
    # added. Exchange entitlement value already belongs to published market_value.
    projection = nav.select(_columns(BacktestNavSchema)).with_columns(
        (pl.col('equity') - nav['receivable']).alias('equity'))
    BacktestNavSchema.validate(projection)
    if nav.filter((pl.col('unit_nav') - pl.col('equity') / initial_cash).abs() > 1e-10).height:
        raise ValueError('Published unit NAV does not match initial capital')
    validated_positions = BacktestPositionSchema.validate(positions.select(_columns(BacktestPositionSchema)))
    # Removing daily coercion leaves an all-null target_weight as Null. Apply
    # exactly the original schema coercion after concatenation, without changing
    # values or dropping the pending-exchange diagnostic columns.
    result['positions'] = positions.with_columns(
        *[validated_positions[column] for column in validated_positions.columns])
    positions = result['positions']
    _finite(positions, ['exchange_pending_quantity', 'exchange_pending_value'], 'exchange positions')
    if positions.select('strategy', 'date', 'symbol').is_duplicated().any():
        raise ValueError('Duplicate published position keys')
    totals = positions.group_by('date').agg(pl.col('market_value').sum().alias('_positions'))
    balanced = nav.join(totals, on='date', how='left').with_columns(pl.col('_positions').fill_null(0.))
    if balanced.filter((pl.col('market_value') - pl.col('_positions')).abs()
                       > pl.max_horizontal(pl.lit(1.), pl.col('market_value').abs()) * 1e-9).height:
        raise ValueError('Published position value does not reconcile with NAV')

    trades = result['trades']
    BacktestTradeSchema.validate(trades.select(_columns(BacktestTradeSchema)))
    _finite(trades, ['price', 'notional', 'fee', 'slippage_cost'], 'trades')
    if trades.filter((pl.col('price') * pl.col('quantity') - pl.col('notional')).abs()
                     > pl.max_horizontal(pl.lit(1.), pl.col('notional').abs()) * 1e-9).height:
        raise ValueError('Trade notional does not match price and quantity')
    rejections = result['rejections']
    unknown = rejections.filter(~pl.col('reason').is_in((*ENGINE_REASONS, *MANUAL_REASONS)))
    if unknown.height or rejections['reason'].null_count():
        raise ValueError('Unknown rejection reason cannot bypass batch validation')
    BacktestRejectionSchema.validate(rejections.filter(pl.col('reason').is_in(ENGINE_REASONS))
                                    .select(_columns(BacktestRejectionSchema)))
    ManualRejectionSchema.validate(rejections.filter(pl.col('reason').is_in(MANUAL_REASONS))
                                   .select(_columns(ManualRejectionSchema)))
    decisions = result['decisions']
    if decisions.schema != {**DECISION_SCHEMA, 'suspension_coverage_complete': pl.Boolean}:
        raise ValueError('Changed decision schema requires explicit wrapper review')
    for label in ('trades', 'decisions'):
        frame = result[label]
        for col in ('suspension_daily_covered', 'suspension_coverage_complete'):
            if frame.schema.get(col) != pl.Boolean or frame[col].null_count():
                raise ValueError('Suspension coverage must be explicit Boolean')
        if frame.filter(pl.col('suspension_daily_covered') != pl.col('suspension_coverage_complete')).height:
            raise ValueError('Conflicting suspension coverage flags')
    for label in ('trades', 'rejections', 'positions', 'decisions'):
        if result[label].filter(~pl.col('date').is_in(sessions)).height:
            raise ValueError(f'{label} outside requested sessions')
    last = nav.row(-1, named=True)
    if result['state']['nav'][-1] != {**last, 'date': str(last['date'])}:
        raise ValueError('Published last NAV and checkpoint disagree')


def replay_batched(**kwargs: Any) -> dict:
    """Identical account path for canonical inputs, with transactional final checks.

Not automatically selected by timing or return performance. Call only from an
explicitly registered future runner whose frozen code includes this wrapper.
"""
    storage = getattr(pa_config, '_CONTEXT_CONFIG', None)
    underlying = storage if isinstance(storage, ContextVar) else getattr(storage, '_config', None)
    if not isinstance(underlying, ContextVar):
        raise RuntimeError('Batch validation requires context-local Pandera settings')
    call = dict(kwargs)
    caller_state = call.get('account_state')
    if caller_state is not None:
        call['account_state'] = copy.deepcopy(caller_state)
    with pa_config.config_context(validation_enabled=True,
                                  validation_depth=pa_config.ValidationDepth.SCHEMA_AND_DATA):
        for name, schema in [('bars', Bar1dSchema), ('calendar', TradeCalendarSchema),
                             ('instruments', InstrumentSchema)]:
            call[name] = _canonical(call[name], schema, name)
        _finite(call['bars'], ['open', 'high', 'low', 'close', 'volume', 'amount', 'adj_factor'], 'bars')
        # No callable/global replacement: every non-Pandera branch in the frozen
        # daily path executes, and errors still propagate without committing state.
        with pa_config.config_context(validation_enabled=False):
            result = _reference_replay(**call)
        sessions = call.get('sessions')
        if sessions is None:
            sessions = sorted(set(call['bars']['trade_date']))
        _validate_outputs(result, initial_cash=call['config']['paper']['initial_cash'], sessions=list(sessions))
    if caller_state is not None:
        caller_state.clear()
        caller_state.update(copy.deepcopy(result['state']))
    return result
