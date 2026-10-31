import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.events_v0 import accept_extraction, build_events, family_of


class Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class Session:
    def __init__(self, bulletin: str):
        self.bulletin = bulletin
        self.queries = []

    def post(self, url, **kwargs):
        if "bulletin_detail" in url:
            return Response({"announcementContent": self.bulletin})
        self.queries.append(kwargs["data"]["searchkey"])
        return Response({"totalAnnouncement": 1, "announcements": [{
            "announcementId": "a1", "secCode": "600000",
            "announcementTitle": "<em>关于回购股份进展的公告</em>",
            "announcementTime": 1704067200000,
            "adjunctUrl": "finalpage/2024-01-01/1.pdf",
        }]})


def _pricing(path: Path) -> Path:
    path.write_text("input_usd_per_million = 0.3\noutput_usd_per_million = 1.2\n", encoding="utf-8")
    return path


def _complete(messages, settings):
    assert settings["max_tokens"] == 250
    assert len(messages[1]["content"]) <= 1500
    return {"choices": [{"message": {"content": json.dumps({
        "status": "parsed", "amount_cny": 10_000_000, "ratio_pct": 1.2, "term_days": 90,
        "direction": "repurchase",
        "evidence": "本次回购金额1000万元，占总股本1.2%，期限3个月。",
    }, ensure_ascii=False)}}], "usage": {"prompt_tokens": 100, "completion_tokens": 40}}


def test_family_and_evidence_rules():
    assert family_of("关于回购股份进展的公告") == "repurchase"
    assert family_of("持股5%以上股东减持股份预披露公告") == "insider_trading"
    assert family_of("年度报告") is None
    excerpt = "本次回购金额1000万元，占总股本1.2%，期限3个月。"
    kept = accept_extraction(excerpt, {
        "status": "parsed", "amount_cny": 10_000_000, "ratio_pct": 1.2, "term_days": 90,
        "direction": "repurchase", "evidence": excerpt})
    assert kept["parse_status"] == "parsed"
    assert kept["amount_cny"] == 10_000_000
    invented = accept_extraction(excerpt, {
        "status": "parsed", "amount_cny": 1, "ratio_pct": None, "term_days": None,
        "direction": "repurchase", "evidence": "回购金额1元"})
    assert invented["parse_status"] == "unresolved"
    assert invented["amount_cny"] is None


def test_build_writes_both_tables_and_ledger_once(tmp_path):
    excerpt = "<p>本次回购金额1000万元，占总股本1.2%，期限3个月。</p>"
    session = Session(excerpt)
    calls = {"n": 0}

    def complete(messages, settings):
        calls["n"] += 1
        return _complete(messages, settings)

    summary = build_events(
        start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 31),
        data_root=tmp_path / "data", artifact_root=tmp_path / "artifacts",
        session=session, complete=complete, pricing=_pricing(tmp_path / "pricing.toml"),
        ledger_root=tmp_path / "ledger")
    assert calls["n"] == 1
    assert session.queries == ["回购实施", "股东减持", "股东增持"]
    repurchase = pl.read_parquet(tmp_path / "data/clean/events/repurchase/version=20240131/events.parquet")
    insider = pl.read_parquet(tmp_path / "data/clean/events/insider_trading/version=20240131/events.parquet")
    assert repurchase.height == 1 and insider.height == 0
    assert repurchase["known_at"][0] == repurchase["published"][0] == dt.date(2024, 1, 1)
    assert repurchase["parse_status"][0] == "parsed"
    assert summary["tables"]["repurchase"]["unresolved_ratio"] == 0
    text = (tmp_path / "artifacts/events_v0_2024-01-31/sample50.csv").read_text(encoding="utf-8")
    assert "human_label" in text
    ledger_files = list((tmp_path/'ledger').glob('*.jsonl'))
    assert len(ledger_files) == 1
    ledger = ledger_files[0].read_text(encoding="utf-8")
    row = json.loads(ledger)
    assert row["task"] == "event_extract" and row["usd"] > 0
    cache_file = next((tmp_path / "artifacts" / "events_v0_cache_v2").glob("*.json"))
    second = tmp_path / "artifacts2" / "events_v0_cache_v2"
    second.mkdir(parents=True)
    (second / cache_file.name).write_text(cache_file.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        build_events(
            start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 31),
            data_root=tmp_path / "data", artifact_root=tmp_path / "artifacts2",
            session=Session(excerpt), complete=complete, pricing=tmp_path / "pricing.toml",
            ledger_root=tmp_path / "ledger2")
    except ValueError as exc:
        assert "overwrite" in str(exc)
    assert calls["n"] == 1


def test_existing_table_is_not_overwritten(tmp_path):
    target = tmp_path / "data/clean/events/repurchase/version=20240131/events.parquet"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"keep")
    try:
        build_events(
            start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 31),
            data_root=tmp_path / "data", artifact_root=tmp_path / "artifacts",
            session=Session("<p>无</p>"), complete=_complete,
            pricing=_pricing(tmp_path / "pricing.toml"), ledger_root=tmp_path / "ledger")
    except ValueError as exc:
        assert "overwrite" in str(exc)
    else:
        raise AssertionError("overwrite was allowed")
    assert target.read_bytes() == b"keep"


def _build_fixture(root, **options):
    defaults = dict(start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 31),
        data_root=root/'data', artifact_root=root/'artifacts',
        session=Session('<p>本次回购金额1000万元，占总股本1.2%，期限3个月。</p>'),
        complete=_complete, pricing=root/'pricing.toml', ledger_root=root/'ledger', workers=1)
    if not defaults['pricing'].exists():
        _pricing(defaults['pricing'])
    defaults.update(options)
    return build_events(**defaults)


def test_collect_only_can_resume_extraction_without_overwriting_or_poisoning_cache(tmp_path):
    import hashlib

    def forbidden(*args):
        raise AssertionError('collect-only invoked the LLM')

    first = _build_fixture(tmp_path, collect_only=True, complete=forbidden)
    old_paths = [Path(row['path']) for row in first['tables'].values()]
    old_paths.append(tmp_path/'artifacts/events_v0_2024-01-31/sample50.csv')
    old_paths.append(tmp_path/'artifacts/events_v0_2024-01-31/summary.json')
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in old_paths}
    assert first['collect_only'] and first['llm_calls'] == 0
    assert not (tmp_path/'artifacts/events_v0_cache_v2/a1.json').exists()
    assert not list((tmp_path/'ledger').glob('*.jsonl'))
    second = _build_fixture(tmp_path, resume=True)
    assert second['llm_calls'] == 1 and second['partition'] != first['partition']
    assert Path(second['resumed_from']).parent.name == 'events_v0_2024-01-31'
    assert second['tables']['repurchase']['rows'] == 1
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in before.items())

    class Offline:
        def post(self, *args, **kwargs):
            raise AssertionError('cached resume requested network')

    third = _build_fixture(tmp_path, resume=True, complete=forbidden, session=Offline())
    assert third['llm_calls'] == 0
    assert third['partition'] not in (first['partition'], second['partition'])


def test_budget_stop_resumes_from_cached_raw_into_a_new_version(tmp_path, monkeypatch):
    monkeypatch.setattr('quant.data.events_v0._task_spend', lambda *_: 5.)
    first = _build_fixture(tmp_path)
    assert first['stopped'] == 'budget' and first['tables']['repurchase']['rows'] == 0
    original = Path(first['tables']['repurchase']['path']).read_bytes()
    monkeypatch.setattr('quant.data.events_v0._task_spend', lambda *_: 0.)
    second = _build_fixture(tmp_path, resume=True)
    assert second['stopped'] is None and second['llm_calls'] == 1
    assert second['tables']['repurchase']['rows'] == 1
    assert Path(first['tables']['repurchase']['path']).read_bytes() == original


def test_existing_partition_rejection_precedes_network_and_llm(tmp_path):
    target = tmp_path/'data/clean/events/insider_trading/version=20240131/events.parquet'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'unchanged')
    class Forbidden:
        def post(self, *args, **kwargs):
            raise AssertionError('should reject before network')
    import pytest
    with pytest.raises(ValueError, match='overwrite'):
        _build_fixture(tmp_path, session=Forbidden())
    assert target.read_bytes() == b'unchanged'


def test_empty_text_can_retry_without_overwriting_original_raw(tmp_path):
    from unittest.mock import patch

    with patch('quant.data.events_v0.bulletin_text', return_value=''):
        first = _build_fixture(tmp_path, collect_only=True)
    original = tmp_path/'data/raw/cninfo/events_v0_text_v2/a1.txt'
    assert original.read_bytes() == b''
    assert not (tmp_path/'artifacts/events_v0_cache_v2/a1.json').exists()
    second = _build_fixture(tmp_path, resume=True)
    assert second['llm_calls'] == 1
    assert original.read_bytes() == b''
    retry = list((original.parent/'retries/a1').glob('*.txt'))
    assert len(retry) == 1 and retry[0].stat().st_size > 0
    assert first['partition'] != second['partition']


def test_retryable_llm_disconnect_stays_unresolved(tmp_path, monkeypatch):
    from quant.llm import RequestFailure
    monkeypatch.setattr("quant.data.events_v0.time.sleep", lambda _seconds: None)

    def complete(_messages, _settings):
        raise RequestFailure("connect_failed", retryable=True)

    summary = build_events(
        start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 31),
        data_root=tmp_path / "data", artifact_root=tmp_path / "artifacts",
        session=Session("<p>本次回购金额1000万元。</p>"), complete=complete,
        pricing=_pricing(tmp_path / "pricing.toml"), ledger_root=tmp_path / "ledger")
    assert summary["stopped"] is None
    assert summary["llm_calls"] == 0
    assert not (tmp_path/'artifacts/events_v0_cache_v2/a1.json').exists()
    frame = pl.read_parquet(tmp_path / "data/clean/events/repurchase/version=20240131/events.parquet")
    assert frame["parse_status"][0] == "unresolved"
    text = Path("configs/research/event_family_v1.toml").read_text(encoding="utf-8")
    assert "evaluate_this_round = false" in text
    assert "event_extract" in text
    assert "repurchase_strength_90d" in text


def test_unified_cli_preserves_resume_and_text_only_flags(monkeypatch):
    from quant import cli
    seen = []
    monkeypatch.setattr(cli, '_delegate', lambda module, args: seen.append((module, args)) or 0)
    args = ['--from', '2019-01-01', '--to', '2026-10-30', '--resume', '--collect-only',
            '--workers', '8']
    assert cli.main(['data', 'events-v0', *args]) == 0
    assert seen == [('quant.data.events_v0', args)]


def test_real_unified_cli_resumes_offline_with_canonical_schema(tmp_path):
    import os
    import subprocess
    import sys

    _build_fixture(tmp_path, collect_only=True)
    env = os.environ.copy()
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]/'src'),
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
               ALL_PROXY='http://127.0.0.1:9')
    command = [sys.executable, '-m', 'quant', 'data', 'events-v0',
        '--from', '2024-01-01', '--to', '2024-01-31', '--resume', '--collect-only',
        '--data-root', str(tmp_path/'data'), '--artifact-root', str(tmp_path/'artifacts')]
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=60)
    assert result.returncode == 0, result.stderr
    paths = list((tmp_path/'artifacts').glob('events_v0_2024-01-31_*/summary.json'))
    assert len(paths) == 1
    summary = json.loads(paths[0].read_text(encoding='utf-8'))
    assert summary['collect_only'] and summary['llm_calls'] == 0
    assert summary['tables']['repurchase']['rows'] == 1


def test_valid_pdf_cid_font_alias_keeps_chinese_and_amount_digits():
    import io
    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                              NameObject, NumberObject, TextStringObject)
    from quant.data.events_v0 import pdf_plain_text

    text = '公司股份回购实施进展公告本次已实际支付回购总金额为1,234,567.89元。'
    chars = sorted(set(text))
    cmap = ('/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n'
        '1 begincodespacerange <0000> <FFFF> endcodespacerange\n'
        +str(len(chars))+' beginbfchar\n'
        +'\n'.join(f'<{ord(c):04X}> <{ord(c):04X}>' for c in chars)
        +'\nendbfchar endcmap end end').encode()
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    unicode_map = DecodedStreamObject(); unicode_map.set_data(cmap)
    cid = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/CIDFontType0'), NameObject('/BaseFont'): NameObject('/STSong-Light'),
        NameObject('/CIDSystemInfo'): DictionaryObject({NameObject('/Registry'): TextStringObject('Adobe'),
            NameObject('/Ordering'): TextStringObject('Identity'), NameObject('/Supplement'): NumberObject(0)})})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type0'), NameObject('/BaseFont'): NameObject('/STSong-Light'),
        NameObject('/Encoding'): NameObject('/Identity-H'),
        NameObject('/DescendantFonts'): ArrayObject([writer._add_object(cid)]),
        NameObject('/ToUnicode'): writer._add_object(unicode_map)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/C2_0'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(('BT /C2_0 12 Tf 10 100 Td <'+text.encode('utf-16-be').hex()+'> Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO(); writer.write(output)
    assert pdf_plain_text(output.getvalue()) == text


def test_bulletin_reuses_cached_pdf_before_requesting_network(tmp_path, monkeypatch):
    from quant.data.events_v0 import bulletin_text
    cached = tmp_path/'a1.pdf'
    cached.write_bytes(b'cached original source')
    def extract(data):
        assert data == b'cached original source'
        return '公司股份回购实施公告已支付金额1000万元。'
    monkeypatch.setattr('quant.data.events_v0.pdf_plain_text', extract)
    class Offline:
        def post(self, *args, **kwargs): raise AssertionError('unexpected network')
        def get(self, *args, **kwargs): raise AssertionError('unexpected download')
    assert bulletin_text({'announcementId': 'a1'}, Offline(), tmp_path) == extract(cached.read_bytes())


def test_publication_timestamp_uses_shanghai_day_at_midnight_boundary():
    from quant.data.events_v0 import published_date
    midnight = dt.datetime(2023, 12, 31, 16, tzinfo=dt.timezone.utc)
    for value in (midnight, midnight.timestamp(), midnight.timestamp()*1000):
        assert published_date(value) == dt.date(2024, 1, 1)


def test_pdf_text_uses_tounicode_and_ignores_unmapped_glyphs():
    from quant.data.events_v0 import pdf_plain_text
    data = b"""%PDF-1.4
8 0 obj
<</BaseFont /SimSun /ToUnicode 9 0 R /Type /Font>>
endobj
9 0 obj
<</Length 78>>
stream
beginbfchar
<56DE> <56DE>
<8D2D> <8D2D>
endbfchar
endstream
endobj
3 0 obj
<</Length 40>>
stream
/FT8 12 Tf
<56DE8D2D>Tj
endstream
endobj
1 0 obj
<</Resources <</Font <</FT8 8 0 R>>>>
endobj
"""
    # Twenty Chinese characters are required before a filing is sent to the model.
    assert pdf_plain_text(data) == ""
    long = data.replace(b"<56DE8D2D>Tj", b"<" + b"56DE8D2D" * 10 + b">Tj")
    assert pdf_plain_text(long) == "回购" * 10


def test_literal_pdf_strings_keep_digits_next_to_glyphs():
    from quant.data.events_v0 import _show_text
    assert _show_text("(7500)<56DE8D2D>(6.5)", {0x56DE: "回", 0x8D2D: "购"}) == "7500回购6.5"


def test_explicit_paid_total_is_copied_and_a_plan_range_is_not():
    from quant.data.events_v0 import fill_explicit_total
    paid = "公司完成回购，已支付的总金额为1,665.30万元（不含交易费用）。"
    filled = fill_explicit_total(paid, {"parse_status": "unresolved", "amount_cny": None,
                                        "direction": None, "evidence": None}, "repurchase")
    assert filled["amount_cny"] == 16_653_000
    assert filled["direction"] == "repurchase"
    plan = "回购的资金总额不低于人民币3,000万元，不超过人民币6,000万元。"
    assert fill_explicit_total(plan, {"parse_status": "unresolved", "amount_cny": None,
                                      "direction": "repurchase"}, "repurchase")["amount_cny"] is None


def test_explicit_completed_ratio_is_copied_when_blank():
    from quant.data.events_v0 import fill_explicit_ratio
    text = "预计回购股份数量占0.74%至1.47%。实际回购股数占总股本比例0.79%。"
    filled = fill_explicit_ratio(text, {"parse_status": "parsed", "ratio_pct": None, "direction": "repurchase"})
    assert filled["ratio_pct"] == 0.79
    kept = fill_explicit_ratio(text, {"ratio_pct": 1.12})
    assert kept["ratio_pct"] == 1.12
    mixed = "实际回购股数占总股本比例0.37%。更正后实际回购股数占总股本比例0.31%。"
    assert fill_explicit_ratio(mixed, {"ratio_pct": None})["ratio_pct"] is None


def test_unexecuted_reduction_is_not_a_sell():
    from quant.data.events_v0 import drop_unexecuted_sell
    quote = "高新同华在本次减持计划期间内未减持公司股份。"
    cleared = drop_unexecuted_sell({"parse_status": "parsed", "direction": "sell", "evidence": quote,
                                    "amount_cny": None, "ratio_pct": None})
    assert cleared["parse_status"] == "unresolved"
    assert cleared["direction"] is None
    done = drop_unexecuted_sell({"parse_status": "parsed", "direction": "sell",
                                 "evidence": "累计减持公司股份122,662,201股，占公司总股本的4.10%。"})
    assert done["direction"] == "sell"
    mixed = drop_unexecuted_sell({
        "parse_status": "parsed", "direction": "sell",
        "evidence": "爱特威投资累计减持公司股份1,606,800股，占公司总股本的1%，华古投资未减持。"})
    assert mixed["direction"] == "sell"
    zero = drop_unexecuted_sell({
        "parse_status": "parsed", "direction": "sell",
        "evidence": "累计减持公司股份0股，占公司总股本的0%；本次减持股份计划已届满，未减持公司股份。"})
    assert zero["direction"] is None

def test_load_or_fetch_pages_retries_announcement_set_changed(tmp_path, monkeypatch):
    from quant.data import events_v0
    from quant.data.connectors.cninfo_announcements import AnnouncementSetChanged
    attempts = []

    def pages(start, end, **kwargs):
        attempts.append(1)
        yield {'page': len(attempts)}, [{'announcementId': 'old' if len(attempts) == 1 else 'new'}]
        if len(attempts) == 1:
            raise AnnouncementSetChanged('announcement count changed during pagination; retry window')

    monkeypatch.setattr(events_v0, 'announcement_pages', pages)
    monkeypatch.setattr(events_v0.time, 'sleep', lambda seconds: None)
    rows = events_v0._load_or_fetch_pages(tmp_path, '回购实施', dt.date(2022, 2, 1), dt.date(2022, 2, 28), session=None)
    assert len(attempts) == 2
    assert [row['announcementId'] for row in rows] == ['new']
    done = tmp_path / 'cninfo' / 'events_v0_index' / '回购实施' / '2022-02-01_2022-02-28' / 'done.json'
    assert done.is_file()

def test_load_or_fetch_pages_bisects_when_retries_exhaust(tmp_path, monkeypatch):
    from quant.data import events_v0
    from quant.data.connectors.cninfo_announcements import AnnouncementSetChanged
    calls = []

    def pages(start, end, **kwargs):
        calls.append((start, end))
        if start != end:
            yield {'wide': True}, [{'announcementId': f'{start}-{end}'}]
            raise AnnouncementSetChanged('announcement count changed during pagination; retry window')
        yield {'day': str(start)}, [{'announcementId': str(start)}]

    monkeypatch.setattr(events_v0, 'announcement_pages', pages)
    monkeypatch.setattr(events_v0.time, 'sleep', lambda seconds: None)
    rows = events_v0._load_or_fetch_pages(
        tmp_path, '回购实施', dt.date(2022, 2, 1), dt.date(2022, 2, 2), session=None)
    assert [row['announcementId'] for row in rows] == ['2022-02-01', '2022-02-02']
    assert (dt.date(2022, 2, 1), dt.date(2022, 2, 2)) in calls
