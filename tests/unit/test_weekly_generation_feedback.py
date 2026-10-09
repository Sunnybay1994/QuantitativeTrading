import json
from pathlib import Path

from quant.research.weekly_generation_feedback import generation_feedback


def save_week(root: Path, week: str, *, completed=True, expressions=None):
    folder = root / week
    folder.mkdir(parents=True)
    (folder / 'summary.json').write_text(json.dumps({
        'completed': completed, 'accepted_count': 0, 'queued_ids': []}))
    (folder / 'design.toml').write_text('[search]\nfields=["adj_close"]\noperators=["delay"]\n')
    (folder / 'validation.json').write_text(json.dumps([
        {'candidate': {'expression': expr}, 'result': 'rejected', 'reason': 'unregistered'}
        for expr in (expressions or ['rank(delay(adj_close,5))', 'rank(delay(adj_close,20))'])]))
    return folder


def test_diagnoses_invalid_operator_grid_without_calling_it_failed_alpha(tmp_path):
    folder = save_week(tmp_path, '2026-09-28')
    result = generation_feedback(tmp_path, before_week='2026-10-05')
    row = result['weeks'][0]
    assert row['proposed_count'] == 2 and row['queued_count'] == 0
    assert row['unregistered_operator_candidate_counts'] == {'rank': 2}
    assert row['unregistered_field_candidate_counts'] == {}
    assert row['distinct_numeric_stripped_structures'] == 1
    assert row['additional_same_structure_candidates'] == 1
    assert row['validation_reasons'] == {'unregistered': 2}
    assert len(row['sources']) == 3
    assert all(len(s['sha256']) == 64 for s in row['sources'])
    assert 'not battery rejection' in result['meaning']
    assert (folder / 'validation.json').exists()


def test_only_previous_completed_weeks_and_bounded_history(tmp_path):
    for week in ['2026-09-07', '2026-09-14', '2026-09-21', '2026-10-05', '2026-10-12']:
        save_week(tmp_path, week)
    save_week(tmp_path, '2026-09-28', completed=False)
    assert [w['week'] for w in generation_feedback(tmp_path, before_week='2026-10-05', limit=2)['weeks']] == [
        '2026-09-21', '2026-09-14']


def test_missing_or_bad_history_is_reported_without_blocking_generation(tmp_path):
    save_week(tmp_path, '2026-09-21', expressions=['unknown_field/delay(adj_close,5)', 'bad('])
    folder = save_week(tmp_path, '2026-09-28')
    (folder / 'validation.json').write_text('broken')
    result = generation_feedback(tmp_path, before_week='2026-10-05')
    assert len(result['unavailable']) == 1
    assert result['weeks'][0]['unregistered_field_candidate_counts'] == {'unknown_field': 1}
    assert generation_feedback(tmp_path / 'absent', before_week='2026-10-05')['weeks'] == []


def test_final_acceptance_overrides_pre_dedup_status_and_feedback_is_bounded(tmp_path):
    folder = save_week(tmp_path, '2026-09-28')
    (folder / 'summary.json').write_text(json.dumps({'completed': True, 'accepted_count': 2, 'queued_ids': ['a']}))
    (folder / 'accepted.json').write_text(json.dumps([{'id': 'a', 'expr': 'adj_close/delay(adj_close,5)'}]))
    (folder / 'mechanism_deduplication.json').write_text(json.dumps([{'id': 'b'}]))
    result = generation_feedback(tmp_path, before_week='2026-10-05')
    row = result['weeks'][0]
    assert row['locally_accepted_count'] == 1 and row['parameter_variant_rejections'] == 1
    assert row['previously_accepted_examples'][0]['id'] == 'a'
    bounded = generation_feedback(tmp_path, before_week='2026-10-05', maximum_bytes=1000)
    assert len(json.dumps(bounded, ensure_ascii=False).encode('utf-8')) <= 1000
    assert bounded['detail_truncated']
