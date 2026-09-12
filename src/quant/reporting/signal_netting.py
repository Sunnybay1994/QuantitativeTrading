"""Rehearse frozen model target netting; output reference needs, never fills."""
import argparse
import json
import math
import tomllib
from pathlib import Path

import polars as pl

from quant.backtest.costs import AShareCostModel
from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data
from quant.portfolio.signal_netting import net_signals


def run(*, config: Path, output: Path, data_root: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or output.exists():
        raise ValueError('Require diagnostic mode and new output')
    source = Path(spec['source'])
    state = json.loads((source/spec['account']).read_text(encoding='utf-8'))['account']
    if state['date'] != str(spec['as_of']):
        raise ValueError('Initial account is not the signal close')
    sessions = [d for d in available_sessions(data_root, spec['execution_date']) if d > spec['as_of']]
    if sessions != [spec['execution_date']]:
        raise ValueError('Execution must be the immediate next session')
    targets = []
    for method in spec['budgets']:
        frame = pl.read_parquet(source/f'targets_{method}_top50.parquet').filter(pl.col('as_of') == spec['as_of'])
        if frame.is_empty() or frame['strategy'].n_unique() != 1:
            raise ValueError(f'Missing unambiguous frozen targets: {method}')
        targets.append(frame.rename({'strategy': 'source_strategy'}).with_columns(pl.lit(method).alias('strategy')))
    target = pl.concat(targets)
    holdings = []
    for symbol, h in state['holdings'].items():
        restricted = sum(r['quantity'] for r in state.get('restricted_shares', []) if r['symbol'] == symbol and r['list_date'] > str(spec['execution_date']))
        holdings.append({'symbol': symbol, 'quantity': h['quantity'], 'settled_quantity': h['quantity']-restricted})
    book = pl.from_dicts(holdings, schema={'symbol': pl.String, 'quantity': pl.Int64, 'settled_quantity': pl.Int64})
    bars = read_stock_data(data_root=data_root, config=Path(spec['refresh_config']), table='bar_1d', start=spec['as_of'], end=spec['as_of'])
    prices = bars.select('symbol', pl.col('close').alias('price'))
    price_map = dict(zip(prices['symbol'], prices['price'], strict=True))
    for symbol, h in state['holdings'].items():
        if symbol not in price_map or not math.isclose(price_map[symbol], h['mark_price'], abs_tol=1e-8, rel_tol=0):
            raise ValueError('Saved holding marks differ from signal-close prices')
    receivables = sum(r['amount'] for r in state['receivables'])
    equity = state['cash'] + receivables + sum(h['quantity']*h['mark_price'] for h in state['holdings'].values())
    if not math.isclose(equity, state['nav'][-1]['equity'], abs_tol=1e-7, rel_tol=0):
        raise ValueError('Initial account does not reconcile')
    merged, sleeves, orders = net_signals(targets=target, budgets=spec['budgets'], holdings=book, prices=prices,
        equity=equity, as_of=spec['as_of'], execution_date=spec['execution_date'], sell_only=spec['sell_only'], lot_size=spec['lot_size'])
    costs = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))['costs']['a_share']
    model = AShareCostModel(**costs)
    def expense(notional: float) -> float:
        if abs(notional) <= 1e-8:
            return 0.
        return model.fee(abs(notional), spec['execution_date'], 'BUY' if notional > 0 else 'SELL') + abs(notional)*model.slippage
    sleeves = sleeves.with_columns(pl.Series('indicative_cost', [expense(x) for x in sleeves['signed_notional']]))
    cash_rows = []
    for (strategy,), sleeve in sleeves.partition_by('strategy', as_dict=True).items():
        cash = state['cash']*spec['budgets'][strategy]
        cash_rows.append({'strategy': strategy, 'virtual_cash_before': cash,
            'virtual_cash_after_reference_requests': cash-sleeve['signed_notional'].sum()-sleeve['indicative_cost'].sum(),
            'indicative_cost': sleeve['indicative_cost'].sum()})
    net_cost = sum(expense(x) for x in merged['net_notional'])
    consolidated_gross_cost = sum(expense(x) for x in merged['gross_buys']) + sum(expense(-x) for x in merged['gross_sells'])
    rounded_cost = sum(expense(x) for x in merged['proposed_signed_notional'])
    cash_after = state['cash']-merged['proposed_signed_notional'].sum()-rounded_cost
    continuous_cash_after = state['cash']-merged['net_notional'].sum()-net_cost
    result = {'auto_trade': False, 'as_of': str(spec['as_of']), 'execution_date': str(spec['execution_date']),
        'models': list(spec['budgets']), 'initial_equity': equity, 'initial_cash': state['cash'], 'receivables_not_spendable': receivables,
        'merged_weight': merged['weight'].sum(), 'target_cash_weight': 1-merged['weight'].sum(),
        'gross_virtual_sleeve_notional': merged['gross_notional'].sum(), 'net_continuous_notional': merged['net_notional'].abs().sum(),
        'cancelled_each_side_notional': merged['cancelled_notional'].sum(),
        'virtual_separate_cost_reference': sleeves['indicative_cost'].sum(), 'same_account_continuous_cost_reference': net_cost,
        'same_side_consolidated_cost_reference': consolidated_gross_cost,
        'same_side_consolidation_cost_reduction': sleeves['indicative_cost'].sum()-consolidated_gross_cost,
        'opposite_cancellation_cost_reduction': consolidated_gross_cost-net_cost,
        'rounded_same_account_cost_reference': rounded_cost, 'rounded_reference_orders': orders.height,
        'rounded_reference_cash_after': cash_after, 'cash_shortfall': max(0., -cash_after),
        'continuous_reference_cash_after': continuous_cash_after,
        'continuous_reference_cash_shortfall': max(0., -continuous_cash_after),
        'virtual_sleeves_with_cash_shortfall': sum(r['virtual_cash_after_reference_requests'] < -1e-7 for r in cash_rows),
        'withheld_quantity': merged['withheld_delta'].abs().sum(), 'conclusion': 'RESEARCH_ONLY'}
    output.mkdir(parents=True)
    (output/'config.toml').write_bytes(config.read_bytes())
    target.write_parquet(output/'source_targets.parquet')
    merged.write_parquet(output/'merged_targets_and_cancellation.parquet')
    sleeves.write_parquet(output/'virtual_sleeve_requests.parquet')
    orders.write_csv(output/'same_account_reference_orders.csv')
    pl.from_dicts(cash_rows).write_csv(output/'virtual_sleeve_cash.csv')
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'report.md').write_text(f"# 同账户模型目标净额诊断\n\n{spec['as_of']} 冻结的等权、IC 与 LGB 三模型按等预算合并，使用同一既有 LGB 账户。\n\n"
        f"虚拟子需求总额 {result['gross_virtual_sleeve_notional']:,.2f} 元；净额 {result['net_continuous_notional']:,.2f} 元；双边各抵消 {result['cancelled_each_side_notional']:,.2f} 元。\n\n"
        f"分别虚拟分账参考成本 {result['virtual_separate_cost_reference']:,.2f} 元，合并连续净额 {net_cost:,.2f} 元，合并后整手参考成本 {rounded_cost:,.2f} 元。\n\n"
        f"连续参考成本变化中，同向订单合并减少 {result['same_side_consolidation_cost_reduction']:,.2f} 元，反向抵消减少 {result['opposite_cancellation_cost_reduction']:,.2f} 元。\n\n"
        f"整手参考订单 {orders.height} 条，全部按参考价完成后的假设现金 {cash_after:,.2f} 元；不足额 {result['cash_shortfall']:,.2f} 元。\n\n"
        f"连续满仓目标未预留费用，合并前有 {result['virtual_sleeves_with_cash_shortfall']} 个虚拟分账缺现金，合并连续需求仍缺 {result['continuous_reference_cash_shortfall']:,.2f} 元；整手后的正现金来自数量取整。\n\n"
        "各子需求按预算分摊同一初始持仓、现金和权益；虚拟分账不是三个真实独立账户，也不共享各自现金。实际同账户只执行净需求。\n\n"
        "这里只生成参考需求，尚未应用执行日停牌/涨跌停/真实可成交价；模型组合并非独立alpha家族，不改变单模型REJECTED结论。\n", encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output, data_root=args.data_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
