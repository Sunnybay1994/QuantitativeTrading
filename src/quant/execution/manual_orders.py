"""Rehearse next-session reference orders from a closed manual account."""
import argparse
import copy
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.stock_paper_inputs import StockPaperInputs
from quant.execution.order_risk import assess_reference_orders, render_report
from quant.execution.stock_paper import ORDER_SCHEMA, reference_orders


def prepare_manual_orders(*, state: dict[str, Any], targets: pl.DataFrame,
                          inputs: StockPaperInputs, market: pl.DataFrame,
                          next_session: dt.date, config: dict[str, Any],
                          limits: dict[str, float]) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    """Keep the input book intact and withhold the whole proposal on a risk issue."""
    if config['paper']['auto_trade'] is not False:
        raise ValueError('Require auto_trade=false')
    valuation = state.get('valuation', {})
    if valuation.get('date') != state['date']:
        raise ValueError('Require a closed manual account for the signal date')
    equity = float(state['cash']) + sum(h['quantity'] * h['mark_price']
        for h in state['holdings'].values()) + sum(r['amount'] for r in state.get('receivables', []))
    if not math.isfinite(equity) or not math.isclose(
            equity, valuation['equity'], rel_tol=0, abs_tol=1e-7):
        raise ValueError('Account differs from its closing valuation')
    as_of = dt.date.fromisoformat(state['date'])
    sessions = sorted(set(inputs.calendar.filter(pl.col('is_open') & (pl.col('date') > as_of))['date']))
    if not sessions or next_session != sessions[0]:
        raise ValueError('Require the immediate next open session')
    if targets['symbol'].is_duplicated().any():
        raise ValueError('Duplicate target symbols')
    for row in targets.iter_rows(named=True):
        if (row['as_of'] != state['date'] or row['execution_date'] != str(next_session)
                or not math.isfinite(row['weight']) or not 0 <= row['weight'] <= 1
                or not row['strategy'] or not row['strategy_version']):
            raise ValueError('Invalid target date, weight or strategy')
    if targets['weight'].sum() > 1 + 1e-10:
        raise ValueError('Target weights exceed one')
    if targets.height and targets.select('strategy', 'strategy_version').unique().height != 1:
        raise ValueError('Require a single target strategy and version')
    # Validate actual holdings and marks before sizing, even when no rebalance is due.
    empty = pl.DataFrame(schema=ORDER_SCHEMA)
    baseline = assess_reference_orders(state=state, orders=empty, market=market,
        next_session=next_session, limits=limits)
    if not math.isclose(equity, baseline['initial_equity'], rel_tol=0, abs_tol=1e-7):
        raise ValueError('Market marks differ from the closed account')
    proposed_state = copy.deepcopy(state)
    proposed_state['pending'] = targets.to_dicts()
    sizing_config = {**config, 'paper': {**config['paper'], 'sell_only': False}}
    proposal = reference_orders(proposed_state, inputs, sizing_config)
    if config['paper'].get('sell_only', False):
        proposal = proposal.filter(pl.col('side') == 'SELL')
    risk = assess_reference_orders(state=state, orders=proposal, market=market,
        next_session=next_session, limits=limits)
    blocked = risk['requires_review']
    result = {'rehearsal': True, 'auto_trade': False, 'risk': risk,
              'halt': not config['paper'].get('enabled', True),
              'sell_only': config['paper'].get('sell_only', False),
              'withheld': blocked, 'proposed_orders': proposal.height,
              'reference_orders': 0 if blocked else proposal.height}
    return proposal, empty if blocked else proposal, result


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
        raise ValueError('This command requires rehearsal mode and auto_trade=false')
    from quant.data.manual_order_inputs import read_manual_order_inputs

    state = json.loads(args.state.read_text(encoding='utf-8'))
    targets = pl.read_csv(args.targets, schema_overrides={
        'as_of': pl.String, 'execution_date': pl.String, 'weight': pl.Float64})
    symbols = sorted(set(state['holdings']) | set(targets['symbol']))
    inputs, market, next_session = read_manual_order_inputs(data_root=args.data_root,
        settings=settings, symbols=symbols, as_of=dt.date.fromisoformat(state['date']))
    costs = tomllib.loads(Path(settings['cost_config']).read_text(encoding='utf-8'))['costs']
    config = {'paper': {'name': targets['strategy'][0] if targets.height else 'manual_order_rehearsal', 'auto_trade': False,
              'enabled': not settings['halt'], 'sell_only': settings['sell_only']}, 'costs': costs}
    proposed, orders, result = prepare_manual_orders(state=state, targets=targets,
        inputs=inputs, market=market, next_session=next_session, config=config, limits=settings['limits'])
    args.output.mkdir(parents=True, exist_ok=False)
    proposed.write_csv(args.output/'proposed_orders.csv')
    orders.write_csv(args.output/'orders.csv')
    targets.write_csv(args.output/'targets.csv')
    (args.output/'config.toml').write_bytes(args.config.read_bytes())
    (args.output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    heading = '# 手工账户次日订单演练\n\n'
    heading += f"拟议{proposed.height}笔；风险拦截后参考清单{orders.height}笔。仅供演练。\n\n"
    (args.output/'report.md').write_text(heading + render_report(result['risk']), encoding='utf-8')
    print(json.dumps({'output': str(args.output), **{k: v for k, v in result.items() if k != 'risk'}}))


if __name__ == '__main__':
    main()
