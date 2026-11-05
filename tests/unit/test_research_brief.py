from pathlib import Path
import json

from quant.reporting.research_brief import collect_facts, render_template, write_brief


def test_brief_template_keeps_facts(tmp_path: Path):
    facts = {
        "month": "2026-10",
        "registry_new_rows": 1,
        "registry_conclusions": {"REJECTED": 1},
        "n5_methods": {"q10_plus_admitted": "PAPER_CANDIDATE"},
        "q10_forward": None,
        "llm_month_usd": 0.0,
        "llm_tasks": 0,
        "funnel": {},
        "gp_hints_count": 0,
        "latest_gp_hint": None,
    }
    text = render_template(facts, "关注增量模型稳定性")
    assert "PAPER_CANDIDATE" in text
    assert "关注增量模型稳定性" in text


def test_write_brief_no_llm(tmp_path: Path, monkeypatch):
    notifications = []
    monkeypatch.setattr("quant.notify.send", lambda **kw: notifications.append(kw))
    result = write_brief("2026-10", root=tmp_path, use_llm=False)
    path = Path(result["path"])
    assert path.is_file() and path.is_relative_to(tmp_path)
    assert result["facts"]["month"] == "2026-10"
    assert result["facts"]["registry_new_rows"] == 0
    assert result["facts"]["llm_month_usd"] == 0
    assert len(notifications) == 1
    assert notifications[0]["subject"] == "research brief 2026-10"


def test_monthly_market_narrative_calls_once_and_keeps_machine_facts_separate(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr('quant.notify.send',lambda **kw:None)
    def complete(messages,settings):
        calls.append(messages)
        assert 'market_state' in messages[1]['content']
        return {'choices':[{'message':{'content':'市场资料仍不足，先核验覆盖与风险暴露。'}}],'usd':.01}
    monkeypatch.setattr('quant.llm.complete_messages',complete)
    first=write_brief('2026-10',root=tmp_path)
    second=write_brief('2026-10',root=tmp_path)
    assert len(calls)==1 and first['narrative'] and second['narrative']
    receipt=json.loads((tmp_path/'artifacts/research/brief/2026-10.narrative.json').read_text(encoding='utf-8'))
    assert receipt['status']=='accepted'
    ledger=list((tmp_path/'artifacts/research/llm_ledger').glob('*.jsonl'))
    assert len(ledger)==1 and len(ledger[0].read_text(encoding='utf-8').splitlines())==1
    assert '市场状态解读' in Path(first['path']).read_text(encoding='utf-8')


def test_numeric_narrative_is_rejected_but_paid_response_is_recorded_and_not_retried(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr('quant.notify.send',lambda **kw:None)
    monkeypatch.setattr('quant.llm.complete_messages',lambda *a:calls.append(1) or {'content':'本月风险为1级','usd':.01})
    assert not write_brief('2026-10',root=tmp_path)['narrative']
    assert not write_brief('2026-10',root=tmp_path)['narrative']
    assert len(calls)==1
    receipt=json.loads((tmp_path/'artifacts/research/brief/2026-10.narrative.json').read_text(encoding='utf-8'))
    assert receipt['status']=='rejected_numeric_narrative' and receipt['usd']==.01


def test_market_inputs_before_report_month_are_explicitly_stale(tmp_path):
    folder=tmp_path/'artifacts/research/market_indicators_fixture'
    folder.mkdir(parents=True)
    (folder/'summary.json').write_text(json.dumps({'latest':{'trade_date':'2026-09-21','observed_stocks':5209}}))
    facts=collect_facts('2026-10',root=tmp_path)
    assert facts['market_state']['status']=='stale_before_month'
    assert facts['market_state']['as_of']=='2026-09-21'


def test_structured_response_keeps_only_whole_nonnumeric_sentences(tmp_path,monkeypatch):
    calls=[]
    raw=json.dumps({'as_of':'2026-10-30','summary':
        '基准位于200日均线下方。证据仅来自单日收盘重建，非到达证明；相关维度资料不足。'},ensure_ascii=False)
    monkeypatch.setattr('quant.llm.complete_messages',lambda *a:calls.append(1) or {'content':raw,'usd':.01})
    result=write_brief('2026-10',root=tmp_path,notify=False)
    receipt=json.loads((tmp_path/'artifacts/research/brief/2026-10.narrative.json').read_text(encoding='utf-8'))
    assert result['narrative'] and calls==[1]
    assert receipt['response']['content']==raw
    assert receipt['accepted_text']=='证据仅来自单日收盘重建，非到达证明；相关维度资料不足。'
    assert '200' not in Path(result['path']).read_text(encoding='utf-8')


def test_cached_structured_rejection_is_recovered_without_second_call_or_charge(tmp_path,monkeypatch):
    path=tmp_path/'artifacts/research/brief/2026-10.narrative.json';path.parent.mkdir(parents=True)
    raw={'content':json.dumps({'summary':'本月数字为2。来源仍有缺口，需要继续核对。'},ensure_ascii=False)}
    path.write_text(json.dumps({'status':'rejected_numeric_narrative','response':raw,
        'usd':.01,'maximum_calls':1,'facts':{'month':'2026-10'}}),encoding='utf-8')
    monkeypatch.setattr('quant.llm.complete_messages',lambda *a:__import__('pytest').fail('no second paid call'))
    result=write_brief('2026-10',root=tmp_path,notify=False)
    cached=json.loads(path.read_text(encoding='utf-8'))
    assert result['narrative'] and cached['accepted_text']=='来源仍有缺口，需要继续核对。'
    assert cached['response']==raw and cached['usd']==.01 and cached['maximum_calls']==1
    assert not list((tmp_path/'artifacts/research/llm_ledger').glob('*'))


def test_structured_numeric_only_summary_stays_rejected():
    from quant.reporting.research_brief import _structured_narrative
    assert _structured_narrative(json.dumps({'summary':'市场风险为2级。'})) is None
    assert _structured_narrative(json.dumps({'summary':'200日均线下方；短句。'})) is None
