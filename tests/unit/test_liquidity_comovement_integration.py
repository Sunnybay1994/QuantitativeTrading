import datetime as dt
import json

import polars as pl
import pytest

from quant.factors.liquidity_comovement import SIGNALS as NAMES, CONTROLS
from pathlib import Path
from polars.testing import assert_frame_equal


def test_n3_recovers_matched_controls_without_rewriting_cached_signals(tmp_path, monkeypatch):
    import hashlib
    from quant.factors import compute
    from tests.unit.test_factor_expressions import prepared
    from tests.unit.test_turnover_reference_integration import sample
    bars, basic, calendar = sample()
    reads = []
    monkeypatch.setattr(compute, 'available_sessions', lambda root, end: tuple(d for d in calendar if d <= end))

    def read(root, config, start, end, sessions):
        reads.append((start, end))
        selected = bars.filter(pl.col('trade_date').is_between(start, end))
        return prepared(selected), selected

    def source(**kwargs):
        frame = bars if kwargs['table'] == 'bar_1d' else basic
        return frame.filter(pl.col('trade_date').is_between(kwargs['start'], kwargs['end']))

    def monthly(**kwargs):
        ends = [a for a,b in zip(calendar,calendar[1:]) if (a.year,a.month)!=(b.year,b.month)
                and kwargs['start'] <= a <= kwargs['end']]
        frame = bars.select('symbol').unique().join(pl.DataFrame({'trade_date':ends},schema={'trade_date':pl.Date}),how='cross')
        return frame.with_columns(*[pl.lit(float(i+1)).alias(name) for i,name in enumerate((*NAMES,*CONTROLS))]), None, None

    monkeypatch.setattr(compute, 'read_factor_inputs', read)
    monkeypatch.setattr(compute, 'read_stock_data', source)
    monkeypatch.setattr(compute, 'read_liquidity_comovement', monthly)
    library = tmp_path/'library'; library.mkdir()
    for name, direction in zip(NAMES, (1,-1,-1)):
        (library/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\ndirection={direction}\n'
            'family="liquidity_comovement_logchange_60m_v1"\nsource_ref="fixture"\n')
    args = dict(data_root=tmp_path/'data',refresh_config=Path('unused'),library=library,selected='all',
                start=dt.date(2020,1,1),end=dt.date(2022,2,15))
    compute.run(**args,artifact_root=tmp_path/'first')

    def shared():
        return {str(p): (p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest())
                for p in (tmp_path/'data').rglob('*') if p.is_file()}

    before = shared()
    compute.run(**args,artifact_root=tmp_path/'second')
    paths = sorted((tmp_path/'first/liquidity_comovement_controls').glob('*.parquet'))
    assert len(paths) == 3
    for path in paths:
        recovered = tmp_path/'second/liquidity_comovement_controls'/path.name
        assert_frame_equal(pl.read_parquet(path),pl.read_parquet(recovered))
        assert tuple(pl.read_parquet(recovered).columns[2:]) == CONTROLS
    assert shared() == before
    count = len(reads)
    compute.run(**args,artifact_root=tmp_path/'second')
    assert len(reads) == count
    damaged = tmp_path/'second/liquidity_comovement_controls/year=2021.parquet'
    damaged.write_bytes(b'interrupted write')
    compute.run(**args,artifact_root=tmp_path/'second')
    assert len(reads) == count+1 and shared() == before
    assert_frame_equal(pl.read_parquet(damaged),pl.read_parquet(tmp_path/'first/liquidity_comovement_controls/year=2021.parquet'))


@pytest.mark.parametrize('chosen_variant', ['raw', 'size_industry_neutral'])
@pytest.mark.parametrize('control_state', ['intact', 'missing', 'damaged'])
@pytest.mark.parametrize('index', [0, 1, 2])
def test_n4_uses_selected_variant_and_cannot_skip_family_failure(tmp_path, monkeypatch, chosen_variant, control_state, index):
    from quant.research import nightly_steps as steps, liquidity_comovement_controls as family
    from quant.data import nightly_genetic_inputs as data
    from quant.data.factor_control_receipts import write_control_receipt
    run, batch, library = tmp_path/'run', tmp_path/'batch', tmp_path/'library'
    name, day = NAMES[index], dt.date(2026, 8, 31)
    for path in (run/'N3', run/'N4', batch/'library', library, tmp_path/'reference', tmp_path/'queue/processing'):
        path.mkdir(parents=True)
    (batch/'library'/f'{name}.toml').write_text(f'id="{name}"\nexpr="{name}"\ndirection=1\n'
        'family="liquidity_comovement_logchange_60m_v1"\nsource_ref="registered_battery:test"\n')
    (library/'ref.toml').write_text('id="ref"\nexpr="close"\ndirection=1\nfamily="other"\nsource_ref="test"\n')
    card = batch/'scorecard.parquet'
    pl.DataFrame({'factor': [name], 'variant': [chosen_variant], 'factor_admitted': [True]}).write_parquet(card)
    (run/'N3/result.json').write_text(json.dumps({'evaluated': 1, 'batch': str(batch), 'scorecard': str(card)}))
    (tmp_path/'reference/battery.toml').write_text('[run]\nas_of=2026-08-31\n')
    keys = pl.DataFrame({'symbol': ['x'], 'trade_date': [day]})
    folder = batch/'evaluation/statistics/factors'/name
    folder.mkdir(parents=True)
    keys.with_columns(pl.lit(1.).alias('raw'), pl.lit(9.).alias('size_industry_neutral')).write_parquet(folder/'monthly_scores.parquet')
    write_control_receipt(batch/'compute/liquidity_comovement_controls/year=2026.parquet',
        keys.with_columns(*[pl.lit(float(i)).alias(n) for i, n in enumerate(CONTROLS)]), start=day, end=day, columns=CONTROLS)
    monkeypatch.setattr(data, 'admitted_controls', lambda *a: (keys, []))
    monkeypatch.setattr(data, 'read_raw_monthly', lambda **kw: keys.with_columns(pl.lit(day).alias('label_exit_date')))
    monkeypatch.setattr(steps, 'incremental_statistics', lambda *a: {'months': 120, 'newey_west_t': 4., 'complete_control_fraction': 1.})
    monkeypatch.setattr(steps, 'maximum_correlation', lambda *a: .1)
    seen = []
    def reject(frame, admitted, evaluate, *, identifier, variant):
        assert identifier == name and variant == chosen_variant
        seen.append(frame['candidate'].item())
        assert all(n in frame.columns for n in CONTROLS)
        return {'passed': False, 'reason': 'fixed_controls_failed'}
    monkeypatch.setattr(family, 'check_liquidity_comovement_controls', reject)
    settings = {'library': str(library), 'reference_scorecard': str(card), 'reference_statistics': str(tmp_path/'reference'),
        'as_of': day, 'history_start': day, 'data_root': str(tmp_path/'data'),
        'rejected_root': str(tmp_path/'rejected'), 'queue': str(tmp_path/'queue')}
    control_path = batch/'compute/liquidity_comovement_controls/year=2026.parquet'
    if control_state == 'missing': control_path.unlink()
    elif control_state == 'damaged': control_path.write_bytes(b'interrupted')
    if control_state != 'intact':
        with pytest.raises(ValueError, match='matched control receipt'):
            steps.admit(settings, run)
        assert not seen
        assert not (run/'N4/admission_scorecard.parquet').exists()
    else:
        result = steps.admit(settings, run)
        assert seen == [1. if chosen_variant == 'raw' else 9.]
        assert result['admitted'] == 0 and result['rejected'] == 1
    assert not (library/'auto'/f'{name}.toml').exists()
