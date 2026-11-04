from quant.core.paths import project_paths
from quant.intel.extract import extract_candidates
from quant.intel.pipeline import run_intel
import datetime as dt

from quant.intel.sources import collect, fetch_arxiv, iso_week


ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>A reversal test</title>
    <id>http://arxiv.org/abs/0000.00001</id>
    <summary>Cross-sectional reversal using past returns.</summary>
    <published>2026-09-01T00:00:00Z</published>
  </entry>
</feed>
"""


def test_arxiv_parser():
    items = fetch_arxiv(getter=lambda url: ATOM)
    assert items[0]["source"] == "arxiv"
    assert "reversal" in items[0]["title"].lower()


def test_arxiv_query_uses_spaces_for_or(monkeypatch):
    seen = {}

    def capture(url: str) -> str:
        seen["url"] = url
        return ATOM

    fetch_arxiv(getter=capture, limit=1)
    assert "search_query=cat%3Aq-fin.ST+OR+cat%3Aq-fin.PM+OR+cat%3Aq-fin.TR" in seen["url"]
    assert "%2BOR%2B" not in seen["url"]


def test_iso_week_sunday_intel_slot_matches_f2_paths():
    assert iso_week(dt.date(2026, 11, 1)) == "2026-W45"
    assert iso_week(dt.date(2026, 11, 8)) == "2026-W46"
    assert iso_week(dt.date(2026, 10, 31)) == "2026-W44"


def test_extract_keeps_valid_dsl_and_drops_python():
    quote='Cross-sectional reversal using past returns.'
    items = [{"id": "abcd1234efgh0000", "source": "arxiv", "title": "x", "summary": quote}]
    accepted, rejected = extract_candidates(
        items,
        existing_canonical=set(),
        complete=lambda messages, settings: {
            "candidates": [
                {"expression": "-ts_mean(adj_close/delay(adj_close,20),20)",
                 "direction": 1, "rationale": "reversal", "source_id": "abcd1234efgh0000",'evidence_quote':quote},
                {"expression": "os.system('rm')", "direction": 1, "rationale": "bad",
                 "source_id": "abcd1234efgh0000",'evidence_quote':quote},
            ]
        },
    )
    assert len(accepted) == 1
    assert accepted[0]["expr"].startswith("-ts_mean")
    assert rejected


def test_pipeline_preserves_verified_quotes_without_creating_queue_files(monkeypatch, tmp_path):
    (tmp_path / "src" / "quant").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='quant'\n")
    monkeypatch.setenv("QUANT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
    project_paths.cache_clear()
    configs = tmp_path / "configs"
    (configs / "research").mkdir(parents=True)
    (configs / "factors" / "queue").mkdir(parents=True)
    (configs / "research" / "intel.toml").write_text(
        'library="configs/factors/library"\nqueue="configs/factors/queue"\n'
        "maximum_candidates=4\n[sources]\narxiv=true\ngithub=false\nrss=[]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "quant.intel.pipeline.collect",
        lambda config, getter=None: [{
            "id": "abcd1234efgh0000", "source": "arxiv", "title": "A reversal test",
            "url": "http://arxiv.org/abs/0000.00001", "summary": "Cross-sectional reversal using past returns.", "published": "2026-09-01",
        }],
    )
    result = run_intel(
        config_path=configs / "research" / "intel.toml",
        complete=lambda messages, settings: {"candidates": [{
            "expression": "delay(adj_close,20)/adj_close",
            "direction": -1, "rationale": "reversal", "source_id": "abcd1234efgh0000",
            "evidence_quote":"Cross-sectional reversal using past returns.",
        }]},
    )
    assert result["accepted"] == 1
    queue = tmp_path / "configs" / "factors" / "queue"
    written = list(queue.glob("intel_*.toml"))
    assert written==[] and result['queue'] is None
    digest = tmp_path / "artifacts" / "intel"
    assert list(digest.glob("*/digest.md"))
    assert 'Cross-sectional reversal using past returns.' in next(digest.glob('*/candidates.json')).read_text()
    import json,hashlib
    ledger=next((tmp_path/'artifacts/research/llm_ledger').glob('*.jsonl'))
    paid=json.loads(ledger.read_text(encoding='utf-8'))
    receipt=__import__('pathlib').Path(paid['artifact'])
    assert paid['usd']>0 and receipt.is_file()
    assert hashlib.sha256(receipt.read_bytes()).hexdigest()==paid['artifact_sha256']
    project_paths.cache_clear()


def test_candidates_without_a_matching_complete_paper_quote_are_discarded():
    quote='Cross-sectional reversal using past returns.'
    item={'id':'paper','source':'arxiv','title':'Reversal','summary':quote}
    for wrong in ('','using past returns.','An invented sentence about reversal.'):
        accepted,rejected=extract_candidates([item],existing_canonical=set(),complete=lambda *a:{'candidates':[
            {'expression':'delay(adj_close,20)/adj_close','direction':-1,'source_id':'paper','evidence_quote':wrong}]})
        assert accepted==[] and rejected
    assert extract_candidates([{**item,'source':'github'}],existing_canonical=set(),
        complete=lambda *a: (_ for _ in ()).throw(AssertionError('no paper input, no paid call')))==([],[])


def test_collect_excludes_non_qfin_feeds_and_requires_research_keywords():
    urls=[]
    config={'sources':{'arxiv':False,'github':False,'rss':['https://example.org/feed','https://rss.arxiv.org/rss/cs.AI',
        'https://rss.arxiv.org/rss/q-fin.PM'],'keywords':['portfolio']}}
    def getter(url):
        urls.append(url)
        return '<rss><channel><item><title>Unrelated physics</title><link>https://arxiv.org/abs/0</link><description>Particles.</description></item></channel></rss>'
    assert collect(config,getter=getter)==[]
    assert urls==['https://rss.arxiv.org/rss/q-fin.PM']


def test_collect_swallows_network_errors():
    assert collect({"sources": {"arxiv": True, "github": False, "rss": []}},
                   getter=lambda url: (_ for _ in ()).throw(RuntimeError("offline"))) == []
