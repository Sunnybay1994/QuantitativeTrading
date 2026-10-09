"""Machine report: paired family extension, unchanged costs and account admission."""
import copy
import json
import math
from pathlib import Path

import polars as pl
import numpy as np

from quant.research.personal_top5 import restore_dates, write_json
from quant.research.personal_top5_report import concat_years, fees
from quant.research.factor_battery_cost_report import compare_nav
from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
from quant.reporting.multifactor_assessment import assess_model, holding_metrics
from quant.reporting.period_metrics import period_metrics, write_period_reports


def paired_checks(control, treatment, admission, aligned):
    """Preregistered superiority is separate from unchanged account eligibility."""
    return {'same_continuous_session_grid': aligned,
        'original_account_gates': all(admission['checks'].values()),
        'one_cost_cagr_gain': treatment[1.]['cagr'] > control[1.]['cagr'],
        'double_cost_cagr_gain': treatment[2.]['cagr'] > control[2.]['cagr'],
        'rf2_sharpe_gain': treatment[1.]['sharpe_rf2'] > control[1.]['sharpe_rf2'],
        'drawdown_not_worse': treatment[1.]['max_drawdown'] >= control[1.]['max_drawdown']}


def measure(nav, trades):
    result = holding_metrics(nav, trades, initial_cash=100000.)
    turnover = calendar_turnover(nav, trades)
    result['annualized_one_way_turnover_252'] = result['annualized_one_way_turnover']
    result['annualized_one_way_turnover'] = turnover['median']
    returns = nav.with_columns((pl.col('unit_nav')/pl.col('unit_nav').shift(1).fill_null(1.)-1).alias('r')).filter(
        pl.col('date') >= result['active_start'])['r']
    result['sharpe_rf2'] = ((returns.mean()-(1.02**(1/252)-1))/returns.std()*math.sqrt(252)
                           if returns.std() else None)
    return result, turnover


def common_window_metrics(nav, start):
    """Include cash and first-day return on the exact common continuous path."""
    history = nav.with_columns((pl.col('unit_nav')/pl.col('unit_nav').shift(1).fill_null(1.)-1).alias('r'))
    frame = history.filter(pl.col('date') >= start)
    before = nav.filter(pl.col('date') < start)
    anchor = before['unit_nav'][-1] if before.height else 1.
    values = frame['unit_nav']/anchor
    returns = frame['r']; deviation = returns.std()
    dd = values.to_numpy()/np.maximum.accumulate(np.r_[1., values.to_numpy()])[1:]-1
    return {'first': str(start), 'last': str(frame['date'][-1]), 'sessions': frame.height,
        'cagr': float(values[-1]**(252/frame.height)-1), 'max_drawdown': float(dd.min()),
        'sharpe_rf2': ((returns.mean()-(1.02**(1/252)-1))/deviation*math.sqrt(252) if deviation else None)}


def report(spec, output):
    inputs = output/'account_inputs'
    settings = restore_dates(json.loads((inputs/'settings.json').read_text()))
    model = restore_dates(json.loads((inputs/'model.json').read_text()))
    windows = restore_dates(json.loads((inputs/'stress.json').read_text()))
    sessions = restore_dates(json.loads((inputs/'sessions.json').read_text()))
    benchmarks = {p.stem.removeprefix('benchmark_'): pl.read_parquet(p) for p in inputs.glob('benchmark_*.parquet')}
    benchmarks['510300_total_return_reference'] = benchmarks.pop('510300')
    old = Path(spec['control_account'])
    control, treatment, navs, comparisons, rows = {}, {}, {}, [], []
    common_control, common_treatment = {}, {}
    aligned = True
    for cost in spec['cost_multipliers']:
        folder = output/f'extended_cost{cost:g}'
        frames = {name: concat_years(folder, name+'.parquet') for name in
                  ('nav', 'trades', 'rejections', 'orders', 'holdings', 'exposure')}
        for name, frame in frames.items(): frame.write_parquet(folder/f'{name}.parquet')
        nav, trades = frames['nav'], frames['trades']
        if nav['date'].to_list() != sessions:
            raise ValueError('Treatment continuous account is incomplete')
        metrics, turns = measure(nav, trades)
        fee = fees(trades, 1, cost, settings); fee.write_parquet(folder/'fee_attribution.parquet')
        actual = trades.group_by('date', 'symbol').agg(pl.when(pl.col('side') == 'BUY').then(pl.col('quantity'))
            .otherwise(-pl.col('quantity')).sum().alias('filled_delta'))
        fills = frames['orders'].join(actual, left_on=['execution_date', 'symbol'], right_on=['date', 'symbol'], how='left').with_columns(
            pl.col('filled_delta').fill_null(0)).with_columns((pl.col('requested_delta')-pl.col('filled_delta')).alias('unfilled_delta'))
        fills.write_parquet(folder/'order_fills.parquet')
        exposure = frames['exposure']
        metrics.update(fees={k: fee[k].sum() for k in ('commission', 'floor_premium', 'transfer', 'stamp', 'slippage_cost')},
            risk={'max_name_weight': exposure['max_name_weight'].max(),
                  'max_industry_weight': exposure['max_industry_weight'].max(),
                  'max_actual_holdings': exposure['holdings'].max()},
            rejected_orders=frames['rejections'].height,
            unfilled_orders=fills.filter(pl.col('unfilled_delta') != 0).height)
        treatment[cost] = metrics; navs[cost] = nav
        write_json(folder/'summary.json', metrics); write_json(folder/'calendar_turnover.json', turns)
        write_period_reports(folder/'periods', period_metrics(nav, benchmarks, start=metrics['active_start']),
            '新增3个已入库候选后重新执行原年度因果筛选；10万元Top5最低佣金1元；已见历史开发证据。')
        control_folder = old/f'top5_fee1_cost{cost:g}'
        old_nav = pl.read_parquet(control_folder/'nav.parquet')
        old_trades = pl.read_parquet(control_folder/'trades.parquet')
        control[cost], _ = measure(old_nav, old_trades)
        same_grid = nav['date'].equals(old_nav['date']); aligned &= same_grid
        if not same_grid:
            raise ValueError('Paired account grids differ; do not compare different capital paths')
        common_start = sessions[0]
        common_control[cost] = common_window_metrics(old_nav, common_start)
        common_treatment[cost] = common_window_metrics(nav, common_start)
        comparisons.append({'cost': cost, 'same_session_grid': same_grid,
            **compare_nav(nav, old_nav), 'rf2_sharpe_difference': common_treatment[cost]['sharpe_rf2']-common_control[cost]['sharpe_rf2'],
            'drawdown_difference': common_treatment[cost]['max_drawdown']-common_control[cost]['max_drawdown'],
            'common_control': common_control[cost], 'common_extended': common_treatment[cost]})
        rows.extend([{'branch': 'control', 'cost': cost, **control[cost]}, {'branch': 'extended', 'cost': cost, **metrics}])
    evaluation = copy.deepcopy(model)
    evaluation['walk_forward'].update(test_start=sessions[0], test_end=sessions[-1])
    admission = assess_model(nav=navs[1.], one=treatment[1.], two=treatment[2.],
                            benchmarks=benchmarks, model=evaluation, windows=windows)
    reference = next(r for r in admission['benchmarks'] if r['benchmark'] == admission['strongest_benchmark'])
    admission['double_cost_excess'] = treatment[2.]['cagr']-reference['cagr']
    admission['checks']['turnover'] = turnover_passes(treatment[1.]['annualized_one_way_turnover'], admission['double_cost_excess'])
    admission['conclusion'] = 'PAPER_CANDIDATE' if all(admission['checks'].values()) else 'REJECTED'
    checks = paired_checks(common_control, common_treatment, admission, aligned)
    result = {'completed': True, 'auto_trade': False, 'classification': 'DEVELOPMENT_EVIDENCE',
        'rows': rows, 'paired_comparisons': comparisons, 'admission': admission, 'paired_checks': checks,
        'paired_hypothesis_supported': all(checks.values()), 'control_replayed': False,
        'control': str(old), 'evidence': spec['evidence'],
        'limitations': ['No unseen holdout; additions were selected using already observed historical data.',
            'Signal-close quantities and daily next-open execution do not validate manual delay or order-book capacity.',
            'Factor admission is not portfolio admission; no live or frozen forward account is changed.']}
    write_json(output/'summary.json', result)
    lines = ['# 新准入候选的个人账户配对检验', '',
        '旧库控制复用已冻结Top5账户；新增3个候选后重新年度因果筛选。10万元、最低佣金1元、三档成本；历史开发证据。', '',
        '|分支|成本|持仓期年化|Sharpe rf0/rf2|最大回撤|年度换手中位数|', '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"|{row['branch']}|{row['cost']:g}|{row['cagr']:.2%}|{row['sharpe']:.3f}/{row['sharpe_rf2']:.3f}|{row['max_drawdown']:.2%}|{row['annualized_one_way_turnover']:.3f}|")
    lines += ['', '原账户门槛：'+admission['conclusion']+'。配对假设支持：'+str(all(checks.values()))+'。', '',
        '不通过项：'+', '.join(k for k, passed in checks.items() if not passed), '',
        '年度选择差异见selection/summary.json，原门槛/压力窗口见summary.json；各成本账户含年/月报告、逐笔委托、未成交、持仓、集中度与费用拆分。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result
