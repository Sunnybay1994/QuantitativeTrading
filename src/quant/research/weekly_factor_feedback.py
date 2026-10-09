"""Report measured weekly-candidate redundancy from completed admission outputs."""
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.research.nightly_steps import dump


def update(config: Path, research_root: Path) -> None:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    root = Path(settings['output_root'])
    for summary_path in root.glob('*/summary.json'):
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        if not summary.get('completed'):
            continue
        ids = set(summary.get('queued_ids', []))
        candidates_path = summary_path.parent/'candidates.json'
        proposed = len(json.loads(candidates_path.read_text(encoding='utf-8'))['candidates']) if candidates_path.exists() else None
        rows: dict[str, dict] = {}
        paths = sorted(research_root.glob('batch_*/????-??-??/N4/admission_scorecard.parquet')) if ids else []
        for path in paths:
            frame = pl.read_parquet(path).filter(pl.col('factor').is_in(sorted(ids)))
            for row in frame.iter_rows(named=True):
                rows.setdefault(row['factor'], {**row, 'evidence': str(path)})
        measured = [row for row in rows.values() if isinstance(row.get('maximum_rank_correlation'), (int, float))
                    and 0 <= row['maximum_rank_correlation'] <= 1]
        passed = sum(row['maximum_rank_correlation'] < .6 for row in measured)
        result = {'proposed_count': proposed, 'candidate_count': len(ids), 'evaluated_count': len(rows),
                  'measured_correlation_count': len(measured), 'correlation_below_0_6_count': passed,
                  'maxcorr_lt_0_6_fraction': passed/len(measured) if measured else None,
                  'evaluation_status': ('not_applicable_no_candidates' if not ids else
                                        'complete' if len(measured) == len(ids) else 'pending'),
                  'factors': list(rows.values())}
        dump(summary_path.parent/'evaluation_feedback.json', result)
        ratio = ('不适用（无有效候选）' if not ids else
                 f'{passed}/{len(measured)}' if measured else '待评估')
        text = (f"# 每周LLM候选 {summary.get('week', summary_path.parent.name)}\n\n"
                f"生成候选 {proposed if proposed is not None else '未知'}；本地校验后候选 {len(ids)}；"
                f"已评估 {len(rows)}；实测相关性 < 0.6：{ratio}。\n\n"
                f"共享账本预算统计：{json.dumps(summary.get('budget', {}), ensure_ascii=False)}。\n\n"
                "相关性比例只统计已有实测值的候选；准入仍以完整因子评估和增量检验为准。\n")
        (summary_path.parent/'report.md').write_text(text, encoding='utf-8')
