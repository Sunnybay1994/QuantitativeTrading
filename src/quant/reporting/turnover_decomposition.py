"""Compare monthly target changes with observed replay turnover, without causal attribution."""
import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.research.model_training_models import buffered_model_targets


def _targets(frame: pl.DataFrame) -> dict[tuple[dt.date, dt.date], dict[str, float]]:
    if frame.select('as_of', 'execution_date', 'symbol').is_duplicated().any():
        raise ValueError('Duplicate target keys')
    result: dict[tuple[dt.date, dt.date], dict[str, float]] = {}
    for row in frame.iter_rows(named=True):
        signal, execution, weight = row['as_of'], row['execution_date'], row['weight']
        if execution <= signal or weight is None or not math.isfinite(weight) or weight < 0:
            raise ValueError('Invalid target date or weight')
        result.setdefault((signal, execution), {})[row['symbol']] = weight
    if any(sum(v.values()) > 1+1e-8 for v in result.values()):
        raise ValueError('Target exposure exceeds one')
    if len({execution for _, execution in result}) != len(result):
        raise ValueError('Multiple signals for one execution date')
    if len({signal for signal, _ in result}) != len(result):
        raise ValueError('Multiple execution dates for one signal')
    return result


def _movement(previous: dict[str, float], target: dict[str, float]) -> tuple[float, float]:
    differences = [target.get(s, 0)-previous.get(s, 0) for s in previous.keys() | target.keys()]
    return sum(max(d, 0) for d in differences), sum(max(-d, 0) for d in differences)


def decompose(*, unbuffered: pl.DataFrame, buffered: pl.DataFrame,
              nav: pl.DataFrame, trades: pl.DataFrame, rejections: pl.DataFrame,
              initial_cash: float, constrained: pl.DataFrame | None = None,
              holdings: dict[dt.date, dict[str, float]] | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Target turnover is half stock-weight L1; actual turnover is gross fills / 2 prior NAV."""
    raw, buffer = _targets(unbuffered), _targets(buffered)
    constraint = _targets(constrained) if constrained is not None else {}
    if set(raw) != set(buffer) or not set(constraint) <= set(buffer):
        raise ValueError('Target stages must align by signal and execution date')
    if (nav.is_empty() or nav['date'].is_duplicated().any()
            or not math.isfinite(initial_cash) or initial_cash <= 0):
        raise ValueError('Duplicate NAV dates or invalid initial cash')
    dates = set(nav['date'])
    if set(trades['date']) - dates or set(rejections['date']) - dates:
        raise ValueError('Execution records outside NAV calendar')
    if {execution for _, execution in buffer} - dates:
        raise ValueError('Target execution date outside NAV calendar')
    ordered_dates = sorted(dates)
    prior_dates = dict(zip(ordered_dates[1:], ordered_dates[:-1]))
    if any(execution in prior_dates and prior_dates[execution] != signal for signal, execution in buffer):
        raise ValueError('Signal date is not the prior recorded NAV session')
    grouped_trades = {key[0]: frame for key, frame in trades.partition_by('date', as_dict=True).items()}
    grouped_rejections = {key[0]: frame for key, frame in rejections.partition_by('date', as_dict=True).items()}
    daily = []
    previous_equity = float(initial_cash)
    signal_days = {execution for _, execution in buffer}
    for row in nav.sort('date').iter_rows(named=True):
        if not math.isfinite(row['equity']) or row['equity'] <= 0:
            raise ValueError('Invalid closing equity')
        if not math.isfinite(previous_equity) or previous_equity <= 0:
            raise ValueError('Invalid prior equity')
        fills = grouped_trades.get(row['date'])
        buys = sells = fees = 0.
        if fills is not None:
            for fill in fills.iter_rows(named=True):
                if (fill['side'] not in ('BUY', 'SELL') or fill['quantity'] <= 0
                        or not math.isfinite(fill['price']) or fill['price'] <= 0
                        or not math.isfinite(fill['fee']) or fill['fee'] < 0):
                    raise ValueError('Invalid fill side or quantity')
                notional = float(fill['notional'])
                if (not math.isfinite(notional) or notional < 0 or
                        not math.isclose(notional, fill['quantity']*fill['price'], rel_tol=1e-10, abs_tol=1e-6)):
                    raise ValueError('Fill notional does not reconcile with quantity and price')
                buys += notional if fill['side'] == 'BUY' else 0
                sells += notional if fill['side'] == 'SELL' else 0
                fees += fill['fee']
        rejects = grouped_rejections.get(row['date'])
        daily.append({'date': row['date'], 'prior_equity': previous_equity,
            'buy_notional': buys, 'sell_notional': sells, 'gross_notional': buys+sells,
            'actual_one_way_turnover': (buys+sells)/(2*previous_equity), 'fees': fees,
            'rejection_count': 0 if rejects is None else rejects.height,
            'target_execution_day': row['date'] in signal_days})
        previous_equity = float(row['equity'])
    observed = {r['date']: r for r in daily}
    previous_raw: dict[str, float] = {}
    previous_buffer: dict[str, float] = {}
    previous_constraint: dict[str, float] | None = {}
    rows = []
    for key in sorted(buffer):
        signal, execution = key
        target = buffer[key]
        raw_buy, raw_sell = _movement(previous_raw, raw[key])
        buffer_buy, buffer_sell = _movement(previous_buffer, target)
        distance = sum(_movement(raw[key], target))/2
        current_constraint = constraint.get(key)
        constrained_turnover = (sum(_movement(previous_constraint, current_constraint))/2
            if previous_constraint is not None and current_constraint is not None else None)
        actual_holdings = (holdings or {}).get(signal)
        needs = _movement(actual_holdings, target) if actual_holdings is not None else None
        fill = observed[execution]
        rejects = grouped_rejections.get(execution)
        reasons: dict[str, int] = {}
        if rejects is not None:
            for reason in rejects['reason']:
                reasons[reason] = reasons.get(reason, 0)+1
        rows.append({'as_of': signal, 'execution_date': execution,
            'unbuffered_target_turnover': (raw_buy+raw_sell)/2,
            'buffered_target_turnover': (buffer_buy+buffer_sell)/2,
            'buffered_target_buy_weight': buffer_buy, 'buffered_target_sell_weight': buffer_sell,
            'same_day_buffer_target_distance': distance,
            'constrained_target_turnover': constrained_turnover,
            'constraint_provided': current_constraint is not None,
            'same_day_constraint_target_distance': sum(_movement(target, current_constraint))/2
                if current_constraint is not None else None,
            'actual_holdings_available': actual_holdings is not None,
            'needed_buy_weight_at_signal_close': needs[0] if needs else None,
            'needed_sell_weight_at_signal_close': needs[1] if needs else None,
            'unattributed_actual_minus_buffer_target': fill['actual_one_way_turnover']-(buffer_buy+buffer_sell)/2,
            'execution_difference_interpretation': 'unattributed_cash_marks_lots_constraints_and_price_drift',
            'rejection_reasons': json.dumps(reasons, sort_keys=True),
            **{k: v for k, v in fill.items() if k not in ('date', 'target_execution_day')}})
        previous_raw, previous_buffer, previous_constraint = raw[key], target, current_constraint
    return pl.from_dicts(rows, infer_schema_length=None), pl.from_dicts(daily)


def run(*, model_root: Path, output: Path, data_root: Path = Path('data'),
        method: str = 'lightgbm', top_k: int = 50, cost: str = '1',
        constrained: Path | None = None) -> dict[str, Any]:
    replay = model_root/'replay'
    model = tomllib.loads((replay/'model.toml').read_text(encoding='utf-8'))
    scores = pl.read_parquet(model_root/'predictions/monthly_predictions.parquet')
    sessions = available_sessions(data_root, model['walk_forward']['test_end']+dt.timedelta(days=40))
    common = dict(method=method, sessions=sessions, start=model['walk_forward']['test_start'],
        end=model['walk_forward']['test_end'], top_k=top_k,
        minimum_symbols=model['models']['minimum_signal_stocks'])
    raw = buffered_model_targets(scores, **common, retention_multiplier=1.)
    buffered = pl.read_parquet(replay/f'targets_{method}_top{top_k}.parquet')
    rebuilt = buffered_model_targets(scores, **common,
        retention_multiplier=model['portfolio']['retention_rank_multiplier'])
    keys = ['as_of', 'execution_date', 'symbol']
    if not buffered.sort(keys).equals(rebuilt.sort(keys)):
        raise ValueError('Saved buffered targets differ from registered model predictions')
    constraint_metadata: dict[str, Any] = {}
    if constrained is not None and (constrained.parent/'summary.json').is_file():
        constraint_metadata = json.loads((constrained.parent/'summary.json').read_text(encoding='utf-8'))
        source = constraint_metadata.get('source')
        if source and Path(source).resolve() != (replay/f'targets_{method}_top{top_k}.parquet').resolve():
            raise ValueError('Constraint targets reference a different model replay source')
    account = replay/f'{method}_top{top_k}'/f'cost_{cost}'
    def table(name: str) -> pl.DataFrame:
        return pl.concat([pl.read_parquet(path) for path in sorted(account.glob(f'*/{name}.parquet'))],
                         how='vertical_relaxed')
    nav, trades, rejections = table('nav'), table('trades'), table('rejections')
    nav_start, nav_end = nav['date'].min(), nav['date'].max()
    if not isinstance(nav_start, dt.date) or not isinstance(nav_end, dt.date):
        raise ValueError('Replay NAV requires date-valued observations')
    expected_dates = [date for date in sessions if nav_start <= date <= nav_end]
    if nav.sort('date')['date'].to_list() != expected_dates:
        raise ValueError('Replay NAV does not cover every trading session')
    holdings: dict[dt.date, dict[str, float]] = {}
    for path in sorted(account.glob('*/account.json')):
        state = json.loads(path.read_text(encoding='utf-8'))['account']
        date = dt.date.fromisoformat(state['date'])
        equity = nav.filter(pl.col('date') == date)['equity'].item()
        holdings[date] = {s: h['quantity']*h['mark_price']/equity for s, h in state['holdings'].items()}
    monthly, daily = decompose(unbuffered=raw, buffered=buffered, nav=nav, trades=trades,
        rejections=rejections, initial_cash=model['portfolio']['initial_cash'], holdings=holdings,
        constrained=pl.read_parquet(constrained) if constrained else None)
    output.mkdir(parents=True, exist_ok=False)
    monthly.write_parquet(output/'signal_decomposition.parquet')
    monthly.write_csv(output/'signal_decomposition.csv')
    daily.write_parquet(output/'daily_actual_turnover.parquet')
    sums = ['unbuffered_target_turnover', 'buffered_target_turnover', 'constrained_target_turnover']
    annual = monthly.with_columns(pl.col('execution_date').dt.year().alias('year')).group_by('year').agg(
        pl.len().alias('signals'), *[pl.col(c).sum().alias(c) for c in sums],
        pl.col('constraint_provided').sum().alias('constrained_signals'),
        pl.col('constrained_target_turnover').count().alias('constrained_turnover_observations'),
        pl.col('actual_holdings_available').sum().alias('holding_snapshots'))
    actual_annual = daily.with_columns(pl.col('date').dt.year().alias('year')).group_by('year').agg(
        pl.col('actual_one_way_turnover').sum(), pl.col('gross_notional').sum(),
        pl.col('fees').sum(), pl.col('rejection_count').sum())
    annual = annual.join(actual_annual, on='year', how='full', coalesce=True).sort('year').with_columns(
        pl.col('signals', 'unbuffered_target_turnover', 'buffered_target_turnover',
               'constrained_signals', 'constrained_turnover_observations', 'holding_snapshots').fill_null(0)
    ).filter((pl.col('signals') > 0) | (pl.col('gross_notional') > 0)).with_columns(
        pl.when((pl.col('constrained_signals') == pl.col('signals'))
                & (pl.col('constrained_turnover_observations') == pl.col('signals'))
                & (pl.col('signals') > 0))
        .then(pl.col('constrained_target_turnover')).otherwise(None).alias('constrained_target_turnover'))
    annual.write_csv(output/'annual.csv')
    daily.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month')).group_by('month').agg(
        pl.col('actual_one_way_turnover').sum(), pl.col('gross_notional').sum(),
        pl.col('fees').sum(), pl.col('rejection_count').sum()).sort('month').write_csv(output/'monthly_actual.csv')
    gross = float(trades['notional'].sum())
    if not math.isclose(float(daily['gross_notional'].sum()), gross, rel_tol=1e-12, abs_tol=1e-6):
        raise ValueError('Actual gross turnover reconciliation failed')
    summary = {'model_root': str(model_root.resolve()), 'model_id': model['research']['id'], 'method': method, 'top_k': top_k, 'cost': cost,
        'signals': monthly.height, 'gross_notional_reconciled': gross,
        'unbuffered_target_turnover': monthly['unbuffered_target_turnover'].sum(),
        'buffered_target_turnover': monthly['buffered_target_turnover'].sum(),
        'actual_one_way_turnover_sum': daily['actual_one_way_turnover'].sum(),
        'constraint_source': str(constrained) if constrained else None,
        'actual_replay_stage': 'buffered_model_targets',
        'constrained_signal_count': monthly['constraint_provided'].sum(),
        'constrained_transition_count': monthly['constrained_target_turnover'].count(),
        'constraint_scenario': constraint_metadata.get('scenario'),
        'constraint_source_verified': bool(constraint_metadata.get('source')),
        'actual_holdings_signal_count': monthly['actual_holdings_available'].sum(),
        'non_target_day_gross_notional': daily.filter(~pl.col('target_execution_day'))['gross_notional'].sum(),
        'rejection_reasons': dict(rejections.group_by('reason').agg(pl.len()).iter_rows()),
        'interpretation': 'Descriptive stage comparison; target differences are not causal fill contributions.'}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 换手来源诊断', '',
        f"模型：{model['research']['id']}；方法：{method} Top{top_k}；成本倍数：{cost}。",
        f"输入目录：{model_root.resolve()}。",
        f"约束来源：{constrained or '未提供'}；覆盖{summary['constrained_signal_count']}/{monthly.height}个日期；场景：{summary['constraint_scenario'] or '未提供'}。", '',
        f"{monthly.height}次信号；未缓冲目标累计单边换手{summary['unbuffered_target_turnover']:.3f}，"
        f"缓冲目标{summary['buffered_target_turnover']:.3f}，实际逐日成交/前日权益{summary['actual_one_way_turnover_sum']:.3f}。", '',
        '|年度|未缓冲目标|缓冲目标|约束目标|实际成交|拒单数|', '|---|---:|---:|---:|---:|---:|']
    for r in annual.to_dicts():
        c = r['constrained_target_turnover']
        lines.append(f"|{r['year']}|{r['unbuffered_target_turnover']:.3f}|{r['buffered_target_turnover']:.3f}|"
                     + (f'{c:.3f}' if c is not None else ('不完整' if r['constrained_signals'] else '未提供'))
                     + f"|{r['actual_one_way_turnover']:.3f}|{r['rejection_count']}|")
    lines += ['', f"已记录拒单原因：{json.dumps(summary['rejection_reasons'], ensure_ascii=False)}。",
        '未记录为拒单的整手取整与现金余量仍可能影响成交，不按拒单数量推算未成交贡献。', f"仅{summary['actual_holdings_signal_count']}个信号日有保存的实际持仓；其余月份的现金、整手与价格漂移贡献不可单独识别。",
        '实际成交对应已保存的缓冲策略回放；约束目标输入只作目标层面对照。',
        '目标换手用各阶段前次目标作基准，跨年连续；实际成交使用当日前一交易日权益，含非调仓日成交。',
        '阶段差异是描述性比较，不能视为缓冲或执行限制的因果贡献。下一步结合拒单及有持仓快照日期决定是否值得预注册降低换手的策略规则。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--method', default='lightgbm')
    parser.add_argument('--top-k', type=int, default=50)
    parser.add_argument('--cost', default='1')
    parser.add_argument('--constrained', type=Path)
    print(json.dumps(run(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == '__main__':
    main()
