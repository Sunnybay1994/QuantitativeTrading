import json
from pathlib import Path
import sys

import polars as pl
import pytest

from quant.research import deepseek_diagnostics as diagnostics
from quant.research.research_diagnostic_summary import build_research_summary

CONFIG = Path(__file__).resolve().parents[2] / "configs/research/deepseek_diagnosis_v1.toml"


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    rows = []
    for i in range(30):
        for variant in ("raw", "size_industry_neutral"):
            rows.append({"factor": f"factor_{i:02d}", "variant": variant, "direction": 1,
                "months": 100, "icir": .2, "newey_west_t": 2., "statistical_pass": i >= 20,
                "statistical_failures": ["hac_t"] if i < 20 else [],
                "costs_complete": None if i == 20 else True,
                "cost_excess_pass": i != 21, "redundancy_pass": None if i == 20 else i != 22,
                "factor_admitted": i >= 23, "conclusion": "RESEARCH_ONLY" if i >= 23 else "REJECTED",
                "cost_1_cagr": None if i == 20 else .05, "cost_2_cagr": .02,
                "cost_1_sharpe": .6, "cost_1_max_drawdown": -.3})
    scorecard = root / "factor_scorecard.parquet"
    pl.from_dicts(rows).write_parquet(scorecard)
    paths = []
    for i in range(3):
        path = root / f"model_{i}" / "assessment.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"large_unused_section": {str(n): n for n in range(1000)},
            "primary": {"conclusion": "REJECTED", "strongest_benchmark": "reference",
                "active_start": "2020-01-01", "active_years": 6., "net_cagr_excess": -.01 * (i + 1),
                "risk": {"first": "2017-01-01", "last": "2026-08-31", "cagr": .05 + i * .01,
                         "sharpe": .5, "max_drawdown": -.2},
                "checks": {"net_excess": False, "drawdown": True}},
            "sensitivity": {"conclusion": "PAPER_CANDIDATE"}}))
        paths.append(path)
    return dict(scorecard=scorecard, assessments=paths, artifact_root=root)


def test_full_counts_balanced_late_examples_and_every_model_primary(sources):
    result = build_research_summary(**sources)
    facts = result["facts"]
    assert facts["summary#/full_scorecard/rows"] == 60
    assert facts["summary#/full_scorecard/factors"] == 30
    assert facts["summary#/full_scorecard/raw/statistical_pass/false"] == 20
    assert facts["summary#/full_scorecard/raw/factor_admitted/true"] == 7
    assert facts["summary#/full_scorecard/raw/costs_complete/missing"] == 1
    assert facts["summary#/full_scorecard/raw/costs_complete/false"] == 0
    assert facts["summary#/full_scorecard/raw/failure_reasons/hac_t"] == 20
    selected = result["coverage"]["sampled_factors"]
    assert selected == ["factor_00", "factor_20", "factor_21", "factor_22", "factor_23"]
    assert result["coverage"]["sampled_variant_rows"] == 10
    for factor in selected:
        assert all(f"summary#/examples/{factor}/{variant}/icir" in facts for variant in ("raw", "size_industry_neutral"))
    for index in range(1, 4):
        assert facts[f"summary#/models/model{index}/primary/conclusion"] == "REJECTED"
        assert facts[f"summary#/models/model{index}/primary/risk/cagr"] == pytest.approx(.05 + (index - 1) * .01)
        assert result["sources"][index]["fact_count"] >= 14
    assert not any("sensitivity" in key or "large_unused" in key for key in facts)


def test_deterministic_order_and_original_row_provenance(sources):
    first = build_research_summary(**sources)
    original = pl.read_parquet(sources["scorecard"]).to_dicts()
    for pointer, origin in first["provenance"].items():
        if origin.get("source") == "source0" and "pointer" in origin:
            row_index, field = origin["pointer"].split("/")[2:]
            assert first["facts"][pointer] == original[int(row_index)][field]
    pl.from_dicts(original[::-1]).write_parquet(sources["scorecard"])
    second = build_research_summary(**{**sources, "assessments": sources["assessments"][::-1]})
    assert first["facts"] == second["facts"] and first["selection"] == second["selection"]
    assert first["sources"][0]["sha256"] != second["sources"][0]["sha256"]


def test_missing_metrics_and_nonfinite_remain_missing(sources):
    path = sources["scorecard"]
    pl.read_parquet(path).with_columns(pl.when(pl.col("factor") == "factor_00")
        .then(float("nan")).otherwise(pl.col("icir")).alias("icir")).drop("cost_2_cagr").write_parquet(path)
    result = build_research_summary(**sources)
    assert result["facts"]["summary#/full_scorecard/raw/missing_metrics/icir"] == 1
    assert result["facts"]["summary#/full_scorecard/raw/missing_metrics/cost_2_cagr"] == 30
    assert result["facts"]["summary#/examples/factor_00/raw/icir"] is None
    assert result["provenance"]["summary#/examples/factor_00/raw/cost_2_cagr"]["absent_column"] is True


def test_evidence_missing_also_includes_statistically_rejected_rows(sources):
    path = sources["scorecard"]
    table = pl.read_parquet(path).with_columns(pl.when(pl.col("factor") == "factor_01")
        .then(False).otherwise(pl.col("costs_complete")).alias("costs_complete"))
    table.write_parquet(path)
    result = build_research_summary(**sources)
    assert result["selection"]["evidence_missing"]["eligible_factors"] == 2
    assert result["selection"]["evidence_missing"]["selected"] == "factor_01"
    assert result["facts"]["summary#/examples/factor_01/raw/statistical_pass"] is False


@pytest.mark.parametrize("change", ["duplicate_row", "missing_variant", "status_type", "outside", "duplicate_model", "no_primary"])
def test_invalid_inputs_do_not_silently_reduce_coverage(sources, change):
    path = sources["scorecard"]
    table = pl.read_parquet(path)
    if change == "duplicate_row":
        pl.concat([table, table.head(1)]).write_parquet(path)
    elif change == "missing_variant":
        table.slice(1).write_parquet(path)
    elif change == "status_type":
        table.with_columns(pl.lit(1).alias("statistical_pass")).write_parquet(path)
    elif change == "outside":
        sources["artifact_root"] = path.parent / "other"
    elif change == "duplicate_model":
        sources["assessments"].append(sources["assessments"][0])
    else:
        sources["assessments"][0].write_text(json.dumps({"sensitivity": {"conclusion": "REJECTED"}}))
    with pytest.raises(ValueError):
        build_research_summary(**sources)


def test_raw_excerpt_budget_is_shared_and_no_source_starves(sources):
    facts, metadata = diagnostics.extract_facts(
        [sources["scorecard"], *sources["assessments"]], artifact_root=sources["artifact_root"])
    assert len(facts) <= 250
    assert [source["fact_allowance"] for source in metadata] == [63, 63, 62, 62]
    assert all(source["fact_count"] > 0 for source in metadata)
    assert all(any(key.startswith(f"source{i}#") for key in facts) for i in range(4))


def test_summary_run_reuses_schedule_budget_and_cache_without_real_provider(sources, monkeypatch, diagnosis_config):
    root = sources["artifact_root"]
    monkeypatch.setattr("quant.research.score_forecast_text.request_window",
        lambda: {"allowed": False, "next_allowed_at": "2026-09-14T04:00:00+00:00"})

    class Client:
        calls = 0

        def complete_messages(self, messages, settings):
            self.calls += 1
            facts = json.loads(messages[1]["content"])["facts"]
            key = "summary#/full_scorecard/rows"
            return {"model": "fixture", "usage": {"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"findings": [
                    {"claim": "评分表包含完整汇总", "evidence": [{"pointer": key, "value": facts[key]}]}], "candidates": []})}}]}

    client = Client()
    args = dict(inputs=[], **sources, config=diagnosis_config, cache_path=root / "cache.sqlite", client=client)
    dry = diagnostics.run_diagnosis(**args, output=root / "dry")
    assert dry["result"] == "dry_run" and not (root / "cache.sqlite").exists()
    assert dry["summary_coverage"]["assessments_included"] == 3
    deferred = diagnostics.run_diagnosis(**args, output=root / "peak", execute=True, max_requests=1, max_usd=.1)
    assert deferred["result"] == "deferred_off_peak" and client.calls == 0
    blocked = diagnostics.run_diagnosis(**args, output=root / "budget", execute=True,
        development_test=True, max_requests=1, max_usd=.000001)
    assert blocked["result"] == "budget_exhausted" and client.calls == 0
    for index in range(2):
        result = diagnostics.run_diagnosis(**args, output=root / f"success{index}", execute=True,
            development_test=True, max_requests=1, max_usd=.1)
        assert result["result"] == "success"
    assert client.calls == 1
    saved = json.loads((root / "dry/research_summary.json").read_text(encoding="utf-8"))
    assert saved["facts"] == json.loads((root / "dry/facts.json").read_text(encoding="utf-8"))
    assert set(saved["facts"]) == set(saved["provenance"])


def test_summary_cli_defaults_to_offline(sources, monkeypatch, capsys):
    root = sources["artifact_root"]
    monkeypatch.chdir(root.parent)
    monkeypatch.setattr(diagnostics, "load_key", lambda *args: pytest.fail("Dry run must not read a credential"))
    monkeypatch.setattr(sys, "argv", ["diagnosis", "--scorecard", str(sources["scorecard"]),
        "--assessment", *map(str, sources["assessments"]), "--config", str(CONFIG), "--output", str(root / "cli")])
    diagnostics.main()
    assert json.loads(capsys.readouterr().out)["result"] == "dry_run"


def test_oversized_summary_fails_before_output_without_dropping_models(sources):
    root = sources["artifact_root"]
    config = root / "small.toml"
    config.write_text(CONFIG.read_text(encoding="utf-8").replace("max_input_bytes = 60000", "max_input_bytes = 100"))
    with pytest.raises(ValueError, match="fewer/smaller"):
        diagnostics.run_diagnosis(inputs=[], **sources, config=config, output=root / "oversized",
                                  cache_path=root / "cache.sqlite")
    assert not (root / "oversized").exists() and not (root / "cache.sqlite").exists()
