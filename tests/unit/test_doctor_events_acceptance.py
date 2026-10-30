import csv
import datetime as dt
import json

import polars as pl
import pytest

from quant.reporting.doctor_events_acceptance import evaluate, markdown, _months

TODAY = dt.date(2026, 10, 30)


@pytest.fixture
def event_tree(tmp_path):
    folder = tmp_path/'artifacts/data/events_v0_2026-10-27'
    folder.mkdir(parents=True)
    tables, sample = {}, []
    for family in ('repurchase', 'insider_trading'):
        rows = [dict(announcement_id=str(i), family=family,
            published=dt.date.fromisoformat(month+'-01'), known_at=dt.date.fromisoformat(month+'-01'),
            parse_status='unresolved' if i == 0 else 'parsed')
            for i, month in enumerate(_months(dt.date(2019, 1, 1), TODAY))]
        path = tmp_path/f'data/clean/events/{family}/version=fixture/events.parquet'
        path.parent.mkdir(parents=True)
        pl.DataFrame(rows).write_parquet(path)
        tables[family] = dict(path=str(path.relative_to(tmp_path)), rows=len(rows), unresolved=1,
                              months=[r['published'].strftime('%Y-%m') for r in rows])
        sample.extend(dict(family=family, announcement_id=r['announcement_id'], human_label='match')
                      for r in rows[1:26])
    path = folder/'sample50.csv'
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['family', 'announcement_id', 'human_label'])
        writer.writeheader()
        writer.writerows(sample)
    summary = dict(start='2019-01-01', end=TODAY.isoformat(), stopped=None,
                   tables=tables, sample_path=str(path.relative_to(tmp_path)))
    (folder/'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    ledger = tmp_path/'artifacts/research/llm_ledger/2026-10.jsonl'
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(dict(task='event_extract', usd=.5))+'\n', encoding='utf-8')
    return tmp_path, folder/'summary.json'


def test_actual_contents_are_reported_without_asserting_human_authorship(event_tree):
    root, _ = event_tree
    report = evaluate(root, TODAY)
    assert report['coverage_met'] and report['automated_checks_met']
    assert report['tables']['repurchase']['rows'] == 94
    assert report['tables']['repurchase']['unresolved'] == 1
    assert report['sample']['reported_accuracy'] == 1
    assert report['sample']['human_authorship_verified'] is None
    assert report['ledger']['calls'] == 1 and report['ledger']['usd'] == .5
    assert '2019-01' in '\n'.join(markdown(report))


@pytest.mark.parametrize('problem', ['budget', 'declared_count', 'declared_months', 'future_pit',
                                    'early_pit', 'duplicate', 'unlabeled', 'unknown_sample', 'outside'])
def test_declared_success_cannot_hide_incomplete_or_invalid_evidence(event_tree, problem):
    root, path = event_tree
    summary = json.loads(path.read_text())
    if problem == 'budget': summary['stopped'] = 'budget'
    elif problem == 'declared_count': summary['tables']['repurchase']['rows'] += 1
    elif problem == 'declared_months': summary['tables']['repurchase']['months'] = ['2019-01']
    elif problem == 'outside': summary['tables']['repurchase']['path'] = str(root.parent/'outside.parquet')
    elif problem in ('unlabeled', 'unknown_sample'):
        sample = root/summary['sample_path']
        text = sample.read_text()
        sample.write_text(text.replace('match', '') if problem == 'unlabeled'
                          else text.replace('repurchase,1,', 'repurchase,unknown,'))
    else:
        table = root/summary['tables']['repurchase']['path']
        frame = pl.read_parquet(table)
        if problem == 'duplicate': frame = pl.concat([frame, frame.head(1)])
        else:
            date = TODAY+dt.timedelta(days=1) if problem == 'future_pit' else dt.date(2018, 12, 31)
            frame = frame.with_row_index().with_columns(
                pl.when(pl.col('index') == 0).then(pl.lit(date)).otherwise(pl.col('known_at')).alias('known_at')
            ).drop('index')
        frame.write_parquet(table)
    path.write_text(json.dumps(summary))
    report = evaluate(root, TODAY)
    assert report['errors'] and not report['automated_checks_met']


def test_absent_events_are_not_required_in_a_non_project_fixture(tmp_path):
    assert not evaluate(tmp_path, TODAY)['enabled']


def test_doctor_uses_new_immutable_resume_summary(event_tree):
    root, path = event_tree
    newer = path.parent.with_name(path.parent.name+'_20261030T050000_123456')
    newer.mkdir()
    summary = json.loads(path.read_text())
    summary['stopped'] = 'budget'
    (newer/'summary.json').write_text(json.dumps(summary))
    report = evaluate(root, TODAY)
    assert report['summary'] == str(newer/'summary.json')
    assert not report['coverage_met'] and report['stopped'] == 'budget'


def test_requested_full_dates_do_not_substitute_for_observed_months(event_tree):
    root, path = event_tree
    summary = json.loads(path.read_text())
    table = root/summary['tables']['repurchase']['path']
    frame = pl.read_parquet(table).filter(pl.col('published') >= dt.date(2024, 1, 1))
    frame.write_parquet(table)
    summary['tables']['repurchase'].update(rows=frame.height, unresolved=0,
        months=[d.strftime('%Y-%m') for d in frame['published']])
    path.write_text(json.dumps(summary))
    result = evaluate(root, TODAY)
    assert result['requested_start'] == '2019-01-01' and not result['coverage_met']
    assert '2019-01' in result['tables']['repurchase']['missing_months']


@pytest.mark.parametrize('amount', [0, -1, 'nan', 'inf', 5.001])
def test_invalid_or_over_budget_ledger_cannot_pass(event_tree, amount):
    root, _ = event_tree
    (root/'artifacts/research/llm_ledger/2026-10.jsonl').write_text(
        json.dumps(dict(task='event_extract', usd=amount))+'\n')
    result = evaluate(root, TODAY)
    assert not result['automated_checks_met']
    assert any('USD' in error or 'spend exceeds' in error for error in result['errors'])


@pytest.mark.parametrize('problem', ['start_type', 'reversed_dates', 'ledger_null'])
def test_malformed_artifact_is_a_reported_error_not_a_doctor_crash(event_tree, problem):
    root, path = event_tree
    if problem == 'ledger_null':
        (root/'artifacts/research/llm_ledger/2026-10.jsonl').write_text('null\n')
    else:
        summary = json.loads(path.read_text())
        summary['start'] = None if problem == 'start_type' else '2027-01-01'
        path.write_text(json.dumps(summary))
    result = evaluate(root, TODAY)
    assert result['errors'] and not result['automated_checks_met']


def test_doctor_counts_unsettled_fees_without_claiming_they_are_paid(event_tree):
    root, _ = event_tree
    directory = root/'artifacts/research/llm_ledger/.event_extract_budget'
    directory.mkdir()
    (directory/'2026-10.jsonl').write_text(json.dumps(dict(kind='reserve', request_id='fixture', usd=.02))+'\n')
    result = evaluate(root, TODAY)
    assert result['ledger']['usd'] == .5
    assert result['ledger']['pending_usd'] == .02 and result['ledger']['exposure_usd'] == .52
    assert not result['automated_checks_met']
    assert any('unresolved request charges' in item for item in result['errors'])
