"""Operational counts from filled trades, distinct from submitted orders."""
import polars as pl


def execution_burden(nav: pl.DataFrame, trades: pl.DataFrame) -> dict:
    if nav.is_empty() or nav['date'].is_duplicated().any() or not nav['date'].is_sorted():
        raise ValueError('Require a unique increasing account calendar')
    if trades.height and (trades['date'].null_count() or trades['symbol'].null_count()
            or trades['notional'].null_count() or not trades['notional'].is_finite().all()
            or (trades['notional'] <= 0).any() or not set(trades['date']) <= set(nav['date'])):
        raise ValueError('Require positive finite filled notionals on the account calendar')
    first = nav.filter(pl.col('market_value') > 0)['date'].min()
    active = nav.filter(pl.col('date') >= first) if first is not None else nav.head(0)
    daily = trades.group_by('date').agg(pl.len().alias('fills'), pl.col('symbol').n_unique().alias('symbols'))
    small = trades.filter(pl.col('notional') < 5000).height
    return {'scope': 'filled_records_not_submitted_orders',
        'position_window': 'first_positive_stock_value_through_end_including_later_cash',
        'mean_positions': active['position_count'].mean(), 'max_positions': active['position_count'].max(),
        'fills': trades.height, 'trade_days': daily.height,
        'median_fills_per_trade_day': daily['fills'].median(),
        'max_fills_per_trade_day': daily['fills'].max(),
        'median_symbols_per_trade_day': daily['symbols'].median(),
        'small_fill_threshold': 5000, 'small_fills': small,
        'small_fill_fraction': small/trades.height if trades.height else None}


def render_burden(rows: list[dict]) -> str:
    def number(value: float | int | None) -> str:
        return 'NA' if value is None else f'{value:.2f}'
    lines = ['\n## 成交与持仓负担\n',
        '|组合|成本|平均/最多持仓|成交记录数|成交日笔数中位/最多|低于5000元占比|',
        '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        share = row['small_fill_fraction']
        lines.append(f"|{row['variant']}|{row['cost_multiplier']:g}×|"
            f"{number(row['mean_positions'])}/{number(row['max_positions'])}|{row['fills']}|"
            f"{number(row['median_fills_per_trade_day'])}/{number(row['max_fills_per_trade_day'])}|"
            f"{f'{share:.2%}' if share is not None else 'NA'}|")
    lines.append('\n成交记录数不是提交订单数。持仓均值从首次持股起计算，保留之后空仓日；成交日笔数仅以有成交的日期为分母。\n')
    return '\n'.join(lines)
