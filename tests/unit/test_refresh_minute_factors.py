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
    assert result['error'] == 'factor computation failed'
    assert result['rebuild_start'] == '2026-09-10'


def test_missed_maintenance_bridges_saved_panel_without_disjoint_write(tmp_path, monkeypatch):
    import polars as pl
    from quant.data.factor_panels import write_panel, read_coverage
    args = setup(tmp_path, monkeypatch)
    old_day = dt.date(2026, 9, 10)
    old = pl.DataFrame({'ts_code': ['600000.SH'], 'trade_date': [old_day], 'value': [1.0]})
    write_panel(tmp_path, 'minute', 2026, old, old_day, old_day)

    def factors(**kw):
        low = dt.date.fromisoformat(kw['settings']['start'])
        assert low == kw['minute_start'] == dt.date(2026, 9, 11)
        dates = [low + dt.timedelta(days=n) for n in range((kw['end'] - low).days + 1)]
        incoming = pl.DataFrame({'ts_code': ['600000.SH'] * len(dates),
                                'trade_date': dates, 'value': [2.0] * len(dates)})
        write_panel(tmp_path, 'minute', 2026, incoming, low, kw['end'])
        return {'years': [2026]}

    monkeypatch.setattr(module, 'refresh_factors', factors)
    result = module.run(**args)
    assert result['status'] == 'computed'
    assert result['coverage_bridges'] == [{'panel': 'minute', 'previous_end': str(old_day),
                                          'rebuild_from': '2026-09-11'}]
    assert read_coverage(tmp_path, 'minute', 2026)['start'] == str(old_day)
    saved = pl.read_parquet(tmp_path/'factors/minute/year=2026/data.parquet')
    assert saved.filter(pl.col('trade_date') == old_day)['value'].item() == 1.0
    assert saved.height == 20


def test_bridge_includes_engine_labels_and_does_not_extend_current_panels(tmp_path):
    folder = tmp_path/'factors/forward_returns/year=2026'
    folder.mkdir(parents=True)
    (folder/'data.parquet').touch()
    (folder/'coverage.json').write_text(json.dumps({'start': '2026-01-01', 'end': '2026-10-21'}))
    start, bridges = module.contiguous_rebuild_start(tmp_path, ['minute'],
        dt.date(2026, 10, 30), dt.date(2026, 11, 5))
    assert start == dt.date(2026, 10, 22)
    assert bridges[0]['panel'] == 'forward_returns'
    assert module.contiguous_rebuild_start(tmp_path, ['minute'],
        dt.date(2026, 10, 20), dt.date(2026, 11, 5)) == (dt.date(2026, 10, 20), [])
