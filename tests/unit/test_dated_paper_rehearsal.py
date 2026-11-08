import datetime as dt
import json
from types import SimpleNamespace

import pytest

from quant.execution import dated_paper_rehearsal as subject


@pytest.fixture
def setup_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = dt.date(2026, 1, 6)
    config = tmp_path / 'daily.toml'
    config.write_text('auto_trade=false\n' + ''.join(
        f'[{name}]\noutput="formal/{name}"\nconfig="{name}.toml"\n'
        for name in subject.NAMES), encoding='utf-8')
    for name in subject.NAMES:
        (tmp_path / f'{name}.toml').write_text(
            '[paper]\ninception_date=2026-11-30\n'
            '[model]\nforecast_root="forecast_root"\n', encoding='utf-8')
    forecast = tmp_path / 'source/model/forecast'
    forecast.mkdir(parents=True)
    (forecast / 'summary.json').write_text(json.dumps(
        dict(as_of=str(target), rehearsal=False)), encoding='utf-8')
    (forecast / 'predictions.parquet').write_bytes(b'frozen')
    (forecast.parent / 'summary.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(subject.paper_rehearsal, 'resolve_session', lambda **kw: target)

    def q10(**kw):
        return dict(status='complete')

    def a2(**kw):
        assert 'rehearsal' in kw['output'].parts
        assert f'inception_date = {target}' in kw['config_path'].read_text()
        assert kw['as_month_end'] is True
        assert kw['forecast'] == forecast
        return dict(as_of=str(target), rehearsal=True)

    monkeypatch.setattr(subject.paper_rehearsal, 'rehearse_account', q10)
    monkeypatch.setattr(subject.a2, 'run', a2)
    return dict(config=config, target=target, root=tmp_path / 'results', forecast=forecast)


def test_complete_isolated_and_no_second_attempt(setup_run, tmp_path):
    result = subject.run(**setup_run)
    assert result['status'] == 'complete'
    assert result['formal_unchanged']
    assert not (tmp_path / 'formal').exists()
    assert set(result['formal_before']) == set(subject.NAMES)
    assert result['forecast_hashes']['predictions.parquet']
    with pytest.raises(FileExistsError):
        subject.run(**setup_run)


def test_future_target_never_calls_engine(setup_run, monkeypatch):
    monkeypatch.setattr(subject.paper_rehearsal, 'rehearse_account',
                        lambda **kw: pytest.fail('future engine call'))
    setup_run['target'] = dt.date(2099, 11, 27)
    result = subject.run(**setup_run)
    assert result['status'] == 'failed'
    assert 'actual target close' in result['error']
    assert result['accounts'] == {}
    assert not setup_run['root'].exists()


@pytest.mark.parametrize('observed', [
    dt.datetime(2026, 11, 26, 22),
    dt.datetime(2026, 11, 27, 20, 59),
    dt.datetime(2026, 11, 28, 22),
])
def test_default_not_due_or_expired_does_not_reserve_directory(tmp_path, monkeypatch, observed):
    monkeypatch.chdir(tmp_path)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return observed.replace(tzinfo=tz)

    monkeypatch.setattr(subject, 'dt', SimpleNamespace(datetime=Clock))
    # Missing configuration also proves rejection happens before account reads.
    result = subject.run()
    assert result['status'] == 'failed'
    assert result['accounts'] == {}
    assert not subject.ROOT.exists()
    if observed.date() > subject.TARGET:
        assert 'actual target day' in result['error']


def test_missing_same_day_forecast_retained_without_engine(setup_run, monkeypatch):
    (setup_run['forecast'] / 'summary.json').write_text(
        '{"as_of":"2026-01-05","rehearsal":false}', encoding='utf-8')
    monkeypatch.setattr(subject.a2, 'run', lambda **kw: pytest.fail('stale engine call'))
    result = subject.run(**setup_run)
    assert result['status'] == 'failed'
    assert 'same-day' in result['error']
    assert (setup_run['root'] / 'rehearsal' / str(setup_run['target']) / 'receipt.json').exists()


def test_formal_change_invalidates_success(setup_run, tmp_path, monkeypatch):
    def changed(**kw):
        root = tmp_path / 'formal/q10'
        root.mkdir(parents=True, exist_ok=True)
        (root / 'state.json').write_text('changed', encoding='utf-8')
        return dict(status='complete')
    monkeypatch.setattr(subject.paper_rehearsal, 'rehearse_account', changed)
    result = subject.run(**setup_run)
    assert not result['formal_unchanged']
    assert result['status'] == 'failed'


def test_partial_engine_failure_does_not_become_complete(setup_run, monkeypatch):
    monkeypatch.setattr(subject.a2, 'run', lambda **kw: (_ for _ in ()).throw(ValueError('ETF missing')))
    result = subject.run(**setup_run)
    assert result['accounts']['q10']['status'] == 'complete'
    assert result['accounts']['account_30w_top15']['error'] == 'ETF missing'
    assert result['status'] == 'failed'
    assert result['formal_unchanged']
