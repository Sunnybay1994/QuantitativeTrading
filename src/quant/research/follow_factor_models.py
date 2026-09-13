"""Continue a complete factor batch into the existing annual model pipeline."""
import argparse
import datetime as dt
import json
import re
import tomllib
from pathlib import Path

import polars as pl

from quant.research.factor_battery_cost_batch import existing_cost_factor
from quant.research.factor_battery_cost_report import load_cost_history
from quant.research.run_multifactor_pipeline import run_pipeline


def _bind_template(text: str, changes: dict[str, dict]) -> str:
    section = ''
    remaining = {name: dict(values) for name, values in changes.items()}
    lines = []
    skipping_array = False
    for line in text.splitlines():
        if skipping_array:
            if ']' in line:
                skipping_array = False
            continue
        match = re.fullmatch(r'\s*\[([^\]]+)\]\s*', line)
        if match:
            if section in remaining:
                for key, value in remaining[section].items():
                    lines.append(f'{key} = {_toml_value(value)}')
                remaining[section].clear()
            section = match[1]
        key = line.split('=', 1)[0].strip() if '=' in line else None
        if key in remaining.get(section, {}):
            value = remaining[section].pop(key)
            original = line.split('=', 1)[1].strip()
            skipping_array = original.startswith('[') and ']' not in original
            line = f'{key} = {_toml_value(value)}'
        lines.append(line)
    if section in remaining:
        lines += [f'{key} = {_toml_value(value)}' for key, value in remaining[section].items()]
        remaining[section].clear()
    if any(remaining.values()):
        raise ValueError('Model template lacks required sections')
    result = '\n'.join(lines)+'\n'
    tomllib.loads(result)
    return result


def _toml_value(value: object) -> str:
    return value.isoformat() if type(value) is dt.date else json.dumps(value, ensure_ascii=False)


def next_model_output(parent: Path) -> Path:
    number, output = 1, parent/'models'
    while output.exists():
        number += 1
        output = parent/f'models_{number:03d}'
    return output


def follow_factor_models(*, evaluation: Path, model_config: Path, measurement_config: Path,
                         output: Path, data_root: Path = Path('data')) -> dict:
    """Bind every evaluated factor, never the full-period admission winners."""
    template = model_config.read_text(encoding='utf-8')
    model = tomllib.loads(template)
    measurement_bytes = measurement_config.read_bytes()
    measurement = tomllib.loads(measurement_bytes.decode('utf-8'))
    if (set(measurement) != {'benchmarks'} or not {'equal_weight_snapshot', 'etf_total_return_snapshot'}
            <= set(measurement['benchmarks'])):
        raise ValueError('Factor continuation requires explicit return-index measurement configuration')
    if model['execution']['auto_trade'] is not False:
        raise ValueError('Model continuation requires auto_trade=false')
    choices = [evaluation/name for name in ('statistics', 'training') if (evaluation/name/'statistics.parquet').is_file()]
    if len(choices) != 1:
        raise ValueError('Require exactly one complete statistics or training source')
    statistics = choices[0]
    battery = tomllib.loads((statistics/'battery.toml').read_text(encoding='utf-8'))
    statistical_summary = json.loads((statistics/'summary.json').read_text(encoding='utf-8'))
    if battery['run']['selected'] != 'all':
        raise ValueError('Continuation must use the complete evaluated factor batch')
    known_through = min(battery['run']['as_of'], dt.date.fromisoformat(statistical_summary['as_of']))
    end = min(model['walk_forward']['test_end'], known_through)
    if model['walk_forward']['test_start'] > end:
        raise ValueError('Statistical history ends before the model test window')
    family = pl.read_parquet(statistics/'statistics.parquet', columns=['factor', 'variant'])
    factors = sorted(set(family['factor']))
    if (not factors or statistical_summary['factors'] != len(factors) or
            family.is_duplicated().any() or set(family.rows()) !=
            {(factor, variant) for factor in factors for variant in battery['variants']}):
        raise ValueError('Incomplete statistical factor family')
    benchmarks = evaluation/'benchmarks'
    benchmark_summary = json.loads((benchmarks/'summary.json').read_text(encoding='utf-8'))
    missing = []
    for factor in factors:
        for name in ('monthly_ic.parquet', 'monthly_groups.parquet', 'monthly_scores.parquet'):
            if not (statistics/'factors'/factor/name).is_file():
                missing.append(f'statistics:{factor}/{name}')
    for year in range(model['walk_forward']['test_start'].year-1, end.year+1):
        for name in ('universe.parquet', 'monthly_labels.parquet'):
            if not (statistics/'inputs'/str(year)/name).is_file():
                missing.append(f'statistics:inputs/{year}/{name}')
    roots = {p.parent.resolve() for pattern in ('*/summary.json', 'attempt_*/*/summary.json')
             for p in (evaluation/'costs').glob(pattern)}
    for path in (evaluation/'costs').rglob('batch_summary.json'):
        batch = json.loads(path.read_text(encoding='utf-8'))
        roots.update(Path(value).resolve() for value in batch.get('completed_runs', {}).values())
    completed = {}
    for run in sorted(roots):
        if not (run/'summary.json').is_file():
            continue
        factor = existing_cost_factor(run, settings=battery, snapshot=benchmark_summary['execution_snapshot'])
        if factor not in factors or factor in completed:
            raise ValueError(f'Unknown or duplicate completed cost factor: {factor}')
        saved = json.loads((run/'summary.json').read_text(encoding='utf-8'))
        expected = {(v, c) for v in battery['variants'] for c in battery['portfolio']['cost_multipliers']}
        if (len(saved['rows']) != len(expected) or
                {(r['variant'], r['cost_multiplier']) for r in saved['rows']} != expected):
            missing.append(f'costs:{factor}:incomplete_variants_or_costs')
            continue
        if any(dt.date.fromisoformat(r['last_date']) < end for r in saved['rows']):
            missing.append(f'costs:{factor}:ends_before_model_window')
            continue
        try:
            for variant, multiplier in sorted(expected):
                load_cost_history(run, variant, multiplier, battery['run']['as_of'])
        except (ValueError, FileNotFoundError) as exc:
            missing.append(f'costs:{factor}:incomplete_account_history:{exc}')
            continue
        completed[factor] = str(run)
    missing += [f'costs:{factor}' for factor in factors if factor not in completed]
    output.mkdir(parents=True, exist_ok=False)
    (output/'additional_costs').mkdir()
    content = _bind_template(template, {'research': {
        'id': f'{model["research"]["id"]}-{output.name}',
        'statistics_source': str(statistics.resolve()), 'battery_config': str((statistics/'battery.toml').resolve()),
        'cost_root': str((output/'additional_costs').resolve()), 'cost_runs': [completed[f] for f in sorted(completed)],
        'stock_benchmarks': str(benchmarks.resolve()),
        'historical_evidence': 'retrospective_adaptive_candidate_batch_not_an_unseen_holdout',
        'factor_evaluation_source': str(evaluation.resolve()),
        'candidate_selection_scope': 'entire_evaluated_family_reassessed_on_annual_known_prefixes'},
        'walk_forward': {'test_end': end}})
    (output/'model.toml').write_text(content, encoding='utf-8')
    (output/'model_template.toml').write_text(template, encoding='utf-8')
    (output/'measurement.toml').write_bytes(measurement_bytes)
    result: dict = {'model_results_ready': False, 'evaluation': str(evaluation.resolve()),
        'candidate_factors': factors, 'completed_cost_factors': sorted(completed),
        'known_through': str(known_through), 'test_end': str(end), 'missing_inputs': sorted(set(missing)),
        'historical_evidence': 'retrospective', 'conclusion': 'RESEARCH_ONLY', 'promotion_allowed': False, 'selection_basis': 'whole_batch_annual_known_prefix',
        'pipeline_output': str(output/'pipeline')}
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    try:
        if not missing:
            result['pipeline'] = run_pipeline(config=output/'model.toml', output=output/'pipeline',
                data_root=data_root, measurement_config=output/'measurement.toml')
            result['model_results_ready'] = result['pipeline']['model_results_ready']
    except Exception as exc:
        result['failure_reason'] = str(exc)
        raise
    finally:
        write_result(output=output, result=result)
    return result


def write_result(*, output: Path, result: dict) -> None:
    """Keep adaptive-discovery results research-only; preserve raw model decisions."""
    result['conclusion'] = 'RESEARCH_ONLY'
    result['promotion_allowed'] = False
    result['raw_model_conclusions'] = result.get('pipeline', {}).get('conclusions')
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output/'report.md').write_text('# 因子评估接续年度模型\n\n'
        f'整批 {len(result["candidate_factors"])} 个候选，完成成本 {len(result["completed_cost_factors"])} 个；'
        f'模型结果齐全：{result["model_results_ready"]}。最终结论上限：RESEARCH_ONLY。\n\n'
        f'统计可知末日 {result["known_through"]}，模型测试末日 {result["test_end"]}；模板准入阈值保持原值。\n\n'
        '全部候选进入逐年前缀筛选，不按全期评分表赢家过滤。候选挖掘使用历史数据，属于 retrospective；'
        '底层模型指标及原判定保留为诊断，不会触发自动晋级。\n\n'
        f'待补输入：{result["missing_inputs"]}。失败原因：{result.get("failure_reason", "无")}。\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation', type=Path, required=True)
    parser.add_argument('--model-config', type=Path, required=True)
    parser.add_argument('--measurement-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(follow_factor_models(**vars(args))))


if __name__ == '__main__':
    main()
