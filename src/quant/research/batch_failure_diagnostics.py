"""Read-only, reproducible diagnosis of completed mining batches; never rerun a backtest."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import tomllib

import polars as pl

from quant.research.research_feedback import (
    candidate_diagnostic, search_objective_components, search_selection_summary, summarize,
    training_sample_description,
)
from quant.research.search_sample_diagnostics import batch_diagnostics


def distribution(values: list) -> dict:
    finite = [float(v) for v in values if type(v) in (int, float) and math.isfinite(v)]
    return {
        'available': len(finite), 'missing': len(values) - len(finite),
        'minimum': min(finite) if finite else None,
        'median': statistics.median(finite) if finite else None,
        'maximum': max(finite) if finite else None,
        'nonpositive': sum(v <= 0 for v in finite),
    }


def paired_difference(left: list, right: list) -> dict:
    if len(left) != len(right):
        raise ValueError('Paired comparisons require equal lengths')
    values = [a-b if type(a) in (int, float) and type(b) in (int, float)
              and math.isfinite(a) and math.isfinite(b) else None
              for a, b in zip(left, right, strict=True)]
    return distribution(values)


def _source(path: Path) -> dict:
    with path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def battery_scope(run: Path, result: dict, candidates: list[dict], rows: list[dict],
                  steps: dict, variants: list[str]) -> tuple[dict, dict, list[Path]]:
    """Require the exact frozen battery and explicit N1 provenance for non-GP entries."""
    frozen_root = Path(result['batch'])/'library'
    paths = sorted(frozen_root.glob('*.toml'))
    definitions = {}
    for path in paths:
        definition = tomllib.loads(path.read_text(encoding='utf-8'))
        identifier = definition.get('id')
        if (identifier != path.stem or identifier in definitions
                or any(not isinstance(definition.get(key), str) or not definition[key].strip()
                       for key in ('expr', 'family', 'source_ref'))
                or type(definition.get('direction')) is not int
                or definition['direction'] not in (-1, 1)):
            raise ValueError('Invalid or duplicate frozen N3 definition')
        definitions[identifier] = definition
    if not definitions or set(definitions) != {row['factor'] for row in rows}:
        raise ValueError('Complete scorecard does not match the frozen N3 definition set')
    expected = {(identifier, variant) for identifier in definitions for variant in variants}
    observed = [(row['factor'], row['variant']) for row in rows]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError('Complete scorecard does not contain every frozen factor/variant exactly once')
    if any(result.get(key) != len(definitions) for key in ('candidates', 'evaluated')):
        raise ValueError('N3 candidate/evaluated counts differ from frozen definitions')
    indexed = {row['factor_id']: row for row in candidates}
    if len(indexed) != len(candidates) or not set(indexed) <= set(definitions):
        raise ValueError('Selected N2 candidates are missing or duplicated in the frozen battery')
    for identifier, candidate in indexed.items():
        definition = definitions[identifier]
        if (candidate.get('expression') != definition['expr']
                or candidate.get('direction') != definition['direction']
                or Path(definition['source_ref']).resolve() != (run/'N2/search.json').resolve()):
            raise ValueError('N2 candidate differs from its frozen N3 definition/source')
    queued = sorted(set(definitions)-set(indexed))
    queue_sources = []
    if queued:
        n1 = steps.get('N1', {})
        if not n1.get('ok') or n1.get('result', {}).get('queued_candidates') != len(queued):
            raise ValueError('N1 queue count does not establish every additional frozen candidate')
        for identifier in queued:
            path = run/'candidates'/f'{identifier}.toml'
            original = tomllib.loads(path.read_text(encoding='utf-8'))
            if original != definitions[identifier]:
                raise ValueError('Queued candidate differs from its frozen N3 definition/source')
            if Path(original['source_ref']).resolve() == (run/'N2/search.json').resolve():
                raise ValueError('Additional candidate claims N2 provenance but is absent from N2')
            paths.append(path)
            queue_sources.append({'factor': identifier, 'family': original['family'],
                                  'source_ref': original['source_ref'],
                                  'training_comparison': 'not_applicable'})
    return ({'mode': 'mixed_battery' if queued else 'N2_only',
             'complete_battery': summarize(rows),
             'N2_search': summarize([row for row in rows if row['factor'] in indexed]),
             'fixed_queue': summarize([row for row in rows if row['factor'] in queued]),
             'training_comparison_candidates': len(candidates), 'queued_sources': queue_sources},
            definitions, paths)


def aggregate(rows: list[dict], diagnostics: list[dict], candidates: list[dict],
              inputs: dict, settings: dict) -> dict:
    """Count variant rows separately from the selected, dependent candidate expressions."""
    if not rows or len({(r['factor'], r['variant']) for r in rows}) != len(rows):
        raise ValueError('Require nonempty unique factor/variant rows')
    raw = [d for d in diagnostics if d.get('same_score_preprocessing')
           and (d.get('sample_comparison') or {}).get('status') == 'complete']
    stages = {'reported_training': [], 'saved_sample_battery_labels': [],
              'full_pool_search_dates': [], 'full_pool_before_search': [],
              'full_pool_after_search': [], 'full_history_raw': []}
    for d in raw:
        sample = d['sample_comparison']
        stages['reported_training'].append(d['train_direction_adjusted']['mean_ic'])
        stages['saved_sample_battery_labels'].append(
            sample['search_keys_with_battery_scores']['battery_labels_battery_coverage']['mean_ic'])
        for stage, window in [('full_pool_search_dates', 'search_dates'),
                              ('full_pool_before_search', 'before_search'),
                              ('full_pool_after_search', 'after_search')]:
            stages[stage].append(sample['all_battery_stocks_by_window'][window]['mean_ic'])
        stages['full_history_raw'].append(d['full_history']['mean_ic'])
    comparisons = {
        'sample_reproduction_minus_reported_training':
            paired_difference(stages['saved_sample_battery_labels'], stages['reported_training']),
        'full_pool_same_window_minus_sample':
            paired_difference(stages['full_pool_search_dates'], stages['saved_sample_battery_labels']),
        'before_search_minus_search_dates':
            paired_difference(stages['full_pool_before_search'], stages['full_pool_search_dates']),
    }
    fields = ['months', 'mean_ic', 'icir', 'newey_west_t', 'yearly_positive_fraction',
              'long_short_sharpe', 'bh_adjusted_p', 'cost_1_sharpe', 'cost_1_max_drawdown',
              'cost_1_annualized_one_way_turnover', 'cost_1_mean_invested_fraction',
              'mean_top_target_turnover', 'mean_monthly_rank_autocorrelation']
    costs = {}
    for tier in ('0p5', '1', '2'):
        costs[tier] = {
            'cagr': distribution([r.get(f'cost_{tier}_cagr') for r in rows]),
            'all_market_ew_excess': distribution([
                r.get(f'cost_{tier}_all_market_equal_weight_cagr_excess') for r in rows]),
            'csi800_ew_excess': distribution([
                r.get(f'cost_{tier}_csi800_equal_weight_cagr_excess') for r in rows]),
            'etf_reference_excess': distribution([
                r.get(f'cost_{tier}_510300_total_return_reference_cagr_excess') for r in rows]),
        }
    favored = set(inputs.get('favored_terminals', []))
    favored_counts = []
    components = []
    for c in candidates:
        terminals = {n.id for n in ast.walk(ast.parse(c['terminal_expression'], mode='eval'))
                     if isinstance(n, ast.Name) and n.id.startswith('gp_')}
        favored_counts.append(len(terminals & favored))
        components.append({'factor': c['factor_id'], **search_objective_components(c)})
    benchmark_columns = [k for r in rows for k in r
                         if k.startswith('cost_') and k.endswith('_cagr_excess')]
    return {
        **summarize(rows),
        'count_unit': 'factor_variant; candidates and variants are not independent observations',
        'statistical_failure_counts_are_nonexclusive': True,
        'by_variant': {v: summarize([r for r in rows if r['variant'] == v])
                       for v in sorted({r['variant'] for r in rows})},
        'costs_complete': sum(r.get('costs_complete') is True for r in rows),
        'admitted_variants': sum(r.get('factor_admitted') is True for r in rows),
        'metrics': {key: distribution([r.get(key) for r in rows]) for key in fields},
        'cost_tiers': costs,
        'paired_cagr_change_0p5_to_1': paired_difference(
            [r.get('cost_1_cagr') for r in rows], [r.get('cost_0p5_cagr') for r in rows]),
        'cost_interpretation': 'Replay sensitivity includes changed fills, sizing and cash paths; not an isolated fee attribution. No zero-cost replay was requested.',
        'missing_benchmark_columns': {k: sum(r.get(k) is None for r in rows)
                                      for k in sorted(set(benchmark_columns))
                                      if any(r.get(k) is None for r in rows)},
        'aligned_raw_candidates': len(raw),
        'raw_ic_stages': {k: distribution(v) for k, v in stages.items()},
        'paired_ic_differences': comparisons,
        'label_disagreement_rows_candidate_summed': sum(
            d['sample_comparison']['label_difference_over_1e_12_rows'] for d in raw),
        'comparison_note': 'Same signal-date window does not guarantee identical valid months. Full-universe preprocessing and eligible coverage differ. Paired differences are descriptive, not additive causal attribution.',
        'decay_mean_ic': {str(h): distribution([
            (r.get('decay') or {}).get(str(h), {}).get('mean_ic') for r in rows])
                         for h in settings.get('decay_sessions', [])},
        'training_objectives': dict(Counter(c.get('search_objective', 'pooled_mean_ic_v1')
                                           for c in candidates)),
        'objective_components': components,
        'search_selection': search_selection_summary(candidates),
        'scalar_objective_candidates': sum(c['search_objective'] != 'predictive_priority_v2' for c in components),
        'correlation_penalty_exceeds_signal_candidates': sum(
            c['correlation_penalty'] > c['signal_component'] for c in components
            if c['correlation_penalty'] is not None and c['signal_component'] is not None),
        'declared_family': inputs.get('family'),
        'candidates_using_favored_family_terminals':
            sum(n > 0 for n in favored_counts) if favored else None,
        'family_note': 'The run family biases generation; a family label does not prove every selected expression uses that family.',
        'frozen_admission': settings['admission'],
        'fdr_is_required_for_admission': settings['multiple_testing']['admission_requires_fdr'],
        'independent_validation': False,
    }


def diagnose_run(run: Path) -> dict:
    summary_path = run/'summary.json'
    saved = json.loads(summary_path.read_text(encoding='utf-8'))
    n3 = saved.get('steps', {}).get('N3', {})
    n4 = saved.get('steps', {}).get('N4', {})
    n4_result = n4.get('result', {})
    admission = {'status': 'not_confirmed_complete'}
    if n4.get('ok') and all(type(n4_result.get(key)) is int for key in ('admitted', 'rejected')):
        admission = {'status': 'complete', 'admitted': n4_result['admitted'],
                     'rejected': n4_result['rejected']}
    if not n3.get('ok') or not n3.get('result', {}).get('scorecard'):
        raise ValueError(f'Battery not completed: {run}')
    scorecard = Path(n3['result']['scorecard'])
    search_path, input_path = run/'N2/search.json', run/'N2/input_summary.json'
    search = json.loads(search_path.read_text(encoding='utf-8'))
    inputs = json.loads(input_path.read_text(encoding='utf-8'))
    settings_path = scorecard.parent/'battery.toml'
    settings = tomllib.loads(settings_path.read_text(encoding='utf-8'))
    rows = pl.read_parquet(scorecard).to_dicts()
    candidates = search['candidates']
    indexed = {c['factor_id']: c for c in candidates}
    scope, definitions, definition_paths = battery_scope(run, n3['result'], candidates, rows,
                                                        saved.get('steps', {}), settings['variants'])
    statistics_root = scorecard.parent.parent/'statistics'
    samples = batch_diagnostics(run, statistics_root)
    diagnostics = []
    for row in rows:
        if row['factor'] in indexed:
            diagnostic = candidate_diagnostic(row, indexed[row['factor']], inputs)
            diagnostic['origin'] = 'N2_search'
        else:
            diagnostic = candidate_diagnostic(row, {'search_objective': 'not_applicable'}, {})
            diagnostic.update(origin='fixed_queue', training_comparison_status='not_applicable',
                training_sample=None, search_selection=None,
                source_ref=definitions[row['factor']]['source_ref'],
                sample_comparison={'status': 'not_applicable', 'reason': 'No N2 training source'})
        diagnostics.append(diagnostic)
    for d in diagnostics:
        if d['same_score_preprocessing']:
            d['sample_comparison'] = samples.get(d['factor'])
    source_paths = [summary_path, scorecard, settings_path, search_path, input_path,
                    run/'N2/monthly_sample.parquet', *definition_paths]
    source_paths.extend(sorted((statistics_root/'inputs').glob('*/monthly_labels.parquet')))
    for factor in sorted(indexed):
        source_paths.extend(statistics_root/'factors'/factor/name
                            for name in ('monthly_scores.parquet', 'monthly_ic.parquet'))
    return {
        'run': str(run), 'as_of': str(settings['run']['as_of']),
        'search_trials': len(search['trials']),
        'trial_error_counts': dict(Counter(c['error'] for c in search['trials'] if c.get('error'))),
        'training_sample': training_sample_description(inputs),
        'admission_observation': admission,
        'summary': {**aggregate(rows, diagnostics, candidates, inputs, settings), 'population_scope': scope},
        'candidate_diagnostics': diagnostics,
        'sources': [_source(p) for p in source_paths],
    }


def render_report(result: dict) -> str:
    lines = ['# 已完成挖掘批次诊断', '',
        '本报告由已保存的搜索、评分表、月度分数和收益标签自动计算，不重新搜索或回测。'
        '所有中位数均是所列候选/变体的描述性统计，不是组合收益。', '',
        '| 批次 | 候选/变体 | 统计通过 | 1×超额通过 | 1×等权超额中位数 | 1×实际换手中位数 |',
        '|---|---:|---:|---:|---:|---:|']
    for b in result['batches']:
        s = b['summary']
        excess = s['cost_tiers']['1']['all_market_ew_excess']['median']
        turnover = s['metrics']['cost_1_annualized_one_way_turnover']['median']
        lines.append(f"| {Path(b['run']).parent.name} | {s['candidates']}/{s['variants']} | "
                     f"{s['statistical_pass']} | {s['cost_excess_pass']} | "
                     f"{_format(excess, 100)} pp | {_format(turnover)}× |")
    for b in result['batches']:
        s = b['summary']
        scope = s.get('population_scope', {})
        search_count = scope.get('training_comparison_candidates', s['candidates'])
        lines += ['', f"## {Path(b['run']).parent.name}", '',
            f"搜索目标：`{', '.join(s['training_objectives'])}`；"
            f"共评估 {b['search_trials']} 个表达式，选出 {search_count} 个 N2 候选。"
            f"训练信号日期 {b['training_sample']['sample_first_signal']}—"
            f"{b['training_sample']['sample_last_signal']}，评分表截至 {b['as_of']}。", '',
            '### 筛选结果与未通过原因', '',
            '统计失败次数（可重叠）：' + '；'.join(
                f'{k}={v}/{s["variants"]}' for k, v in s['statistical_failure_counts'].items()) + '。',
            f"三档成本齐全 {s['costs_complete']}/{s['variants']}；"
            f"完整基准 {s['benchmark_complete']}/{s['variants']}。"
            '基准缺口单列，不用缺失值冒充零收益；准入使用的全市场等权超额可见于下表。', '',
            '| 成本 | 等权超额最小值 | 中位数 | 最大值 | 有效/非正 |',
            '|---|---:|---:|---:|---:|']
        for tier, label in [('0p5', '0.5×'), ('1', '1×'), ('2', '2×')]:
            d = s['cost_tiers'][tier]['all_market_ew_excess']
            lines.append(f"| {label} | {_format(d['minimum'], 100)} pp | "
                         f"{_format(d['median'], 100)} pp | {_format(d['maximum'], 100)} pp | "
                         f"{d['available']}/{d['nonpositive']} |")
        if scope.get('mode') == 'mixed_battery':
            lines += ['', f"混合电池完整分母：{s['candidates']} 因子/{s['variants']} 变体；"
                f"N2 搜索 {scope['N2_search']['candidates']} 因子/{scope['N2_search']['variants']} 变体，"
                f"N1 固定队列 {scope['fixed_queue']['candidates']} 因子/{scope['fixed_queue']['variants']} 变体。"
                '仅 N2 来源参加训练差异比较；固定队列明确记为 not_applicable。']
        admission = b.get('admission_observation', {})
        if admission.get('status') == 'complete':
            lines += ['', f"最终 N4 已完成：{admission['admitted']} 个因子入库、"
                      f"{admission['rejected']} 个拒绝；统计通过变体数不等于最终入库因子数。"]
        else:
            lines += ['', '本诊断保存范围未确认 N4 完成，不能据此认定零入库。']
        lines += ['', '### 训练与全历史的描述性比较', '',
            '| 原始分数候选的月度 RankIC | 中位数 | 有效/非正 |', '|---|---:|---:|']
        stage_labels = {'reported_training': '方向调整后的合池训练IC（描述统计，不是最弱组目标）',
            'saved_sample_battery_labels': '相同股票样本，电池分数与标签',
            'full_pool_search_dates': '相同日期窗口，全股票池',
            'full_pool_before_search': '搜索日期之前，全股票池',
            'full_pool_after_search': '搜索日期之后，全股票池（已观察历史）',
            'full_history_raw': '全历史，全股票池'}
        for key, label in stage_labels.items():
            d = s['raw_ic_stages'][key]
            lines.append(f"| {label} | {_format(d['median'], decimals=5)} | "
                         f"{d['available']}/{d['nonpositive']} |")
        lines += ['', f"相同样本的有限标签差异行数（逐候选累计）="
            f"{s['label_disagreement_rows_candidate_summed']}；"
            f"完成原始分数样本对齐 {s['aligned_raw_candidates']} 个候选。"
            '同日期窗口仍可能有不同有效月份，股票覆盖及全池预处理也不同；'
            '这些差额不构成因果分解，不能直接归因为过拟合或时间衰减。', '',
            '### 搜索目标与准入条件', '']
        for objective, selection in s.get('search_selection', {}).items():
            primary = _format(selection['primary']['median'], decimals=5)
            correlation = _format(selection['secondary_correlation']['median'], decimals=5)
            if objective == 'predictive_priority_v2':
                lines += [f"`{objective}`：主指标为三个训练组中最弱组的方向调整IC，"
                          f"中位数={primary}；次级最大相关性中位数={correlation}。"
                          '相关性只在已注册的 IC 接近区间内参与排序，不构造标量适应度，'
                          '也不从主指标扣除相关性或复杂度惩罚。'
                          f"保存的选择资格：有效 {selection['eligible']}、无效 {selection['ineligible']}、"
                          f"未提供 {selection['eligibility_unavailable']}；选择资格不等于因子准入。"]
            else:
                label = '三个训练组中最弱组的方向调整IC' if objective == 'cross_stock_min_ic_v1' else '合池IC绝对值'
                lines += [f"`{objective}` 的适应度IC项为{label}，中位数={primary}；"
                          f"最大相关性中位数={correlation}。"]
        if not s.get('search_selection'):
            lines += ['旧标量目标的适应度IC项：跨股票目标使用最弱组方向调整IC，普通搜索使用合池IC绝对值；'
                      '本批中位数='
                      f"{_format(distribution([c['signal_component'] for c in s['objective_components']])['median'], decimals=5)}。"]
        scalar_count = s.get('scalar_objective_candidates', s['candidates'])
        if scalar_count:
            lines += [f"{s['correlation_penalty_exceeds_signal_candidates']}/{scalar_count} 个旧标量目标候选的"
                      '相关性惩罚大于适应度中的IC项；低相关可提高相对排序，但不能证明有预测力。']
        lines += ['上表的 reported_training 是合池描述统计，不能充当最弱组优化目标。'
                  '搜索目标不直接包含全历史稳定性、可执行收益或成本。']
        if s['declared_family'] is not None:
            lines += [f"本批名义家族 `{s['declared_family']}`。家族名是生成偏好，不是候选经济机制鉴定。"]
        if s['candidates_using_favored_family_terminals'] is not None:
            lines += [f"包含偏好家族终端的候选数={s['candidates_using_favored_family_terminals']}。"]
        lines += [
            'BH 调整 p 值仅按冻结设置报告；本批是否要求 FDR 准入：'
            f"{s['fdr_is_required_for_admission']}。不把未启用的条件说成拒绝原因。"]
    lines += ['', '## 解释边界与后续', '',
        '已验证的是历史样本表现差异和所列筛选结果。使用分组目标时，三组股票都进入训练目标；'
        '搜索期后的既有历史已被查看，不能称为独立样本外验证。不同批次可能同时改变股票样本和搜索目标，'
        '不能从批间中位数差异推出新目标的因果效果。', '',
        '成本档的差额包含成交、仓位及现金路径变化，不能全归为手续费；未运行零成本反事实。'
        '现有证据支持优先补充不同经济来源的输入、保持已注册跨股票试验一次停止条件，'
        '不支持调低门槛或继续追加种子挽救同一假设。', '',
        '完整逐候选、衰减、统计门槛、缺失项和源文件 SHA256 见 `diagnosis.json`。', '']
    return '\n'.join(lines)


def _format(value: float | None, scale: float = 1, decimals: int = 2) -> str:
    return '未知' if value is None else f'{value*scale:.{decimals}f}'


def run_diagnosis(runs: list[Path], output: Path) -> dict:
    if not runs or len(set(p.resolve() for p in runs)) != len(runs):
        raise ValueError('Provide distinct completed runs')
    if output.exists():
        raise FileExistsError(f'Preserve existing diagnosis: {output}')
    result = {'version': 'saved_batch_failure_diagnosis_v1',
              'independent_validation': False, 'reran_search_or_backtest': False,
              'generator': _source(Path(__file__)),
              'batches': [diagnose_run(p) for p in runs]}
    output.mkdir(parents=True, exist_ok=False)
    (output/'diagnosis.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (output/'report.md').write_text(render_report(result), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run_diagnosis(args.run, args.output)
    print(json.dumps({'output': str(args.output), 'batches': len(result['batches'])}))


if __name__ == '__main__':
    main()
