import datetime as dt
from pathlib import Path

import pytest

from quant.data import daily_input_quality, refresh
from quant.factors import compute


def configuration(tmp_path: Path) -> tuple[Path, dict]:
    library = tmp_path/'library'
    library.mkdir()
    for name in ('pit_sue8', 'pit_sue8_context_v2'):
        (library/f'{name}.toml').write_text(
            f'id="{name}"\nexpr="{name}"\nfamily="pit_financial"\ndirection=1\nsource_ref="fixture"\n')
    settings = {'library': library.as_posix(), 'selected': 'all',
                'excluded_factors': ['pit_sue8'], 'start': '2026-09-11'}
    config = tmp_path/'refresh.toml'
    config.write_text('etf_config="configs/research/m2_s2_volatility_target.toml"\n'
        f'[factors]\nenabled=true\nlibrary="{library.as_posix()}"\nselected="all"\n'
        'excluded_factors=["pit_sue8"]\nstart="2026-09-11"\n'
        '[quality]\nenabled=true\nbattery_config="configs/factors/battery.toml"\n')
    return config, settings


def test_compute_and_quality_share_explicit_version_selection(tmp_path, monkeypatch):
    config, settings = configuration(tmp_path)
    assert refresh.refresh_factor_selection(settings) == 'pit_sue8_context_v2'
    assert refresh.refresh_factor_selection({'selected': 'all'}) == 'all'
    calls = []
    monkeypatch.setattr(refresh, 'latest_session', lambda **kw: dt.date(2026, 9, 11))
    monkeypatch.setattr(refresh, 'refresh_stocks', lambda **kw: {'new_dates': 0, 'new_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_etfs', lambda **kw: {'new_rows': 0, 'new_bar_rows': 0})
    monkeypatch.setattr(refresh, 'refresh_limits', lambda **kw: 0)
    monkeypatch.setattr(refresh, 'refresh_stock_limits', lambda **kw: {'new_rows': 0})

    def calculate(**kwargs):
        assert kwargs['selected'] == 'pit_sue8_context_v2'
        assert kwargs['start'] == dt.date(2026, 9, 11)
        calls.append('compute')
        return {'years': [], 'factor_count': 1, 'output': 'result'}

    def quality(**kwargs):
        assert calls == ['compute']
        assert kwargs['factors'] == [{'id': 'pit_sue8_context_v2', 'family': 'pit_financial'}]
        calls.append('quality')
        return {'errors': []}

    monkeypatch.setattr(compute, 'run', calculate)
    monkeypatch.setattr(daily_input_quality, 'run_quality', quality)
    result = refresh.run_refresh(to='2026-09-11', data_root=tmp_path, artifact_root=tmp_path,
        config=config, intraday=False)
    assert calls == ['compute', 'quality']
    assert result['factors']['selected'] == 'pit_sue8_context_v2'
    assert result['factors']['excluded_factors'] == ['pit_sue8']


@pytest.mark.parametrize('excluded', ['pit_sue8', ['missing'], ['pit_sue8', 'pit_sue8'],
                                      ['pit_sue8', 'pit_sue8_context_v2']])
def test_invalid_exclusions_fail_before_factor_writes(tmp_path, excluded):
    _, settings = configuration(tmp_path)
    with pytest.raises(ValueError):
        refresh.refresh_factor_selection({**settings, 'excluded_factors': excluded})


def test_excluding_legacy_factor_does_not_change_explicit_library_access(tmp_path):
    from quant.factors.library import load_library

    _, settings = configuration(tmp_path)
    old = load_library(Path(settings['library']), 'pit_sue8')
    assert len(old) == 1 and old[0].id == old[0].expr == 'pit_sue8'
    assert refresh.refresh_factor_selection(settings) == 'pit_sue8_context_v2'


def test_consumer_selection_cannot_restore_excluded_or_unknown_factors(tmp_path):
    _, settings = configuration(tmp_path)
    original = dict(settings)
    scoped = refresh.scoped_factor_settings(settings, ['pit_sue8_context_v2'])
    assert scoped['selected'] == 'pit_sue8_context_v2'
    assert scoped['excluded_factors'] == []
    assert settings == original
    for required in [[], ['pit_sue8'], ['missing'], ['pit_sue8_context_v2'] * 2]:
        with pytest.raises(ValueError):
            refresh.scoped_factor_settings(settings, required)
