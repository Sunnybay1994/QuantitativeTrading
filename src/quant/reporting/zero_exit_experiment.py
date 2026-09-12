"""Compare frozen monthly and daily complete-exit accounts on shared windows."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_battery_inputs import read_battery_execution
from quant.reporting.lagged_exposure import reconstruct
from quant.reporting.model_window_comparison import window_metrics
from quant.reporting.multifactor_models import report_models
from quant.research.factor_battery_cost_report import load_cost_history


def run(*, config: Path, candidate: Path, output: Path, data_root: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    source = Path(spec['research']['source'])/'replay'
    start, end = spec['evaluation']['start'], spec['evaluation']['end']
    output.mkdir(parents=True, exist_ok=False)
    (output/'experiment.toml').write_bytes(config.read_bytes())
    standard = report_models(run=candidate, output=output/'model', data_root=data_root,
        measurement_config=Path('configs/data/return_benchmarks_q1b_20260912.toml'))
    settings = json.loads((source/'replay_config.json').read_text(encoding='utf-8'))
    events = tomllib.loads((source/'share_exchanges.toml').read_text())['share_exchanges']
    targets = pl.read_parquet(source/'targets_lightgbm_top50.parquet')
    batches = {k[0]: dict(v.select('symbol','weight').iter_rows()) for k,v in
               targets.partition_by('execution_date', as_dict=True).items()}
    baseline_rows = []
    weights = {}
    maximum_residual = 0.
    for year in range(start.year, end.year+1):
        folder = source/f'lightgbm_top50/cost_1/{year}'
        nav = pl.read_parquet(folder/'nav.parquet').sort('date')
        trades = pl.read_parquet(folder/'trades.parquet')
        initial = json.loads((folder.parent/f'{year-1}/account.json').read_text())['account']
        symbols = sorted(set(trades['symbol']) | set(initial['holdings']) | {e['to_symbol'] for e in events})
        inputs = read_battery_execution(data_root=data_root,
            refresh_config=Path(settings['settings']['data']['refresh_config']), snapshot=settings['snapshot'],
            start=nav['date'][0], end=nav['date'][-1], symbols=symbols, include_all_dividends=True)
        dividends = inputs['dividends'].with_columns((pl.col('div_cash') *
            (1-settings['settings']['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
        detail, daily = reconstruct(nav=nav, trades=trades, bars=inputs['bars'], dividends=dividends,
            calendar=inputs['calendar'], initial=initial, share_exchanges=events)
        maximum_residual = max(maximum_residual, float(daily['residual_pnl'].abs().to_numpy().max()))
        details = detail.partition_by('date', as_dict=True)
        for row in nav.iter_rows(named=True):
            day = row['date']
            if day in batches:
                weights = batches[day]
            value = sum(r['close_value'] for r in details[(day,)].iter_rows(named=True)
                        if weights.get(r['symbol'], 0.) == 0)
            baseline_rows.append({'date': day, 'zero_target_weight': value/row['equity']})
        print(json.dumps({'baseline_reconstructed':year}), flush=True)
    baseline = pl.from_dicts(baseline_rows)
    baseline.write_parquet(output/'baseline_zero_target_exposure.parquet')
    rows = []
    for variant in ('lightgbm_top50','lightgbm_top100'):
        monthly = set(pl.read_parquet(source/f'targets_{variant}.parquet')['execution_date'])
        for cost in (.5,1.,2.):
            old, old_trades = load_cost_history(source, variant, cost, end)
            nav, trades = load_cost_history(candidate, variant, cost, end)
            retry_trades = trades.filter(~pl.col('date').is_in(monthly))
            assert retry_trades.filter(pl.col('side') != 'SELL').is_empty()
            if retry_trades.height:
                first_retry = retry_trades['date'].min()
                assert nav.filter(pl.col('date') < first_retry).select(old.columns).equals(old.filter(pl.col('date') < first_retry))
                assert trades.filter(pl.col('date') < first_retry).equals(old_trades.filter(pl.col('date') < first_retry))
            rejects = pl.concat([pl.read_parquet(p) for p in sorted(
                (candidate/variant/f'cost_{cost:g}').glob('*/rejections.parquet'))], how='vertical_relaxed')
            stress = []
            for label in spec['evaluation']['stress']:
                low, high = [dt.date.fromisoformat(d) for d in label.split(' to ')]
                stress.append({'window':label,
                    'baseline':window_metrics(old,old_trades,start=low,end=high,initial_cash=1e6),
                    'candidate':window_metrics(nav,trades,start=low,end=high,initial_cash=1e6)})
            rows.append({'variant':variant,'cost':cost,
                'baseline':window_metrics(old,old_trades,start=start,end=end,initial_cash=1e6),
                'candidate':window_metrics(nav,trades,start=start,end=end,initial_cash=1e6),
                'retry_fills':retry_trades.height,
                'retry_rejections':rejects.filter(~pl.col('date').is_in(monthly)).height,
                'stress':stress,
                'cash_mean':nav.filter(pl.col('date') >= start).select((pl.col('cash')/pl.col('equity')).mean()).item(),
                'baseline_cash_mean':old.filter(pl.col('date') >= start).select((pl.col('cash')/pl.col('equity')).mean()).item()})
    nav, trades = load_cost_history(candidate, 'lightgbm_top50', 1., end)
    baseline_weight_days = baseline['zero_target_weight'].sum()
    candidate_weight_days = nav['zero_target_weight'].sum()
    # Verify every non-monthly fill is a zero-target exit under latest targets.
    weights = {}
    by_day = trades.partition_by('date', as_dict=True)
    for day in nav['date']:
        if day in batches:
            weights = batches[day]
        elif (day,) in by_day:
            assert all(r['side'] == 'SELL' and weights.get(r['symbol'],0.) == 0
                       for r in by_day[(day,)].iter_rows(named=True))
    execution_pass = candidate_weight_days < baseline_weight_days
    primary = [r for r in rows if r['variant'] == 'lightgbm_top50']
    one = next(r for r in primary if r['cost'] == 1.)
    economic_pass = (standard['conclusions']['lightgbm'] == 'PAPER_CANDIDATE'
        and all(r['candidate']['cagr'] >= r['baseline']['cagr'] for r in primary)
        and one['candidate']['max_drawdown'] >= one['baseline']['max_drawdown'])
    result = {'scenarios':rows,'baseline_zero_weight_days':baseline_weight_days,
        'candidate_zero_weight_days':candidate_weight_days,'maximum_baseline_pnl_residual':maximum_residual,
        'execution_pass':execution_pass,'economic_pass':economic_pass,
        'conclusion':'PAPER_CANDIDATE' if execution_pass and economic_pass else
                     'RESEARCH_ONLY' if execution_pass else 'REJECTED'}
    (output/'summary.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    lines = [f"# 零目标退出逐日重试：{result['conclusion']}", '',
        f'{start}—{end}；最新目标为零的持仓权重累计从 {baseline_weight_days:.4f} 降至 '
        f'{candidate_weight_days:.4f} 个仓位日。一个仓位日等于100%账户权益暴露一天。', '',
        '|Top-K|成本|月度年化|重试年化|重试最大回撤|重试年换手|日度卖出成交|日度拒单|现金均值|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        c = row['candidate']
        lines.append(f"|{row['variant'].split('top')[-1]}|{row['cost']:g}×|{row['baseline']['cagr']:.2%}|"
            f"{c['cagr']:.2%}|{c['max_drawdown']:.2%}|{c['annualized_one_way_turnover']:.2f}|"
            f"{row['retry_fills']}|{row['retry_rejections']}|{row['cash_mean']:.2%}|")
    lines += ['', '|Top50 1×窗口|月度收益|重试收益|月度最大回撤|重试最大回撤|', '|---|---:|---:|---:|---:|']
    for row in one['stress']:
        a,b = row['baseline'],row['candidate']
        lines.append(f"|{row['window']}|{a['total_return']:.2%}|{b['total_return']:.2%}|"
            f"{a['max_drawdown']:.2%}|{b['max_drawdown']:.2%}|")
    lines += ['', f'执行改善条件：{execution_pass}；经济及原模型准入条件：{economic_pass}。', '',
        f'基线逐日重建最大损益残差 {maximum_residual:.2e} 元；日度成交均核对为最新零目标的卖出。', '',
        '这是已研究历史上的执行规则实验，后续需要独立前向验证。', '']
    (output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('data'))
    print(json.dumps(run(**vars(parser.parse_args())),default=str))


if __name__ == '__main__':
    main()
