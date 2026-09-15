"""Read-only combined holding and reference-order risk diagnostics."""
import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

RULE_LABELS = {
    'board_lot': '股数不满足整手或可卖零股规则',
    'sellable_quantity': '卖出股数超过可卖数量',
    'signal_day_suspension': '信号日停牌，执行日前需重新核对',
    'missing_signal_day_price_band': '缺少信号日官方涨跌停价格',
    'signal_day_price_limit': '信号日触及该方向价格限制',
    'insufficient_cash': '订单序列所需现金不足',
    'cash_buffer': '预计现金低于缓冲比例',
    'missing_industry': '持仓缺少当时行业分类',
    'single_stock_weight': '预计单股持仓比例超限',
    'missing_liquidity': '缺少完整成交额窗口',
    'liquidation_days': '预计变现天数超限',
    'industry_weight': '预计行业持仓比例超限',
    'order_participation': '当日订单总额超过历史成交额参与率上限，需拆日并重新核对',
}


def assess_reference_orders(*, state: dict[str, Any], orders: pl.DataFrame,
                            market: pl.DataFrame, next_session: dt.date,
                            limits: dict[str, float]) -> dict[str, Any]:
    """Value the post-order account without changing orders or the saved account."""
    as_of = dt.date.fromisoformat(state['date'])
    if next_session <= as_of or market['symbol'].is_duplicated().any():
        raise ValueError('Require a next session and unique market rows')
    required = {'cash_buffer', 'single_stock_weight', 'industry_weight',
                'participation_rate', 'maximum_liquidation_days'}
    if set(limits) != required or any(not math.isfinite(v) or v <= 0 for v in limits.values()):
        raise ValueError('Invalid risk limits')
    if any(limits[k] > 1 for k in required - {'maximum_liquidation_days'}):
        raise ValueError('Risk fractions must not exceed one')
    data = {row['symbol']: row for row in market.iter_rows(named=True)}
    holdings = {symbol: row['quantity'] for symbol, row in state['holdings'].items()}
    if any(type(quantity) is not int or quantity < 0 for quantity in holdings.values()):
        raise ValueError('Holdings must contain nonnegative integer share quantities')
    symbols = set(holdings) | set(orders['symbol'])
    if symbols - data.keys():
        raise ValueError('Missing risk market inputs')
    for symbol in symbols:
        row = data[symbol]
        price_date = row.get('price_date', as_of)
        if (row['trade_date'] != as_of or row['close'] is None
                or not math.isfinite(row['close']) or row['close'] <= 0
                or price_date is None or price_date > as_of
                or (price_date != as_of and not row['suspended'])):
            raise ValueError('Risk prices must be finite signal-date marks')
    cash = float(state['cash'])
    if not math.isfinite(cash) or cash < 0 or any(q < 0 for q in holdings.values()):
        raise ValueError('Invalid account cash or holdings')
    receivable = sum(float(row['amount']) for row in state.get('receivables', []))
    if not math.isfinite(receivable) or receivable < 0:
        raise ValueError('Invalid dividend receivables')
    initial_equity = cash + receivable + sum(q * data[s]['close'] for s, q in holdings.items())
    if initial_equity <= 0:
        raise ValueError('Nonpositive account equity')
    available = holdings.copy()
    for row in state.get('restricted_shares', []):
        if row['list_date'] > str(next_session):
            available[row['symbol']] = available.get(row['symbol'], 0) - row['quantity']
    if any(q < 0 for q in available.values()):
        raise ValueError('Restricted shares exceed holdings')
    issues: list[dict[str, Any]] = []
    gross = 0.0
    order_amounts: dict[str, float] = {}
    for row in orders.iter_rows(named=True):
        symbol, side, quantity = row['symbol'], row['side'], row['quantity']
        if (row['as_of'] != str(as_of) or row['execution_date'] != str(next_session)
                or side not in ('BUY', 'SELL') or type(quantity) is not int or quantity <= 0):
            raise ValueError('Invalid reference order date, side or quantity')
        price, fee = row['estimated_fill_price'], row['estimated_fee']
        if not math.isfinite(price) or price <= 0 or not math.isfinite(fee) or fee < 0:
            raise ValueError('Invalid reference fill price or fee')
        lot = data[symbol]['board_lot']
        if lot is None or lot <= 0:
            raise ValueError('Missing board lot')
        if quantity % lot and not (side == 'SELL' and quantity == available.get(symbol, 0)):
            issues.append({'rule': 'board_lot', 'symbol': symbol})
        if side == 'SELL' and quantity > available.get(symbol, 0):
            issues.append({'rule': 'sellable_quantity', 'symbol': symbol})
        if data[symbol]['suspended']:
            issues.append({'rule': 'signal_day_suspension', 'symbol': symbol})
        band = 'up_limit' if side == 'BUY' else 'down_limit'
        value = data[symbol].get(band)
        if value is None or not math.isfinite(value) or value <= 0:
            issues.append({'rule': 'missing_signal_day_price_band', 'symbol': symbol})
        elif (side == 'BUY' and data[symbol]['close'] >= value) or (
                side == 'SELL' and data[symbol]['close'] <= value):
            issues.append({'rule': 'signal_day_price_limit', 'symbol': symbol})
        notional = quantity * price
        gross += notional
        order_amounts[symbol] = order_amounts.get(symbol, 0.0) + notional
        if side == 'SELL':
            available[symbol] = available.get(symbol, 0) - quantity
            holdings[symbol] = holdings.get(symbol, 0) - quantity
            cash += notional - fee
        else:
            holdings[symbol] = holdings.get(symbol, 0) + quantity
            cash -= notional + fee
        if cash < -1e-8:
            issues.append({'rule': 'insufficient_cash', 'symbol': symbol})
    liquidity = []
    for symbol, notional in sorted(order_amounts.items()):
        amount = data[symbol]['average_amount']
        rate = notional / amount if amount is not None and math.isfinite(amount) and amount > 0 else None
        if rate is None:
            issues.append({'rule': 'missing_liquidity', 'symbol': symbol})
        elif rate > limits['participation_rate']:
            issues.append({'rule': 'order_participation', 'symbol': symbol})
        liquidity.append({'symbol': symbol, 'gross_order_amount': notional,
            'average_daily_amount': amount if rate is not None else None,
            'participation_rate': rate, 'maximum_participation_rate': limits['participation_rate'],
            'minimum_execution_days': max(1, math.ceil(rate / limits['participation_rate'])) if rate is not None else None})
    common = {'as_of': str(as_of), 'execution_date': str(next_session), 'auto_trade': False,
              'order_liquidity': liquidity,
              'mode': 'diagnostic_only', 'initial_equity': initial_equity,
              'one_way_turnover': gross / (2 * initial_equity),
              'execution_day_market_status': 'unknown_at_signal_close'}
    if any(row['rule'] in ('sellable_quantity', 'insufficient_cash', 'board_lot') for row in issues):
        if cash < 0:
            issues.append({'rule': 'cash_buffer', 'symbol': None})
        return {**common, 'projection_valid': False, 'projected_equity': None,
                'projected_cash': None, 'cash_fraction': None, 'positions': [],
                'industry_weights': None, 'unknown_industry_weight': None,
                'issues': issues, 'requires_review': True}
    equity = cash + receivable + sum(q * data[s]['close'] for s, q in holdings.items())
    if equity <= 0:
        raise ValueError('Nonpositive projected equity')
    if cash / equity < limits['cash_buffer']:
        issues.append({'rule': 'cash_buffer', 'symbol': None})
    positions: list[dict[str, Any]] = []
    industries: dict[str, float] = {}
    unknown = 0.0
    for symbol, quantity in sorted(holdings.items()):
        if quantity <= 0:
            continue
        value = quantity * data[symbol]['close']
        weight = value / equity
        industry = data[symbol]['industry']
        if industry is None:
            unknown += weight
            issues.append({'rule': 'missing_industry', 'symbol': symbol})
        else:
            industries[industry] = industries.get(industry, 0.0) + weight
        if weight > limits['single_stock_weight']:
            issues.append({'rule': 'single_stock_weight', 'symbol': symbol})
        amount = data[symbol]['average_amount']
        days = value / (limits['participation_rate'] * amount) if (
            amount is not None and math.isfinite(amount) and amount > 0) else None
        if days is None:
            issues.append({'rule': 'missing_liquidity', 'symbol': symbol})
        elif days > limits['maximum_liquidation_days']:
            issues.append({'rule': 'liquidation_days', 'symbol': symbol})
        positions.append({'symbol': symbol, 'quantity': quantity, 'weight': weight,
                          'industry': industry, 'liquidation_days': days,
                          'half_volume_liquidation_days': 2 * days if days is not None else None})
    for industry, weight in industries.items():
        if weight > limits['industry_weight']:
            issues.append({'rule': 'industry_weight', 'industry': industry})
    return {**common, 'projection_valid': True,
            'projected_equity': equity, 'projected_cash': cash, 'cash_fraction': cash / equity,
            'positions': positions,
            'industry_weights': industries, 'unknown_industry_weight': unknown,
            'issues': issues, 'requires_review': bool(issues)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    from quant.data.order_risk_inputs import read_order_risk_inputs

    config = tomllib.loads(args.config.read_text(encoding='utf-8'))
    if config['mode'] != 'diagnostic_only' or config['auto_trade'] is not False:
        raise ValueError('Risk diagnostics require auto_trade=false')
    state = json.loads((args.snapshot/'state.json').read_text(encoding='utf-8'))
    orders = pl.read_csv(args.snapshot/'orders.csv', schema_overrides={
        'as_of': pl.String, 'execution_date': pl.String})
    symbols = sorted(set(state['holdings']) | set(orders['symbol']))
    market, next_session = read_order_risk_inputs(data_root=args.data_root,
        refresh_config=Path(config['refresh_config']), symbols=symbols,
        as_of=dt.date.fromisoformat(state['date']), lookback=config['liquidity_sessions'])
    result = assess_reference_orders(state=state, orders=orders, market=market,
                                    next_session=next_session, limits=config['limits'])
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'config.toml').write_bytes(args.config.read_bytes())
    (args.output/'risk.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output/'report.md').write_text(render_report(result), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'requires_review': result['requires_review'],
                      'positions': len(result['positions']), 'issues': len(result['issues'])}))


def render_report(result: dict[str, Any]) -> str:
    cash = f"{result['cash_fraction']:.2%}" if result['projection_valid'] else '订单不可行，暂停预测'
    lines = ['# 持仓与订单风险诊断', '',
        f"信号日：{result['as_of']}；参考执行日：{result['execution_date']}。",
        f"预计现金比例：{cash}；拟议单边换手：{result['one_way_turnover']:.2%}。",
        f"需核对项目：{len(result['issues'])}；数量及现金可行：{'是' if result['projection_valid'] else '否'}。", '',
        '诊断使用信号日价格和市场状态；执行日停牌及涨跌停需届时重新核对。', '',
        '|证券|预计持仓权重|行业|预计变现天数|成交量减半天数|', '|---|---:|---|---:|---:|']
    for row in result['positions']:
        days = row['liquidation_days']
        lines.append(f"|{row['symbol']}|{row['weight']:.2%}|{row['industry'] or '未知'}|"
                     + (f"{days:.2f}|{2*days:.2f}|" if days is not None else '未知|未知|'))
    lines += ['', '|证券|订单总额|历史成交额参与率|估计最少执行天数|', '|---|---:|---:|---:|']
    for row in result.get('order_liquidity', []):
        rate = row['participation_rate']
        formatted = f'{rate:.2%}' if rate is not None else '未知'
        lines.append(f"|{row['symbol']}|{row['gross_order_amount']:.2f}|{formatted}|{row['minimum_execution_days'] or '未知'}|")
    lines += ['', '执行天数按信号日历史成交额估计；整手、价格及每日成交变化可能要求更多天。',
              '', *[f"- {RULE_LABELS[row['rule']]}：{row.get('symbol') or row.get('industry') or '账户'}"
                   for row in result['issues']]]
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    main()
