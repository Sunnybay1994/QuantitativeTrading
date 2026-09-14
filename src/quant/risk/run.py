"""Produce daily risk estimates and saved-fill monthly attribution in one run."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import cast

import numpy as np
import polars as pl

from quant.data.factor_battery_inputs import read_battery_execution
from quant.data.risk_model_inputs import load_risk_year
from quant.reporting.lagged_exposure import reconstruct
from quant.reporting.model_stratification import read_parts
from quant.risk.model import EWMARisk, STYLES, design, fit_wls, prepare_exposures, tracking_error


def write_stress_window(output: Path) -> pl.DataFrame:
    """Aggregate the already registered B93 January shock (through 8 February)."""
    daily = pl.read_parquet(output/'daily_attribution.parquet').filter(
        pl.col('date').is_between(dt.date(2024, 1, 1), dt.date(2024, 2, 8))).sort('date')
    components = [c for c in daily.columns if c not in
                  ['date', 'portfolio', 'prior_equity', 'equity', 'daily_return']]
    daily = daily.with_columns(pl.col('prior_equity').first().over('portfolio').alias('window_base'))
    result = daily.group_by('portfolio').agg(
        pl.col('date').min().alias('start'), pl.col('date').max().alias('end'),
        *((pl.col(c)*pl.col('prior_equity')/pl.col('window_base')).sum().alias(c) for c in components),
        (pl.col('equity').last()/pl.col('window_base').first()-1).alias('return'))
    result = result.with_columns((pl.col('return')-pl.sum_horizontal(components)).alias('reconciliation_error'))
    if cast(float, result['reconciliation_error'].abs().max()) > 1e-10:
        raise ValueError('Stress-window attribution does not reconcile')
    result.write_csv(output/'stress_attribution_2024_01.csv')
    marker = '\n## B93 2024-01压力窗（2024-01-01至2024-02-08）\n'
    report = (output/'report.md').read_text(encoding='utf-8').split(marker)[0]
    lines = [marker, '|组合|收益|规模|其他九风格|市场及行业合计|特质|执行及未建模|',
             '|---|---:|---:|---:|---:|---:|---:|']
    for row in result.sort('portfolio').iter_rows(named=True):
        other = sum(row[c] for c in STYLES if c != 'size')
        industry = sum(row[c] for c in components if c.startswith('industry:'))
        residual = row['unmodeled']+row['execution_cost_and_cash_residual']
        lines.append(f"|{row['portfolio']}|{row['return']:.2%}|{row['size']:.2%}|{other:.2%}|{industry:.2%}|{row['specific']:.2%}|{residual:.2%}|")
    (output/'report.md').write_text(report+'\n'.join(lines)+'\n', encoding='utf-8')
    return result


def saved_holdings(spec: dict, *, start: dt.date, end: dt.date, data_root: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    folder = Path(spec['folder'])
    root = folder.parent.parent
    nav = read_parts(folder, 'nav', ['date', 'equity', 'market_value', 'cash', 'delisted_symbols']).filter(
        pl.col('date').is_between(start, end)).sort('date')
    trades = read_parts(folder, 'trades', ['date', 'symbol', 'side', 'quantity', 'price', 'notional', 'fee']).filter(
        pl.col('date').is_between(start, end))
    config = Path(spec['replay_config'])
    if config.exists():
        replay = json.loads(config.read_text(encoding='utf-8'))
        settings, snapshot = replay['settings'], replay['snapshot']
        initial = json.loads((folder/f'{start.year-1}/account.json').read_text(encoding='utf-8'))['account']
    else:
        settings = tomllib.loads((root/'battery.toml').read_text(encoding='utf-8'))
        snapshot = json.loads((root/'summary.json').read_text(encoding='utf-8'))['execution_snapshot']
        previous = pl.read_parquet(folder/f'{start.year-1}/nav.parquet').sort('date').tail(1).row(0, named=True)
        if previous['market_value'] != 0:
            raise ValueError('Legacy reconstruction requires observed cash-only initial account')
        initial = {'date': str(previous['date']), 'cash': previous['cash'], 'receivables': [],
                   'restricted_shares': [], 'cumulative_fees': 0., 'pending': [], 'holdings': {}}
    exchanges = [{**e, **{k: dt.date.fromisoformat(e[k]) for k in
                  ('announcement_date', 'record_date', 'effective_date', 'tradable_date')}}
                 for e in settings.get('share_exchanges', [])]
    symbols = sorted(set(trades['symbol'].to_list()) | {e['to_symbol'] for e in exchanges})
    inputs = read_battery_execution(data_root=data_root, refresh_config=Path(settings['data']['refresh_config']),
        snapshot=snapshot, start=start, end=end, symbols=symbols, include_all_dividends=True)
    dividends = inputs['dividends'].with_columns(
        (pl.col('div_cash')*(1-settings['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
    detail, daily = reconstruct(nav=nav, trades=trades, bars=inputs['bars'], dividends=dividends,
                               calendar=inputs['calendar'], initial=initial, share_exchanges=exchanges)
    return detail, daily


def run(config: Path, output: Path, data_root: Path, holdings_source: Path | None = None) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['styles'] != STYLES:
        raise ValueError('Unsupported risk model contract')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    start, end = spec['start'], spec['end']
    holdings, accounts = {}, {}
    for portfolio in spec['portfolios']:
        name = portfolio['name']
        if holdings_source is None:
            detail, daily = saved_holdings(portfolio, start=start, end=end, data_root=data_root)
        else:
            if (holdings_source/'config.toml').read_bytes() != config.read_bytes():
                raise ValueError('Cached holdings require the same portfolio and date configuration')
            detail = pl.read_parquet(holdings_source/f'{name}_security_daily.parquet')
            daily = pl.read_parquet(holdings_source/f'{name}_account_daily.parquet')
        detail.write_parquet(output/f'{name}_security_daily.parquet')
        daily.write_parquet(output/f'{name}_account_daily.parquet')
        holdings[name] = detail.partition_by('date', as_dict=True)
        accounts[name] = {r['date']: r for r in daily.iter_rows(named=True)}
        print(f'reconstructed {name}: {detail.height} security-days', flush=True)
    # Industry dimension fixed from historical versions, with no coefficient fit using future data.
    # Enumerating category labels does not estimate returns or statistics from future dates.
    industries = ['UNKNOWN']
    for year in range(spec['warmup_start'].year, end.year+1):
        path = Path(spec['statistics'])/f'inputs/{year}/universe.parquet'
        industries += pl.scan_parquet(path).select('industry_l1').unique().collect()['industry_l1'].drop_nulls().to_list()
    industries = sorted(set(industries))
    names = STYLES+[f'industry:{name}' for name in industries]
    state = EWMARisk(len(names), spec['covariance_half_life'], spec['specific_half_life'],
                     spec['minimum_history'], spec['covariance_diagonal_shrinkage'])
    previous = None
    exposures, contributions, factors, coverage = [], [], [], []
    covariance_rows: list[dict] = []
    for year in range(spec['warmup_start'].year, end.year+1):
        print(f'loading risk descriptors {year}', flush=True)
        panel = load_risk_year(data_root=data_root, statistics=Path(spec['statistics']), year=year)
        sections = panel.filter(pl.col('trade_date') <= end).sort('trade_date', 'symbol').partition_by('trade_date')
        for current in sections:
            day = current['trade_date'][0]
            if previous is None:
                previous = current
                continue
            source = previous['trade_date'][0]
            lagged = prepare_exposures(previous)
            joined = lagged.join(current.select('symbol', pl.col('adjusted_close').alias('next_close')),
                                 on='symbol', how='inner', validate='1:1').with_columns(
                (pl.col('next_close')/pl.col('adjusted_close')-1).alias('security_return'))
            valid = joined.filter(pl.col('security_return').is_finite() & (pl.col('total_market_value') > 0))
            fit = valid.filter(pl.col('eligible'))
            x_fit = design(fit, industries)
            beta, residual = fit_wls(x_fit, fit['security_return'].to_numpy(), fit['total_market_value'].to_numpy())
            realized_specific = valid['security_return'].to_numpy()-design(valid, industries)@beta
            residual_by_symbol = dict(zip(valid['symbol'].to_list(), realized_specific.tolist(), strict=True))
            # The forecast universe is fixed BEFORE observing today's return/quote availability.
            forecast = lagged.filter(pl.col('total_market_value') > 0)
            x = design(forecast, industries)
            symbols = forecast['symbol'].to_list()
            indices = {s: n for n, s in enumerate(symbols)}
            benchmark = forecast['eligible'].to_numpy().astype(float)
            benchmark /= benchmark.sum()
            state.begin_industry_regime(set(forecast.filter(pl.col('eligible'))['industry_l1'].to_list()))
            covariance = state.covariance()
            specific, proxy_count = state.prior_specific(symbols)
            if day >= start:
                factors.append({'date': day, 'exposure_date': source, 'observations': fit.height,
                                **dict(zip(names, beta.tolist(), strict=True))})
                coverage.append({'date': day, 'regression_symbols': fit.height,
                    'imputed_style_cells': int(fit['imputed_styles'].sum()),
                    'imputed_style_fraction': float(fit['imputed_styles'].sum())/(fit.height*10),
                    'unknown_industry_symbols': fit.filter(pl.col('industry_l1') == 'UNKNOWN').height,
                    'specific_prior_proxy_symbols': proxy_count})
                for name, daily_map in accounts.items():
                    account = daily_map.get(day)
                    if account is None:
                        raise ValueError(f'Missing account session {name} {day}')
                    weight = np.zeros(len(symbols))
                    attribution_weight = np.zeros(len(symbols))
                    missing_weight, missing_contribution = 0., 0.
                    for row in holdings[name].get((day,), pl.DataFrame()).iter_rows(named=True):
                        index = indices.get(row['symbol'])
                        if index is None:
                            missing_weight += row['prior_weight']
                            missing_contribution += row['contribution']
                        else:
                            weight[index] = row['prior_weight']
                            if row['symbol'] in residual_by_symbol:
                                attribution_weight[index] = row['prior_weight']
                            else:
                                missing_contribution += row['contribution']
                    exposure = weight@x
                    te = tracking_error(weight-benchmark, x, covariance, specific) if covariance is not None else None
                    # Missing held exposure means the whole-portfolio TE is not identifiable.
                    if missing_weight > 1e-10:
                        te = None
                    exposures.append({'date': day, 'portfolio': name, 'exposure_date': source,
                        'risk_information_through': state.last_date, 'ex_ante_tracking_error': te,
                        'invested_prior_weight': float(weight.sum()+missing_weight),
                        'unmodeled_prior_weight': missing_weight, **dict(zip(names, exposure.tolist(), strict=True))})
                    parts = dict(zip(names, ((attribution_weight@x)*beta).tolist(), strict=True))
                    parts['specific'] = float(sum(attribution_weight[i]*residual_by_symbol[s]
                        for i, s in enumerate(symbols) if s in residual_by_symbol))
                    parts['unmodeled'] = missing_contribution
                    parts['execution_cost_and_cash_residual'] = account['daily_return']-sum(parts.values())
                    contributions.append({'date': day, 'portfolio': name, 'prior_equity': account['prior_equity'],
                        'equity': account['equity'], 'daily_return': account['daily_return'], **parts})
                if day.month != (day+dt.timedelta(days=1)).month or current is sections[-1]:
                    if covariance is not None:
                        covariance_rows.extend({'date': day, 'information_through': state.last_date,
                            'factor_i': names[i], 'factor_j': names[j], 'daily_covariance': float(covariance[i, j])}
                            for i in range(len(names)) for j in range(i+1))
            # Forecasts above consume history only; today's fit is learned afterwards.
            state.update(day, beta, residual_by_symbol)
            previous = current
        print(f'completed risk {year}: {len(factors)} modeled days', flush=True)
    daily_exposure = pl.from_dicts(exposures, infer_schema_length=None)
    daily_contribution = pl.from_dicts(contributions)
    daily_exposure.write_parquet(output/'daily_exposures.parquet')
    daily_contribution.write_parquet(output/'daily_attribution.parquet')
    pl.from_dicts(factors).write_parquet(output/'daily_factor_returns.parquet')
    pl.from_dicts(coverage).write_csv(output/'coverage.csv')
    pl.from_dicts(covariance_rows).write_parquet(output/'factor_covariance.parquet')
    pl.DataFrame({'symbol': list(state.specific), 'daily_specific_variance': [v[0] for v in state.specific.values()],
                  'observations': [v[1] for v in state.specific.values()]}).write_parquet(output/'specific_variance.parquet')
    monthly = daily_exposure.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month')).sort('date').group_by(
        'portfolio', 'month').agg(pl.col('date').last().alias('as_of'),
        pl.col('ex_ante_tracking_error', 'invested_prior_weight', 'unmodeled_prior_weight', *names).mean()).sort('portfolio', 'month')
    monthly.write_csv(output/'monthly_exposures.csv')
    component_names = [*names, 'specific', 'unmodeled', 'execution_cost_and_cash_residual']
    attribution = daily_contribution.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month')).sort('date')
    attribution = attribution.with_columns(pl.col('prior_equity').first().over('portfolio', 'month').alias('month_base'))
    attribution = attribution.group_by('portfolio', 'month').agg(
        *((pl.col(c)*pl.col('prior_equity')/pl.col('month_base')).sum().alias(c) for c in component_names),
        (pl.col('equity').last()/pl.col('month_base').first()-1).alias('return')).sort('portfolio', 'month')
    attribution = attribution.with_columns((pl.col('return')-pl.sum_horizontal(component_names)).alias('reconciliation_error'))
    if cast(float, attribution['reconciliation_error'].abs().max()) > 1e-10:
        raise ValueError('Monthly capital-linked attribution fails to reconcile')
    attribution.write_csv(output/'monthly_attribution.csv')
    stress = attribution.filter(pl.col('month') == '2024-01')
    stress.write_csv(output/'attribution_2024_01.csv')
    summary = {'conclusion': 'RESEARCH_ONLY', 'start': str(start), 'end': str(end),
        'portfolios': list(accounts), 'style_factors': 10, 'industry_categories': len(industries),
        'daily_regressions': len(factors), 'monthly_portfolio_rows': monthly.height,
        'max_monthly_reconciliation_error': attribution['reconciliation_error'].abs().max(),
        'max_unmodeled_prior_weight': daily_exposure['unmodeled_prior_weight'].max(),
        'risk_forecasts': daily_exposure['ex_ante_tracking_error'].is_not_null().sum(),
        'mean_imputed_style_fraction': pl.from_dicts(coverage)['imputed_style_fraction'].mean()}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    lines = ['# 日频十风格与历史申万行业风险模型', '',
        f"{len(factors)} 次日频回归，{monthly.height} 条组合月度暴露，{summary['risk_forecasts']} 条事前跟踪误差。", '',
        '|组合|2024-01收益|规模|市场及行业合计|特质|执行、成本与现金残差|', '|---|---:|---:|---:|---:|---:|']
    for row in stress.iter_rows(named=True):
        industry = sum(row[c] for c in names if c.startswith('industry:'))
        lines.append(f"|{row['portfolio']}|{row['return']:.2%}|{row['size']:.2%}|{industry:.2%}|{row['specific']:.2%}|{row['execution_cost_and_cash_residual']:.2%}|")
    lines += ['', '暴露为前一交易日信息；每日 sqrt(总市值) 加权截面回归，行业为完整截距，十风格为日频1/99分位截尾z值。财务缺口按当日已知行业中位数、再市场中位数处理，覆盖率逐日披露。', '',
        'EWMA因子协方差半衰期126日、特质方差63日，协方差10%对角收缩；事前TE只用前一日及以前收益，相对滞后可交易全市场等权风险代理。月度暴露是日均；归因按期初资本链接并逐月闭合。', '',
        '关键限制：风险代理基准与准入收益指数口径不同；缺失暴露持仓日TE留空，归因保留未建模及执行残差，不能解释为因果收益来源。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    write_stress_window(output)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--holdings-source', type=Path, help='Reuse previously reconciled holdings for exactly this config')
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.output, args.data_root, args.holdings_source)))


if __name__ == '__main__':
    main()
