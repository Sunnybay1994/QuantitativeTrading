import datetime as dt
import json
from pathlib import Path
import tomllib
import os
import subprocess
import sys
import time

import polars as pl
import pytest

from quant.execution import q10_paper as q10
from quant.research.model_training_models import buffered_model_targets


def test_kernel_lock_conflict_preserves_holder_and_canonical_identity(tmp_path, paper_config, monkeypatch):
    output = tmp_path/'canonical/account'
    ready, stop = tmp_path/'ready', tmp_path/'stop'
    worker = '''import datetime as dt,sys,time
from pathlib import Path
from quant.execution import q10_paper as q
def hold(**kw):
 Path(sys.argv[3]).write_text('held')
 while not Path(sys.argv[4]).exists(): time.sleep(.02)
 return {}
q._run=hold
q.run(config_path=Path(sys.argv[1]),output=Path(sys.argv[2]),end=dt.date(2026,9,13))
'''
    child = subprocess.Popen([sys.executable, '-c', worker, str(paper_config), str(output),
                              str(ready), str(stop)],
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        deadline = time.monotonic()+15
        while not ready.exists():
            assert child.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.02)
        lock = output.parent/'.account.writer.lock'
        before = lock.stat().st_size
        monkeypatch.setattr(q10, '_run', lambda **kw: pytest.fail('Contender acquired held lock'))
        for alias in (output, output.parent/'unused/../account'):
            with pytest.raises(OSError):
                q10.run(config_path=paper_config, output=alias, end=dt.date(2026, 9, 13))
            assert child.poll() is None
            assert lock.exists() and lock.stat().st_size == before
        assert not output.exists()
    finally:
        stop.write_text('release own fixture')
        child.wait(timeout=10)
    assert child.returncode == 0
    monkeypatch.setattr(q10, '_run', lambda **kw: {'reacquired': True})
    assert q10.run(config_path=paper_config, output=output, end=dt.date(2026, 9, 13))['reacquired']


@pytest.fixture
def paper_config(tmp_path):
    """Keep frozen account/cost settings; all artifact inputs belong to this test."""
    payload = q10.DEFAULT_CONFIG.read_text(encoding='utf-8')
    spec = tomllib.loads(payload)
    assessment = tmp_path/'inputs/assessment.json'
    assessment.parent.mkdir()
    assessment.write_text(json.dumps({'assessments': {'budgeted': {
        'conclusion': 'PAPER_CANDIDATE', 'checks': {'synthetic_fixture_admission': True}}}}),
        encoding='utf-8')
    replacements = [(spec['research']['assessment'], assessment)]
    for section, field in [('research', 'predictions'), ('model', 'selection'), ('model', 'forecast_root')]:
        path = tmp_path/'inputs'/field
        path.mkdir()
        replacements.append((spec[section][field], path))
    for old, new in replacements:
        assert json.dumps(old) in payload
        payload = payload.replace(json.dumps(old), json.dumps(new.as_posix()))
    config = tmp_path/'paper_fixture.toml'
    config.write_text(payload, encoding='utf-8')
    return config


def test_targets_match_frozen_buffer_then_apply_actual_holdings_budget():
    date, following = dt.date(2026, 9, 30), dt.date(2026, 10, 8)
    prior = dt.date(2026, 8, 31)
    symbols = [f'{600000+i}.SH' for i in range(100)]
    old = pl.DataFrame({'symbol': symbols, 'trade_date': [prior]*100,
                        'lightgbm': [float(i) for i in range(100)]})
    new = pl.DataFrame({'symbol': symbols, 'trade_date': [date]*100,
                        'lightgbm': [float((i+30)%100) for i in range(100)]})
    expected = buffered_model_targets(pl.concat([old, new]), method='lightgbm',
        sessions=(prior, dt.date(2026, 9, 1), date, following), start=dt.date(2026, 9, 1),
        end=following, top_k=50, minimum_symbols=100, retention_multiplier=1.5)
    state = {'date': str(date), 'previous_targets': symbols[50:],
             'nav': [{'equity': 1000000.}],
             'holdings': {s: {'quantity': 2000, 'mark_price': 10.} for s in symbols[50:]}}
    actual = q10.signal_targets(new.rename({'lightgbm': 'prediction'}), state, following)
    expected = expected.filter(pl.col('as_of') == date)
    assert actual.select('symbol', 'weight').equals(expected.select('symbol', 'weight'))
    assert len(state['previous_targets']) == 50
    assert actual['weight'].sum() == pytest.approx(1.)


def test_first_signal_empty_account_and_invalid_pool():
    date = dt.date(2026, 9, 30)
    scores = pl.DataFrame({'symbol': [str(i) for i in range(100)],
        'trade_date': [date]*100, 'prediction': [float(i) for i in range(100)]})
    state = {'date': str(date), 'previous_targets': [], 'holdings': {}, 'nav': [{'equity': 1e6}]}
    targets = q10.signal_targets(scores, state, dt.date(2026, 10, 8))
    assert targets.height == 50
    assert targets['weight'].sum() == pytest.approx(1.)
    with pytest.raises(ValueError, match='minimum 100'):
        q10.signal_targets(scores.head(50), state, dt.date(2026, 10, 8))


def test_shadow_size_band_changes_weights_and_skips_paper_gate(monkeypatch):
    date, following = dt.date(2026, 10, 30), dt.date(2026, 11, 2)
    scores = pl.DataFrame({'symbol': [f'{600000+i}.SH' for i in range(100)],
        'trade_date': [date]*100, 'prediction': [float(i) for i in range(100)]})
    state = {'date': str(date), 'previous_targets': [], 'holdings': {}, 'nav': [{'equity': 1e6}]}
    plain = q10.signal_targets(scores, dict(state), following)

    def hook(**kwargs):
        assert kwargs['score_column'] == 'score'

        def transform(batch, _state):
            first = batch.sort('symbol')['symbol'][0]
            return batch.with_columns(
                pl.when(pl.col('symbol') == first).then(pl.lit(0.30))
                .when(pl.col('weight') > 0).then(pl.lit(0.004))
                .otherwise(pl.lit(0.0)).alias('weight')), {'size_band': 0.5}
        return transform, None, None

    monkeypatch.setattr(
        'quant.research.run_constrained_portfolio.prepare_constrained_hook', hook)
    config = {'paper': {'name': 'q10_size_neutral_shadow', 'statistics': 'unused',
                        'size_on_policy': {'top_k': 50}}}
    shadow = q10.size_neutral_targets(scores, dict(state), following, config)
    assert shadow['strategy'].unique().to_list() == ['q10_size_neutral_shadow']
    assert float(shadow['weight'].max()) == pytest.approx(0.30)
    assert not shadow.select('symbol', 'weight').equals(plain.select('symbol', 'weight'))


def test_shadow_config_stays_out_of_the_candidate_count():
    import tomllib
    paper = tomllib.loads(Path('configs/paper/q10_size_neutral_shadow_20261027.toml').read_text(encoding='utf-8'))
    assert paper['paper']['shadow'] is True
    assert paper['paper']['counts_toward_account_limit'] is False
    assert paper['paper']['auto_trade'] is False
    assert paper['paper']['construction'] == 'b0.5_k50_size_on'
    assert paper['paper']['inception_date'] == dt.date(2026, 10, 29)
    daily_cfg = tomllib.loads(Path('configs/research/daily_observation_q2_sue_v2_20260912.toml').read_text(encoding='utf-8'))
    assert daily_cfg['q10_shadow']['inception'] == dt.date(2026, 10, 29)
    roadmap = Path('项目实施路线图.md').read_text(encoding='utf-8')
    assert '真金启动须：两份真实月报（≥2026-12-01）+ 影子账户同步运行 + 两账户均未触发 attention；金额与时点由用户确认。' in roadmap


def test_open_account_idempotent_and_controls(tmp_path, monkeypatch, paper_config):
    monkeypatch.setattr(q10, 'read_stock_paper_calendar', lambda _: pl.DataFrame({
        'date': [dt.date(2026, 9, 14)], 'is_open': [True]}))
    first = q10.run(config_path=paper_config, data_root=tmp_path/'data', output=tmp_path, end=dt.date(2026, 9, 13))
    second = q10.run(config_path=paper_config, data_root=tmp_path/'data', output=tmp_path, end=dt.date(2026, 9, 13), halt=True)
    assert first['equity'] == second['equity'] == 1e6
    assert second['positions'] == second['reference_orders'] == 0
    assert second['controls']['halt']
    state = json.loads((tmp_path/'2026-09-13/state.json').read_text())
    assert len(state['nav']) == 1
    assert not state['auto_trade']


def test_rehearsal_forecast_rejected(tmp_path):
    folder = tmp_path/'model/forecast'
    folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps({'as_of': '2026-09-30', 'rehearsal': True}))
    (folder.parent/'summary.json').write_text('{}')
    with pytest.raises(ValueError, match='prospective'):
        q10.load_forecast(folder, dt.date(2026, 9, 30), Path('selection'), dt.date(2026, 10, 8))


def test_forced_month_end_cannot_write_production(tmp_path, paper_config):
    with pytest.raises(ValueError, match='isolated rehearsal'):
        q10.run(config_path=paper_config, output=tmp_path/'production',
                end=dt.date(2026, 9, 29), as_month_end=True)
    assert not (tmp_path/'production').exists()


def test_rehearsal_forces_signal_without_mutating_production(tmp_path, monkeypatch, paper_config):
    import hashlib
    from quant.execution.paper_rehearsal import rehearse_account
    from tests.unit.test_stock_paper import fixture_inputs

    inputs = fixture_inputs()[0]
    monkeypatch.setattr(q10, 'read_stock_paper_calendar', lambda _: inputs.calendar)
    monkeypatch.setattr(q10, 'read_stock_paper_inputs', lambda *args: inputs)
    account = tmp_path/'account'
    date = dt.date(2026, 9, 29)  # Ordinary session; only rehearsal should create targets.
    q10.run(config_path=paper_config, output=account, end=date)
    before = {str(p.relative_to(account)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in account.rglob('*') if p.is_file()}
    forecast = tmp_path/'forecast'
    forecast.mkdir()
    (forecast/'summary.json').write_text(json.dumps({'as_of': str(date)}))
    scores = pl.DataFrame({'symbol': [f'{600000+i}.SH' for i in range(100)],
        'trade_date': [date]*100, 'prediction': [float(100-i) for i in range(100)]})
    monkeypatch.setattr(q10, 'load_forecast', lambda *args: scores)
    receipt = rehearse_account(account=account, config=paper_config, end=date,
                               data_root=tmp_path/'data', forecast=forecast)
    assert receipt['status'] == 'complete'
    assert receipt['pushed'] is False
    assert receipt['result']['reference_orders'] == 50
    output = Path(receipt['output'])
    state = json.loads((output/str(date)/'state.json').read_text())
    assert state['conclusion'] == 'REHEARSAL'
    assert state['counts_toward_account_limit'] is False
    assert {name: hashlib.sha256((account/name).read_bytes()).hexdigest()
            for name in before} == before
    assert json.loads((account/'latest_summary.json').read_text())['reference_orders'] == 0


def test_month_end_orders_execute_next_session_and_restart(tmp_path, monkeypatch, paper_config):
    from tests.unit.test_stock_paper import fixture_inputs

    inputs = fixture_inputs()[0]
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 2, 22, tzinfo=tz)
    monkeypatch.setattr(q10.dt, 'datetime', Clock)
    monkeypatch.setattr(q10, 'read_stock_paper_calendar', lambda _: inputs.calendar)
    monkeypatch.setattr(q10, 'read_stock_paper_inputs', lambda *args: inputs)
    date = dt.date(2026, 9, 30)
    scores = pl.DataFrame({'symbol': [f'{600000+i}.SH' for i in range(100)],
        'trade_date': [date]*100, 'prediction': [float(100-i) for i in range(100)]})
    forecast = tmp_path/'forecast'
    forecast.mkdir()
    (forecast/'summary.json').write_text(json.dumps({'as_of': str(date)}))
    monkeypatch.setattr(q10, 'load_forecast', lambda *args: scores)
    output = tmp_path/'account'
    first = q10.run(config_path=paper_config, data_root=tmp_path/'data', output=output, end=date, forecast=forecast)
    assert first['positions'] == 0
    assert first['reference_orders'] == 50
    next_day = q10.run(config_path=paper_config, data_root=tmp_path/'data', output=output, end=dt.date(2026, 10, 1), forecast=forecast)
    assert next_day['positions'] == 50
    fills = pl.read_csv(output/'2026-10-01/fills.csv')
    assert fills.height == 50
    assert (fills['quantity'] % 100 == 0).all()
    repeated = q10.run(config_path=paper_config, data_root=tmp_path/'data', output=output, end=dt.date(2026, 10, 1), forecast=forecast)
    assert repeated['equity'] == next_day['equity']


@pytest.mark.parametrize('bad', ['conclusion', 'check'])
def test_fixture_admission_is_still_enforced_before_account_creation(tmp_path, paper_config, bad):
    config = tomllib.loads(paper_config.read_text(encoding='utf-8'))
    path = Path(config['research']['assessment'])
    value = json.loads(path.read_text(encoding='utf-8'))
    assessment = value['assessments']['budgeted']
    if bad == 'conclusion':
        assessment['conclusion'] = 'RESEARCH_ONLY'
    else:
        assessment['checks']['synthetic_fixture_admission'] = False
    path.write_text(json.dumps(value), encoding='utf-8')
    output = tmp_path/'rejected_account'
    with pytest.raises(ValueError, match='registered admission criteria'):
        q10.run(config_path=paper_config, data_root=tmp_path/'data', output=output,
                end=dt.date(2026,9,13))
    assert not output.exists()
