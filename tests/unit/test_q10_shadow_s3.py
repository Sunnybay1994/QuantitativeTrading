import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import tomllib

from quant.research import scheduled_observation as scheduled


def test_actual_scheduled_default_passes_frozen_shadow_to_daily_child(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(scheduled, 'latest_session', lambda **kwargs: kwargs['through'])

    def child(command, **kwargs):
        assert command[2] == 'quant.research.run_daily_observation'
        config = Path(command[command.index('--config') + 1])
        spec = tomllib.loads(config.read_text(encoding='utf-8'))
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
