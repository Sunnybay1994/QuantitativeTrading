import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import tomllib
import pytest

from quant.research import scheduled_observation as scheduled


@pytest.fixture
def isolated_scheduled_default(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2]
    settings = tomllib.loads((source / scheduled.DEFAULT_CONFIG).read_text(encoding='utf-8'))
    paths = {scheduled.DEFAULT_CONFIG, Path(settings['refresh_config']),
             Path(settings['q10_shadow']['config']),
             Path('configs/research/daily_observation_q2_sue_v2_20260912.toml')}
    for relative in paths:
        target = tmp_path / relative
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / relative).read_bytes())
    selection = tmp_path / settings['model']['selection']
    assert selection.resolve().is_relative_to(tmp_path.resolve())
    selection.mkdir(parents=True)
    # This routing test stubs the daily child; it does not train or load a model.
    monkeypatch.chdir(tmp_path)
    return settings


def test_actual_scheduled_default_passes_frozen_shadow_to_daily_child(tmp_path, monkeypatch, isolated_scheduled_default):
    captured = []
    monkeypatch.setattr(scheduled, 'latest_session', lambda **kwargs: kwargs['through'])

    def child(command, **kwargs):
        assert command[2] == 'quant.research.run_daily_observation'
        config = Path(command[command.index('--config') + 1])
        spec = tomllib.loads(config.read_text(encoding='utf-8'))
        assert spec['model'] == isolated_scheduled_default['model']
        assert Path(spec['model']['selection']).resolve().is_relative_to(tmp_path.resolve())
        captured.append(spec['q10_shadow'])
        folder = Path(command[command.index('--output') + 1])
        folder.mkdir()
        (folder / 'summary.json').write_text(json.dumps({
            'as_of': '2026-10-29', 'rehearsal': False, 'status': 'incomplete', 'stages': {},
        }), encoding='utf-8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduled.subprocess, 'run', child)
    scheduled.run(root=tmp_path / 'records',
                  now=dt.datetime(2026, 10, 29, 22, tzinfo=scheduled.SHANGHAI))
    assert len(captured) == 1
    frozen = tomllib.loads(Path('configs/research/daily_observation_q2_sue_v2_20260912.toml')
                          .read_text(encoding='utf-8'))['q10_shadow']
    assert captured[0] == frozen
    shadow = tomllib.loads(Path(captured[0]['config']).read_text(encoding='utf-8'))
    assert shadow['paper']['inception_date'] == captured[0]['inception'] == dt.date(2026, 10, 29)
    assert shadow['paper']['shadow'] is True and shadow['paper']['auto_trade'] is False
    assert shadow['paper']['counts_toward_account_limit'] is False


def test_actual_scheduled_default_still_rejects_missing_model_before_child(tmp_path, monkeypatch, isolated_scheduled_default):
    selection = Path(isolated_scheduled_default['model']['selection'])
    selection.rmdir()
    monkeypatch.setattr(scheduled.subprocess, 'run', lambda *a, **k: pytest.fail('child must not start'))
    with pytest.raises(FileNotFoundError) as caught:
        scheduled.run(root=tmp_path / 'records',
                      now=dt.datetime(2026, 10, 29, 22, tzinfo=scheduled.SHANGHAI))
    assert Path(caught.value.args[0]) == selection
    assert not (tmp_path / 'records').exists()
