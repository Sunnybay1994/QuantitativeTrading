"""Append completed model/strategy variants and regenerate the result leaderboard."""
import argparse
import datetime as dt
import hashlib
import json
import math
import tomllib
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = ROOT/'artifacts/registry/experiments.parquet'
DEFAULT_LEADERBOARD = ROOT/'docs/research/排行榜.md'
COSTS = {0.5: '0_5x', 1.0: '1x', 2.0: '2x'}
METRICS = {'cagr': 'cagr', 'sharpe': 'sharpe', 'mdd': 'max_drawdown',
           'turnover': 'annualized_one_way_turnover'}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _number(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        raise TypeError('Metric must be numeric or missing')
    result = float(value)
    return result if math.isfinite(result) else None


def records_from_run(run: Path) -> list[dict]:
    """Read already measured results; never infer missing costs or conclusions."""
    run = run.resolve()
    if (run/'pipeline_config.json').is_file():
        return factor_records_from_run(run)
    model_report = (run/'cost_metrics.parquet').is_file()
    config = run/('model.toml' if model_report else 'config.toml')
    config_bytes = config.read_bytes()
    settings = tomllib.loads(config_bytes.decode('utf-8'))
    if model_report:
        rows = pl.read_parquet(run/'cost_metrics.parquet').to_dicts()
        comparisons = (pl.read_parquet(run/'benchmark_comparisons.parquet').to_dicts()
                       if (run/'benchmark_comparisons.parquet').exists() else [])
        result = _json(run/'summary.json')
        assessments = {}
        primary_top = settings['portfolio']['primary_top_k']
        for variant in {r['variant'] for r in rows}:
            method, top = variant.rsplit('_top', 1)
            assessment_file = run/method/'assessment.json'
            if not (run/method/'report.md').is_file():
                raise ValueError(f'Missing completed report: {run/method}')
            assessments[variant] = _json(assessment_file)[
                'primary' if int(top) == primary_top else 'sensitivity']
    else:
        result = _json(run/'assessment.json')
        rows, assessments = result['rows'], result['assessments']
        comparisons = result.get('benchmark_comparisons', [])
        if not (run/'report.md').is_file():
            raise ValueError(f'Missing completed report: {run}')
    records = []
    for variant in sorted({r['variant'] for r in rows}):
        selected = [r for r in rows if r['variant'] == variant]
        if len(selected) != 3 or {r['cost_multiplier'] for r in selected} != set(COSTS):
            raise ValueError(f'Require exactly 0.5/1/2x costs: {run}/{variant}')
        assessment = assessments[variant]
        conclusion = assessment['conclusion']
        if not model_report and variant != 'control':
            conclusion = result.get('conclusion', conclusion)
        if conclusion not in ('PAPER_CANDIDATE', 'RESEARCH_ONLY', 'REJECTED'):
            raise ValueError(f'Unknown conclusion: {conclusion}')
        one = next(r for r in selected if r['cost_multiplier'] == 1.)
        report = run/(variant.rsplit('_top', 1)[0]+'/report.md' if model_report else 'report.md')
        record = {'run_path': run.as_posix(), 'variant': variant,
            'experiment_id': settings.get('research', settings).get('id', run.name),
            'config_sha256': hashlib.sha256(config_bytes).hexdigest(),
            'config_path': config.as_posix(), 'report_path': report.as_posix(),
            'source_run': str(result.get('source', result.get('source_run', ''))),
            'start': str(one.get('active_start') or one.get('first_date') or '') or None,
            'end': str(one.get('report_end') or one.get('last_date') or one.get('last') or '') or None,
            'measurement': str(result.get('measurement', one.get('measurement', ''))),
            'conclusion': conclusion, 'strongest_benchmark': assessment.get('strongest_benchmark'),
            'primary': not model_report or int(variant.rsplit('_top', 1)[1]) == primary_top,
            'result_time': dt.datetime.fromtimestamp(report.stat().st_mtime, dt.UTC).isoformat()}
        for row in selected:
            suffix = COSTS[row['cost_multiplier']]
            for name, source in METRICS.items():
                record[f'{name}_{suffix}'] = _number(row.get(source))
            references = [c for c in comparisons if c.get('variant') == variant
                and c.get('cost_multiplier') == row['cost_multiplier']
                and c.get('benchmark_cagr') is not None]
            excess = None
            if references and row.get('cagr') is not None:
                excess = row['cagr']-max(c['benchmark_cagr'] for c in references)
            elif row['cost_multiplier'] == 1.:
                excess = assessment.get('net_cagr_excess')
            record[f'excess_{suffix}'] = _number(excess)
        records.append(record)
    return records


def factor_records_from_run(run: Path) -> list[dict]:
    """Register completed battery rows, retaining missing costs as missing."""
    result = _json(run/'summary.json')
    if result['cost_failures'] or result['pending_external_runs']:
        raise ValueError('Cannot register an unfinished factor battery')
    config = run/'pipeline_config.json'
    report = run/'report.md'
    if not report.is_file():
        raise ValueError('Missing completed factor report')
    scorecard = Path(result['scorecard_path']).resolve()
    if not scorecard.is_relative_to(run.resolve()):
        raise ValueError('Factor scorecard must belong to its run')
    records = []
    for row in pl.read_parquet(scorecard).to_dicts():
        if row['conclusion'] not in ('REJECTED', 'RESEARCH_ONLY', 'PAPER_CANDIDATE'):
            raise ValueError('Unknown factor conclusion')
        record = {'run_path': run.as_posix(), 'variant': f"{row['factor']}/{row['variant']}",
            'experiment_id': row['factor'], 'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
            'config_path': config.as_posix(), 'report_path': report.as_posix(), 'source_run': '',
            'start': None, 'end': None, 'measurement': 'factor_battery_holding_window_costs',
            'conclusion': row['conclusion'], 'strongest_benchmark': None,
            'primary': row['variant'] == 'size_industry_neutral',
            'result_time': dt.datetime.fromtimestamp(report.stat().st_mtime, dt.UTC).isoformat()}
        for cost, suffix in COSTS.items():
            prefix = {0.5: 'cost_0p5', 1.0: 'cost_1', 2.0: 'cost_2'}[cost]
            for metric, source in METRICS.items():
                record[f'{metric}_{suffix}'] = _number(row.get(f'{prefix}_{source}'))
            excess = [_number(value) for key, value in row.items()
                      if key.startswith(prefix+'_') and key.endswith('_cagr_excess')]
            observed = [value for value in excess if value is not None]
            record[f'excess_{suffix}'] = min(observed) if observed else None
        records.append(record)
    return records


def append_records(records: list[dict], registry: Path = DEFAULT_REGISTRY) -> int:
    """Upsert by report run and variant, preserving separate historical runs."""
    if registry.resolve() == DEFAULT_REGISTRY.resolve():
        from quant.reporting.registered_periods import attach
        attach(records, ROOT)
    registry.parent.mkdir(parents=True, exist_ok=True)
    prior = pl.read_parquet(registry).to_dicts() if registry.exists() else []
    merged = {(r['run_path'], r['variant']): r for r in prior}
    for record in records:
        merged[record['run_path'], record['variant']] = record
    ordered = sorted(merged.values(), key=lambda r: (r['run_path'], r['variant']))
    if ordered != prior:
        frame = pl.from_dicts(ordered, infer_schema_length=None)
        for name in (f'{metric}_{suffix}' for metric in (*METRICS, 'excess') for suffix in COSTS.values()):
            frame = frame.with_columns(pl.col(name).cast(pl.Float64))
        temporary = registry.with_suffix('.parquet.tmp')
        frame.write_parquet(temporary)
        temporary.replace(registry)
    return len(ordered)


def register_run(run: Path, registry: Path | None = None,
                 leaderboard: Path | None = None) -> int:
    """Public completion hook for model, strategy and nightly research runners."""
    from quant.reporting.leaderboard import write_leaderboard
    registry = registry or DEFAULT_REGISTRY
    count = append_records(records_from_run(run), registry)
    write_leaderboard(registry, leaderboard or DEFAULT_LEADERBOARD)
    return count


def backfill(root: Path, registry: Path, leaderboard: Path) -> dict:
    """Discover completed supported reports under artifacts only."""
    from quant.reporting.leaderboard import write_leaderboard
    # An artifacts root also contains test fixtures, archived worktrees and raw downloads.
    roots = [root/name for name in ('models', 'research')] if root.name == 'artifacts' else [root]
    candidates = {p.parent for base in roots for p in base.rglob('cost_metrics.parquet')
                  if (p.parent/'model.toml').exists() and (p.parent/'summary.json').exists()}
    for path in (p for base in roots for p in base.rglob('assessment.json')):
        if (path.parent/'config.toml').exists():
            result = _json(path)
            if 'rows' in result and 'assessments' in result:
                candidates.add(path.parent)
    records, failures = [], []
    for run in sorted(candidates):
        try:
            records.extend(records_from_run(run))
        except (ValueError, KeyError, FileNotFoundError) as exc:
            failures.append({'run': str(run), 'error': str(exc)})
    count = append_records(records, registry)
    write_leaderboard(registry, leaderboard)
    return {'discovered_runs': len(candidates), 'registered_variants': count, 'failures': failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path)
    parser.add_argument('--backfill', type=Path)
    parser.add_argument('--registry', type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument('--leaderboard', type=Path, default=DEFAULT_LEADERBOARD)
    args = parser.parse_args()
    if bool(args.run) == bool(args.backfill):
        parser.error('Choose --run or --backfill artifacts root')
    result = (backfill(args.backfill, args.registry, args.leaderboard) if args.backfill else
              {'registered_variants': register_run(args.run, args.registry, args.leaderboard)})
    print(json.dumps(result, ensure_ascii=False))
    if result.get('failures'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
