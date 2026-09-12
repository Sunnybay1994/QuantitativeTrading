"""One bounded research cycle: scorecard diagnosis, DSL preparation, fixed search."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import tomllib
from typing import Any

from quant.research.deepseek_diagnostics import run_diagnosis
from quant.research.generate_factor_candidates import run as generate_candidates
from quant.research.run_factor_search import run as run_factor_search


def _configuration(config: Path) -> tuple[dict, dict]:
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    diagnosis, candidates, budget = (settings[name] for name in ("diagnosis", "candidates", "budget"))
    for name in ("scorecard", "config"):
        if not isinstance(diagnosis[name], str) or not Path(diagnosis[name]).is_file():
            raise ValueError(f"Invalid diagnosis {name} path")
    if (not isinstance(diagnosis["assessments"], list)
            or any(not isinstance(path, str) or not Path(path).is_file() for path in diagnosis["assessments"])):
        raise ValueError("Invalid model assessment paths")
    if (not isinstance(budget["cache"], str) or not budget["cache"].strip()
            or type(budget["max_requests"]) is not int or budget["max_requests"] < 0
            or type(budget["max_usd"]) not in (int, float) or not math.isfinite(budget["max_usd"]) or budget["max_usd"] < 0):
        raise ValueError("Invalid shared cumulative request/USD budget")
    design = tomllib.loads(Path(candidates["design"]).read_text(encoding="utf-8"))
    if "config" in candidates and (not isinstance(candidates["config"], str) or not Path(candidates["config"]).is_file()):
        raise ValueError("Invalid candidate scoring configuration path")
    search, dates = design["search"], design["dates"]
    if (not isinstance(candidates["scope"], str) or not 1 <= len(candidates["scope"].strip()) <= 2000
            or type(candidates["maximum_candidates"]) is not int
            or not 1 <= candidates["maximum_candidates"] <= min(50, search["maximum_candidates"])
            or type(candidates["maximum_history"]) is not int or not 1 <= candidates["maximum_history"] <= 1000):
        raise ValueError("Invalid bounded candidate scope")
    for name in ("fields", "operators"):
        values = candidates[name]
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or not set(values) <= set(search[name]):
            raise ValueError("Candidate whitelist must be within the selected design")
    if not candidates["fields"] or not (
        dates["start"] < dates["training_end"] < dates["validation_start"] <= dates["validation_end"]
        <= dates["panel_end"] < dates["forward_start"]):
        raise ValueError("Invalid frozen candidate dates or fields")
    return settings, design


def _check_batch(path: Path, *, candidate_root: Path, design: dict) -> None:
    batch = tomllib.loads(path.read_text(encoding="utf-8"))
    if batch.get("candidate_generation", {}).get("synthetic_fixture") is not False:
        raise ValueError("Only non-fixture generated batches may enter evaluation")
    if batch["dates"] != design["dates"]:
        raise ValueError("Generated batch changed frozen evaluation dates")
    for name in ("maximum_hours", "maximum_cost_attempts", "workers", "execution_snapshot"):
        if batch["search"][name] != design["search"][name]:
            raise ValueError("Generated batch changed the selected evaluation budget or snapshot")
    for name in ("library", "battery_config", "refresh_config"):
        if not Path(batch["search"][name]).resolve().is_relative_to(candidate_root.resolve()):
            raise ValueError("Generated batch must use its local registry and frozen evaluation inputs")


def run(*, config: Path, output: Path, execute: bool = False, development_test: bool = False) -> dict:
    """No same-directory resume; a new cycle reuses the configured cumulative cache.

    Candidate command strings are display-only. Evaluation is a direct call to
    the existing function using this cycle's fixed batch path.
    """
    settings, design = _configuration(config)
    budget, diagnosis, candidates = (settings[name] for name in ("budget", "diagnosis", "candidates"))
    if execute and (budget["max_requests"] < 1 or budget["max_usd"] <= 0):
        raise ValueError("Execution requires positive cumulative budget caps")
    if not output.resolve().is_relative_to(Path("artifacts").resolve()):
        raise ValueError("Research cycle outputs must stay under artifacts")
    output.mkdir(parents=True, exist_ok=False)
    (output / "cycle.toml").write_bytes(config.read_bytes())
    frozen_design = output / "design.toml"
    frozen_design.write_bytes(Path(candidates["design"]).read_bytes())
    frozen_scoring = output / "llm.toml"
    frozen_scoring.write_bytes(Path(diagnosis["config"]).read_bytes())
    frozen_candidate_scoring = output / "candidate_llm.toml"
    frozen_candidate_scoring.write_bytes(Path(candidates.get("config", diagnosis["config"])).read_bytes())
    paths = {name: output / name for name in ("diagnosis", "candidates", "evaluation")}
    result: dict[str, Any] = {"status": "running", "execute": execute, "development_test": development_test,
        "conclusion": "RESEARCH_ONLY", "stages": {name: {"path": str(path.resolve()), "status": "not_run"}
            for name, path in paths.items()},
        "budget": {**budget, "cache": str(Path(budget["cache"]).resolve()), "semantics": "same cumulative caps in both LLM stages"},
        "dates": {key: str(value) for key, value in design["dates"].items()},
        "cost_estimates": {"diagnosis_usd_bound_including_retries": None,
            "candidates_usd_bound_including_retries": None, "full_cycle_usd_bound": None,
            "scope": "Candidate input is unknown until diagnosis succeeds; null is unknown, not zero. Shared budget caps remain authoritative."},
        "resume": "No same-directory cycle resume. Use a new output with the same cache; successful model requests are reusable. Evaluation may be resumed directly with run_factor_search."}

    def save(status: str) -> dict:
        result["status"] = status
        (output / "run.json").write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    shared = {"config": frozen_scoring, "cache_path": Path(budget["cache"]).resolve(),
              "max_requests": budget["max_requests"], "max_usd": budget["max_usd"],
              "execute": execute, "development_test": development_test}
    stage = "diagnosis"
    try:
        result["stages"][stage]["status"] = "running"
        save("running")
        report = run_diagnosis(inputs=[], scorecard=Path(diagnosis["scorecard"]),
            assessments=[Path(path) for path in diagnosis["assessments"]], artifact_root=Path("artifacts"),
            output=paths[stage], **shared)
        result["stages"][stage].update(status=report["result"], result=report)
        result["cost_estimates"]["diagnosis_usd_bound_including_retries"] = report.get("usd_bound_including_retries")
        if not execute:
            result["stages"]["candidates"]["reason"] = "No real diagnosis in dry-run; no candidates manufactured"
            result["stages"]["evaluation"]["reason"] = "Requires accepted non-fixture candidates"
            return save("dry_run" if report["result"] == "dry_run" else "stopped")
        if report["result"] != "success":
            result["stopped_stage"] = stage
            return save("stopped")
        stage = "candidates"
        result["stages"][stage]["status"] = "running"
        save("running")
        report = generate_candidates(diagnosis=paths["diagnosis"], design=frozen_design,
            scope=candidates["scope"], fields=candidates["fields"], operators=candidates["operators"],
            maximum_candidates=candidates["maximum_candidates"], maximum_history=candidates["maximum_history"],
            output=paths[stage], **{**shared, "config": frozen_candidate_scoring})
        result["stages"][stage].update(status=report["result"], result=report)
        result["cost_estimates"]["candidates_usd_bound_including_retries"] = report.get("usd_bound_including_retries")
        if report["result"] != "success" or report["accepted_count"] < 1 or report.get("synthetic_fixture") is not False:
            result["stopped_stage"] = stage
            result["stages"]["evaluation"]["reason"] = "Requires successful generation with accepted non-fixture candidates"
            return save("stopped")
        batch = paths["candidates"] / "batch.toml"
        _check_batch(batch, candidate_root=paths["candidates"], design=design)
        stage = "evaluation"
        result["stages"][stage]["status"] = "running"
        save("running")
        # Never interpret or execute report['next_command'] or any model-provided command.
        report = run_factor_search(config=batch, output=paths["evaluation"])
        result["stages"][stage].update(status=report["message"], result=report)
        return save("completed" if report["message"] == "completed" else "stopped")
    except Exception as exc:
        result["stages"][stage].update(status="failed", error_type=type(exc).__name__, error=str(exc)[:1000])
        result["stopped_stage"] = stage
        return save("failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--development-test", action="store_true")
    try:
        result = run(**vars(parser.parse_args()))
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(json.dumps({"status": "invalid_input", "error_type": type(exc).__name__, "error": str(exc)[:1000]}))
        raise SystemExit(2) from None
    print(json.dumps({"status": result["status"], "stages": {
        name: value["status"] for name, value in result["stages"].items()}}))
    if result["status"] not in {"dry_run", "completed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
