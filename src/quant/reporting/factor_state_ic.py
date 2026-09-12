"""Describe saved monthly incremental IC by existing observable market states."""
import argparse
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.factor_benchmarks import read_etf_total_return
from quant.reporting.stratified_signals import market_states
from quant.research.factor_battery_statistics import monthly_ic_summary


def summarize_states(monthly: pl.DataFrame, states: pl.DataFrame, *, lag: int,
                     minimum_months_per_year: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    if monthly.is_empty() or monthly.select('factor', 'trade_date').is_duplicated().any():
        raise ValueError('Require nonempty unique factor/month observations')
    # States for next session are based on this signal close, never its future return.
    dated = states.drop_nulls('signal_date').select(
        pl.col('signal_date').alias('trade_date'), 'trend', 'volatility')
    panel = monthly.join(dated, on='trade_date', how='left', validate='m:1').with_columns(
        pl.col('trend', 'volatility').fill_null('unknown'))
    rows = []
    for (factor,), frame in panel.sort('trade_date').partition_by('factor', as_dict=True).items():
        for dimension, choices in [('trend', ['bull', 'bear', 'transition', 'unknown']),
                                   ('volatility', ['low', 'high', 'unknown'])]:
            for state in choices:
                subset = frame.filter(pl.col(dimension) == state)
                for metric in ('raw_rank_ic', 'partial_rank_ic'):
                    stats = monthly_ic_summary(subset['trade_date'].to_list(), subset[metric].to_list(),
                        lag=lag, minimum_months_per_year=minimum_months_per_year)
                    rows.append({'factor': factor, 'dimension': dimension, 'state': state,
                        'metric': metric, 'selected_months': subset.height, **stats,
                        'conclusion': 'RESEARCH_ONLY'})
    return panel, pl.from_dicts(rows, infer_schema_length=None)


def run(*, config: Path, output: Path, data_root: Path = Path('data')) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or output.exists():
        raise ValueError('Require research-only mode and a new output directory')
    source = Path(spec['source'])
    monthly = pl.read_parquet(source/'monthly_incremental_ic.parquet')
    if monthly['trade_date'].max() >= spec['end']:
        raise ValueError('Require a benchmark session after final signal for existing state alignment')
    prices = read_etf_total_return(data_root=data_root, snapshot=spec['benchmark_snapshot'], end=spec['end'])
    states = market_states(prices)
    panel, summary = summarize_states(monthly, states, lag=spec['newey_west_lag'],
        minimum_months_per_year=spec['minimum_months_per_year'])
    output.mkdir(parents=True)
    (output/'config.toml').write_bytes(config.read_bytes())
    states.write_parquet(output/'market_states.parquet')
    panel.write_parquet(output/'monthly_state_ic.parquet')
    summary.write_csv(output/'state_ic_summary.csv')
    result = {'source': str(source), 'factor_months': panel.height, 'factors': panel['factor'].n_unique(),
        'signal_months': panel['trade_date'].n_unique(), 'summary_rows': summary.height,
        'unknown_trend_factor_months': panel.filter(pl.col('trend') == 'unknown').height,
        'unknown_volatility_factor_months': panel.filter(pl.col('volatility') == 'unknown').height,
        'conclusion': 'RESEARCH_ONLY', 'auto_trade': False}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    report = '# Q7：市场状态下的增量IC\n\n'
    report += f"{result['factors']}个因子、{result['signal_months']}个信号月。状态使用信号收盘时已知信息，复用既有趋势与波动定义。\n\n"
    report += '|因子|状态维度|状态|有效月|partial均值|NW t|\n|---|---|---|---:|---:|---:|\n'
    def fmt(value: float | None) -> str:
        return 'NA' if value is None else f'{value:.4f}'
    for row in summary.filter((pl.col('metric') == 'partial_rank_ic') & (pl.col('months') > 0)).sort(
            'factor', 'dimension', 'state').iter_rows(named=True):
        report += f"|{row['factor']}|{row['dimension']}|{row['state']}|{row['months']}|{fmt(row['mean_ic'])}|{fmt(row['newey_west_t'])}|\n"
    report += '\n状态子样本仅作描述；各组相对零的t值不能证明组间差异，亦不用于选因子或改变持仓。完整原始/partial及未知状态见CSV。\n'
    (output/'report.md').write_text(report, encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output)))
