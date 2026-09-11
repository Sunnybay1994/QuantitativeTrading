"""Replay risk-filtered manual share lists through the shared daily account."""
import argparse
import copy
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.backtest.daily_account import advance
from quant.data.stock_execution_inputs import stock_session_states
from quant.data.stock_paper_inputs import StockPaperInputs
from quant.execution.manual_orders import prepare_manual_orders


def replay_orders(*, state: dict[str, Any], orders: pl.DataFrame, execution_date: dt.date,
                  inputs: StockPaperInputs, config: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Execute the decided share list; later prices never change planned share counts."""
    as_of = dt.date.fromisoformat(state['date'])
    sessions = sorted(set(inputs.calendar.filter(pl.col('is_open') & (pl.col('date') > as_of))['date']))
    if not sessions or execution_date != sessions[0]:
        raise ValueError('Replay requires the next open session')
    if orders.height and (set(orders['as_of'].cast(pl.String)) != {state['date']}
                          or set(orders['execution_date'].cast(pl.String)) != {str(execution_date)}):
        raise ValueError('Replay order dates differ from the closed account')
    symbols = sorted(set(state['holdings']) | set(orders['symbol']))
    today = inputs.bars.filter(pl.col('trade_date') == execution_date)
    suspended = set(inputs.suspensions.filter(pl.col('trade_date') == execution_date)['symbol'])
    if set(symbols) - set(today['symbol']) - suspended:
        raise ValueError('Missing execution price without official suspension')
    market_states = stock_session_states(bars=inputs.bars, limits=inputs.limits,
        suspensions=inputs.suspensions, sessions=[execution_date], symbols=symbols,
        execution_dates=[execution_date] if orders.height else [],
        slippage=config['costs']['a_share']['slippage'])
    source = copy.deepcopy(state)
    source['pending'] = []
    source.setdefault('receivables', [])
    # This isolated session starts at unit NAV 1; do not append it to a manual
    # Modified Dietz history that may contain prior external cash flows.
    source['nav'] = []
    source['cumulative_fees'] = 0.0
    return advance(date=execution_date, state=source, bars=inputs.bars,
        calendar=inputs.calendar, instruments=inputs.instruments, market_states=market_states,
        dividends=inputs.dividends, config=config, scheduled_orders=orders)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--targets', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    settings = tomllib.loads(args.config.read_text(encoding='utf-8'))
    if settings['mode'] != 'rehearsal' or settings['auto_trade'] is not False:
        raise ValueError('Require rehearsal mode and auto_trade=false')
    from quant.data.manual_order_inputs import read_manual_order_inputs, read_manual_replay_inputs

    state = json.loads(args.state.read_text(encoding='utf-8'))
    targets = pl.read_csv(args.targets, schema_overrides={
        'as_of': pl.String, 'execution_date': pl.String, 'weight': pl.Float64})
    symbols = sorted(set(state['holdings']) | set(targets['symbol']))
    as_of = dt.date.fromisoformat(state['date'])
    signal_inputs, market, date = read_manual_order_inputs(data_root=args.data_root,
        settings=settings, symbols=symbols, as_of=as_of)
    base_costs = tomllib.loads(Path(settings['cost_config']).read_text(encoding='utf-8'))['costs']
    plans = []
    for scale in (0.5, 1.0, 2.0):
        costs = copy.deepcopy(base_costs)
        for model in costs.values():
            for key in ('commission_rate', 'commission_min', 'stamp_tax_sell', 'transfer_fee', 'slippage'):
                if key in model:
                    model[key] *= scale
        config = {'paper': {'name': targets['strategy'][0] if targets.height else 'manual_order_rehearsal',
            'auto_trade': False, 'enabled': not settings['halt'], 'sell_only': settings['sell_only'],
            'initial_cash': state['valuation']['equity']}, 'costs': costs}
        proposed, approved, decision = prepare_manual_orders(state=state, targets=targets,
            inputs=signal_inputs, market=market, next_session=date, config=config, limits=settings['limits'])
        plans.append((scale, config, proposed, approved, decision))
    # Read actual next-session observations after all decisions have been fixed.
    observed = read_manual_replay_inputs(data_root=args.data_root, settings=settings,
        symbols=symbols, as_of=as_of, execution_date=date)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'config.toml').write_bytes(args.config.read_bytes())
    targets.write_csv(args.output/'targets.csv')
    rows = []
    for scale, config, proposed, approved, decision in plans:
        for name, orders in [('unfiltered', proposed), ('risk_filtered', approved)]:
            closing, fills = replay_orders(state=state, orders=orders, execution_date=date,
                inputs=observed, config=config)
            folder = args.output/f'{name}_{scale:g}x'
            folder.mkdir()
            orders.write_csv(folder/'orders.csv')
            fills.trades.write_csv(folder/'fills.csv')
            fills.rejections.write_csv(folder/'rejections.csv')
            (folder/'state.json').write_text(json.dumps(closing, ensure_ascii=False, indent=2), encoding='utf-8')
            nav = closing['nav'][-1]
            rows.append({'cost_scale': scale, 'case': name, 'orders': orders.height,
                'fills': fills.trades.height, 'rejections': fills.rejections.height,
                'equity': nav['equity'], 'cash': nav['cash'],
                'return': nav['equity']/state['valuation']['equity']-1,
                'fees': fills.trades['fee'].sum(),
                'one_way_turnover': fills.trades['notional'].sum()/(2*state['valuation']['equity']),
                'risk_withheld': decision['withheld']})
        (args.output/f'risk_{scale:g}x.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'rehearsal': True, 'as_of': str(as_of), 'execution_date': str(date), 'scenarios': rows}
    (args.output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 固定股数订单风险回放演练', '', f'信号日{as_of}，执行日{date}。', '',
        '|成本|清单|订单/成交|权益|当日收益|费用|单边换手|', '|---|---|---:|---:|---:|---:|---:|']
    for r in rows:
        label = '拦截后' if r['case'] == 'risk_filtered' else '原始拟议'
        lines.append(f"|{r['cost_scale']:g}×|{label}|{r['orders']}/{r['fills']}|{r['equity']:.2f}|"
                     f"{r['return']:.4%}|{r['fees']:.2f}|{r['one_way_turnover']:.3%}|")
    lines += ['', '信号收盘决定固定股数；次日按真实开盘、停牌/涨跌停、T+1和现金约束成交。',
              '这是一日执行链路演练，不能据此判断策略收益。']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
