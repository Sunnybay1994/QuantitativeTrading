"""Read-only audit of scheduler recovery history and completed cost NAV keys."""
import argparse
import json
import hashlib
import datetime as dt
from pathlib import Path

import polars as pl


def compare_files(root: Path, baseline: Path) -> dict:
    """Compare captured files; this does not establish that a worker resumed."""
    saved = json.loads(baseline.read_text(encoding='utf-8'))
    results, seen = [], set()
    for row in saved['files']:
        path = (root/row['path']).resolve()
        if not path.is_relative_to(root.resolve()) or path in seen:
            raise ValueError('Baseline contains an outside-root or duplicate path')
        seen.add(path)
        result = {'path': row['path']}
        try:
            before = path.stat()
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = path.stat()
            stable = (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size)
            result.update(status='compared' if stable else 'changed_during_read',
                          content_matches=stable and digest == row['sha256'],
                          mtime_matches=stable and after.st_mtime_ns == row['mtime_ns'],
                          current_sha256=digest)
        except OSError as exc:
            result.update(status='unavailable', error=str(exc), content_matches=False, mtime_matches=False)
        results.append(result)
    return {'checked_at': dt.datetime.now().astimezone().isoformat(), 'baseline': str(baseline),
            'scope': saved.get('verification_scope', 'Only files explicitly named in baseline'),
            'checked_files': len(results), 'content_matches': bool(results) and all(r['content_matches'] for r in results),
            'mtime_matches': bool(results) and all(r['mtime_matches'] for r in results),
            'automatic_resume_verified': False, 'files': results,
            'limitation': 'File equality alone cannot prove resume or exclude an identical-byte rewrite.'}


def scheduler_records(folder: Path) -> list[dict]:
    rows = []
    for path in sorted(folder.glob('*.log')):
        data = path.read_bytes()
        text = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and all(k in row for k in ('batch', 'run', 'state', 'seed', 'updated_at')):
                rows.append({**row, 'source_log': str(path)})
    return sorted(rows, key=lambda row: row['updated_at'])


def check_nav_keys(folder: Path) -> dict:
    """Check row order and cross-year uniqueness, not financial performance."""
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    results = []
    seen = set()
    for row in summary['rows']:
        key = row['variant'], row['cost_multiplier']
        if key in seen:
            raise ValueError('Duplicate completed cost scenario')
        seen.add(key)
        files = sorted((folder/key[0]/f'cost_{key[1]:g}').glob('[0-9][0-9][0-9][0-9]/nav.parquet'))
        if not files:
            raise ValueError('Completed scenario has no NAV files')
        dates = pl.concat([pl.read_parquet(path, columns=['date']) for path in files])['date']
        results.append({'variant': key[0], 'cost_multiplier': key[1], 'files': len(files),
                        'rows': len(dates), 'duplicate_dates': len(dates)-dates.n_unique(),
                        'null_dates': dates.null_count(), 'ordered': dates.is_sorted(),
                        'end_matches_summary': str(dates[-1]) == row['last_date']})
    return {'factor': summary['factor'], 'run': str(folder), 'scenarios': results,
            'passed': bool(results) and all(not r['duplicate_dates'] and not r['null_dates']
                       and r['ordered'] and r['end_matches_summary'] for r in results)}


def audit(root: Path, continuous: Path) -> dict:
    records = scheduler_records(continuous/'scheduler')
    by_batch = {}
    for row in records:
        by_batch.setdefault(row['batch'], []).append(row)
    batches = []
    for batch, history in by_batch.items():
        finished = [row for row in history if row['state'] == 'completed']
        if not finished:
            continue
        last = finished[-1]
        prior = [row for row in history if row['state'] == 'resumable' and row['updated_at'] < last['updated_at']]
        if not prior:
            continue
        context_matches = all(row['run'] == last['run'] and row['seed'] == last['seed'] for row in prior)
        n3 = last.get('steps', {}).get('N3', {}).get('result', {})
        cost_results, errors = [], []
        if n3.get('batch'):
            evaluation = root/Path(n3['batch'])/'evaluation'
            batch_path = evaluation/'costs/batch_summary.json'
            if batch_path.exists():
                saved = json.loads(batch_path.read_text(encoding='utf-8'))
                for folder in saved.get('completed_runs', {}).values():
                    try:
                        cost_results.append(check_nav_keys(root/Path(folder)))
                    except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
                        errors.append({'run': folder, 'error': str(exc)})
            else:
                errors.append({'run': str(batch_path), 'error': 'Missing cost batch summary'})
        batches.append({'batch': batch, 'resume_events': len(prior), 'context_matches': context_matches,
                        'interrupted_logs': [row['source_log'] for row in prior],
                        'completed_log': last['source_log'], 'completed_at': last['updated_at'],
                        'cost_runs': cost_results, 'errors': errors,
                        'final_nav_keys_passed': bool(cost_results) and not errors
                            and all(row['passed'] for row in cost_results)})
    return {'scope': 'historical scheduler recovery and final saved NAV date uniqueness',
            'historical_file_rewrites_verified': False,
            'limitation': 'No before/after file hashes were captured by these historical scheduler logs.',
            'batches': batches, 'recovered_batches': len(batches)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--continuous', type=Path, default=Path('artifacts/research/continuous'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--file-baseline', type=Path, help='Compare existing before/after file evidence only')
    args = parser.parse_args()
    result = (compare_files(args.root.resolve(), args.file_baseline) if args.file_baseline
              else audit(args.root.resolve(), args.root/args.continuous))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    if args.file_baseline:
        print(json.dumps({k: result[k] for k in ('checked_files', 'content_matches', 'mtime_matches', 'automatic_resume_verified')}))
        return
    print(json.dumps({'recovered_batches': result['recovered_batches'], 'batches': [
        {k: b[k] for k in ('batch', 'resume_events', 'context_matches', 'final_nav_keys_passed')}
        for b in result['batches']]}))


if __name__ == '__main__':
    main()
