"""Explain the first infeasible construction from saved account evidence, never trade it."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
from unittest.mock import patch

import numpy as np
import polars as pl
from scipy.optimize import LinearConstraint, milp

from quant.backtest.costs import AShareCostModel
from quant.portfolio.integer_construction import construct


def diagnose(output):
    spec = tomllib.loads((output/'config.toml').read_text())
    folder = output/'integer_fixed_1'; base = Path(spec['baseline'])
    sources = [output/'config.toml', folder/'loss_trace.parquet', folder/'nav.parquet',
        folder/'execution_holdings.parquet', base/'inputs/joint_dividends.parquet',
        base/'inputs/joint_instruments.parquet',
        Path('artifacts/portfolio/r4_constrained_q10_20260913_01/signal_controls.parquet'),
        Path('artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01/battery.toml'),
        Path('src/quant/portfolio/integer_construction.py'), Path(__file__)]
    trace = pl.read_parquet(sources[1])
    day = trace.filter(~pl.col('constraints_satisfied'))['as_of'].min()
    rows = trace.filter(pl.col('as_of') == day)
    holdings = {r['symbol']:dict(quantity=r['current_quantity'],mark_price=r['valuation_mark'])
                for r in rows.to_dicts() if r['current_quantity'] > 0}
    if not rows.filter(pl.col('current_quantity') > 0)['price_complete'].all():
        raise ValueError('Do not reconstruct missing-price failure as complete')
    # This minimal reconstruction only applies before any corporate action or
    # intervening stock trade. Refuse instead of inventing restricted-share state.
    dividends = pl.read_parquet(sources[4])
    if dividends.filter(pl.col('symbol').is_in(sorted(holdings)) &
            pl.col('ex_date').is_between(spec['start'], day)).height:
        raise ValueError('First-failure reconstruction requires no prior stock action')
    initial = pl.read_parquet(sources[3]).filter(pl.col('date') == spec['start'])
    initial_q = dict(initial.filter(pl.col('symbol').is_in(sorted(holdings))).select('symbol','quantity').iter_rows())
    if initial_q != {s:h['quantity'] for s,h in holdings.items()}:
        raise ValueError('Intervening stock quantities changed')
    nav = pl.read_parquet(sources[2]).filter(pl.col('date') == day).row(0,named=True)
    if nav['receivable'] != 0: raise ValueError('Need explicit receivable state')
    state = dict(date=str(day),nav=[nav],holdings=holdings)
    raw = rows.select('as_of','symbol',pl.col('raw_weight').alias('weight'))
    budgeted = rows.select('as_of','symbol',pl.col('budget_weight').alias('weight'))
    market = pl.read_parquet(sources[6]).filter(pl.col('as_of') == day)
    inst = {r['symbol']:r for r in pl.read_parquet(sources[5]).to_dicts()}
    fees = tomllib.loads(sources[7].read_text())['costs']['a_share']
    captured = []
    def capture(c, **kw):
        captured.append((c,kw));return milp(c,**kw)
    with patch('quant.portfolio.integer_construction.milp',capture):
        _,_,_,info=construct(raw=raw,budgeted=budgeted,state=state,market=market,
            prices={r['symbol']:r['signal_price'] for r in rows.to_dicts() if r['signal_price'] is not None},
            instruments=inst,scores={r['symbol']:r['score'] for r in rows.to_dicts() if r['score'] is not None},
            costs=AShareCostModel(**fees),spec=spec)
    if info['status'] != 'primary_solver_2' or len(captured) != 1:
        raise ValueError('Failed to reproduce recorded primary infeasibility')
    _,kw=captured[0];linear=kw['constraints'];index=len(rows)+2
    vector=linear.A.toarray()[index];budget=linear.ub[index]
    # Diagnostic ONLY: same integer choices and all other constraints; calculate
    # the least turnover required without the aggregate turnover ceiling.
    keep=np.arange(linear.A.shape[0])!=index
    check=milp(vector/nav['equity'],integrality=kw['integrality'],bounds=kw['bounds'],
        constraints=LinearConstraint(linear.A[keep],linear.lb[keep],linear.ub[keep]),
        options={'time_limit':30.,'mip_rel_gap':0.})
    result=dict(as_of=str(day),reproduced_status=info['status'],auto_trade=False,
        diagnostic_only=True,unchanged_integer_choices=True,unchanged_other_constraints=True,
        solver_status=int(check.status),permitted_one_way_turnover=budget,
        minimum_required_one_way_turnover=float(vector@check.x) if check.success else None,
        minimum_required_fraction=float(vector@check.x)/nav['equity'] if check.success else None,
        planned_exit_fraction=float((rows.filter(pl.col('raw_weight')==0)['current_quantity']*
            rows.filter(pl.col('raw_weight')==0)['valuation_mark']).sum()/nav['equity']),
        conclusion='turnover_ceiling_incompatible_with_other_frozen_constraints' if check.success and vector@check.x>budget+.01
            else 'other_joint_constraints_infeasible_or_not_proven',
        execution='diagnostic solution discarded; no NAV replay or relaxed-rule strategy created',
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (output/'first_infeasibility.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    marker='\n\n## 首次不可行的复现诊断\n\n'
    report_path=output/'report.md'
    if report_path.exists():
        text=report_path.read_text(encoding='utf-8').split(marker)[0]
        detail=(f"{day}：最低所需单边换手 {result['minimum_required_one_way_turnover']:.2f} 元"
                f"（净值 {result['minimum_required_fraction']:.4%}），冻结上限 {budget:.2f} 元。"
                if check.success else '其余约束也可能联合不可行，尚未获得最小换手证据。')
        report_path.write_text(text+marker+detail+
            '诊断仅移除总换手上限以求理论最低需求，保留相同整数选项及其余限制；解未用于成交或收益回放。'
            '完整来源和求解状态见 first_infeasibility.json。\n\n'
            '本规则大部分调仓不可行，费用下降主要来自冻结持仓，不能算费用感知构建成功。'
            '当前分支停止，不提高换手预算或扫描持股数来挽救；这不证明所有整手构建规则都无效。\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    diagnose(p.parse_args().output)
