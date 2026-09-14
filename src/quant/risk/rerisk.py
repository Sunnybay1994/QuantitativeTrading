"""Recompute historical risk from saved regressions, without refitting WLS."""
from __future__ import annotations

import argparse
import json
import shutil
import tomllib
from pathlib import Path

import numpy as np
import polars as pl

from quant.data.risk_model_inputs import load_risk_year
from quant.risk.model import EWMARisk, STYLES, design, prepare_exposures, tracking_error
from quant.risk.run import write_stress_window


def write_report(output: Path) -> None:
    """Render both calendar-month and registered-stress attribution, all components."""
    summary = json.loads((output/'summary.json').read_text(encoding='utf-8'))
    january = pl.read_csv(output/'attribution_2024_01.csv')
    lines = ['# 日频十风格与历史申万行业风险模型', '',
        f"{summary['daily_regressions']} 次日频回归，{summary['monthly_portfolio_rows']} 条组合月度暴露，{summary['risk_forecasts']} 条事前跟踪误差。", '',
        '|组合|2024-01-01至01-31收益|规模|其他九风格|市场及行业合计|特质|执行及未建模|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for row in january.sort('portfolio').iter_rows(named=True):
        other = sum(row[c] for c in STYLES if c != 'size')
        industry = sum(row[c] for c in january.columns if c.startswith('industry:'))
        residual = row['execution_cost_and_cash_residual']+row['unmodeled']
        lines.append(f"|{row['portfolio']}|{row['return']:.2%}|{row['size']:.2%}|{other:.2%}|{industry:.2%}|{row['specific']:.2%}|{residual:.2%}|")
    lines += ['', f"暴露使用前一交易日信息，回归按sqrt(总市值)加权，十风格为日频1/99分位截尾z值。财务缺口使用已知行业中位数、再市场中位数；平均填补{summary['mean_imputed_style_fraction']:.2%}风格单元，覆盖率逐日披露。", '',
        'EWMA因子协方差半衰期126日、特质方差63日，协方差10%对角收缩；事前TE相对滞后可交易全市场等权风险代理。月度暴露为日均；收益归因按期初资本链接并逐月闭合。', '',
        f"行业有效集合切换{summary['industry_regime_resets']}次，因子EWMA重置后满60个实际交易日才估计TE；2019年起始60日也留空。行业不存在期间的零系数不计为新行业历史。具体日期见industry_regimes.csv，每个TE保留历史日数和覆盖原因，每月保留有效估计日数。", '',
        '完整行业截距包含共同市场涨跌，所以列名为市场及行业合计；不能解释成主动行业偏离。', '',
        '关键限制：风险代理基准与准入收益指数口径不同；缺失暴露持仓日TE留空，归因保留未建模及执行残差。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    write_stress_window(output)


def run(source: Path, output: Path, data_root: Path) -> dict:
    spec = tomllib.loads((source/'config.toml').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=False)
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, output/path.name)
    factors = pl.read_parquet(source/'daily_factor_returns.parquet').sort('date')
    names = [c for c in factors.columns if c not in ['date', 'exposure_date', 'observations']]
    industries = [name.removeprefix('industry:') for name in names[len(STYLES):]]
    returns = {row['date']: np.array([row[name] for name in names]) for row in factors.iter_rows(named=True)}
    original = pl.read_parquet(source/'daily_exposures.parquet')
    holdings = {p['name']: pl.read_parquet(source/f"{p['name']}_security_daily.parquet").partition_by(
        'date', as_dict=True) for p in spec['portfolios']}
    state = EWMARisk(len(names), spec['covariance_half_life'], spec['specific_half_life'],
                     spec['minimum_history'], spec['covariance_diagonal_shrinkage'])
    first, end = factors['date'][0], factors['date'][-1]
    previous = load_risk_year(data_root=data_root, statistics=Path(spec['statistics']), year=first.year-1)
    previous = previous.filter(pl.col('trade_date') == previous['trade_date'].max())
    rows, regimes = [], []
    covariances: list[dict] = []
    for year in range(first.year, end.year+1):
        print(f'replaying saved factor returns {year}', flush=True)
        panel = load_risk_year(data_root=data_root, statistics=Path(spec['statistics']), year=year)
        sections = panel.filter(pl.col('trade_date') <= end).sort('trade_date', 'symbol').partition_by('trade_date')
        for number, current in enumerate(sections):
            day = current['trade_date'][0]
            beta = returns[day]
            lagged = prepare_exposures(previous)
            forecast = lagged.filter(pl.col('total_market_value') > 0)
            symbols = forecast['symbol'].to_list()
            indices = {symbol: i for i, symbol in enumerate(symbols)}
            x = design(forecast, industries)
            benchmark = forecast['eligible'].to_numpy().astype(float)
            benchmark /= benchmark.sum()
            active = set(forecast.filter(pl.col('eligible'))['industry_l1'].to_list())
            if state.begin_industry_regime(active):
                regimes.append({'date': day, 'exposure_date': previous['trade_date'][0],
                                'industry_count': len(active), 'industries': ','.join(sorted(active))})
            covariance = state.covariance()
            specific, proxy_count = state.prior_specific(symbols)
            for name in holdings:
                weight = np.zeros(len(symbols))
                missing_weight = 0.
                for row in holdings[name].get((day,), pl.DataFrame()).iter_rows(named=True):
                    index = indices.get(row['symbol'])
                    if index is None:
                        missing_weight += row['prior_weight']
                    else:
                        weight[index] = row['prior_weight']
                reason = ('unmodeled_prior_holdings' if missing_weight > 1e-10 else
                          'industry_regime_history_under_60' if covariance is None else 'estimated')
                te = tracking_error(weight-benchmark, x, covariance, specific) if reason == 'estimated' and covariance is not None else None
                if te is not None and not np.isfinite(te):
                    reason, te = 'specific_history_unavailable', None
                rows.append({'date': day, 'portfolio': name, 'ex_ante_tracking_error': te,
                    'risk_information_through': state.last_date, 'risk_history_sessions': state.observations,
                    'risk_coverage_reason': reason, 'specific_prior_proxy_symbols': proxy_count})
            last_session = number == len(sections)-1 or sections[number+1]['trade_date'][0].month != day.month
            if last_session and covariance is not None:
                covariances.extend({'date': day, 'information_through': state.last_date,
                    'factor_i': names[i], 'factor_j': names[j], 'daily_covariance': float(covariance[i, j]),
                    'risk_history_sessions': state.observations}
                    for i in range(len(names)) for j in range(i+1)
                    if (i < len(STYLES) or industries[i-len(STYLES)] in active)
                    and (j < len(STYLES) or industries[j-len(STYLES)] in active))
            # Same fitted coefficients, reconstituting residual histories from original descriptors.
            valid = lagged.join(current.select('symbol', pl.col('adjusted_close').alias('next_close')),
                on='symbol', how='inner', validate='1:1').with_columns(
                (pl.col('next_close')/pl.col('adjusted_close')-1).alias('security_return')).filter(
                pl.col('security_return').is_finite() & (pl.col('total_market_value') > 0))
            residual = valid['security_return'].to_numpy()-design(valid, industries)@beta
            state.update(day, beta, dict(zip(valid['symbol'].to_list(), residual.tolist(), strict=True)))
            previous = current
    corrected = original.drop('ex_ante_tracking_error', 'risk_information_through').join(
        pl.from_dicts(rows, infer_schema_length=None), on=['date', 'portfolio'], validate='1:1')
    corrected.write_parquet(output/'daily_exposures.parquet')
    pl.from_dicts(regimes).write_csv(output/'industry_regimes.csv')
    pl.from_dicts(covariances).write_parquet(output/'factor_covariance.parquet')
    pl.DataFrame({'symbol': list(state.specific),
        'information_through': [state.last_date]*len(state.specific),
        'daily_specific_variance': [v[0] for v in state.specific.values()],
        'observations': [v[1] for v in state.specific.values()]}).write_parquet(output/'specific_variance.parquet')
    monthly = corrected.with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month')).sort('date').group_by(
        'portfolio', 'month').agg(pl.col('date').last().alias('as_of'),
        pl.col('ex_ante_tracking_error', 'invested_prior_weight', 'unmodeled_prior_weight', *names).mean(),
        pl.col('ex_ante_tracking_error').is_not_null().sum().alias('risk_covered_sessions'),
        pl.len().alias('sessions')).sort('portfolio', 'month')
    monthly.write_csv(output/'monthly_exposures.csv')
    summary = json.loads((source/'summary.json').read_text(encoding='utf-8'))
    summary.update({'source_regressions': str(source), 'risk_forecasts': corrected['ex_ante_tracking_error'].is_not_null().sum(),
        'industry_regime_resets': len(regimes), 'risk_warmup_start': str(first),
        'covariance_regime': 'Reset on lagged eligible industry set change; 60 actual sessions required',
        'coverage_reasons': corrected.group_by('risk_coverage_reason').len().to_dicts()})
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    write_report(output)
    january = pl.read_csv(output/'attribution_2024_01.csv').with_columns(
        pl.lit('2024-01-01').alias('window_start'), pl.lit('2024-01-31').alias('window_end'))
    january.write_csv(output/'attribution_2024_01.csv')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output, args.data_root)))


if __name__ == '__main__':
    main()
