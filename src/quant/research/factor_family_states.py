"""Describe saved battery IC by new market states; no factor rescreening or selection."""
import argparse
import hashlib
import json
from pathlib import Path

import polars as pl

DIMENSIONS = ['liquidity_state', 'sentiment_state', 'volatility_state', 'market_state']


def run(output, battery):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {}

    def read(path):
        manifest[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return pl.read_parquet(path)

    states = read(Path('artifacts/research/market_indicators_20260922_02/market_states.parquet'))
    if states['trade_date'].is_duplicated().any() or states.filter(pl.col('effective_date') <= pl.col('trade_date')).height:
        raise ValueError('Invalid state timing')
    definitions = read(battery/'scorecard/factor_scorecard.parquet').select('factor','family').unique()
    if definitions['factor'].is_duplicated().any():
        raise ValueError('Ambiguous factor family')
    panels, missing = [], []
    for row in definitions.iter_rows(named=True):
        path = battery/'statistics/factors'/row['factor']/'monthly_ic.parquet'
        if not path.exists():
            missing.append(str(path))
            continue
        ic = read(path)
        if ic.select('trade_date','variant').is_duplicated().any():
            raise ValueError('Duplicate factor month/variant')
        panels.append(ic.with_columns(pl.lit(row['factor']).alias('factor'), pl.lit(row['family']).alias('family')))
    panel = pl.concat(panels).join(states.select('trade_date','effective_date',*DIMENSIONS), on='trade_date', how='left', validate='m:1').with_columns(
        pl.col(*DIMENSIONS).fill_null('unknown'), pl.col('trade_date').dt.year().alias('year'))
    panel.write_parquet(output/'monthly_factor_states.parquet')
    long = panel.unpivot(on=DIMENSIONS, index=['factor','family','variant','year','trade_date','rank_ic'],
                         variable_name='dimension', value_name='state')
    finite = long.filter(pl.col('rank_ic').is_finite())
    by_factor = finite.group_by('factor','family','variant','year','dimension','state').agg(
        pl.len().alias('valid_months'), pl.col('rank_ic').mean().alias('mean_rank_ic'))
    by_factor.sort('factor','variant','year','dimension','state').write_csv(output/'factor_year_state_ic.csv')
    # Correlated factors are not independent samples: average within family/month first.
    family_month = finite.group_by('family','variant','trade_date','year','dimension','state').agg(
        pl.col('factor').n_unique().alias('factor_count'), pl.col('rank_ic').mean().alias('family_mean_ic'))
    family_month.write_parquet(output/'family_month_states.parquet')
    family = family_month.group_by('family','variant','year','dimension','state').agg(
        pl.len().alias('valid_months'), pl.col('family_mean_ic').mean().alias('mean_rank_ic'),
        pl.col('factor_count').min().alias('minimum_factors'),pl.col('factor_count').max().alias('maximum_factors'))
    family.sort('family','variant','year','dimension','state').write_csv(output/'family_year_state_ic.csv')
    manifest[str(Path(__file__))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = dict(status='complete', factors=panel['factor'].n_unique(), families=panel['family'].unique().sort().to_list(),
                  factor_variant_months=panel.height, missing_sources=missing,
                  unknown_market_rows=panel.filter(pl.col('market_state')=='unknown').height,
                  metric='saved monthly rank IC, not Q7 partial/incremental IC',
                  auto_trade=False, historical_is_development=True)
    (output/'source_manifest.json').write_text(json.dumps(manifest, indent=2),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(result, indent=2),encoding='utf-8')
    (output/'report.md').write_text('# 因子族与滞后市场状态\n\n机器生成，复用完整电池月度IC，不重新筛选因子。\n\n'
        + json.dumps(result, ensure_ascii=False, indent=2)
        + '\n\n信号收盘指标仅对下一交易日生效。早期无状态的月份保留unknown，不填零。'
        '\n\n原始/中性化版本分别输出；该IC不是Q7条件增量IC。族内先按月等权平均，因子数量不当独立样本数；状态子样本不估计连续时间NW t或据此挑选赢家。'
        '\n\n收益指数、成本、实盘延迟和完整电池准入均未被此诊断替代。\n',encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--battery',type=Path,default=Path('artifacts/factors/nightly_batches/6b35e47b1f0dcf04/evaluation'))
    args = parser.parse_args()
    print(json.dumps(run(args.output,args.battery)))
