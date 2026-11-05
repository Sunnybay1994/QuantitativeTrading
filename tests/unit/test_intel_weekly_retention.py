import hashlib
import json
import pytest

from quant.core.paths import project_paths
from quant.intel.pipeline import run_intel

QUOTE='Cross-sectional reversal using past returns.'


@pytest.fixture
def intel_tree(tmp_path,monkeypatch):
    (tmp_path/'src/quant').mkdir(parents=True)
    (tmp_path/'pyproject.toml').write_text("[project]\nname='quant'\n")
    config=tmp_path/'configs/research/intel.toml';config.parent.mkdir(parents=True)
    config.write_text('library="configs/factors/library"\nmaximum_candidates=8\n')
    monkeypatch.setenv('QUANT_PROJECT_ROOT',str(tmp_path))
    monkeypatch.setenv('QUANT_ARTIFACTS_ROOT',str(tmp_path/'artifacts'))
    monkeypatch.setattr('quant.intel.pipeline.iso_week',lambda:'2026-W46')
    project_paths.cache_clear()
    yield tmp_path,config,tmp_path/'artifacts/intel/2026-W46'
    project_paths.cache_clear()


def paper(identifier='paper_one'):
    return dict(id=identifier,source='arxiv',title='A reversal test',
        url='https://arxiv.org/abs/'+identifier,summary=QUOTE,evidence_text=QUOTE)


def candidate(identifier='paper_one',expression='delay(adj_close,20)/adj_close'):
    return {'expression':expression,'direction':-1,'rationale':'reversal',
        'source_id':identifier,'evidence_quote':QUOTE}


def fail_call(*args):
    pytest.fail('An already reviewed source must not cause another paid call')


def weekly_hashes(folder):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


def test_repeat_or_empty_scan_preserves_paid_product_and_does_not_pay_again(intel_tree,monkeypatch):
    root,config,folder=intel_tree
    monkeypatch.setattr('quant.intel.pipeline.collect',lambda *a,**kw:[paper()])
    first=run_intel(config_path=config,complete=lambda *a:{'candidates':[candidate()]})
    assert first['accepted']==1
    before=weekly_hashes(folder)
    second=run_intel(config_path=config,complete=fail_call)
    assert second['items']==0 and second['weekly_items']==1 and second['weekly_accepted']==1
    assert weekly_hashes(folder)==before
    monkeypatch.setattr('quant.intel.pipeline.collect',lambda *a,**kw:[])
    run_intel(config_path=config,complete=fail_call)
    assert weekly_hashes(folder)==before
    ledger=next((root/'artifacts/research/llm_ledger').glob('*.jsonl'))
    assert len(ledger.read_text(encoding='utf-8').splitlines())==1
    assert not list((root/'configs/factors').glob('queue/intel_*.toml'))


def test_collect_only_before_and_after_extraction_does_not_consume_or_erase_it(intel_tree,monkeypatch):
    root,config,folder=intel_tree
    monkeypatch.setattr('quant.intel.pipeline.collect',lambda *a,**kw:[paper()])
    run_intel(config_path=config,extract=False,complete=fail_call)
    assert not list(folder.glob('extraction_*.json'))
    assert json.loads((folder/'seen.json').read_text())==['paper_one']
    # This also recovers the legacy state where no-extract populated seen.json.
    result=run_intel(config_path=config,complete=lambda *a:{'candidates':[candidate()]})
    assert result['items']==0 and result['accepted']==1
    before=weekly_hashes(folder)
    run_intel(config_path=config,extract=False,complete=fail_call)
    assert weekly_hashes(folder)==before


def test_new_collect_only_item_remains_eligible_if_next_fetch_is_empty(intel_tree,monkeypatch):
    _,config,folder=intel_tree
    monkeypatch.setattr('quant.intel.pipeline.collect',lambda *a,**kw:[paper()])
    run_intel(config_path=config,complete=lambda *a:{'candidates':[candidate()]})
    monkeypatch.setattr('quant.intel.pipeline.collect',lambda *a,**kw:[paper('paper_two')])
    run_intel(config_path=config,extract=False,complete=fail_call)
    monkeypatch.setattr('quant.intel.pipeline.collect',lambda *a,**kw:[])
    inputs=[]
    def complete(messages,settings):
        inputs.extend(r['id'] for r in json.loads(messages[-1]['content'])['items'])
        return {'candidates':[candidate('paper_two','ts_mean(adj_close,20)/adj_close')]}
    run_intel(config_path=config,complete=complete)
    assert inputs==['paper_two']
    assert len(json.loads((folder/'items.json').read_text()))==2
    assert len(json.loads((folder/'candidates.json').read_text()))==2


def test_only_actual_model_inputs_are_reviewed_at_the_25_paper_limit(intel_tree,monkeypatch):
    _,config,folder=intel_tree
    monkeypatch.setattr('quant.intel.pipeline.collect',lambda *a,**kw:[paper(f'paper_{i}') for i in range(30)])
    calls=[]
    def complete(messages,settings):
        calls.append([r['id'] for r in json.loads(messages[-1]['content'])['items']])
        return {'candidates':[]}
    run_intel(config_path=config,complete=complete)
    run_intel(config_path=config,complete=complete)
    run_intel(config_path=config,complete=fail_call)
    assert [len(ids) for ids in calls]==[25,5] and len(set(calls[0])&set(calls[1]))==0
    assert len(json.loads((folder/'items.json').read_text()))==30
