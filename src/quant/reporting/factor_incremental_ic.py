"""Annual-causal incremental rank IC using the frozen model's exact feature encoding."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

import numpy as np
import polars as pl

from quant.research.factor_battery_statistics import monthly_ic_summary
from quant.research.model_training_models import common_features, validate_active_features


def incremental_ic(panel: pl.DataFrame, *, factors: list[str], minimum_symbols: int) -> list[dict]:
    """Rank once on a shared complete sample; use identical OLS controls for x/y."""
    if len(factors) != len(set(factors)) or not factors or minimum_symbols < 3:
        raise ValueError('Require unique factors and at least three samples')
    if panel.height and panel['trade_date'].n_unique() != 1:
        raise ValueError('One monthly cross-section required')
    if panel.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate stock/date')
    if panel.height:
        validate_active_features(panel, factors, required=True)
    active = [f for f in factors if panel.height and panel[f'__active_{f}'][0]]
    excluded = [f for f in factors if f not in active]
    complete = panel.filter(pl.all_horizontal([pl.col(c).is_finite().fill_null(False) for c in [*active, 'label_rebalance']]))
    n = complete.height
    rank_columns = [*active, 'label_rebalance']
    ranks = complete.select([pl.col(c).rank('average') for c in rank_columns]).to_numpy().astype(float)
    # Centering ranks improves numerical conditioning without changing OLS.
    ranks = ranks-ranks.mean(axis=0) if n else ranks
    rows = []
    for factor in factors:
        row = {'factor': factor, 'feature_stocks': panel.height, 'common_stocks': n,
            'label_paired_fraction': n/panel.height if panel.height else None,
            'active_factors': len(active), 'excluded_factors': json.dumps(excluded),
            'controls': json.dumps([f for f in active if f != factor]), 'raw_rank_ic': None,
            'partial_rank_ic': None, 'reason': 'ok', 'control_rank': None, 'control_columns': None}
        if factor not in active:
            row['reason'] = 'monthly_excluded_or_no_valid_feature_pool'
        elif n < minimum_symbols:
            row['reason'] = 'insufficient_common_sample'
        else:
            index = active.index(factor)
            x, y = ranks[:, index], ranks[:, -1]
            if np.linalg.norm(x) <= 1e-12:
                row['reason'] = 'constant_factor'
            elif np.linalg.norm(y) <= 1e-12:
                row['reason'] = 'constant_label'
            else:
                row['raw_rank_ic'] = float(np.dot(x, y)/(np.linalg.norm(x)*np.linalg.norm(y)))
                others = [i for i in range(len(active)) if i != index]
                z = np.column_stack([np.ones(n), ranks[:, others]])
                rank = np.linalg.matrix_rank(z)
                row['control_rank'], row['control_columns'] = int(rank), z.shape[1]
                if n <= z.shape[1]+1:
                    row['reason'] = 'insufficient_residual_degrees_of_freedom'
                elif rank != z.shape[1]:
                    row['reason'] = 'rank_deficient_controls'
                else:
                    residual = np.column_stack([x, y])-z@np.linalg.lstsq(z, np.column_stack([x, y]), rcond=None)[0]
                    rx, ry = residual[:, 0], residual[:, 1]
                    if np.linalg.norm(rx) <= 1e-10*max(1., np.linalg.norm(x)):
                        row['reason'] = 'factor_rank_explained_by_controls'
                    elif np.linalg.norm(ry) <= 1e-10*max(1., np.linalg.norm(y)):
                        row['reason'] = 'label_rank_explained_by_controls'
                    else:
                        row['partial_rank_ic'] = float(np.dot(rx, ry)/(np.linalg.norm(rx)*np.linalg.norm(ry)))
        rows.append(row)
    return rows


def run(*, config: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError('Use a new diagnostic directory')
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False:
        raise ValueError('Require research-only mode')
    source = Path(spec['source'])
    saved = tomllib.loads((source/'config.toml').read_text(encoding='utf-8'))
    model = tomllib.loads((source/'predictions/model.toml').read_text(encoding='utf-8'))
    battery = tomllib.loads((source/'predictions/battery.toml').read_text(encoding='utf-8'))
    fits = json.loads((source/'predictions/summary.json').read_text(encoding='utf-8'))['annual_fits']
    predictions = pl.read_parquet(source/'predictions/monthly_predictions.parquet')
    statistics = Path(model['research']['statistics_source'])
    roots = [Path(p) for p in saved['inputs']['calendar_statistics']]
    sources = {factor: roots for factor in saved['replacements'].values()}
    known_through = saved['model']['test_end']
    labels = pl.concat([pl.read_parquet(p).select('symbol', 'trade_date', 'label_rebalance', 'exit_date_rebalance')
        for p in sorted((statistics/'inputs').glob('*/monthly_labels.parquet'))], how='vertical_relaxed')
    if labels.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate outcome keys')
    labels = labels.with_columns(pl.when(pl.col('exit_date_rebalance') <= known_through)
        .then(pl.col('label_rebalance')).otherwise(None).alias('label_rebalance'))
    selected = [f for f in fits if spec['start_year'] <= f['test_year'] <= spec['end_year'] and f['factors']]
    rows: list[dict] = []
    coverage_rows: list[dict] = []
    checks: list[dict] = []
    output.mkdir(parents=True)
    (output/'config.toml').write_bytes(config.read_bytes())
    for fit in selected:
        year, factors = fit['test_year'], fit['factors']
        start = dt.date.fromisoformat(fit['refit_close'])
        next_fit = next((f for f in fits if f['test_year'] == year+1 and 'refit_close' in f), None)
        end = dt.date.fromisoformat(next_fit['refit_close'])-dt.timedelta(days=1) if next_fit else known_through
        coverage: list[dict] = []
        features = common_features(statistics=statistics, factors=factors, variant=model['selection']['variant'],
            start=start, end=end, minimum_symbols=saved['model']['minimum_signal_stocks'], statistics_sources=sources,
            missing_policy=saved['model']['missing_features'], maximum_missing_fraction=saved['model']['maximum_missing_fraction'], coverage=coverage)
        expected = predictions.filter(pl.col('test_year') == year).select('symbol', 'trade_date').sort('trade_date', 'symbol')
        if not features.select('symbol', 'trade_date').equals(expected):
            raise ValueError(f'Reconstructed feature universe differs from actual predictions for {year}')
        panel = features.join(labels, on=['symbol', 'trade_date'], how='left', validate='1:1')
        dates = sorted({r['trade_date'] for r in coverage})
        coverage_by_key = {(r['trade_date'], r['factor']): r for r in coverage}
        for day in dates:
            section = panel.filter(pl.col('trade_date') == day)
            for row in incremental_ic(section, factors=factors, minimum_symbols=spec['minimum_symbols']):
                cov = coverage_by_key[(day, row['factor'])]
                rows.append({**row, 'test_year': year, 'trade_date': day,
                    'eligible_stocks_before_control_filter': cov['eligible_stocks'], 'observed_factor_stocks': cov['observed_stocks'],
                    'controls_missing_stocks': cov['controls_missing_stocks'], 'factor_missing_fraction': cov['missing_fraction']})
        coverage_rows.extend({'test_year': year, **r} for r in coverage)
        checks.append({'test_year': year, 'factors': len(factors), 'feature_rows': features.height,
                       'prediction_keys_exact': True, 'signal_months': len(dates)})
        print(json.dumps(checks[-1]), flush=True)
        pl.from_dicts(rows, infer_schema_length=None).write_parquet(output/'monthly_incremental_ic.parquet')
    monthly = pl.from_dicts(rows, infer_schema_length=None)
    summaries = []
    for (factor,), frame in monthly.sort('trade_date').partition_by('factor', as_dict=True).items():
        for metric in ('raw_rank_ic', 'partial_rank_ic'):
            summary = monthly_ic_summary(frame['trade_date'].to_list(), frame[metric].to_list(),
                lag=battery['monthly_newey_west_lag'], minimum_months_per_year=battery['minimum_months_per_year'])
            summaries.append({'factor': factor, 'metric': metric, **summary,
                'selected_months': frame.height, 'meets_96_month_length': summary['months'] >= 96,
                'conclusion': 'RESEARCH_ONLY'})
    pl.from_dicts(summaries, infer_schema_length=None).write_csv(output/'ic_summary.csv')
    pl.from_dicts(coverage_rows, infer_schema_length=None).write_parquet(output/'feature_coverage.parquet')
    monthly.group_by('reason').agg(pl.len().alias('factor_months')).write_csv(output/'reasons.csv')
    result = {'annual_feature_checks': checks, 'factor_months': monthly.height, 'unique_factors': monthly['factor'].n_unique(),
        'identified_partial_months': monthly['partial_rank_ic'].is_not_null().sum(), 'known_through': str(known_through),
        'minimum_final_admission_months': 96, 'conclusion': 'RESEARCH_ONLY'}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    report = f"# 年度因果因子增量IC\n\n{len(checks)} 个年度名单，{monthly['factor'].n_unique()} 个不同因子，{monthly.height} 因子月；可识别partial IC共 {result['identified_partial_months']} 因子月。\n\n"
    report += "|因子|有效partial月|原平均IC|partial平均IC|partial NW t|\n|---|---:|---:|---:|---:|\n"
    def fmt(value: float | None) -> str:
        return f'{value:.4f}' if value is not None else 'NA'
    lookup = {(s['factor'], s['metric']): s for s in summaries}
    for factor in sorted(monthly['factor'].unique()):
        raw, partial = lookup[(factor, 'raw_rank_ic')], lookup[(factor, 'partial_rank_ic')]
        report += f"|{factor}|{partial['months']}|{fmt(raw['mean_ic'])}|{fmt(partial['mean_ic'])}|{fmt(partial['newey_west_t'])}|\n"
    report += "\n"
    report += (
        "因子与标签在同一完整共同样本上取平均秩，分别对相同其余当月有效因子秩及截距做OLS，最后相关两个残差。使用冻结模型的补零编码、日历替换和有效规模/行业控制。\n\n"
        "HAC复用既有日历月间隔口径；排除及退化月份保留NA。年度名单会变化，partial IC条件集也随当时名单变化；这份描述诊断不改变准入，少于96月的序列不据此晋级。\n")
    (output/'report.md').write_text(report, encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output)))


if __name__ == '__main__':
    main()
