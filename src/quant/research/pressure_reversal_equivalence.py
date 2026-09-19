"""Label-free rank-equivalence witnesses on common stocks and frozen battery scores.

This diagnoses signal duplication, not predictive value or a new economic mechanism.
No return labels, accounts, queues or factor files are written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.factors.library import load_library
from quant.research.factor_battery_evaluation import score_factor_sections

KEYS = ['trade_date', 'ts_code']
LAYERS = ('source_values', 'raw', 'size_industry_neutral')


def _values(frame: pl.DataFrame) -> pl.DataFrame:
    frame = frame.select(pl.col('trade_date').cast(pl.Date),
                         pl.col('ts_code').cast(pl.String), pl.col('value').cast(pl.Float64))
    if frame.select(pl.struct(KEYS).is_duplicated().any()).item():
        raise ValueError('Duplicate date/symbol input keys')
    if any(frame[c].null_count() for c in KEYS):
        raise ValueError('Null date/symbol input keys')
    return frame.sort(KEYS)


def frame_sha256(frame: pl.DataFrame) -> str:
    """Hash normalized selected input contents, not a claim about unscanned file rows."""
    buffer = io.BytesIO()
    frame.write_ipc(buffer, compression='uncompressed')
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _strict_less(a: float, b: float, atol: float, rtol: float) -> bool:
    return b-a > atol+rtol*max(abs(a), abs(b))


def _order_witness(rows: list[dict], *, orientation: int, atol: float, rtol: float) -> dict | None:
    """Find a stable inversion or exact tie mismatch in O(n log n).

    A difference involving only numerical near-ties remains unresolved. Inversions
    require separated values on both sides; tie mismatches require an exact tie
    in one input and a separated pair in the other input.
    """
    for swapped in (False, True):
        points = [(r['reference']*orientation, r['candidate'], r) if swapped
                  else (r['candidate'], r['reference']*orientation, r) for r in rows]
        points.sort(key=lambda p: (p[0], p[1], p[2]['ts_code']))
        pointer, maximum, tie_start = 0, None, 0
        for index, current in enumerate(points):
            while pointer < index and _strict_less(points[pointer][0], current[0], atol, rtol):
                if maximum is None or points[pointer][1] > maximum[1]:
                    maximum = points[pointer]
                pointer += 1
            chosen = None
            if maximum is not None and _strict_less(current[1], maximum[1], atol, rtol):
                chosen = maximum
            if index and current[0] == points[index-1][0]:
                if _strict_less(points[tie_start][1], current[1], atol, rtol):
                    chosen = points[tie_start]
            else:
                tie_start = index
            if chosen is not None:
                return {'rejects_orientation': 'same' if orientation == 1 else 'reversed',
                        'left': chosen[2], 'right': current[2],
                        'value_atol': atol, 'value_rtol': rtol,
                        'rule': 'stable_inversion_or_exact_tie_with_stable_separation'}
    return None


def compare_rank_sections(candidate: pl.DataFrame, reference: pl.DataFrame, *,
                          expected_dates: list[dt.date], minimum_symbols: int = 100,
                          complete_coverage: bool = False, value_atol: float = 1e-12,
                          value_rtol: float = 1e-10) -> dict:
    """Re-rank each common finite intersection; missing masks never prove novelty.

    ``complete_coverage`` may be true only when the caller supplies its complete
    frozen date universe. Missing/constant/undercovered dates still prevent a
    global same/reversed conclusion. A reliable counterexample can prove different
    before coverage is complete. Reversed means one fixed reversal across dates.
    """
    if minimum_symbols < 100 or value_atol < 0 or not 0 <= value_rtol < 1:
        raise ValueError('Require >=100 common stocks and valid numerical tolerances')
    if not expected_dates or expected_dates != sorted(set(expected_dates)):
        raise ValueError('Require distinct sorted expected dates')
    candidate, reference = _values(candidate), _values(reference)
    expected = set(expected_dates)
    if not set(candidate['trade_date'].to_list()+reference['trade_date'].to_list()) <= expected:
        raise ValueError('Input dates outside the declared comparison scope')
    sections = []
    for date in expected_dates:
        c = candidate.filter(pl.col('trade_date') == date).filter(pl.col('value').is_finite())
        r = reference.filter(pl.col('trade_date') == date).filter(pl.col('value').is_finite())
        paired = c.rename({'value': 'candidate'}).join(
            r.rename({'value': 'reference'}), on=KEYS, validate='1:1').sort('ts_code')
        section = {'trade_date': date.isoformat(), 'candidate_finite': c.height,
                   'reference_finite': r.height, 'common_finite': paired.height,
                   'finite_masks_equal': c.select(KEYS).equals(r.select(KEYS)),
                   'status': 'insufficient', 'reason': 'fewer_than_minimum_common_finite',
                   'rejected_orientations': [], 'witnesses': []}
        if paired.height >= minimum_symbols:
            ranked = paired.with_columns(
                pl.col('candidate').rank('average').alias('candidate_rank'),
                pl.col('reference').rank('average').alias('reference_rank'))
            n = ranked.height
            same = ranked.select((pl.col('candidate_rank') == pl.col('reference_rank')).all()).item()
            reversed_ = ranked.select(
                (pl.col('candidate_rank')+pl.col('reference_rank') == n+1).all()).item()
            witnesses = [w for orientation in (1, -1)
                         if (w := _order_witness(ranked.select('ts_code', 'candidate', 'reference',
                             'candidate_rank', 'reference_rank').to_dicts(), orientation=orientation,
                             atol=value_atol, rtol=value_rtol)) is not None]
            rejected = [w['rejects_orientation'] for w in witnesses]
            section.update({'rejected_orientations': rejected, 'witnesses': witnesses,
                            'candidate_unique_ranks': ranked['candidate_rank'].n_unique(),
                            'reference_unique_ranks': ranked['reference_rank'].n_unique(),
                            'same_rank_rows': ranked.filter(
                                pl.col('candidate_rank') == pl.col('reference_rank')).height,
                            'input_pair_sha256': frame_sha256(paired)})
            if len(rejected) == 2:
                section.update(status='different', reason='both_fixed_orientations_disproved')
            elif same and 'reversed' in rejected:
                section.update(status='same', reason='identical_average_ranks')
            elif reversed_ and 'same' in rejected:
                section.update(status='reversed', reason='identical_reversed_average_ranks')
            else:
                section['reason'] = 'constant_or_numerically_ambiguous_ranks'
        sections.append(section)
    return summarize_sections(sections, expected_dates=expected_dates,
                              complete_coverage=complete_coverage, minimum_symbols=minimum_symbols)


def summarize_sections(sections: list[dict], *, expected_dates: list[dt.date],
                       complete_coverage: bool, minimum_symbols: int = 100) -> dict:
    dates = {date.isoformat() for date in expected_dates}
    observed = {s['trade_date'] for s in sections}
    if len(observed) != len(sections) or not observed <= dates:
        raise ValueError('Duplicate or unexpected comparison dates')
    rejected = set().union(*(set(s['rejected_orientations']) for s in sections))
    reliable = [s for s in sections if s['status'] in ('same', 'reversed', 'different')]
    completed = complete_coverage and observed == dates and len(reliable) == len(dates)
    status = 'different' if rejected == {'same', 'reversed'} else 'insufficient'
    observed_relation = next(iter({'same', 'reversed'}-rejected)) if len(rejected) == 1 else None
    if completed and observed_relation and all(s['status'] == observed_relation for s in sections):
        status = observed_relation
    return {'status': status, 'observed_relation': observed_relation,
            'global_complete_coverage': completed, 'complete_coverage_requested': complete_coverage,
            'expected_dates': len(dates), 'compared_dates': len(sections),
            'reliable_dates': len(reliable), 'minimum_symbols': minimum_symbols,
            'rejected_orientations': sorted(rejected), 'sections': sections,
            'new_economic_mechanism_proven': False,
            'scope': 'Common finite stocks only. Different missing masks are not rank differences. '
                     'same/reversed require complete declared date coverage; different is a counterexample.'}


def battery_scores(values: pl.DataFrame, universe: pl.DataFrame, *, direction: int,
                   settings: dict) -> pl.DataFrame:
    """Exactly the battery's label-free raw/neutral preprocessing on the full frozen universe."""
    scored = score_factor_sections(universe=universe,
        values=_values(values).rename({'ts_code': 'symbol'}), direction=direction, settings=settings)
    return scored.rename({'symbol': 'ts_code'})


def _file_source(path: Path) -> dict:
    with path.open('rb') as handle:
        sha = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha}


def compare_materialized_signals(values: dict[str, pl.DataFrame], scores: dict[str, pl.DataFrame], *,
                                 candidate_ids: list[str], ordered_dates: list[dt.date]) -> list[dict]:
    """Check candidates against each other and saved controls with the same three layers."""
    dates = sorted(ordered_dates)
    result = []
    for candidate in candidate_ids:
        for reference in sorted(set(values)-{candidate}):
            sections = {layer: [] for layer in LAYERS}
            processing = []
            for date in ordered_dates:
                if all(summarize_sections(sections[layer], expected_dates=dates,
                    complete_coverage=False)['status'] == 'different' for layer in LAYERS):
                    break
                for layer in LAYERS:
                    pair = []
                    for name in (candidate, reference):
                        source = values[name] if layer == 'source_values' else scores[name].select(
                            *KEYS, pl.col(layer).alias('value'))
                        pair.append(source.filter(pl.col('trade_date') == date))
                    compared = compare_rank_sections(*pair, expected_dates=[date])['sections'][0]
                    sections[layer].append(compared)
                    if layer != 'source_values' and compared['status'] == 'different' and (
                            sections['source_values'][-1]['status'] in ('same', 'reversed')):
                        processing.append({'trade_date': date.isoformat(), 'variant': layer,
                            'interpretation': 'Preprocessing or availability changed ranks'})
            layers = {layer: summarize_sections(sections[layer], expected_dates=dates,
                       complete_coverage=len(sections[layer]) == len(dates)) for layer in LAYERS}
            result.append({'candidate_id': candidate, 'reference_id': reference,
                'reference_scope': 'same_frozen_candidate_and_control_materialization', 'layers': layers,
                'different_on_all_layers': all(r['status'] == 'different' for r in layers.values()),
                'processing_only_difference_dates': processing, 'new_economic_mechanism_proven': False})
    return result


def scan_library_equivalence(*, candidate_path: Path, universe_path: Path, battery_path: Path,
                             library: Path, factors_root: Path, output: Path,
                             candidate_ids: list[str], candidate_directions: dict[str, int] | None = None,
                             witness_years: tuple[int, ...] = (2014, 2018, 2022, 2026)) -> dict:
    """Scan witnesses first, expand only unresolved pairs, one reference factor at a time.

    Reference hashes cover normalized rows selected for the declared monthly dates;
    file size and mtime are also retained. No unscanned rows are represented as read.
    """
    if output.exists():
        raise FileExistsError(f'Preserve existing scan: {output}')
    values = pl.read_parquet(candidate_path)
    universe = pl.read_parquet(universe_path)
    settings = tomllib.loads(battery_path.read_text(encoding='utf-8'))
    if set(settings['variants']) != {'raw', 'size_industry_neutral'}:
        raise ValueError('Require both frozen battery score variants')
    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError('Require distinct candidate IDs')
    if set(candidate_ids)-set(values['candidate_id'].unique().to_list()):
        raise ValueError('Requested candidate data is missing')
    dates = universe['trade_date'].unique().sort().to_list()
    date_set = set(dates)
    if any(not isinstance(d, dt.date) for d in dates) or not dates:
        raise ValueError('Require frozen monthly universe dates')
    if len({(d.year, d.month) for d in dates}) != len(dates):
        raise ValueError('Bounded scan requires only one declared date per month')
    ordered = [d for y in witness_years for d in dates if d.year == y]
    ordered += [d for d in dates if d.year not in witness_years]
    directions = candidate_directions or {}
    materialized = {c: _values(values.filter(pl.col('candidate_id') == c))
                    for c in values['candidate_id'].unique().sort().to_list()}
    candidates = {c: materialized[c] for c in candidate_ids}
    if any(set(v['trade_date'].to_list())-date_set for v in candidates.values()):
        raise ValueError('Candidate dates outside frozen universe')
    by_date = {d: universe.filter(pl.col('trade_date') == d) for d in dates}
    materialized_scores = {c: battery_scores(v, universe, direction=directions.get(c, 1), settings=settings)
                           for c, v in materialized.items()}
    candidate_scores = {c: materialized_scores[c] for c in candidate_ids}
    definitions = load_library(library)
    output.mkdir(parents=True, exist_ok=False)
    pairs, sources = [], []
    for definition in definitions:
        reference_by_year = {}
        sections = {c: {layer: [] for layer in LAYERS} for c in candidate_ids}
        processing = {c: [] for c in candidate_ids}
        for date in ordered:
            pending = [c for c in candidate_ids if not all(
                summarize_sections(sections[c][layer], expected_dates=dates,
                    complete_coverage=False)['status'] == 'different' for layer in LAYERS)]
            if not pending:
                break
            if date.year not in reference_by_year:
                path = factors_root/definition.id/f'year={date.year}'/'data.parquet'
                if path.is_file():
                    selected = pl.scan_parquet(path).filter(
                        pl.col('trade_date').is_in([d for d in dates if d.year == date.year])).select(
                            'trade_date', 'ts_code', 'value').collect()
                    reference_by_year[date.year] = _values(selected)
                    sources.append({'factor_id': definition.id, 'year': date.year, 'path': str(path),
                        'file_bytes': path.stat().st_size, 'file_mtime_ns': path.stat().st_mtime_ns,
                        'selected_rows': selected.height, 'selected_content_sha256':
                            frame_sha256(reference_by_year[date.year]),
                        'hash_scope': 'normalized rows on the full declared monthly dates in this year'})
                else:
                    reference_by_year[date.year] = pl.DataFrame(
                        schema={'trade_date': pl.Date, 'ts_code': pl.String, 'value': pl.Float64})
                    sources.append({'factor_id': definition.id, 'year': date.year,
                                    'path': str(path), 'missing': True})
            reference = reference_by_year[date.year].filter(pl.col('trade_date') == date)
            ref_scores = battery_scores(reference, by_date[date],
                                        direction=definition.direction, settings=settings)
            for candidate in pending:
                left = candidates[candidate].filter(pl.col('trade_date') == date)
                raw_result = compare_rank_sections(left, reference, expected_dates=[date])
                raw_section = raw_result['sections'][0]
                sections[candidate]['source_values'].append(raw_section)
                for layer in LAYERS[1:]:
                    first = candidate_scores[candidate].filter(pl.col('trade_date') == date).select(
                        *KEYS, pl.col(layer).alias('value'))
                    second = ref_scores.select(*KEYS, pl.col(layer).alias('value'))
                    compared = compare_rank_sections(first, second, expected_dates=[date])['sections'][0]
                    sections[candidate][layer].append(compared)
                    if raw_section['status'] in ('same', 'reversed') and compared['status'] == 'different':
                        processing[candidate].append({'trade_date': date.isoformat(), 'variant': layer,
                            'source_relation': raw_section['status'],
                            'interpretation': 'Preprocessing or availability changed ranks; not a new source ordering witness'})
        for candidate in candidate_ids:
            layer_results = {layer: summarize_sections(sections[candidate][layer], expected_dates=dates,
                complete_coverage=len(sections[candidate][layer]) == len(dates)) for layer in LAYERS}
            pair = {'candidate_id': candidate, 'reference_id': definition.id,
                    'reference_direction': definition.direction,
                    'candidate_direction': directions.get(candidate, 1), 'layers': layer_results,
                    'processing_only_difference_dates': processing[candidate],
                    'different_on_all_layers': all(r['status'] == 'different' for r in layer_results.values()),
                    'new_economic_mechanism_proven': False}
            pairs.append(pair)
        (output/'progress.json').write_text(json.dumps({'references_completed':
            len(pairs)//len(candidate_ids), 'references_total': len(definitions),
            'last_reference': definition.id}), encoding='utf-8')
        print(json.dumps({'reference': definition.id, 'completed': len(pairs)//len(candidate_ids),
                          'total': len(definitions)}), flush=True)
    materialized_pairs = compare_materialized_signals(materialized, materialized_scores,
        candidate_ids=candidate_ids, ordered_dates=ordered)
    result = {'version': 'pressure_reversal_rank_equivalence_v1',
        'candidate_ids': candidate_ids, 'reference_count': len(definitions),
        'expected_dates': [d.isoformat() for d in dates], 'witness_years': list(witness_years),
        'minimum_common_finite_symbols': 100, 'return_labels_read': False,
        'new_economic_mechanism_proven': False,
        'input_sources': [_file_source(p) for p in (candidate_path, universe_path, battery_path)],
        'library_definitions': [{'id': d.id, 'expr': d.expr, 'direction': d.direction,
                                 'family': d.family, 'source_ref': d.source_ref} for d in definitions],
        'reference_sources': sources, 'pairs': pairs, 'materialized_reference_pairs': materialized_pairs,
        'summary': {c: {'references': len(definitions),
            'different_on_all_layers': sum(p['different_on_all_layers'] for p in pairs if p['candidate_id'] == c),
            'unresolved_or_equivalent': [p['reference_id'] for p in pairs
                if p['candidate_id'] == c and not p['different_on_all_layers']]}
            for c in candidate_ids},
        'limitations': ['Rank non-equivalence is not low correlation, novelty, predictive power or admission.',
            'Missing masks alone never disprove equivalence. Empty early periods remain insufficient.',
            'Reverse ordering is the same signal with opposite direction, not a new mechanism.',
            'Source values and raw/neutral scores use separate common finite intersections; '
            'preprocessing-only differences are reported separately.',
            'Reference hashes cover selected monthly input rows, not entire historical parquet files.']}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                                allow_nan=False), encoding='utf-8')
    (output/'report.md').write_text(render_equivalence_report(result), encoding='utf-8')
    return result


def render_equivalence_report(result: dict) -> str:
    """Render measured counts and unresolved evidence without inventing admission results."""
    lines = ['# 压力反转信号排序等价检查', '',
        '仅使用信号值和冻结股票池，不读未来收益，不运行回测。逐日重排双方共同有限股票的平均秩，'
        f"每个可靠截面至少 {result['minimum_common_finite_symbols']} 只。"
        '分别比较原始值、电池raw分数、行业与市值中性分数；后两层沿用score_factor_sections。', '',
        '| 候选 | 库因子数 | 三层均找到差异见证 | 未决或等价 |', '|---|---:|---:|---:|']
    for candidate, row in result['summary'].items():
        lines.append(f"| {candidate} | {row['references']} | {row['different_on_all_layers']} | "
                     f"{len(row['unresolved_or_equivalent'])} |")
    materialized = result['materialized_reference_pairs']
    lines += ['', f"同组候选相互及控制项共 {len(materialized)} 个有向配对，"
        f"其中 {sum(p['different_on_all_layers'] for p in materialized)} 个三层均有差异见证。"
        '两个候选互比的两个方向不是两项独立证据。', '', '## 尚不能判定的比较', '',
        '| 候选 | 参考因子 | 层 | 已检查月数 | 最大共同有限股票数 | 状态 |',
        '|---|---|---|---:|---:|---|']
    for pair in result['pairs']+materialized:
        for layer, evidence in pair['layers'].items():
            if evidence['status'] != 'different':
                maximum = max((s['common_finite'] for s in evidence['sections']), default=0)
                lines.append(f"| {pair['candidate_id']} | {pair['reference_id']} | {layer} | "
                    f"{evidence['compared_dates']} | {maximum} | {evidence['status']} |")
    processing = sum(len(p['processing_only_difference_dates']) for p in result['pairs']+materialized)
    lines += ['', f"原始值同秩/反向同秩而处理后不同的日期-层记录数：{processing}。"
        '这些记录若存在，仅表示预处理或可用性影响，不构成新的原始排序。', '',
        '## 判定范围', '',
        '- different表示有可靠的股票对排序差异，足以否定该输入中的固定同向/反向完全等价。',
        '- same/reversed仅能在声明的完整月末范围均可可靠比较时成立；反向同一排序不是新机制。',
        '- insufficient包含不足100只共同股票、常数及数值近似并列；缺失掩码不同本身不证明差异。',
        '- 差异见证不等于低相关、独立机制、预测能力或准入。所有已有历史仅用于描述性诊断。', '',
        '先读2014、2018、2022、2026月末，只有未决比较继续扩展。参考因子的内容哈希覆盖实际选取的月末行，'
        '并附原文件大小与修改时间；不冒称读过或哈希过未扫描的日频行。'
        'summary.json保留全部因子ID、日期、共同样本数、股票对数值/秩差和输入来源。', '']
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--universe', type=Path, required=True)
    parser.add_argument('--battery', type=Path, required=True)
    parser.add_argument('--candidate-id', action='append', required=True)
    parser.add_argument('--library', type=Path, default=Path('configs/factors/library'))
    parser.add_argument('--factors-root', type=Path, default=Path('data/factors'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = scan_library_equivalence(candidate_path=args.candidates, universe_path=args.universe,
        battery_path=args.battery, library=args.library, factors_root=args.factors_root,
        output=args.output, candidate_ids=args.candidate_id)
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
