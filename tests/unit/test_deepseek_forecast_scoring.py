import datetime as dt
import json
from pathlib import Path

import httpx
import polars as pl
import pytest

from quant.data.connectors.deepseek import DeepSeekClient, RequestFailure, load_key
from quant.data.forecast_text_scores import ScoreCache, asof_panel, publish_panels, read_corpus
from quant.factors.forecast_text_score import DIMENSIONS, messages, parse_score, score_key
from quant.research.score_forecast_text import load_design, load_settings, run_batch, score_one

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/research/deepseek_p7_v1.toml"
DESIGN = ROOT / "configs/factors/p7_text_evaluation_v2.toml"
REASON = "订单显著增加，成本效率改善。"


@pytest.fixture(autouse=True)
def off_peak_clock(monkeypatch):
    monkeypatch.setattr('quant.research.score_forecast_text.request_window',
                        lambda: {'allowed': True, 'next_allowed_at': '2026-09-12T00:00:00+00:00'})


def content():
    return {name: {"score": 2 if name == DIMENSIONS[0] else 0, "status": "scored",
                   "evidence": "订单显著增加" if name == DIMENSIONS[0] else ""}
            for name in DIMENSIONS}


def response(text=None):
    return {"model": "deepseek-flash", "usage": {"prompt_tokens": 100,
             "completion_tokens": 80, "total_tokens": 180},
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(content(), ensure_ascii=False) if text is None else text}}]}


class FakeClient:
    def __init__(self, responses=None):
        self.responses = responses or [response()]
        self.calls = 0

    def complete(self, reason, settings):
        self.calls += 1
        value = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.mark.parametrize("bad", ["", "```json\n{}\n```", "[]", '{"x":1,"x":2}',
                                 '{"x":NaN}'])
def test_rejects_bad_json(bad):
    with pytest.raises(ValueError):
        parse_score(bad, REASON)


@pytest.mark.parametrize("bad", [-1, 4, 2.0, True, "2"])
def test_strict_score_range(bad):
    data = content()
    data[DIMENSIONS[0]]["score"] = bad
    with pytest.raises(ValueError):
        parse_score(json.dumps(data), REASON)


def test_requires_exact_evidence_and_known_fields():
    data = content()
    data[DIMENSIONS[0]]["evidence"] = "不存在于原文"
    with pytest.raises(ValueError):
        parse_score(json.dumps(data), REASON)
    data = content()
    data["buy"] = True
    with pytest.raises(ValueError):
        parse_score(json.dumps(data), REASON)


def test_uncertainty_and_numeric_only_are_null():
    data = {name: {"score": None, "status": "numeric_only", "evidence": "净利润增长50%"}
            for name in DIMENSIONS}
    score = parse_score(json.dumps(data), "净利润增长50%")
    assert score.operating_improvement.score is None
    data[DIMENSIONS[0]]["score"] = 0
    with pytest.raises(ValueError):
        parse_score(json.dumps(data), "净利润增长50%")


def test_prompt_is_text_only_and_cache_changes_with_epoch():
    user_input = json.loads(messages(REASON)[1]["content"])
    assert set(user_input) == {"reason_text", "record_id"}
    assert user_input["reason_text"] == REASON and len(user_input["record_id"]) == 16
    settings = load_settings(CONFIG)
    assert score_key(REASON, settings) != score_key(REASON, {**settings, "model_epoch": "next"})


def test_old_rubric_is_not_silently_scored_with_new_prompt():
    with pytest.raises(ValueError, match='new rubric version'):
        load_design(ROOT / 'configs/factors/p7_text_evaluation_v1.toml')
    assert load_design(DESIGN)['scoring']['prompt_version'] == 'p7_reason_v2'


def test_success_reused_without_paying_again(tmp_path):
    settings = load_settings(CONFIG)
    client = FakeClient()
    cache = ScoreCache(tmp_path / "cache.sqlite")
    first = score_one(REASON, settings=settings, cache=cache, client=client,
                      max_requests=10, max_usd=1)
    cache.close()
    cache = ScoreCache(tmp_path / "cache.sqlite")
    second = score_one(REASON, settings=settings, cache=cache, client=client,
                       max_requests=10, max_usd=1)
    assert first["state"] == second["state"] == "success"
    assert client.calls == 1
    assert cache.totals()["requests"] == 1
    cache.close()


def test_crash_after_request_reservation_never_resubmits(tmp_path):
    settings = load_settings(CONFIG)
    cache = ScoreCache(tmp_path / "cache.sqlite")
    cache.reserve(score_key(REASON, settings), .01, max_requests=10, max_usd=1, max_attempts=2)
    cache.close()
    cache = ScoreCache(tmp_path / "cache.sqlite")
    client = FakeClient()
    result = score_one(REASON, settings=settings, cache=cache, client=client,
                       max_requests=10, max_usd=1)
    assert result["state"] == "unknown" and client.calls == 0
    assert cache.totals()["charged_or_reserved_usd"] == .01
    cache.close()


def test_invalid_json_retries_once_then_no_recharge_on_resume(tmp_path):
    cache = ScoreCache(tmp_path / "cache.sqlite")
    client = FakeClient([response("not JSON")])
    for _ in range(2):
        result = score_one(REASON, settings=load_settings(CONFIG), cache=cache, client=client,
                           max_requests=10, max_usd=1, sleep=lambda _: None)
        assert result["scores_json"] is None
    assert client.calls == 2
    assert cache.totals()["charged_or_reserved_usd"] > 0
    cache.close()


@pytest.mark.parametrize("requests,usd", [(0, 1), (10, .0000001)])
def test_budget_exhaustion_does_not_call(tmp_path, requests, usd):
    cache = ScoreCache(tmp_path / "cache.sqlite")
    client = FakeClient()
    result = score_one(REASON, settings=load_settings(CONFIG), cache=cache, client=client,
                       max_requests=requests, max_usd=usd)
    assert result["state"] == "budget_exhausted" and client.calls == 0
    cache.close()


def test_request_failure_no_neutral_value(tmp_path):
    cache = ScoreCache(tmp_path / "cache.sqlite")
    client = FakeClient([RequestFailure("transport_outcome_unknown")])
    result = score_one(REASON, settings=load_settings(CONFIG), cache=cache, client=client,
                       max_requests=10, max_usd=1)
    assert result["state"] == "failed" and result["scores_json"] is None
    assert client.calls == 1 and cache.totals()["charged_or_reserved_usd"] > 0
    cache.close()


def test_request_cap_survives_resumption_and_new_text(tmp_path):
    client = FakeClient()
    cache = ScoreCache(tmp_path / "cache.sqlite")
    score_one(REASON, settings=load_settings(CONFIG), cache=cache, client=client,
               max_requests=1, max_usd=1)
    cache.close()
    cache = ScoreCache(tmp_path / "cache.sqlite")
    result = score_one("另一条文本", settings=load_settings(CONFIG), cache=cache, client=client,
                       max_requests=1, max_usd=1)
    assert result["state"] == "budget_exhausted" and client.calls == 1
    cache.close()


@pytest.mark.parametrize("failure", ["missing_usage", "truncated"])
def test_bad_envelope_never_creates_scores(tmp_path, failure):
    envelope = response()
    if failure == "missing_usage":
        del envelope["usage"]
    else:
        envelope["choices"][0]["finish_reason"] = "length"
    cache = ScoreCache(tmp_path / "cache.sqlite")
    client = FakeClient([envelope])
    result = score_one(REASON, settings=load_settings(CONFIG), cache=cache, client=client,
                       max_requests=2, max_usd=1, sleep=lambda _: None)
    assert result["scores_json"] is None and client.calls <= 2
    cache.close()


def test_provider_usage_overrun_halts(tmp_path):
    envelope = response()
    envelope["usage"] = {"prompt_tokens": 999999, "completion_tokens": 80,
                         "total_tokens": 1000079}
    cache = ScoreCache(tmp_path / "cache.sqlite")
    with pytest.raises(RuntimeError, match="exceeded reservation"):
        score_one(REASON, settings=load_settings(CONFIG), cache=cache,
                   client=FakeClient([envelope]), max_requests=10, max_usd=1)
    assert cache.totals()["charged_or_reserved_usd"] > .2
    cache.close()


def test_http_contract_and_no_key_in_failure():
    def handle(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        data = json.loads(request.content)
        assert data["thinking"] == {"type": "disabled"}
        assert data["response_format"] == {"type": "json_object"}
        assert data["stream"] is False
        return httpx.Response(401, text="secret-key-should-not-leak")
    client = DeepSeekClient("secret-key-should-not-leak", transport=httpx.MockTransport(handle))
    with pytest.raises(RequestFailure, match="^http_401$"):
        client.complete(REASON, load_settings(CONFIG))
    client.close()


def test_project_local_key_only(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="configs/deepseek.local.toml"):
        load_key(tmp_path)


def corpus(path):
    pl.DataFrame({"ts_code": ["600001.SH"] * 4,
                  "publication_date": [dt.date(2020, 1, 1), dt.date(2020, 2, 1),
                                       dt.date(2020, 3, 1), dt.date(2020, 3, 1)],
                  "report_period": [dt.date(2020, 3, 31)] * 4,
                  "reason_text": [REASON, None, REASON, "不同原因"]}).write_parquet(path)


def test_batch_missing_conflicts_and_resume(tmp_path):
    source = tmp_path / "input.parquet"
    corpus(source)
    assert read_corpus(source)["same_day_conflict"].sum() == 2
    client = FakeClient()
    for n in range(2):
        result = run_batch(source=source, config=CONFIG, design_path=DESIGN,
                           output=tmp_path / str(n), cache_path=tmp_path / "cache.sqlite",
                           execute=True, max_requests=10, max_usd=1, client=client)
        assert result["summary"] == {"success": 1, "missing_text": 1, "same_day_conflict": 2}
    assert client.calls == 1 and result["requests_this_run"] == 0
    scores = pl.read_parquet(tmp_path / "1/scores.parquet")
    assert scores["text_operating_improvement"].to_list() == [2., None, None, None]


def test_dry_run_never_calls_provider(tmp_path):
    source = tmp_path / "input.parquet"
    corpus(source)
    client = FakeClient()
    report = run_batch(source=source, config=CONFIG, design_path=DESIGN, output=tmp_path / "dry",
                       cache_path=tmp_path / "cache.sqlite", client=client)
    assert report["dry_run"] and client.calls == 0
    assert not (tmp_path / "cache.sqlite").exists()
    assert report["plan"]["selected_unique_texts"] == 1


def test_panel_no_future_leak_missing_invalidation_and_expiry(tmp_path):
    source = tmp_path / "input.parquet"
    corpus(source)
    run_batch(source=source, config=CONFIG, design_path=DESIGN, output=tmp_path / "run",
              cache_path=tmp_path / "cache.sqlite", execute=True, max_requests=10,
              max_usd=1, client=FakeClient())
    scores = pl.read_parquet(tmp_path / "run/scores.parquet")
    sessions = [dt.date(2019, 12, 31), dt.date(2020, 1, 1), dt.date(2020, 2, 1),
                dt.date(2020, 3, 2)]
    panel = asof_panel(scores, sessions, max_age_days=120)
    assert panel["text_operating_improvement"].to_list() == [None, 2., None, None]
    old_only = asof_panel(scores.head(1), [dt.date(2020, 4, 29), dt.date(2020, 4, 30)],
                          max_age_days=120)
    assert old_only["text_operating_improvement"].to_list() == [2., None]


def test_publish_uses_battery_layout_and_rejects_dry_run(tmp_path, monkeypatch):
    source = tmp_path / "input.parquet"
    corpus(source)
    args = dict(source=source, config=CONFIG, design_path=DESIGN,
                cache_path=tmp_path / "cache.sqlite", client=FakeClient())
    run_batch(**args, output=tmp_path / "dry")
    with pytest.raises(ValueError, match="real validated"):
        publish_panels(tmp_path / "dry", data_root=tmp_path / "data", design=load_design(DESIGN))
    run_batch(**args, output=tmp_path / "live", execute=True, max_requests=2, max_usd=1)
    monkeypatch.setattr("quant.data.factor_panels.available_sessions",
                         lambda root, through: (dt.date(2020, 1, 2),))
    published = publish_panels(tmp_path / "live", data_root=tmp_path / "data", design=load_design(DESIGN))
    assert published["factors"] == 3
    panel = pl.read_parquet(tmp_path / "data/factors/text_operating_improvement/year=2020/data.parquet")
    assert panel.columns == ["trade_date", "ts_code", "value"]
    assert panel["value"].to_list() == [2.]
