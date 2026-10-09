import datetime as dt
import json

import pytest

from quant.data import refresh_minute_factors as module


def setup(tmp_path, monkeypatch):
    library = tmp_path/'library'
    library.mkdir()
    for name, expr in [('daily', 'close'), ('minute', 'ts_mean(minute_tail_amount, 20)')]:
        (library/f'{name}.toml').write_text(f'id="{name}"\nexpr="{expr}"\nfamily="volume"\n'
            'direction=1\nsource_ref="fixture"\n', encoding='utf-8')
    config = tmp_path/'config.toml'
    config.write_text(f'[factors]\nenabled=true\nlibrary="{library.as_posix()}"\n'
        'selected="all"\nstart="2010-01-01"\n[intraday]\nstock_lookback_days=7\n', encoding='utf-8')
    monkeypatch.setattr(module, 'latest_session', lambda **kw: dt.date(2026, 9, 29))
    return dict(config=config, data_root=tmp_path, artifact_root=tmp_path,
        output=tmp_path/'result', to='2026-09-29')


@pytest.mark.parametrize('collect,errors', [(False, []), (True, []), (True, ['shared access timeout'])])
def test_only_minute_factors_reconciled_and_partial_input_stays_partial(tmp_path, monkeypatch, collect, errors):
    from quant.data import intraday
    args = setup(tmp_path, monkeypatch)
    calls = []

    def fetch(**kw):
        assert kw['stock_from'] == dt.date(2026, 9, 23)
        calls.append('collect')
        return {'errors': errors, 'changed_rows': 48}

    def factors(**kw):
        calls.append('factors')
        assert kw['minute_start'] == dt.date(2026, 9, 23)
        assert kw['settings']['selected'] == 'minute'
        return {'years': [2026], 'factor_count': 1}

    monkeypatch.setattr(intraday, 'refresh_intraday', fetch)
    monkeypatch.setattr(module, 'refresh_factors', factors)
    result = module.run(**args, collect=collect)
    assert calls == (['collect', 'factors'] if collect else ['factors'])
    assert result['status'] == ('partial' if errors else 'computed')
    assert result['factor_ids'] == ['minute']
    assert json.loads((args['output']/'summary.json').read_text())['status'] == result['status']
    with pytest.raises(FileExistsError):
        module.run(**args)


def test_alternate_late_bars_extend_rebuild_and_failure_preserves_receipt(tmp_path, monkeypatch):
    from quant.data import intraday
    args = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(intraday, 'refresh_intraday', lambda **kw:
        {'errors': [], 'stock_alternate_from': '2026-09-10'})

    def failed(**kw):
        assert kw['minute_start'] == dt.date(2026, 9, 10)
        raise ValueError('factor computation failed')

    monkeypatch.setattr(module, 'refresh_factors', failed)
    with pytest.raises(ValueError, match='computation'):
        module.run(**args, collect=True)
    result = json.loads((args['output']/'summary.json').read_text())
    assert result['status'] == 'failed' and result['error_type'] == 'ValueError'
    assert result['rebuild_start'] == '2026-09-10'
