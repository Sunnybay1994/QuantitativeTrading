import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from quant.data.forecast_text_scores import read_corpus
from quant.factors.forecast_text_score import score_key
from quant.research import run_monthly_text_pipeline as pipeline
from quant.research.score_forecast_text import load_settings


@pytest.fixture
def plan(tmp_path):
    folder = tmp_path / 'plan'
    folder.mkdir()
    config = Path('configs/research/p7_monthly_sampling_20260912.toml')
    (folder / 'config.toml').write_bytes(config.read_bytes())
    pl.DataFrame({'symbol': ['000001.SZ'], 'publication_date': [dt.date(2020, 1, 1)],
        'report_period': [dt.date(2019, 12, 31)], 'reason_text': ['销售增长']
    }).write_parquet(folder / 'scoring_batch.parquet')
    corpus = read_corpus(folder / 'scoring_batch.parquet')
    corpus.select('symbol', 'input_id').with_columns(pl.lit(dt.date(2020, 1, 31)).alias(
        'trade_date')).write_parquet(folder / 'selected_members.parquet')
    settings = load_settings(Path('configs/research/deepseek_p7_thinking_8192_20260912.toml'))
    (folder / 'summary.json').write_text(json.dumps({
        'selected_request_keys': [score_key('销售增长', settings)]}))
    return folder


def test_changed_request_text_rejected_before_output_or_api(plan, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'run_batch', lambda **kw: pytest.fail('Unexpected API call'))
    source = plan / 'scoring_batch.parquet'
    pl.read_parquet(source).with_columns(pl.lit('成本上涨').alias('reason_text')).write_parquet(source)
    with pytest.raises(ValueError, match='frozen plan'):
        pipeline.run(plan=plan, prior_plans=[], cache=tmp_path / 'cache.sqlite',
            output=tmp_path / 'output', data_root=tmp_path, execute=True,
            max_requests=1, max_usd=1.)
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('usd,requests', [(30.01, 1), (float('nan'), 1), (1., 0)])
def test_invalid_budget_rejected_before_output(plan, tmp_path, usd, requests):
    with pytest.raises(ValueError, match='cumulative'):
        pipeline.run(plan=plan, prior_plans=[], cache=tmp_path / 'cache.sqlite',
            output=tmp_path / 'output', data_root=tmp_path, execute=True,
            max_requests=requests, max_usd=usd)
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('execute', [False, True])
def test_failed_text_is_reported_and_evaluated_without_resubmission(
        plan, tmp_path, monkeypatch, execute):
    stages = []
    cache = tmp_path / 'cache.sqlite'
    cache.touch()
    def score(**kwargs):
        stages.append('score')
        assert kwargs['max_usd'] == 2. and kwargs['max_requests'] == 7
        return {'requests_this_run': 1, 'summary': {'retryable': 1}}
    def quality(**kwargs):
        stages.append('quality')
        return {'successful_texts': 0, 'selected_unique_texts': 1,
                'shared_charged_or_reserved_usd': .01}
    def evaluate(**kwargs):
        stages.append('evaluate')
        assert kwargs['plan'] == plan and kwargs['additional_plans'] == []
        return {'sample_rows': 1, 'coverage': [
            {'factor': 'text_operating_improvement', 'max_common_symbols': 0, 'usable_months': 0}]}
    monkeypatch.setattr(pipeline, 'run_batch', score)
    monkeypatch.setattr(pipeline, 'report_quality', quality)
    monkeypatch.setattr(pipeline, 'evaluate', evaluate)
    result = pipeline.run(plan=plan, prior_plans=[], cache=cache, output=tmp_path / 'output',
        data_root=tmp_path, execute=execute, max_requests=7, max_usd=2., workers=4)
    assert stages == (['score'] if execute else []) + ['quality', 'evaluate']
    assert result['requests_this_run'] == int(execute)
    assert result['conclusion'] == 'RESEARCH_ONLY'
    assert (tmp_path / 'output/report.md').is_file()


def test_cost_stage_requires_global_peer_comparison_and_return_benchmarks(plan, tmp_path, monkeypatch):
    cache = tmp_path/'cache.sqlite'
    cache.touch()
    benchmark = tmp_path/'benchmark.toml'
    benchmark.write_text('# fixture')
    calls = []
    monkeypatch.setattr(pipeline, 'run_batch', lambda **kw: pytest.fail('Offline run made API calls'))
    monkeypatch.setattr(pipeline, 'report_quality', lambda **kw: {
        'successful_texts':1,'selected_unique_texts':1,'shared_charged_or_reserved_usd':.01})
    monkeypatch.setattr(pipeline, 'evaluate', lambda **kw: {
        'sample_rows':1,'coverage':[], 'cost_inputs':{'primary_statistical_pass':['text_operating_improvement']}})
    completed = tmp_path/'completed'
    def costs(**kw):
        calls.append('costs')
        assert kw['only_statistical_pass'] is True
        return {'completed_runs':{'text_operating_improvement':str(completed)},
                'failures':{},'pending_external_runs':{}}
    def redundancy(**kw):
        calls.append('redundancy')
        assert kw['peer_library'] == Path('configs/factors/library')
        return {}
    def scorecard(**kw):
        calls.append('scorecard')
        assert kw['redundancy'] == tmp_path/'output/redundancy'
        assert kw['return_benchmark_config'] == benchmark and kw['cost_runs'] == [completed]
        return {'admitted_rows':0}
    monkeypatch.setattr('quant.research.factor_battery_cost_batch.run_cost_batch', costs)
    monkeypatch.setattr('quant.research.forecast_text_redundancy.run_redundancy', redundancy)
    monkeypatch.setattr('quant.research.factor_battery_scorecard.run_scorecard', scorecard)
    result = pipeline.run(plan=plan,prior_plans=[],cache=cache,output=tmp_path/'output',
        data_root=tmp_path,execution_snapshot='fixture',return_benchmark_config=benchmark)
    assert calls == ['costs','redundancy','scorecard']
    assert result['requests_this_run'] == 0 and result['scorecard']['admitted_rows'] == 0
