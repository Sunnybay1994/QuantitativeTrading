"""One bounded research cycle: scorecard diagnosis, DSL preparation, fixed search."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import sqlite3
import json
import math
from pathlib import Path
import tomllib
from typing import Any

from quant.research.deepseek_diagnostics import parse_diagnosis, run_diagnosis
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


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths))}


def _inputs(config: Path, settings: dict, design: dict, return_benchmark_config: Path | None = None) -> dict[str, str]:
    d, c = settings["diagnosis"], settings["candidates"]
    paths = [config, Path(c["design"]), Path(d["config"]),
             Path(c.get("config", d["config"])), Path(d["scorecard"]),
             *map(Path, d["assessments"])]
    for name in ("battery_config", "refresh_config"):
        if name in design["search"]:
            paths.append(Path(design["search"][name]))
    if "library" in design["search"]:
        paths.extend(Path(design["search"]["library"]).rglob("*.toml"))
    if return_benchmark_config is not None:
        paths.append(return_benchmark_config)
    return _hashes(paths)


def _cache_totals(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("Resume requires the original shared cache; never create a replacement")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT COUNT(*), COALESCE(SUM(charged_usd),0) FROM attempts").fetchone()
    return {"requests": row[0], "charged_or_reserved_usd": row[1]}


def _archive_partial(path: Path) -> None:
    if path.exists():
        number = 1
        target = path.with_name(f"{path.name}_partial_{number:03d}")
        while target.exists():
            number += 1
            target = path.with_name(f"{path.name}_partial_{number:03d}")
        if not path.resolve().is_relative_to(path.parent.resolve()) or not target.resolve().is_relative_to(path.parent.resolve()):
            raise ValueError("Partial stage must remain inside the cycle directory")
        path.rename(target)


def _stage_files(path: Path, name: str) -> list[Path]:
    if name != "evaluation":
        return [p for p in path.rglob("*") if p.is_file()]
    # Large factor panels are owned by the search's existing recovery mechanism.
    return [*path.rglob("*summary.json"), *path.rglob("scorecard.parquet"),
            *path.glob("*.toml"), *path.glob("trials.json")]


def _validate_saved(path: Path, name: str, report: dict) -> None:
    filename = "summary.json" if name == "evaluation" else "run.json"
    saved = json.loads((path / filename).read_text(encoding="utf-8"))
    if saved != json.loads(json.dumps(report, default=str)):
        raise ValueError(f"Saved {name} report differs from cycle result")
    if name == "diagnosis":
        parse_diagnosis((path / "diagnosis.json").read_text(encoding="utf-8"),
                        json.loads((path / "facts.json").read_text(encoding="utf-8")))
    elif name == "candidates":
        request = json.loads((path / "frozen_request.json").read_text(encoding="utf-8"))
        if report.get("synthetic_fixture") is not False or request["synthetic_fixture"] is not False:
            raise ValueError("Synthetic candidates cannot be resumed into evaluation")
        batch = path / "batch.toml"
        if (path / "prepared/search.toml").read_bytes() != batch.read_bytes():
            raise ValueError("Prepared candidates differ from the generated batch")
        trials = json.loads((path / "prepared/trials.json").read_text(encoding="utf-8"))
        if trials["registered_count"] != report["accepted_count"] or report["accepted_count"] < 1:
            raise ValueError("Missing prepared candidates")
        for factor in trials["factors"]:
            if (path / "registry" / f"{factor}.toml").read_bytes() != (
                    path / "prepared/library" / f"{factor}.toml").read_bytes():
                raise ValueError("Prepared candidate library mismatch")
        payload = json.loads((path / "candidates.json").read_text(encoding="utf-8"))
        if not payload["candidates"]:
            raise ValueError("Missing generated candidate payload")
    else:
        if saved.get("message") != "completed" or not saved.get("completed_stages"):
            raise ValueError("Missing completed evaluation evidence")
        for stage in saved["completed_stages"]:
            if stage == "costs":
                if not list((path / "costs").glob("attempt_*/batch_summary.json")):
                    raise ValueError("Missing cost summaries")
            else:
                json.loads((path / stage / "summary.json").read_text(encoding="utf-8"))


def run(*, config: Path, output: Path, execute: bool = False, development_test: bool = False,
        resume: bool = False, return_benchmark_config: Path | None = None) -> dict:
    """Explicit recovery uses unchanged inputs and the original cumulative cache.

    Candidate command strings are display-only. Evaluation is a direct call to
    the existing function using this cycle's fixed batch path.
    """
    settings, design = _configuration(config)
    budget, diagnosis, candidates = (settings[name] for name in ("budget", "diagnosis", "candidates"))
    if execute and (budget["max_requests"] < 1 or budget["max_usd"] <= 0):
        raise ValueError("Execution requires positive cumulative budget caps")
    if not output.resolve().is_relative_to(Path("artifacts").resolve()):
        raise ValueError("Research cycle outputs must stay under artifacts")
    current_inputs = _inputs(config, settings, design, return_benchmark_config)
    return_bytes = return_benchmark_config.read_bytes() if return_benchmark_config is not None else None
    if return_bytes is not None:
        tomllib.loads(return_bytes.decode('utf-8'))['benchmarks']
    frozen_design, frozen_scoring = output / "design.toml", output / "llm.toml"
    frozen_candidate_scoring = output / "candidate_llm.toml"
    paths = {name: output / name for name in ("diagnosis", "candidates", "evaluation")}
    result: dict[str, Any] = {"status": "running", "execute": execute, "development_test": development_test,
        "conclusion": "RESEARCH_ONLY", "stages": {name: {"path": str(path.resolve()), "status": "not_run"}
            for name, path in paths.items()},
        "budget": {**budget, "cache": str(Path(budget["cache"]).resolve()), "semantics": "same cumulative caps in both LLM stages"},
        "dates": {key: str(value) for key, value in design["dates"].items()},
        "cost_estimates": {"diagnosis_usd_bound_including_retries": None,
            "candidates_usd_bound_including_retries": None, "full_cycle_usd_bound": None,
            "scope": "Candidate input is unknown until diagnosis succeeds; null is unknown, not zero. Shared budget caps remain authoritative."},
        "resume": "Use --resume with unchanged config, inputs and shared cumulative cache"}

    if resume:
        result = json.loads((output / "run.json").read_text(encoding="utf-8"))
        if result.get("input_hashes") != current_inputs:
            raise ValueError("Changed or unfrozen cycle inputs; refusing resume")
        if result["execute"] != execute:
            raise ValueError("Resume must preserve --execute mode")
        frozen = {output / "cycle.toml": config, frozen_design: Path(candidates["design"]),
                  frozen_scoring: Path(diagnosis["config"]), frozen_candidate_scoring:
                  Path(candidates.get("config", diagnosis["config"]))}
        if any(a.read_bytes() != b.read_bytes() for a, b in frozen.items()):
            raise ValueError("Frozen configuration changed")
        if result["budget"]["cache"] != str(Path(budget["cache"]).resolve()):
            raise ValueError("Shared cache changed")
        if execute:
            totals = _cache_totals(Path(budget["cache"]))
            floor = result.get("cache_totals", {})
            if any(totals[k] < v for k, v in floor.items()):
                raise ValueError("Shared cumulative cache usage moved backwards")
        for name, value in result["stages"].items():
            saved = value.get("output_hashes")
            if saved is not None and saved != _hashes(_stage_files(paths[name], name)):
                raise ValueError(f"Saved {name} outputs changed or are missing")
        candidate_report = paths["candidates"] / "run.json"
        if candidate_report.is_file() and json.loads(candidate_report.read_text(encoding="utf-8")).get("synthetic_fixture") is True:
            raise ValueError("Synthetic candidates cannot be resumed")
        for name, value in result["stages"].items():
            if value.get("output_hashes"):
                _validate_saved(paths[name], name, value["result"])
        # Validate local candidate safety even if the outer cycle says completed.
        if result["stages"]["candidates"].get("output_hashes"):
            _check_batch(paths["candidates"] / "batch.toml",
                         candidate_root=paths["candidates"], design=design)
    else:
        output.mkdir(parents=True, exist_ok=False)
        for target, source in ((output / "cycle.toml", config),
                               (frozen_design, Path(candidates["design"])),
                               (frozen_scoring, Path(diagnosis["config"])),
                               (frozen_candidate_scoring, Path(candidates.get("config", diagnosis["config"])))):
            target.write_bytes(source.read_bytes())
        result["input_hashes"] = current_inputs

    def save(status: str) -> dict:
        result["status"] = status
        if execute and Path(budget["cache"]).is_file():
            result["cache_totals"] = _cache_totals(Path(budget["cache"]))
        temporary = output / "run.tmp.json"
        temporary.write_text(json.dumps(result, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output / "run.json")
        return result

    def reuse(name: str) -> dict | None:
        value = result["stages"][name]
        if resume and value.get("output_hashes"):
            return value["result"]
        return None

    def record(name: str, report: dict) -> None:
        if _inputs(config, settings, design, return_benchmark_config) != current_inputs:
            raise ValueError("Cycle inputs changed during execution")
        _validate_saved(paths[name], name, report)
        files = _stage_files(paths[name], name)
        if not files:
            raise ValueError(f"No saved {name} artifacts")
        result["stages"][name]["output_hashes"] = _hashes(files)

    shared = {"config": frozen_scoring, "cache_path": Path(budget["cache"]).resolve(),
              "max_requests": budget["max_requests"], "max_usd": budget["max_usd"],
              "execute": execute, "development_test": development_test}
    stage = "diagnosis"
    try:
        result["stages"][stage]["status"] = "running"
        save("running")
        report = reuse(stage)
        if report is None:
            if resume:
                _archive_partial(paths[stage])
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
        record(stage, report)
        stage = "candidates"
        result["stages"][stage]["status"] = "running"
        save("running")
        report = reuse(stage)
        if report is None:
            if resume:
                _archive_partial(paths[stage])
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
        record(stage, report)
        stage = "evaluation"
        result["stages"][stage]["status"] = "running"
        save("running")
        # Never interpret or execute report['next_command'] or any model-provided command.
        report = reuse(stage)
        if report is None:
            if return_bytes is not None:
                frozen_returns = output/'return_benchmarks.toml'
                frozen_returns.write_bytes(return_bytes)
                report = run_factor_search(config=batch, output=paths["evaluation"],
                                           return_benchmark_config=frozen_returns)
            else:
                report = run_factor_search(config=batch, output=paths["evaluation"])
        result["stages"][stage].update(status=report["message"], result=report)
        if report["message"] == "completed":
            record(stage, report)
        return save("completed" if report["message"] == "completed" else "stopped")
    except Exception as exc:
        result["stages"][stage].update(status="failed", error_type=type(exc).__name__, error=str(exc)[:1000])
        result["stopped_stage"] = stage
        return save("failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--development-test", action="store_true")
    parser.add_argument('--return-benchmark-config', type=Path)
    try:
        result = run(**vars(parser.parse_args()))
    except (ValueError, KeyError, OSError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "invalid_input", "error_type": type(exc).__name__, "error": str(exc)[:1000]}))
        raise SystemExit(2) from None
    print(json.dumps({"status": result["status"], "stages": {
        name: value["status"] for name, value in result["stages"].items()}}))
    if result["status"] not in {"dry_run", "completed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
