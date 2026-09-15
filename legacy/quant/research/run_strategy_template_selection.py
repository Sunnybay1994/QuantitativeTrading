"""Finite model-method selection from existing causal predictions; no test tuning."""
import argparse
import datetime as dt
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.research.factor_battery_statistics import benjamini_hochberg, monthly_ic_summary, rank_ic_by_date


def select_method(*, scores: pl.DataFrame, labels: pl.DataFrame, fits: list[dict],
                  config: dict[str, Any]) -> tuple[dict, pl.DataFrame]:
    selection, research, forward = config['selection'], config['research'], config['forward']
    methods = selection['methods']
    if (not methods or len(methods) != len(set(methods)) or len(methods) > research['maximum_candidates']
            or set(methods) - {'equal_z', 'positive_mean_ic', 'lightgbm'}
            or research['auto_trade'] is not False):
        raise ValueError('Invalid finite model grid')
    start, end = selection['validation_start'], selection['validation_end']
    if not start <= end < forward['start'] or forward['conclusion_before_independent_evidence'] != 'RESEARCH_ONLY':
        raise ValueError('Require ordered validation and future research periods')
    panel = scores.filter(pl.col('trade_date').is_between(start, end))
    if panel.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate validation predictions')
    if panel.filter(~pl.all_horizontal([pl.col(m).is_finite().fill_null(False) for m in methods])).height:
        raise ValueError('Models must share complete finite predictions')
    for year in panel['test_year'].unique():
        entries = [row for row in fits if row['test_year'] == year]
        if len(entries) != 1:
            raise ValueError('Require one causal fit per prediction year')
        fit = entries[0]
        cutoff = dt.date.fromisoformat(fit['refit_close'])
        if (dt.date.fromisoformat(fit['last_known_exit']) > cutoff
                or fit['training_months'] < selection['minimum_training_months']
                or panel.filter((pl.col('test_year') == year) & (pl.col('trade_date') < cutoff)).height):
            raise ValueError('Model fit crosses the information boundary or lacks training history')
    known = labels.filter(pl.col('trade_date').is_between(start, end)
                          & (pl.col('exit_date_rebalance') <= end))
    if (known.select('symbol', 'trade_date').is_duplicated().any()
            or known.filter(pl.col('exit_date_rebalance') <= pl.col('trade_date')).height):
        raise ValueError('Duplicate or non-forward validation labels')
    joined = panel.join(known.select('symbol', 'trade_date', 'label_rebalance'),
                        on=['symbol', 'trade_date'], how='left', validate='1:1')
    attempts, monthly = [], []
    for method in methods:
        ic = rank_ic_by_date(joined, score=method, label='label_rebalance',
            minimum_symbols=selection['minimum_symbols'], minimum_paired_coverage=selection['minimum_paired_coverage'])
        stats = monthly_ic_summary(ic['trade_date'].to_list(), ic['rank_ic'].to_list(),
                                   lag=selection['newey_west_lag'])
        mean = stats['mean_ic']
        eligible = stats['months'] >= selection['minimum_validation_months'] and (
            mean is not None and math.isfinite(mean) and mean > selection['minimum_mean_ic_exclusive'])
        attempts.append({'method': method, **stats, 'eligible_for_forward_research': eligible})
        monthly.append(ic.with_columns(pl.lit(method).alias('method')))
    for row, adjusted in zip(attempts, benjamini_hochberg([row['p_value'] for row in attempts]), strict=True):
        row['family_fdr_q'] = adjusted
    eligible = [row for row in attempts if row['eligible_for_forward_research']]
    best = min(eligible, key=lambda row: (-row['mean_ic'], methods.index(row['method']))) if eligible else None
    result = {'research_id': research['id'], 'attempts': attempts,
        'selected_method': best['method'] if best else None,
        'conclusion': 'RESEARCH_ONLY' if best else 'REJECTED', 'auto_trade': False,
        'historical_evidence': research['historical_evidence'],
        'validation_start': str(start), 'validation_end': str(end), 'forward_start': str(forward['start']),
        'minimum_forward_months': forward['minimum_observation_months'],
        'source_rejections_remain_effective': True,
        'selection_rule': selection['ranking']}
    return result, pl.concat(monthly)


def run_selection(*, config_path: Path, output: Path) -> dict:
    contents = config_path.read_bytes()
    config = tomllib.loads(contents.decode('utf-8'))
    source = Path(config['research']['predictions'])
    source_model = tomllib.loads((source/'model.toml').read_text(encoding='utf-8'))
    selection = config['selection']
    start, end = selection['validation_start'], selection['validation_end']
    scores = pl.scan_parquet(source/'monthly_predictions.parquet').filter(
        pl.col('trade_date').is_between(start, end)).collect()
    statistics = Path(source_model['research']['statistics_source'])
    labels = pl.concat([pl.scan_parquet(path).filter(pl.col('trade_date').is_between(start, end)
        & (pl.col('exit_date_rebalance') <= end)).select('symbol', 'trade_date', 'exit_date_rebalance',
        'label_rebalance').collect() for path in sorted((statistics/'inputs').glob('*/monthly_labels.parquet'))])
    fits = json.loads((source/'summary.json').read_text(encoding='utf-8'))['annual_fits']
    result, monthly = select_method(scores=scores, labels=labels, fits=fits, config=config)
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(contents)
    (output/'source_model.toml').write_bytes((source/'model.toml').read_bytes())
    monthly.write_parquet(output/'validation_monthly_ic.parquet')
    pl.DataFrame(result['attempts']).write_csv(output/'attempts.csv')
    (output/'selection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 有限策略模板选型', '', f"选择：{result['selected_method'] or '无'}；结论：{result['conclusion']}。", '',
        '|方法|有效月数|平均RankIC|ICIR|Newey–West t|', '|---|---:|---:|---:|---:|']
    for row in result['attempts']:
        values = [f"{row[key]:.4f}" if row[key] is not None else '缺失' for key in ('mean_ic', 'icir', 'newey_west_t')]
        lines.append(f"|{row['method']}|{row['months']}|{'|'.join(values)}|")
    lines += ['', f"验证期{start}至{end}；只使用期末已实现的标签。前向观察从{result['forward_start']}开始。",
              '历史已经用于研究，原模型拒绝结论仍有效；选型只冻结后续研究方法，不产生交易准入。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_selection(config_path=args.config, output=args.output)))


if __name__ == '__main__':
    main()
