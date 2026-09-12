"""Descriptive cross-sectional market/industry/size attribution, with lagged exposures."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import cast

import polars as pl

from quant.data.equal_weight_index import load_return_benchmarks
from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data


def lagged_panel(bars: pl.DataFrame, controls: pl.DataFrame, sessions: list[dt.date]) -> pl.DataFrame:
    if bars.select('symbol', 'trade_date').is_duplicated().any() or controls.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate price or control keys')
    calendar = pl.DataFrame({'trade_date': sessions, 'prior_session': [None, *sessions[:-1]]})
    prices = bars.sort('symbol', 'trade_date').with_columns(
        (pl.col('close')*pl.col('adj_factor')).alias('adjusted_close'))
    prices = prices.with_columns(pl.col('adjusted_close').shift(1).over('symbol').alias('prior_close'),
        pl.col('trade_date').shift(1).over('symbol').alias('prior_price_date'))
    prices = prices.join(calendar, on='trade_date', validate='m:1').with_columns(
        pl.when((pl.col('prior_price_date') == pl.col('prior_session')) & (pl.col('prior_close') > 0)
                & (pl.col('adjusted_close') > 0)).then(pl.col('adjusted_close')/pl.col('prior_close')-1)
        .otherwise(None).alias('security_return'))
    panel = prices.sort('trade_date').join_asof(controls.rename({'trade_date': 'exposure_date'}).sort('exposure_date'),
        left_on='trade_date', right_on='exposure_date', by='symbol', allow_exact_matches=False,
        strategy='backward', check_sortedness=False)
    return panel.with_columns(pl.when(pl.col('total_market_value') > 0).then(pl.col('total_market_value').log()).alias('log_size'))


def fit_day(panel: pl.DataFrame, *, market_return: float, minimum_symbols: int, minimum_industry_symbols: int,
            project_outside_universe: bool = False) -> tuple[pl.DataFrame, dict]:
    """OLS equivalent: full industry intercepts plus industry-demeaned size.

    With equal weights, size is orthogonal to every industry dummy. The common
    return is mean excess return; industry effects sum to zero by stock count.
    This exact reparameterization avoids choosing an arbitrary base industry.
    """
    if panel.select('trade_date', 'symbol').is_duplicated().any():
        raise ValueError('Duplicate regression keys')
    if panel['trade_date'].n_unique() != 1 or panel.filter(pl.col('exposure_date') >= pl.col('trade_date')).height:
        raise ValueError('Require one date with strictly lagged exposure')
    valid = panel.filter(pl.col('eligible').fill_null(False) & pl.col('security_return').is_finite()
        & pl.col('log_size').is_finite() & pl.col('industry_l1').is_not_null())
    if valid.height < minimum_symbols:
        raise ValueError('Insufficient cross-sectional observations')
    valid = valid.with_columns(pl.when(pl.len().over('industry_l1') < minimum_industry_symbols)
        .then(pl.lit('__small_industry_pool__')).otherwise(pl.col('industry_l1')).alias('industry'))
    valid = valid.with_columns((pl.col('log_size')-pl.col('log_size').mean().over('industry')).alias('size_exposure'),
                              (pl.col('security_return')-market_return).alias('excess_return'))
    scale = cast(float | None, valid['size_exposure'].std(ddof=0))
    if scale is None or scale <= 1e-12:
        raise ValueError('Size exposure unidentified within industries')
    valid = valid.with_columns(pl.col('size_exposure')/scale)
    beta = valid.select((pl.col('size_exposure')*pl.col('excess_return')).sum()/pl.col('size_exposure').pow(2).sum()).item()
    common = valid['excess_return'].mean()
    valid = valid.with_columns(pl.lit(market_return).alias('market_component'), pl.lit(common).alias('common_component'),
        (pl.col('excess_return').mean().over('industry')-common).alias('industry_component'),
        (pl.col('size_exposure')*beta).alias('size_component'))
    valid = valid.with_columns((pl.col('security_return')-pl.sum_horizontal('market_component', 'common_component',
        'industry_component', 'size_component')).alias('specific_component'))
    fit = {'date': panel['trade_date'][0], 'observations': valid.height, 'industry_groups': valid['industry'].n_unique(),
           'market_return': market_return, 'common_return': common, 'size_return': beta, 'size_scale': scale,
           'weighted_industry_effect': valid['industry_component'].mean(), 'mean_specific_return': valid['specific_component'].mean(),
           'specific_size_inner_product': valid.select((pl.col('specific_component')*pl.col('size_exposure')).mean()).item()}
    columns = ['trade_date', 'symbol', 'exposure_date', 'security_return', 'industry', 'size_exposure',
        'market_component', 'common_component', 'industry_component', 'size_component', 'specific_component']
    if project_outside_universe:
        # The estimation universe fixes group membership, centers and scale.
        # Holdings never participate in a second fit or change identification.
        mapping = valid.select('industry_l1', 'industry').unique()
        group_parameters = valid.group_by('industry').agg(pl.col('log_size').mean().alias('fitted_size_center'),
            pl.col('industry_component').first())
        projected = panel.filter(pl.col('security_return').is_finite() & pl.col('log_size').is_finite()
            & pl.col('industry_l1').is_not_null()).join(mapping, on='industry_l1', how='inner', validate='m:1').join(
                group_parameters, on='industry', validate='m:1')
        projected = projected.with_columns(((pl.col('log_size')-pl.col('fitted_size_center'))/scale).alias('size_exposure'),
            pl.lit(market_return).alias('market_component'), pl.lit(common).alias('common_component'))
        projected = projected.with_columns((pl.col('size_exposure')*beta).alias('size_component'))
        projected = projected.with_columns((pl.col('security_return')-pl.sum_horizontal('market_component', 'common_component',
            'industry_component', 'size_component')).alias('specific_component'))
        additional = projected.join(valid.select('trade_date', 'symbol'), on=['trade_date', 'symbol'], how='anti')
        valid = pl.concat([valid.select(columns), additional.select(columns)])
    return valid.select(columns), fit


def portfolio_decomposition(holdings: pl.DataFrame, fitted: pl.DataFrame, daily: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    components = ['market_component', 'common_component', 'industry_component', 'size_component', 'specific_component']
    joined = holdings.join(fitted.rename({'trade_date': 'date'}), on=['date', 'symbol'], how='left', validate='1:1')
    joined = joined.with_columns(pl.col('security_return').is_not_null().alias('modeled'))
    joined = joined.with_columns(*[(pl.col(c)*pl.col('prior_weight')).fill_null(0.).alias(c) for c in components])
    joined = joined.with_columns(pl.when(pl.col('modeled')).then(pl.col('contribution')-pl.sum_horizontal(components)).otherwise(0.).alias('execution_difference'),
        pl.when(~pl.col('modeled')).then(pl.col('contribution')).otherwise(0.).alias('unmodeled_contribution'))
    parts = [*components, 'execution_difference', 'unmodeled_contribution']
    result = joined.group_by('date').agg(pl.col(parts).sum(),
        pl.col('prior_weight').filter(~pl.col('modeled')).sum().alias('unmodeled_prior_weight')).join(daily, on='date', validate='1:1')
    result = result.with_columns((pl.col('daily_return')-pl.sum_horizontal(parts)-pl.col('residual_contribution')).alias('reconciliation_error'))
    if cast(float, result['reconciliation_error'].abs().max()) > 1e-10:
        raise ValueError('Portfolio attribution does not reconcile')
    return joined, result.sort('date')


def run(*, config: Path, output: Path, data_root: Path) -> dict:
    if output.exists():
        raise ValueError('Use a new output directory')
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['weighting'] != 'equal_weight_among_lagged_eligible_complete_cases':
        raise ValueError('Unsupported attribution settings')
    objects = spec.get('attribution_objects', 'regression_sample_only')
    if objects not in ('regression_sample_only', 'all_complete_cases_with_fitted_industry'):
        raise ValueError('Unsupported attribution object policy')
    project_outside = objects == 'all_complete_cases_with_fitted_industry'
    source = Path(spec['source'])
    holdings = pl.read_parquet(source/'security_daily.parquet').filter(pl.col('date').is_between(spec['start'], spec['end']))
    daily = pl.read_parquet(source/'daily_reconciliation.parquet').filter(pl.col('date').is_between(spec['start'], spec['end']))
    sessions = list(available_sessions(data_root, spec['end']))
    start_index = next(i for i, day in enumerate(sessions) if day >= spec['start'])
    sessions = sessions[max(0, start_index-1):]
    bars = read_stock_data(data_root=data_root, config=Path(spec['refresh_config']), table='bar_1d', start=sessions[0], end=spec['end'])
    root = Path(spec['statistics'])
    dates = pl.concat([pl.read_parquet(p).select('trade_date').unique() for p in root.glob('inputs/*/monthly_labels.parquet')])['trade_date'].unique().to_list()
    controls = pl.concat([pl.read_parquet(p).filter(pl.col('trade_date').is_in(dates)).select('symbol', 'trade_date',
        'eligible', 'total_market_value', 'industry_l1') for p in root.glob('inputs/*/universe.parquet')], how='vertical_relaxed')
    panel = lagged_panel(bars, controls, sessions).filter(pl.col('trade_date') >= spec['start'])
    benchmark = load_return_benchmarks(config=Path(spec['benchmark_config']), data_root=data_root,
        start=cast(dt.date, daily['date'].min()), end=spec['end'], names=['all_market_equal_weight'])['all_market_equal_weight']
    returns = benchmark.with_columns((pl.col('unit_nav')/pl.col('unit_nav').shift(1).fill_null(1.)-1).alias('market_return'))
    market = dict(zip(returns['date'], returns['market_return'], strict=True))
    frames, fits = [], []
    for (day,), section in panel.partition_by('trade_date', as_dict=True).items():
        frame, fit = fit_day(section, market_return=market[day], minimum_symbols=spec['minimum_symbols'],
                             minimum_industry_symbols=spec['minimum_industry_symbols'], project_outside_universe=project_outside)
        frames.append(frame)
        fits.append(fit)
    fitted = pl.concat(frames)
    joined, result = portfolio_decomposition(holdings, fitted, daily)
    quality = panel.select(pl.col('trade_date').alias('date'), 'symbol',
        pl.when(pl.col('exposure_date').is_null()).then(pl.lit('missing_prior_exposure'))
        .when(~pl.col('eligible').fill_null(False) & pl.lit(not project_outside)).then(pl.lit('outside_lagged_eligible_universe'))
        .when(~pl.col('security_return').is_finite().fill_null(False)).then(pl.lit('missing_adjacent_session_return'))
        .when(~pl.col('log_size').is_finite().fill_null(False)).then(pl.lit('missing_size'))
        .when(pl.col('industry_l1').is_null()).then(pl.lit('missing_industry')).otherwise(pl.lit('modeled')).alias('coverage_reason'))
    joined = joined.join(quality, on=['date', 'symbol'], how='left', validate='1:1').with_columns(
        pl.col('coverage_reason').fill_null('missing_session_bar'))
    joined = joined.with_columns(pl.when(~pl.col('modeled') & (pl.col('coverage_reason') == 'modeled'))
        .then(pl.lit('industry_absent_from_regression_sample')).otherwise(pl.col('coverage_reason')).alias('coverage_reason'))
    coverage = joined.filter(~pl.col('modeled')).group_by('date', 'coverage_reason').agg(
        pl.col('prior_weight', 'contribution').sum(), pl.len().alias('security_rows'))
    if result['date'].to_list() != daily.sort('date')['date'].to_list():
        raise ValueError('Attribution date coverage incomplete')
    parts = ['market_component', 'common_component', 'industry_component', 'size_component', 'specific_component',
             'execution_difference', 'unmodeled_contribution', 'residual_contribution']
    base = result['prior_equity'][0]
    summary = {'start': str(result['date'][0]), 'end': str(result['date'][-1]), 'sessions': result.height,
        'cumulative_return': result['equity'][-1]/base-1,
        'linked_contributions': {c: result.select((pl.col(c)*pl.col('prior_equity')/base).sum()).item() for c in parts},
        'max_reconciliation_error': result['reconciliation_error'].abs().max(),
        'max_unmodeled_prior_weight': result['unmodeled_prior_weight'].max(),
        'minimum_regression_symbols': min(f['observations'] for f in fits), 'conclusion': 'RESEARCH_ONLY'}
    output.mkdir(parents=True)
    (output/'config.toml').write_bytes(config.read_bytes())
    fitted.write_parquet(output/'stock_fitted_returns.parquet')
    pl.from_dicts(fits).write_csv(output/'daily_factor_returns.csv')
    joined.write_parquet(output/'portfolio_security_components.parquet')
    coverage.write_csv(output/'unmodeled_coverage.csv')
    result.write_parquet(output/'portfolio_daily_components.parquet')
    (output/'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    rows = ['# 市场、行业、规模统计归因', '', f"{summary['start']} 至 {summary['end']} 收益 {summary['cumulative_return']:.2%}。", '',
        '|分量|期初资本链接贡献|', '|---|---:|']
    rows += [f'|{c}|{v:.2%}|' for c, v in summary['linked_contributions'].items()]
    rows += ['', '市场基准为全市场等权收益指数；common为回归样本与基准的共同收益差。行业系数按股票数加权和为零，规模为行业内中心化后的标准差单位。', '',
        f"每日回归至少 {summary['minimum_regression_symbols']} 只股票；最大未建模前日权重 {summary['max_unmodeled_prior_weight']:.2%}，原因逐日保存在 unmodeled_coverage.csv。", '',
        'execution_difference含日内调仓、实际费用滑点、分红税与价格口径差；缺收益/暴露的股票保留unmodeled。', '',
        '这是同期描述性统计分解，回归收益不是事前预测；行业内规模识别不等同于因果风险溢价。']
    (output/'report.md').write_text('\n'.join(rows)+'\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output, data_root=args.data_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
