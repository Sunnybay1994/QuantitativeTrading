import json
from pathlib import Path
import tomllib

import pytest

from quant.research import report_factor_candidates as mod

FORMULA='adj_close / delay(adj_close, 17) - 1'
DEFINITION=f'因子定义：`{FORMULA}`，方向：1。'


def candidate(**changes):
    return {'expression':FORMULA,'direction':1,'rationale':'报告明确的相对价格变化',
            'source_id':'report0','expression_quote':FORMULA,'direction_quote':'方向：1',
            'definition_quote':DEFINITION,**changes}


def test_exact_formula_and_same_definition_direction_required():
    reports={'report0':{'text':DEFINITION+'\n其他因子：方向：-1'}}
    accepted,records=mod.check_evidence({'candidates':[candidate(),candidate(expression=FORMULA.replace('17','18')),
        candidate(direction=-1),candidate(direction_quote='方向：-1'),candidate(expression_quote='fake')], 'skipped':[]},reports)
    assert len(accepted)==1 and len(records)==5
    assert records[1]['reason']=='formula_not_written_in_source'
    assert records[3]['reason']=='formula_and_direction_must_share_a_source_definition'


def test_incomplete_description_and_untrusted_skip_references():
    reports={'report0':{'text':'仅有均线想法，未写窗口。'}}
    payload={'candidates':[], 'skipped':[{'source_id':'report0','reason':'缺少窗口','quote':'未写窗口'},
                                      {'source_id':'unknown','reason':'缺少','quote':'fake'}]}
    assert mod.check_evidence(payload,reports)[0]==[]
    assert mod.check_evidence(payload,reports)[1][1]['reason']=='unverifiable_skip_reference'
    with pytest.raises(ValueError):
        mod.parse_extraction('{"candidates":[],"skipped":[],"execute":"evil"}',reports=reports,maximum=4)


def test_reports_have_bounded_complete_snapshots(tmp_path):
    path=tmp_path/'source.md'
    path.write_text(DEFINITION,encoding='utf-8')
    result=mod.read_reports([path],maximum_bytes=1000)
    assert result['report0']['text']==DEFINITION
    with pytest.raises(ValueError):
        mod.read_reports([path,path],maximum_bytes=1000)
    with pytest.raises(ValueError):
        mod.read_reports([path],maximum_bytes=5)


def test_semantic_definition_preserves_source_and_direction_boundaries():
    text = '因子：今日复权收盘价除以17个交易日前复权收盘价，再减一。高值优先。'
    item = candidate(expression_quote='今日复权收盘价除以17个交易日前复权收盘价，再减一',
                     direction_quote='高值优先', definition_quote=text)
    reports = {'report0': {'text': text}}
    payload = {'candidates': [item], 'skipped': []}
    assert mod.check_evidence(payload, reports)[0] == []
    accepted, _ = mod.check_evidence(payload, reports, mode='semantic_definition')
    assert accepted[0]['expression'] == FORMULA
    for changes in ({'direction': -1}, {'expression_quote': '不在原文内'},
                    {'definition_quote': '高值优先'}):
        bad = {'candidates': [{**item, **changes}], 'skipped': []}
        assert mod.check_evidence(bad, reports, mode='semantic_definition')[0] == []
    with pytest.raises(ValueError, match='Unknown report extraction mode'):
        mod.check_evidence(payload, reports, mode='unchecked')


@pytest.mark.parametrize('calibration_only', [False, True])
def test_semantic_live_path_keeps_dsl_validation(inputs, calibration_only):
    text = '因子：今日复权收盘价除以17个交易日前复权收盘价，再减一。高值优先。'
    inputs['reports'][0].write_text(text, encoding='utf-8')
    inputs['config'].write_text(f'calibration_only={str(calibration_only).lower()}\nextraction_mode="semantic_definition"\n' +
        inputs['config'].read_text(encoding='utf-8'), encoding='utf-8')
    item = candidate(expression_quote='今日复权收盘价除以17个交易日前复权收盘价，再减一',
                     direction_quote='高值优先', definition_quote=text)

    class Client:
        def complete_messages(self, messages, settings):
            assert '非可信数据' in messages[0]['content']
            assert '不能靠经验补充' in messages[0]['content']
            payload = {'candidates': [item, {**item, 'expression': "__import__('os')"}], 'skipped': []}
            return {'model': 'deepseek-flash', 'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(payload, ensure_ascii=False)}}]}

    summary = mod.run(**inputs, client=Client(), execute=True, development_test=True)
    assert summary['accepted_count'] == 1
    assert summary['extraction_mode'] == 'semantic_definition'
    if calibration_only:
        assert summary['batch'] is None and summary['next_command'] is None
        assert not (inputs['output']/'batch.toml').exists()
        with pytest.raises(ValueError, match='Calibration inputs cannot start'):
            mod.run(**{**inputs, 'output': inputs['output'].parent/'evaluation'}, client=Client(), execute=True,
                    evaluate=True, return_benchmark_config=Path('configs/data/return_benchmarks_q1b_20260912.toml'))
        return
    batch = tomllib.loads((inputs['output']/'batch.toml').read_text(encoding='utf-8'))
    assert batch['templates'][0]['family'] == 'report_semantic_candidates'


@pytest.fixture
def inputs(tmp_path):
    source=tmp_path/'report.md'
    source.write_text(DEFINITION,encoding='utf-8')
    config=tmp_path/'extraction.toml'
    text=Path('configs/research/report_factor_candidates_v1_20260913.toml').read_text(encoding='utf-8')
    text=text.replace('artifacts/research/p7_deepseek_cache.sqlite',(tmp_path/'cache.sqlite').as_posix())
    config.write_text(text,encoding='utf-8')
    return dict(reports=[source],design=Path('configs/factors/search/report_batch01_20260913.toml'),
                config=config,output=tmp_path/'run')


def test_dry_run_never_reads_credentials_or_uses_provider(inputs,monkeypatch):
    monkeypatch.setattr(mod,'load_key',lambda *_:pytest.fail('dry run credential access'))
    summary=mod.run(**inputs)
    assert summary['result']=='dry_run' and summary['batch'] is None
    assert not (inputs['output'].parent/'cache.sqlite').exists()
    snapshot=json.loads((inputs['output']/'request.json').read_text(encoding='utf-8'))
    assert snapshot['reports']['report0']['text']==DEFINITION


def test_provider_cache_budget_and_runnable_batch_preserve_original_thresholds(inputs, monkeypatch):
    class Client:
        calls=0
        def complete_messages(self,messages,settings):
            self.calls+=1
            assert '非可信数据' in messages[0]['content']
            return {'model':'deepseek-flash','usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'candidates':[candidate()], 'skipped':[]},ensure_ascii=False)}}]}
    client=Client()
    summary=mod.run(**inputs,client=client,execute=True,development_test=True)
    assert summary['result']=='success' and summary['accepted_count']==1
    batch=tomllib.loads((inputs['output']/'batch.toml').read_text(encoding='utf-8'))
    original=tomllib.loads(inputs['design'].read_text(encoding='utf-8'))
    assert batch['dates']==original['dates']
    assert batch['search']['maximum_cost_attempts']==original['search']['maximum_cost_attempts']
    assert (inputs['output']/'battery_config.toml').read_bytes()==Path(original['search']['battery_config']).read_bytes()
    assert summary['prepared']['registered_count']==1
    inputs['output']=inputs['output'].parent/'cached'
    calls = []
    def evaluate(**kwargs):
        calls.append(kwargs)
        return {'message': 'completed'}
    monkeypatch.setattr('quant.research.run_factor_search.run', evaluate)
    benchmark = Path('configs/data/return_benchmarks_q1b_20260912.toml')
    again=mod.run(**inputs,client=client,execute=True,development_test=True,
                  evaluate=True, return_benchmark_config=benchmark)
    assert calls[0]['config'] == inputs['output']/'batch.toml'
    assert calls[0]['return_benchmark_config'] == benchmark
    assert again['evaluation']['message'] == 'completed'
    assert client.calls==1 and again['accepted_count']==1
    assert again['new_requests']==0 and again['new_charged_or_reserved_usd']==0
    assert again['request_charged_or_reserved_usd']<.05


def test_claimed_expression_still_fails_local_dsl_whitelist(inputs):
    expr="__import__('os').system('echo malicious')"
    quote=f'{expr}，方向：1'
    inputs['reports'][0].write_text(quote,encoding='utf-8')
    class Client:
        def complete_messages(self,messages,settings):
            raw=candidate(expression=expr,expression_quote=expr,definition_quote=quote)
            return {'model':'deepseek-flash','usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200},
                'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'candidates':[raw],'skipped':[]})}}]}
    result=mod.run(**inputs,client=Client(),execute=True,development_test=True)
    assert result['accepted_count']==0 and result['batch'] is None


def test_cli_failure_is_nonzero_for_automation(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['report_factor_candidates', '--reports', 'report.md',
        '--design', 'design.toml', '--config', 'config.toml', '--output', 'output'])
    monkeypatch.setattr(mod, 'run', lambda **kwargs: {'result': 'budget_exhausted'})
    with pytest.raises(SystemExit) as stopped:
        mod.main()
    assert stopped.value.code == 1
