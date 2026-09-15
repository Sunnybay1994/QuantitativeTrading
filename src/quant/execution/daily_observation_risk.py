"""Attach read-only account diagnostics to a saved daily observation record."""
import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.order_risk_inputs import read_order_risk_inputs
from quant.execution.execution_risk_log import summarize_execution_risk
from quant.execution.order_risk import assess_reference_orders, render_report

DEFAULT_CONFIG = Path('configs/paper/order_risk_diagnostic_v1_20260911.toml')


def _saved_snapshot(snapshot: Path, date: str) -> tuple[dict, pl.DataFrame, dict]:
    state = json.loads((snapshot/'state.json').read_text(encoding='utf-8'))
    if snapshot.name != date or state['date'] != date:
        raise ValueError('Account snapshot does not match requested session')
    orders = pl.read_csv(snapshot/'orders.csv', schema_overrides={
        'as_of': pl.String, 'execution_date': pl.String})
    targets = pl.read_csv(snapshot/'targets.csv', schema_overrides={'as_of': pl.String})
    for frame in (orders, targets):
        if frame.height and (frame['as_of'].null_count() or not (frame['as_of'] == date).all()):
            raise ValueError('Stale order or target date')
        if 'execution_date' in frame.columns and frame.height and (
                frame['execution_date'].null_count() or not (frame['execution_date'] > date).all()):
            raise ValueError('Reference execution date must follow signal date')
    if targets.height and (targets['symbol'].is_duplicated().any()
            or targets['weight'].null_count() or not targets['weight'].is_finite().all()
            or (targets['weight'] < 0).any() or targets['weight'].sum() > 1 + 1e-8):
        raise ValueError('Invalid saved target weights')
    cash = float(state['cash'])
    values = []
    for holding in state['holdings'].values():
        q, p = holding['quantity'], holding['mark_price']
        if type(q) is not int or q < 0 or not math.isfinite(p) or p <= 0:
            raise ValueError('Invalid saved holding')
        values.append(q*p)
    receivable = sum(float(r['amount']) for r in state.get('receivables', []))
    if not math.isfinite(cash) or cash < 0 or not math.isfinite(receivable) or receivable < 0:
        raise ValueError('Invalid saved cash or receivables')
    equity = cash + sum(values) + receivable
    if equity <= 0:
        raise ValueError('Nonpositive saved equity')
    return state, orders, {'cash': cash, 'equity': equity, 'cash_fraction': cash/equity,
        'holding_count': len(values), 'target_count': targets.height, 'order_count': orders.height}


def run(*, record: dict[str, Any], output: Path, data_root: Path,
        config: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Only reads saved account snapshots and local risk inputs; never refreshes accounts."""
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings['auto_trade'] is not False or settings['mode'] != 'diagnostic_only':
        raise ValueError('Read-only diagnostic configuration required')
    if record.get('auto_trade') is not False:
        raise ValueError('Observation must have auto_trade=false')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    date, stages = record.get('as_of'), record['stages']
    source_errors = [name for name in ('model', 'refresh', 'b20', 'b32', 'monthly')
                     if stages.get(name, {}).get('status') != 'complete']
    if stages.get('model', {}).get('result', {}).get('input_errors'):
        source_errors.append('model_input_quality')
    results: list[dict[str, Any]] = []
    groups = [('b20', 6), ('b32', 2)]
    if 'q10' in stages:
        groups.append(('q10', 1))
        if stages['q10'].get('status') != 'complete':
            source_errors.append('q10')
    for group, expected in groups:
        stage = stages.get(group, {})
        accounts = stage.get('result', {}).get('accounts', [])
        if group == 'q10' and stage.get('status') == 'complete':
            value = stage.get('result', {})
            accounts = ([{'account': 'q10_sue_v2', 'output': str(Path(value['output'])/str(date))}]
                if value.get('output') and value.get('as_of') == date else [])
        if stage.get('status') != 'complete' or len(accounts) != expected:
            results.append({'account': group, 'status': 'unavailable',
                            'error': 'Current account stage incomplete or account count wrong'})
            continue
        for number, account in enumerate(accounts):
            item: dict[str, Any] = {'account': account.get('account',
                f"{group}_{account.get('cost_multiplier')}_{account.get('comparison')}"),
                'group': group, 'status': 'failed'}
            try:
                if not isinstance(date, str):
                    raise ValueError('Missing observation session')
                snapshot = Path(account['output'])
                item['snapshot'] = str(snapshot)
                state, orders, saved = _saved_snapshot(snapshot, date)
                item['saved'] = saved
                folder = output/f'{group}_{number}'
                folder.mkdir()
                if group in ('b32', 'q10'):
                    symbols = sorted(set(state['holdings']) | set(orders['symbol']))
                    market, next_session = read_order_risk_inputs(data_root=data_root,
                        refresh_config=Path(settings['refresh_config']), symbols=symbols,
                        as_of=dt.date.fromisoformat(date), lookback=settings['liquidity_sessions'])
                    risk = assess_reference_orders(state=state, orders=orders, market=market,
                        next_session=next_session, limits=settings['limits'])
                    (folder/'risk.json').write_text(json.dumps(risk, ensure_ascii=False, indent=2),
                                                   encoding='utf-8')
                    (folder/'report.md').write_text(render_report(risk), encoding='utf-8')
                    execution = summarize_execution_risk(orders=orders, market=market, risk=risk,
                        liquidity_sessions=settings['liquidity_sessions'],
                        maximum_participation_rate=settings['limits']['participation_rate'])
                    (folder/'execution_risk.json').write_text(
                        json.dumps(execution, ensure_ascii=False, indent=2, allow_nan=False),
                        encoding='utf-8')
                    item.update(scope='stock_reference_order_risk',
                        execution_requires_review=execution['requires_review'],
                        participation_exceeded_symbols=execution['participation_exceeded_symbols'],
                        execution_observed_through=execution['observed_through'],
                        requires_review=risk['requires_review'] or execution['requires_review'],
                        issue_count=len(risk['issues']),
                        projection_valid=risk['projection_valid'])
                else:
                    # Stock industry/concentration limits do not describe cross-asset ETF accounts.
                    item.update(scope='saved_balances_and_dates_only',
                        requires_review=bool(orders.height), issue_count=0,
                        limitation='ETF execution liquidity and order feasibility not assessed')
                item['status'] = 'complete'
                item['output'] = str(folder)
                (folder/'summary.json').write_text(json.dumps(item, ensure_ascii=False, indent=2),
                                                  encoding='utf-8')
            except Exception as exc:
                item['error'] = f'{type(exc).__name__}: {exc}'
            results.append(item)
    complete = not source_errors and len(results) == sum(n for _, n in groups) and all(
        row['status'] == 'complete' for row in results)
    summary = {'as_of': date, 'auto_trade': False, 'mode': 'diagnostic_only',
        'status': 'complete' if complete else 'incomplete', 'source_errors': source_errors,
        'requires_review': not complete or any(r.get('requires_review', True) for r in results),
        'accounts': results, 'output': str(output)}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                     encoding='utf-8')
    lines = ['# 日更观察风险摘要', '', f"日期：{date}；运行状态：{summary['status']}。", '',
        '|账户|检查范围|状态|需核对|', '|---|---|---|---|']
    lines += [f"|{r['account']}|{r.get('scope', '输入不可用')}|{r['status']}|"
              f"{'是' if r.get('requires_review', True) else '否'}；"
              f"{r.get('issue_count', r.get('error', '未知'))}|" for r in results]
    lines += ['', 'ETF检查仅含已保存余额与日期；股票账户包含现有持仓与参考订单风险规则。',
              f"上游异常：{', '.join(source_errors) or '无'}。预警不改变持仓，不发送消息。"]
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = vars(parser.parse_args())
    args['record'] = json.loads((args['record']/'summary.json').read_text(encoding='utf-8'))
    result = run(**args)
    print(json.dumps({'status': result['status'], 'requires_review': result['requires_review'],
                      'output': result['output']}))
    if result['status'] != 'complete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
