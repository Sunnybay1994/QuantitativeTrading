"""Compare saved text scores with frozen, partial semantic constraints."""
import argparse
import hashlib
import json
from pathlib import Path

import polars as pl


def check_calibration(*, run: Path, checks: Path, output: Path) -> dict:
    expected = json.loads(checks.read_text(encoding='utf-8'))
    report = json.loads((run/'run.json').read_text(encoding='utf-8'))
    if report['dry_run'] or report['prompt_version'] != expected['prompt_version']:
        raise ValueError('Calibration requires actual results under the frozen prompt version')
    scores = pl.read_parquet(run/'scores.parquet')
    if scores['input_id'].is_duplicated().any():
        raise ValueError('Calibration records must have unique input IDs')
    records = {row['input_id']: row for row in scores.iter_rows(named=True)}
    cases = expected['cases']
    if not cases or len({case['input_id'] for case in cases}) != len(cases) or any(not case['checks'] for case in cases):
        raise ValueError('Expected calibration cases must be nonempty and unique')
    rows = []
    for case in cases:
        actual = records.get(case['input_id'])
        if actual and hashlib.sha256(actual['reason_text'].encode()).hexdigest() != case['reason_sha256']:
            raise ValueError('Calibration reason differs from the frozen expectation')
        for dimension, allowed in case['checks'].items():
            complete = actual is not None and actual['result'] == 'success'
            value = None
            if complete:
                assert actual is not None
                value = {'status': actual[f'{dimension}_status'], 'score': actual[f'text_{dimension}']}
            rows.append({'input_id': case['input_id'], 'dimension': dimension,
                'result': actual['result'] if actual else 'missing_record', 'observed': value,
                'allowed': allowed, 'passed': value in allowed if complete else None,
                'reference_excerpt': case['reference_excerpt'], 'rationale': case['rationale']})
    passed = sum(row['passed'] is True for row in rows)
    failed = sum(row['passed'] is False for row in rows)
    ungraded = sum(row['passed'] is None for row in rows)
    result = {'purpose': 'partial_semantic_constraints_only', 'expectation_origin': expected['origin'],
        'scope': expected['scope'], 'cases': len(cases), 'dimension_checks': len(rows),
        'passed': passed, 'failed': failed, 'ungraded': ungraded,
        'observed_pass_fraction': passed/(passed+failed) if passed+failed else None,
        'completion_fraction': (passed+failed)/len(rows) if rows else 0,
        'run': str(run), 'checks': str(checks), 'model_calls': 0, 'rows': rows}
    output.mkdir(parents=True, exist_ok=False)
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--checks', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check_calibration(run=args.run, checks=args.checks, output=args.output)
    print(json.dumps({key: value for key, value in result.items() if key != 'rows'}, ensure_ascii=False))
    if result['failed'] or result['ungraded']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
