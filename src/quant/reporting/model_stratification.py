"""Read existing research artifacts and diagnose signal, execution and risk strata."""
import argparse
import json
import tomllib
from pathlib import Path
from typing import cast

import polars as pl

from quant.data.factor_benchmarks import read_etf_total_return
from quant.reporting.stratified_signals import assign_strata, conditional_returns, market_states, signal_diagnostics


def read_parts(folder: Path, filename: str, columns: list[str]) -> pl.DataFrame:
    paths = sorted(folder.glob(f'*/{filename}.parquet'))
    if not paths:
        raise ValueError(f'Missing saved {filename} in {folder}')
    return pl.concat([pl.read_parquet(path).select(columns) for path in paths], how='vertical_relaxed')


def portfolio_diagnostics(*, model: dict, controls: pl.DataFrame, states: pl.DataFrame, benchmark: pl.DataFrame,
                           settings: dict) -> tuple[list[dict], list[dict], list[dict], pl.DataFrame, pl.DataFrame]:
    source, method = Path(model['source']), model['method']
    saved = tomllib.loads((source/'replay/model.toml').read_text(encoding='utf-8'))
    initial = saved['portfolio']['initial_cash']
    targets = pl.read_parquet(source/f'replay/targets_{method}_top50.parquet')
    target_controls = controls.select(pl.col('trade_date').alias('as_of'), 'symbol', 'amount20', 'liquidity', 'size', 'industry')
    target_info = targets.filter(pl.col('weight') > 0).join(target_controls, on=['as_of', 'symbol'], how='left', validate='1:1')
    if target_info.filter(pl.col('liquidity').is_null()).height:
        raise ValueError('Missing original signal-date controls for target exposures')
    signal_dates = controls.select(pl.col('trade_date').alias('signal_date'), 'market_liquidity').unique().sort('signal_date')
    executions, trading_strata = [], []
    returns: list[dict] = []
    capacity, exposure = pl.DataFrame(), pl.DataFrame()
    for multiplier in (.5, 1., 2.):
        folder = source/f'replay/{method}_top50'/f'cost_{multiplier:g}'
        nav = read_parts(folder, 'nav', ['date', 'equity', 'market_value']).sort('date')
        trades = read_parts(folder, 'trades', ['date', 'symbol', 'side', 'quantity', 'notional', 'fee', 'slippage_cost'])
        rejects = read_parts(folder, 'rejections', ['date', 'symbol', 'side', 'reason', 'requested_quantity', 'rejected_quantity'])
        if nav['date'].is_duplicated().any():
            raise ValueError('Duplicate saved NAV dates')
        daily = nav.with_columns(pl.col('equity').shift(1).fill_null(initial).alias('prior_equity'))
        daily = daily.with_columns((pl.col('equity')/pl.col('prior_equity')-1).alias('daily_return'))
        cashflows = trades.group_by('date').agg(pl.col('notional', 'fee', 'slippage_cost').sum())
        daily = daily.join(cashflows, on='date', how='left', validate='1:1').with_columns(
            pl.col('notional', 'fee', 'slippage_cost').fill_null(0.)).with_columns(
            (pl.col('notional')/(2*pl.col('prior_equity'))).alias('one_way_turnover'))
        daily = daily.join(benchmark, on='date', how='left', validate='1:1').join(states, on='date', how='left', validate='1:1').sort('date').join_asof(
            signal_dates.rename({'signal_date': 'liquidity_signal_date'}), left_on='date', right_on='liquidity_signal_date',
            strategy='backward', allow_exact_matches=False).with_columns(
                pl.col('trend', 'volatility', 'market_liquidity').fill_null('unknown'))
        first_active = nav.filter(pl.col('market_value') > 0)['date'].min()
        keys = ['date', 'symbol', 'side']
        attempts = pl.concat([trades.select(keys).with_columns(pl.lit(True).alias('any_fill')),
                              rejects.select(keys).with_columns(pl.lit(False).alias('any_fill'))]).group_by(keys).agg(pl.col('any_fill').any())
        info = {'model': model['name'], 'cost_multiplier': multiplier}
        active = daily.filter(pl.col('date') >= first_active) if first_active else daily.clear()
        executions.append({**info, 'sessions': nav.height, 'first_active': first_active,
            'full_cagr': (nav['equity'][-1]/initial)**(252/nav.height)-1,
            'active_cagr': (nav['equity'][-1]/active['prior_equity'][0])**(252/active.height)-1 if active.height else None,
            'active_sessions': active.height,
            'active_annualized_one_way_turnover': active['one_way_turnover'].sum()*252/active.height if active.height else None,
            'annualized_one_way_turnover': daily['one_way_turnover'].sum()*252/nav.height,
            'order_attempts': attempts.height, 'orders_with_any_fill': attempts['any_fill'].sum(),
            'fraction_orders_with_any_fill': attempts['any_fill'].mean(), 'rejection_rows': rejects.height,
            'rejections_by_reason': json.dumps(rejects.group_by('reason', 'side').agg(pl.len().alias('rows'),
                pl.col('rejected_quantity').sum()).sort('reason', 'side').to_dicts()),
            'total_fees': trades['fee'].sum(), 'total_slippage_cost': trades['slippage_cost'].sum(),
            'sum_fee_and_slippage_fraction': daily.select(((pl.col('fee')+pl.col('slippage_cost'))/pl.col('prior_equity')).sum()).item()})
        for period, start in [('full', nav['date'][0]), ('active', first_active)]:
            if start is None:
                continue
            observed = daily.filter(pl.col('date') >= start)
            for dimension in ('trend', 'volatility', 'market_liquidity'):
                returns.extend({**info, 'period': period, **row} for row in conditional_returns(observed, dimension))
        # Actual executions are attributed to the immediately preceding signal close.
        fill_info = trades.join(states.select('date', pl.col('signal_date').alias('as_of')), on='date', how='left', validate='m:1').join(
            target_controls, on=['as_of', 'symbol'], how='left', validate='m:1').join(
            daily.select('date', 'prior_equity'), on='date', validate='m:1').with_columns(
                (pl.col('notional')/(2*pl.col('prior_equity'))).alias('one_way_turnover'),
                (pl.col('notional')/pl.col('amount20')).alias('participation'))
        if fill_info.height != trades.height:
            raise ValueError('Execution attribution dropped trade rows')
        for dimension in ('liquidity', 'size', 'industry'):
            for (stratum,), group in fill_info.with_columns(pl.col(dimension).fill_null('unknown')).partition_by(dimension, as_dict=True).items():
                trading_strata.append({**info, 'dimension': dimension, 'stratum': stratum,
                    'fills': group.height, 'notional': group['notional'].sum(), 'fees': group['fee'].sum(),
                    'slippage_cost': group['slippage_cost'].sum(), 'one_way_turnover_sum': group['one_way_turnover'].sum(),
                    'known_liquidity_fills': group['participation'].is_finite().sum(),
                    'max_participation': group['participation'].max()})
        if multiplier == 1.:
            info_targets = target_info.join(nav.select(pl.col('date').alias('as_of'), pl.col('equity').alias('signal_equity')),
                on='as_of', how='left', validate='m:1').with_columns(pl.col('signal_equity').fill_null(initial))
            capacity = info_targets.with_columns(
                (pl.col('amount20')*settings['minimum_participation_capacity']/pl.col('weight')).alias('portfolio_capacity'),
                (pl.col('weight')*pl.col('signal_equity')/(pl.col('amount20')*settings['minimum_participation_capacity'])).alias('liquidation_days'))
            capacity = capacity.with_columns((pl.col('portfolio_capacity')*settings['volume_stress_fraction']).alias('stressed_portfolio_capacity'),
                (pl.col('liquidation_days')/settings['volume_stress_fraction']).alias('stressed_liquidation_days'), pl.lit(model['name']).alias('model'))
            frames = []
            for dimension in ('liquidity', 'size', 'industry'):
                group = info_targets.group_by('as_of', dimension).agg(pl.col('weight').sum())
                grid = info_targets.select('as_of').unique().join(info_targets.select(dimension).unique(), how='cross')
                group = grid.join(group, on=['as_of', dimension], how='left', validate='1:1').with_columns(pl.col('weight').fill_null(0.))
                frames.append(group.rename({dimension: 'stratum'}).with_columns(pl.lit(dimension).alias('dimension'), pl.lit(model['name']).alias('model')))
            exposure = pl.concat(frames)
    return executions, returns, trading_strata, capacity, exposure


def write_report(output: Path) -> None:
    def number(value: float | None, pattern: str) -> str:
        return format(value, pattern) if value is not None else '缺失'

    signals = pl.read_csv(output/'signal_strata.csv')
    execution = pl.read_csv(output/'execution_summary.csv')
    capacity = pl.read_parquet(output/'target_capacity.parquet')
    exposure = pl.read_csv(output/'target_exposures.csv')
    rows = ['# 信号、成本及风险分层诊断', '', '只复用保存的预测和回放；原模型拒绝结论保持。', '',
        '## 后期信号（模型至2026-08，候选因子至2025-12）', '',
        '|序列|有效月|平均RankIC|最高十分组月均毛超额|', '|---|---:|---:|---:|']
    for row in signals.filter((pl.col('dimension') == 'all') & (pl.col('period') == 'later')).iter_rows(named=True):
        excess = row['mean_top_gross_excess']
        rows.append(f"|{row['series']}|{row['months']}|{number(row['mean_ic'], '.4f')}|{number(excess, '.2%')}|")
    rows += ['', '毛超额相对该预测截面等权，按信号日划分样本；有效月和可用股票随序列而异。', '',
        '## 已有Top50回放（1×成本）', '',
        '|模型|全期年化|首次持仓后年化|首次持仓后单边年换手|有成交订单比例|手续费/滑点金额|', '|---|---:|---:|---:|---:|---:|']
    for row in execution.filter(pl.col('cost_multiplier') == 1.).iter_rows(named=True):
        rows.append(f"|{row['model']}|{row['full_cagr']:.2%}|{row['active_cagr']:.2%}|"
            f"{row['active_annualized_one_way_turnover']:.2f}|{row['fraction_orders_with_any_fill']:.2%}|"
            f"{row['total_fees']:,.0f}/{row['total_slippage_cost']:,.0f}元|")
    rows += ['', '有成交比例计入部分成交；拒单行数另见execution_summary.csv。首次持仓后的描述统计不替代完整期准入标准。', '',
        '## 目标暴露与成交容量', '', '|模型|最大单行业目标|最小5%成交参与容量|成交量减半容量|', '|---|---:|---:|---:|']
    for model in execution['model'].unique().sort().to_list():
        industry = cast(float, exposure.filter((pl.col('model') == model) & (pl.col('dimension') == 'industry'))['weight'].max())
        sample = capacity.filter(pl.col('model') == model)
        limit = cast(float, sample['portfolio_capacity'].min())
        stressed = cast(float, sample['stressed_portfolio_capacity'].min())
        rows.append(f"|{model}|{industry:.2%}|{limit:,.0f}元|{stressed:,.0f}元|")
    rows += ['', '容量为目标权重下5%历史日均成交额的简单诊断，停牌、涨跌停与冲击成本仍由实际回放及成本压力分别体现。', '',
        '状态归因附510300总回报参考的同期收益及相对贡献；该参考不含交易成本。', '',
        '分层阈值、逐月IC、状态收益贡献、实际交易及目标暴露分别保存在同目录CSV/Parquet中。状态收益贡献按真实持仓日拆分，不拼接成可交易择时收益。']
    (output/'report.md').write_text('\n'.join(rows)+'\n', encoding='utf-8')


def run(*, config: Path, output: Path, data_root: Path) -> dict:
    contents = config.read_bytes()
    specification = tomllib.loads(contents.decode('utf-8'))
    settings = specification['diagnostic']
    if settings['auto_trade'] is not False:
        raise ValueError('Diagnostics must not trade')
    root = Path(settings['statistics'])
    battery = tomllib.loads((root/'battery.toml').read_text(encoding='utf-8'))
    if settings['end'] > battery['run']['as_of']:
        raise ValueError('Diagnostic date exceeds saved inputs')
    labels = pl.concat([pl.read_parquet(p) for p in sorted((root/'inputs').glob('*/monthly_labels.parquet'))], how='vertical_relaxed')
    labels = labels.filter(pl.col('trade_date') <= settings['end'])
    dates = labels['trade_date'].unique().to_list()
    columns = ['symbol', 'trade_date', 'eligible', 'amount20', 'total_market_value', 'industry_l1']
    raw_controls = pl.concat([pl.scan_parquet(p).filter(pl.col('trade_date').is_in(dates)).select(columns).collect()
        for p in sorted((root/'inputs').glob('*/universe.parquet'))], how='vertical_relaxed')
    controls, thresholds = assign_strata(raw_controls, quantiles=settings['quantiles'], minimum_months=settings['minimum_training_months'])
    prices = read_etf_total_return(data_root=data_root, snapshot=battery['data']['etf_total_return_snapshot'], end=settings['end'])
    states = market_states(prices)
    benchmark = prices.select('date', pl.col('unit_nav').pct_change().alias('benchmark_daily_return'))
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(contents)
    thresholds.write_csv(output/'annual_strata_thresholds.csv')
    states.write_parquet(output/'market_states.parquet')
    monthly, summary = [], []
    for model in specification['models']:
        scores = pl.read_parquet(Path(model['source'])/'predictions/monthly_predictions.parquet').select(
            'symbol', 'trade_date', pl.col(model['method']).alias('score'))
        detail, total = signal_diagnostics(scores, controls, labels, states, name=model['name'], end=settings['end'], settings=settings)
        monthly.append(detail)
        summary.append(total)
    for factor in specification['factors']:
        source = Path(factor['source'])
        scores = pl.concat([pl.read_parquet(source/period/'factors'/factor['factor']/'monthly_scores.parquet')
                           for period in ('training', 'validation')]).select('symbol', 'trade_date', pl.col(factor['variant']).alias('score'))
        detail, total = signal_diagnostics(scores, controls, labels, states, name=factor['name'], end=factor['end'], settings=settings)
        monthly.append(detail)
        summary.append(total)
    pl.concat(monthly, how='diagonal_relaxed').write_parquet(output/'monthly_signal_diagnostics.parquet')
    signal_summary = pl.concat(summary, how='diagonal_relaxed')
    signal_summary.write_csv(output/'signal_strata.csv')
    execution, attribution, trading, capacities, exposures = [], [], [], [], []
    for model in specification['models']:
        executed, attributed, strata, capacity, exposure = portfolio_diagnostics(model=model, controls=controls, states=states, benchmark=benchmark, settings=settings)
        execution.extend(executed)
        attribution.extend(attributed)
        trading.extend(strata)
        capacities.append(capacity)
        exposures.append(exposure)
    pl.from_dicts(execution, infer_schema_length=None).write_csv(output/'execution_summary.csv')
    pl.from_dicts(attribution, infer_schema_length=None).write_csv(output/'state_returns.csv')
    pl.from_dicts(trading, infer_schema_length=None).write_csv(output/'trading_strata.csv')
    pl.concat(capacities, how='diagonal_relaxed').write_parquet(output/'target_capacity.parquet')
    pl.concat(exposures, how='diagonal_relaxed').write_csv(output/'target_exposures.csv')
    write_report(output)
    result = {'diagnostic_id': settings['id'], 'models': len(specification['models']), 'factor_series': len(specification['factors']),
        'signal_stratum_rows': signal_summary.height, 'cost_scenarios': len(execution), 'conclusion': 'RESEARCH_ONLY',
        'auto_trade': False, 'source_model_rejections_remain_effective': True}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    print(json.dumps(run(**vars(parser.parse_args()))))


if __name__ == '__main__':
    main()
