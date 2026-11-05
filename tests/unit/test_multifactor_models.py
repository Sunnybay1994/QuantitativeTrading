import datetime as dt
import json
from pathlib import Path
import re
import tomllib

import polars as pl
import pytest

from quant.reporting import multifactor_models as module


@pytest.fixture
def saved_run(tmp_path, monkeypatch):
    from quant.reporting import experiment_registry
    monkeypatch.setenv('QUANT_REGISTRY_ROOT',str(tmp_path/'registry/experiments.parquet'))
    monkeypatch.setattr(experiment_registry, 'DEFAULT_LEADERBOARD', tmp_path/'leaderboard.md')
    run = tmp_path/'saved'
    run.mkdir()
    text = Path('configs/models/p4_annual_walk_forward_20260911.toml').read_text(encoding='utf-8')
    text = re.sub(r'(?m)^test_start = .*$', 'test_start = 2024-01-01', text)
    text = re.sub(r'(?m)^test_end = .*$', 'test_end = 2024-01-06', text)
    (run/'model.toml').write_text(text, encoding='utf-8')
    model = tomllib.loads(text)
    (run/'battery.toml').write_text('[run]\nas_of = 2024-01-06\n[portfolio]\ninitial_cash = 100.0\n')
    dates = [dt.date(2024, 1, i) for i in range(1, 7)]
    rows = []
    for method in model['models']['methods']:
        for top in (50, 100):
            for cost, entry in ((.5, 0), (1., 2), (2., 3)):
                values = [1.]*entry + [1-.01*cost]*(6-entry)
                market = [0.]*entry + [80.]*(6-entry)
                if method == 'lightgbm':
                    market, values = [0.]*6, [1.]*6
                folder = run/f'{method}_top{top}'/f'cost_{cost:g}'/'2024'
                folder.mkdir(parents=True)
                pl.DataFrame({'date': dates, 'unit_nav': values,
                    'equity': [v*100 for v in values], 'market_value': market,
                    'position_count': [int(v > 0) for v in market]}).write_parquet(folder/'nav.parquet')
                trades = (pl.DataFrame({'date': [dates[entry]], 'symbol': ['TEST'], 'notional': [80.]})
                          if method != 'lightgbm' else pl.DataFrame(
                              schema={'date': pl.Date, 'symbol': pl.String, 'notional': pl.Float64}))
                trades.write_parquet(folder/'trades.parquet')
                rows.append({'variant': f'{method}_top{top}', 'cost_multiplier': cost})
    (run/'summary.json').write_text(json.dumps({'factor': model['research']['id'], 'rows': rows}))
    windows = tmp_path/'stress.toml'
    windows.write_text('[[cycle_validation.stress_windows]]\nname = "test"\nstart = 2024-01-03\nend = 2024-01-06\n')
    measurement = tmp_path/'measurement.toml'
    measurement.write_text('index_version = "fixture"\nindex_codes = ["H00300.CSI", "H00906.CSI", "H00985.CSI"]\n'
                           f'stress_windows_config = {json.dumps(windows.as_posix())}\n')
    monkeypatch.setattr(module, 'available_sessions', lambda *args: dates)
    names = {'H00300.CSI': '沪深300全收益', 'H00906.CSI': '中证800全收益', 'H00985.CSI': '中证全指全收益'}

    def index(**kwargs):
        assert kwargs['required_return_type'] == 'total_return'
        return pl.DataFrame({'trade_date': dates, 'daily_return': [.1, .0, .02, .0, .0, .0],
            'index_name': [names[kwargs['index_code']]]*6, 'return_type': ['total_return']*6})
    monkeypatch.setattr(module, 'read_index_benchmark', index)
    return dict(run=run, output=tmp_path/'report', data_root=tmp_path/'data', measurement_config=measurement)


def test_saved_reports_all_cost_windows_first_index_return_and_zero_holdings(saved_run):
    before = {str(p): p.read_bytes() for p in saved_run['run'].rglob('*') if p.is_file()}
    result = module.report_models(**saved_run)
    metrics = pl.read_parquet(saved_run['output']/'cost_metrics.parquet')
    one = metrics.filter((pl.col('variant') == 'equal_z_top50') & (pl.col('cost_multiplier') == 1.)).row(0, named=True)
    assert metrics.height == 18 and one['sessions'] == 4
    assert one['annualized_one_way_turnover'] == pytest.approx(.4*252/4)
    starts = metrics.filter(pl.col('variant') == 'equal_z_top50')['active_start'].to_list()
    assert starts == [dt.date(2024, 1, d) for d in (1, 3, 4)]
    comparisons = pl.read_parquet(saved_run['output']/'benchmark_comparisons.parquet')
    half = comparisons.filter(pl.col('cost_multiplier') == .5)
    assert half['benchmark_total_return'][0] == pytest.approx(1.1*1.02-1)
    primary = result['models']['equal_z']['primary']
    assert primary['benchmarks'][0]['total_return'] == pytest.approx(.02)
    assert result['models']['lightgbm']['primary']['active_start'] is None
    assert result['conclusions']['lightgbm'] == 'RESEARCH_ONLY'
    assert '无股票持仓' in (saved_run['output']/'lightgbm/report.md').read_text(encoding='utf-8')
    assert result['measurement']['admission_thresholds_changed'] is False
    assert '全收益' in primary['strongest_benchmark'] and 'equal_weight' not in primary['strongest_benchmark']
    assert before == {str(p): p.read_bytes() for p in saved_run['run'].rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):
        module.report_models(**saved_run)


def test_missing_index_day_rejected_before_output(saved_run, monkeypatch):
    original = module.read_index_benchmark
    monkeypatch.setattr(module, 'read_index_benchmark', lambda **kw: original(**kw).slice(1))
    with pytest.raises(ValueError, match='complete model session grid'):
        module.report_models(**saved_run)
    assert not saved_run['output'].exists()


def test_account_baselines_no_longer_accepted(saved_run):
    with pytest.raises(ValueError, match='account benchmarks'):
        module.report_models(**saved_run, benchmarks=Path('old_account_run'))


def test_cli_uses_explicit_measurement_config(saved_run, monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['report', '--run', str(saved_run['run']), '--output', str(saved_run['output']),
        '--data-root', str(saved_run['data_root']), '--measurement-config', str(saved_run['measurement_config'])])
    module.main()
    assert json.loads(capsys.readouterr().out)['lightgbm'] == 'RESEARCH_ONLY'
    registry=saved_run['output'].parent/'registry/experiments.parquet'
    rows=pl.read_parquet(registry)
    assert rows.height==6
    assert {Path(value).resolve() for value in rows['run_path']}=={saved_run['output'].resolve()}



def test_all_models_cash_writes_empty_comparison_table(saved_run, monkeypatch):
    original = module.load_cost_history
    def cash(*args):
        nav, _ = original(*args)
        return nav.with_columns(pl.lit(0.).alias('market_value'), pl.lit(1.).alias('unit_nav')), \
            pl.DataFrame(schema={'date': pl.Date, 'symbol': pl.String, 'notional': pl.Float64})
    monkeypatch.setattr(module, 'load_cost_history', cash)
    result = module.report_models(**saved_run)
    assert set(result['conclusions'].values()) == {'RESEARCH_ONLY'}
    assert pl.read_parquet(saved_run['output']/'benchmark_comparisons.parquet').is_empty()


@pytest.mark.parametrize('broken', [None, 'missing_day', 'wrong_name'])
def test_registered_equal_weight_references_keep_first_day_return(saved_run, monkeypatch, broken):
    measurement = saved_run['measurement_config']
    windows = tomllib.loads(measurement.read_text())['stress_windows_config']
    measurement.write_text(f'stress_windows_config = {json.dumps(windows)}\n'
                           '[benchmarks]\nequal_weight_snapshot="fixture"\netf_total_return_snapshot="fixture"\n')

    def load(**kwargs):
        assert kwargs['config'] == measurement
        dates = [dt.date(2024, 1, i) for i in range(1, 7)]
        frames = {name: pl.DataFrame({'date': dates, 'unit_nav': [1.1, 1.1, 1.122, 1.122, 1.122, 1.122]})
                  for name in ('510300', 'csi800_equal_weight', 'all_market_equal_weight')}
        if broken == 'missing_day':
            frames['all_market_equal_weight'] = frames['all_market_equal_weight'].slice(1)
        elif broken == 'wrong_name':
            frames['cap_weighted'] = frames.pop('all_market_equal_weight')
        return frames

    monkeypatch.setattr(module, 'load_return_benchmarks', load)
    monkeypatch.setattr(module, 'read_index_benchmark', lambda **kw: pytest.fail('No official-index substitution'))
    if broken:
        with pytest.raises(ValueError, match='session grid|three registered'):
            module.report_models(**saved_run)
        assert not saved_run['output'].exists()
        return
    result = module.report_models(**saved_run)
    half = pl.read_parquet(saved_run['output']/'benchmark_comparisons.parquet').filter(
        (pl.col('variant') == 'equal_z_top50') & (pl.col('cost_multiplier') == .5))
    assert half['benchmark_total_return'].to_list() == pytest.approx([.122]*3)
    one = result['models']['equal_z']['primary']
    assert [b['total_return'] for b in one['benchmarks']] == pytest.approx([.02]*3)
    assert result['measurement']['indexes'][1]['source'] == 'monthly_equal_weight'


def test_ambiguous_index_config_rejected(saved_run):
    path = saved_run['measurement_config']
    path.write_text(path.read_text()+'\n[benchmarks]\nequal_weight_snapshot="fixture"\n')
    with pytest.raises(ValueError, match='Choose either'):
        module.report_models(**saved_run)
    assert not saved_run['output'].exists()
