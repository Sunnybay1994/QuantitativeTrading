"""Run descriptive raw-factor health diagnostics with a past-only reference."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.factor_health_inputs import (
    read_factor_health_inputs,
    read_factor_health_month_ends,
    read_factor_health_selection,
)
from quant.reporting.factor_health import HealthParameters, diagnose_factor_health


def reference_start(as_of: dt.date, months: int) -> dt.date:
    """First day of the fixed calendar window, excluding the current month."""
    if months < 1:
        raise ValueError('reference_months must be positive')
    year, month = divmod(as_of.year * 12 + as_of.month - 1 - months, 12)
    return dt.date(year, month + 1, 1)


def _flat(record: dict[str, Any], prefix: str = '') -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        name = f'{prefix}_{key}' if prefix else key
        if isinstance(value, dict):
            result.update(_flat(value, name))
        elif isinstance(value, (list, tuple)):
            result[name] = json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)
        else:
            result[name] = value
    return result


def _write_report(output: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    def number(value: Any, pattern: str = '.3f') -> str:
        return format(value, pattern) if value is not None else '缺失'

    latest = [row for row in records if row['as_of'] == summary['end']]
    lines = ['# Q1d 原始因子健康诊断', '',
        f"覆盖 {summary['start']}—{summary['end']} 共 {summary['report_months']} 个月、"
        f"{summary['unique_factors']} 个入选因子、{summary['factor_months']} 个因子月。",
        '', '年度名单从 refit_close 当日生效；因子原始值左接同日已冻结的 eligible 股票池。',
        '分布和漂移使用全池有限原始值；中性化裁剪先排除无效市值及行业，与中性化输入范围一致。',
        '', f"参考窗固定为此前 {summary['reference_months']} 个完整日历月，"
        '每月须有足够有限样本；按历史股票月观测合并取分位数，当月值不参与拟合分箱。',
        f"PSI 使用历史分位分箱和每箱 {summary['parameters']['psi_smoothing']:g} 伪计数；"
        '偏度、超额峰度使用总体矩。',
        '', f"## 最新截面：{summary['end']}", '',
        '|因子|原值缺失率|偏度|超额峰度|中性化输入裁剪率|PSI|规模秩相关|行业解释方差|',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in sorted(latest, key=lambda record: record['factor']):
        lines.append(f"|{row['factor_id']}|{number(row['counts']['missing_or_nonfinite_rate'], '.2%')}|"
            f"{number(row['distribution']['skewness'])}|{number(row['distribution']['excess_kurtosis'])}|"
            f"{number(row['mad_clipping_valid_controls']['clipped_fraction'], '.2%')}|"
            f"{number(row['drift']['psi'])}|{number(row['controls']['size']['spearman'])}|"
            f"{number(row['controls']['industry']['eta_squared'], '.2%')}|")
    reasons = []
    for row in records:
        for name, reason in [('distribution', row['distribution']['reason']),
                ('skewness', row['distribution']['skewness_reason']),
                ('excess_kurtosis', row['distribution']['excess_kurtosis_reason']),
                ('mad_all', row['mad_clipping']['reason']),
                ('mad_valid_controls', row['mad_clipping_valid_controls']['reason']),
                ('psi', row['drift']['psi_reason']),
                ('median_shift_iqr', row['drift']['median_shift_reason']),
                ('size', row['controls']['size']['reason']),
                ('industry', row['controls']['industry']['reason'])]:
            if reason:
                reasons.append({'metric': name, 'reason': reason})
    lines += ['', '## 无法计算的指标', '']
    if reasons:
        counts = pl.from_dicts(reasons).group_by('metric', 'reason').len().sort('metric', 'reason')
        lines += ['|指标|原因|因子月数|', '|---|---|---:|']
        lines += [f"|{row['metric']}|{row['reason']}|{row['len']}|"
                  for row in counts.iter_rows(named=True)]
    else:
        lines.append('本批各项指标均有足够样本且可计算。')
    lines += ['', '逐月明细见 health.parquet / health.jsonl；分母、真实裁剪阈值、历史分箱边界、'
        '参考各月样本数和无效原因一并保存。input_coverage.parquet 区分缺分区、缺行、null 与非有限值，'
        'sample_inputs.parquet 保留原始值及控制项供抽查。', '',
        '下一步：日常刷新调用相同读取与统计函数，将结果作为输入诊断日志。', '',
        '关键限制：分布漂移同时受股票池变化和市场状态影响，诊断数值本身不作为因子准入或持仓条件。', '']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def run_factor_health(*, config: Path, output: Path, data_root: Path) -> dict[str, Any]:
    """Read each selected raw panel once and publish new, inspectable diagnostics."""
    if output.exists():
        raise FileExistsError('Choose a new factor-health run directory')
    saved_config = config.read_bytes()
    settings = tomllib.loads(saved_config.decode('utf-8'))
    scope = settings['diagnostics']
    start, end = scope['start'], scope['end']
    months = scope['reference_months']
    if (type(start) is not dt.date or type(end) is not dt.date or start > end
            or type(months) is not int or months < 1
            or scope.get('diagnostics_only') is not True):
        raise ValueError('Require dated, bounded, diagnostics-only factor health settings')
    parameters = HealthParameters(**settings['statistics'])
    if parameters.minimum_reference_months > months:
        raise ValueError('Reference requirement exceeds the fixed reference window')
    statistics = Path(scope['statistics'])
    history_dates = read_factor_health_month_ends(data_root=data_root, statistics=statistics,
        start=reference_start(start, months), end=end)
    dates = [day for day in history_dates if start <= day <= end]
    if not dates:
        raise ValueError('No completed month ends in the requested reporting window')
    plan = read_factor_health_selection(selection=Path(scope['selection']), as_of_dates=dates,
        max_factors=scope['maximum_factors'], replacements=settings.get('replacements', {}))
    if plan.is_empty():
        raise ValueError('No annually selected factors in the requested reporting window')
    records: list[dict[str, Any]] = []
    coverage: list[pl.DataFrame] = []
    samples: list[pl.DataFrame] = []
    for (factor_id,), factor_plan in plan.partition_by('factor_id', as_dict=True).items():
        active_dates = factor_plan['as_of'].to_list()
        needed = [day for day in history_dates
                  if any(reference_start(current, months) <= day <= current
                         for current in active_dates)]
        panel = read_factor_health_inputs(data_root=data_root, statistics=statistics,
            factor_id=str(factor_id), as_of_dates=needed)
        coverage.append(panel.group_by('trade_date', 'raw_value_status').agg(
            pl.len().alias('rows')).with_columns(pl.lit(str(factor_id)).alias('factor_id')))
        for selected in factor_plan.sort('as_of').iter_rows(named=True):
            day = selected['as_of']
            current = panel.filter(pl.col('trade_date') == day)
            prior = panel.filter((pl.col('trade_date') >= reference_start(day, months))
                & (pl.col('trade_date') < day.replace(day=1)))
            diagnostic = diagnose_factor_health(current, prior, as_of=day, parameters=parameters)
            status_counts = {row['raw_value_status']: row['len'] for row in
                current.group_by('raw_value_status').len().iter_rows(named=True)}
            record = {**diagnostic, **selected, 'reference_start': reference_start(day, months),
                'reference_end_exclusive': day.replace(day=1),
                'source_partition': str(data_root / 'factors' / str(factor_id)
                    / f'year={day.year}/data.parquet'),
                'controls_source': str(statistics / f'inputs/{day.year}/universe.parquet'),
                'raw_status_counts': {key: status_counts.get(key, 0) for key in
                    ('observed', 'null_value', 'nonfinite_value', 'missing_row', 'missing_partition')}}
            # Strict JSON conversion fails on any accidental NaN/Infinity before publication.
            json.dumps(record, allow_nan=False, default=str)
            records.append(record)
            samples.append(current.sort('symbol').head(3).with_columns(
                pl.lit(str(factor_id)).alias('factor_id'), pl.lit(selected['factor']).alias('factor')))
        print(f'factor_health: {factor_id}: {factor_plan.height} months', flush=True)
    flat = pl.from_dicts([_flat(record) for record in records], infer_schema_length=None)
    flat = flat.with_columns(pl.col('as_of').cast(pl.Date)).sort('as_of', 'factor')
    latest = flat.filter(pl.col('as_of') == max(dates))
    summary = {'diagnostics_only': True, 'start': min(dates), 'end': max(dates),
        'report_months': len(dates), 'factor_months': len(records),
        'unique_factors': plan['factor'].n_unique(), 'latest_factor_count': latest.height,
        'reference_months': months, 'minimum_reference_months': parameters.minimum_reference_months,
        'reference_policy': 'Previous calendar months only; bins fitted independently on that past window',
        'selection': scope['selection'], 'statistics': scope['statistics'],
        'model_config': scope.get('model_config'), 'factor_replacements': settings.get('replacements', {}),
        'parameters': records[0]['parameters'],
        'factor_ids': sorted(plan['factor_id'].unique().to_list()), 'output': str(output)}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.toml').write_bytes(saved_config)
    plan.write_parquet(output / 'selection.parquet')
    flat.write_parquet(output / 'health.parquet')
    pl.concat(coverage).sort('factor_id', 'trade_date', 'raw_value_status').write_parquet(
        output / 'input_coverage.parquet')
    pl.concat(samples).write_parquet(output / 'sample_inputs.parquet')
    (output / 'health.jsonl').write_text('\n'.join(json.dumps(record, ensure_ascii=False,
        allow_nan=False, default=str) for record in records) + '\n', encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False,
        allow_nan=False, default=str, indent=2), encoding='utf-8')
    _write_report(output, records, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run_factor_health(config=args.config, output=args.output,
        data_root=args.data_root), default=str, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
