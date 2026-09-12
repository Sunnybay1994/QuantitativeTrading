import copy
import json

import pytest

from quant.research.monthly_market_brief import summarize


def record(month, *, forward=True):
    return {'as_of': f'2026-{month:02d}-20', 'target_date': f'2026-{month+1:02d}-20',
        'status': 'scored', 'auto_trade': False, 'affects_positions': False,
        'forward_evidence': forward, 'mode': 'forward' if forward else 'rehearsal',
        'development_test': not forward, 'actual_model': 'fixture-version',
        'series': [{'id': name, 'probability_up': .2, 'total_return': -.1, 'brier': .04}
                   for name in ('a', 'b', 'c')]}


def save(tmp_path, name, row):
    path = tmp_path / f'{name}.json'
    path.write_text(json.dumps(row))
    return path


def test_count_months_not_indices_and_separate_rehearsal_pending(tmp_path):
    pending = record(4)
    pending.update(status='pending', series=[])
    paths = [save(tmp_path, str(i), row) for i, row in enumerate(
        [record(1), record(2), record(3, forward=False), pending])]
    result = summarize(scores=paths, output=tmp_path/'out')
    assert result['forward']['months'] == 2 and result['forward']['index_forecasts'] == 6
    assert result['forward']['mean_brier'] == pytest.approx(.04)
    assert result['forward']['brier_skill_vs_half'] == pytest.approx(.84)
    assert result['rehearsal']['months'] == 1 and len(result['unscored']) == 1
    assert result['affects_positions'] is False


def test_duplicate_signal_month_and_altered_brier_rejected(tmp_path):
    a = record(1)
    b = copy.deepcopy(a)
    b['as_of'] = '2026-01-25'
    paths = [save(tmp_path, 'a', a), save(tmp_path, 'b', b)]
    with pytest.raises(ValueError, match='one issue'):
        summarize(scores=paths, output=tmp_path/'duplicate')
    a['series'][0]['brier'] = 0.
    with pytest.raises(ValueError, match='Brier'):
        summarize(scores=[save(tmp_path, 'bad', a)], output=tmp_path/'altered')


def test_fixture_flag_overrides_claimed_forward_status(tmp_path):
    a = record(1)
    a['development_test'] = True
    result = summarize(scores=[save(tmp_path, 'a', a)], output=tmp_path/'out')
    assert result['forward']['months'] == 0 and result['forward']['mean_brier'] is None
    assert result['rehearsal']['months'] == 1
