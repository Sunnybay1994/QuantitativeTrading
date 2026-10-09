"""Account evidence for frozen PEAD development experiments; never grants admission."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import polars as pl

from quant.reporting.calendar_turnover import calendar_turnover, turnover_passes
from quant.reporting.cycle_stress import path_statistics
from quant.reporting.multifactor_assessment import calendar_years, holding_metrics, underwater_calendar
from quant.reporting.period_metrics import period_metrics, write_period_reports
from quant.research.factor_battery_cost_report import compare_holding_index


def _jsonable(value):
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def _validate_nav(nav: pl.DataFrame) -> None:
    if (nav.is_empty() or nav['date'].null_count() or not nav['date'].is_sorted()
            or nav['date'].n_unique() != nav.height):
        raise ValueError('Account histories require ordered unique daily NAV')
    for name in ('unit_nav', 'equity', 'market_value', 'cash', 'cumulative_fees'):
        values = nav[name]
        if values.null_count() or not values.is_finite().all() or (values < 0).any():
            raise ValueError(f'Account history has invalid {name}')
    if (nav['equity'] <= 0).any() or (nav['unit_nav'] <= 0).any():
        raise ValueError('Account equity and NAV must remain positive')


def window_metrics(nav: pl.DataFrame, trades: pl.DataFrame, *, start: dt.date,
                   end: dt.date, initial_cash: float) -> dict:
    """Keep the preceding actual NAV/equity anchor, including entry and exit costs."""
    _validate_nav(nav)
    part = nav.filter(pl.col('date').is_between(start, end))
    if part.is_empty():
        raise ValueError('Empty account window')
    returns = nav.with_columns(
        (pl.col('unit_nav') / pl.col('unit_nav').shift(1).fill_null(1.) - 1).alias('r')
    ).filter(pl.col('date').is_between(start, end))['r']
    sigma = returns.std() if len(returns) > 1 else 0.
    risk = path_statistics(nav, start=start, end=end)
    daily = nav.select('date', pl.col('equity').shift(1).fill_null(initial_cash).alias('prior_equity'))
    amounts = trades.filter(pl.col('date').is_between(start, end)).group_by('date').agg(pl.col('notional').sum())
    daily = daily.filter(pl.col('date').is_between(start, end)).join(amounts, on='date', how='left')
    turnover = daily.select((pl.col('notional').fill_null(0.) / (2 * pl.col('prior_equity'))).sum()).item()
    earlier = nav.filter(pl.col('date') < start)
    earlier_fees = earlier['cumulative_fees'][-1] if earlier.height else 0.
    return {**risk, 'sharpe_rf0': risk['sharpe'],
            'sharpe_rf2': float((returns.mean() - (1.02 ** (1 / 252) - 1)) / sigma * math.sqrt(252))
            if sigma and sigma > 0 else None,
            'annualized_one_way_turnover_252': turnover * 252 / part.height,
            'mean_invested_fraction': part.select((pl.col('market_value') / pl.col('equity')).mean()).item(),
            'mean_cash_fraction': part.select((pl.col('cash') / pl.col('equity')).mean()).item(),
            'ending_invested_fraction': part['market_value'][-1] / part['equity'][-1],
            'cash_sessions': part.filter(pl.col('market_value') == 0).height,
            'fees': float(part['cumulative_fees'][-1] - earlier_fees),
            'ending_equity': float(part['equity'][-1]), 'trade_sessions': amounts['notional'].len(),
            'trade_count': trades.filter(pl.col('date').is_between(start, end)).height}


def benchmark_comparisons(nav: pl.DataFrame, benchmarks: dict[str, pl.DataFrame], *,
                          start: dt.date, end: dt.date) -> list[dict]:
    """Expose listing-date coverage explicitly; never discard internal missing dates."""
    rows = []
    for name, benchmark in sorted(benchmarks.items()):
        row = {'benchmark': name, 'requested_start': start, 'requested_end': end,
               'benchmark_cost_treatment': 'return_index_without_account_constraints',
               'net_cagr_excess': None}
        try:
            if benchmark.is_empty():
                raise ValueError('Empty benchmark')
            low, high = max(start, benchmark['date'].min()), min(end, benchmark['date'].max())
            if low > high:
                raise ValueError('No common benchmark dates')
            nav_prior = nav.filter(pl.col('date') < low)
            benchmark_prior = benchmark.filter(pl.col('date') < low)
            if (benchmark_prior.height and nav_prior.height
                    and benchmark_prior['date'][-1] != nav_prior['date'][-1]):
                raise ValueError('Benchmark preceding return anchor session differs from account')
            comparison = compare_holding_index(nav, benchmark, start=low, end=high)
            full_grid = nav.filter(pl.col('date').is_between(start, end))['date']
            common_grid = nav.filter(pl.col('date').is_between(low, high))['date']
            full = full_grid.equals(common_grid)
            row.update(**comparison, comparison_status='complete' if full else 'partial_coverage',
                       complete_requested_window=full, omitted_sessions=len(full_grid) - len(common_grid),
                       benchmark_risk=path_statistics(benchmark, start=low, end=high))
        except (ValueError, KeyError) as exc:
            row.update(comparison_status='unavailable', complete_requested_window=False, error=str(exc))
        rows.append(row)
    return rows


def stress_metrics(nav: pl.DataFrame, trades: pl.DataFrame, benchmarks: dict[str, pl.DataFrame], *,
                   windows: list[dict], initial_cash: float) -> list[dict]:
    """Continuous paths; a liquidation day remains exposed even when its close is cash."""
    exposure = nav.with_columns(((pl.col('market_value') > 0)
        | (pl.col('market_value').shift(1).fill_null(0.) > 0)).alias('exposed'))
    rows = []
    for window in windows:
        start, end = window['start'], window['end']
        part = exposure.filter(pl.col('date').is_between(start, end))
        row = {'window': window['name'], 'start': start, 'end': end, 'applicable': False,
               'total_return': None, 'max_drawdown': None, 'benchmark_comparisons': []}
        if start > end:
            raise ValueError('Invalid stress dates')
        covered = (part.height > 0 and start >= nav['date'][0] and end <= nav['date'][-1])
        if not covered:
            row['reason'] = 'outside_account_history'
        elif not part['exposed'].any():
            row['reason'] = 'cash_only_window'
        else:
            row.update(applicable=True, **window_metrics(nav, trades, start=start, end=end, initial_cash=initial_cash),
                       benchmark_comparisons=benchmark_comparisons(nav, benchmarks, start=start, end=end))
        rows.append(row)
    return rows


def _position_summary(positions: pl.DataFrame, nav: pl.DataFrame) -> dict:
    if positions.is_empty():
        if (nav['market_value'] != 0).any():
            raise ValueError('Missing saved positions for invested NAV')
        return {'rows': 0, 'maximum_names': 0, 'maximum_name_weight': None}
    required = {'date', 'symbol', 'quantity', 'market_value'}
    if not required.issubset(positions.columns):
        raise ValueError('Positions require date, symbol, quantity and market_value')
    if positions.select('date', 'symbol').is_duplicated().any():
        raise ValueError('Duplicate date/symbol positions')
    for column in ('quantity', 'market_value'):
        if (positions[column].null_count() or not positions[column].is_finite().all()
                or (positions[column] < 0).any()):
            raise ValueError(f'Invalid saved position {column}')
    if positions.filter(~pl.col('date').is_in(nav['date'].implode())).height:
        raise ValueError('Positions outside account history')
    held = positions.filter(pl.col('quantity') > 0)
    totals = positions.group_by('date').agg(pl.col('market_value').sum().alias('position_market_value'))
    check = nav.select('date', 'market_value').join(totals, on='date', how='left').with_columns(
        pl.col('position_market_value').fill_null(0.))
    if check.filter((pl.col('market_value') - pl.col('position_market_value')).abs() > .01).height:
        raise ValueError('Saved positions do not reconcile with account NAV')
    weights = held.join(nav.select('date', 'equity'), on='date', how='left')
    return {'rows': positions.height,
            'maximum_names': held.group_by('date').len()['len'].max() if held.height else 0,
            'maximum_name_weight': weights.select((pl.col('market_value') / pl.col('equity')).max()).item()}


def _pending_checks(one: dict, two: dict, rules: dict) -> dict:
    """Check only benchmark-independent conditions; do not rebrand unresolved gates."""
    holding = one['holding']
    if holding['active_start'] is None:
        return {'status': 'pending_benchmark_corporate_actions',
                'additional_pending': ['pending_suspension_execution_validation'],
                'checks': {'active_evidence': False}}
    turnover = one['calendar_turnover']['median']
    checks = {
        'sharpe': holding['sharpe'] >= rules['minimum_1x_sharpe'],
        'double_cost_positive': two['holding']['cagr'] is not None
        and two['holding']['cagr'] > rules['minimum_2x_cagr_exclusive'],
        'underwater': one['underwater']['years'] <= rules['maximum_underwater_calendar_years'],
        'active_evidence': calendar_years(holding['active_start'], holding['report_end'])
        > rules['minimum_active_evidence_calendar_years_exclusive'],
        'turnover': True if turnover_passes(turnover, -math.inf) else False if turnover > 8. else None,
        'net_excess': None, 'drawdown': None, 'stress_windows': None, 'annual_outperformance': None,
    }
    return {'status': 'pending_benchmark_corporate_actions', 'checks': checks,
            'additional_pending': ['pending_suspension_execution_validation'],
            'failed_independent_checks': [name for name, value in checks.items() if value is False],
            'pending_checks': [name for name, value in checks.items() if value is None],
            'rules': rules,
            'turnover_rule': 'calendar median <=6; 6<turnover<=8 requires 2x strongest-benchmark excess>=0.05; >8 fails',
            'not_a_final_admission_decision': True}


def _execution_coverage(trades: pl.DataFrame) -> dict:
    column = 'suspension_coverage_complete'
    if column not in trades.columns:
        return {'status': 'unavailable', 'total_fills': trades.height,
                'covered_fills': None, 'unverified_fills': trades.height}
    if trades.schema[column] != pl.Boolean:
        raise ValueError('Suspension coverage must be a Boolean per actual fill')
    covered = trades[column].fill_null(False)
    return {'status': 'complete' if covered.all() else 'partial', 'total_fills': trades.height,
            'covered_fills': covered.sum(), 'unverified_fills': (~covered).sum(),
            'unverified_execution_dates': trades.filter(~covered)['date'].n_unique()}


def _development_decision(paired: list[dict]) -> dict:
    one = next(row for row in paired if row['cost_multiplier'] == 1.)
    two = next(row for row in paired if row['cost_multiplier'] == 2.)
    if any(row['comparison_status'] != 'complete' for row in (one, two)):
        return {'status': 'INSUFFICIENT_ACCOUNT_EVIDENCE', 'not_admission': True}
    values = [row['differences'][key] for row in (one, two) for key in ('cagr', 'sharpe_rf2')]
    if any(value is None for value in values):
        return {'status': 'INSUFFICIENT_ACCOUNT_EVIDENCE', 'not_admission': True}
    checks = {'higher_1x_cagr': values[0] > 0, 'higher_1x_rf2_sharpe': values[1] > 0,
              'no_2x_cagr_reversal': values[2] >= 0, 'no_2x_rf2_sharpe_reversal': values[3] >= 0}
    return {'status': 'PAIRED_GAIN_PENDING_VALIDATION' if all(checks.values()) else 'STOP_FIXED_PORTFOLIO_HYPOTHESIS',
            'checks': checks, 'not_admission': True,
            'interpretation': 'Paired accounts differ in exposure and cash, so their difference is not a pure causal SUE effect.',
            'positive_difference_does_not_imply_absolute_profit_or_risk_gate_pass': True,
            'validation_pending': ['suspension_execution_validation', 'benchmark_corporate_actions',
                                   'original_financial_vintages', 'original_risk_gates', 'future_unseen_outcomes'],
            'no_parameter_rescue': 'Do not change SUE sign, percentile, holding horizon, slot count or hash seed using these outcomes.'}


def build_report(accounts: dict[tuple[str, float], dict[str, pl.DataFrame]],
                 benchmarks: dict[str, pl.DataFrame], *, initial_cash: float,
                 stress_windows: list[dict], admission_rules: dict,
                 treatment: str = 'pead40', control: str = 'all_events',
                 expected_sessions: list[dt.date] | None = None) -> dict:
    """Consume completed frozen account frames at all three costs on one session grid."""
    expected_keys = {(case, cost) for case in (treatment, control) for cost in (.5, 1., 2.)}
    if treatment == control or set(accounts) != expected_keys:
        raise ValueError('Require treatment and control at all three frozen costs')
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError('Invalid initial cash')
    if len({w['name'] for w in stress_windows}) != len(stress_windows):
        raise ValueError('Stress window names must be unique')
    grid = expected_sessions if expected_sessions is not None else accounts[treatment, 1.]['nav']['date'].to_list()
    rows, by_key, periods = [], {}, []
    for (case, cost), frames in sorted(accounts.items()):
        nav, trades, rejections, positions = (frames[name] for name in ('nav', 'trades', 'rejections', 'positions'))
        _validate_nav(nav)
        if nav['date'].to_list() != grid:
            raise ValueError('Account history is incomplete or has a different session grid')
        # The shared holding calculation also checks finite fills and their dates.
        holding = holding_metrics(nav, trades, initial_cash=initial_cash)
        start = holding['active_start']
        full = window_metrics(nav, trades, start=nav['date'][0], end=nav['date'][-1], initial_cash=initial_cash)
        turns, underwater = None, None
        comparisons = []
        if start is not None:
            holding.update(window_metrics(nav, trades, start=start, end=nav['date'][-1], initial_cash=initial_cash))
            turns = calendar_turnover(nav, trades)
            holding['calendar_turnover_median'] = turns['median']
            previous = nav.filter(pl.col('date') < start)
            anchor = previous['unit_nav'][-1] if previous.height else 1.
            underwater = underwater_calendar(nav.filter(pl.col('date') >= start).with_columns(
                (pl.col('unit_nav') / anchor).alias('unit_nav')), start=start)
            comparisons = benchmark_comparisons(nav, benchmarks, start=start, end=nav['date'][-1])
        else:
            holding.update(sharpe_rf0=None, sharpe_rf2=None, calendar_turnover_median=None)
        rejects = (rejections.group_by('reason').len().sort('reason').to_dicts()
                   if rejections.height and 'reason' in rejections.columns else [])
        row = {'case': case, 'cost_multiplier': cost, 'full': full, 'holding': holding,
               'calendar_turnover': turns, 'underwater': underwater,
               'positions': _position_summary(positions, nav), 'rejected_orders': rejections.height,
               'suspension_execution_coverage': _execution_coverage(trades),
               'rejections_by_reason': rejects, 'benchmark_comparisons': comparisons,
               'stress': stress_metrics(nav, trades, benchmarks, windows=stress_windows, initial_cash=initial_cash)}
        rows.append(row)
        by_key[case, cost] = row
        periods.append({'case': case, 'cost_multiplier': cost,
                        'rows': period_metrics(nav, benchmarks, start=start) if start else []})
    paired = []
    for cost in (.5, 1., 2.):
        pair = {'cost_multiplier': cost, 'treatment': treatment, 'control': control,
                'comparison_status': 'unavailable'}
        first = [by_key[case, cost]['holding']['active_start'] for case in (treatment, control)]
        if all(first):
            low, high = max(first), grid[-1]
            measurements = [window_metrics(accounts[case, cost]['nav'], accounts[case, cost]['trades'],
                start=low, end=high, initial_cash=initial_cash) for case in (treatment, control)]
            pair.update(comparison_status='complete', first_date=low, last_date=high,
                        scope='same_continuous_window_from_later_first_holding',
                        treatment_metrics=measurements[0], control_metrics=measurements[1])
            pair['differences'] = {key: measurements[0][key] - measurements[1][key]
                if measurements[0][key] is not None and measurements[1][key] is not None else None
                for key in ('total_return', 'cagr', 'sharpe_rf0', 'sharpe_rf2', 'max_drawdown',
                            'annualized_one_way_turnover_252', 'mean_invested_fraction', 'fees')}
        paired.append(pair)
    gates = [{'case': case, **_pending_checks(by_key[case, 1.], by_key[case, 2.], admission_rules)}
             for case in (treatment, control)]
    return _jsonable({'status': 'complete', 'classification': 'HISTORICAL_DEVELOPMENT_EVIDENCE',
        'auto_trade': False, 'accounts': rows, 'paired': paired, 'periods': periods, 'admission': gates,
        'development_decision': _development_decision(paired),
        'limitations': ['Financial and historical-name vintages are reconstructed; original publication vintages are not proven.',
            'All historical results are development evidence, not a new untouched out-of-sample test.',
            'Equal-weight benchmark delisting consideration remains unresolved: pending_benchmark_corporate_actions.',
            'Historical daily suspension coverage is incomplete: pending_suspension_execution_validation. Positive-volume bars do not prove open-time tradability.',
            'CNY1 minimum commission is the user assumption, not a verified broker tariff.',
            'Daily-bar replay does not demonstrate intraday execution quality or true live trading performance.'],
        'measurement': {'holding_window': 'first actual close holding through report end, including later cash and entry-day return',
            'sharpe': 'daily arithmetic mean excess return divided by sample daily standard deviation times sqrt(252)',
            'risk_free_rates': [0., .02], 'rf2_daily': '1.02**(1/252)-1; fixed sensitivity, not historical rates',
            'turnover': 'shared calendar_year_half_gross_fills_over_mean_daily_equity; median includes labelled partial years',
            'benchmarks': 'same dates and prior NAV anchor; pre-listing dates omitted and explicitly partial coverage',
            'paired': 'PEAD minus all-event account on identical dates; paths preserve actual capital; exposure/cash differences preclude a pure causal SUE interpretation',
            'stress': 'continuous saved path; no rebalance or reset; no current/prior holdings means not applicable'}})


def write_report(output: Path, accounts: dict, benchmarks: dict, **kwargs) -> dict:
    """Write inspectable JSON, compact summary, and shared annual/monthly reports."""
    report = build_report(accounts, benchmarks, **kwargs)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    descriptions = {}
    for period in report['periods']:
        name = f"{period['case']}_cost{period['cost_multiplier']:g}"
        description = (f"{period['case']}，成本{period['cost_multiplier']:g}倍；冻结事件规则，连续10万元账户、5个槽位，最低佣金1元。"
                       '历史开发证据，未构成准入；基准公司行动待核对。')
        write_period_reports(output / name / 'periods', period['rows'], description)
        descriptions[period['case'], period['cost_multiplier']] = name
    def fmt(value, percent=False):
        return 'N/A' if value is None else format(value, '.2%' if percent else '.3f')
    lines = ['# PEAD 连续账户开发检验', '',
             '实际持仓与成本后的账户结果；没有资本重置。该历史已用于开发，不是新增样本外。'
             '等权基准公司行动未解决，准入保留 pending_benchmark_corporate_actions。', '',
             '|账户|成本|首持|持仓期年化|Sharpe rf0/rf2|最大回撤|自然年换手中位数|平均现金|',
             '|---|---:|---|---:|---:|---:|---:|---:|']
    for row in report['accounts']:
        risk = row['holding']
        name = descriptions[row['case'], row['cost_multiplier']]
        lines.append(f"|[{row['case']}]({name}/periods/report.md)|{row['cost_multiplier']:g}|{risk['active_start']}|"
                     f"{fmt(risk['cagr'], True)}|{fmt(risk.get('sharpe_rf0'))}/{fmt(risk.get('sharpe_rf2'))}|"
                     f"{fmt(risk['max_drawdown'], True)}|{fmt(risk.get('calendar_turnover_median'))}|"
                     f"{fmt(risk.get('mean_cash_fraction'), True)}|")
    lines.extend(['', '## 同窗 PEAD − 全事件对照', '',
                  '|成本|日期|年化差|rf2 Sharpe 差|最大回撤差|', '|---|---|---:|---:|---:|'])
    for row in report['paired']:
        if row['comparison_status'] == 'complete':
            delta = row['differences']
            lines.append(f"|{row['cost_multiplier']:g}|{row['first_date']}—{row['last_date']}|"
                         f"{fmt(delta['cagr'], True)}|{fmt(delta['sharpe_rf2'])}|{fmt(delta['max_drawdown'], True)}|")
    lines.extend(['', '收益差为百分点。最大回撤差为正表示回撤更浅；组合差异包含真实资金路径交互。', '',
                  '冻结停止规则：' + report['development_decision']['status'] + '。'
                  '正向配对结果也仍需停牌/开盘执行验证与公司行动基准修复，且不构成纯SUE因果或准入证据。', '',
                  '全历史、首持后现金、逐年换手、连续压力事件、三档成本和基准覆盖详见 summary.json；'
                  '没有把缺失基准、空仓压力窗口或短期状态切片计作通过。', ''])
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    return report
