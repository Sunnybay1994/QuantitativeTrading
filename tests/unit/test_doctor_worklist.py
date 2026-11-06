import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from quant.reporting.doctor_worklist import collect, markdown, REQUIRED

CLOCK = dt.datetime(2026, 11, 6, 12, tzinfo=ZoneInfo('Asia/Shanghai'))


def _json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def _tree(root):
    (root / 'docs').mkdir()
    (root / 'docs/工作清单_20261102.md').write_text('worklist', encoding='utf-8')
    rows = []
    for experiment, variants in REQUIRED.items():
        run = root / 'artifacts/research' / experiment
        run.mkdir(parents=True)
        config = run / 'config.toml'
        config.write_text(f'id="{experiment}"\n', encoding='utf-8')
        (run / 'report.md').write_text('machine report', encoding='utf-8')
        _json(run / 'assessment.json', {'auto_trade': False,
            'rows': [{'variant': variant, 'cost_multiplier': cost, 'cagr': .1, 'max_drawdown': .1}
                     for variant in variants for cost in (0.5, 1., 2.)],
            'assessments': {variant: {'conclusion': 'REJECTED'} for variant in variants}})
        for variant in variants:
            rows.append({'experiment_id': experiment, 'variant': variant, 'level': 'strategy',
                'result_time': '2026-11-04T12:00:00+00:00', 'conclusion': 'REJECTED',
                'run_path': str(run), 'config_path': str(config), 'report_path': str(run / 'report.md'),
                'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
                **{f'{metric}_{cost}': .1 for metric in ('cagr', 'mdd') for cost in ('0_5x', '1x', '2x')}})
    _write_registry(root, rows)
    return rows


def _write_registry(root, rows):
    path = root / 'artifacts/registry/experiments.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path)


def test_required_results_do_not_advance_calendar_or_full_acceptance(tmp_path):
    _tree(tmp_path)
    result = collect(tmp_path, CLOCK)
    assert len(result['registry']['verified_results']) == 6
    assert result['registry']['missing_required'] == []
    assert not result['midterm_date_reached'] and not result['final_date_reached']
    assert result['structured']['published_table_count'] == 0
    assert '不宣告清单完成' in '\n'.join(markdown(result))
    assert 'accepted' not in result


@pytest.mark.parametrize('change', ['duplicate', 'future', 'factor', 'config', 'costs', 'conclusion', 'metrics'])
def test_unverified_rows_cannot_inflate_result_count(tmp_path, change):
    rows = _tree(tmp_path)
    first = rows[0]
    expected = 5
    if change == 'duplicate':
        rows.append(dict(first))
    elif change == 'future':
        first['result_time'] = '2026-11-16T00:00:00+00:00'
    elif change == 'factor':
        first['level'] = 'factor'
    elif change == 'metrics':
        first['cagr_2x'] = 99.
    elif change == 'config':
        Path(first['config_path']).write_text('id="changed"', encoding='utf-8')
        expected = 4  # Both variants share the original frozen config.
    else:
        path = Path(first['run_path']) / 'assessment.json'
        assessment = json.loads(path.read_text())
        if change == 'costs':
            assessment['rows'] = [r for r in assessment['rows']
                if not (r['variant'] == first['variant'] and r['cost_multiplier'] == 2.)]
        else:
            assessment['assessments'][first['variant']]['conclusion'] = 'PAPER_CANDIDATE'
        _json(path, assessment)
    _write_registry(tmp_path, rows)
    result = collect(tmp_path, CLOCK)
    assert len(result['registry']['verified_results']) == expected
    assert result['registry']['issues'] and result['registry']['missing_required']


def _table(root, published=True, year=2019):
    folder = root / 'artifacts/data/structured_events_fixture'
    folder.mkdir(parents=True)
    payload = ('id="structured_events_v1"\nauto_trade=false\nevaluate_factors=false\n'
        'start=2019-01-01\nend=2026-11-04\n[tables.repurchase]\ndate_field="ann_date"\n')
    (folder / 'config.toml').write_text(payload, encoding='utf-8')
    clean = root / 'data/clean/repurchase/snapshot=fixture'
    record = {'clean_path': str(clean), 'rows': 8, 'first_date': f'{year}-01-02',
        'last_date': '2026-01-02', 'symbols': 1, 'years': list(range(year, 2027)),
        'date_field': 'ann_date', 'null_available_at': 0}
    _json(folder / 'summary.json', {'config_sha256': hashlib.sha256((folder / 'config.toml').read_bytes()).hexdigest(),
        'tables': {'repurchase': record}})
    if published:
        _json(clean / 'summary.json', record)
        # The fixture is evidence available before CLOCK, independent of wall time.
        # Future-publication tests explicitly move this timestamp after CLOCK.
        os.utime(clean / 'summary.json', (CLOCK.timestamp()-1, CLOCK.timestamp()-1))
        data = clean / 'year=all/data.parquet'
        data.parent.mkdir()
        pl.DataFrame({'ts_code': ['000001.SZ'] * (2027-year),
            'ann_date': [f'{y}0102' for y in range(year, 2027)],
            'available_at': [CLOCK-dt.timedelta(days=1)] * (2027-year),
            'observed_at': [CLOCK-dt.timedelta(days=1)] * (2027-year)}).write_parquet(data)


def test_only_published_actual_tables_count_and_trial_report_is_excluded(tmp_path):
    _tree(tmp_path)
    _table(tmp_path)
    _json(tmp_path / 'data/clean/report_rc/snapshot=trial/summary.json', {'rows': 5})
    result = collect(tmp_path, CLOCK)['structured']
    assert result['published_table_count'] == 1
    assert result['tables_2019_to_registered_end'] == ['repurchase']
    assert result['tables']['repurchase']['rows'] == 8


@pytest.mark.parametrize('mode', ['missing', 'missing_data', 'wrong_rows', 'late_start'])
def test_table_receipt_alone_or_wrong_coverage_does_not_satisfy_date_count(tmp_path, mode):
    _tree(tmp_path)
    _table(tmp_path, published=mode != 'missing', year=2020 if mode == 'late_start' else 2019)
    if mode == 'missing_data':
        (tmp_path / 'data/clean/repurchase/snapshot=fixture/year=all/data.parquet').unlink()
    result = collect(tmp_path, CLOCK)['structured']
    if mode != 'wrong_rows':
        assert result['tables_2019_to_registered_end'] == []
    if mode == 'wrong_rows':
        path = tmp_path / 'data/clean/repurchase/snapshot=fixture/year=all/data.parquet'
        pl.read_parquet(path).head(7).write_parquet(path)
        result = collect(tmp_path, CLOCK)['structured']
        assert result['tables_2019_to_registered_end'] == []
    if mode in ('missing', 'missing_data'):
        assert result['published_table_count'] == 0 and result['issues']


def test_old_doctor_fixtures_without_this_worklist_are_unchanged(tmp_path):
    assert collect(tmp_path, CLOCK) == {'enabled': False}
    assert markdown({'enabled': False}) == []


def test_future_publication_is_not_present_evidence(tmp_path):
    _tree(tmp_path)
    _table(tmp_path)
    path = tmp_path / 'data/clean/repurchase/snapshot=fixture/summary.json'
    os.utime(path, (CLOCK.timestamp()+1, CLOCK.timestamp()+1))
    result = collect(tmp_path, CLOCK)['structured']
    assert result['published_table_count'] == 0
    assert result['issues']


def test_unfinished_recovery_excluded_from_date_coverage_count(tmp_path):
    _tree(tmp_path)
    _table(tmp_path)
    path = tmp_path / 'artifacts/data/structured_events_fixture/summary.json'
    receipt = json.loads(path.read_text())
    receipt['symbol_splits'] = {'repurchase/all/2024-02-19/2024-02-19': {'complete': False}}
    _json(path, receipt)
    result = collect(tmp_path, CLOCK)['structured']
    assert result['published_table_count'] == 1
    assert result['tables_2019_to_registered_end'] == []


def test_calendar_date_alone_never_completes_worklist(tmp_path):
    _tree(tmp_path)
    result = collect(tmp_path, CLOCK.replace(month=12, day=1))
    assert result['midterm_date_reached'] and result['final_date_reached']
    assert not result['structured']['published_table_count']
    assert result['credibility'].get('issue')
    assert '不宣告清单完成' in '\n'.join(markdown(result))


def test_existing_doctor_includes_worklist_section(tmp_path, monkeypatch):
    from quant.reporting.doctor import collect as doctor, render_markdown
    _tree(tmp_path)
    monkeypatch.setattr('quant.reporting.doctor._git_facts', lambda root: {
        'dirty': 0, 'days_since_commit': 0, 'root_scratch_py': 0, 'git_ok': True})
    result = doctor(root=tmp_path, now=CLOCK, tasks=[])
    assert len(result['worklist']['registry']['verified_results']) == 6
    assert '工作清单 2026-11-02' in render_markdown(result)
