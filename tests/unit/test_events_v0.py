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
    repurchase = pl.read_parquet(tmp_path / "data/clean/events/repurchase/version=20261027/events.parquet")
    insider = pl.read_parquet(tmp_path / "data/clean/events/insider_trading/version=20261027/events.parquet")
    assert repurchase.height == 1 and insider.height == 0
    assert repurchase["known_at"][0] == repurchase["published"][0] == dt.date(2024, 1, 1)
    assert repurchase["parse_status"][0] == "parsed"
    assert summary["tables"]["repurchase"]["unresolved_ratio"] == 0
    text = (tmp_path / "artifacts/events_v0_2024-01-31/sample50.csv").read_text(encoding="utf-8")
    assert "human_label" in text
    ledger = (tmp_path / "ledger/2026-10.jsonl").read_text(encoding="utf-8")
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
    target = tmp_path / "data/clean/events/repurchase/version=20261027/events.parquet"
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


def test_event_family_is_not_evaluated_this_round():
    text = Path("configs/research/event_family_v1.toml").read_text(encoding="utf-8")
    assert "evaluate_this_round = false" in text
    assert "event_extract" in text
    assert "repurchase_strength_90d" in text


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
