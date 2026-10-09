"""Bounded saved-target and rejection intersection; never rerun an account."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)


def run(*, cases: Path, runs: list[Path], output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    keys = pl.read_parquet(cases).select('symbol', 'trade_date')
    if keys.is_duplicated().any():
        raise ValueError('Duplicate audit cases')
    sources = {str(cases): digest(cases)}
    inventory, hits, scope = [], [], []
    for root in runs:
        summary = root/'summary.json'
        sources[str(summary)] = digest(summary)
        evidence = json.loads(summary.read_text(encoding='utf-8'))
        if evidence.get('execution_snapshot') != 'factor_battery_20260911_v2':
            raise ValueError('Saved run does not identify the affected execution snapshot')
        files = sorted(set([*root.glob('targets*.parquet'), *root.rglob('rejections.parquet'),
            *root.rglob('orders.parquet')]))
        if not files:
            raise ValueError(f'No saved target/order/rejection records: {root}')
        run_keys = []
        for path in files:
            sources[str(path)] = digest(path)
            frame = pl.read_parquet(path)
            date = 'execution_date' if 'execution_date' in frame.columns else 'date'
            if not {'symbol', date} <= set(frame.columns):
                raise ValueError(f'Unrecognized saved execution schema: {path}')
            kind = 'target' if path.name.startswith('targets') else path.stem
            selected = frame.join(keys, left_on=['symbol', date], right_on=['symbol', 'trade_date'], how='inner')
            for row in selected.iter_rows(named=True):
                hits.append({'run': str(root), 'source_path': str(path), 'kind': kind, **row})
            inventory.append({'run': str(root), 'path': str(path), 'kind': kind, 'rows': frame.height,
                'matched_rows': selected.height, 'first_date': frame[date].min(), 'last_date': frame[date].max()})
            if kind == 'target':
                run_keys.append(frame.select(pl.col(date).alias('trade_date')))
        dates = pl.concat(run_keys).unique() if run_keys else pl.DataFrame(schema={'trade_date': pl.Date})
        scope.append({'run': str(root), 'execution_snapshot': evidence['execution_snapshot'],
            'case_dates_on_saved_target_schedule': keys.join(dates, on='trade_date', how='inner').height,
            'total_cases': keys.height, 'saved_files': len(files)})
    after = {name: digest(Path(name)) for name in sources}
    if sources != after:
        raise ValueError('Saved evidence changed while checking intersection')
    pl.from_dicts(inventory).write_parquet(output/'checked_files.parquet')
    write_json(output/'matched_records.json', hits)
    write_json(output/'source_manifest_before.json', sources)
    write_json(output/'source_manifest_after.json', after)
    result = {'completed_at': dt.datetime.now().isoformat(), 'cases': keys.height,
        'runs': scope, 'files_checked': len(inventory), 'rows_checked': sum(r['rows'] for r in inventory),
        'matched_rows': len(hits), 'matched_cases': len({(r['symbol'], str(r.get('execution_date', r.get('date')))) for r in hits}),
        'matched_reasons': sorted(set(str(r.get('reason', 'target_without_rejection_reason')) for r in hits)),
        'scope_limit': 'Only these saved runs and their target/order/rejection records; not an all-project impact claim',
        'source_hashes_unchanged': True, 'battery_runs': 0, 'account_runs': 0, 'pnl_recalculated': False,
        'next': 'Version only future opening-time inputs/semantics; preserve frozen experiments' if not hits
            else 'Version opening-time correction and pair only the matched decisions before any broader scope'}
    write_json(output/'summary.json', result)
    (output/'report.md').write_text('# 保存执行记录的停牌交集核对\n\n```json\n'+json.dumps(result,
        ensure_ascii=False, indent=2)+'\n```\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--runs', type=Path, nargs='+')
    parser.add_argument('--pair-intersection', type=Path)
    parser.add_argument('--new-snapshot')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.pair_intersection:
        if not args.new_snapshot or args.runs:
            parser.error('Pairing needs --new-snapshot and the saved intersection, without --runs')
        from quant.research.suspension_open_validation import compare
        result = compare(cases=args.cases, intersection=args.pair_intersection,
            new_snapshot=args.new_snapshot, output=args.output)
    else:
        if not args.runs or args.new_snapshot:
            parser.error('Intersection needs --runs; do not specify a new snapshot')
        result = run(cases=args.cases, runs=args.runs, output=args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
