"""Pure multi-signal target aggregation and same-account cancellation diagnostics."""
import datetime as dt
import math

import polars as pl


def net_signals(*, targets: pl.DataFrame, budgets: dict[str, float], holdings: pl.DataFrame,
                prices: pl.DataFrame, equity: float, as_of: dt.date, execution_date: dt.date,
                sell_only: bool = False, lot_size: int = 100) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Allocate current positions pro rata to virtual sleeves, not real accounts.

    Gross = abs(net) + 2 * cancelled for every symbol, before lot rounding.
    Rounding is applied only after merging same-account targets. Prices are
    signal-close references and proposed quantities do not imply fills.
    """
    if (not math.isfinite(equity) or equity <= 0 or execution_date <= as_of or lot_size <= 0
            or not budgets or any(not k or not math.isfinite(v) or v <= 0 for k, v in budgets.items())
            or not math.isclose(sum(budgets.values()), 1., abs_tol=1e-12, rel_tol=0)):
        raise ValueError('Invalid equity, date, lot or budget allocation')
    if set(targets['strategy']) != set(budgets):
        raise ValueError('Missing or unexpected strategy target set; cash requires an explicit zero target row')
    if targets.select('strategy', 'symbol').is_duplicated().any():
        raise ValueError('Duplicate strategy/symbol target')
    if targets.filter(pl.col('symbol').is_null() | (pl.col('symbol') == '')
        | (pl.col('as_of') != as_of) | pl.col('as_of').is_null()
        | (pl.col('execution_date') != execution_date) | pl.col('execution_date').is_null()
        | ~pl.col('weight').is_finite().fill_null(False) | (pl.col('weight') < 0) | (pl.col('weight') > 1)).height:
        raise ValueError('Invalid target dates, symbol or weight')
    if targets.group_by('strategy').agg(pl.col('weight').sum()).filter(pl.col('weight') > 1+1e-12).height:
        raise ValueError('Individual strategy target exceeds capital')
    if holdings['symbol'].is_duplicated().any() or prices['symbol'].is_duplicated().any():
        raise ValueError('Duplicate holdings or prices')
    if holdings.filter(~pl.col('quantity').is_finite().fill_null(False) | ~pl.col('settled_quantity').is_finite().fill_null(False)
        | (pl.col('quantity') < 0) | (pl.col('settled_quantity') < 0)
        | (pl.col('settled_quantity') > pl.col('quantity'))
        | (pl.col('quantity') != pl.col('quantity').floor())
        | (pl.col('settled_quantity') != pl.col('settled_quantity').floor())).height:
        raise ValueError('Invalid held or settled quantities')
    symbols = sorted(set(targets['symbol']) | set(holdings['symbol']))
    grid = pl.DataFrame({'symbol': symbols}).join(holdings, on='symbol', how='left', validate='1:1').with_columns(
        pl.col('quantity', 'settled_quantity').fill_null(0)).join(prices, on='symbol', how='left', validate='1:1')
    if grid.filter(~pl.col('price').is_finite().fill_null(False) | (pl.col('price') <= 0)).height:
        raise ValueError('Missing positive reference prices')
    grid = grid.with_columns((pl.col('quantity')*pl.col('price')).alias('held_value'))
    if grid['held_value'].sum() > equity+1e-7:
        raise ValueError('Holdings exceed account equity')
    allocations = pl.DataFrame({'strategy': list(budgets), 'budget': list(budgets.values())})
    sleeves = grid.join(allocations, how='cross').join(targets.select('strategy', 'symbol', 'weight'),
        on=['strategy', 'symbol'], how='left', validate='1:1').with_columns(pl.col('weight').fill_null(0.))
    sleeves = sleeves.with_columns((pl.col('budget')*pl.col('weight')).alias('combined_weight'),
        (pl.col('budget')*(pl.col('weight')*equity-pl.col('held_value'))).alias('signed_notional'))
    merged = sleeves.group_by('symbol').agg(pl.col('combined_weight').sum().alias('weight'),
        pl.col('signed_notional').sum().alias('net_notional'), pl.col('signed_notional').abs().sum().alias('gross_notional'),
        pl.col('signed_notional').clip(lower_bound=0.).sum().alias('gross_buys'),
        (-pl.col('signed_notional').clip(upper_bound=0.)).sum().alias('gross_sells'))
    merged = merged.join(grid, on='symbol', validate='1:1').with_columns(
        pl.min_horizontal('gross_buys', 'gross_sells').alias('cancelled_notional'),
        pl.lit(as_of).alias('as_of'), pl.lit(execution_date).alias('execution_date'))
    merged = merged.with_columns(((pl.col('weight')*equity/pl.col('price')/lot_size).floor()*lot_size).cast(pl.Int64).alias('target_quantity'))
    merged = merged.with_columns((pl.col('target_quantity')-pl.col('quantity')).alias('requested_delta'))
    merged = merged.with_columns(pl.min_horizontal((-pl.col('requested_delta')).clip(lower_bound=0),
        pl.col('settled_quantity')).alias('sell_cap'), (pl.col('quantity') % lot_size).alias('odd_shares'))
    merged = merged.with_columns(pl.when(pl.col('sell_cap') >= pl.col('odd_shares')).then(
        ((pl.col('sell_cap')-pl.col('odd_shares'))/lot_size).floor()*lot_size+pl.col('odd_shares'))
        .otherwise((pl.col('sell_cap')/lot_size).floor()*lot_size).alias('allowed_sell'))
    merged = merged.with_columns(pl.when(pl.col('requested_delta') < 0).then(
        -pl.col('allowed_sell'))
        .when(pl.lit(sell_only)).then(0).otherwise(pl.col('requested_delta')).cast(pl.Int64).alias('proposed_delta'))
    merged = merged.with_columns((pl.col('proposed_delta')*pl.col('price')).alias('proposed_signed_notional'),
        (pl.col('requested_delta')-pl.col('proposed_delta')).alias('withheld_delta'))
    orders = merged.filter(pl.col('proposed_delta') != 0).select('symbol', 'as_of', 'execution_date', 'price',
        pl.when(pl.col('proposed_delta') > 0).then(pl.lit('BUY')).otherwise(pl.lit('SELL')).alias('side'),
        pl.col('proposed_delta').abs().alias('quantity'), pl.col('proposed_signed_notional').abs().alias('notional'))
    error = merged.select((pl.col('gross_notional')-pl.col('net_notional').abs()-2*pl.col('cancelled_notional')).abs().max()).item()
    if error > 1e-7:
        raise ValueError('Netting identity failed')
    return merged.sort('symbol'), sleeves.sort('strategy', 'symbol'), orders.sort('side', 'symbol')
